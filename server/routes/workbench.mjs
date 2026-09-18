import { PersistentRunner } from '../persistent_runner.mjs';
import { json, readBody } from '../http-utils.mjs';
import { marketStreamService } from '../market-stream-service.mjs';
import { WorkbenchSlowCache } from '../workbench-cache.mjs';
import { riskLevel } from '../risk-summary.mjs';
import { loadShadowResearchStatus } from '../../lib/shadow-research-status.mjs';

const riskRunner = new PersistentRunner('risk_runner.py');
const alertRunner = new PersistentRunner('alert_runner.py');
const paperRunner = new PersistentRunner('paper_runner.py');
const f5PaperRunner = new PersistentRunner('f5_paper_runner.py');
const strategyRunner = new PersistentRunner('strategy_runner.py');

function normalizedSentiment(context) {
  const value = context?.sentiment;
  if (!value || typeof value !== 'object') return null;
  const rawScore = Number(value.sentiment_score);
  const rawConfidence = Number(value.confidence);
  const score = Number.isFinite(rawScore) ? Math.max(0, Math.min(100, rawScore)) : null;
  const confidence = Number.isFinite(rawConfidence) ? Math.max(0, Math.min(1, rawConfidence)) : null;
  const official = new Set(['cboe', 'hkex', 'fred']);
  const sources = (value.sources || [])
    .filter((source) => official.has(String(source?.source || '').toLowerCase()) && ['live', 'stale'].includes(source?.status))
    .map((source) => ({ source: source.source, status: source.status, official: true }));
  const regime = score === null ? 'unknown' : score >= 80 ? 'extreme_greed' : score >= 60 ? 'positive' : score >= 40 ? 'neutral' : score >= 20 ? 'fear' : 'extreme_fear';
  return { sentiment_score: score, sentiment_regime: regime, confidence, sources, stale: sources.some((source) => source.status === 'stale') };
}

function dataOf(result) {
  if (!result || result.success === false) return null;
  return result.data ?? result;
}

let slowCache = null;

function getSlowCache() {
  if (!slowCache) {
    slowCache = new WorkbenchSlowCache({
      healthLoader: async () => dataOf(await riskRunner.call({ action: 'system_health' }, 12_000)),
      targetLoader: async () => dataOf(await strategyRunner.call({ action: 'research_selection' }, 12_000)),
      contextLoader: async () => dataOf(await paperRunner.call({ action: 'global_context_status' }, 12_000)),
      paperStatusLoader: async () => dataOf(await f5PaperRunner.call({ action: 'status' }, 12_000)),
      alertsLoader: async () => dataOf(await alertRunner.call({ action: 'stats' }, 12_000)),
      shadowResearchLoader: async () => loadShadowResearchStatus(),
    });
    slowCache.start();
  }
  return slowCache;
}

export function stopWorkbenchCache() {
  slowCache?.stop();
  slowCache = null;
}

function normalizedTargetPortfolio(value) {
  if (!value || typeof value !== 'object'
      || value.promotion_state !== 'research_only'
      || value.execution_authority !== false) return null;
  const positions = (Array.isArray(value.positions) ? value.positions : [])
    .filter((row) => row && typeof row === 'object' && String(row.code || '').trim())
    .map((row) => ({
      code: String(row.code || ''),
      name: String(row.name || ''),
      target_weight: Number.isFinite(Number(row.target_weight)) ? Number(row.target_weight) : null,
      research_reason: String(row.research_reason || ''),
    }));
  return {
    selection_date: String(value.selection_date || ''),
    selection_status: String(value.selection_status || ''),
    portfolio_id: String(value.portfolio_id || ''),
    f4_validation_id: String(value.f4_validation_id || ''),
    positions,
    position_count: positions.length,
    promotion_state: 'research_only',
    execution_authority: false,
    not_a_trade_signal: value.not_a_trade_signal === true,
    is_current: value.is_current !== false,
    expected_latest_date: String(value.expected_latest_date || ''),
    freshness_warning: String(value.freshness_warning || ''),
    research_refresh: value.research_refresh || null,
  };
}

export function composeWorkbenchStatus(input = {}) {
  const activeLedger = input.activeLedger || {};
  const account = activeLedger.account || activeLedger.status || null;
  const risk = input.risk || null;
  const alerts = input.alerts || null;
  const level = riskLevel(risk, alerts);
  const paperStatus = input.paperStatus || {};
  const currentReadiness = paperStatus.current_readiness || {};
  const executionLane = currentReadiness.execution_lane
    || paperStatus.execution_lane
    || paperStatus.latest_run?.execution_lane
    || 'inactive';
  const intradaySimulationEnabled = Boolean(
    paperStatus.enabled
      && !paperStatus.kill_switch
      && (
        paperStatus.execution_mode === 'paper_intraday'
        || ['experimental_paper', 'validated_paper'].includes(executionLane)
      ),
  );
  const paperAuthority = Boolean(
    intradaySimulationEnabled && paperStatus.paper_execution_authority,
  );
  const executionReason = currentReadiness.reason_code
    || paperStatus.reason_code
    || paperStatus.latest_run?.status
    || (intradaySimulationEnabled ? 'intraday_schedule_ready' : 'automatic_execution_disabled');
  return {
    as_of: new Date().toISOString(),
    ledger_authority: activeLedger.ledger_authority || 'unavailable',
    ledger: activeLedger.ledger || null,
    account,
    positions: activeLedger.positions || [],
    performance: {
      total_return_pct: account?.total_pnl_pct ?? null,
      series: Array.isArray(activeLedger.equity_history) ? activeLedger.equity_history : [],
      source: 'f5_ledger',
    },
    risk: risk ? {
      ...risk,
      level,
      state: level === 'high' ? 'error' : level === 'medium' ? 'warn' : 'ok',
      source: 'risk_runner',
    } : null,
    overall_risk: {
      level,
      state: level === 'unknown' ? 'unknown' : 'ready',
      source: 'deterministic_risk_summary',
    },
    alerts,
    sentiment: normalizedSentiment(input.globalContext),
    services: { overall: input.health?.overall || 'unknown', layers: input.health || null },
    automatic_execution: {
      enabled: intradaySimulationEnabled,
      reason: executionReason,
      label: intradaySimulationEnabled ? '盘中自动模拟交易已启用' : '盘中自动模拟交易未启用',
    },
    trade_permission: {
      allowed: paperAuthority,
      state: paperAuthority ? 'ready' : 'blocked',
      reason: executionReason,
      scope: intradaySimulationEnabled
        ? (executionLane === 'inactive' ? 'experimental_paper' : executionLane)
        : 'read_only_ledger',
      live_execution_authority: false,
    },
    target_portfolio: normalizedTargetPortfolio(input.targetPortfolio),
    shadow_research: input.shadowResearch || null,
    freshness: { state: 'current', as_of: new Date().toISOString() },
  };
}

function riskMatchesActiveLedger(activeLedger, risk) {
  const account = activeLedger?.account || {};
  const accountSnapshot = String(account.market_snapshot_id || '');
  const riskSnapshot = String(risk?.market_snapshot_id || '');
  if (accountSnapshot && riskSnapshot && accountSnapshot === riskSnapshot) return true;

  const accountEquity = Number(account.total_equity);
  const riskEquity = Number(risk?.total_equity);
  const accountPositions = Number(
    account.position_count ?? (Array.isArray(activeLedger?.positions) ? activeLedger.positions.length : NaN),
  );
  const riskPositions = Number(risk?.position_count);
  const accountTime = Date.parse(String(account.valuation_as_of || account.updated_at || ''));
  const riskTime = Date.parse(String(risk?.calculated_at || risk?.valuation_as_of || ''));
  const relativeEquityDrift = Number.isFinite(accountEquity) && Number.isFinite(riskEquity)
    ? Math.abs(accountEquity - riskEquity) / Math.max(Math.abs(accountEquity), 1)
    : Number.POSITIVE_INFINITY;
  return activeLedger?.ledger_authority === 'f5'
    && risk?.ledger_authority === 'f5'
    && String(activeLedger?.ledger || '') === String(risk?.ledger || '')
    && Number.isFinite(accountPositions)
    && accountPositions === riskPositions
    && relativeEquityDrift <= 0.001
    && Number.isFinite(accountTime)
    && Number.isFinite(riskTime)
    && Math.abs(accountTime - riskTime) <= 15_000;
}

export function composeFastWorkbenchStatus(input = {}) {
  const activeLedger = input.activeLedger || {};
  const accountSnapshot = String(activeLedger.account?.market_snapshot_id || '');
  const consistent = riskMatchesActiveLedger(activeLedger, input.risk);
  const slow = input.slow || {};
  const state = composeWorkbenchStatus({
    activeLedger,
    risk: consistent ? input.risk : null,
    health: slow.health,
    alerts: slow.alerts,
    globalContext: slow.globalContext,
    paperStatus: slow.paperStatus,
    targetPortfolio: slow.targetPortfolio,
    shadowResearch: slow.shadowResearch,
  });
  state.services = {
    overall: slow.health?.overall || (slow.meta?.health?.refreshing ? 'refreshing' : 'unknown'),
    layers: slow.health || null,
    meta: slow.meta || {},
  };
  state.freshness = {
    state: consistent ? 'current' : 'inconsistent',
    as_of: new Date().toISOString(),
    market_snapshot_id: accountSnapshot || null,
    quote_timestamp: activeLedger.account?.quote_timestamp || null,
    valuation_as_of: activeLedger.account?.valuation_as_of || null,
    risk_calculated_at: consistent ? input.risk?.calculated_at || null : null,
    consistent,
  };
  return state;
}

export async function handleWorkbench(req, res) {
  const body = await readBody(req);
  if ((body.action || 'status') !== 'status') {
    return json(res, 400, { success: false, error: 'unsupported workbench action' });
  }
  const slow = getSlowCache().snapshot();
  if (!slow.shadowResearch) {
    slow.shadowResearch = loadShadowResearchStatus();
  }
  const streamed = marketStreamService.cockpitSnapshot();
  let activeLedger = streamed?.activeLedger || null;
  let risk = streamed?.risk || null;
  if (!activeLedger || !risk) {
    const settled = await Promise.allSettled([
      f5PaperRunner.call({ action: 'account' }, 5_000),
      riskRunner.call({ action: 'portfolio_risk' }, 5_000),
    ]);
    activeLedger = settled[0].status === 'fulfilled' ? dataOf(settled[0].value) : null;
    risk = settled[1].status === 'fulfilled' ? dataOf(settled[1].value) : null;
  }
  return json(res, 200, {
    success: true,
    data: composeFastWorkbenchStatus({ activeLedger, risk, slow }),
  });
}

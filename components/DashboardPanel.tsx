import React, { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Database, FlaskConical, Layers3, RefreshCw, ShieldCheck, WalletCards } from 'lucide-react';
import { workbenchRequest } from '../lib/workbench-state.mjs';
import { useMarketStream } from '../hooks/useMarketStream';

const money = (value: unknown) => value === null || value === undefined || value === ''
  ? '--'
  : Number.isFinite(Number(value))
  ? Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  : '--';

const percent = (value: unknown) => Number.isFinite(Number(value))
  ? `${(Number(value) * 100).toFixed(1)}%`
  : '--';

const REASON_FACTOR_LABELS: Record<string, string> = {
  '-volatility_20': '低20日波动率',
  '-volatility_60': '低60日波动率',
  trend_strength: '趋势强度',
  ret_20: '20日收益率',
};

const localizedReason = (value: unknown) => Object.entries(REASON_FACTOR_LABELS)
  .reduce((text, [factor, label]) => text.replaceAll(factor, label), String(value || ''));

const displayTime = (value: unknown) => {
  const text = String(value || '');
  if (/^\d{14}$/.test(text)) return `${text.slice(8, 10)}:${text.slice(10, 12)}:${text.slice(12, 14)}`;
  const parsed = Date.parse(text);
  return Number.isFinite(parsed) ? new Date(parsed).toLocaleTimeString('zh-CN', { hour12: false }) : '--';
};

const displayDateTime = (value: unknown) => {
  const parsed = Date.parse(String(value || ''));
  return Number.isFinite(parsed) ? new Date(parsed).toLocaleString('zh-CN', { hour12: false }) : '--';
};

const SHADOW_STATUS_LABELS: Record<string, string> = {
  baseline_missing: '缺少 baseline 结果',
  runtime_summary_missing: '缺少运行摘要',
  shadow_ai_raw_output_missing: '缺少 AI 原始输出',
  shadow_cycle_report_missing: '缺少对照报告',
  shadow_cycle_failed: '影子对照失败',
  shadow_recorded: '影子记录已生成',
};

const shadowStageState = (value: any) => value?.exists || value?.report_exists ? '已生成' : '缺失';

const DashboardPanel: React.FC = () => {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setData(await workbenchRequest({ action: 'status' }));
      setError('');
    } catch (reason: any) {
      setError(reason?.message || '驾驶舱数据读取失败');
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    const timer = setInterval(refresh, 30_000);
    return () => clearInterval(timer);
  }, [refresh]);
  const onCockpitMark = useCallback((event: any) => {
    if (event.type !== 'cockpit_mark') return;
    const mark = event.data || {};
    setData((previous: any) => ({
      ...(previous || {}),
      ledger_authority: mark.activeLedger?.ledger_authority || previous?.ledger_authority,
      ledger: mark.activeLedger?.ledger || previous?.ledger,
      account: mark.account || mark.activeLedger?.account || previous?.account,
      positions: mark.positions || mark.activeLedger?.positions || previous?.positions || [],
      risk: mark.risk || previous?.risk,
      overall_risk: mark.overall_risk || previous?.overall_risk,
      freshness: {
        state: 'current',
        market_snapshot_id: mark.market_snapshot_id || mark.account?.market_snapshot_id || null,
        quote_timestamp: mark.quote_timestamp || mark.account?.quote_timestamp || null,
        valuation_as_of: mark.account?.valuation_as_of || null,
        risk_calculated_at: mark.risk?.calculated_at || null,
        market_phase: mark.market_phase || 'unknown',
        consistent: Boolean(
          (mark.account?.market_snapshot_id || mark.market_snapshot_id)
          && mark.risk?.market_snapshot_id
          && (mark.account?.market_snapshot_id || mark.market_snapshot_id) === mark.risk.market_snapshot_id
        ),
      },
    }));
  }, []);
  const cockpitStream = useMarketStream({
    channels: ['cockpit_mark'],
    codes: [],
    enabled: true,
    onEvent: onCockpitMark,
    fallback: refresh,
    fallbackIntervalMs: 2000,
  });
  const account = data?.account || {};
  const risk = data?.overall_risk || {};
  const sentiment = data?.sentiment;
  const rawSentimentScore = sentiment?.sentiment_score;
  const sentimentScore = typeof rawSentimentScore === 'number' && Number.isFinite(rawSentimentScore)
    ? Math.max(0, Math.min(100, rawSentimentScore)) : null;
  const rawSentimentConfidence = sentiment?.confidence;
  const sentimentConfidence = typeof rawSentimentConfidence === 'number' && Number.isFinite(rawSentimentConfidence)
    ? Math.max(0, Math.min(1, rawSentimentConfidence)) : null;
  const sentimentLabel = sentimentScore === null ? '暂无可用数据' : sentimentScore >= 80 ? '过热' : sentimentScore >= 60 ? '积极' : sentimentScore >= 40 ? '中性' : sentimentScore >= 20 ? '谨慎' : '极度谨慎';
  const sentimentSources = (sentiment?.sources || []).filter((source: any) => source?.official === true && (source?.status === 'live' || source?.status === 'stale'));
  const automaticExecution = data?.automatic_execution || {};
  const tradePermission = data?.trade_permission || {};
  const shadowResearch = data?.shadow_research || {};
  const targetPortfolio = data?.target_portfolio;
  const targetPositions = Array.isArray(targetPortfolio?.positions)
    ? targetPortfolio.positions : [];
  const targetStatus = targetPortfolio?.selection_status === 'experimental_research_portfolio'
    ? '实验研究组合'
    : targetPortfolio?.selection_status === 'f4_research_portfolio'
      ? 'F4 研究组合'
      : targetPortfolio?.selection_status === 'diagnostic_research_portfolio'
        ? '诊断研究组合'
      : '研究组合';
  const freshness = data?.freshness || {};
  const valuationMs = Date.parse(String(freshness.valuation_as_of || ''));
  const freshnessAgeMs = Number.isFinite(valuationMs) ? Math.max(0, Date.now() - valuationMs) : Number.POSITIVE_INFINITY;
  const marketClosed = freshness.market_phase === 'closed' || freshness.market_phase === 'midday_break';
  const freshnessState = marketClosed
    ? '休市'
    : cockpitStream.status === 'degraded'
      ? '降级'
      : freshnessAgeMs <= 3_000 && freshness.consistent !== false
        ? '实时'
        : freshnessAgeMs <= 15_000
          ? '延迟'
          : '不可用';
  const freshnessColor = freshnessState === '实时' ? '#4ADE80' : freshnessState === '休市' ? '#94A3B8' : freshnessState === '延迟' ? '#FBBF24' : '#F87171';
  return (
    <div className="cockpit">
      <style>{`
        .cockpit{display:flex;flex-direction:column;gap:14px}.cockpit header{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.cockpit h1{margin:0;color:#f8fafc;font-size:var(--font-page-title)}.cockpit p{margin:5px 0 0;color:#64748b}.cockpit-button{display:flex;align-items:center;gap:6px;min-width:92px;min-height:36px;padding:0 12px;border:1px solid #334155;border-radius:6px;color:#cbd5e1;background:#111827;cursor:pointer;white-space:nowrap}.cockpit-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.cockpit-card{padding:16px;border:1px solid #1e293b;border-radius:8px;background:#111827}.cockpit-card span{display:flex;align-items:center;gap:7px;color:#94a3b8;font-size:var(--font-meta)}.cockpit-card strong{display:block;margin-top:14px;color:#f8fafc;font:700 var(--font-kpi)/1.1 Consolas,monospace}.cockpit-notice{padding:14px;border:1px solid #92400e;border-radius:8px;color:#fcd34d;background:#1c1917}.cockpit-error{color:#fca5a5}.sentiment-block,.target-portfolio,.shadow-research{padding:14px;border:1px solid #1e293b;border-radius:8px;background:#111827;color:#cbd5e1}.sentiment-block small{display:block;margin-top:6px;color:#64748b}.shadow-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;margin-top:12px}.shadow-cell{padding:10px;border:1px solid #263449;border-radius:7px;background:#0b1220}.shadow-cell span{display:block;color:#64748b;font-size:11px}.shadow-cell strong{display:block;margin-top:6px;color:#e2e8f0;font-size:12px}.shadow-meta{margin-top:10px;color:#64748b;font-size:12px;line-height:1.6}.target-title{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:10px}.target-title strong{display:flex;align-items:center;gap:7px;color:#f8fafc}.target-title small,.target-note{color:#64748b}.target-scroll{overflow-x:auto}.target-table{width:100%;border-collapse:collapse;font-size:13px}.target-table th,.target-table td{padding:9px 10px;border-top:1px solid #1e293b;text-align:left;vertical-align:top}.target-table th{color:#64748b;font-weight:500}.target-table td{color:#cbd5e1}.target-table td:nth-child(1),.target-table td:nth-child(3){font-family:Consolas,monospace;white-space:nowrap}.target-reason{min-width:280px;color:#94a3b8!important}.target-empty{padding:10px 0;color:#64748b}@media(max-width:1100px){.shadow-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:800px){.cockpit-grid{grid-template-columns:repeat(2,1fr)}.cockpit-card strong{font-size:var(--font-kpi-mobile)}.target-title{flex-direction:column}.target-reason{min-width:220px}}
      `}</style>
      <header><div><h1>投资驾驶舱</h1><p>数据、确定性风控与统一 F5 模拟账本概览</p></div><button className="cockpit-button" onClick={refresh}><RefreshCw size={14} className={loading ? 'spin' : ''}/>刷新</button></header>
      <section className="cockpit-grid">
        <div className="cockpit-card"><span><WalletCards size={14}/>总权益</span><strong>¥{money(account.total_equity)}</strong></div>
        <div className="cockpit-card"><span><WalletCards size={14}/>今日盈亏</span><strong>¥{money(account.daily_pnl)}</strong></div>
        <div className="cockpit-card"><span><ShieldCheck size={14}/>综合风险</span><strong>{risk.level === 'low' ? '低' : risk.level === 'medium' ? '中' : risk.level === 'high' ? '高' : '未知'}</strong></div>
        <div className="cockpit-card"><span><Database size={14}/>持仓数量</span><strong>{Array.isArray(data?.positions) ? data.positions.length : '--'}</strong></div>
      </section>
      <section className="cockpit-card" style={{ display: 'grid', gridTemplateColumns: 'repeat(4,minmax(0,1fr))', gap: 12 }}>
        <div><span>行情时间</span><strong style={{ fontSize: 16 }}>{displayTime(freshness.quote_timestamp || account.quote_timestamp)}</strong></div>
        <div><span>权益估值时间</span><strong style={{ fontSize: 16 }}>{displayTime(freshness.valuation_as_of || account.valuation_as_of)}</strong></div>
        <div><span>风险计算时间</span><strong style={{ fontSize: 16 }}>{displayTime(freshness.risk_calculated_at || data?.risk?.calculated_at)}</strong></div>
        <div><span>数据状态</span><strong style={{ fontSize: 16, color: freshnessColor }}>{freshnessState}</strong></div>
      </section>
      <div className="cockpit-notice"><AlertTriangle size={15} style={{ verticalAlign: 'middle', marginRight: 8 }}/>{automaticExecution.enabled
        ? `盘中自动模拟交易已启用；${tradePermission.allowed ? '本轮模拟执行许可已通过' : '当前周期未取得模拟执行许可'}；实盘权限未启用。`
        : '盘中自动模拟交易未启用；当前仅保留研究、风控与历史账本查询。'}</div>
      <section className="shadow-research">
        <div className="target-title">
          <strong><FlaskConical size={15}/>AI影子研究</strong>
          <small>{SHADOW_STATUS_LABELS[shadowResearch.status] || shadowResearch.status || '暂无状态'} · {displayDateTime(shadowResearch.updated_at)}</small>
        </div>
        <div className="shadow-grid">
          <div className="shadow-cell"><span>baseline</span><strong>{shadowStageState(shadowResearch.baseline)}</strong></div>
          <div className="shadow-cell"><span>runtime summary</span><strong>{shadowStageState(shadowResearch.runtime_summary)}</strong></div>
          <div className="shadow-cell"><span>AI 原始输出</span><strong>{shadowStageState(shadowResearch.ai_raw_output)}</strong></div>
          <div className="shadow-cell"><span>对照报告</span><strong>{shadowStageState(shadowResearch.shadow_cycle)}</strong></div>
          <div className="shadow-cell"><span>影子记录库</span><strong>{shadowStageState(shadowResearch.shadow_store)}</strong></div>
        </div>
        <div className="shadow-meta">
          只读影子建议：execution_authority=false · can_trigger_order=false · live_execution_authority=false。
          当前原因：{shadowResearch.reason_code || '--'}；建议数量：{shadowResearch.shadow_cycle?.total_proposals ?? '--'}。
        </div>
      </section>
      <div className="sentiment-block">市场情绪：{sentimentLabel} {sentimentScore === null ? '' : `· ${sentimentScore.toFixed(0)}`}<small>情绪置信度：{sentimentConfidence === null ? '--' : `${(sentimentConfidence * 100).toFixed(0)}%`} · 官方来源：{sentimentSources.map((source: any) => source.source).join('、') || '--'}</small>{sentiment?.stale ? <small>部分官方数据已过期，当前展示包含缓存值</small> : null}</div>
      <section className="target-portfolio">
        <div className="target-title">
          <strong><Layers3 size={15}/>研究目标组合</strong>
          <small>{targetPortfolio ? `${targetStatus} · ${targetPortfolio.selection_date || '--'} · ${targetPositions.length} 只` : '暂无完整研究组合'}</small>
        </div>
        {targetPortfolio?.is_current === false ? <div className="cockpit-notice" style={{ marginBottom: 10 }}>
          目标组合研究日期已落后：{targetPortfolio.freshness_warning || `当前组合日期 ${targetPortfolio.selection_date || '未知'}，预期至少 ${targetPortfolio.expected_latest_date || '最新完整交易日'}；仅供历史参考。`}
        </div> : null}
        {targetPositions.length ? <div className="target-scroll"><table className="target-table">
          <thead><tr><th>代码</th><th>名称</th><th>目标权重</th><th>研究理由</th></tr></thead>
          <tbody>{targetPositions.map((position: any) => <tr key={position.code}>
            <td>{position.code}</td><td>{position.name || '--'}</td><td>{percent(position.target_weight)}</td><td className="target-reason">{localizedReason(position.research_reason) || '--'}</td>
          </tr>)}</tbody>
        </table></div> : <div className="target-empty">目标组合不可用；刷新中的研究代不会与上一代混用。</div>}
        <div className="target-note">研究目标组合，不构成订单；仅展示已验证的只读研究投影，实盘权限未启用。</div>
      </section>
      {error ? <div className="cockpit-error">{error}</div> : null}
    </div>
  );
};

export default DashboardPanel;

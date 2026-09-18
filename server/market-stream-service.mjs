import { marketStreamFullRunner, marketStreamHotRunner } from './data-runners.mjs';
import { PersistentRunner } from './persistent_runner.mjs';
import { syncPolicy } from './sync-policy.mjs';
import { overallRisk } from './risk-summary.mjs';

const ALLOWED_CHANNELS = new Set(['hot_quotes', 'market_top100', 'cockpit_mark', 'stream_status', 'heartbeat']);
const defaultF5Runner = new PersistentRunner('f5_paper_runner.py', 'market-stream-f5');
const defaultRiskRunner = new PersistentRunner('risk_runner.py', 'market-stream-risk');

function dataOf(result) {
  if (!result || result.success === false) return null;
  return result.data ?? result;
}

function normalizedCodes(values) {
  const output = [];
  const seen = new Set();
  for (const value of values || []) {
    const pure = String(value || '').replace(/^(sh|sz|bj)/i, '').replace(/\.(SH|SZ|BJ)$/i, '');
    if (!/^\d{6}$/.test(pure) || seen.has(pure)) continue;
    seen.add(pure);
    output.push(pure);
  }
  return output;
}

export class MarketStreamService {
  constructor({
    hotRunner = marketStreamHotRunner,
    fullRunner = marketStreamFullRunner,
    f5Runner = defaultF5Runner,
    riskRunner = defaultRiskRunner,
    setIntervalFn = setInterval,
    clearIntervalFn = clearInterval,
    nowMs = Date.now,
  } = {}) {
    this.hotRunner = hotRunner;
    this.fullRunner = fullRunner;
    this.f5Runner = f5Runner;
    this.riskRunner = riskRunner;
    this.setIntervalFn = setIntervalFn;
    this.clearIntervalFn = clearIntervalFn;
    this.nowMs = nowMs;
    this.clients = new Map();
    this.sequence = 0;
    this.hotInFlight = null;
    this.topInFlight = null;
    this.hotTimer = null;
    this.topTimer = null;
    this.f5Timer = null;
    this.lastHot = null;
    this.lastTopGeneration = '';
    this.lastError = '';
    this.holdingCodes = new Set();
    this.lastMarkedSnapshot = '';
    this.lastCockpit = null;
    this.hotUpstreamCalls = 0;
    this.topUpstreamCalls = 0;
    this.markCalls = 0;
    this.riskCalls = 0;
    this.lastRiskAt = 0;
    this.lastRiskError = '';
    this.hotFailureCount = 0;
    this.hotRetryNotBefore = 0;
    this.running = false;
  }

  _event(type, data) {
    return { id: ++this.sequence, type, data };
  }

  _send(client, event) {
    try { client.send(event); } catch { this.clients.delete(client.id); }
  }

  _broadcast(type, data) {
    const event = this._event(type, data);
    for (const client of this.clients.values()) {
      if (client.channels.has(type)) this._send(client, event);
    }
    return event;
  }

  subscribe(clientId, codes, channels, send) {
    const requested = normalizedCodes(codes);
    const bounded = requested.slice(0, 200);
    const normalizedChannels = new Set(
      (channels || []).map(String).filter(channel => ALLOWED_CHANNELS.has(channel)),
    );
    if (!normalizedChannels.size) normalizedChannels.add('hot_quotes');
    const client = {
      id: String(clientId),
      codes: new Set(bounded),
      channels: normalizedChannels,
      send,
    };
    this.clients.set(client.id, client);
    this._send(client, this._event('stream_status', {
      connected: true,
      truncated: requested.length > bounded.length,
      requested_symbols: requested.length,
      accepted_symbols: bounded.length,
    }));
    return () => this.clients.delete(client.id);
  }

  hotCodes() {
    const codes = new Set(this.holdingCodes);
    for (const client of this.clients.values()) {
      for (const code of client.codes) codes.add(code);
    }
    return [...codes].sort().slice(0, 200);
  }

  refreshHot() {
    if (this.hotInFlight) return this.hotInFlight;
    if (this.nowMs() < this.hotRetryNotBefore) return Promise.resolve(null);
    const codes = this.hotCodes();
    if (!codes.length) return Promise.resolve(null);
    // Process-level guard is deliberately wider than the 3s freshness gate:
    // late quotes are marked stale by Python, while a busy machine does not
    // churn the persistent runner merely because a response crossed 3s.
    const timeout = Math.max(15000, syncPolicy('hot_quotes').stale_after_ms);
    this.hotUpstreamCalls += 1;
    this.hotInFlight = this.hotRunner.call({ action: 'hot_snapshot', codes }, timeout)
      .then((result) => {
        const data = dataOf(result);
        if (!data?.snapshot_id) throw new Error('hot_snapshot_missing');
        this.hotFailureCount = 0;
        this.hotRetryNotBefore = 0;
        this.lastError = '';
        if (data.snapshot_id !== this.lastHot?.snapshot_id) {
          this.lastHot = data;
          this._broadcast('hot_quotes', data);
          return this._markCockpit(data).then(() => data);
        }
        this.lastError = '';
        return data;
      })
      .catch((error) => {
        this.lastError = String(error?.message || error);
        this.hotFailureCount += 1;
        const retryDelays = [2000, 5000, 10000];
        const retryDelay = retryDelays[Math.min(this.hotFailureCount - 1, retryDelays.length - 1)];
        this.hotRetryNotBefore = this.nowMs() + retryDelay;
        this._broadcast('stream_status', { connected: true, degraded: true, reason: this.lastError });
        return null;
      })
      .finally(() => { this.hotInFlight = null; });
    return this.hotInFlight;
  }

  async refreshF5State() {
    try {
      const activeLedger = dataOf(await this.f5Runner.call({ action: 'account' }, 5000));
      this.holdingCodes = new Set(
        (activeLedger?.positions || []).map(row => String(row?.code || '')).filter(code => /^\d{6}$/.test(code)),
      );
      if (activeLedger) {
        this.lastCockpit = { ...(this.lastCockpit || {}), activeLedger, account: activeLedger.account, positions: activeLedger.positions || [] };
      }
      return activeLedger;
    } catch (error) {
      this.lastError = String(error?.message || error);
      return null;
    }
  }

  async _markCockpit(snapshot) {
    if (!snapshot?.snapshot_id || snapshot.snapshot_id === this.lastMarkedSnapshot || !this.holdingCodes.size) return this.lastCockpit;
    this.markCalls += 1;
    const marked = await this.f5Runner.call({ action: 'mark_to_market' }, 5000);
    if (marked?.success === false) return this.lastCockpit;
    this.lastMarkedSnapshot = snapshot.snapshot_id;
    const riskInterval = syncPolicy('cockpit_risk').active_interval_ms;
    const riskDue = !this.lastCockpit?.risk || this.nowMs() - this.lastRiskAt >= riskInterval;
    let riskError = '';
    const riskPromise = riskDue
      ? this.riskRunner.call({ action: 'portfolio_risk' }, Math.max(12_000, riskInterval * 3))
        .catch((error) => {
          riskError = String(error?.message || error);
          return null;
        })
      : Promise.resolve(null);
    if (riskDue) this.riskCalls += 1;
    const [activeLedgerResult, riskResult] = await Promise.all([
      this.f5Runner.call({ action: 'account' }, 5000),
      riskPromise,
    ]);
    const activeLedger = dataOf(activeLedgerResult);
    const freshRisk = dataOf(riskResult);
    if (freshRisk) {
      this.lastRiskAt = this.nowMs();
      this.lastRiskError = '';
    } else if (riskError) {
      this.lastRiskError = riskError;
    }
    const risk = freshRisk || this.lastCockpit?.risk || null;
    this.holdingCodes = new Set(
      (activeLedger?.positions || []).map(row => String(row?.code || '')).filter(code => /^\d{6}$/.test(code)),
    );
    this.lastCockpit = {
      activeLedger,
      account: { ...(activeLedger?.account || {}), ...(dataOf(marked) || {}) },
      positions: activeLedger?.positions || [],
      risk,
      overall_risk: overallRisk(risk, null),
      market_snapshot_id: snapshot.snapshot_id,
      quote_timestamp: snapshot.quote_timestamp || null,
      market_phase: snapshot.market_phase || 'unknown',
    };
    this._broadcast('cockpit_mark', this.lastCockpit);
    return this.lastCockpit;
  }

  cockpitSnapshot() { return this.lastCockpit ? structuredClone(this.lastCockpit) : null; }

  refreshTop() {
    if (this.topInFlight) return this.topInFlight;
    if (![...this.clients.values()].some(client => client.channels.has('market_top100'))) {
      return Promise.resolve(null);
    }
    this.topUpstreamCalls += 1;
    this.topInFlight = this.fullRunner.call({
      action: 'stocks', limit: 100, sort_by: 'amount', refresh_if_stale: true,
    }, 15_000)
      .then((result) => {
        const data = dataOf(result);
        if (!data?.complete || !data?.generation_id) return data;
        if (data.generation_id !== this.lastTopGeneration) {
          this.lastTopGeneration = data.generation_id;
          this._broadcast('market_top100', data);
        }
        this.lastError = '';
        return data;
      })
      .catch((error) => {
        this.lastError = String(error?.message || error);
        this._broadcast('stream_status', { connected: true, degraded: true, reason: this.lastError });
        return null;
      })
      .finally(() => { this.topInFlight = null; });
    return this.topInFlight;
  }

  start() {
    if (this.running) return;
    this.running = true;
    const hotMs = syncPolicy('hot_quotes').active_interval_ms;
    const topMs = syncPolicy('market_top100').active_interval_ms;
    this.hotTimer = this.setIntervalFn(() => void this.refreshHot(), hotMs);
    this.topTimer = this.setIntervalFn(() => void this.refreshTop(), topMs);
    this.f5Timer = this.setIntervalFn(() => void this.refreshF5State(), syncPolicy('system_health').active_interval_ms);
    this.hotTimer?.unref?.();
    this.topTimer?.unref?.();
    this.f5Timer?.unref?.();
    void this.refreshF5State();
  }

  stop() {
    if (this.hotTimer) this.clearIntervalFn(this.hotTimer);
    if (this.topTimer) this.clearIntervalFn(this.topTimer);
    if (this.f5Timer) this.clearIntervalFn(this.f5Timer);
    this.hotTimer = null;
    this.topTimer = null;
    this.f5Timer = null;
    this.running = false;
    this.clients.clear();
  }

  snapshot() {
    return {
      clients: this.clients.size,
      symbols: this.hotCodes().length,
      running: this.running,
      hot_in_flight: Boolean(this.hotInFlight),
      top_in_flight: Boolean(this.topInFlight),
      last_hot_snapshot_id: this.lastHot?.snapshot_id || '',
      last_top_generation_id: this.lastTopGeneration,
      last_error: this.lastError,
      holding_symbols: this.holdingCodes.size,
      last_marked_snapshot_id: this.lastMarkedSnapshot,
      hot_upstream_calls: this.hotUpstreamCalls,
      top_upstream_calls: this.topUpstreamCalls,
      mark_calls: this.markCalls,
      risk_upstream_calls: this.riskCalls,
      last_risk_error: this.lastRiskError,
      hot_failure_count: this.hotFailureCount,
      hot_retry_not_before: this.hotRetryNotBefore,
    };
  }
}

export const marketStreamService = new MarketStreamService();

import { syncPolicy } from './sync-policy.mjs';

const SLOT_NAMES = ['health', 'targetPortfolio', 'globalContext', 'paperStatus', 'alerts', 'shadowResearch'];

export class WorkbenchSlowCache {
  constructor({
    healthLoader = null,
    targetLoader = null,
    contextLoader = null,
    paperStatusLoader = null,
    alertsLoader = null,
    shadowResearchLoader = null,
    setIntervalFn = setInterval,
    clearIntervalFn = clearInterval,
  } = {}) {
    this.loaders = {
      health: healthLoader,
      targetPortfolio: targetLoader,
      globalContext: contextLoader,
      paperStatus: paperStatusLoader,
      alerts: alertsLoader,
      shadowResearch: shadowResearchLoader,
    };
    this.values = Object.fromEntries(SLOT_NAMES.map(name => [name, null]));
    this.meta = Object.fromEntries(SLOT_NAMES.map(name => [name, {
      as_of: null, refreshing: false, stale: true, last_error: '',
    }]));
    this.pending = new Map();
    this.timers = [];
    this.setIntervalFn = setIntervalFn;
    this.clearIntervalFn = clearIntervalFn;
    this.running = false;
  }

  _refresh(name) {
    if (this.pending.has(name)) return this.pending.get(name);
    const loader = this.loaders[name];
    if (typeof loader !== 'function') return Promise.resolve(null);
    this.meta[name] = { ...this.meta[name], refreshing: true };
    const pending = Promise.resolve()
      .then(loader)
      .then((value) => {
        this.values[name] = value ?? null;
        this.meta[name] = {
          as_of: new Date().toISOString(), refreshing: false,
          stale: value == null, last_error: '',
        };
        return value;
      })
      .catch((error) => {
        this.meta[name] = {
          ...this.meta[name], refreshing: false, stale: true,
          last_error: String(error?.message || error),
        };
        return null;
      })
      .finally(() => this.pending.delete(name));
    this.pending.set(name, pending);
    return pending;
  }

  refreshHealth() { return this._refresh('health'); }
  refreshTargetPortfolio() { return this._refresh('targetPortfolio'); }
  refreshGlobalContext() { return this._refresh('globalContext'); }
  refreshPaperStatus() { return this._refresh('paperStatus'); }
  refreshAlerts() { return this._refresh('alerts'); }
  refreshShadowResearch() { return this._refresh('shadowResearch'); }

  start() {
    if (this.running) return;
    this.running = true;
    for (const name of SLOT_NAMES) void this._refresh(name);
    const schedules = [
      ['health', syncPolicy('system_health').active_interval_ms],
      ['targetPortfolio', syncPolicy('system_health').background_interval_ms],
      ['globalContext', syncPolicy('core_indices').background_interval_ms],
      ['paperStatus', syncPolicy('cockpit_risk').active_interval_ms],
      ['alerts', syncPolicy('alerts').active_interval_ms],
      ['shadowResearch', syncPolicy('system_health').background_interval_ms],
    ];
    for (const [name, interval] of schedules) {
      const timer = this.setIntervalFn(() => void this._refresh(name), interval);
      timer?.unref?.();
      this.timers.push(timer);
    }
  }

  stop() {
    for (const timer of this.timers) this.clearIntervalFn(timer);
    this.timers = [];
    this.running = false;
  }

  snapshot() {
    return {
      ...structuredClone(this.values),
      meta: structuredClone(this.meta),
    };
  }
}

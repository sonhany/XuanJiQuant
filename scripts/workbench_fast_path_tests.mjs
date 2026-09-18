import assert from 'node:assert/strict';

import { WorkbenchSlowCache } from '../server/workbench-cache.mjs';
import { composeFastWorkbenchStatus } from '../server/routes/workbench.mjs';
import { syncPolicy } from '../server/sync-policy.mjs';

function deferred() {
  let resolve;
  const promise = new Promise(yes => { resolve = yes; });
  return { promise, resolve };
}

{
  const intervals = [];
  const cache = new WorkbenchSlowCache({
    healthLoader: async () => null,
    targetLoader: async () => null,
    contextLoader: async () => null,
    paperStatusLoader: async () => null,
    alertsLoader: async () => null,
    setIntervalFn: (_callback, interval) => {
      intervals.push(interval);
      return { unref() {} };
    },
    clearIntervalFn: () => {},
  });
  cache.start();
  assert.equal(
    intervals[1],
    syncPolicy('system_health').background_interval_ms,
    'target portfolio pointer must be checked on the health cadence, not once per day',
  );
  cache.stop();
}

{
  const health = deferred();
  const cache = new WorkbenchSlowCache({
    healthLoader: () => health.promise,
    targetLoader: async () => ({ portfolio_id: 'target-1' }),
    contextLoader: async () => ({ sentiment: { sentiment_score: 70 } }),
    paperStatusLoader: async () => ({ enabled: true }),
  });
  const pending = cache.refreshHealth();
  const snapshot = cache.snapshot();
  assert.equal(snapshot.health, null);
  assert.equal(snapshot.meta.health.refreshing, true);
  health.resolve({ overall: 'healthy' });
  await pending;
  assert.equal(cache.snapshot().health.overall, 'healthy');
  cache.stop();
}

{
  const state = composeFastWorkbenchStatus({
    activeLedger: {
      ledger_authority: 'f5',
      account: { total_equity: 1_010_000, daily_pnl: 10_000, market_snapshot_id: 'snap-1' },
      positions: [{ code: '600519' }],
    },
    risk: { volatility_pct: 10, market_snapshot_id: 'snap-1' },
    slow: {
      health: null,
      alerts: { business_active: 0 },
      globalContext: null,
      paperStatus: null,
      targetPortfolio: null,
      meta: { health: { refreshing: true, as_of: null } },
    },
  });
  assert.equal(state.account.total_equity, 1_010_000);
  assert.equal(state.account.market_snapshot_id, 'snap-1');
  assert.equal(state.risk.market_snapshot_id, 'snap-1');
  assert.equal(state.services.overall, 'refreshing');
  assert.equal(state.freshness.market_snapshot_id, 'snap-1');
  assert.equal(state.freshness.consistent, true);
}

{
  const mixed = composeFastWorkbenchStatus({
    activeLedger: { ledger_authority: 'f5', account: { market_snapshot_id: 'snap-a' }, positions: [] },
    risk: { market_snapshot_id: 'snap-b' },
    slow: { meta: {} },
  });
  assert.equal(mixed.freshness.consistent, false);
  assert.equal(mixed.overall_risk.level, 'unknown');
}

console.log('workbench fast path tests passed');

import assert from 'node:assert/strict';

import { MarketStreamService } from '../server/market-stream-service.mjs';

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

{
  const pending = deferred();
  const calls = [];
  const hotRunner = {
    call(body, timeout) {
      calls.push({ body, timeout });
      return pending.promise;
    },
  };
  const service = new MarketStreamService({
    hotRunner,
    fullRunner: { call: async () => ({ success: true, data: {} }) },
  });
  const a = [];
  const b = [];
  service.subscribe('a', ['600519'], ['hot_quotes'], event => a.push(event));
  service.subscribe('b', ['600519'], ['hot_quotes'], event => b.push(event));

  const first = service.refreshHot();
  const second = service.refreshHot();
  assert.equal(calls.length, 1, 'overlapping clients must share one upstream hot request');
  assert.equal(service.snapshot().hot_upstream_calls, 1);
  assert.deepEqual(calls[0].body, { action: 'hot_snapshot', codes: ['600519'] });
  pending.resolve({ success: true, data: { snapshot_id: 'snap-1', quotes: { '600519': { price: 10 } } } });
  await Promise.all([first, second]);

  const eventA = a.find(event => event.type === 'hot_quotes');
  const eventB = b.find(event => event.type === 'hot_quotes');
  assert.equal(eventA.data.snapshot_id, 'snap-1');
  assert.equal(eventB.data.snapshot_id, 'snap-1');
  assert.equal(eventA.id, eventB.id, 'one snapshot must use one stream sequence');
  service.stop();
}

{
  const service = new MarketStreamService({
    hotRunner: { call: async () => ({ success: true, data: {} }) },
    fullRunner: { call: async () => ({ success: true, data: {} }) },
  });
  const events = [];
  const codes = Array.from({ length: 250 }, (_, index) => String(600000 + index));
  service.subscribe('bounded', codes, ['hot_quotes'], event => events.push(event));
  const status = service.snapshot();
  assert.equal(status.symbols, 200);
  assert.equal(events.at(-1).type, 'stream_status');
  assert.equal(events.at(-1).data.truncated, true);
  service.stop();
}

{
  let calls = 0;
  const events = [];
  const service = new MarketStreamService({
    hotRunner: { call: async () => ({ success: true, data: {} }) },
    fullRunner: {
      async call() {
        calls += 1;
        return { success: true, data: { generation_id: 'generation-1', complete: true, stocks: [] } };
      },
    },
  });
  service.subscribe('top', [], ['market_top100'], event => events.push(event));
  await service.refreshTop();
  await service.refreshTop();
  assert.equal(calls, 2);
  assert.equal(events.filter(event => event.type === 'market_top100').length, 1, 'duplicate generation must not rebroadcast');
  service.stop();
}

{
  const f5Calls = [];
  const riskCalls = [];
  const events = [];
  const service = new MarketStreamService({
    hotRunner: {
      async call() {
        return {
          success: true,
          data: {
            snapshot_id: 'holding-snapshot-1',
            quotes: { '600519': { code: '600519', price: 10, stale: false } },
          },
        };
      },
    },
    fullRunner: { call: async () => ({ success: true, data: {} }) },
    f5Runner: {
      async call(body) {
        f5Calls.push(body);
        if (body.action === 'account') {
          return { success: true, data: { account: { total_equity: 100 }, positions: [{ code: '600519' }] } };
        }
        return { success: true, data: { total_equity: 101, market_snapshot_id: 'holding-snapshot-1' } };
      },
    },
    riskRunner: {
      async call(body) {
        riskCalls.push(body);
        return { success: true, data: { volatility_pct: 10, market_snapshot_id: 'holding-snapshot-1' } };
      },
    },
  });
  service.subscribe('cockpit', [], ['cockpit_mark'], event => events.push(event));
  await service.refreshF5State();
  assert.deepEqual(service.hotCodes(), ['600519']);
  await service.refreshHot();
  await service.refreshHot();
  assert.equal(f5Calls.filter(call => call.action === 'mark_to_market').length, 1, 'one market snapshot must mark F5 once');
  assert.equal(riskCalls.length, 1);
  assert.equal(events.filter(event => event.type === 'cockpit_mark').length, 1);
  assert.equal(service.cockpitSnapshot().account.market_snapshot_id, 'holding-snapshot-1');
  service.stop();
}

{
  let now = 1_000;
  let snapshotIndex = 0;
  let riskCalls = 0;
  const service = new MarketStreamService({
    nowMs: () => now,
    hotRunner: {
      async call() {
        snapshotIndex += 1;
        return {
          success: true,
          data: {
            snapshot_id: `risk-throttle-${snapshotIndex}`,
            quote_timestamp: `20260903093${snapshotIndex}00`,
            quotes: { '600519': { code: '600519', price: 10 + snapshotIndex, stale: false } },
          },
        };
      },
    },
    fullRunner: { call: async () => ({ success: true, data: {} }) },
    f5Runner: {
      async call(body) {
        if (body.action === 'account') {
          return {
            success: true,
            data: {
              account: { total_equity: 1_000_000, market_snapshot_id: `risk-throttle-${snapshotIndex}` },
              positions: [{ code: '600519', quantity: 100 }],
            },
          };
        }
        return {
          success: true,
          data: { total_equity: 1_000_000, market_snapshot_id: `risk-throttle-${snapshotIndex}` },
        };
      },
    },
    riskRunner: {
      async call() {
        riskCalls += 1;
        return {
          success: true,
          data: { volatility_pct: 10, market_snapshot_id: `risk-throttle-${snapshotIndex}` },
        };
      },
    },
  });
  await service.refreshF5State();
  await service.refreshHot();
  now = 1_500;
  await service.refreshHot();
  assert.equal(riskCalls, 1, '1-second account marks must reuse risk inside the governed 2-second interval');
  assert.equal(service.cockpitSnapshot().market_snapshot_id, 'risk-throttle-2');
  now = 3_100;
  await service.refreshHot();
  assert.equal(riskCalls, 2, 'risk must refresh after the governed interval elapses');
  service.stop();
}

{
  let now = 1_000;
  let calls = 0;
  const service = new MarketStreamService({
    hotRunner: {
      async call() {
        calls += 1;
        throw new Error('provider timeout');
      },
    },
    fullRunner: { call: async () => ({ success: true, data: {} }) },
    nowMs: () => now,
  });
  service.subscribe('backoff', ['600519'], ['hot_quotes'], () => {});
  await service.refreshHot();
  await service.refreshHot();
  assert.equal(calls, 1, 'hot source failure must enter retry backoff');
  now += 2_001;
  await service.refreshHot();
  assert.equal(calls, 2, 'hot source must retry after the bounded delay');
  assert.equal(service.snapshot().hot_failure_count, 2);
  assert(service.snapshot().hot_retry_not_before > now);
  service.stop();
}

console.log('market stream service tests passed');

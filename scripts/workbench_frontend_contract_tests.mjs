import assert from 'node:assert/strict';
import {
  deriveTradePermission,
  f5ReasonLabel,
  formatSystemField,
  freshnessState,
  normalizePercentInput,
  roleCapabilities,
  toDisplayPercent,
  toPercentPoints,
  valueState,
} from '../lib/workbench-state.mjs';

const now = Date.parse('2026-07-20T09:30:00.000Z');
assert.equal(freshnessState('2026-07-20T09:29:45.000Z', now, 30_000).state, 'fresh');
assert.equal(freshnessState('2026-07-20T09:28:00.000Z', now, 30_000).state, 'stale');
assert.equal(deriveTradePermission({ allowed: true, risk_state: 'ok', fresh: true }).allowed, true);
assert.equal(deriveTradePermission({ allowed: true, risk_state: 'unknown', fresh: true }).allowed, false);
assert.equal(normalizePercentInput(0.2), 20);
assert.equal(normalizePercentInput('95%'), 95);
assert.equal(toDisplayPercent(0.125), '12.50%');
assert.equal(toPercentPoints(-0.25, 1), '-0.3%');
assert.equal(roleCapabilities('risk-review').canOperateSimulation, false);
assert.equal(valueState(undefined, false, '').state, 'loading');
assert.equal(valueState(0, true, '').state, 'ready');
assert.equal(f5ReasonLabel('outside_intraday_window'), '盘中执行窗口外');
assert.equal(f5ReasonLabel('non_trading_weekday'), '当前不是交易日');
assert.deepEqual(
  formatSystemField('current_readiness', {
    paper_execution_ready: true,
    market_window_allowed: false,
    reason_code: 'outside_intraday_window',
  }),
  {
    label: '当前模拟执行准备状态',
    value: '模拟许可已通过；当前不在盘中执行窗口；盘中执行窗口外',
  },
);
assert.deepEqual(
  formatSystemField('historical_run_reason', null),
  { label: '历史运行原因', value: '--' },
);
console.log('workbench frontend contract tests passed');

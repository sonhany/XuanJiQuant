import test from 'node:test';
import assert from 'node:assert/strict';
import { formatOptionalPercent, heartbeatAgeSeconds, nextVisibleCount, normalizePerformanceSeries, takeVisibleRows } from '../lib/ui-workbench.mjs';

test('computes bounded quote heartbeat age', () => {
  assert.equal(heartbeatAgeSeconds('2026-07-31T02:03:20Z', '2026-07-31T02:03:32Z'), 12);
  assert.equal(heartbeatAgeSeconds('invalid', '2026-07-31T02:03:32Z'), null);
});

test('optional percentages keep missing values explicit', () => {
  assert.equal(formatOptionalPercent(null), '--');
  assert.equal(formatOptionalPercent(2.125), '+2.13%');
  assert.equal(formatOptionalPercent(-1.2), '-1.20%');
});

test('normalizes historical equity without inventing data', () => {
  assert.deepEqual(normalizePerformanceSeries([
    { date: '2026-07-20', equity: 1_020_000, drawdown_pct: 0 },
    { date: '2026-07-21', equity: 999_600, drawdown_pct: -2 },
  ], 1_000_000), [
    { date: '2026-07-20', equity: 1_020_000, nav: 1.02, drawdownPct: 0 },
    { date: '2026-07-21', equity: 999_600, nav: 0.9996, drawdownPct: -2 },
  ]);
});

test('feed rows render in bounded batches', () => {
  const rows = Array.from({ length: 120 }, (_, index) => ({ id: index + 1 }));
  assert.equal(takeVisibleRows(rows, 40).length, 40);
  assert.equal(nextVisibleCount(40, rows.length, 40), 80);
  assert.equal(nextVisibleCount(100, rows.length, 40), 120);
});

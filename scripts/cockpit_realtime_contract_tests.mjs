import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync('components/DashboardPanel.tsx', 'utf8');

assert(source.includes("channels: ['cockpit_mark']"), 'cockpit must subscribe to committed F5 marks');
for (const label of ['行情时间', '权益估值时间', '风险计算时间', '数据状态']) {
  assert(source.includes(label), `cockpit must show ${label}`);
}
assert(source.includes('3_000'), 'cockpit must use the 3-second delayed threshold');
assert(source.includes('15_000'), 'cockpit must use the 15-second unavailable threshold');
assert(source.includes('market_snapshot_id'), 'cockpit must track snapshot identity');
assert(source.includes('fallbackIntervalMs: 2000'), 'cockpit must use a bounded 2-second fallback');
assert(!source.includes('setInterval(refresh, 2000)'), 'cockpit must not run a parallel primary poll');
assert(source.includes("value === null || value === undefined || value === ''"), 'unavailable PnL must not render as zero');

console.log('cockpit realtime contracts passed');

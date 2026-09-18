import fs from 'node:fs';
import assert from 'node:assert/strict';

const route = fs.readFileSync('server/routes/workbench.mjs', 'utf8');
const dashboard = fs.readFileSync('components/DashboardPanel.tsx', 'utf8');

assert(route.includes('strategy_runner.py'), 'workbench must read the governed research selection');
assert(route.includes("{ action: 'research_selection' }"), 'workbench must use the read-only research-selection action');
for (const token of ['研究目标组合', '目标权重', '研究理由', '不构成订单', '目标组合研究日期已落后']) {
  assert(dashboard.includes(token), `dashboard must render ${token}`);
}
for (const label of ['低20日波动率', '趋势强度']) {
  assert(dashboard.includes(label), `dashboard must localize factor reason ${label}`);
}
assert(dashboard.includes('target_portfolio'), 'dashboard must consume the workbench target-portfolio projection');
assert(!dashboard.includes('place_order'), 'dashboard target portfolio must remain read-only');
assert(
  dashboard.includes("value === null || value === undefined || value === ''"),
  'dashboard must not render unavailable PnL as numeric zero',
);

console.log('cockpit target portfolio contract tests passed');

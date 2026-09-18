import assert from 'node:assert/strict';
import fs from 'node:fs';

const execution = fs.readFileSync('components/ExecutionPanel.tsx', 'utf8');
const paper = fs.readFileSync('components/PaperPanel.tsx', 'utf8');
const config = fs.readFileSync('components/PaperStrategyConfig.tsx', 'utf8');
const dashboard = fs.readFileSync('components/DashboardPanel.tsx', 'utf8');
const state = fs.readFileSync('lib/workbench-state.mjs', 'utf8');
const webVerify = fs.readFileSync('scripts/web_verify.mjs', 'utf8');
const combined = `${execution}\n${paper}\n${config}`;

assert(combined.includes('/api/paper-execution'), 'active paper pages must use F5 API');
for (const text of ['F5 确定性模拟执行', '准入原因', '组合 ID', '验证 ID', '目标交易日', '模拟订单', '模拟成交', '对账结果', '熔断开关', '总权益']) {
  assert(combined.includes(text), `F5 UI must render ${text}`);
}
for (const text of ['实验模拟自动交易', '策略质量：未通过F4', '模拟执行许可', '实盘权限：未启用']) {
  assert(combined.includes(text), `experimental F5 UI must render ${text}`);
}
for (const text of ['盘中实验模拟', '实时行情时间']) {
  assert(combined.includes(text), `intraday F5 UI must render ${text}`);
}
for (const text of ['股票名称', '累计盈亏', '累计收益率', '成本金额', '浮动盈亏', '盈亏率', '已实现盈亏', '仓位占比', '更新时间', '名称待补']) {
  assert(paper.includes(text), `F5 portfolio detail must render ${text}`);
}
assert(paper.includes('row.name'), 'F5 portfolio rows must render the projected stock name');
assert(!execution.includes('<p>下一交易日开盘模拟'), 'execution header must not hard-code the retired next-day-only flow');
assert(dashboard.includes('data?.automatic_execution'), 'dashboard must render the authoritative F5 automation state');
assert(dashboard.includes('统一 F5 模拟账本'), 'cockpit must identify the single active ledger');
assert(paper.includes('全系统唯一活动模拟账本'), 'paper account must identify the single active ledger');
assert(!paper.includes('不与历史执行账本合并'), 'retired dual-ledger wording must be removed');
assert(paper.includes("f5('account')"), 'paper account must consume the atomic F5 account projection');
assert(webVerify.includes('统一账本跨页面一致'), 'Web acceptance must reject cross-surface ledger drift');
assert(!dashboard.includes('自动模拟交易已关闭。当前系统只运行数据'), 'dashboard must not retain the retired static closed banner');
for (const reason of ['blocked_by_f4', 'portfolio_policy_incompatible', 'selection_stale', 'superseded_by_intraday']) {
  assert(state.includes(reason), `Chinese reason mapping required for ${reason}`);
}
for (const reason of [
  'positive_excess_window_ratio_below_0_60',
  'after_cost_excess_return_not_positive',
  'sharpe_below_0_80',
  'max_drawdown_below_minus_0_20',
  'double_cost_excess_return_not_positive',
]) {
  assert(state.includes(reason), `Chinese performance reason mapping required for ${reason}`);
}
for (const forbidden of ['defaultModel', 'modelOptions', 'llm_provider', 'llm_model', 'strategy_name', '手工股票池', '选股池']) {
  assert(!config.includes(forbidden), `retired configuration must not contain ${forbidden}`);
}
assert(config.includes('set_enabled') && config.includes('set_kill_switch'), 'only enabled and kill-switch controls remain');
assert(!combined.includes('place_order') && !combined.includes('fill_order'), 'UI must have no arbitrary order control');
console.log('f5 paper UI contracts passed');

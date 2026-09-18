import fs from 'node:fs';
import assert from 'node:assert/strict';

const source = fs.readFileSync('components/ExecutionPanel.tsx', 'utf-8');

assert(
  source.includes('row.filled_price ? number(row.filled_price,4)') && source.includes("row.status==='rejected'"),
  'F5 orders should display actual fill prices and explicit rejection state',
);
assert(
  source.includes('formatTime(row.updated_at || row.created_at)'),
  'F5 order history should display a readable ledger timestamp',
);
assert(
  source.includes("toLocaleString('zh-CN', { hour12: false })"),
  'F5 execution timestamps should be localized in Chinese',
);
assert(
  source.includes("f5Api('account')") && source.includes('accountProjection'),
  'execution page must read the authoritative F5 account and positions',
);
assert(
  source.includes('latestRunOrders') && source.includes('latestRunFills') && source.includes('latestRunChecks'),
  'execution page must focus order, fill and reconciliation tables on the latest run',
);
for (const label of ['本轮运行状态', '本轮订单', '本轮成交', '当前持仓', '当前持仓管理（只读）']) {
  assert(source.includes(label), `execution page must expose ${label} above historical noise`);
}
for (const label of ['股票名称 / 代码', '可用现金', '持仓市值', '当日盈亏', '累计盈亏', '累计收益率', '持仓浮动盈亏', '成本金额', '浮动盈亏', '盈亏率', '已实现盈亏', '仓位占比', '更新时间', '名称待补']) {
  assert(source.includes(label), `execution account detail must expose ${label}`);
}
assert(source.includes('row.name'), 'execution holdings must display the projected stock name');
assert(
  (source.match(/股票名称 \/ 代码/g) || []).length >= 3,
  'positions, orders and fills must all expose stock name plus code',
);
assert(
  source.includes('accountProjection.orders') && source.includes('accountProjection.trades'),
  'orders and fills must consume the name-enriched unified F5 projection',
);
assert(
  source.indexOf('当前持仓管理（只读）') < source.indexOf('本轮模拟订单'),
  'current holdings must appear before order and fill tables',
);

console.log('execution panel contract tests passed');

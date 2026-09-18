import fs from 'node:fs';
import assert from 'node:assert/strict';

const source = fs.readFileSync('components/ExecutionPanel.tsx', 'utf8');
for (const text of ['F5 确定性模拟执行', '永无实盘权限', '准入原因', '模拟订单', '模拟成交与对账结果']) {
  assert(source.includes(text), `execution monitoring must include ${text}`);
}
assert(!source.includes('workbenchRequest'), 'read-only execution must not load a control plane');
assert(!source.includes("action: 'place_order'"), 'read-only execution page must not submit orders');
assert(!source.includes('window.confirm'), 'read-only execution page must not offer manual confirmation');
assert(!source.includes('Agent'), 'execution page must not expose Agent vocabulary');
assert(source.includes('row.filled_price ? number(row.filled_price,4)'), 'orders must show only actual F5 fill prices');
assert(source.includes('拒绝原因'), 'orders must expose rejection reason');
assert(source.includes('formatTime(row.updated_at || row.created_at)'), 'orders must show F5 ledger timestamp');

console.log('professional execution contract tests passed');

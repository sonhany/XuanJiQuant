import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(?:[A-Za-z]:)/, value => value.slice(1))), '..');
const source = fs.readFileSync(path.join(root, 'components', 'RiskPanel.tsx'), 'utf8');
const labels = fs.readFileSync(path.join(root, 'lib', 'workbench-state.mjs'), 'utf8');

if (!source.includes('key={`${row.run_id || row.decision_id || "audit"}-${row.created_at || "time"}-${index}`}')) {
  throw new Error('审计回放列表必须使用包含 index 的唯一 React key');
}
for (const required of ['expected_as_of', 'generation_id', 'paper_execution_authority', 'daily_refresh_pending']) {
  if (!labels.includes(required)) throw new Error(`四层健康中文映射缺失: ${required}`);
}
if (!source.includes("!['overall', 'checked_at'].includes(key)")) {
  throw new Error('检查时间不得被渲染成第五个健康层');
}
console.log('risk panel key contract passed');

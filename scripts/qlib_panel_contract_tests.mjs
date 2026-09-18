import assert from 'assert';
import fs from 'fs';

const app = fs.readFileSync('App.tsx', 'utf-8');
const shell = fs.readFileSync('components/AppShell.tsx', 'utf-8');
const componentPath = 'components/QlibResearchPanel.tsx';
const router = fs.readFileSync('server/router.mjs', 'utf-8');

assert(fs.existsSync(componentPath), 'Qlib research page component must exist');
const src = [
  componentPath,
  ...fs.readdirSync('components/qlib').map(name => `components/qlib/${name}`),
].map(path => fs.readFileSync(path, 'utf-8')).join('\n');

assert(shell.includes("label: 'Qlib 实验'"), 'left navigation must add the Qlib experiment tab');
assert(shell.includes("key: 'qlib'"), 'Qlib tab key must be qlib');
assert(
  app.includes("const QlibResearchPanel = lazy(() => import('./components/QlibResearchPanel'))"),
  'App must lazy-load QlibResearchPanel',
);
assert(app.includes('qlib:') && app.includes('<QlibResearchPanel />'), 'App panels must render QlibResearchPanel for qlib tab');

for (const section of ['研究总览', '数据准备', '模型训练', '实验记录', '模型仓库', '回测评估', '任务日志']) {
  assert(src.includes(section), `Qlib page must render section: ${section}`);
}
for (const feature of ['Alpha158', 'LightGBM', 'Rank IC', '影子']) {
  assert(src.includes(feature), `Qlib page must mention feature: ${feature}`);
}

assert(src.includes('/api/qlib'), 'Qlib page must call /api/qlib');
assert(src.includes('qlib_version'), 'Qlib page must disclose pyqlib installation status');
assert(src.includes('独立数据仓库'), 'Qlib page must show the independent warehouse boundary');
for (const action of ['quality_reports', 'workflow_runs', 'backtests', 'schedule_status']) {
  assert(src.includes(`'${action}'`), `Qlib page must read ${action}`);
}
assert(src.includes("from '../lib/qlib-types'"), 'Qlib page must use the shared typed contract');
assert(!src.includes('type ResearchState'), 'Qlib page must not retain the old any-based ResearchState');
assert(router.includes("'/api/qlib'"), 'router must expose /api/qlib');

console.log('qlib panel contract tests passed');

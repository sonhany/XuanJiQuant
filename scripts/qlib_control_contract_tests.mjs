import fs from 'fs';
import assert from 'assert';

const router = fs.readFileSync('server/router.mjs', 'utf8');
const route = fs.readFileSync('server/routes/qlib.mjs', 'utf8');
const runner = fs.readFileSync('scripts/qlib_runner.py', 'utf8');

const readOnlyBlock = router.match(/const READ_ONLY_ACTIONS = \{([\s\S]*?)\n\};/)?.[1] || '';
const qlibEntry = readOnlyBlock.match(/'\/api\/qlib': new Set\(\[([^\]]*)\]\)/)?.[1] || '';
const expectedReadOnly = [
  'status', 'catalog', 'datasets', 'jobs',
  'experiments', 'models', 'reports', 'job_log',
  'quality_reports', 'workflow_runs', 'backtests', 'schedule_status',
];
for (const action of expectedReadOnly) {
  assert(qlibEntry.includes(`'${action}'`), `Qlib read-only action missing: ${action}`);
}
for (const action of [
  'setup', 'collect_one_year', 'collect_six_years', 'export',
  'build_point_in_time', 'quality_six_years', 'export_six_years',
  'train_smoke', 'train_one_year', 'train_walk_forward',
  'cancel_job', 'promote_shadow',
  'workflow_baseline', 'workflow_monthly_walk_forward',
  'workflow_quarterly_matrix', 'backtest_ashare',
  'resolve_backtest_divergence',
]) {
  assert(!qlibEntry.includes(`'${action}'`), `Qlib control action must require authorization: ${action}`);
}

assert(route.includes('runner.call(body, 30000)'), 'Qlib HTTP controller must return quickly');
assert(runner.includes('.venv-qlib'), 'Qlib worker must use the isolated virtual environment');
assert(runner.includes('qlib_job_worker.py'), 'Qlib jobs must use the fixed worker entry');
assert(!runner.includes('create_cache'), 'Qlib controller must not read the trading cache');
for (const action of [
  'workflow_baseline', 'workflow_monthly_walk_forward',
  'workflow_quarterly_matrix', 'backtest_ashare',
]) {
  assert(runner.includes(`"${action}"`), `Fixed Qlib action missing: ${action}`);
}
assert(runner.includes('review_note must contain 1-1000 characters'), 'Divergence review note must be bounded');

console.log('qlib control contract tests passed');

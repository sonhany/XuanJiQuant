import fs from 'node:fs';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';

const f5Runner = fs.readFileSync('scripts/f5_paper_runner.py', 'utf8');
const workbenchRoute = fs.readFileSync('server/routes/workbench.mjs', 'utf8');
const workbenchCache = fs.readFileSync('server/workbench-cache.mjs', 'utf8');
const dashboard = fs.readFileSync('components/DashboardPanel.tsx', 'utf8');
const executionPanel = fs.readFileSync('components/ExecutionPanel.tsx', 'utf8');

assert(f5Runner.includes('active_account_projection'), 'cockpit account must come from the F5 ledger projection');
assert(
  workbenchRoute.includes("{ action: 'account' }") && !workbenchRoute.includes('execution_runner.py'),
  'workbench must read the atomic F5 account projection',
);
assert(!dashboard.includes('mergeRuntimeStatus'), 'dashboard must not restore retired runtime state merging');
assert(
  executionPanel.includes('/api/paper-execution') && executionPanel.includes('Promise.all'),
  'execution page must request independent F5 projections in parallel',
);
assert(!executionPanel.includes('place_order'), 'execution page must not expose order submission');
assert(
  workbenchCache.includes("['targetPortfolio', syncPolicy('system_health').background_interval_ms]"),
  'target portfolio pointer must refresh on the health cadence instead of once per day',
);

const snapshotProbe = spawnSync(
  'python',
  ['-c', 'from scripts.f5_paper_runner import handle; result=handle({"action":"account"}); assert result.get("success") is True; assert result["data"]["ledger_authority"] == "f5"'],
  { cwd: process.cwd(), encoding: 'utf8', timeout: 10_000 },
);
assert.equal(snapshotProbe.status, 0, `F5 account snapshot failed: ${snapshotProbe.stderr}`);

console.log('cockpit latency contract tests passed');

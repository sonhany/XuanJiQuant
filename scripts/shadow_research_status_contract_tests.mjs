import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { loadShadowResearchStatus } from '../lib/shadow-research-status.mjs';
import { composeFastWorkbenchStatus } from '../server/routes/workbench.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function writeJson(file, payload) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(payload, null, 2), 'utf8');
}

const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'xuanji-shadow-status-'));

const missing = loadShadowResearchStatus(tempRoot);
assert.equal(missing.schema, 'xuanji-shadow-research-status-v1');
assert.equal(missing.status, 'baseline_missing');
assert.equal(missing.reason_code, 'baseline_result_missing');
assert.equal(missing.execution_authority, false);
assert.equal(missing.can_trigger_order, false);
assert.equal(missing.live_execution_authority, false);
assert.equal(missing.permissions.can_change_trade_policy, false);

const base = path.join(tempRoot, 'data', 'nautilus-baseline');
writeJson(path.join(base, 'baseline_result.json'), {
  schema: 'baseline-result-test',
  account_id: 'paper',
  live_execution_authority: false,
});
writeJson(path.join(base, 'baseline_result.meta.json'), {
  baseline_result_hash: 'a'.repeat(64),
});
let status = loadShadowResearchStatus(tempRoot);
assert.equal(status.status, 'runtime_summary_missing');
assert.equal(status.baseline.exists, true);
assert.equal(status.baseline.metadata_exists, true);
assert.equal(status.runtime_summary.exists, false);

writeJson(path.join(base, 'runtime_summary.json'), {
  schema: 'xuanji-shadow-runtime-summary-v1',
  mode: 'shadow_runtime_summary',
  execution_authority: false,
  live_execution_authority: false,
});
status = loadShadowResearchStatus(tempRoot);
assert.equal(status.status, 'shadow_ai_raw_output_missing');
assert.equal(status.runtime_summary.exists, true);

writeJson(path.join(base, 'ai_raw_output.json'), {
  schema: 'xuanji-shadow-ai-output-v1',
  mode: 'shadow_only',
  execution_authority: false,
  can_trigger_order: false,
});
writeJson(path.join(base, 'ai_raw_output.meta.json'), {
  runtime_summary_hash: 'b'.repeat(64),
});
status = loadShadowResearchStatus(tempRoot);
assert.equal(status.status, 'shadow_cycle_report_missing');
assert.equal(status.ai_raw_output.exists, true);
assert.equal(status.ai_raw_output.metadata_exists, true);

writeJson(path.join(base, 'shadow-daily', '20260916T093000Z', 'shadow_cycle_report.json'), {
  success: true,
  stage: 'shadow_research',
  report: {
    proposals: [
      { id: 'proposal-1' },
      { id: 'proposal-2' },
    ],
  },
});
fs.writeFileSync(path.join(base, 'shadow_decisions.sqlite3'), '', 'utf8');
status = loadShadowResearchStatus(tempRoot);
assert.equal(status.status, 'shadow_recorded');
assert.equal(status.shadow_cycle.report_exists, true);
assert.equal(status.shadow_cycle.total_proposals, 2);
assert.equal(status.shadow_store.exists, true);

const workbench = composeFastWorkbenchStatus({
  activeLedger: { ledger_authority: 'f5', ledger: 'paper', account: {}, positions: [] },
  risk: null,
  slow: { shadowResearch: status },
});
assert.equal(workbench.shadow_research.status, 'shadow_recorded');
assert.equal(workbench.shadow_research.execution_authority, false);
assert.equal(workbench.shadow_research.can_trigger_order, false);

const router = fs.readFileSync(path.join(root, 'server', 'router.mjs'), 'utf8');
const workbenchRoute = fs.readFileSync(path.join(root, 'server', 'routes', 'workbench.mjs'), 'utf8');
const dashboard = fs.readFileSync(path.join(root, 'components', 'DashboardPanel.tsx'), 'utf8');
const statusModule = fs.readFileSync(path.join(root, 'lib', 'shadow-research-status.mjs'), 'utf8');

assert(router.includes("'/api/workbench': new Set(['status'])"), 'shadow research status must stay inside the read-only workbench status action');
assert(workbenchRoute.includes('loadShadowResearchStatus'), 'workbench must load shadow research status');
assert(dashboard.includes('AI影子研究'), 'dashboard must expose recent shadow research status');
assert(dashboard.includes('shadow_research'), 'dashboard must render the workbench shadow_research payload');
assert(dashboard.includes('只读影子建议'), 'dashboard must label shadow output as read-only');

for (const [name, source] of Object.entries({ statusModule, dashboard })) {
  for (const forbidden of ['/api/execution', '/api/paper-execution', 'place_order', 'fill_order', 'cancel_order', 'agent_', 'run_intraday']) {
    assert(!source.includes(forbidden), `${name} must not expose execution or retired agent control: ${forbidden}`);
  }
}

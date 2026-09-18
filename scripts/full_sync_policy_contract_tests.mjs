import assert from 'node:assert/strict';
import fs from 'node:fs';

const policy = fs.readFileSync('lib/data-sync-policy.ts', 'utf8');
const jin10 = fs.readFileSync('components/Jin10DataPanel.tsx', 'utf8');
const cninfo = fs.readFileSync('components/CninfoDisclosurePanel.tsx', 'utf8');
const risk = fs.readFileSync('components/RiskPanel.tsx', 'utf8');
const alerts = fs.readFileSync('components/AlertPanel.tsx', 'utf8');
const financials = fs.readFileSync('components/FinancialStatementsPanel.tsx', 'utf8');
const router = fs.readFileSync('server/router.mjs', 'utf8');
const syncRunner = fs.readFileSync('scripts/sync_runner.py', 'utf8');

assert(policy.includes("from '../config/data_sync_policy.json'"), 'frontend policy must consume shared JSON');
assert(policy.includes('syncIntervalMs'), 'frontend policy must expose typed cadence lookup');
for (const name of ['jin10_flash', 'news_feed', 'finance_calendar', 'jin10_core_quotes', 'jin10_full_quotes']) {
  assert(jin10.includes(`syncIntervalMs('${name}'`), `Jin10 panel must use ${name} policy`);
}
assert(cninfo.includes("syncIntervalMs('cninfo_latest'"), 'CNINFO must use the shared disclosure cadence');
assert(risk.includes("syncIntervalMs('cockpit_risk'"), 'risk panel must use the shared risk cadence');
assert(alerts.includes("syncIntervalMs('alerts'"), 'alerts panel must use the shared alert cadence');
assert(!financials.includes('setInterval(refreshFinancials'), 'financial facts must not be fake-polled as realtime');
assert(router.includes("'catalog'"), 'sync catalog must be a read-only API action');
assert(syncRunner.includes('build_sync_catalog'), 'sync runner must expose the policy catalog');

console.log('full sync policy contracts passed');

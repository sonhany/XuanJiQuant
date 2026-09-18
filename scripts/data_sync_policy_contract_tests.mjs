import assert from 'node:assert/strict';
import fs from 'node:fs';

import { syncPolicy, syncPolicySnapshot } from '../server/sync-policy.mjs';

const raw = JSON.parse(fs.readFileSync('config/data_sync_policy.json', 'utf8'));
const snapshot = syncPolicySnapshot();

assert.equal(snapshot.schema_version, 'xuanji-data-sync-policy-v1');
assert.deepEqual(snapshot.datasets, raw.datasets, 'Node must consume the shared JSON authority');
assert.equal(syncPolicy('hot_quotes').active_interval_ms, 1000);
assert.equal(syncPolicy('market_top100').active_interval_ms, 8000);
assert.equal(syncPolicy('cockpit_risk').active_interval_ms, 2000);
assert.equal(syncPolicy('jin10_flash').active_interval_ms, 30000);
assert.equal(syncPolicy('cninfo_latest').active_interval_ms, 60000);
assert.equal(syncPolicy('cockpit_account').authority, 'f5_ledger');
assert.equal(syncPolicy('cockpit_account').execution_authority, false);
assert.throws(() => syncPolicy('not_registered'), /unknown sync dataset/);

console.log('data sync policy contracts passed');

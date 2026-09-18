import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const POLICY_PATH = path.join(ROOT, 'config', 'data_sync_policy.json');
const SCHEMA_VERSION = 'xuanji-data-sync-policy-v1';

const raw = JSON.parse(fs.readFileSync(POLICY_PATH, 'utf8'));
if (raw?.schema_version !== SCHEMA_VERSION || !raw?.datasets || typeof raw.datasets !== 'object') {
  throw new Error('data sync policy schema mismatch');
}

for (const [name, policy] of Object.entries(raw.datasets)) {
  for (const field of ['active_interval_ms', 'background_interval_ms', 'stale_after_ms', 'hard_floor_ms']) {
    if (!Number.isInteger(policy[field]) || policy[field] <= 0) {
      throw new Error(`data sync policy cadence must be positive: ${name}.${field}`);
    }
  }
  if (policy.active_interval_ms < policy.hard_floor_ms) {
    throw new Error(`data sync policy active interval is below hard floor: ${name}`);
  }
  if (policy.execution_authority !== false) {
    throw new Error(`data sync policy execution authority must be false: ${name}`);
  }
}

export function syncPolicy(name) {
  const value = raw.datasets[String(name || '')];
  if (!value) throw new Error(`unknown sync dataset: ${name}`);
  return structuredClone(value);
}

export function syncPolicySnapshot() {
  return structuredClone(raw);
}

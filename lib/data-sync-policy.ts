import policy from '../config/data_sync_policy.json';

type Phase = 'active' | 'background';

export function syncIntervalMs(name: string, phase: Phase = 'active'): number {
  const row = (policy as any)?.datasets?.[name];
  if (!row) throw new Error(`unknown sync dataset: ${name}`);
  const value = Number(phase === 'background' ? row.background_interval_ms : row.active_interval_ms);
  const floor = Number(row.hard_floor_ms);
  if (!Number.isFinite(value) || value <= 0 || value < floor) {
    throw new Error(`invalid sync cadence: ${name}`);
  }
  return value;
}

export function syncPolicySnapshot() {
  return structuredClone(policy);
}

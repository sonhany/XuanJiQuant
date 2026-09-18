/**
 * Factor 因子引擎 API 路由 — 持久化 Python 进程
 * 47因子计算 + IC 评估
 */
import { PersistentRunner } from '../persistent_runner.mjs';
import { log, json, readBody } from '../http-utils.mjs';

const runner = new PersistentRunner('factor_runner.py');
runner.prewarm();
const BUSINESS_GATE_REASONS = new Set([
  'factor_snapshot_stale',
  'factor_snapshot_missing',
  'factor_snapshot_not_passed',
  'factor_input_snapshot_unavailable',
  'factor_evaluation_version_mismatch',
  'factor_projection_version_mismatch',
]);

export async function handleFactor(req, res) {
  const body = await readBody(req);
  log('INFO', `[Factor] action=${body.action || 'meta'}`);
  try {
    runner.ensure();
    const data = await runner.call(body);
    return json(res, data.success || BUSINESS_GATE_REASONS.has(data.reason_code) ? 200 : 500, data);
  } catch (e) {
    return json(res, 500, { success: false, error: `引擎异常: ${e.message}` });
  }
}

/**
 * Stock valuation research API.
 *
 * Deterministic tracks are read-only. GLM analysis remains a protected
 * control-plane action because it consumes model quota and writes audit data.
 */
import { PersistentRunner } from '../persistent_runner.mjs';
import { log, json, readBody } from '../http-utils.mjs';

const runner = new PersistentRunner('valuation_runner.py');

export async function handleValuation(req, res) {
  const body = await readBody(req);
  log('INFO', `[Valuation] action=${body.action || 'latest'} code=${body.code || ''}`);
  try {
    const timeout = body.action === 'glm_analyze' ? 150000 : 90000;
    const data = await runner.call(body, timeout);
    return json(res, data.success ? 200 : Number(data.status || 500), data);
  } catch (error) {
    return json(res, 500, {
      success: false,
      error: `估值服务异常: ${String(error?.message || error).slice(0, 300)}`,
    });
  }
}

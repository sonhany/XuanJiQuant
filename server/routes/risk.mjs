/**
 * Risk 风控与监控 API 路由 — 持久化 Python 进程
 */
import { PersistentRunner } from '../persistent_runner.mjs';
import { log, json, readBody } from '../http-utils.mjs';

const runner = new PersistentRunner('risk_runner.py');
runner.ensure();

export async function handleRisk(req, res) {
  const body = await readBody(req);
  log('INFO', `[Risk] action=${body.action || 'system_health'}`);
  try {
    runner.ensure();
    const data = await runner.call(body);
    return json(res, data.success ? 200 : 400, data);
  } catch (e) {
    return json(res, 500, { success: false, error: `引擎异常: ${e.message}` });
  }
}

/**
 * Factor 因子引擎 API 路由 — 持久化 Python 进程
 * 47因子计算 + IC 评估
 */
import { PersistentRunner } from '../persistent_runner.mjs';
import { log, json, readBody } from '../http-utils.mjs';

const runner = new PersistentRunner('factor_runner.py');
runner.ensure(); // warm up at import

export async function handleFactor(req, res) {
  const body = await readBody(req);
  log('INFO', `[Factor] action=${body.action || 'meta'}`);
  try {
    runner.ensure();
    const data = await runner.call(body);
    return json(res, data.success ? 200 : 500, data);
  } catch (e) {
    return json(res, 500, { success: false, error: `引擎异常: ${e.message}` });
  }
}

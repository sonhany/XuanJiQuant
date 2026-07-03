/**
 * Strategy 策略引擎 API 路由 — 持久化 Python 进程
 * 4 种内置策略 + 回测
 */
import { PersistentRunner } from '../persistent_runner.mjs';
import { log, json, readBody } from '../http-utils.mjs';

const runner = new PersistentRunner('strategy_runner.py');
runner.ensure();

export async function handleStrategy(req, res) {
  const body = await readBody(req);
  log('INFO', `[Strategy] action=${body.action || 'meta'}`);
  try {
    runner.ensure();
    const data = await runner.call(body);
    return json(res, data.success ? 200 : 500, data);
  } catch (e) {
    return json(res, 500, { success: false, error: `引擎异常: ${e.message}` });
  }
}

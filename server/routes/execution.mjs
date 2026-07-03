/**
 * Execution 模拟交易执行 API 路由 — 持久化 Python 进程
 */
import { PersistentRunner } from '../persistent_runner.mjs';
import { log, json, readBody } from '../http-utils.mjs';

const runner = new PersistentRunner('execution_runner.py');
runner.ensure();

export async function handleExecution(req, res) {
  const body = await readBody(req);
  log('INFO', `[Execution] action=${body.action || 'status'}`);
  try {
    runner.ensure();
    const data = await runner.call(body, 30000);
    // 业务拒单属于正常交易结果，保持 HTTP 200，避免浏览器控制台报 500 资源错误。
    return json(res, 200, data);
  } catch (e) {
    return json(res, 500, { success: false, error: `引擎异常: ${e.message}` });
  }
}

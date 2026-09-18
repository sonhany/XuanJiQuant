/**
 * Execution 只读兼容 API — 所有当前事实来自唯一 F5 模拟账本。
 */
import { PersistentRunner } from '../persistent_runner.mjs';
import { log, json, readBody } from '../http-utils.mjs';

const runner = new PersistentRunner('f5_paper_runner.py');
const READ_ONLY_ACTIONS = new Set(['all', 'status', 'positions', 'orders', 'trades']);

export async function handleExecution(req, res) {
  const body = await readBody(req);
  log('INFO', `[Execution] action=${body.action || 'status'}`);
  if (!READ_ONLY_ACTIONS.has(body.action || 'status')) {
    return json(res, 409, {
      success: false,
      error: '任意交易动作已关闭；当前只允许读取统一 F5 模拟账本',
      reason: 'automatic_execution_disabled',
    });
  }
  try {
    runner.ensure();
    const action = body.action || 'status';
    const mappedAction = action === 'all' || action === 'status'
      ? 'account'
      : action === 'trades'
        ? 'fills'
        : action;
    const data = await runner.call({ ...body, action: mappedAction }, 30000);
    return json(res, 200, data);
  } catch (e) {
    return json(res, 500, { success: false, error: `引擎异常: ${e.message}` });
  }
}

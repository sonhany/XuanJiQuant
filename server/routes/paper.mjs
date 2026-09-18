/** 模拟盘只读 API：自动交易退役后仅提供配置、历史状态、日志和日报。 */
import { PersistentRunner } from '../persistent_runner.mjs';
import { json, readBody } from '../http-utils.mjs';

const runner = new PersistentRunner('paper_runner.py');
const ALLOWED_ACTIONS = new Set(['status', 'get_config', 'set_config', 'progress', 'log', 'report', 'benchmark']);

export async function handlePaper(req, res) {
  const body = await readBody(req);
  const action = body.action || 'status';
  if (!ALLOWED_ACTIONS.has(action)) {
    return json(res, 409, {
      success: false,
      error: '自动模拟交易与智能体控制面已删除；当前仅保留只读账本',
      reason: 'automatic_execution_disabled',
    });
  }
  try {
    const result = await runner.call({ ...body, action }, action === 'report' ? 60_000 : 12_000);
    if (action === 'status' && result?.success !== false) {
      const data = result?.data || result || {};
      return json(res, 200, {
        success: true,
        data: {
          ...data,
          daemon: { running: false, retired: true },
          automatic_execution: { enabled: false, reason: 'automatic_execution_disabled' },
        },
      });
    }
    return json(res, result?.success === false ? 503 : 200, result);
  } catch (error) {
    return json(res, 503, { success: false, error: error.message, reason: 'paper_read_unavailable' });
  }
}

/** F5 deterministic, simulation-only paper execution API. */
import { PersistentRunner } from '../persistent_runner.mjs';
import { json, readBody } from '../http-utils.mjs';

const runner = new PersistentRunner('f5_paper_runner.py');
const READ_ACTIONS = new Set(['status', 'account', 'runs', 'orders', 'fills', 'positions', 'equity', 'reconciliations', 'audit']);
const CONTROL_ACTIONS = new Set(['set_enabled', 'set_kill_switch', 'run_due', 'run_intraday']);

export async function handlePaperExecution(req, res) {
  const body = await readBody(req);
  const action = body.action || 'status';
  if (!READ_ACTIONS.has(action) && !CONTROL_ACTIONS.has(action)) {
    return json(res, 409, {
      success: false,
      reason: 'arbitrary_order_action_forbidden',
      error: 'F5 仅接受确定性到期周期，禁止任意下单、填单或撤单',
      execution_mode: 'paper_daily',
      live_execution_authority: false,
    });
  }
  try {
    runner.ensure();
    const result = await runner.call({ ...body, action }, ['run_due', 'run_intraday'].includes(action) ? 120_000 : 15_000);
    return json(res, result?.success === false ? 409 : 200, result);
  } catch (error) {
    return json(res, 503, {
      success: false,
      reason: 'f5_runner_unavailable',
      error: error.message,
      live_execution_authority: false,
    });
  }
}

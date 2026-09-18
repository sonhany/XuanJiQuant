/**
 * Qlib research API route.
 *
 * Lightweight bridge for the standalone Qlib research page. Heavy work runs
 * in detached .venv-qlib workers, never inside the HTTP request.
 */
import { PersistentRunner } from '../persistent_runner.mjs';
import { log, json, readBody } from '../http-utils.mjs';

const runner = new PersistentRunner('qlib_runner.py');
runner.prewarm();

export async function handleQlib(req, res) {
  const body = await readBody(req);
  log('INFO', `[Qlib] action=${body.action || 'status'}`);
  try {
    runner.ensure();
    const data = await runner.call(body, 30000);
    return json(res, data.success ? 200 : 500, data);
  } catch (e) {
    return json(res, 500, { success: false, error: `Qlib 研究服务异常：${e.message}` });
  }
}

/**
 * Alert Routes — /api/alerts
 */
import { PersistentRunner } from '../persistent_runner.mjs';
import { log, json, readBody } from '../http-utils.mjs';

const runner = new PersistentRunner('alert_runner.py');
runner.ensure();

export async function handleAlerts(req, res) {
  const parsed = await readBody(req);
  const action = parsed.action || 'list';
  log('INFO', `[Alerts] action=${action}`);
  try {
    runner.ensure();
    const data = await runner.call(parsed, 15000);
    return json(res, data.success ? 200 : 500, data);
  } catch (e) {
    return json(res, 500, { success: false, error: `alert engine error: ${e.message}` });
  }
}

/**
 * Alert Routes — /api/alerts
 */
import { PersistentRunner } from '../persistent_runner.mjs';
import { log, json } from '../http-utils.mjs';

const runner = new PersistentRunner('alert_runner.py');
runner.ensure();

export async function handleAlerts(req, res) {
  let body = '';
  req.on('data', chunk => { body += chunk; });
  await new Promise(resolve => req.on('end', resolve));
  let parsed = {};
  try { parsed = body ? JSON.parse(body) : {}; } catch (_) {}
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

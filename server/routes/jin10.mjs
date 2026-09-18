import { PersistentRunner } from '../persistent_runner.mjs';
import { log, json, readBody } from '../http-utils.mjs';

const runner = new PersistentRunner('jin10_runner.py');

export async function handleJin10(req, res) {
  const body = await readBody(req);
  log('INFO', `[Jin10] action=${body.action || 'status'}`);
  try {
    runner.ensure();
    const isBulkRead = body.action === 'quotes'
      || ((body.action === 'flash' || body.action === 'news') && Number(body.pages || 1) > 1);
    const data = await runner.call(body, isBulkRead ? 90000 : 30000);
    return json(res, data.success ? 200 : 500, data);
  } catch (e) {
    return json(res, 500, { success: false, error: `Jin10 MCP error: ${e.message}` });
  }
}

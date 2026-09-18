import { PersistentRunner } from '../persistent_runner.mjs';
import { json, log, readBody } from '../http-utils.mjs';

const queryRunner = new PersistentRunner('cninfo_runner.py', 'cninfo-query');
const detailRunner = new PersistentRunner('cninfo_runner.py', 'cninfo-detail');

export async function handleCninfo(req, res) {
  const body = await readBody(req);
  log('INFO', `[CNINFO] action=${body.action || 'query'} preset=${body.preset || 'latest'}`);
  try {
    const runner = body.action === 'detail' ? detailRunner : queryRunner;
    runner.ensure();
    const data = await runner.call(body, body.action === 'detail' ? 60_000 : 45_000);
    return json(res, data.success ? 200 : 502, data);
  } catch (error) {
    return json(res, 502, {
      success: false,
      error: `CNINFO disclosure error: ${error.message}`,
    });
  }
}

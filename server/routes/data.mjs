/**
 * Data 数据层 API 路由 — 持久化 Python 进程
 * 股票列表 + Kline 查询 + Redis 状态
 */
import { PersistentRunner } from '../persistent_runner.mjs';
import { log, json, readBody } from '../http-utils.mjs';

const runner = new PersistentRunner('data_runner.py');
runner.ensure();

export async function handleData(req, res) {
  let body;
  if (req.method === 'GET') {
    // GET 请求: 从 query string 解析参数 (执行面板取价用 GET /api/data?action=klines&code=xxx)
    const url = new URL(req.url, 'http://localhost');
    body = { action: url.searchParams.get('action') || 'stats' };
    for (const [k, v] of url.searchParams) {
      if (k !== 'action') body[k] = v;
    }
  } else {
    body = await readBody(req);
  }
  log('INFO', `[Data] ${req.method} action=${body.action || 'stats'}`);
  try {
    const data = await runner.call(body);
    return json(res, data.success ? 200 : 500, data);
  } catch (e) {
    return json(res, 500, { success: false, error: `数据层异常: ${e.message}` });
  }
}

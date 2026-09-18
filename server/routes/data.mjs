/**
 * Data 数据层 API 路由 — 持久化 Python 进程
 * 股票列表 + Kline 查询 + Redis 状态
 */
import { dataReadRunner, dataRealtimeRunner, dataStocksRunner } from '../data-runners.mjs';
import { log, json, readBody } from '../http-utils.mjs';
import { handleTickCollectorAction } from '../tick_collector_manager.mjs';

function runnerForAction(action) {
  if (action === 'hot_snapshot') return dataRealtimeRunner;
  if (action === 'realtime_prices') return dataRealtimeRunner;
  if (action === 'stocks') return dataStocksRunner;
  return dataReadRunner;
}

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
    const collector = handleTickCollectorAction(body.action || 'stats', body);
    if (collector) {
      const status = collector.success ? 200 : 500;
      return json(res, status, collector);
    }
    let data;
    const runner = runnerForAction(body.action);
    try {
      data = await runner.call(body);
    } catch (e) {
      if (!String(e.message || '').includes('response id mismatch')) throw e;
      log('WARN', `[Data] runner protocol mismatch; restarting and retrying once`);
      runner.restart();
      data = await runner.call(body);
    }
    const status = data.success ? 200 : (Number(data.status) || 500);
    return json(res, status, data);
  } catch (e) {
    return json(res, 500, { success: false, error: `数据层异常: ${e.message}` });
  }
}

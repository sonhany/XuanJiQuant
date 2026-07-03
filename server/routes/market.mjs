/**
 * 市场行情路由 — 已统一代理到 Python 数据层 (data_runner.py)
 *
 * 数据层统一后, 本路由不再有自己的抓取代码:
 *   - 所有行情数据走 data_runner (PersistentRunner) → market_data.py
 *   - 保留路由兼容 (顶栏 LiveIndexBar / 旧调用方仍可用 /api/market)
 *   - 已删除 Node 侧 Sina fetcher (fetchSinaPrices) 和 data-source.js 依赖
 *
 * GET  /api/market/indices          — 顶栏指数 (代理 data_runner {action:'realtime_prices'})
 * POST /api/market {action}         — realtime_prices / sector_flow / northbound (代理 data_runner)
 */
import { PersistentRunner } from '../persistent_runner.mjs';
import { json, readBody } from '../http-utils.mjs';

// 复用 data.mjs 的同一个 data_runner 实例 (单例, 避免起两个 Python 进程)
// 注: PersistentRunner 内部按 scriptName 去重, 同名只起一个进程
const runner = new PersistentRunner('data_runner.py');
runner.ensure();

export async function handleRealtimeIndices(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Content-Type', 'application/json');

  if (req.method === 'OPTIONS') { res.end(); return; }

  // POST: realtime_prices / sector_flow / northbound — 全部代理 data_runner
  if (req.method === 'POST') {
    const body = await readBody(req);
    const parsed = body && typeof body === 'object' ? body : {};
    try {
      const data = await runner.call(parsed, 15000);
      return json(res, 200, data);
    } catch (e) {
      return json(res, 500, { success: false, error: e.message });
    }
  }

  // GET /api/market/indices — 顶栏 LiveIndexBar 用
  // 代理到 data_runner {action:'realtime_prices', codes: [A股大盘指数]}
  if (req.method === 'GET') {
    const INDICES = [
      { name: '上证指数', code: 'sh000001' },
      { name: '深证成指', code: 'sz399001' },
      { name: '创业板', code: 'sz399006' },
      { name: '沪深300', code: 'sh000300' },
      { name: '中证500', code: 'sh000905' },
      { name: '科创50', code: 'sh000688' },
    ];
    try {
      const rt = await runner.call({ action: 'realtime_prices', codes: INDICES.map(i => i.code) }, 10000);
      const rtData = (rt && rt.success && rt.data) ? rt.data : {};
      const data = INDICES.map(idx => {
        const q = rtData[idx.code] || {};
        return {
          ...idx,
          name: q.name || idx.name,
          price: q.price || 0,
          open: q.open || 0,
          close: q.close || 0,
          high: q.high || 0,
          low: q.low || 0,
          volume: q.volume || 0,
          amount: q.amount || 0,
          chg_pct: q.chg_pct || 0,
          time: q.time || '',
        };
      });
      return json(res, 200, { success: true, data });
    } catch (e) {
      return json(res, 500, { success: false, error: e.message });
    }
  }

  return json(res, 405, { success: false, error: 'method not allowed' });
}

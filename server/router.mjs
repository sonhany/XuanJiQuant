/**
 * 路由分发器 — 5 层量化架构 + 数据层
 * Layer 1: 数据层 /api/data
 * Layer 2: 因子层 /api/factor
 * Layer 3: 策略层 /api/strategy
 * Layer 4: 执行层 /api/execution
 * Layer 5: 风控层 /api/risk
 */
import { json, serveStatic, wrapResponseLogging } from './http-utils.mjs';
import { handleData } from './routes/data.mjs';
import { handleFactor } from './routes/factor.mjs';
import { handleStrategy } from './routes/strategy.mjs';
import { handleExecution } from './routes/execution.mjs';
import { handleAlerts } from './routes/alerts.mjs';
import { handleRisk } from './routes/risk.mjs';
import { handleRealtimeIndices } from './routes/market.mjs';
import { handleSync } from './routes/sync.mjs';
import { handlePaper } from './routes/paper.mjs';

export function createRouter() {
  return function router(req, res) {
    wrapResponseLogging(req, res);

    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    if (req.method === 'OPTIONS') return res.end();

    const url = new URL(req.url, 'http://localhost');
    const pathname = url.pathname;

    // GET: static files + index data query
    if (req.method === 'GET') {
      // 数据查询: 支持 GET /api/data?action=klines&code=xxx (执行面板取价用)
      //          和 GET /api/data/klines (兼容旧路径)
      if (pathname === '/api/data' || pathname === '/api/data/klines') return handleData(req, res);
      if (pathname === '/api/market/indices') return handleRealtimeIndices(req, res);
      if (serveStatic(req, res, pathname)) return;
      return json(res, 404, { error: 'Not found' });
    }

    if (req.method !== 'POST') return json(res, 405, { error: 'Method not allowed' });

    // POST: 5 layer API + market endpoints
    const handlers = {
      '/api/data':       handleData,
      '/api/factor':    handleFactor,
      '/api/strategy':  handleStrategy,
      '/api/execution': handleExecution,
      '/api/risk':      handleRisk,
      '/api/alerts':    handleAlerts,
      '/api/market':    handleRealtimeIndices,  // POST {action:"realtime_prices",codes:["000001.SZ"]}
      '/api/sync':      handleSync,
      '/api/paper':     handlePaper,
    };

    const handler = handlers[pathname];
    if (handler) return handler(req, res);

    json(res, 404, { error: 'Not found' });
  };
}

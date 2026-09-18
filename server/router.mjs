/**
 * 路由分发器 — 5 层量化架构 + 数据层
 * Layer 1: 数据层 /api/data
 * Layer 2: 因子层 /api/factor
 * Layer 3: 策略层 /api/strategy
 * Layer 4: 执行层 /api/execution
 * Layer 5: 风控层 /api/risk
 */
import { json, readBody, serveStatic, wrapResponseLogging } from './http-utils.mjs';
import { ALLOWED_ORIGINS, API_TOKEN } from './config.mjs';
import { handleData } from './routes/data.mjs';
import { handleFactor } from './routes/factor.mjs';
import { handleStrategy } from './routes/strategy.mjs';
import { handleExecution } from './routes/execution.mjs';
import { handleAlerts } from './routes/alerts.mjs';
import { handleRisk } from './routes/risk.mjs';
import { handleRealtimeIndices } from './routes/market.mjs';
import { handleSync } from './routes/sync.mjs';
import { handlePaper } from './routes/paper.mjs';
import { handleJin10 } from './routes/jin10.mjs';
import { handleCninfo } from './routes/cninfo.mjs';
import { handleQlib } from './routes/qlib.mjs';
import { handleValuation } from './routes/valuation.mjs';
import { handleWorkbench } from './routes/workbench.mjs';
import { handlePaperExecution } from './routes/paper-execution.mjs';
import { handleMarketStream } from './routes/market-stream.mjs';

const READ_ONLY_ACTIONS = {
  '/api/workbench': new Set(['status']),
  '/api/data': new Set(['stocks', 'klines', 'financials', 'stats', 'realtime_prices', 'hot_snapshot', 'indices', 'sector_flow', 'northbound', 'ticks', 'tick_probe', 'tick_collector_status', 'watchlist_get']),
  '/api/factor': new Set(['meta', 'factors', 'market_eval', 'market_evaluation', 'factor_stocks']),
  '/api/strategy': new Set(['meta', 'market_scan', 'research_selection']),
  '/api/execution': new Set(['all', 'status', 'positions', 'orders', 'trades']),
  '/api/risk': new Set(['portfolio_risk', 'system_health', 'system_log', 'audit_replays', 'audit_replay', 'decision_trace', 'audit_logs']),
  '/api/alerts': new Set(['list', 'rules', 'stats']),
  '/api/market': new Set(['realtime_prices', 'indices', 'sector_flow', 'northbound']),
  '/api/jin10': new Set(['status', 'tools', 'resources', 'codes']),
  '/api/cninfo': new Set(['query', 'detail', 'status']),
    '/api/qlib': new Set([
      'status', 'catalog', 'datasets', 'jobs',
      'experiments', 'models', 'reports', 'job_log',
      'quality_reports', 'workflow_runs', 'backtests', 'schedule_status',
    ]),
  '/api/valuation': new Set(['analyze', 'latest']),
  '/api/sync': new Set(['status', 'health', 'catalog', 'stream_status', 'progress', 'update_progress', 'daemon_status']),
  '/api/paper': new Set([
    'status', 'get_config', 'progress', 'log', 'report', 'benchmark',
  ]),
  '/api/paper-execution': new Set([
    'status', 'account', 'runs', 'orders', 'fills', 'positions', 'equity',
    'reconciliations', 'audit',
  ]),
};

function isLocalRequest(req) {
  const addr = req.socket?.remoteAddress || '';
  return addr === '127.0.0.1' || addr === '::1' || addr === '::ffff:127.0.0.1';
}

function setCors(req, res) {
  const origin = req.headers.origin;
  if (!origin) return;
  if (ALLOWED_ORIGINS.includes(origin) || (origin === 'null' && isLocalRequest(req))) {
    res.setHeader('Access-Control-Allow-Origin', origin);
    res.setHeader('Vary', 'Origin');
  }
}

function isReadOnly(pathname, body) {
  const action = body?.action || 'status';
  return !!READ_ONLY_ACTIONS[pathname]?.has(action);
}

function tokenValid(req, body) {
  return !!API_TOKEN && (req.headers['x-xuanji-token'] === API_TOKEN || body?.token === API_TOKEN);
}

function authorizedControlRequest(req, pathname, body) {
  if (isReadOnly(pathname, body)) return true;
  const origin = req.headers.origin;
  if (origin && !ALLOWED_ORIGINS.includes(origin)) return false;
  const contentType = String(req.headers['content-type'] || '').toLowerCase();
  if (!contentType.includes('application/json')) return false;
  if (!isLocalRequest(req)) return false;
  return tokenValid(req, body);
}

export function createRouter() {
  return async function router(req, res) {
    wrapResponseLogging(req, res);

    setCors(req, res);
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, X-XuanJi-Token');

    if (req.method === 'OPTIONS') return res.end();

    const url = new URL(req.url, 'http://localhost');
    const pathname = url.pathname;

    // GET: static files + index data query
    if (req.method === 'GET') {
      if (pathname === '/api/market-stream') return handleMarketStream(req, res);
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
      '/api/jin10':     handleJin10,
      '/api/cninfo':   handleCninfo,
      '/api/qlib':      handleQlib,
      '/api/valuation': handleValuation,
      '/api/sync':      handleSync,
      '/api/paper':     handlePaper,
      '/api/workbench': handleWorkbench,
      '/api/paper-execution': handlePaperExecution,
    };

    const handler = handlers[pathname];
    if (handler) {
      let body;
      try {
        body = await readBody(req);
      } catch (error) {
        const status = Number(error?.statusCode) || 400;
        return json(res, status, { success: false, error: error?.message || 'invalid request body' });
      }
      if (!authorizedControlRequest(req, pathname, body)) {
        return json(res, 403, { success: false, error: '控制面请求未授权: 请使用本机、JSON Content-Type 并配置/发送 XUANJI_API_TOKEN' });
      }
      if (pathname === '/api/paper') {
        return handlePaper(req, res);
      }
      return handler(req, res);
    }

    json(res, 404, { error: 'Not found' });
  };
}

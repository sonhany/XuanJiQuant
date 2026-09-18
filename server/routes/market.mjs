/**
 * Market data route.
 *
 * GET  /api/market/indices returns top-bar index quotes.
 * POST /api/market proxies market actions to data_runner.py.
 */
import { PersistentRunner } from '../persistent_runner.mjs';
import { json, readBody } from '../http-utils.mjs';

const runner = new PersistentRunner('data_runner.py', 'market-indices');

const INDICES = [
  { name: '上证指数', code: 'sh000001' },
  { name: '深证成指', code: 'sz399001' },
  { name: '创业板', code: 'sz399006' },
  { name: '沪深300', code: 'sh000300' },
  { name: '中证500', code: 'sh000905' },
  { name: '科创50', code: 'sh000688' },
];

const INDICES_CACHE_TTL_MS = Number(process.env.XUANJI_INDICES_CACHE_TTL_MS || 3000);
let indicesCache = null;
let indicesCacheAt = 0;
let indicesInflight = null;

function fallbackIndices() {
  return INDICES.map(idx => ({
    ...idx,
    price: 0,
    open: 0,
    close: 0,
    high: 0,
    low: 0,
    volume: 0,
    amount: 0,
    chg_pct: 0,
    time: '',
    source: 'fallback',
    amount_source: '',
    volume_unit: '',
    stale: true,
  }));
}

async function loadRealtimeIndices() {
  const now = Date.now();
  if (indicesCache && now - indicesCacheAt < INDICES_CACHE_TTL_MS) {
    return indicesCache;
  }
  if (indicesInflight) {
    return indicesInflight;
  }

  indicesInflight = runner
    .call({ action: 'realtime_prices', codes: INDICES.map(i => i.code), force_refresh: true }, 10000)
    .then((rt) => {
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
          source: q.source || '',
          amount_source: q.amount_source || '',
          volume_unit: q.volume_unit || '',
        };
      });
      indicesCache = data;
      indicesCacheAt = Date.now();
      return data;
    })
    .finally(() => {
      indicesInflight = null;
    });

  return indicesInflight;
}

function scheduleRealtimeIndicesRefresh() {
  if (indicesInflight) return false;
  indicesInflight = runner
    .call({ action: 'realtime_prices', codes: INDICES.map(i => i.code), force_refresh: true }, 10000)
    .then((rt) => {
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
          source: q.source || '',
          amount_source: q.amount_source || '',
          volume_unit: q.volume_unit || '',
        };
      });
      indicesCache = data;
      indicesCacheAt = Date.now();
      return data;
    })
    .catch(() => indicesCache || fallbackIndices())
    .finally(() => {
      indicesInflight = null;
    });
  return true;
}

export async function handleRealtimeIndices(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Content-Type', 'application/json');

  if (req.method === 'OPTIONS') {
    res.end();
    return;
  }

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

  if (req.method === 'GET') {
    try {
      const now = Date.now();
      if (indicesCache && now - indicesCacheAt < INDICES_CACHE_TTL_MS) {
        return json(res, 200, { success: true, data: indicesCache });
      }
      const refreshScheduled = scheduleRealtimeIndicesRefresh();
      if (indicesCache) {
        return json(res, 200, { success: true, data: indicesCache, stale: true, refreshing: true });
      }
      return json(res, 200, { success: true, data: fallbackIndices(), stale: true, refreshing: refreshScheduled });
    } catch (e) {
      const data = indicesCache || fallbackIndices();
      return json(res, 200, { success: true, data, warning: e.message });
    }
  }

  return json(res, 405, { success: false, error: 'method not allowed' });
}

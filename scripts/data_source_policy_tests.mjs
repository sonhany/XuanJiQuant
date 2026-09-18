const API_BASE = process.env.API_BASE || 'http://127.0.0.1:8880';

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function post(path, body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const json = await res.json();
  return { status: res.status, json };
}

async function testSourcePolicyIsExplicit() {
  const res = await post('/api/data', { action: 'stats' });
  assert(res.status === 200 && res.json.success, `stats expected success, got ${res.status}`);
  const policy = res.json.data?.source_policy || {};
  assert(policy.realtime_primary === 'tdx_quant', 'realtime primary source should be tdx_quant');
  assert(JSON.stringify(policy.realtime_fallbacks) === JSON.stringify(['sina', 'tencent']), 'realtime fallback sources should be sina then tencent');
  assert(policy.kline_primary === 'tdx_quant', 'kline primary source should be tdx_quant');
  assert(policy.kline_cross_check === 'tencent', 'kline cross-check source should be tencent');
  assert(JSON.stringify(policy.kline_fallbacks) === JSON.stringify(['sina', 'baostock']), 'kline fallback sources should be sina then baostock');
  assert(policy.minute_kline_primary === 'tdx_quant', 'minute kline primary source should be tdx_quant');
  assert(policy.minute_kline_fallback === 'tencent', 'minute kline fallback source should be tencent');
  assert(policy.realtime_store === 'sqlite', 'realtime store should be sqlite');
  assert(policy.historical_store === 'sqlite', 'active historical store should be SQLite');
  assert(policy.historical_store_target === 'clickhouse', 'ClickHouse should remain an explicit migration target');
  assert(policy.historical_store_target_deployed === false, 'ClickHouse target must not be reported as deployed');
}

async function testRealtimeKeepsStockAndIndexSeparate() {
  const res = await post('/api/data', { action: 'realtime_prices', codes: ['000001', 'sh000001'] });
  assert(res.status === 200 && res.json.success, `realtime expected success, got ${res.status}`);
  const data = res.json.data || {};
  assert(data.sz000001, 'realtime should include stock sz000001 for plain 000001');
  assert(data.sh000001, 'realtime should include index sh000001');
  assert(data.sz000001.name, 'sz000001 should have a name');
  assert(data.sh000001.name, 'sh000001 should have a name');
  assert(data.sz000001.name !== data.sh000001.name, 'stock 000001 and index sh000001 should not share cached quote/name');
  assert(data.sz000001.name !== '上证指数', 'stock 000001 should not be polluted by sh000001 cache');
  assert(['tdx_quant', 'sina', 'tencent'].includes(String(data.sz000001.source || '').replace(/^cache:/, '')), 'stock quote should declare tdx_quant/sina/tencent source');
}

await testSourcePolicyIsExplicit();
await testRealtimeKeepsStockAndIndexSeparate();

console.log('data source policy tests passed');

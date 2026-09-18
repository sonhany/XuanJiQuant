import fs from 'fs';

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

function testMarketBrowseRequestsTop100ByAmount() {
  const src = fs.readFileSync('components/DbPanel.tsx', 'utf-8');
  const runner = fs.readFileSync('scripts/data_runner.py', 'utf-8');
  assert(src.includes("limit: 100, sort_by: 'amount'"), 'market browse should request TOP100 by amount');
  assert(!src.includes('force_refresh: true'), 'market browse polling must not bypass realtime top cache on every interval');
  assert(src.includes('refresh_if_stale: true'), 'market browse should allow stale-cache refresh without forcing every poll');
  assert(src.includes('stocksLoadingRef'), 'market browse should skip overlapping stock-list requests');
  assert(runner.includes('REALTIME_TOP_STALE_KEY'), 'market browse backend should keep stale top cache for fast first paint');
  assert(runner.includes('_schedule_top_refresh'), 'market browse backend should refresh stale top cache in background');
  assert(src.includes('成交额前 100'), 'market browse label should describe the TOP100 ranking in Chinese');
  assert(src.includes("'代码'") && src.includes("'名称'") && src.includes("'最新价'") && src.includes("'涨跌幅'") && src.includes("'成交量'") && src.includes("'成交额'"), 'market browse Top100 table should include latest price column without removing existing columns');
  assert(src.includes("'涨跌额'") && src.includes("'振幅'"), 'market browse Top100 table should include change amount and amplitude columns for pro charting');
  assert(src.includes('s.price') && src.includes('toFixed(2)'), 'market browse Top100 latest price column should render stock price');
  assert(/price:\s+Number\(s\.price \?\? 0\)/.test(src), 'market browse should preserve API stock price when normalizing Top100 rows');
  assert(src.includes('turnover_rate') && src.includes('main_net_inflow') && src.includes('main_net_inflow_pct'), 'market browse should normalize all market metric fields');
  assert(src.includes("label: '换手率'") && src.includes("label: '主力净流入'") && src.includes("label: '主力净占比'"), 'market browse should render three sortable metric columns');
  assert(src.includes("'换手率','主力净流入','主力净占比'"), 'market browse CSV should export the three metrics');
  assert(src.includes("overflowX: 'auto'") && src.includes('minWidth:'), 'market browse table should remain usable with the detail panel open');
  assert(src.includes('资金流：东方财富') && src.includes('换手率：东方财富/腾讯降级'), 'market browse should document field provenance');
}

function testRealtimePanelDocumentsTdxQuantFirst() {
  const src = fs.readFileSync('components/DbPanel.tsx', 'utf-8');
  assert(src.includes('TdxQuant优先 / 新浪腾讯兜底'), 'realtime panel should show TdxQuant-first source policy');
  assert(!src.includes('新浪主源 / 腾讯备用'), 'realtime panel must not claim Sina is the primary source');
}

function testReadmeDocumentsMarketMetricDataFlow() {
  const readme = fs.readFileSync('README.md', 'utf-8');
  assert(readme.includes('市场浏览 Top100 与资金流补充链路'), 'README should name the market metric data flow');
  assert(readme.includes('DbPanel') && readme.includes('server/routes/data.mjs') && readme.includes('data_runner.py::action_stocks'), 'README should trace the market browser through Node and Python');
  assert(readme.includes('fetch_stock_market_metrics') && readme.includes('main_net_inflow') && readme.includes('turnover_rate'), 'README should document implementation entry points and response fields');
  assert(readme.includes('东方财富不接管行情主源') && readme.includes('腾讯只补换手率'), 'README should preserve source and fallback boundaries');
}

async function testKlinesReturnCodeAndName() {
  const res = await post('/api/data', { action: 'klines', code: '600519', limit: 1 });
  assert(res.status === 200 && res.json.success, `klines expected success, got ${res.status}`);
  assert(res.json.data.code === '600519', 'klines should return normalized code');
  assert(res.json.data.name && res.json.data.name !== '600519', 'klines should return stock name');
}

function testKlineTitleRendersCodeAndName() {
  const src = fs.readFileSync('components/DbPanel.tsx', 'utf-8');
  assert(src.includes('klineName'), 'K-line title should keep stock name state');
  assert(src.includes('{klineCode}') && src.includes('{klineName}'), 'K-line title should render code and name');
}

function testMarketBrowseStockDetailLoadsTicksAndStats() {
  const src = fs.readFileSync('components/DbPanel.tsx', 'utf-8');
  assert(src.includes("action: 'ticks'"), 'market browse detail should call ticks API');
  assert(src.includes('limit: 300'), 'market browse detail should request a larger recent tick window before pagination');
  assert(src.includes('trade_date: todayTradeDate()'), 'market browse detail should read current-day ticks instead of mixing older sessions');
  assert(src.includes('collect?.items'), 'market browse detail should tolerate force-refresh collect-wrapped ticks');
  assert(src.includes('selectedStock'), 'market browse should keep selected stock state');
  assert(src.includes('tickStats'), 'market browse should render tick statistics');
  assert(src.includes('orderBook'), 'market browse should keep order book state');
  assert(src.includes('l.price > 0 ?'), 'market browse order book should render empty levels as placeholders');
  assert(src.includes('tdxrs_transaction'), 'market browse should distinguish true tdxrs transaction ticks');
  assert(src.includes('calc(100vh'), 'market browse tick table should stretch with viewport height');
  assert(src.includes('逐笔交易') && src.includes('成交统计') && src.includes('盘口买卖盘'), 'market browse should expose tick trades, volume statistics, and order book labels');
  assert(src.includes("action: 'tick_collect_full_day'"), 'market browse should expose full-day tick backfill action');
  assert(src.includes('补齐今日逐笔'), 'market browse should provide a full-day tick backfill button');
  assert(src.includes('stored_count') && src.includes('first_time') && src.includes('last_time') && src.includes('complete'), 'market browse should show full-day tick backfill status');
  assert(src.includes('tickFullDayMode'), 'market browse should keep full-day tick mode after backfill');
  assert(src.includes('display_limit: 20000'), 'market browse full-day backfill should request more than the recent 100-row display window');
  assert(src.includes('今日逐笔状态'), 'market browse should keep the full-day tick status area visible');
  assert(src.includes('tickPageSize') && src.includes('pagedTicks'), 'market browse should paginate full-day tick rows instead of dumping or truncating them');
  assert(src.includes('上一页') && src.includes('下一页'), 'market browse should expose tick pagination controls');
  assert(src.includes('Math.ceil(ticks.length / tickPageSize)'), 'market browse should calculate total tick pages from the loaded full-day row count');
  assert(src.includes('tickFullDayModeRef') && src.includes('if (tickFullDayModeRef.current) return'), 'market browse should prevent recent-tick polling from overwriting full-day backfill rows');
  assert(src.indexOf("await dataApi({ action: 'tick_collect_full_day'") < src.indexOf('tickFullDayModeRef.current = true'), 'market browse should enter full-day mode only after full-day backfill succeeds');
}

testMarketBrowseRequestsTop100ByAmount();
testRealtimePanelDocumentsTdxQuantFirst();
testReadmeDocumentsMarketMetricDataFlow();
await testKlinesReturnCodeAndName();
testKlineTitleRendersCodeAndName();
testMarketBrowseStockDetailLoadsTicksAndStats();

console.log('data browse contract tests passed');

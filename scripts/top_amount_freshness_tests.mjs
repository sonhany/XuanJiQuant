const API_BASE = process.env.API_BASE || 'http://127.0.0.1:8880';

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function post(body) {
  const res = await fetch(`${API_BASE}/api/data`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const json = await res.json();
  return { status: res.status, json };
}

function quoteForCode(quotes, code) {
  const c = String(code || '').trim();
  return quotes[c] || quotes[`sh${c}`] || quotes[`sz${c}`] || quotes[`${c}.SH`] || quotes[`${c}.SZ`] || null;
}

const dataRunnerSource = await import('node:fs').then(fs => fs.readFileSync('scripts/data_runner.py', 'utf-8'));
assert(dataRunnerSource.includes('force_refresh'), 'stocks/realtime APIs should accept force_refresh');
assert(dataRunnerSource.includes('use_cache=not force_refresh'), 'force_refresh should bypass realtime quote cache');
assert(dataRunnerSource.includes('bypass_cache=force_refresh'), 'force_refresh should bypass market top cache');
assert(dataRunnerSource.includes('def _realtime_trade_date'), 'realtime TOP lists should derive latest_date from trading calendar');
assert(!dataRunnerSource.includes('"latest_date": _today_yyyymmdd()'), 'realtime TOP latest_date must not use local machine date directly');

const res = await post({ action: 'stocks', limit: 10, sort_by: 'amount', force_refresh: true });
assert(res.status === 200 && res.json.success, `stocks expected success, got ${res.status}`);
const stocks = res.json.data?.stocks || [];
assert(stocks.length > 0, 'Top amount list should not be empty');
assert(res.json.data?.latest_date, 'Top amount response should expose latest_date');
assert(Number(stocks[0]?.amount || 0) > 0, 'Top amount list should be driven by non-zero market-wide amount data');
assert(
  ['realtime', 'realtime_fallback', 'realtime_stale'].includes(res.json.data?.source),
  `Top amount list should use a realtime-derived source before daily summary, got ${res.json.data?.source}`,
);
if (res.json.data?.source === 'realtime_stale') {
  assert(res.json.data?.stale === true, 'Closed-market realtime snapshot must be explicitly marked stale');
} else {
  assert(res.json.data?.stale !== true, 'Live realtime source must not be marked stale');
}
for (let i = 1; i < stocks.length; i++) {
  assert(Number(stocks[i - 1].amount || 0) >= Number(stocks[i].amount || 0), 'Top amount list should be sorted by amount desc');
}
for (const s of stocks) {
  assert(s.latest_time || s.latest_date === res.json.data.latest_date, `Top amount stock ${s.code} should expose realtime time or latest trade date`);
}

const quoteRes = await post({ action: 'realtime_prices', codes: stocks.slice(0, 3).map(s => s.code), force_refresh: true });
assert(quoteRes.status === 200 && quoteRes.json.success, `realtime quote expected success, got ${quoteRes.status}`);
for (const s of stocks.slice(0, 3)) {
  const q = quoteForCode(quoteRes.json.data || {}, s.code);
  assert(q, `Realtime quote should be available for top stock ${s.code}`);
  const stockPrice = Number(s.price || 0);
  const quotePrice = Number(q.price || 0);
  const stockChange = Number(s.change_pct || 0);
  const quoteChange = Number(q.chg_pct || 0);
  const stockAmount = Number(s.amount || 0);
  const quoteAmount = Number(q.amount || 0);
  // Both calls force a fresh market snapshot, so active symbols can move between them.
  assert(stockPrice > 0 && quotePrice > 0 && Math.abs(stockPrice - quotePrice) / stockPrice <= 0.005,
    `Top stock ${s.code} price should remain aligned with realtime quote`);
  assert(Math.abs(stockChange - quoteChange) <= 0.5,
    `Top stock ${s.code} change_pct should remain aligned with realtime quote`);
  assert(stockAmount > 0 && quoteAmount > 0 && Math.abs(stockAmount - quoteAmount) / stockAmount <= 0.05,
    `Top stock ${s.code} amount should remain in the same realtime scale`);
  if (q.source === 'tdx_quant' && Number(q.volume || 0) > 0 && Number(q.price || 0) > 0) {
    assert(
      Number(q.amount || 0) >= Number(q.price || 0) * Number(q.volume || 0) * 50,
      `Top stock ${s.code} amount should not treat TdxQuant lot volume as shares`,
    );
  }
}

console.log('top amount freshness tests passed');

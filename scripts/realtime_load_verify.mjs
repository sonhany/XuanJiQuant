import crypto from 'node:crypto';

const API_BASE = process.env.API_BASE || 'http://127.0.0.1:8880';
const args = process.argv.slice(2);
const numberArg = (name, fallback) => {
  const index = args.indexOf(name);
  return index >= 0 ? Number(args[index + 1]) || fallback : fallback;
};
const clients = Math.max(1, numberArg('--clients', 10));
const seconds = Math.max(5, numberArg('--seconds', 20));

async function post(path, body) {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok || payload.success === false) throw new Error(`${path}: ${payload.error || payload.reason || response.status}`);
  return payload.data ?? payload;
}

const hash = value => crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
const p95 = (values) => {
  const sorted = values.filter(Number.isFinite).toSorted((a, b) => a - b);
  return sorted.length ? sorted[Math.min(sorted.length - 1, Math.ceil(sorted.length * 0.95) - 1)] : null;
};

async function executionInvariant() {
  const [account, orders, fills] = await Promise.all([
    post('/api/paper-execution', { action: 'account' }),
    post('/api/paper-execution', { action: 'orders', limit: 1000 }),
    post('/api/paper-execution', { action: 'fills', limit: 1000 }),
  ]);
  return hash({
    cash: account.account?.cash,
    positions: (account.positions || []).map(row => ({
      code: row.code, quantity: row.quantity, available_qty: row.available_qty,
      today_buy_qty: row.today_buy_qty, avg_price: row.avg_price, realized_pnl: row.realized_pnl,
    })),
    orders,
    fills,
  });
}

const account = await post('/api/paper-execution', { action: 'account' });
const codes = (account.positions || []).map(row => row.code).filter(Boolean);
const beforeInvariant = await executionInvariant();
const beforeStatus = await post('/api/sync', { action: 'stream_status' });
const hotAges = [];
const cockpitAges = [];
const topGenerations = new Set();
const perClientEvents = Array.from({ length: clients }, () => ({ hot: 0, cockpit: 0, top: 0 }));

async function consume(index, controller) {
  const query = new URLSearchParams({
    codes: codes.join(','), channels: 'hot_quotes,cockpit_mark,market_top100',
  });
  try {
    const response = await fetch(`${API_BASE}/api/market-stream?${query}`, { signal: controller.signal });
    if (!response.ok || !response.body) throw new Error(`SSE HTTP ${response.status}`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) >= 0) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        let type = '';
        let data = null;
        for (const line of block.split('\n')) {
          if (line.startsWith('event: ')) type = line.slice(7);
          if (line.startsWith('data: ')) {
            try { data = JSON.parse(line.slice(6)); } catch { data = null; }
          }
        }
        if (type === 'hot_quotes' && data) {
          perClientEvents[index].hot += 1;
          if (Number.isFinite(Number(data.age_ms))) hotAges.push(Number(data.age_ms));
        } else if (type === 'cockpit_mark' && data) {
          perClientEvents[index].cockpit += 1;
          const stamp = Date.parse(data.account?.valuation_as_of || '');
          if (Number.isFinite(stamp)) cockpitAges.push(Math.max(0, Date.now() - stamp));
        } else if (type === 'market_top100' && data) {
          perClientEvents[index].top += 1;
          if (data.generation_id) topGenerations.add(data.generation_id);
        }
      }
    }
  } catch (error) {
    if (error?.name !== 'AbortError') throw error;
  }
}

const controllers = Array.from({ length: clients }, () => new AbortController());
const consumers = controllers.map((controller, index) => consume(index, controller));
await new Promise(resolve => setTimeout(resolve, seconds * 1000));
controllers.forEach(controller => controller.abort());
await Promise.all(consumers);

await post('/api/workbench', { action: 'status' });
const workbenchLatencies = [];
for (let index = 0; index < 20; index += 1) {
  const started = performance.now();
  await post('/api/workbench', { action: 'status' });
  workbenchLatencies.push(performance.now() - started);
}
const afterStatus = await post('/api/sync', { action: 'stream_status' });
const afterInvariant = await executionInvariant();
const hotCalls = Number(afterStatus.hot_upstream_calls || 0) - Number(beforeStatus.hot_upstream_calls || 0);
const expectedCalls = seconds * 1000 / 1000;
const report = {
  clients,
  seconds,
  symbols: codes.length,
  hot_quote_freshness_p95_ms: p95(hotAges),
  cockpit_valuation_freshness_p95_ms: p95(cockpitAges),
  workbench_latency_p95_ms: Math.round(p95(workbenchLatencies) || 0),
  hot_upstream_calls: hotCalls,
  upstream_call_multiplier: Number((hotCalls / Math.max(1, expectedCalls)).toFixed(3)),
  top100_generations: topGenerations.size,
  client_event_min: {
    hot: Math.min(...perClientEvents.map(row => row.hot)),
    cockpit: Math.min(...perClientEvents.map(row => row.cockpit)),
    top: Math.min(...perClientEvents.map(row => row.top)),
  },
  execution_invariants_changed: beforeInvariant !== afterInvariant,
  stream_status: afterStatus,
};
console.log(JSON.stringify(report, null, 2));

const failures = [];
if (!(report.hot_quote_freshness_p95_ms !== null && report.hot_quote_freshness_p95_ms <= 2000)) failures.push('hot quote p95 > 2000ms');
if (!(report.cockpit_valuation_freshness_p95_ms !== null && report.cockpit_valuation_freshness_p95_ms <= 3000)) failures.push('cockpit valuation p95 > 3000ms');
if (!(report.workbench_latency_p95_ms < 300)) failures.push('workbench p95 >= 300ms');
if (!(report.upstream_call_multiplier <= 1.1)) failures.push('upstream multiplier > 1.1');
if (report.client_event_min.hot < 1 || report.client_event_min.cockpit < 1) failures.push('a client received no live events');
if (report.client_event_min.top < 1 || report.top100_generations < 1) failures.push('a client received no complete Top100 generation');
if (report.execution_invariants_changed) failures.push('execution facts changed during marks');
if (failures.length) {
  console.error(`FAIL: ${failures.join('; ')}`);
  process.exitCode = 1;
}

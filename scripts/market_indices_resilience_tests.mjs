import fs from 'node:fs';

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const src = fs.readFileSync('server/routes/market.mjs', 'utf-8');
assert(src.includes('indicesCache || fallbackIndices'), 'market indices should fall back to cache/default data on timeout');
assert(src.includes('force_refresh: true'), 'market indices route should force-refresh its short-TTL quote fetch');
assert(src.includes('source: q.source ||'), 'market indices route should expose the underlying quote source');
assert(!/GET'\)\s*\{[\s\S]*?catch \(e\) \{[\s\S]*?json\(res, 500/.test(src), 'GET /api/market/indices should not return HTTP 500 on transient quote timeout');

const res = await fetch('http://127.0.0.1:8880/api/market/indices');
const json = await res.json();
assert(res.status === 200, `GET /api/market/indices should return 200, got ${res.status}`);
assert(json.success === true, 'GET /api/market/indices should return success=true with fallback data');
assert(Array.isArray(json.data), 'GET /api/market/indices should return data array');
assert(json.data.every((row) => Object.prototype.hasOwnProperty.call(row, 'source')), 'GET /api/market/indices rows should include source');

console.log('market indices resilience tests passed');

import assert from 'node:assert/strict';
import fs from 'node:fs';

const hook = fs.readFileSync('hooks/useMarketStream.ts', 'utf8');
const panel = fs.readFileSync('components/DbPanel.tsx', 'utf8');

for (const token of [
  'new EventSource',
  'visibilitychange',
  '[1000, 2000, 5000, 10000]',
  'lastSequenceRef',
  'eventSource.close()',
  'fallbackIntervalMs',
  'clearInterval',
  'clearTimeout',
]) assert(hook.includes(token), `market stream hook missing ${token}`);

assert(panel.includes("from '../hooks/useMarketStream'"), 'DbPanel must use the shared market stream hook');
assert(panel.includes("channels: ['market_top100']"), 'market browse must subscribe to complete Top100 generations');
assert(panel.includes("channels: ['hot_quotes']"), 'realtime watch must subscribe to hot quotes');
assert(!panel.includes('setInterval(loadStocks, 15000)'), 'market browse must not retain the 15-second primary poll');
assert(!panel.includes('setInterval(poll, 5000)'), 'realtime watch must not retain the 5-second primary poll');
assert(panel.includes('fallbackIntervalMs: 5000'), 'Top100 must retain a bounded fallback poll');
assert(panel.includes('fallbackIntervalMs: 2000'), 'hot quotes must retain a bounded fallback poll');
assert(panel.includes('quote_timestamp'), 'UI must render source quote time rather than only browser receipt time');
assert(panel.includes('推送中(1s)') && panel.includes('服务端单飞推送'), 'realtime UI must describe the actual push cadence');
assert(!panel.includes('轮询中(5s)') && !panel.includes('5秒轮询'), 'realtime UI must not retain obsolete polling copy');

console.log('market stream frontend contracts passed');

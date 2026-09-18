import assert from 'node:assert/strict';

import {
  formatSseEvent,
  isAllowedStreamRequest,
  parseStreamRequest,
} from '../server/routes/market-stream.mjs';

const parsed = parseStreamRequest('/api/market-stream?codes=600519,000001&channels=hot_quotes,cockpit_mark');
assert.deepEqual(parsed.codes, ['600519', '000001']);
assert.deepEqual(parsed.channels, ['hot_quotes', 'cockpit_mark']);

assert.equal(isAllowedStreamRequest({ socket: { remoteAddress: '127.0.0.1' }, headers: { origin: 'http://127.0.0.1:8888' } }), true);
assert.equal(isAllowedStreamRequest({ socket: { remoteAddress: '192.168.1.10' }, headers: { origin: 'http://evil.example' } }), false);

assert.equal(
  formatSseEvent({ id: 7, type: 'hot_quotes', data: { snapshot_id: 's1' } }),
  'id: 7\nevent: hot_quotes\ndata: {"snapshot_id":"s1"}\n\n',
);

console.log('market stream route contracts passed');

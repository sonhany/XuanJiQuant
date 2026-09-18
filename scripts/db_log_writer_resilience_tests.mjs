import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync('server/db_log_writer.mjs', 'utf8');

assert(
  /child\.stdin\.(?:on|once)\(['"]error['"]/.test(source),
  'database log writer must handle child stdin errors so EPIPE cannot terminate the API server',
);
assert(
  /if \(proc (?:===|!==) child\)/.test(source) && source.includes('proc = null'),
  'database log writer must only clear the currently active child after a stream failure',
);

console.log('db log writer resilience tests passed');

import assert from 'node:assert/strict';
import fs from 'node:fs';
import { classifyChildStderr } from '../server/child_process_logging.mjs';

assert.equal(classifyChildStderr('2026-07-25 INFO service started'), 'INFO');
assert.equal(classifyChildStderr('WARNING quote provider degraded'), 'WARN');
assert.equal(classifyChildStderr('Traceback (most recent call last):'), 'ERROR');
assert.equal(classifyChildStderr('CRITICAL database unavailable'), 'ERROR');

for (const file of [
  'server/sync_service_manager.mjs',
  'server/tick_collector_manager.mjs',
]) {
  const source = fs.readFileSync(file, 'utf8');
  assert(
    source.includes('logChildStderr('),
    `${file} should classify Python stderr instead of logging every line as WARN`,
  );
}

const persistentRunner = fs.readFileSync('server/persistent_runner.mjs', 'utf8');
assert(
  persistentRunner.includes("const exitLevel = code === 0 && !pending ? 'INFO' : 'WARN';"),
  'idle runner exit code 0 should be logged as INFO',
);

console.log('child process logging contract tests passed');

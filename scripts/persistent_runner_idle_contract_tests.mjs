import fs from 'node:fs';
import assert from 'node:assert/strict';

const src = fs.readFileSync('server/persistent_runner.mjs', 'utf8');

assert(src.includes('XUANJI_RUNNER_IDLE_MS'), 'persistent runner should expose an idle timeout env override');
assert(src.includes('RUNNER_IDLE_MS'), 'persistent runner should define idle timeout');
assert(src.includes('_scheduleIdleClose'), 'persistent runner should schedule idle process shutdown');
assert(src.includes('_clearIdleTimer'), 'persistent runner should cancel idle shutdown when reused');
assert(src.includes('stderrTail'), 'persistent runner must retain a bounded stderr tail');

console.log('persistent runner idle contract tests passed');

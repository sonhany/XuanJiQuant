import assert from 'node:assert/strict';

const manager = await import('../server/update_manager.mjs');

assert.equal(
  typeof manager.normalizeProcessExitCode,
  'function',
  'update manager must expose Windows exit-code normalization',
);
assert.equal(manager.normalizeProcessExitCode(4294967295), -1);
assert.equal(manager.normalizeProcessExitCode(1), 1);
assert.equal(manager.normalizeProcessExitCode(0), 0);
assert.equal(manager.normalizeProcessExitCode(null), null);

assert.equal(
  typeof manager.classifyUpdateExit,
  'function',
  'update manager must expose process-exit classification',
);
assert.equal(
  manager.classifyUpdateExit({
    code: 4294967295,
    signal: null,
    stoppedByUser: false,
  }).kind,
  'external_termination',
);
assert.equal(
  manager.classifyUpdateExit({
    code: null,
    signal: 'SIGTERM',
    stoppedByUser: false,
  }).kind,
  'external_termination',
);
assert.equal(
  manager.classifyUpdateExit({
    code: 1,
    signal: null,
    stoppedByUser: false,
  }).kind,
  'failed',
);
assert.equal(
  manager.classifyUpdateExit({
    code: 0,
    signal: null,
    stoppedByUser: false,
  }).kind,
  'success',
);
assert.equal(
  manager.classifyUpdateExit({
    code: 4294967295,
    signal: null,
    stoppedByUser: true,
  }).kind,
  'manual_stop',
);

assert.equal(
  typeof manager.releaseProcessAfterPersist,
  'function',
  'update manager must keep the in-memory process reference until final state is persisted',
);
let resolvePersist;
let released = false;
const persistence = new Promise((resolve) => {
  resolvePersist = resolve;
});
const releasePending = manager.releaseProcessAfterPersist(
  persistence,
  () => { released = true; },
);
await Promise.resolve();
assert.equal(released, false);
resolvePersist();
await releasePending;
assert.equal(released, true);

assert.equal(
  typeof manager.mergeFinancialCheckpoint,
  'function',
  'update manager must reconstruct financial progress after backend restart',
);
const baseFinancial = {
  running: true, mode: 'financial', pid: 123, percent: 0,
  done: 0, total: 5203, ok: 0, err: 0, last_error: '',
};
const resumed = manager.mergeFinancialCheckpoint(
  baseFinancial,
  { status: 'running', done: 20, total: 5203, ok: 20, err: 0, updated_at: '2026-09-01T20:20:00' },
  true,
);
assert.equal(resumed.running, true);
assert.equal(resumed.done, 20);
assert.match(resumed.step, /财务刷新/);

const completed = manager.mergeFinancialCheckpoint(
  baseFinancial,
  { status: 'completed', done: 5203, total: 5203, ok: 5203, err: 0, finished_at: '2026-09-01T21:00:00' },
  false,
);
assert.equal(completed.running, false);
assert.equal(completed.percent, 100);
assert.equal(completed.last_error, '');
assert.match(completed.step, /财务更新完成/);

const interrupted = manager.mergeFinancialCheckpoint(
  baseFinancial,
  { status: 'running', done: 3, total: 5203, ok: 3, err: 0 },
  false,
);
assert.equal(interrupted.running, false);
assert.equal(interrupted.done, 3);
assert.equal(interrupted.last_error, 'orphaned update process');

console.log('update manager exit-code tests passed');

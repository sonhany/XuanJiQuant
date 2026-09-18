import assert from 'node:assert/strict';
import fs from 'node:fs';

const workbenchRoute = fs.readFileSync('server/routes/workbench.mjs', 'utf8');
const paperRoute = fs.readFileSync('server/routes/paper.mjs', 'utf8');

assert(
  workbenchRoute.includes('runtimeMetaFromPersisted(values.scheduler)')
    && workbenchRoute.includes('runtimeMetaFromPersisted(values.paper?.status)'),
  'workbench must derive daemon liveness from runner results instead of spawning Python status probes',
);
assert(
  /schedulerRuntime,\s*paperRuntime/.test(workbenchRoute),
  'workbench must pass validated runtime metadata into the status composer',
);
assert(paperRoute.includes('独立模拟盘执行入口已移除'), 'paper route must retire the standalone daemon entry');
assert(!paperRoute.includes('paper_manager.mjs') && !paperRoute.includes('startPaperDaemon'), 'paper route must not import or start a standalone daemon');

const { runtimeMetaFromPersisted } = await import('../server/runtime_status.mjs');
assert.deepEqual(
  runtimeMetaFromPersisted({ running: true, pid: process.pid, started_at: '2026-07-30T00:00:00Z' }),
  { running: true, pid: process.pid, started_at: '2026-07-30T00:00:00Z' },
  'a live persisted pid should be accepted without a subprocess probe',
);
assert.deepEqual(
  runtimeMetaFromPersisted({ daemon_running: true, daemon_pid: 999_999_999 }),
  { running: false, pid: null, started_at: null },
  'a stale persisted pid must fail closed',
);

console.log('P1 runtime performance tests passed');

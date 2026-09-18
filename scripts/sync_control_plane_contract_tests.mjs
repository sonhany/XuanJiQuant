import assert from 'node:assert/strict';
import fs from 'node:fs';

const route = fs.readFileSync('server/routes/sync.mjs', 'utf-8');
const updateManager = fs.readFileSync('server/update_manager.mjs', 'utf-8');
const syncManager = fs.readFileSync('server/sync_service_manager.mjs', 'utf-8');
const httpUtils = fs.readFileSync('server/http-utils.mjs', 'utf-8');
const serverIndex = fs.readFileSync('server/index.mjs', 'utf-8');
const dbLogWriter = fs.readFileSync('server/db_log_writer.mjs', 'utf-8');
const watchdogWorker = fs.existsSync('server/watchdog_worker.mjs')
  ? fs.readFileSync('server/watchdog_worker.mjs', 'utf-8')
  : '';
const watchdog = fs.readFileSync('server/watchdog.mjs', 'utf-8');
const panel = fs.readFileSync('components/DbPanel.tsx', 'utf-8');
const dataRunner = fs.readFileSync('scripts/data_runner.py', 'utf-8');
const syncRunner = fs.existsSync('scripts/sync_runner.py')
  ? fs.readFileSync('scripts/sync_runner.py', 'utf-8')
  : '';
const controlPlane = fs.readFileSync('quant/data/control_plane.py', 'utf-8');

assert(
  fs.existsSync('server/sync_service_manager.mjs'),
  'realtime sync must have a dedicated process manager',
);
assert(
  fs.existsSync('quant/data/sync_status.py'),
  'Python sync daemon must use a dedicated status contract',
);
assert(
  syncManager.includes("'data_sync_daemon_exit'") && syncManager.includes('childPid'),
  'daemon exit audit must retain the child PID and remain distinct from the stop request',
);

assert(
  route.includes("from '../sync_service_manager.mjs'"),
  '/api/sync must use the managed daemon lifecycle',
);
assert(
  route.includes("new PersistentRunner('sync_runner.py')"),
  '/api/sync status and health must use an isolated lightweight persistent runner',
);
assert(
  !route.includes('spawnSync'),
  '/api/sync polling must not start a fresh Python process per request',
);
assert(
  !route.includes('sync:cmd:trigger:'),
  'legacy unconsumed trigger keys must be removed',
);
assert(
  !route.includes('sync:popular_progress') && !route.includes('sync:full_progress'),
  'legacy progress keys must be removed',
);
assert(
  !route.includes('elapsed > 60000'),
  'sync progress must never be marked complete by elapsed-time heuristic',
);
assert(
  route.includes("action === 'health'"),
  '/api/sync must expose a truthful data-health action',
);
assert(
  route.includes('stocks_with_bars_total: state.kline_total_count || 0') &&
  route.includes('stocks_outside_universe: state.kline_extra_count || 0'),
  'sync status must separate historical or universe-lag K-line keys from coverage',
);
assert(
  controlPlane.includes('"stock:universe"'),
  'sync status must use the canonical stock universe key',
);
assert(
  !route.includes("source: 'Redis (Phase 1)'"),
  'sync status must not hard-code the retired Redis phase label',
);

assert(
  updateManager.includes("'data:update:status'"),
  'manual update progress must be persisted',
);
assert(
  updateManager.includes("new PersistentRunner('sync_runner.py')"),
  'manual update persistence must reuse the lightweight runner without blocking HTTP',
);
assert(
  updateManager.includes('stderr_tail'),
  'manual update errors must retain a bounded stderr tail',
);
assert(
  updateManager.includes("'data_update_exit'") && updateManager.includes('proc.stoppedByUser'),
  'manual update stop and process exit must remain distinct audit events',
);
assert(
  updateManager.includes('codes'),
  'manual updates must accept an optional selected stock-code scope',
);

assert(
  watchdog.includes("from './sync_service_manager.mjs'"),
  'watchdog must monitor the realtime sync daemon',
);
assert(
  watchdog.includes('sync_alive'),
  'watchdog status must expose realtime sync liveness',
);
assert(
  serverIndex.includes("from 'worker_threads'") && serverIndex.includes('watchdog_worker.mjs'),
  'watchdog must run outside the main HTTP event loop',
);
assert(
  !serverIndex.includes("import { watchdogTick } from './watchdog.mjs'"),
  'HTTP server must not execute blocking watchdog checks on its main thread',
);
assert(
  watchdogWorker.includes('watchdogTick') && watchdogWorker.includes('setInterval'),
  'watchdog worker must own periodic health checks',
);
assert(
  dbLogWriter.includes('isMainThread') && dbLogWriter.includes("type: 'db_log'"),
  'worker logs must be forwarded to the main log writer instead of spawning a duplicate process',
);
assert(
  serverIndex.includes("message?.type === 'db_log'"),
  'HTTP main thread must persist forwarded watchdog logs through the shared writer',
);

assert(
  panel.includes("action: 'health'"),
  'Data Management must request full data-health state',
);
assert(
  panel.includes('source_health'),
  'Data Management must render source-health information',
);
assert(
  panel.includes('selectedCodes'),
  'Data Management must support selective stock-code updates',
);
assert(
  !dataRunner.includes('"sync_status": action_sync_status'),
  'market data runner must not carry control-plane actions that can be blocked by quotes',
);
assert(
  syncRunner.includes('"sync_status"')
    && syncRunner.includes('"sync_health"')
    && syncRunner.includes('"write_update_status"'),
  'lightweight sync runner must expose status, health and update-state persistence actions',
);
assert(
  !syncRunner.includes('numpy') && !syncRunner.includes('market_data'),
  'lightweight sync runner must not import heavy market-data dependencies',
);
assert(
  httpUtils.includes("'application/json; charset=utf-8'"),
  'JSON responses must declare UTF-8 so Chinese operational states are decoded correctly',
);

console.log('sync control plane contract tests passed');

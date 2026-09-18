/**
 * Managed lifecycle for the realtime Python data-sync daemon.
 */
import { spawn, spawnSync } from 'child_process';
import { log } from './http-utils.mjs';
import { logChildStderr } from './child_process_logging.mjs';
import { ROOT_DIR, resolvePython } from './config.mjs';

const PYTHON = resolvePython();
const STATUS_KEY = 'data:sync:daemon_status';
const CONFIG_KEY = 'data:sync:config';
const HEARTBEAT_MAX_AGE_MS = 90_000;
let daemonProc = null;
let daemonPid = null;
let daemonStartedAt = null;

function pythonEnv(extra = {}) {
  return {
    ...process.env,
    QUANT_SKIP_NODE_PROXY: '1',
    PYTHONIOENCODING: 'utf-8',
    PYTHONUNBUFFERED: '1',
    OMP_NUM_THREADS: process.env.OMP_NUM_THREADS || '1',
    OPENBLAS_NUM_THREADS: process.env.OPENBLAS_NUM_THREADS || '1',
    MKL_NUM_THREADS: process.env.MKL_NUM_THREADS || '1',
    NUMEXPR_NUM_THREADS: process.env.NUMEXPR_NUM_THREADS || '1',
    ...extra,
  };
}

function pidAlive(pid) {
  if (!pid) return false;
  try {
    process.kill(Number(pid), 0);
    return true;
  } catch {
    return false;
  }
}

function runPython(script, timeout = 8000) {
  const result = spawnSync(PYTHON, ['-c', script], {
    cwd: ROOT_DIR,
    env: pythonEnv(),
    encoding: 'utf-8',
    windowsHide: true,
    timeout,
  });
  if (result.status !== 0) {
    return { success: false, error: String(result.stderr || 'python failed').trim() };
  }
  try {
    return JSON.parse(String(result.stdout || '{}').trim().split(/\r?\n/).pop() || '{}');
  } catch {
    return { success: false, error: 'invalid cache response' };
  }
}

function readCacheState() {
  return runPython(`
import json, sys
sys.path.insert(0, '.')
from quant.data.cache import create_cache
c = create_cache()
print(json.dumps({
  'config': c.get('${CONFIG_KEY}') or {},
  'status': c.get('${STATUS_KEY}') or {},
}, ensure_ascii=False))
`);
}

function writeState({ config = null, status = null, eventType = '', payload = {} } = {}) {
  const encoded = Buffer.from(JSON.stringify({ config, status, eventType, payload })).toString('base64');
  return runPython(`
import base64, json, sys
sys.path.insert(0, '.')
from quant.data.cache import create_cache
from quant.data.audit import write_audit_event
data = json.loads(base64.b64decode('${encoded}').decode('utf-8'))
c = create_cache()
if data.get('config') is not None:
    c.set('${CONFIG_KEY}', data['config'])
if data.get('status') is not None:
    c.set('${STATUS_KEY}', data['status'])
if data.get('eventType'):
    write_audit_event(c, data['eventType'], data.get('payload') or {}, source='sync_service_manager')
print(json.dumps({'success': True}))
`);
}

function normalizeCodes(codes) {
  const out = [];
  const seen = new Set();
  for (const raw of Array.isArray(codes) ? codes : []) {
    let code = String(raw || '').trim().toLowerCase();
    code = code.replace(/\.(sh|sz|bj)$/i, '').replace(/^(sh|sz|bj)/i, '');
    if (!/^\d{6}$/.test(code) || code.startsWith('920') || seen.has(code)) continue;
    seen.add(code);
    out.push(code);
  }
  return out;
}

export function readDaemonStatus() {
  const state = readCacheState();
  const status = state.status || {};
  const config = state.config || {};
  const alive = pidAlive(status.pid) || !!(daemonProc && daemonProc.exitCode === null);
  const heartbeatAt = Date.parse(status.heartbeat_at || '');
  const heartbeatAgeMs = Number.isFinite(heartbeatAt) ? Math.max(0, Date.now() - heartbeatAt) : null;
  const heartbeatFresh = alive && heartbeatAgeMs !== null && heartbeatAgeMs <= HEARTBEAT_MAX_AGE_MS;
  return {
    ...status,
    enabled: config.enabled === true,
    configured_codes: normalizeCodes(config.codes || []),
    process_alive: alive,
    heartbeat_fresh: heartbeatFresh,
    heartbeat_age_seconds: heartbeatAgeMs === null ? null : Math.round(heartbeatAgeMs / 1000),
    running: alive && (heartbeatFresh || status.heartbeat_at == null),
  };
}

export function startDaemon(options = {}) {
  const current = readDaemonStatus();
  if (current.process_alive) {
    return { success: true, already_running: true, data: current };
  }
  const codes = normalizeCodes(options.codes || []);
  const requestedAt = new Date().toISOString();
  const config = { enabled: true, codes, requested_at: requestedAt };
  writeState({
    config,
    status: {
      running: false,
      starting: true,
      pid: null,
      heartbeat_at: null,
      watch_count: codes.length,
      last_error: '',
    },
  });

  const args = ['-m', 'quant.data.sync_service'];
  if (codes.length) args.push('--codes', codes.join(','));
  const proc = spawn(PYTHON, args, {
    cwd: ROOT_DIR,
    env: pythonEnv(),
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  proc.stoppedByUser = false;
  daemonProc = proc;
  daemonPid = proc.pid;
  const childPid = proc.pid;
  daemonStartedAt = requestedAt;
  writeState({
    config,
    status: {
      running: true,
      starting: true,
      pid: daemonPid,
      heartbeat_at: null,
      watch_count: codes.length,
      last_error: '',
    },
    eventType: 'data_sync_daemon_start',
    payload: { pid: daemonPid, codes, requested_at: requestedAt },
  });
  log('INFO', `[DataSync] daemon started pid=${daemonPid} codes=${codes.length || 'default'}`);

  proc.stdout?.setEncoding('utf-8');
  proc.stdout?.on('data', () => {});
  proc.stderr?.setEncoding('utf-8');
  proc.stderr?.on('data', (chunk) => logChildStderr('DataSync', chunk));
  proc.on('exit', (code) => {
    const stoppedByUser = proc.stoppedByUser === true;
    const crashed = !stoppedByUser && code !== 0;
    const cached = readCacheState();
    writeState({
      status: {
        ...(cached.status || {}),
        running: false,
        starting: false,
        crashed,
        pid: null,
        last_pid: childPid,
        process_alive: false,
        heartbeat_fresh: false,
        exit_code: code,
        stopped_at: new Date().toISOString(),
      },
      eventType: crashed ? 'data_sync_daemon_failed' : 'data_sync_daemon_exit',
      payload: { pid: childPid, exit_code: code, stopped_by_user: stoppedByUser },
    });
    if (daemonProc === proc) {
      daemonProc = null;
      daemonPid = null;
    }
  });
  proc.on('error', (error) => {
    writeState({
      config: { ...config, enabled: false },
      status: {
        running: false,
        starting: false,
        pid: daemonPid,
        last_error: error.message,
        stopped_at: new Date().toISOString(),
      },
      eventType: 'data_sync_daemon_failed',
      payload: { pid: childPid, error: error.message },
    });
    if (daemonProc === proc) {
      daemonProc = null;
      daemonPid = null;
    }
  });

  return { success: true, data: { pid: daemonPid, started_at: daemonStartedAt, codes } };
}

export function stopDaemon() {
  const current = readDaemonStatus();
  const pid = current.pid || daemonPid;
  writeState({ config: { enabled: false, codes: current.configured_codes || [] } });
  let stopped = false;
  if (daemonProc && daemonProc.exitCode === null) {
    try {
      daemonProc.stoppedByUser = true;
      stopped = daemonProc.kill();
    } catch {}
  } else if (pidAlive(pid)) {
    try {
      process.kill(Number(pid));
      stopped = true;
    } catch {}
  }
  const status = {
    ...current,
    running: false,
    starting: false,
    enabled: false,
    pid: null,
    last_pid: pid || null,
    process_alive: false,
    heartbeat_fresh: false,
    stopped_at: new Date().toISOString(),
  };
  writeState({
    status,
    eventType: 'data_sync_daemon_stop',
    payload: { pid, stopped, requested_at: status.stopped_at },
  });
  daemonProc = null;
  daemonPid = null;
  return stopped
    ? { success: true, data: status }
    : { success: false, error: 'realtime sync daemon is not running', data: status };
}

export function daemonMeta() {
  return readDaemonStatus();
}

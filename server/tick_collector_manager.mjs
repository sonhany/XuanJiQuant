import { spawn, spawnSync } from 'child_process';
import { log } from './http-utils.mjs';
import { logChildStderr } from './child_process_logging.mjs';
import { ROOT_DIR, resolvePython } from './config.mjs';

const PYTHON = resolvePython();
const SCRIPT = `${ROOT_DIR}/scripts/tick_collector.py`;

let daemonProc = null;
let daemonPid = null;

function runPython(script, timeout = 8000) {
  const r = spawnSync(PYTHON, ['-c', script], {
    cwd: ROOT_DIR,
    encoding: 'utf-8',
    timeout,
    windowsHide: true,
    env: { ...process.env, QUANT_SKIP_NODE_PROXY: '1', PYTHONIOENCODING: 'utf-8' },
  });
  if (r.status !== 0) return { success: false, error: r.stderr || r.stdout || `python exit ${r.status}` };
  try {
    return { success: true, data: JSON.parse((r.stdout || '{}').trim().split('\n').pop() || '{}') };
  } catch {
    return { success: true, data: { output: r.stdout } };
  }
}

function pidAlive(pid) {
  if (!pid) return false;
  try { process.kill(Number(pid), 0); return true; } catch { return false; }
}

function cachedStatus() {
  return runPython(`
import json, sys
sys.path.insert(0, '.')
from quant.data.cache import create_cache
c = create_cache()
print(json.dumps({'status': c.get('tick:collector:latest') or {}, 'config': c.get('tick:collector:config') or {}}, ensure_ascii=False, default=str))
`).data || { status: {}, config: {} };
}

function cachedPid() {
  const s = cachedStatus().status || {};
  return s.running ? s.pid : null;
}

export function tickCollectorStatus() {
  const cached = cachedStatus();
  const pid = daemonPid || cachedPid();
  const running = (daemonProc && daemonProc.exitCode === null) || pidAlive(pid);
  return {
    success: true,
    data: {
      ...(cached.status || {}),
      running,
      pid: running ? pid : null,
      config: cached.config || {},
    },
  };
}

export function startTickCollector(options = {}) {
  if (daemonProc && daemonProc.exitCode === null) {
    return { success: true, data: { already_running: true, pid: daemonPid } };
  }
  const pid = cachedPid();
  if (pidAlive(pid)) return { success: true, data: { already_running: true, pid } };
  const args = [SCRIPT, '--daemon'];
  if (options.interval_ms) args.push('--interval-ms', String(options.interval_ms));
  if (options.max_codes) args.push('--max-codes', String(options.max_codes));
  if (options.tick_count) args.push('--tick-count', String(options.tick_count));
  daemonProc = spawn(PYTHON, args, {
    cwd: ROOT_DIR,
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, QUANT_SKIP_NODE_PROXY: '1', PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1' },
  });
  daemonPid = daemonProc.pid;
  log('INFO', `[TickCollector] daemon started pid=${daemonPid}`);
  daemonProc.stderr?.setEncoding('utf-8');
  daemonProc.stderr?.on('data', d => logChildStderr('TickCollector', d, 200));
  daemonProc.on('exit', code => {
    log('INFO', `[TickCollector] daemon exited code=${code}`);
    daemonProc = null;
    daemonPid = null;
  });
  return { success: true, data: { pid: daemonPid, started: true } };
}

export function stopTickCollector() {
  runPython(`
import sys
sys.path.insert(0, '.')
from scripts.tick_collector import save_config
save_config({'enabled': False})
print('{"ok": true}')
`);
  if (daemonProc && daemonProc.exitCode === null) {
    try { daemonProc.kill(); } catch {}
  }
  daemonProc = null;
  daemonPid = null;
  return { success: true, data: { stopped: true } };
}

export function collectTickOnce(options = {}) {
  const payload = Buffer.from(JSON.stringify(options || {})).toString('base64');
  const r = runPython(`
import base64, json, sys
sys.path.insert(0, '.')
from scripts.tick_collector import collect_once, save_config
options = json.loads(base64.b64decode('${payload}').decode('utf-8')) if '${payload}' else {}
cfg = {}
for key in ('interval_ms', 'max_codes', 'tick_count', 'store_order_book', 'order_book_change_only'):
    if key in options:
        cfg[key] = options[key]
if cfg:
    save_config(cfg)
print(json.dumps(collect_once(codes=options.get('codes'), tick_count=options.get('tick_count')), ensure_ascii=False, default=str))
`, 120000);
  return r.success ? { success: true, data: r.data } : r;
}

export function handleTickCollectorAction(action, body = {}) {
  if (action === 'tick_collector_status') return tickCollectorStatus();
  if (action === 'tick_collector_start') return startTickCollector(body);
  if (action === 'tick_collector_stop') return stopTickCollector();
  if (action === 'tick_collect_once') return collectTickOnce(body);
  return null;
}

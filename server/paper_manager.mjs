/**
 * 模拟盘调度器进程管理 — 非阻塞式启动 paper_trader.py (daemon 模式)
 *
 * 设计 (与 update_manager.mjs 风格一致):
 *   - spawn (非阻塞) 启动 python paper_trader.py
 *   - daemon 模式: 长驻循环, 每日到点执行
 *   - 状态写 SQLite (paper:status), 前端轮询 /api/paper {action:"status"}
 *   - kill 子进程即停止 (stop)
 *   - run_now: 单独 spawn 一次 paper_trader.py --once (短任务, 跑完即退出)
 */
import { spawn, spawnSync } from 'child_process';
import { log } from './http-utils.mjs';
import { ROOT_DIR, resolvePython } from './config.mjs';

const PYTHON = resolvePython();
const PAPER_SCRIPT = `${ROOT_DIR}/scripts/paper_trader.py`;

// daemon 进程句柄 (单例, 同时只允许一个 daemon)
let daemonProc = null;
let daemonPid = null;
let daemonStartedAt = null;

function pidAlive(pid) {
  if (!pid) return false;
  try { process.kill(Number(pid), 0); return true; } catch { return false; }
}

function killPid(pid) {
  if (!pidAlive(pid)) return false;
  try { process.kill(Number(pid)); return true; } catch { return false; }
}

function clearCachedStatus() {
  try {
    spawnSync(PYTHON, ['-c', `
import sys
sys.path.insert(0, '.')
from quant.data.cache import create_cache
c = create_cache()
s = c.get('paper:status') or {}
s['running'] = False
c.set('paper:status', s)
`], { cwd: ROOT_DIR, env: { ...process.env, QUANT_SKIP_NODE_PROXY: '1', PYTHONIOENCODING: 'utf-8' }, windowsHide: true, timeout: 5000 });
  } catch {}
}

function cachedDaemonPid() {
  try {
    const r = spawnSync(PYTHON, ['-c', `
import json, sys
sys.path.insert(0, '.')
from quant.data.cache import create_cache
s = create_cache().get('paper:status') or {}
print(json.dumps({'running': bool(s.get('running')), 'pid': s.get('pid')}))
`], { cwd: ROOT_DIR, env: { ...process.env, QUANT_SKIP_NODE_PROXY: '1', PYTHONIOENCODING: 'utf-8' }, windowsHide: true, timeout: 5000, encoding: 'utf-8' });
    return JSON.parse((r.stdout || '{}').trim().split('\n').pop() || '{}');
  } catch { return {}; }
}

/**
 * 启动 daemon (非阻塞)。若已在运行返回冲突错误。
 */
export function startDaemon() {
  if (daemonProc && daemonProc.exitCode === null) {
    return { success: false, error: '模拟盘调度器已在运行中' };
  }
  const cached = cachedDaemonPid();
  if (cached.running && pidAlive(cached.pid)) {
    return { success: false, error: `模拟盘调度器已在运行中(pid=${cached.pid})` };
  }
  daemonProc = spawn(PYTHON, [PAPER_SCRIPT], {
    cwd: ROOT_DIR,
    env: { ...process.env, QUANT_SKIP_NODE_PROXY: '1', PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1' },
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  daemonPid = daemonProc.pid;
  daemonStartedAt = new Date().toISOString();
  log('INFO', `[PaperTrader] daemon started pid=${daemonPid}`);

  daemonProc.stdout?.setEncoding('utf-8');
  daemonProc.stdout?.on('data', () => {}); // daemon 日志走 SQLite, 这里丢弃 stdout
  daemonProc.stderr?.setEncoding('utf-8');
  daemonProc.stderr?.on('data', (d) => log('WARN', `[PaperTrader] stderr: ${String(d).slice(0, 200)}`));

  daemonProc.on('exit', (code) => {
    log('INFO', `[PaperTrader] daemon exited code=${code}`);
    daemonProc = null;
    daemonPid = null;
    // 同步清掉 SQLite 的 running 标志, 避免 daemon 崩溃后状态永远停在 true
    try {
      spawnSync(PYTHON, ['-c', `
import sys
sys.path.insert(0, '.')
from quant.data.cache import create_cache
c = create_cache()
s = c.get('paper:status') or {}
s['running'] = False
c.set('paper:status', s)
`], { cwd: ROOT_DIR, env: { ...process.env, QUANT_SKIP_NODE_PROXY: '1', PYTHONIOENCODING: 'utf-8' }, windowsHide: true, timeout: 5000 });
    } catch (e) {
      log('WARN', `[PaperTrader] cleanup status failed: ${e.message}`);
    }
  });
  daemonProc.on('error', (e) => {
    log('ERROR', `[PaperTrader] spawn error: ${e.message}`);
    daemonProc = null;
    daemonPid = null;
  });

  return { success: true, message: '模拟盘调度器已启动', pid: daemonPid };
}

/**
 * 停止 daemon (kill 子进程)。
 */
export function stopDaemon() {
  if (daemonProc && daemonProc.exitCode === null) {
    try {
      daemonProc.kill();
      log('INFO', '[PaperTrader] daemon killed by user');
    } catch (e) {
      log('WARN', `[PaperTrader] kill failed: ${e.message}`);
    }
    const pid = daemonPid;
    daemonProc = null;
    daemonPid = null;
    return { success: true, message: '已停止模拟盘调度器', pid };
  }
  const cached = cachedDaemonPid();
  if (cached.running && pidAlive(cached.pid)) {
    const ok = killPid(cached.pid);
    clearCachedStatus();
    return ok ? { success: true, message: '已停止缓存中的模拟盘调度器', pid: cached.pid }
              : { success: false, error: `无法停止缓存中的调度器(pid=${cached.pid})` };
  }
  clearCachedStatus();
  return { success: false, error: '调度器未在运行' };
}

/**
 * daemon 运行状态 (内存镜像, 用于快速判断)。
 * 真实状态 (last_run/next_run/result) 由路由从 SQLite paper:status 读取。
 */
export function daemonMeta() {
  return {
    running: !!(daemonProc && daemonProc.exitCode === null),
    pid: daemonPid,
    started_at: daemonStartedAt,
  };
}

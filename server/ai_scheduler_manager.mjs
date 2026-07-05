/**
 * AI 自主调度器进程管理 — 非阻塞式启动 ai_scheduler.py (daemon 模式)
 *
 * 设计 (与 paper_manager.mjs 风格一致):
 *   - spawn (非阻塞) 启动 python scripts/ai_scheduler.py --daemon
 *   - daemon 模式: 长驻, 按时段(intraday/postclose/idle)自动巡检五层闭环
 *   - 状态写 SQLite (ai:scheduler:latest), 前端轮询 /api/paper {action:"ai_scheduler_status"}
 *   - kill 子进程即停止 (stop)
 *   - exit handler 清理 ai:scheduler 状态, 避免孤儿
 *
 * watchdog.mjs 会监控此 daemon 存活状态, 挂了自动拉起。
 */
import { spawn, spawnSync } from 'child_process';
import { log } from './http-utils.mjs';
import { ROOT_DIR, resolvePython } from './config.mjs';

const PYTHON = resolvePython();
const SCHED_SCRIPT = `${ROOT_DIR}/scripts/ai_scheduler.py`;

// daemon 进程句柄 (单例, 同时只允许一个)
let daemonProc = null;
let daemonPid = null;
let daemonStartedAt = null;
// 区分"用户主动停止" vs "意外崩溃": 只有用户停止才清 enabled, 崩溃保留让 watchdog 重启
let stoppedByUser = false;

function pidAlive(pid) {
  if (!pid) return false;
  try { process.kill(Number(pid), 0); return true; } catch { return false; }
}

function killPid(pid) {
  if (!pidAlive(pid)) return false;
  try { process.kill(Number(pid)); return true; } catch { return false; }
}

function clearCachedStatus(clearEnabled = true) {
  try {
    spawnSync(PYTHON, ['-c', `
import sys
sys.path.insert(0, '.')
from quant.data.cache import create_cache
c = create_cache()
s = c.get('ai:scheduler:latest') or {}
s['running'] = False
s['crashed'] = False
c.set('ai:scheduler:latest', s)
cfg = c.get('ai:scheduler:config') or {}
if ${JSON.stringify(clearEnabled)}:
    cfg['enabled'] = False
c.set('ai:scheduler:config', cfg)
`], { cwd: ROOT_DIR, env: { ...process.env, QUANT_SKIP_NODE_PROXY: '1', PYTHONIOENCODING: 'utf-8' }, windowsHide: true, timeout: 5000 });
  } catch {}
}

function cachedDaemonPid() {
  try {
    const r = spawnSync(PYTHON, ['-c', `
import json, sys
sys.path.insert(0, '.')
from quant.data.cache import create_cache
s = create_cache().get('ai:scheduler:latest') or {}
print(json.dumps({'running': bool(s.get('running')), 'pid': s.get('pid')}))
`], { cwd: ROOT_DIR, env: { ...process.env, QUANT_SKIP_NODE_PROXY: '1', PYTHONIOENCODING: 'utf-8' }, windowsHide: true, timeout: 5000, encoding: 'utf-8' });
    return JSON.parse((r.stdout || '{}').trim().split('\n').pop() || '{}');
  } catch { return {}; }
}

/** 启动 daemon (非阻塞)。若已在运行返回冲突错误。 */
export function startDaemon(provider = null, options = {}) {
  if (options && Object.keys(options).length) {
    try {
      const cfgB64 = Buffer.from(JSON.stringify(options)).toString('base64');
      spawnSync(PYTHON, ['-c', `
import sys, json, base64
sys.path.insert(0, '.')
from scripts.ai_objective import save_autonomous_config
save_autonomous_config(json.loads(base64.b64decode('${cfgB64}').decode('utf-8')))
print('OK')
`], { cwd: ROOT_DIR, env: { ...process.env, QUANT_SKIP_NODE_PROXY: '1', PYTHONIOENCODING: 'utf-8' }, windowsHide: true, timeout: 5000 });
    } catch {}
  }
  if (daemonProc && daemonProc.exitCode === null) {
    return { success: false, error: 'AI 调度器已在运行中' };
  }
  const cached = cachedDaemonPid();
  if (cached.running && pidAlive(cached.pid)) {
    return { success: false, error: `AI 调度器已在运行中(pid=${cached.pid})` };
  }
  stoppedByUser = false;  // 新启动, 重置标志
  const args = [SCHED_SCRIPT, '--daemon'];
  if (provider) args.push('--provider', provider);
  daemonProc = spawn(PYTHON, args, {
    cwd: ROOT_DIR,
    env: { ...process.env, QUANT_SKIP_NODE_PROXY: '1', PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1' },
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  daemonPid = daemonProc.pid;
  daemonStartedAt = new Date().toISOString();
  log('INFO', `[AIScheduler] daemon started pid=${daemonPid}`);

  daemonProc.stdout?.setEncoding('utf-8');
  daemonProc.stdout?.on('data', () => { /* daemon 自身日志走 SQLite, 仅打印关键行 */ });
  daemonProc.stderr?.setEncoding('utf-8');
  daemonProc.stderr?.on('data', (d) => log('WARN', `[AIScheduler] stderr: ${String(d).slice(0, 200)}`));

  daemonProc.on('exit', (code) => {
    log('INFO', `[AIScheduler] daemon exited code=${code} (stoppedByUser=${stoppedByUser})`);
    daemonProc = null;
    daemonPid = null;
    // 清掉 latest.running (避免 UI 显示假存活)。
    // 关键: 只有用户主动停止才清 config.enabled; 崩溃时保留 enabled=true 让 watchdog 自动重启。
    const clearEnabled = stoppedByUser ? 'cfg[\'enabled\'] = False' : '# crash: 保留 enabled 让 watchdog 重启';
    try {
      spawnSync(PYTHON, ['-c', `
import sys
sys.path.insert(0, '.')
from quant.data.cache import create_cache
c = create_cache()
s = c.get('ai:scheduler:latest') or {}
s['running'] = False
s['crashed'] = ${JSON.stringify(!stoppedByUser)}
c.set('ai:scheduler:latest', s)
cfg = c.get('ai:scheduler:config') or {}
${clearEnabled}
c.set('ai:scheduler:config', cfg)
`], { cwd: ROOT_DIR, env: { ...process.env, QUANT_SKIP_NODE_PROXY: '1', PYTHONIOENCODING: 'utf-8' }, windowsHide: true, timeout: 5000 });
    } catch (e) {
      log('WARN', `[AIScheduler] cleanup status failed: ${e.message}`);
    }
    stoppedByUser = false;  // 重置
  });
  daemonProc.on('error', (e) => {
    log('ERROR', `[AIScheduler] spawn error: ${e.message}`);
    daemonProc = null;
    daemonPid = null;
  });

  return { success: true, message: 'AI 调度器已启动', pid: daemonPid };
}

/** 停止 daemon (kill 子进程)。 */
export function stopDaemon() {
  if (daemonProc && daemonProc.exitCode === null) {
    stoppedByUser = true;  // 标记为用户主动停止, exit handler 据此清 enabled
    // 先同步清掉 enabled/latest.running (不依赖异步 exit handler, 确保用户停止后 watchdog 不会重启)
    try {
      spawnSync(PYTHON, ['-c', `
import sys
sys.path.insert(0, '.')
from quant.data.cache import create_cache
c = create_cache()
s = c.get('ai:scheduler:latest') or {}
s['running'] = False
s['crashed'] = False
c.set('ai:scheduler:latest', s)
cfg = c.get('ai:scheduler:config') or {}
cfg['enabled'] = False
c.set('ai:scheduler:config', cfg)
`], { cwd: ROOT_DIR, env: { ...process.env, QUANT_SKIP_NODE_PROXY: '1', PYTHONIOENCODING: 'utf-8' }, windowsHide: true, timeout: 5000 });
    } catch (e) { /* 非关键 */ }
    try {
      daemonProc.kill();
      log('INFO', '[AIScheduler] daemon killed by user');
    } catch (e) {
      log('WARN', `[AIScheduler] kill failed: ${e.message}`);
    }
    const pid = daemonPid;
    return { success: true, message: '已停止 AI 调度器', pid };
  }
  const cached = cachedDaemonPid();
  if (cached.running && pidAlive(cached.pid)) {
    const ok = killPid(cached.pid);
    clearCachedStatus(true);
    stoppedByUser = true;
    return ok ? { success: true, message: '已停止缓存中的 AI 调度器', pid: cached.pid }
              : { success: false, error: `无法停止缓存中的 AI 调度器(pid=${cached.pid})` };
  }
  clearCachedStatus(true);
  return { success: false, error: '调度器未在运行' };
}

/** daemon 运行状态 (内存镜像, 用于快速判断)。真实状态由路由从 SQLite 读取。 */
export function daemonMeta() {
  return {
    running: !!(daemonProc && daemonProc.exitCode === null),
    pid: daemonPid,
    started_at: daemonStartedAt,
  };
}

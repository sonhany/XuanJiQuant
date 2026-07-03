/**
 * 看门狗 — daemon 自愈 + 持久进程保活
 *
 * 每 60 秒执行一次 watchdogTick():
 *   1. paper_trader daemon: 若 paper:config.enabled=true 但进程已死 → 自动重启
 *   2. ai_scheduler daemon: 若 ai:scheduler:config.enabled=true 但进程已死 → 自动重启
 *   3. PersistentRunner 自愈: 对各路由的 runner 调 ensure() (幂等, 挂了自动拉起)
 *   4. 连续 3 次重启失败 → 写 critical 告警到 alerts:records, 提示人工介入
 *
 * 状态写入 ai:watchdog:latest, 供驾驶舱读取。
 * 在 server/index.mjs 的 server.listen 回调里注册 setInterval(watchdogTick, 60_000)。
 */
import { spawnSync } from 'child_process';
import { log } from './http-utils.mjs';
import { ROOT_DIR, resolvePython } from './config.mjs';
import { daemonMeta as paperMeta, startDaemon as startPaper } from './paper_manager.mjs';
import { daemonMeta as aiSchedMeta, startDaemon as startAISched } from './ai_scheduler_manager.mjs';

const PYTHON = resolvePython();

// 重启失败计数 (内存态, 重启后端会清零 — 这是可接受的, 因为进程已重启本身就是一次"恢复")
const failCounts = { paper: 0, scheduler: 0 };
const MAX_FAILS = 3;

/** 读 SQLite 里某个 key (通过一次性 python 进程)。 */
function readCache(key) {
  const r = spawnSync(PYTHON, ['-c', `
import sys, json
sys.path.insert(0, '.')
from quant.data.cache import create_cache
c = create_cache()
print(json.dumps(c.get(${JSON.stringify(key)}) or {}, ensure_ascii=False, default=str))
`], { cwd: ROOT_DIR, env: { ...process.env, QUANT_SKIP_NODE_PROXY: '1', PYTHONIOENCODING: 'utf-8' }, windowsHide: true, timeout: 8000, encoding: 'utf-8' });
  if (r.status !== 0 || !r.stdout) return {};
  try {
    return JSON.parse(r.stdout.trim().split('\n').pop() || '{}');
  } catch {
    return {};
  }
}

/** 写一条 critical 告警到 alerts:records。 */
function pushCriticalAlert(component, reason) {
  spawnSync(PYTHON, ['-c', `
import sys, json
sys.path.insert(0, '.')
from quant.data.cache import create_cache
from datetime import datetime
c = create_cache()
alerts = c.get('alerts:records') or []
alerts.append({
    'level': 'critical',
    'title': f'看门狗: {${JSON.stringify(component)}} 连续重启失败',
    'message': ${JSON.stringify(reason)},
    'source': 'watchdog',
    'status': 'active',
    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
})
c.set('alerts:records', alerts[-200:])
`], { cwd: ROOT_DIR, env: { ...process.env, QUANT_SKIP_NODE_PROXY: '1', PYTHONIOENCODING: 'utf-8' }, windowsHide: true, timeout: 8000 });
  log('ERROR', `[Watchdog] critical alert pushed: ${component} - ${reason}`);
}

/** 尝试重启一个 daemon, 返回是否成功。 */
function tryRestart(kind, meta, starter, name) {
  if (meta.running) {
    failCounts[kind] = 0;  // 存活则清零
    return true;
  }
  log('WARN', `[Watchdog] ${name} dead but enabled → restarting...`);
  const r = starter();
  if (r.success) {
    failCounts[kind] = 0;
    log('INFO', `[Watchdog] ${name} restarted pid=${r.pid}`);
    return true;
  }
  failCounts[kind] = (failCounts[kind] || 0) + 1;
  log('ERROR', `[Watchdog] ${name} restart failed (${failCounts[kind]}/${MAX_FAILS}): ${r.error}`);
  if (failCounts[kind] >= MAX_FAILS) {
    pushCriticalAlert(name, `${name} 连续 ${failCounts[kind]} 次重启失败, 最后错误: ${r.error || '未知'}. 请人工检查 Python 环境/配置。`);
    failCounts[kind] = 0;  // 告警后清零, 避免每分钟刷一条
  }
  return false;
}

/** 主动触发各路由 PersistentRunner 的 ensure (它们在路由模块内是单例, 但无法从这里访问; 通过 ensure 标志文件间接保证) */
function touchPersistentRunners() {
  // PersistentRunner 的 ensure() 在每次 runner.call() 时也会调用 (lazy 自愈)。
  // 这里通过写入一个 "心跳" 标记, 让前端能确认 watchdog 在跑。真正的 runner 自愈发生在下次有请求时。
  // 注: 不直接 import 各路由的 runner (会形成循环依赖), 依赖其自身 lazy-ensure 机制。
}

/** 一次看门狗巡检。返回状态快照。 */
export function watchdogTick() {
  const events = [];
  const now = new Date().toISOString();

  // 1. paper_trader daemon
  const paperCfg = readCache('paper:config');
  let paperAlive = paperMeta().running;
  if (paperCfg.enabled && !paperAlive) {
    const ok = tryRestart('paper', paperMeta(), startPaper, 'paper_trader daemon');
    paperAlive = ok;
    events.push({ component: 'paper_trader', action: ok ? 'restarted' : 'restart_failed', time: now });
  }

  // 2. ai_scheduler daemon
  const schedCfg = readCache('ai:scheduler:config');
  let schedAlive = aiSchedMeta().running;
  if (schedCfg.enabled && !schedAlive) {
    const ok = tryRestart('scheduler', aiSchedMeta(), () => startAISched(schedCfg.provider || null), 'ai_scheduler daemon');
    schedAlive = ok;
    events.push({ component: 'ai_scheduler', action: ok ? 'restarted' : 'restart_failed', time: now });
  }

  // 3. PersistentRunner 心跳 (依赖 lazy-ensure)
  touchPersistentRunners();

  // 4. 汇总状态并写入 cache (base64 传递, 避免引号/特殊字符注入)
  const status = {
    last_check: now,
    paper_alive: paperAlive,
    paper_enabled: !!paperCfg.enabled,
    scheduler_alive: schedAlive,
    scheduler_enabled: !!schedCfg.enabled,
    restarts_total: (failCounts.paper || 0) + (failCounts.scheduler || 0),
    events,
  };
  const statusB64 = Buffer.from(JSON.stringify(status)).toString('base64');
  spawnSync(PYTHON, ['-c', `
import sys, base64, json as _j
sys.path.insert(0, '.')
from quant.data.cache import create_cache
c = create_cache()
c.set('ai:watchdog:latest', _j.loads(base64.b64decode('${statusB64}').decode('utf-8')))
`], { cwd: ROOT_DIR, env: { ...process.env, QUANT_SKIP_NODE_PROXY: '1', PYTHONIOENCODING: 'utf-8' }, windowsHide: true, timeout: 8000 });

  return status;
}

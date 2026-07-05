/**
 * 模拟盘 API 路由 — 配置/启停/状态/日志/立即运行
 *
 * actions:
 *   status      → daemon 状态 + 配置 + 上次运行结果
 *   get_config  → 读 paper:config
 *   set_config  → 写 paper:config
 *   start       → 启动 daemon
 *   stop        → 停止 daemon
 *   run_now     → 单次执行 paper_trader.py --once (跑完即退出)
 *   log         → 读 paper:log (最近运行日志)
 */
import { spawnSync, spawn } from 'child_process';
import { log, json, readBody } from '../http-utils.mjs';
import { ROOT_DIR } from '../config.mjs';
import { startDaemon, stopDaemon, daemonMeta } from '../paper_manager.mjs';
import { startDaemon as startAIScheduler, stopDaemon as stopAIScheduler, daemonMeta as aiSchedulerMeta } from '../ai_scheduler_manager.mjs';
import { PersistentRunner } from '../persistent_runner.mjs';

const PYTHON = process.env.PYTHON || 'python';
const PAPER_SCRIPT = `${ROOT_DIR}/scripts/paper_trader.py`;

// ── 持久化 Python 进程 (高频只读 action 走这里, 避免 spawnSync 启动开销) ──
const runner = new PersistentRunner('paper_runner.py');
runner.ensure();
// 可路由到 runner 的 action 集合 (高频只读, 纯缓存读取, 不需要 Node 内存态);
// status / ai_scheduler_status 需要 daemonMeta() (Node 内存), 不走 runner
const RUNNER_ACTIONS = new Set([
  'progress', 'log', 'ai_all_status', 'ai_screen_status',
  'ai_autonomous_status', 'ai_autonomous_get_config',
  'ai_operator_status',
  'ai_loop_status', 'ai_memory_status', 'ai_verifier_status',
  'ai_tool_executor_status', 'ai_updates_status',
  'watchdog_status', 'llm_usage',
  'global_context_status', 'report', 'get_config', 'benchmark',
]);

// ─── 模块加载时自愈: 只清理确认已死亡的旧 pid 状态 ─────────────
function selfHealOrphanStatus() {
  try {
    spawnSync(PYTHON, ['-c', `
import sys
sys.path.insert(0, '.')
from quant.data.cache import create_cache
c = create_cache()
s = c.get('paper:status') or {}
# 只清理没有 pid 的旧 running 状态；有 pid 的状态由 paper_manager 的跨进程检查处理。
if s.get('running') and not s.get('pid'):
    s['running'] = False
    s['orphan_checked'] = True
    c.set('paper:status', s)
    print('HEALED')
`], { cwd: ROOT_DIR, env: { ...process.env, QUANT_SKIP_NODE_PROXY: '1', PYTHONIOENCODING: 'utf-8' }, windowsHide: true, timeout: 8000, encoding: 'utf-8' });
  } catch (e) {
    log('WARN', `[paper] self-heal failed: ${e.message}`);
  }
}
selfHealOrphanStatus();


/** 同步跑一段 Python, 返回 JSON 或 {_error}。 */
function runPython(code, timeout = 60_000) {
  const r = spawnSync(PYTHON, ['-c', code], {
    encoding: 'utf-8',
    timeout,
    cwd: ROOT_DIR,
    env: { ...process.env, QUANT_SKIP_NODE_PROXY: '1', PYTHONIOENCODING: 'utf-8' },
    windowsHide: true,
  });
  if (r.status !== 0) {
    return { _error: (r.stderr || 'python failed').slice(0, 500), _code: r.status };
  }
  try {
    return JSON.parse(r.stdout.trim().split('\n').pop() || '{}');
  } catch {
    return { output: r.stdout };
  }
}

/** 读 SQLite 的 paper:* 键 */
function readPaperKeys() {
  return runPython(`
import sys, json
sys.path.insert(0, '.')
from quant.data.cache import create_cache
from scripts.paper_runner import _paper_config
c = create_cache()
print(json.dumps({
  'config': _paper_config(c),
  'status': c.get('paper:status'),
  'log': c.get('paper:log') or [],
}, ensure_ascii=False, default=str))
`);
}

export async function handlePaper(req, res, ctx = {}) {
  let body = {};
  try {
    body = req.method === 'POST' ? await readBody(req) : {};
  } catch {
    body = {};
  }
  const action = body.action || 'status';
  if (ctx.authorize && !ctx.authorize(req, body)) {
    return json(res, 403, { success: false, error: '控制面请求未授权或非本机来源' });
  }

  try {
    // ─── 高频只读 action 走持久化 Python 进程 (省 ~280ms 启动开销) ───
    // 失败自动降级到下方 runPython (spawnSync), 不影响功能
    if (RUNNER_ACTIONS.has(action)) {
      try {
        const r = await runner.call(body, 15000);
        return json(res, 200, r);
      } catch (e) {
        log('WARN', `[paper] runner.call(${action}) failed, fallback to spawnSync: ${e.message}`);
        // 降级: 继续走下方对应的 if 分支
      }
    }

    // ─── 状态 (默认) ───────────────────────────
    if (action === 'status') {
      const meta = daemonMeta();
      const keys = readPaperKeys();
      if (keys._error) {
        return json(res, 200, { success: true, data: { daemon: meta, config: null, status: null, error: keys._error } });
      }
      // 真实运行标志以 SQLite 为准, 但进程存活以内存为准; 二者取并集
      const dbStatus = keys.status || {};
      const running = meta.running || !!dbStatus.running;
      return json(res, 200, {
        success: true,
        data: {
          daemon: { ...meta, running, started_at: meta.started_at || dbStatus.started_at },
          config: keys.config,
          status: dbStatus,
        },
      });
    }

    // ─── 读配置 ───────────────────────────────
    if (action === 'get_config') {
      const keys = readPaperKeys();
      return json(res, 200, { success: !keys._error, data: keys.config, error: keys._error });
    }

    // ─── 写配置 ───────────────────────────────
    if (action === 'set_config') {
      const cfg = body.config;
      if (!cfg || typeof cfg !== 'object') {
        return json(res, 400, { success: false, error: 'config 对象必填' });
      }
      // 把 config 作为 base64 传入, 避免引号/特殊字符注入
      const cfgB64 = Buffer.from(JSON.stringify(cfg)).toString('base64');
      const r = runPython(`
import sys, json, base64
sys.path.insert(0, '.')
from quant.data.cache import create_cache
c = create_cache()
new_cfg = json.loads(base64.b64decode('${cfgB64}').decode('utf-8'))
# 深度合并: 保留已有配置, 用新字段覆盖 (嵌套 dict 也合并)
old = c.get('paper:config') or {}
merged = dict(old)
for k, v in new_cfg.items():
    if isinstance(v, dict) and isinstance(merged.get(k), dict):
        merged[k] = {**merged[k], **v}
    else:
        merged[k] = v
c.set('paper:config', merged)
print(json.dumps({'success': True, 'config': c.get('paper:config')}, ensure_ascii=False, default=str))
`);
      return json(res, r._error ? 500 : 200, r._error ? r : { success: true, data: r.config });
    }

    // ─── 启动 daemon ──────────────────────────
    if (action === 'start') {
      const r = startDaemon();
      if (r.success) {
        // 合并 enabled + status 写入为一次 Python 调用, 减少与 daemon 的 SQLite 锁竞争
        // 用 try/catch + timeout 保护: 即使写状态失败也不影响 start 响应返回
        try {
          runPython(`
import sys, json
sys.path.insert(0, '.')
from quant.data.cache import create_cache
c = create_cache()
cfg = c.get('paper:config') or {}
cfg['enabled'] = True
c.set('paper:config', cfg)
s = c.get('paper:status') or {}
s['running'] = True
s['started_at'] = '${new Date().toISOString()}'
c.set('paper:status', s)
print(json.dumps({'ok': True}))
`, 5000);
        } catch (e) {
          log('WARN', `[paper] start: write status failed (non-fatal): ${e.message}`);
        }
      }
      return json(res, r.success ? 200 : 409, r);
    }

    // ─── 停止 daemon ──────────────────────────
    if (action === 'stop') {
      runPython(`
import sys
sys.path.insert(0, '.')
from quant.data.cache import create_cache
c = create_cache()
cfg = c.get('paper:config') or {}
cfg['enabled'] = False
c.set('paper:config', cfg)
`);
      const r = stopDaemon();
      // 同步把 status.running 清掉
      runPython(`
import sys
sys.path.insert(0, '.')
from quant.data.cache import create_cache
c = create_cache()
s = c.get('paper:status') or {}
s['running'] = False
c.set('paper:status', s)
`);
      return json(res, r.success ? 200 : 404, r);
    }

    // ─── 立即运行一次 (非阻塞, 前端轮询 progress 看进度) ────
    if (action === 'run_now') {
      log('INFO', '[PaperTrader] run_now triggered (non-blocking)');

      // 先清除旧进度和旧结果
      runPython(`
import sys
sys.path.insert(0, '.')
from quant.data.cache import create_cache
c = create_cache()
c.set('paper:progress', [])
c.set('paper:run_result', None)
c.set('paper:run_active', True)
`);

      // 非阻塞 spawn — 立即返回, 前端轮询 progress 端点
      const child = spawn(PYTHON, [PAPER_SCRIPT, '--once', '--source', 'manual'], {
        encoding: 'utf-8',
        cwd: ROOT_DIR,
        env: { ...process.env, QUANT_SKIP_NODE_PROXY: '1', PYTHONIOENCODING: 'utf-8' },
        windowsHide: true,
      });

      let stdoutBuf = '';
      let stderrBuf = '';
      child.stdout.setEncoding('utf-8');
      child.stdout.on('data', (chunk) => { stdoutBuf += chunk; });
      child.stderr.setEncoding('utf-8');
      child.stderr.on('data', (chunk) => { stderrBuf += chunk; });

      child.on('exit', (code) => {
        log('INFO', `[PaperTrader] run_now exited code=${code}`);
        // 解析 stdout 最后一行 JSON, 写入 paper:run_result 供前端轮询
        let result = null;
        if (code === 0) {
          try {
            const lastLine = stdoutBuf.trim().split('\n').pop();
            result = JSON.parse(lastLine);
          } catch {
            result = { success: false, error: '解析结果失败', raw: stdoutBuf.slice(0, 500) };
          }
        } else {
          result = { success: false, error: (stderrBuf || 'paper_trader --once failed').slice(0, 500) };
        }
        // 写入结果供前端轮询读取 (base64 传递避免引号注入)
        const resultB64 = Buffer.from(JSON.stringify(result)).toString('base64');
        runPython(`
import sys, base64
sys.path.insert(0, '.')
import json as _json
from quant.data.cache import create_cache
c = create_cache()
_result = _json.loads(base64.b64decode('${resultB64}').decode('utf-8'))
c.set('paper:run_result', _result)
c.set('paper:run_active', False)
`);
      });

      child.on('error', (e) => {
        log('ERROR', `[PaperTrader] spawn error: ${e.message}`);
        runPython(`
import sys, json
sys.path.insert(0, '.')
from quant.data.cache import create_cache
c = create_cache()
c.set('paper:run_result', {'success': False, 'error': '${e.message.replace(/'/g, "\\'")}'})
c.set('paper:run_active', False)
`);
      });

      return json(res, 200, { success: true, started: true, message: '已在后台启动, 请查看实时日志' });
    }

    // ─── 实时进度轮询 ─────────────────────────
    if (action === 'progress') {
      const r = runPython(`
import sys, json
sys.path.insert(0, '.')
from quant.data.cache import create_cache
c = create_cache()
events = c.get('paper:progress') or []
result = c.get('paper:run_result')
active = bool(c.get('paper:run_active'))
status = c.get('paper:status') or {}
print(json.dumps({'events': events, 'running': active, 'result': result,
                   'daemon_running': status.get('running', False)}, ensure_ascii=False, default=str))
`);
      return json(res, r._error ? 500 : 200, r._error ? r : { success: true, data: r });
    }

    // ─── 运行日志 ─────────────────────────────
    if (action === 'log') {
      const keys = readPaperKeys();
      const logs = keys.log || [];
      const limit = parseInt(body.limit) || 50;
      return json(res, 200, { success: true, data: logs.slice(-limit).reverse() });
    }

    // ─── 每日日报 (读已有) ────────────────────
    if (action === 'report') {
      const r = runPython(`
import sys, json
sys.path.insert(0, '.')
from quant.data.cache import create_cache
from scripts.data_freshness import is_data_stale
c = create_cache()
report = c.get('paper:report:latest')
# 统一入口实时重算 is_stale
if report and isinstance(report, dict):
    data = report.get('data', {})
    data['is_stale'] = is_data_stale()
print(json.dumps({'success': True, 'data': report}, ensure_ascii=False, default=str))
`);
      return json(res, r._error ? 500 : 200, r._error ? r : { success: true, data: r.data });
    }

    // ─── 生成最新日报 ─────────────────────────
    if (action === 'generate_report') {
      const r = runPython(`
import sys, json
sys.path.insert(0, '.')
from scripts.daily_report import generate_report, save_report
report = generate_report()
save_report(report)
print(json.dumps({'success': True, 'data': report}, ensure_ascii=False, default=str))
`, 90000);
      return json(res, r._error ? 500 : 200, r._error ? r : { success: true, data: r.data });
    }

    // ─── AI Quant Operator 总控 ─────────────────
    if (action === 'ai_operator_status') {
      const r = runPython(`
import sys, json
sys.path.insert(0, '.')
from scripts.ai_operator import get_status
print(json.dumps({'success': True, 'data': get_status()}, ensure_ascii=False, default=str))
`, 30000);
      return json(res, r._error ? 500 : 200, r._error ? r : { success: true, data: r.data });
    }

    if (action === 'ai_operator_run') {
      const provider = body.provider || null;
      const providerArg = provider ? JSON.stringify(provider) : 'None';
      const r = runPython(`
import sys, json
sys.path.insert(0, '.')
from scripts.ai_operator import run_operator
provider = ${providerArg}
plan = run_operator(provider)
print(json.dumps({'success': True, 'data': plan}, ensure_ascii=False, default=str))
`, 90000);
      return json(res, r._error ? 500 : 200, r._error ? r : { success: true, data: r.data });
    }

    // ─── 基准对比 ─────────────────────────────
    if (action === 'benchmark') {
      const r = runPython(`
import sys, json
sys.path.insert(0, '.')
from scripts.benchmark import refresh_benchmark
bm = refresh_benchmark()
print(json.dumps({'success': True, 'data': bm}, ensure_ascii=False, default=str))
`);
      return json(res, r._error ? 500 : 200, r._error ? r : { success: true, data: r.data });
    }

    // ─── LLM 连接测试 ──────────────────────────
    if (action === 'test_llm') {
      const provider = body.provider || 'glm';
      const r = runPython(`
import sys, json
sys.path.insert(0, '.')
from scripts.llm_client import chat, get_api_key, get_provider_label
provider = ${JSON.stringify(provider)}
key = get_api_key(provider)
if not key:
    print(json.dumps({'success': False, 'error': '未配置 API Key: ' + provider}))
else:
    r = chat(provider, '你是测试助手', '请回复"连接成功"四个字', timeout=20, max_tokens=300, scene='test')
    print(json.dumps({'success': r['success'], 'text': r.get('text',''), 'error': r.get('error',''),
                       'provider': provider, 'label': get_provider_label(provider),
                       'usage': r.get('usage', {})}, ensure_ascii=False))
`, 20000);
      return json(res, r._error ? 500 : 200, r._error ? r : { success: r.success, data: r });
    }

    // ─── LLM Token 使用量统计 ──────────────────
    if (action === 'llm_usage') {
      const days = parseInt(body.days) || 7;
      const r = runPython(`
import sys, json
sys.path.insert(0, '.')
from scripts.llm_usage import get_usage_stats
print(json.dumps({'success': True, 'data': get_usage_stats(${days})}, ensure_ascii=False, default=str))
`, 10000);
      return json(res, r._error ? 500 : 200, r._error ? r : { success: true, data: r.data });
    }

    if (action === 'llm_usage_reset') {
      const r = runPython(`
import sys, json
sys.path.insert(0, '.')
from scripts.llm_usage import reset_usage
print(json.dumps({'success': reset_usage()}, ensure_ascii=False))
`, 10000);
      return json(res, r._error ? 500 : 200, r._error ? r : { success: true, data: r });
    }

    // ─── AI 五层系统 ────────────────────────────

    // L1 数据层 (支持 auto_fix 自动补数)
    if (action === 'ai_data_run') {
      const providerArg = JSON.stringify(body.provider || 'glm');
      const autoFix = body.auto_fix ? 'True' : 'False';
      const r = runPython(`
import sys, json
sys.path.insert(0, '.')
from scripts.ai_data_agent import run_data_agent
out = run_data_agent(${providerArg}, auto_fix=${autoFix})
print(json.dumps({'success': True, 'data': out}, ensure_ascii=False, default=str))
`, body.auto_fix ? 300000 : 120000);
      return json(res, r._error ? 500 : 200, r._error ? r : { success: true, data: r.data });
    }

    const AI_LAYER_MAP = {
      'ai_data_status': { module: 'scripts.ai_data_agent', func: 'get_status', timeout: 15000 },
      'ai_factor_run': { module: 'scripts.ai_factor_agent', func: 'run_factor_factory', timeout: 120000 },
      'ai_factor_status': { module: 'scripts.ai_factor_agent', func: 'get_status', timeout: 15000 },
      'ai_strategy_run': { module: 'scripts.ai_strategy_agent', func: 'run_strategy_factory', timeout: 120000 },
      'ai_strategy_status': { module: 'scripts.ai_strategy_agent', func: 'get_status', timeout: 15000 },
      'ai_execution_run': { module: 'scripts.ai_execution_agent', func: 'generate_execution_advice', timeout: 60000 },
      'ai_execution_review': { module: 'scripts.ai_execution_agent', func: 'execution_review', timeout: 60000 },
      'ai_execution_status': { module: 'scripts.ai_execution_agent', func: 'get_status', timeout: 15000 },
      'ai_risk_run': { module: 'scripts.ai_risk_agent', func: 'run_risk_monitor', timeout: 60000 },
      'ai_risk_status': { module: 'scripts.ai_risk_agent', func: 'get_status', timeout: 15000 },
    };

    const layerCfg = AI_LAYER_MAP[action];
    if (layerCfg) {
      const providerArg = JSON.stringify(body.provider || 'glm');
      const r = runPython(`
import sys, json
sys.path.insert(0, '.')
from ${layerCfg.module} import ${layerCfg.func}
out = ${layerCfg.func}(${providerArg}) if '${layerCfg.func}' not in ('get_status',) else ${layerCfg.func}()
print(json.dumps({'success': True, 'data': out}, ensure_ascii=False, default=str))
`, layerCfg.timeout);
      return json(res, r._error ? 500 : 200, r._error ? r : { success: true, data: r.data });
    }

    // ─── 全球实时动态 ──────────────────────────
    if (action === 'global_context_run') {
      const r = runPython(`
import sys, json
sys.path.insert(0, '.')
from scripts.global_context import collect_global_context
print(json.dumps({'success': True, 'data': collect_global_context()}, ensure_ascii=False, default=str))
`, 30000);
      return json(res, r._error ? 500 : 200, r._error ? r : { success: true, data: r.data });
    }
    if (action === 'global_context_status') {
      const r = runPython(`
import sys, json
sys.path.insert(0, '.')
from scripts.global_context import get_status
print(json.dumps({'success': True, 'data': get_status()}, ensure_ascii=False, default=str))
`);
      return json(res, r._error ? 500 : 200, r._error ? r : { success: true, data: r.data });
    }

    // ─── AI 自我迭代闭环 ────────────────────────
    if (action === 'ai_loop_run') {
      const providerArg = JSON.stringify(body.provider || 'glm');
      const triggerPaper = body.trigger_paper ? 'True' : 'False';
      const r = runPython(`
import sys, json
sys.path.insert(0, '.')
from scripts.ai_loop import run_loop
out = run_loop(${providerArg}, trigger_paper=${triggerPaper}, source='manual')
print(json.dumps({'success': True, 'data': out}, ensure_ascii=False, default=str))
`, 300000);
      return json(res, r._error ? 500 : 200, r._error ? r : { success: true, data: r.data });
    }
    if (action === 'ai_loop_status') {
      const r = runPython(`
import sys, json
sys.path.insert(0, '.')
from scripts.ai_loop import get_status
print(json.dumps({'success': True, 'data': get_status()}, ensure_ascii=False, default=str))
`);
      return json(res, r._error ? 500 : 200, r._error ? r : { success: true, data: r.data });
    }

    // ─── 全局 AI 自主控制配置 ─────────────────────
    if (action === 'ai_autonomous_status' || action === 'ai_autonomous_get_config') {
      const r = runPython(`
import sys, json
sys.path.insert(0, '.')
from scripts.ai_objective import get_status, load_autonomous_config, compute_objective_status
if '${action}' == 'ai_autonomous_get_config':
    out = load_autonomous_config()
else:
    out = get_status()
    out['objective'] = compute_objective_status()
print(json.dumps({'success': True, 'data': out}, ensure_ascii=False, default=str))
`, 10000);
      return json(res, r._error ? 500 : 200, r._error ? r : { success: true, data: r.data });
    }

    if (action === 'ai_autonomous_set_config') {
      const cfg = body.config || {};
      const cfgB64 = Buffer.from(JSON.stringify(cfg)).toString('base64');
      const r = runPython(`
import sys, json, base64
sys.path.insert(0, '.')
from scripts.ai_objective import save_autonomous_config, compute_objective_status
patch = json.loads(base64.b64decode('${cfgB64}').decode('utf-8'))
cfg = save_autonomous_config(patch)
obj = compute_objective_status(cfg)
print(json.dumps({'success': True, 'config': cfg, 'objective': obj}, ensure_ascii=False, default=str))
`, 10000);
      return json(res, r._error ? 500 : 200, r._error ? r : { success: true, data: { config: r.config, objective: r.objective }, message: '全局 AI 自主配置已保存' });
    }

    if (action === 'ai_autonomous_start') {
      const cfg = body.config || {};
      if (Object.keys(cfg).length) {
        const cfgB64 = Buffer.from(JSON.stringify(cfg)).toString('base64');
        runPython(`
import sys, json, base64
sys.path.insert(0, '.')
from scripts.ai_objective import save_autonomous_config
save_autonomous_config(json.loads(base64.b64decode('${cfgB64}').decode('utf-8')))
print(json.dumps({'ok': True}))
`, 10000);
      }
      const r = startAIScheduler(body.provider || cfg.provider || null);
      return json(res, r.success ? 200 : 409, r);
    }

    if (action === 'ai_autonomous_stop') {
      const r = stopAIScheduler();
      return json(res, r.success ? 200 : 404, r);
    }

    if (action === 'ai_autonomous_run_once') {
      const meta = aiSchedulerMeta();
      if (meta.running) {
        return json(res, 409, { success: false, error: 'AI 调度器 daemon 正在运行, 请等待自动巡检或先停止 daemon' });
      }
      log('INFO', '[AIScheduler] autonomous run_once triggered');
      const child = spawn(process.env.PYTHON || 'python', [`${ROOT_DIR}/scripts/ai_scheduler.py`, '--once'], {
        cwd: ROOT_DIR,
        env: { ...process.env, QUANT_SKIP_NODE_PROXY: '1', PYTHONIOENCODING: 'utf-8' },
        windowsHide: true,
        stdio: ['ignore', 'ignore', 'pipe'],
      });
      runPython(`
import sys
sys.path.insert(0, '.')
from quant.data.cache import create_cache
c = create_cache()
s = c.get('ai:scheduler:latest') or {}
s['run_once_pid'] = ${child.pid || 0}
s['run_once_started_at'] = '${new Date().toISOString()}'
s['run_once_running'] = True
c.set('ai:scheduler:latest', s)
`, 5000);
      child.on('exit', (code) => {
        runPython(`
import sys
sys.path.insert(0, '.')
from quant.data.cache import create_cache
c = create_cache()
s = c.get('ai:scheduler:latest') or {}
s['run_once_running'] = False
s['running'] = False
s['run_once_exit_code'] = ${Number.isFinite(code) ? code : -1}
s['run_once_finished_at'] = '${new Date().toISOString()}'
c.set('ai:scheduler:latest', s)
`, 5000);
      });
      return json(res, 200, { success: true, started: true, pid: child.pid, message: '已后台触发一轮全局 AI 自主巡检' });
    }

    // ─── AI 自主调度器 (daemon 启停 + 状态) ─────────────
    // ai_loop_start/stop 为历史兼容别名；真实语义是启动/停止 ai_scheduler.py。
    if (action === 'ai_scheduler_start' || action === 'ai_loop_start') {
      const provider = body.provider || null;
      const r = startAIScheduler(provider);
      return json(res, r.success ? 200 : 409, r);
    }
    if (action === 'ai_scheduler_stop' || action === 'ai_loop_stop') {
      const r = stopAIScheduler();
      return json(res, r.success ? 200 : 404, r);
    }
    if (action === 'ai_scheduler_status') {
      const meta = aiSchedulerMeta();
      const r = runPython(`
import sys, json
sys.path.insert(0, '.')
from scripts.ai_scheduler import get_status
print(json.dumps({'success': True, 'data': get_status()}, ensure_ascii=False, default=str))
`, 8000);
      const data = r._error ? {} : (r.data || {});
      const cachedPid = data.pid;
      let cachedAlive = false;
      if (cachedPid) {
        try { process.kill(Number(cachedPid), 0); cachedAlive = true; } catch { cachedAlive = false; }
      }
      data.daemon_running = meta.running || cachedAlive;
      data.daemon_pid = meta.pid || (cachedAlive ? cachedPid : null);
      return json(res, 200, { success: true, data });
    }

    if (action === 'ai_verifier_run') {
      const mode = body.mode === 'full' ? 'full' : 'quick';
      const r = runPython(`
import sys, json
sys.path.insert(0, '.')
from scripts.ai_verifier import run_verifier
print(json.dumps({'success': True, 'data': run_verifier('${mode}')}, ensure_ascii=False, default=str))
`, mode === 'full' ? 180000 : 60000);
      return json(res, r._error ? 500 : 200, r._error ? r : { success: true, data: r.data });
    }

    if (action === 'ai_tool_executor_run') {
      const dryRun = body.dry_run !== false ? 'True' : 'False';
      const providerArg = JSON.stringify(body.provider || 'glm');
      const r = runPython(`
import sys, json
sys.path.insert(0, '.')
from scripts.ai_action_executor import run_executor
out = run_executor(source='manual', allowed_tools=None, dry_run=${dryRun}, provider=${providerArg})
print(json.dumps({'success': True, 'data': out}, ensure_ascii=False, default=str))
`, 180000);
      return json(res, r._error ? 500 : 200, r._error ? r : { success: true, data: r.data });
    }

    if (action === 'ai_self_improve_propose') {
      const providerArg = body.provider ? JSON.stringify(body.provider) : 'None';
      const r = runPython(`
import sys, json
sys.path.insert(0, '.')
from scripts.ai_self_improver import propose_update
out = propose_update(${providerArg})
print(json.dumps({'success': True, 'data': out}, ensure_ascii=False, default=str))
`, 60000);
      return json(res, r._error ? 500 : 200, r._error ? r : { success: true, data: r.data });
    }

    // 立即跑当前时段对应的一轮 (非阻塞触发)
    if (action === 'ai_scheduler_run_once') {
      const meta = aiSchedulerMeta();
      if (meta.running) {
        return json(res, 409, { success: false, error: 'AI 调度器 daemon 正在运行, 请等待自动巡检或先停止 daemon' });
      }
      log('INFO', '[AIScheduler] run_once triggered');
      const child = spawn(process.env.PYTHON || 'python', [`${ROOT_DIR}/scripts/ai_scheduler.py`, '--once'], {
        cwd: ROOT_DIR,
        env: { ...process.env, QUANT_SKIP_NODE_PROXY: '1', PYTHONIOENCODING: 'utf-8' },
        windowsHide: true,
        stdio: ['ignore', 'ignore', 'pipe'],
      });
      runPython(`
import sys
sys.path.insert(0, '.')
from quant.data.cache import create_cache
c = create_cache()
s = c.get('ai:scheduler:latest') or {}
s['run_once_pid'] = ${child.pid || 0}
s['run_once_started_at'] = '${new Date().toISOString()}'
s['run_once_running'] = True
c.set('ai:scheduler:latest', s)
`, 5000);
      let stderrBuf = '';
      child.stderr?.setEncoding('utf-8');
      child.stderr?.on('data', d => { stderrBuf += String(d); });
      child.on('exit', (code) => {
        const err = stderrBuf.slice(-500).replace(/'/g, "\\'");
        runPython(`
import sys
sys.path.insert(0, '.')
from quant.data.cache import create_cache
c = create_cache()
s = c.get('ai:scheduler:latest') or {}
s['run_once_running'] = False
s['running'] = False
s['run_once_exit_code'] = ${Number.isFinite(code) ? code : -1}
s['run_once_finished_at'] = '${new Date().toISOString()}'
s['run_once_error'] = '${err}'
c.set('ai:scheduler:latest', s)
`, 5000);
      });
      return json(res, 200, { success: true, started: true, pid: child.pid, message: '已后台触发一轮巡检' });
    }

    // ─── 看门狗状态 (供驾驶舱读取) ─────────────────────
    if (action === 'watchdog_status') {
      const r = runPython(`
import sys, json
sys.path.insert(0, '.')
from quant.data.cache import create_cache
c = create_cache()
print(json.dumps({'success': True, 'data': c.get('ai:watchdog:latest') or {
    'last_check': None, 'paper_alive': False, 'scheduler_alive': False, 'events': []
}}, ensure_ascii=False, default=str))
`, 8000);
      return json(res, r._error ? 500 : 200, r._error ? r : { success: true, data: r.data });
    }

    // ─── AI 全层状态聚合 (一次读全部5层+全球+闭环+选股+决策) ────
    if (action === 'ai_all_status') {
      const r = runPython(`
import sys, json
sys.path.insert(0, '.')
from quant.data.cache import create_cache
c = create_cache()
out = {
  'L1_data': c.get('ai:data:latest'),
  'L2_factor': {'approved': c.get('ai:factor:approved') or [], 'candidates': c.get('ai:factor:candidates') or []},
  'L3_strategy': {'approved': c.get('ai:strategy:approved') or [], 'candidates': c.get('ai:strategy:candidates') or []},
  'L4_execution': c.get('ai:execution:latest'),
  'L5_risk': c.get('ai:risk:latest'),
  'global': c.get('global:context:latest'),
  'operator': c.get('ai:operator:latest'),
  'loop': {'latest': c.get('ai:loop:latest'), 'progress': c.get('ai:loop:progress') or []},
  'lessons': (c.get('ai:memory:lessons') or [])[-5:],
  'memory': {'stats': c.get('ai:memory:stats'), 'summary': c.get('ai:memory:summary'), 'recent': (c.get('ai:memory:lessons') or [])[-10:]},
  'verifier': c.get('ai:verifier:latest'),
  'tool_executor': c.get('ai:tool_executor:latest'),
  'updates': c.get('ai:updates:latest'),
  'decision': c.get('ai:decision:latest'),
  'screen': c.get('ai:screen:latest'),
}
print(json.dumps({'success': True, 'data': out}, ensure_ascii=False, default=str))
`, 15000);
      return json(res, r._error ? 500 : 200, r._error ? r : { success: true, data: r.data });
    }

    // ─── 全市场选股 (手动触发 / 读结果) ─────────────
    if (action === 'ai_screen_run') {
      const providerArg = JSON.stringify(body.provider || 'glm');
      const topArg = Math.max(1, Math.min(100, parseInt(body.top_n || 20, 10) || 20));
      const r = runPython(`
import sys, json
sys.path.insert(0, '.')
from scripts.ai_stock_screener import screen_market
out = screen_market(top_n=${topArg}, provider=${providerArg})
print(json.dumps({'success': True, 'data': out}, ensure_ascii=False, default=str))
`, 200000);
      return json(res, r._error ? 500 : 200, r._error ? r : { success: true, data: r.data });
    }

    // ─── AI 全层运行 (一键跑全部5层) ─────────────
    if (action === 'ai_all_run') {
      const providerArg = JSON.stringify(body.provider || 'glm');
      const r = runPython(`
import sys, json
sys.path.insert(0, '.')
from scripts.ai_data_agent import run_data_agent
from scripts.ai_factor_agent import run_factor_factory
from scripts.ai_strategy_agent import run_strategy_factory
from scripts.ai_execution_agent import generate_execution_advice, execution_review
from scripts.ai_risk_agent import run_risk_monitor
results = {}
for name, func in [('L1_data', run_data_agent), ('L2_factor', run_factor_factory), ('L3_strategy', run_strategy_factory)]:
    try:
        results[name] = func(${providerArg})
    except Exception as e:
        results[name] = {'success': False, 'error': str(e)[:200]}
try:
    results['L4_execution'] = generate_execution_advice(${providerArg})
    results['L4_review'] = execution_review(${providerArg})
except Exception as e:
    results['L4'] = {'success': False, 'error': str(e)[:200]}
try:
    results['L5_risk'] = run_risk_monitor(${providerArg})
except Exception as e:
    results['L5_risk'] = {'success': False, 'error': str(e)[:200]}
print(json.dumps({'success': True, 'data': results}, ensure_ascii=False, default=str))
`, 300000);
      return json(res, r._error ? 500 : 200, r._error ? r : { success: true, data: r.data });
    }

    return json(res, 400, { success: false, error: `Unknown action: ${action}` });
  } catch (e) {
    log('PAPER', `error: ${e.message}`);
    return json(res, 500, { success: false, error: e.message });
  }
}

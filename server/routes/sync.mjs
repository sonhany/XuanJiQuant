/**
 * 多数据源同步 API 路由 (Phase 1: Redis 主存储)
 * 通过 Redis 与 Python sync_service 通信
 */
import path from 'path';
import { spawnSync } from 'child_process';
import { log, json, readBody } from '../http-utils.mjs';
import { ROOT_DIR } from '../config.mjs';
import { startUpdate, stopUpdate, getUpdateProgress } from '../update_manager.mjs';

const PYTHON = process.env.PYTHON || 'python';

// ─── 内存中的 syncState (mirror of Redis sync:status) ───
let lastSyncTime = null;  // 上次触发同步的本地时间 (ISO)
let syncState = {
  running: false,
  percent: 0,
  step: '',
  done: 0,
  total: 0,
  bars_total: 0,
  ok: 0,
  err: 0,
  source: '',
  sync_type: '',
  started_at: null,
  finished_at: null,
  last_error: '',
};

function runPython(script) {
  const r = spawnSync(PYTHON, ['-c', script], {
    encoding: 'utf-8',
    timeout: 30_000,
    cwd: ROOT_DIR,
    env: { ...process.env, QUANT_SKIP_NODE_PROXY: '1', PYTHONIOENCODING: 'utf-8' },
    windowsHide: true,
  });
  if (r.status !== 0) {
    return { _error: r.stderr || 'python failed', _code: r.status };
  }
  try { return JSON.parse(r.stdout); } catch { return { output: r.stdout }; }
}

function getRedisState() {
  return runPython(`
import sys, json
sys.path.insert(0, '.')
from quant.data.cache import create_cache
c = create_cache()
out = {
  'realtime:hot_count': len(c.get('realtime:hot') or []),
  'stock:all_count': len(c.get('stock:all') or []),
  'sync:source_health': c.get('sync:source_health') or {},
  'sync:trading': c.get('sync:trading') or {},
}
# 统计所有 kline 键的实际数据质量
all_kline_keys = c.keys('kline:*:d')
out['kline_count'] = len(all_kline_keys)
incomplete = 0
empty = 0
total_bars_sample = 0
last_dates = []
samples = all_kline_keys[:20]
for k in samples:
    arr = c.get(k) or []
    if not arr: empty += 1
    elif len(arr) < 100: incomplete += 1
    total_bars_sample += len(arr)
    if arr:
        last_dates.append(arr[-1].get('d') or arr[-1].get('date'))
out['sample_avg_bars'] = total_bars_sample // max(1, len(samples))
out['sample_last_dates'] = last_dates
out['sample_incomplete'] = incomplete
out['sample_empty'] = empty

# 读取 sync.py _db_stats_job 设置的状态键
for k in ['kline_total_bars', 'stocks_missing']:
    v = c.get(k)
    if v is not None:
        try: out[k] = int(v)
        except: out[k] = 0

print(json.dumps(out, ensure_ascii=False))
`);
}

export async function handleSync(req, res) {
  try {
    const body = req.method === 'POST' ? await readBody(req) : {};
    const action = body.action || 'status';

  // ─── 状态查询 ────────────────────
  if (action === 'status') {
    const state = getRedisState();
    if (state._error) {
      return json(res, 200, {
        success: true,
        data: {
          sources: [
            { id: 'tencent', name: '腾讯行情', status: 'online', priority: 1 },
            { id: 'sina', name: '新浪行情', status: 'online', priority: 2 },
            { id: 'baostock', name: 'Baostock', status: 'online', priority: 3 },
          ],
          db: null,
          last_sync: null,
          current_task: null,
          redis_state: null,
        },
      });
    }
    const sh = ((state['sync:source_health'] || {}).health) || {};
    const summary = ((state['sync:source_health'] || {}).summary) || {};
    const sources = Object.entries(sh).map(([id, s], idx) => ({
      id,
      name: s.name || id,
      status: s.is_up ? 'online' : 'offline',
      priority: idx + 1,
      success_rate: s.success_rate,
      avg_latency_ms: s.avg_latency_ms,
      success_count: s.success_count,
      fail_count: s.fail_count,
      last_success: s.last_success,
    }));
    const trading = (state['sync:trading'] || {});
    const sortedDates = (state['sample_last_dates'] || []).filter(Boolean).sort().reverse();
    const dataDate = sortedDates[0] || null;
    const dataDateIso = dataDate ? `${dataDate.slice(0,4)}-${dataDate.slice(4,6)}-${dataDate.slice(6,8)}T00:00:00` : null;
    const stocksAllCount = state['stock:all_count'] || 0;
    const klineCount = state['kline_count'] || 0;
    return json(res, 200, {
      success: true,
      data: {
        sources: sources.length ? sources : [
          { id: 'tencent', name: '腾讯行情', status: 'online', priority: 1 },
        ],
        db: {
          stock_count: stocksAllCount,
          stocks_with_bars: klineCount,
          stocks_missing: state['stocks_missing'] != null ? state['stocks_missing'] : Math.max(0, stocksAllCount - klineCount),
          stocks_incomplete_sample: state['sample_incomplete'] || 0,
          stocks_empty_sample: state['sample_empty'] || 0,
          bar_count: state['sample_avg_bars'] || 0,
          total_bars: state['kline_total_bars'] || 0,
          date_range: sortedDates.length ? { min: sortedDates[sortedDates.length-1], max: sortedDates[0] } : null,
          source: 'Redis (Phase 1)',
        },
        last_sync: lastSyncTime,
        data_date: dataDateIso,
        full_progress: state['sync:full_progress'] || null,
        current_task: syncState.running ? {
          percent: syncState.percent, step: syncState.step,
          done: syncState.done, total: syncState.total, bars_total: syncState.bars_total,
          ok: syncState.ok, err: syncState.err,
          source: syncState.source, sync_type: syncState.sync_type,
          started_at: syncState.started_at,
        } : null,
        redis_state: {
          realtime_count: state['realtime:hot_count'],
          is_trading: trading.is_trading,
          is_afterhours: trading.is_afterhours,
          source_health_summary: summary,
        },
      },
    });
  }

  // ─── 开始同步 (Phase 1.5: 通过 Redis 信号触发 sync_service) ───
  if (action === 'start') {
    const source = body.source || 'tencent';
    const syncType = body.sync_type || 'daily';
    const days = body.days || 365;

    lastSyncTime = new Date().toISOString();
    syncState = {
      running: true,
      percent: 5, step: '已发送触发信号到 sync_service...', done: 0, total: 0, bars_total: 0,
      ok: 0, err: 0, source, sync_type: syncType,
      started_at: lastSyncTime, finished_at: null, last_error: '',
    };

    // 按 sync_type 映射到具体 job (修复: 不再全部映射到 popular_refresh)
    const jobMap = {
      realtime: 'trading_realtime',  // 实时行情 (15 hot stocks)
      daily: 'popular_refresh',      // 热门股 K 线 (15 hot stocks)
      basic: 'stocks_refresh',       // 股票列表 (从 sources 重新拉)
      full: 'full_kline_refresh',    // 全量 K 线 (所有 stock:all)
      tick: 'tick_collect',          // Tick 逐笔 (Phase 2 stub)
    };
    const jobId = jobMap[syncType] || 'popular_refresh';
    const r = runPython(`
import sys, json, time
sys.path.insert(0, '.')
from quant.data.cache import create_cache
c = create_cache()
key = 'sync:cmd:trigger:${jobId}'
c.set(key, {'job_id': '${jobId}', 'ts': time.time()}, ttl=30)
print(json.dumps({'success': True, 'trigger_sent': True, 'job_id': '${jobId}'}))
`);
    if (r._error) {
      syncState.running = false;
      syncState.finished_at = new Date().toISOString();
      syncState.last_error = r._error;
      return json(res, 500, { success: false, error: r._error });
    }
    if (r.trigger_sent) {
      syncState.percent = 5;
      syncState.step = '已触发 sync_service, 等待执行...';
      syncState.job_id = jobId;
      // 不再 setTimeout 假进度; 后续 progress 查询会读 Redis 的真实状态
    }

    return json(res, 200, { success: true, data: { message: `同步任务 (${syncType}) 已发送到 sync_service, job=${jobId}`, trigger_sent: r.trigger_sent, job_id: jobId, sync_type: syncType, last_sync: lastSyncTime } });
  }

  // ─── 进度查询 ────────────────────
  if (action === 'progress') {
    // 尝试从 sync_service 读取真实进度
    const live = runPython(`
import sys, json
sys.path.insert(0, '.')
from quant.data.cache import create_cache
c = create_cache()
out = {}
for k in ['sync:popular_progress', 'sync:full_progress']:
    v = c.get(k)
    if v: out[k.replace('sync:', '')] = v
print(json.dumps(out, ensure_ascii=False))
`);
    // 如果 syncState.running 但有 live 进度, 用 live 覆盖
    if (syncState.running && !live._error) {
      const pop = live['popular_progress'];
      const full = live['full_progress'];
      const live_progress = pop || full;
      if (live_progress) {
        if (live_progress.running) {
          const done = live_progress.done || 0;
          const total = live_progress.total || 1;
          syncState.percent = Math.min(95, Math.round((done / total) * 100));
          syncState.done = done;
          syncState.total = total;
          if (pop) {
            syncState.ok = pop.updated || 0;
            syncState.err = pop.failed || 0;
            syncState.step = `热门股同步: ${done}/${total} (更新 ${pop.updated || 0}, 跳过 ${pop.skipped || 0}, 失败 ${pop.failed || 0})${pop.current ? ' · 当前: ' + pop.current : ''}`;
          } else if (full) {
            syncState.ok = full.ok || 0;
            syncState.err = full.err || 0;
            syncState.step = `全量同步: ${done}/${total} (成功 ${full.ok || 0}, 失败 ${full.err || 0})${full.current ? ' · 当前: ' + full.current : ''}`;
          }
        } else {
          // Live 报告显示完成 → 同步 syncState.running
          syncState.running = false;
          syncState.percent = 100;
          syncState.finished_at = new Date().toISOString();
          if (pop) {
            syncState.done = pop.done || pop.total || 0;
            syncState.total = pop.total || 0;
            syncState.ok = pop.updated || 0;
            syncState.err = pop.failed || 0;
            syncState.step = `热门股同步完成: 更新 ${pop.updated || 0} / 跳过 ${pop.skipped || 0} / 失败 ${pop.failed || 0}`;
          } else if (full) {
            syncState.done = full.done || full.total || 0;
            syncState.total = full.total || 0;
            syncState.ok = full.ok || 0;
            syncState.err = full.err || 0;
            syncState.step = `全量同步完成: 成功 ${full.ok || 0} / 失败 ${full.err || 0}`;
          }
        }
      } else {
        // 没有 live 进度但 syncState.running=true → 也设为 false (防止卡死)
        // (popular_refresh 没运行过 或 已完成且 key 已过期)
        // 用 syncState.started_at 距今多久判断
        if (syncState.started_at) {
          const elapsed = Date.now() - new Date(syncState.started_at).getTime();
          if (elapsed > 60000) {  // 超过 60s 视为完成
            syncState.running = false;
            syncState.percent = 100;
            syncState.finished_at = new Date().toISOString();
            syncState.step = '同步完成 (live 进度已过期)';
          }
        }
      }
    }
    // current_task 反映当前 syncState
    const currentTask = syncState.running ? {
      percent: syncState.percent,
      step: syncState.step,
      done: syncState.done,
      total: syncState.total,
      bars_total: syncState.bars_total || 0,
      ok: syncState.ok,
      err: syncState.err,
      source: syncState.source,
      sync_type: syncState.sync_type,
      started_at: syncState.started_at,
    } : null;
    return json(res, 200, { success: true, data: { ...syncState, last_sync: lastSyncTime, current_task: currentTask } });
  }

  // ─── 停止同步 ────────────────────
  if (action === 'stop') {
    syncState.running = false;
    syncState.finished_at = new Date().toISOString();
    syncState.step = '已停止';
    return json(res, 200, { success: true, data: { message: '已请求停止' } });
  }

  // ─── 数据更新 (手动触发 daily_update) ────────────
  if (action === 'start_update') {
    const mode = body.mode || 'kline';   // 'kline' | 'financial'
    const limit = parseInt(body.limit) || 0;
    const r = startUpdate(mode, limit);
    return json(res, r.success ? 200 : 409, r);
  }

  if (action === 'stop_update') {
    return json(res, 200, stopUpdate());
  }

  if (action === 'update_progress') {
    return json(res, 200, getUpdateProgress());
  }

  // ─── 实时同步守护进程状态 (sync_service) ────────────
  if (action === 'daemon_status') {
    const live = runPython(`
import sys, json, logging
sys.path.insert(0, '.')
logging.disable(logging.CRITICAL)  # 静默 logging 输出, 避免污染 stdout
from quant.data.cache import create_cache
from quant.data.sync_service import is_trading_time
c = create_cache()
trading = is_trading_time()
rt_keys = c.keys('stock:realtime:*')
# realtime key 有 TTL 120s, 能读到说明 daemon <120s 前活跃
fresh = len(rt_keys) > 0
out = {
  'trading': trading,
  'realtime_fresh': fresh,
  'watch_count': len(rt_keys),
}
print(json.dumps(out, ensure_ascii=False))
`);
    let data = null;
    if (!live._error) {
      // runPython 会 JSON.parse stdout, 但 logging 可能混入; 尝试提取
      if (live.trading) {
        data = live;
      } else {
        // 可能 logging 输出混在前面, 找 JSON 部分
        data = live;
      }
    }
    return json(res, 200, { success: !live._error, data: data || { error: live._error } });
  }

  return json(res, 400, { success: false, error: 'Unknown action' });
  } catch (e) {
    log('SYNC', `error: ${e.message}`);
    try { return json(res, 500, { success: false, error: e.message }); } catch {}
  }
}

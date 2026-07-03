/**
 * 数据更新任务管理器 — 非阻塞式启动 daily_update.py，解析进度写入缓存
 *
 * 设计:
 *   - spawn (非阻塞) 启动 python daily_update.py
 *   - 逐行读 stdout，正则解析 "K线增量 [123/5207] ok=..." 类进度
 *   - 状态写入 SQLite (通过 data_runner.py 的 write_status action) + 内存镜像
 *   - 前端轮询 /api/sync {action:"update_progress"} 获取实时进度
 */
import { spawn } from 'child_process';
import { log, json } from './http-utils.mjs';
import { ROOT_DIR, resolvePython } from './config.mjs';
import { PersistentRunner } from './persistent_runner.mjs';

const PYTHON = resolvePython();

/**
 * 生成北京时间 (UTC+8) 的 ISO 格式时间戳，形如 "2026-07-01T13:31:01+08:00"。
 * new Date().toISOString() 始终输出 UTC (带 Z)，直接 slice(11,19) 会显示 UTC 时间，
 * 对中国用户差 8 小时。这里用 Intl 格式化到 Asia/Shanghai 再拼成 ISO，保证
 * 前端 slice(11,19) 取到的是北京时间 HH:MM:SS。
 */
const _tsFmt = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
});
function nowIsoLocal() {
  const p = _tsFmt.formatToParts(new Date());
  const g = (t) => p.find(x => x.type === t)?.value || '00';
  return `${g('year')}-${g('month')}-${g('day')}T${g('hour')}:${g('minute')}:${g('second')}+08:00`;
}

// 内存中的更新任务状态 (单例，同一时间只允许一个更新任务)
let updateState = {
  running: false,
  percent: 0,
  step: 'idle',
  done: 0,
  total: 0,
  ok: 0,
  skip: 0,
  err: 0,
  new_bars: 0,
  started_at: null,
  finished_at: null,
  last_error: '',
  mode: '',          // 'kline' | 'financial'
  pid: null,
};
let updateProc = null;

function resetState(mode) {
  updateState = {
    running: true,
    percent: 0,
    step: '启动中...',
    done: 0, total: 0, ok: 0, skip: 0, err: 0, new_bars: 0,
    started_at: nowIsoLocal(),
    finished_at: null,
    last_error: '',
    mode,
    pid: null,
  };
}

/**
 * 启动数据更新任务 (非阻塞)
 * mode: 'kline' (默认) | 'financial'
 * limit: 限制股票数 (0=全部)
 */
export function startUpdate(mode = 'kline', limit = 0) {
  if (updateState.running) {
    return { success: false, error: '已有更新任务在运行中', state: updateState };
  }
  resetState(mode);

  const args = [`${ROOT_DIR}/scripts/daily_update.py`];
  if (mode === 'financial') args.push('--financial');
  if (limit > 0) args.push('--limit', String(limit));

  log('INFO', `[DataUpdate] starting: python ${args.join(' ')}`);
  updateProc = spawn(PYTHON, args, {
    cwd: ROOT_DIR,
    env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1' },
    windowsHide: true,
  });
  updateState.pid = updateProc.pid;

  let buffer = '';
  updateProc.stdout.setEncoding('utf-8');
  updateProc.stdout.on('data', (chunk) => {
    buffer += chunk;
    let idx;
    while ((idx = buffer.indexOf('\n')) !== -1) {
      const line = buffer.slice(0, idx).trim();
      buffer = buffer.slice(idx + 1);
      parseProgress(line);
    }
  });

  updateProc.stderr.setEncoding('utf-8');
  updateProc.stderr.on('data', () => {}); // 丢弃 stderr (python logging)

  updateProc.on('exit', (code) => {
    log('INFO', `[DataUpdate] exited code=${code}`);
    updateState.running = false;
    updateState.finished_at = nowIsoLocal();
    if (code === 0) {
      updateState.percent = 100;
      updateState.step = `更新完成: ok=${updateState.ok} 新增${updateState.new_bars}根K线`;
    } else {
      updateState.step = `更新异常退出 (code=${code})`;
      updateState.last_error = `exit code ${code}`;
    }
    updateProc = null;
  });

  updateProc.on('error', (e) => {
    log('ERROR', `[DataUpdate] spawn error: ${e.message}`);
    updateState.running = false;
    updateState.last_error = e.message;
    updateProc = null;
  });

  return { success: true, message: `${mode} 更新已启动`, state: updateState };
}

/** 解析 daily_update.py 的进度日志行 */
function parseProgress(line) {
  if (!line) return;
  // 匹配: "K线增量 [123/5207] ok=100 skip=20 err=3 新增150根 (5.2/s)"
  const m = line.match(/\[(\d+)\/(\d+)\]\s+ok=(\d+)\s+skip=(\d+)\s+err=(\d+)\s+新增(\d+)根/);
  if (m) {
    updateState.done = parseInt(m[1]);
    updateState.total = parseInt(m[2]);
    updateState.ok = parseInt(m[3]);
    updateState.skip = parseInt(m[4]);
    updateState.err = parseInt(m[5]);
    updateState.new_bars = parseInt(m[6]);
    updateState.percent = updateState.total > 0
      ? Math.min(99, Math.round((updateState.done / updateState.total) * 100))
      : 0;
    updateState.step = `K线增量: ${updateState.done}/${updateState.total} (成功${updateState.ok} 跳过${updateState.skip} 失败${updateState.err})`;
    return;
  }
  // 匹配财务: "财务 [123/5207] ok=100 err=3 (5.20/s)"
  const fm = line.match(/财务\s+\[(\d+)\/(\d+)\]\s+ok=(\d+)\s+err=(\d+)/);
  if (fm) {
    updateState.done = parseInt(fm[1]);
    updateState.total = parseInt(fm[2]);
    updateState.ok = parseInt(fm[3]);
    updateState.err = parseInt(fm[4]);
    updateState.percent = updateState.total > 0
      ? Math.min(99, Math.round((updateState.done / updateState.total) * 100))
      : 0;
    updateState.step = `财务刷新: ${updateState.done}/${updateState.total} (成功${updateState.ok} 失败${updateState.err})`;
    return;
  }
  // 匹配股票池
  if (line.includes('股票池同步')) {
    updateState.step = `同步股票池: ${line.split(':')[1]?.trim() || ''}`;
    updateState.percent = 2;
    return;
  }
  // 完成
  if (line.includes('K线增量完成')) {
    updateState.step = line;
    updateState.percent = 99;
  }
}

/** 停止更新任务 */
export function stopUpdate() {
  if (updateProc && updateState.running) {
    try {
      updateProc.kill();
      log('INFO', '[DataUpdate] killed by user');
    } catch (e) {
      log('WARN', `[DataUpdate] kill failed: ${e.message}`);
    }
    updateState.running = false;
    updateState.step = '已手动停止';
    updateState.finished_at = nowIsoLocal();
    updateProc = null;
    return { success: true, message: '已停止更新任务' };
  }
  return { success: false, error: '没有正在运行的更新任务' };
}

/** 获取更新进度 */
export function getUpdateProgress() {
  return { success: true, data: { ...updateState } };
}

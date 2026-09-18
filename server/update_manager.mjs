/**
 * 数据更新任务管理器 — 非阻塞式启动 daily_update.py，解析进度写入缓存
 *
 * 设计:
 *   - spawn (非阻塞) 启动 python daily_update.py
 *   - 逐行读 stdout，正则解析 "K线增量 [123/5207] ok=..." 类进度
 *   - 状态写入 SQLite (通过 data_runner.py 的 write_status action) + 内存镜像
 *   - 前端轮询 /api/sync {action:"update_progress"} 获取实时进度
 */
import { spawn, spawnSync } from 'child_process';
import fs from 'fs';
import path from 'path';
import { log } from './http-utils.mjs';
import { ROOT_DIR, resolvePython } from './config.mjs';
import { PersistentRunner } from './persistent_runner.mjs';

const PYTHON = resolvePython();
const UPDATE_STATUS_KEY = 'data:update:status';
const FINANCIAL_CHECKPOINT_PATH = path.join(ROOT_DIR, 'data', 'financial_update_progress.json');
const FINANCIAL_STDOUT_PATH = path.join(ROOT_DIR, 'logs', 'financial-update-out.log');
const FINANCIAL_STDERR_PATH = path.join(ROOT_DIR, 'logs', 'financial-update-err.log');
const stateRunner = new PersistentRunner('sync_runner.py');

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

function pidAlive(pid) {
  if (!pid) return false;
  try {
    process.kill(Number(pid), 0);
    return true;
  } catch {
    return false;
  }
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

export function normalizeProcessExitCode(code) {
  if (code === null || code === undefined) return null;
  const numeric = Number(code);
  if (!Number.isInteger(numeric)) return null;
  return numeric > 0x7fffffff ? numeric - 0x100000000 : numeric;
}

export function classifyUpdateExit({ code, signal = null, stoppedByUser = false }) {
  const normalizedCode = normalizeProcessExitCode(code);
  if (stoppedByUser) {
    return { kind: 'manual_stop', normalizedCode, rawCode: code, signal };
  }
  if (normalizedCode === 0 && !signal) {
    return { kind: 'success', normalizedCode, rawCode: code, signal };
  }
  if (signal || normalizedCode === -1 || normalizedCode === null) {
    return { kind: 'external_termination', normalizedCode, rawCode: code, signal };
  }
  return { kind: 'failed', normalizedCode, rawCode: code, signal };
}

export function releaseProcessAfterPersist(persistence, release) {
  return Promise.resolve(persistence).finally(release);
}

export function readFinancialCheckpoint() {
  try {
    const value = JSON.parse(fs.readFileSync(FINANCIAL_CHECKPOINT_PATH, 'utf8'));
    return value && typeof value === 'object' ? value : {};
  } catch {
    return {};
  }
}

export function writeFinancialCheckpointStatus(status) {
  const current = readFinancialCheckpoint();
  if (!Object.keys(current).length) return false;
  const next = {
    ...current,
    status: String(status || 'interrupted'),
    updated_at: nowIsoLocal(),
  };
  const tempPath = `${FINANCIAL_CHECKPOINT_PATH}.tmp.${process.pid}`;
  fs.writeFileSync(tempPath, JSON.stringify(next), 'utf8');
  fs.renameSync(tempPath, FINANCIAL_CHECKPOINT_PATH);
  return true;
}

export function mergeFinancialCheckpoint(state, checkpoint, processIsAlive) {
  const current = { ...(state || {}) };
  const value = checkpoint && typeof checkpoint === 'object' ? checkpoint : {};
  if (!Object.keys(value).length) return current;
  const status = String(value.status || '');
  const total = Number(value.total || current.total || 0);
  const done = Number(value.done || 0);
  const next = {
    ...current,
    mode: 'financial',
    done,
    total,
    ok: Number(value.ok || 0),
    err: Number(value.err || 0),
    percent: total > 0 ? Math.min(status === 'running' ? 99 : 100, Math.round(done / total * 100)) : 0,
    checkpoint_status: status,
    checkpoint_updated_at: value.updated_at || null,
  };
  if (status === 'completed' || status === 'completed_with_errors') {
    next.running = false;
    next.percent = 100;
    next.finished_at = value.finished_at || value.updated_at || current.finished_at || nowIsoLocal();
    next.step = status === 'completed'
      ? `财务更新完成: ok=${next.ok} err=${next.err}`
      : `财务更新完成但存在失败: ok=${next.ok} err=${next.err}`;
    next.last_error = status === 'completed' ? '' : `financial update errors: ${next.err}`;
    next.termination_reason = status;
    return next;
  }
  if (status === 'running' && processIsAlive) {
    next.running = true;
    next.step = `财务刷新: ${done}/${total} (成功${next.ok} 失败${next.err})`;
    next.last_error = '';
    next.finished_at = null;
    next.termination_reason = '';
    return next;
  }
  next.running = false;
  next.finished_at = current.finished_at || nowIsoLocal();
  next.step = status === 'interrupted'
    ? '财务更新已中断，可从断点继续'
    : '任务因服务重启或进程退出而中断';
  next.last_error = 'orphaned update process';
  next.termination_reason = 'external_termination';
  return next;
}

function cacheCommand(script, timeout = 8000) {
  const result = spawnSync(PYTHON, ['-c', script], {
    cwd: ROOT_DIR,
    env: { ...process.env, QUANT_SKIP_NODE_PROXY: '1', PYTHONIOENCODING: 'utf-8' },
    encoding: 'utf-8',
    windowsHide: true,
    timeout,
  });
  if (result.status !== 0) return null;
  try {
    return JSON.parse(String(result.stdout || '{}').trim().split(/\r?\n/).pop() || '{}');
  } catch {
    return null;
  }
}

function loadPersistedState() {
  return cacheCommand(`
import json, sys
sys.path.insert(0, '.')
from quant.data.cache import create_cache
print(json.dumps(create_cache().get('${UPDATE_STATUS_KEY}') or {}, ensure_ascii=False))
`) || {};
}

function writePersistedState(state, eventType = '') {
  const snapshot = JSON.parse(JSON.stringify(state || {}));
  return stateRunner.call({
    action: 'write_update_status',
    state: snapshot,
    event_type: eventType,
  }, 30_000).catch((error) => {
    log('ERROR', `[DataUpdate] persist failed: ${error.message}`);
    return { success: false, error: error.message };
  });
}

function idleState() {
  return {
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
    stderr_tail: '',
    exit_code: null,
    raw_exit_code: null,
    exit_signal: null,
    termination_reason: '',
    mode: '',
    pid: null,
    codes: [],
    limit: 0,
    workers: 0,
  };
}

// 内存镜像；SQLite 状态用于后端重启后的恢复和异常任务识别。
let updateState = { ...idleState(), ...loadPersistedState() };
if (updateState.running && updateState.mode === 'financial') {
  updateState = mergeFinancialCheckpoint(
    updateState,
    readFinancialCheckpoint(),
    pidAlive(updateState.pid),
  );
  if (!updateState.running) writePersistedState(updateState, 'data_update_interrupted');
} else if (updateState.running && !pidAlive(updateState.pid)) {
  updateState.running = false;
  updateState.step = '任务因服务重启或进程退出而中断';
  updateState.finished_at = nowIsoLocal();
  updateState.last_error = 'orphaned update process';
  writePersistedState(updateState, 'data_update_interrupted');
}
let updateProc = null;
let lastPersistAt = 0;

function persistProgress(force = false) {
  const now = Date.now();
  if (!force && now - lastPersistAt < 1000) return;
  lastPersistAt = now;
  writePersistedState(updateState);
}

function resetState(mode, { codes = [], limit = 0, workers = 0 } = {}) {
  updateState = {
    running: true,
    percent: 0,
    step: '启动中...',
    done: 0, total: 0, ok: 0, skip: 0, err: 0, new_bars: 0,
    started_at: nowIsoLocal(),
    finished_at: null,
    last_error: '',
    stderr_tail: '',
    exit_code: null,
    raw_exit_code: null,
    exit_signal: null,
    termination_reason: '',
    mode,
    pid: null,
    codes,
    limit,
    workers,
  };
}

/**
 * 启动数据更新任务 (非阻塞)
 * mode: 'kline' (默认) | 'financial'
 * limit: 限制股票数 (0=全部)
 */
export function startUpdate(mode = 'kline', limit = 0, workers = 0, codes = []) {
  if (
    (updateProc && updateProc.exitCode === null)
    || (updateState.running && pidAlive(updateState.pid))
  ) {
    return { success: false, error: '已有更新任务在运行中', state: updateState };
  }
  const selectedCodes = normalizeCodes(codes);
  const workerCount = Number(workers || process.env.XUANJI_UPDATE_WORKERS || 8);
  const safeLimit = Math.max(0, Number(limit || 0));
  resetState(mode, { codes: selectedCodes, limit: safeLimit, workers: workerCount });

  const args = [`${ROOT_DIR}/scripts/daily_update.py`];
  if (mode === 'financial') args.push('--financial', '--financial-only');
  if (selectedCodes.length) args.push('--codes', selectedCodes.join(','));
  if (safeLimit > 0) args.push('--limit', String(safeLimit));
  if (workerCount > 0) args.push('--workers', String(workerCount));

  log('INFO', `[DataUpdate] starting: python ${args.join(' ')}`);
  let stdoutFd = null;
  let stderrFd = null;
  const durableFinancial = mode === 'financial';
  if (durableFinancial) {
    fs.mkdirSync(path.dirname(FINANCIAL_STDOUT_PATH), { recursive: true });
    stdoutFd = fs.openSync(FINANCIAL_STDOUT_PATH, 'w');
    stderrFd = fs.openSync(FINANCIAL_STDERR_PATH, 'w');
  }
  const proc = spawn(PYTHON, args, {
    cwd: ROOT_DIR,
    env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1' },
    windowsHide: true,
    detached: durableFinancial,
    stdio: durableFinancial ? ['ignore', stdoutFd, stderrFd] : ['ignore', 'pipe', 'pipe'],
  });
  if (stdoutFd !== null) fs.closeSync(stdoutFd);
  if (stderrFd !== null) fs.closeSync(stderrFd);
  if (durableFinancial) proc.unref();
  proc.stoppedByUser = false;
  updateProc = proc;
  updateState.pid = proc.pid;
  writePersistedState(updateState, 'data_update_start');

  let buffer = '';
  proc.stdout?.setEncoding('utf-8');
  proc.stdout?.on('data', (chunk) => {
    buffer += chunk;
    let idx;
    while ((idx = buffer.indexOf('\n')) !== -1) {
      const line = buffer.slice(0, idx).trim();
      buffer = buffer.slice(idx + 1);
      parseProgress(line);
      persistProgress();
    }
  });

  proc.stderr?.setEncoding('utf-8');
  proc.stderr?.on('data', (chunk) => {
    updateState.stderr_tail = `${updateState.stderr_tail || ''}${String(chunk)}`.slice(-4000);
    persistProgress();
  });

  proc.on('exit', (code, signal) => {
    const exit = classifyUpdateExit({
      code,
      signal,
      stoppedByUser: proc.stoppedByUser,
    });
    log(
      'INFO',
      `[DataUpdate] exited raw=${code} normalized=${exit.normalizedCode} signal=${signal || 'none'}`,
    );
    updateState.raw_exit_code = code;
    updateState.exit_code = exit.normalizedCode;
    updateState.exit_signal = signal || null;
    updateState.termination_reason = exit.kind;
    if (updateState.mode === 'financial') {
      updateState = mergeFinancialCheckpoint(
        updateState,
        readFinancialCheckpoint(),
        false,
      );
      updateState.raw_exit_code = code;
      updateState.exit_code = exit.normalizedCode;
      updateState.exit_signal = signal || null;
      releaseProcessAfterPersist(
        writePersistedState(
          updateState,
          updateState.checkpoint_status === 'completed'
            ? 'data_update_complete'
            : (updateState.checkpoint_status === 'completed_with_errors'
              ? 'data_update_complete_with_errors'
              : 'data_update_interrupted'),
        ),
        () => { if (updateProc === proc) updateProc = null; },
      );
      return;
    }
    if (exit.kind === 'manual_stop') {
      releaseProcessAfterPersist(
        writePersistedState(updateState, 'data_update_exit'),
        () => {
          if (updateProc === proc) updateProc = null;
        },
      );
      return;
    }
    updateState.running = false;
    updateState.finished_at = nowIsoLocal();
    if (exit.kind === 'success') {
      updateState.percent = 100;
      updateState.step = updateState.mode === 'financial'
        ? `财务更新完成: ok=${updateState.ok} err=${updateState.err}`
        : `K线更新完成: ok=${updateState.ok} 新增${updateState.new_bars}根`;
    } else if (exit.kind === 'external_termination') {
      updateState.step = updateState.mode === 'financial'
        ? '财务更新进程被外部终止，可重新执行以从断点继续'
        : '更新进程被外部终止';
      updateState.last_error = [
        'process terminated externally',
        `raw=${code}`,
        `normalized=${exit.normalizedCode}`,
        signal ? `signal=${signal}` : '',
      ].filter(Boolean).join(', ');
    } else {
      updateState.step = `更新异常退出 (code=${exit.normalizedCode})`;
      updateState.last_error = `exit code ${exit.normalizedCode}`;
    }
    releaseProcessAfterPersist(
      writePersistedState(
        updateState,
        exit.kind === 'success'
          ? 'data_update_complete'
          : (exit.kind === 'external_termination'
            ? 'data_update_interrupted'
            : 'data_update_failed'),
      ),
      () => {
        if (updateProc === proc) updateProc = null;
      },
    );
  });

  proc.on('error', (e) => {
    log('ERROR', `[DataUpdate] spawn error: ${e.message}`);
    updateState.running = false;
    updateState.finished_at = nowIsoLocal();
    updateState.last_error = e.message;
    updateState.termination_reason = 'spawn_error';
    updateState.stderr_tail = `${updateState.stderr_tail || ''}\n${e.message}`.trim().slice(-4000);
    releaseProcessAfterPersist(
      writePersistedState(updateState, 'data_update_failed'),
      () => {
        if (updateProc === proc) updateProc = null;
      },
    );
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
  const activePid = updateProc?.pid || updateState.pid;
  if (updateState.running && pidAlive(activePid)) {
    try {
      if (updateProc) {
        updateProc.stoppedByUser = true;
        updateProc.kill();
      } else {
        process.kill(Number(activePid));
      }
      log('INFO', '[DataUpdate] killed by user');
    } catch (e) {
      log('WARN', `[DataUpdate] kill failed: ${e.message}`);
    }
    updateState.running = false;
    updateState.step = '已手动停止';
    updateState.finished_at = nowIsoLocal();
    updateState.exit_code = null;
    updateState.raw_exit_code = null;
    updateState.exit_signal = null;
    updateState.termination_reason = 'manual_stop';
    if (updateState.mode === 'financial') writeFinancialCheckpointStatus('interrupted');
    writePersistedState(updateState, 'data_update_stop');
    return { success: true, message: '已停止更新任务' };
  }
  return { success: false, error: '没有正在运行的更新任务' };
}

/** 获取更新进度 */
export function getUpdateProgress() {
  if (!updateProc) {
    const persisted = loadPersistedState();
    if (persisted && Object.keys(persisted).length) {
      updateState = { ...idleState(), ...persisted };
      if (updateState.running && !pidAlive(updateState.pid)) {
        updateState.running = false;
        updateState.step = '任务进程已不存在';
        updateState.finished_at = updateState.finished_at || nowIsoLocal();
        updateState.last_error = updateState.last_error || 'update process is not alive';
        writePersistedState(updateState, 'data_update_interrupted');
      }
    }
  }
  if (updateState.mode === 'financial') {
    const merged = mergeFinancialCheckpoint(
      updateState,
      readFinancialCheckpoint(),
      pidAlive(updateState.pid),
    );
    const changed = JSON.stringify(merged) !== JSON.stringify(updateState);
    updateState = merged;
    if (changed) persistProgress(true);
  }
  return { success: true, data: { ...updateState } };
}

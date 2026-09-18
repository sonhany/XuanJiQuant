import { spawn } from 'child_process';
import { isMainThread, parentPort } from 'worker_threads';
import { resolvePython } from './config.mjs';

let proc = null;
let failedUntil = 0;

function markWriterUnavailable(child, retryDelayMs) {
  if (proc !== child) return;
  proc = null;
  failedUntil = Date.now() + retryDelayMs;
}

function ensureProc() {
  if (proc && !proc.killed && proc.stdin?.writable) return proc;
  if (Date.now() < failedUntil) return null;
  try {
    const child = spawn(resolvePython(), ['scripts/log_writer.py'], {
      cwd: process.cwd(),
      windowsHide: true,
      stdio: ['pipe', 'ignore', 'ignore'],
    });
    proc = child;
    child.on('exit', () => markWriterUnavailable(child, 2000));
    child.on('error', () => markWriterUnavailable(child, 5000));
    child.stdin.on('error', () => markWriterUnavailable(child, 2000));
    return child;
  } catch {
    proc = null;
    failedUntil = Date.now() + 5000;
    return null;
  }
}

export function writeDbLog(level, message, meta = {}) {
  const event = {
    level,
    message,
    meta,
    source: 'server',
    created_at: new Date().toISOString(),
  };
  if (!isMainThread) {
    parentPort?.postMessage({ type: 'db_log', event });
    return true;
  }
  const child = ensureProc();
  if (!child?.stdin?.writable) return false;
  try {
    child.stdin.write(`${JSON.stringify(event)}\n`);
    return true;
  } catch {
    return false;
  }
}

export function closeDbLogWriter() {
  if (!proc) return;
  try { proc.stdin?.end(); } catch {}
  try { proc.kill(); } catch {}
  proc = null;
}

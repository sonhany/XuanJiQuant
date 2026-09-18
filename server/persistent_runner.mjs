import { spawn, execFileSync } from 'child_process';
import path from 'path';
import fs from 'fs';
import { log } from './http-utils.mjs';
import { ROOT_DIR, resolvePython } from './config.mjs';

const PYTHON = resolvePython();
const RUNNER_SINGLETONS = new Map();
const RUNNER_IDLE_MS = Math.max(0, Number(process.env.XUANJI_RUNNER_IDLE_MS || 30 * 60 * 1000));
const CLEANED_SCRIPTS = new Set();

function runnerEnv() {
  return {
    ...process.env,
    QUANT_SKIP_NODE_PROXY: '1',
    PYTHONIOENCODING: 'utf-8',
    PYTHONUNBUFFERED: '1',
    OMP_NUM_THREADS: process.env.OMP_NUM_THREADS || '1',
    OPENBLAS_NUM_THREADS: process.env.OPENBLAS_NUM_THREADS || '1',
    MKL_NUM_THREADS: process.env.MKL_NUM_THREADS || '1',
    NUMEXPR_NUM_THREADS: process.env.NUMEXPR_NUM_THREADS || '1',
  };
}

function _quotePowerShell(s) {
  return `'${String(s).replace(/'/g, "''")}'`;
}

function cleanupStaleScriptProcesses(scriptPath) {
  if (process.env.XUANJI_RUNNER_CLEANUP !== '1') return;
  const normalized = path.normalize(scriptPath).toLowerCase();
  if (CLEANED_SCRIPTS.has(normalized)) return;
  CLEANED_SCRIPTS.add(normalized);
  try {
    if (process.platform === 'win32') {
      const script = `
$target = ${_quotePowerShell(normalized)}
Get-CimInstance Win32_Process |
  Where-Object {
    $_.ProcessId -ne ${process.pid} -and
    $_.ProcessId -ne $PID -and
    $_.CommandLine -and
    ($_.CommandLine.ToLower().Replace('/', '\\') -like ('*' + $target.Replace('/', '\\') + '*'))
  } |
  ForEach-Object {
    try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop; Write-Output $_.ProcessId } catch {}
  }
`;
      const out = execFileSync('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script], {
        encoding: 'utf8',
        windowsHide: true,
        timeout: 5000,
      }).trim();
      if (out) log('WARN', `[${scriptPath}] cleaned stale runner pids=${out.replace(/\s+/g, ',')}`);
      return;
    }
    const out = execFileSync('sh', ['-c', `ps -eo pid=,args= | grep ${JSON.stringify(scriptPath)} | grep -v grep | awk '{print $1}'`], {
      encoding: 'utf8',
      timeout: 5000,
    }).trim();
    for (const pid of out.split(/\s+/).filter(Boolean)) {
      if (Number(pid) !== process.pid) {
        try { process.kill(Number(pid), 'SIGTERM'); } catch {}
      }
    }
  } catch (e) {
    log('WARN', `[${scriptPath}] stale runner cleanup skipped: ${e.message}`);
  }
}

export class PersistentRunner {
  constructor(scriptName, instanceKey = 'default') {
    const scriptPath = path.join(ROOT_DIR, 'scripts', scriptName);
    const singletonKey = `${scriptPath}::${instanceKey}`;
    const existing = RUNNER_SINGLETONS.get(singletonKey);
    if (existing) return existing;
    this.scriptPath = scriptPath;
    this.instanceKey = instanceKey;
    this.proc = null;
    this.buffer = '';
    this.queue = [];
    this.busy = false;
    this.closing = false;
    this.current = null;
    this.idleTimer = null;
    this.seq = 0;
    this.stderrTail = '';
    this.terminating = null;
    this.terminatingProc = null;
    RUNNER_SINGLETONS.set(singletonKey, this);
  }

  ensure() {
    this._clearIdleTimer();
    if (this.proc && this.proc.exitCode === null) return;
    if (!fs.existsSync(this.scriptPath)) throw new Error(`${this.scriptPath} not found`);
    cleanupStaleScriptProcesses(this.scriptPath);
    this.buffer = '';
    this.stderrTail = '';
    const proc = spawn(PYTHON, [this.scriptPath], {
      cwd: ROOT_DIR,
      env: runnerEnv(),
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true,
    });
    this.proc = proc;
    proc.stdout.setEncoding('utf-8');
    proc.stderr.setEncoding('utf-8');
    proc.stdout.on('data', (chunk) => {
      this.buffer += chunk;
      this._drain();
    });
    proc.stderr.on('data', (chunk) => {
      this.stderrTail = (this.stderrTail + chunk).slice(-4000);
    });
    proc.on('exit', (code) => {
      if (this.proc !== proc) return;
      const stderr = this.stderrTail.trim();
      const pending = this.current;
      const exitLevel = code === 0 && !pending ? 'INFO' : 'WARN';
      log(exitLevel, `[${this.scriptPath}#${this.instanceKey}] exited code=${code}${stderr ? ` stderr=${stderr.slice(-800)}` : ''}`);
      this.proc = null;
      this.buffer = '';
      this.stderrTail = '';
      this._clearIdleTimer();
      if (pending) {
        clearTimeout(pending.timer);
        this.current = null;
        this.busy = false;
        pending.reject(new Error(`runner exited code=${code}`));
      }
      this._next();
    });
  }

  _terminateProcess(proc) {
    if (!proc || proc.exitCode !== null) {
      if (this.proc === proc) this.proc = null;
      return Promise.resolve();
    }
    if (this.terminating && this.terminatingProc === proc) return this.terminating;

    this.terminatingProc = proc;
    this.terminating = new Promise((resolve) => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        if (this.proc === proc) this.proc = null;
        resolve();
      };
      proc.once('exit', finish);
      try {
        if (process.platform === 'win32' && proc.pid) {
          execFileSync('taskkill.exe', ['/PID', String(proc.pid), '/T', '/F'], {
            encoding: 'utf8',
            windowsHide: true,
            timeout: 5000,
          });
        } else {
          proc.kill('SIGKILL');
        }
      } catch {
        try { proc.kill(); } catch {}
      }
      setTimeout(finish, 5500);
    }).finally(() => {
      if (this.terminatingProc === proc) {
        this.terminating = null;
        this.terminatingProc = null;
      }
    });
    return this.terminating;
  }

  _clearIdleTimer() {
    if (this.idleTimer) {
      clearTimeout(this.idleTimer);
      this.idleTimer = null;
    }
  }

  _scheduleIdleClose() {
    if (!RUNNER_IDLE_MS || this.busy || this.queue.length || !this.proc || this.proc.exitCode !== null) return;
    this._clearIdleTimer();
    this.idleTimer = setTimeout(() => {
      if (this.busy || this.queue.length || !this.proc || this.proc.exitCode !== null) return;
      log('INFO', `[${this.scriptPath}] idle ${RUNNER_IDLE_MS}ms, closing runner`);
      try { this.proc.stdin.end(); } catch {}
      setTimeout(() => {
        if (this.proc && this.proc.exitCode === null) {
          try { this.proc.kill(); } catch {}
        }
      }, 2000);
    }, RUNNER_IDLE_MS);
  }

  _drain() {
    while (true) {
      const idx = this.buffer.indexOf('\n');
      if (idx === -1) break;
      const line = this.buffer.slice(0, idx);
      this.buffer = this.buffer.slice(idx + 1);
      if (!line.trim()) continue;
      const pending = this.current;
      if (!pending) continue;
      let parsed;
      try {
        parsed = JSON.parse(line);
      } catch (e) {
        clearTimeout(pending.timer);
        this.current = null;
        this.busy = false;
        pending.reject(new Error(`parse error: ${e.message}, raw: ${line.slice(0, 200)}`));
        this._next();
        continue;
      }
      if (!parsed || parsed.__id !== pending.id) {
        log('WARN', `[${this.scriptPath}] orphan response id mismatch: got=${parsed?.__id || 'missing'} expected=${pending.id}`);
        continue;
      }
      clearTimeout(pending.timer);
      this.current = null;
      this.busy = false;
      delete parsed.__id;
      pending.resolve(parsed);
      this._next();
    }
  }

  _next() {
    if (this.busy) return;
    if (this.terminating) {
      this.terminating.finally(() => this._next());
      return;
    }
    if (this.queue.length === 0) {
      this._scheduleIdleClose();
      return;
    }
    this.busy = true;
    const pending = this.queue.shift();
    this.current = pending;
    this.ensure();
    this.proc.stdin.write(JSON.stringify({ ...pending.body, __id: pending.id }) + '\n');
  }

  async call(body, timeout = 120000) {
    return new Promise((resolve, reject) => {
      const id = `req_${Date.now()}_${++this.seq}`;
      const timer = setTimeout(() => {
        const idx = this.queue.indexOf(entry);
        if (idx !== -1) this.queue.splice(idx, 1);
        let termination = null;
        if (this.current === entry) {
          const proc = this.proc;
          this.current = null;
          this.busy = false;
          this.buffer = '';
          termination = this._terminateProcess(proc);
        }
        const stderr = this.stderrTail.trim();
        reject(new Error(`timeout ${timeout}ms${stderr ? `; stderr=${stderr.slice(-500)}` : ''}`));
        if (termination) termination.finally(() => this._next());
        else this._next();
      }, timeout);
      const entry = { id, body, resolve, reject, timer };
      this.queue.push(entry);
      if (!this.busy) this._next();
    });
  }

  prewarm(delayMs = 250) {
    const timer = setTimeout(() => {
      if (this.closing) return;
      try {
        this.ensure();
        this._scheduleIdleClose();
      } catch (error) {
        log('WARN', `[${this.scriptPath}] prewarm failed: ${error.message}`);
      }
    }, Math.max(0, Number(delayMs) || 0));
    timer.unref?.();
  }

  close() {
    this.closing = true;
    this._clearIdleTimer();
    if (this.proc && this.proc.exitCode === null) {
      const proc = this.proc;
      try { proc.stdin.end(); } catch {}
      setTimeout(() => {
        if (this.proc === proc && proc.exitCode === null) this._terminateProcess(proc);
      }, 2000);
    }
  }

  restart() {
    this._clearIdleTimer();
    const proc = this.proc;
    if (proc && proc.exitCode === null) this._terminateProcess(proc);
    this.buffer = '';
  }
}

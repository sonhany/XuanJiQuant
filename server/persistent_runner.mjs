import { spawn } from 'child_process';
import path from 'path';
import fs from 'fs';
import { log } from './http-utils.mjs';
import { ROOT_DIR, resolvePython } from './config.mjs';

const PYTHON = resolvePython();

export class PersistentRunner {
  constructor(scriptName) {
    this.scriptPath = path.join(ROOT_DIR, 'scripts', scriptName);
    this.proc = null;
    this.buffer = '';
    this.queue = [];
    this.busy = false;
    this.closing = false;
    this.current = null;
    this.seq = 0;
  }

  ensure() {
    if (this.proc && this.proc.exitCode === null) return;
    if (!fs.existsSync(this.scriptPath)) throw new Error(`${this.scriptPath} not found`);
    this.buffer = '';
    this.proc = spawn(PYTHON, [this.scriptPath], {
      cwd: ROOT_DIR,
      env: { ...process.env, QUANT_SKIP_NODE_PROXY: '1', PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1' },
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true,
    });
    this.proc.stdout.setEncoding('utf-8');
    this.proc.stderr.setEncoding('utf-8');
    this.proc.stdout.on('data', (chunk) => {
      this.buffer += chunk;
      this._drain();
    });
    this.proc.stderr.on('data', () => {}); // discard
    this.proc.on('exit', (code) => {
      log('WARN', `[${this.scriptPath}] exited code=${code}`);
      this.proc = null;
    });
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
        clearTimeout(pending.timer);
        this.current = null;
        this.busy = false;
        pending.reject(new Error(`response id mismatch: got=${parsed?.__id || 'missing'} expected=${pending.id}`));
        this._next();
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
    if (this.busy || this.queue.length === 0) return;
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
        if (this.current === entry) {
          this.current = null;
          this.busy = false;
          try { this.proc?.kill(); } catch {}
          this.proc = null;
          this.buffer = '';
        }
        reject(new Error(`timeout ${timeout}ms`));
        this._next();
      }, timeout);
      const entry = { id, body, resolve, reject, timer };
      this.queue.push(entry);
      if (!this.busy) this._next();
    });
  }

  close() {
    this.closing = true;
    if (this.proc && this.proc.exitCode === null) {
      this.proc.stdin.end();
      setTimeout(() => { if (this.proc) this.proc.kill(); }, 2000);
    }
  }
}

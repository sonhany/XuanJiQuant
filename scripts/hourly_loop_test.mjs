// 全功能循环测试 - 每小时调用一次
// 用法: node scripts/hourly_loop_test.mjs
// 退出码: 0=全过, 1=有失败, 2=API server 全死
// 日志: logs/loop_test/<YYYY-MM-DD-HH>.log + logs/loop_test/summary.jsonl

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const LOG_DIR = path.join(ROOT, 'logs', 'loop_test');
fs.mkdirSync(LOG_DIR, { recursive: true });

const API = 'http://localhost:3334';
const NOW = new Date();
const TS = NOW.toISOString().slice(0, 13).replace('T', '-');  // 2026-06-07-09 (UTC)
const LOG_FILE = path.join(LOG_DIR, `${TS}.log`);
const SUMMARY_FILE = path.join(LOG_DIR, 'summary.jsonl');

const END = NOW.toISOString().slice(0, 10);
const LONG_START = new Date(NOW.getTime() - 180 * 86400_000).toISOString().slice(0, 10);

const tests = [
  ['data.stats',          '/api/data',      {action:'stats'}],
  ['data.stocks',         '/api/data',      {action:'stocks', limit:5}],
  ['data.klines.000001',  '/api/data',      {action:'klines', code:'000001.SZ', start:LONG_START, end:END}],
  ['data.klines.600519',  '/api/data',      {action:'klines', code:'600519.SH', start:LONG_START, end:END}],
  ['sync.status',         '/api/sync',      {action:'status'}],
  ['sync.progress',       '/api/sync',      {action:'progress'}],
  ['market.indices',      '/api/market',    {action:'indices'}],
  ['market.realtime',     '/api/market',    {action:'realtime_prices', codes:['000001.SZ','600519.SH','600000.SH']}],
  ['factor.meta',         '/api/factor',    {action:'meta'}],
  ['factor.factors',      '/api/factor',    {action:'factors', code:'000001.SZ', start:LONG_START, end:END}],
  ['factor.evaluate',     '/api/factor',    {action:'evaluate', codes:['000001.SZ','600519.SH','600000.SH'], factor_name:'momentum_20', start:LONG_START, end:END}, 120],
  ['strategy.meta',       '/api/strategy',  {action:'meta'}],
  ['strategy.backtest',   '/api/strategy',  {action:'backtest', name:'ma_cross', codes:['000001.SZ','600519.SH','600000.SH'], start:LONG_START, end:END, initial_cash:1000000}, 180],
  ['exec.status',         '/api/execution', {action:'status'}],
  ['exec.positions',      '/api/execution', {action:'positions'}],
  ['exec.orders',         '/api/execution', {action:'orders', limit:10}],
  ['exec.trades',         '/api/execution', {action:'trades', limit:10}],
  ['exec.update_price',   '/api/execution', {action:'update_price'}],
  ['risk.portfolio',      '/api/risk',      {action:'portfolio_risk'}],
  ['risk.system_health',  '/api/risk',      {action:'system_health'}],
  ['risk.system_log',     '/api/risk',      {action:'system_log', lines:10}],
  ['alerts.list',         '/api/alerts',    {action:'list'}],
  ['alerts.rules',        '/api/alerts',    {action:'rules'}],
  ['alerts.check',        '/api/alerts',    {action:'check'}],
  ['alerts.stats',        '/api/alerts',    {action:'stats'}],
  ['qlib.status',         '/api/qlib',      {action:'status'}, 30],
  ['qlib.factors',        '/api/qlib',      {action:'factors', code:'000001.SZ', start:LONG_START, end:END}, 60],
];

const out = fs.createWriteStream(LOG_FILE);
const log = (s) => { out.write(s + '\n'); process.stdout.write(s + '\n'); };

const fmt = (data) => {
  if (data === null || data === undefined) return 'null';
  if (Array.isArray(data)) return `array[${data.length}]`;
  if (typeof data === 'object') return `obj{${Object.keys(data).slice(0,4).join(',')}}`;
  return String(data).slice(0, 60);
};

async function runOne([name, p, body, timeoutSec = 60]) {
  const t0 = Date.now();
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutSec * 1000);
    const res = await fetch(API + p, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
    clearTimeout(timer);
    const ms = Date.now() - t0;
    const json = await res.json().catch(() => ({success:false, error:'invalid JSON'}));
    if (json.success === true) return {name, ok:true, ms, note:fmt(json.data)};
    return {name, ok:false, ms, note:`[${res.status}] ${json.error || 'unknown'}`};
  } catch (e) {
    return {name, ok:false, ms:Date.now() - t0, note:`EXC: ${String(e.message || e).slice(0,120)}`};
  }
}

(async () => {
  log(`===== ${NOW.toISOString()} (${tests.length} tests) =====`);

  // 先 ping 一下确认 server alive；如果挂了试着拉起来
  let serverAlive = false;
  try {
    await fetch(API + '/api/data', {method:'POST', headers:{'Content-Type':'application/json'},
                                     body:'{"action":"stats"}', signal:AbortSignal.timeout(5000)});
    serverAlive = true;
  } catch {}

  if (!serverAlive) {
    log(`WARN: API server down at ${API}, attempting auto-restart...`);
    const { spawn } = await import('node:child_process');
    const serverLog = fs.openSync(path.join(LOG_DIR, '..', 'server_daemon.log'), 'a');
    const errLog = fs.openSync(path.join(LOG_DIR, '..', 'server_daemon.err.log'), 'a');
    const child = spawn('node', ['server/index.mjs'], {
      cwd: ROOT,
      detached: true,
      stdio: ['ignore', serverLog, errLog],
      windowsHide: true,
    });
    child.unref();
    log(`spawned PID ${child.pid}, waiting 6s for boot...`);
    await new Promise(r => setTimeout(r, 6000));
    try {
      await fetch(API + '/api/data', {method:'POST', headers:{'Content-Type':'application/json'},
                                       body:'{"action":"stats"}', signal:AbortSignal.timeout(5000)});
      serverAlive = true;
      log(`server back online ✓`);
    } catch (e) {
      log(`FATAL: auto-restart failed -- ${e.message}`);
      out.end();
      fs.appendFileSync(SUMMARY_FILE, JSON.stringify({
        ts: NOW.toISOString(), pass: 0, fail: tests.length, fatal: 'server_down_unrecoverable',
      }) + '\n');
      process.exit(2);
    }
  }

  const results = [];
  for (const t of tests) {
    const r = await runOne(t);
    results.push(r);
    log(`${r.ok ? '✓' : '✗'} ${r.name.padEnd(22)} ${String(r.ms).padStart(6)}ms  ${r.note}`);
  }
  const ok = results.filter(r => r.ok).length;
  const fail = results.length - ok;
  log(`\nPASS: ${ok}/${results.length}    FAIL: ${fail}`);
  if (fail) {
    log('--- Failures ---');
    for (const r of results.filter(r => !r.ok)) {
      log(`  ✗ ${r.name.padEnd(22)} ${r.note}`);
    }
  }
  out.end();

  const failures = results.filter(r => !r.ok).map(r => ({name:r.name, note:r.note}));
  fs.appendFileSync(SUMMARY_FILE, JSON.stringify({
    ts: NOW.toISOString(), pass: ok, fail, failures,
  }) + '\n');

  process.exit(fail ? 1 : 0);
})();

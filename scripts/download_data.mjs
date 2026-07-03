#!/usr/bin/env node
/**
 * A 股数据批量下载脚本 (Node.js)
 * 通过 server/routes/history.mjs 的 fetchHistory 下载（走 SOCKS5 代理）
 * 写入 SQLite (data/stocks.db)
 *
 * 用法：
 *   node scripts/download_data.mjs               # 全量下载
 *   node scripts/download_data.mjs --quick-test   # 测试5只
 *   node scripts/download_data.mjs --workers 5    # 5个并发
 *   node scripts/download_data.mjs --refresh      # 强制重下
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import BetterSqlite3 from 'better-sqlite3';
import { fetchHistory } from '../server/routes/history.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.join(__dirname, '..', 'data');
const DB_PATH = path.join(DATA_DIR, 'stocks.db');
const STOCKS_JSON = path.join(DATA_DIR, 'stock_list.json');
const PROGRESS_FILE = path.join(DATA_DIR, 'download_progress.json');

// ── 参数 ──────────────────────────────────────────────────────
const args = process.argv.slice(2);
const QUICK_TEST = args.includes('--quick-test');
const REFRESH = args.includes('--refresh');
const WORKERS = Math.min(20, parseInt(args[args.indexOf('--workers') + 1]) || 8);
const DAYS = parseInt(args[args.indexOf('--days') + 1]) || 365;

const END_DATE = new Date();
const START_DATE = new Date(Date.now() - DAYS * 86400000);

const startStr = formatDate(START_DATE);
const endStr = formatDate(END_DATE);

function formatDate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}${m}${day}`;
}

function log(...msg) {
  const ts = new Date().toISOString().slice(11, 19);
  console.log(`[${ts}]`, ...msg);
}

function fmt(n) { return n >= 10000 ? (n/10000).toFixed(1)+'w' : n; }

// ── 获取股票列表 ──────────────────────────────────────────────

function getStockList() {
  if (fs.existsSync(STOCKS_JSON)) {
    const list = JSON.parse(fs.readFileSync(STOCKS_JSON, 'utf-8'));
    log(`从缓存读取股票列表: ${list.length} 只`);
    return list;
  }
  log('需要先获取股票列表，运行: python -c "..."');
  return [];
}

function getMarket(code) {
  if (code.startsWith('6')) return 'SH';
  if (code.startsWith('0') || code.startsWith('3')) return 'SZ';
  if (code.startsWith('8') || code.startsWith('4')) return 'BJ';
  return 'OTHER';
}

// ── SQLite ────────────────────────────────────────────────────

let db;

function initDb() {
  fs.mkdirSync(DATA_DIR, { recursive: true });
  db = new BetterSqlite3(DB_PATH);
  db.pragma('journal_mode = WAL');
  db.pragma('synchronous = OFF');
  db.pragma('cache_size = -8000');

  db.exec(`
    CREATE TABLE IF NOT EXISTS stocks (
      code        TEXT PRIMARY KEY,
      name        TEXT NOT NULL,
      market      TEXT NOT NULL DEFAULT 'SH',
      list_date   TEXT,
      is_active   INTEGER NOT NULL DEFAULT 1,
      created_at  TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS daily_bars (
      id          INTEGER PRIMARY KEY AUTOINCREMENT,
      code        TEXT NOT NULL,
      date        TEXT NOT NULL,
      open        REAL NOT NULL,
      high        REAL NOT NULL,
      low         REAL NOT NULL,
      close       REAL NOT NULL,
      volume      INTEGER NOT NULL,
      amount      REAL NOT NULL DEFAULT 0,
      amplitude   REAL NOT NULL DEFAULT 0,
      pct_chg     REAL NOT NULL DEFAULT 0,
      change_val  REAL NOT NULL DEFAULT 0,
      fqt         INTEGER NOT NULL DEFAULT 1,
      created_at  TEXT NOT NULL DEFAULT (datetime('now')),
      UNIQUE(code, date, fqt)
    );
    CREATE INDEX IF NOT EXISTS idx_daily_bars_code_date ON daily_bars(code, date);
  `);
}

function upsertBar(code, bar) {
  db.prepare(`
    INSERT INTO daily_bars
      (code, date, open, high, low, close, volume, amount, amplitude, pct_chg, change_val, fqt)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(code, date, fqt) DO UPDATE SET
      open=excluded.open, high=excluded.high, low=excluded.low,
      close=excluded.close, volume=excluded.volume, amount=excluded.amount,
      amplitude=excluded.amplitude, pct_chg=excluded.pct_chg, change_val=excluded.change_val
  `).run(code, bar.date, bar.open, bar.high, bar.low, bar.close,
         bar.volume, bar.amount, bar.amplitude, bar.pctChg, bar.changeVal, 1);
}

function bulkInsert(code, bars) {
  if (!bars || bars.length === 0) return 0;
  const insert = db.prepare(`
    INSERT OR IGNORE INTO daily_bars
      (code, date, open, high, low, close, volume, amount, amplitude, pct_chg, change_val, fqt)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `);

  const tx = db.transaction((rows) => {
    for (const r of rows) {
      insert.run(code, r.date, r.open, r.high, r.low, r.close,
                 r.volume, r.amount, r.amplitude, r.pctChg, r.changeVal, 1);
    }
  });
  tx(bars);
  return bars.length;
}

// ── 股票列表生成 ──────────────────────────────────────────────

async function generateStockList() {
  log('正在通过 Baostock 获取股票列表...');
  // 用子进程调用 Python
  const { execSync } = await import('child_process');
  const pyCode = `
import baostock as bs, json
from datetime import datetime, timedelta
bs.login()
today = datetime.now().strftime('%Y-%m-%d')
rs = bs.query_all_stock(today)
if rs.error_code != '0' or rs.get_data().empty:
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    rs = bs.query_all_stock(yesterday)
df = rs.get_data()
df = df[df['tradeStatus'] == '1'].copy()
df['code_num'] = df['code'].str.split('.').str[1]
# 过滤指数
df = df[df['code_num'].apply(lambda c: c.startswith(('6','0','3','8','4')) and not c.startswith('000'))]
result = df[['code_num', 'code_name']].to_dict('records')
print(json.dumps(result, ensure_ascii=False))
`;
  const result = execSync(`python -c "${pyCode.replace(/"/g, '\\"').replace(/\n/g, ' ')}"`, {
    timeout: 60000,
    maxBuffer: 10 * 1024 * 1024
  });
  const list = JSON.parse(result.toString().trim());
  fs.writeFileSync(STOCKS_JSON, JSON.stringify(list, null, 2), 'utf-8');
  log(`股票列表: ${list.length} 只, 已缓存到 ${STOCKS_JSON}`);
  return list;
}

// ── 下载核心 ──────────────────────────────────────────────────

async function downloadOne(code, name) {
  try {
    const hist = await fetchHistory(code, startStr, endStr, 1);
    if (hist && hist.klines && hist.klines.length > 0) {
      // 写入 stocks 表
      db.prepare(`INSERT OR IGNORE INTO stocks (code, name, market) VALUES (?, ?, ?)`)
        .run(code, name, getMarket(code));
      // 写入 K 线
      bulkInsert(code, hist.klines);
      return hist.klines.length;
    }
    return 0;
  } catch (e) {
    return -1;
  }
}

// ── 进度管理 ──────────────────────────────────────────────────

function loadProgress() {
  try { return JSON.parse(fs.readFileSync(PROGRESS_FILE, 'utf-8')); } catch { return {}; }
}

function saveProgress(p) {
  fs.writeFileSync(PROGRESS_FILE, JSON.stringify(p, null, 2), 'utf-8');
}

// ── 主流程 ────────────────────────────────────────────────────

async function main() {
  log(`启动 A 股数据下载 (Node.js)`);
  log(`参数: workers=${WORKERS} days=${DAYS} refresh=${REFRESH} quick=${QUICK_TEST}`);
  log(`日期: ${startStr} ~ ${endStr}`);

  initDb();

  // 获取股票列表
  let stockList;
  if (QUICK_TEST) {
    stockList = [
      { code_num: '000001', code_name: '平安银行' },
      { code_num: '000002', code_name: '万科A' },
      { code_num: '600519', code_name: '贵州茅台' },
      { code_num: '300750', code_name: '宁德时代' },
      { code_num: '000333', code_name: '美的集团' },
    ];
  } else {
    if (fs.existsSync(STOCKS_JSON)) {
      stockList = JSON.parse(fs.readFileSync(STOCKS_JSON, 'utf-8'));
      log(`股票列表缓存: ${stockList.length} 只`);
    } else {
      stockList = await generateStockList();
    }
  }

  // 过滤已下载
  let progress = loadProgress();
  if (!REFRESH) {
    const before = stockList.length;
    stockList = stockList.filter(s => !progress[s.code_num]);
    log(`过滤后: ${stockList.length}/${before} 只需要下载`);
  }

  if (stockList.length === 0) {
    log('所有股票已下载完成');
    checkDbStats();
    db.close();
    return;
  }

  log(`开始下载 ${stockList.length} 只股票...`);

  const tStart = Date.now();
  let done = 0, errors = 0, totalBars = 0;
  const concurrency = QUICK_TEST ? stockList.length : WORKERS;

  // 并发控制
  const queue = [...stockList];
  async function worker() {
    while (queue.length > 0) {
      const stock = queue.shift();
      const code = stock.code_num;
      const name = stock.code_name;
      const bars = await downloadOne(code, name);
      if (bars >= 0) {
        done++;
        totalBars += bars;
        progress[code] = { bars, name, date: endStr };
      } else {
        errors++;
      }
      const elapsed = (Date.now() - tStart) / 1000;
      const rate = done / elapsed;
      log(`[${done}/${stockList.length}] ${code} ${name}: ${fmt(bars)}条 ✓${done} ✗${errors} ${rate.toFixed(1)}条/s`);
    }
  }

  const workers = Array.from({ length: concurrency }, () => worker());
  await Promise.all(workers);

  saveProgress(progress);

  const elapsed = (Date.now() - tStart) / 1000;
  log(`========== 完成 ==========`);
  log(`耗时: ${elapsed.toFixed(0)}s (${(elapsed/60).toFixed(1)}min)`);
  log(`成功: ${done} 失败: ${errors}`);
  log(`总K线: ${totalBars}`);

  checkDbStats();
  db.close();
}

function checkDbStats() {
  const stocks = db.prepare('SELECT COUNT(*) as c FROM stocks').get();
  const bars = db.prepare('SELECT COUNT(*) as c FROM daily_bars').get();
  const size = fs.existsSync(DB_PATH) ? (fs.statSync(DB_PATH).size / 1024 / 1024).toFixed(1) + ' MB' : '0';
  log(`库状态: ${stocks.c} 只股票, ${bars.c} 条K线, ${size}`);
}

main().catch(e => {
  console.error('Fatal:', e);
  process.exit(1);
});

/**
 * HTTP 工具模块：请求解析、响应、静态文件、日志
 */
import fs from 'fs';
import path from 'path';
import { LOG_DIR, MIME, STATIC_DIR } from './config.mjs';
import { writeDbLog } from './db_log_writer.mjs';

const STATIC_ROOT = path.resolve(STATIC_DIR);
export const MAX_REQUEST_BODY_BYTES = 1024 * 1024;
const LOG_RETENTION_DAYS = Math.max(1, Number(process.env.XUANJI_LOG_RETENTION_DAYS || 30));
const SENSITIVE_STATIC_NAMES = new Set([
  '.env', '.env.local', '.env.development', '.env.production',
  '.npmrc', '.yarnrc', '.pnpmrc', 'package-lock.json',
]);
const SENSITIVE_STATIC_EXTS = new Set([
  '.pem', '.key', '.crt', '.p12', '.pfx', '.sqlite', '.sqlite3', '.db', '.log',
]);
const STDERR_LEVELS = new Set(['WARN', 'ERROR', 'FATAL']);

export function pruneOldLogs(now = Date.now()) {
  fs.mkdirSync(LOG_DIR, { recursive: true });
  const cutoff = now - LOG_RETENTION_DAYS * 24 * 60 * 60 * 1000;
  for (const name of fs.readdirSync(LOG_DIR)) {
    if (!/^server-\d{8}\.log$/.test(name)) continue;
    const filePath = path.join(LOG_DIR, name);
    try {
      if (fs.statSync(filePath).mtimeMs < cutoff) fs.unlinkSync(filePath);
    } catch {}
  }
}

pruneOldLogs();

// ─── 日志 ───────────────────────────────

export function log(level, msg) {
  const ts = new Date().toISOString();
  const line = `[${ts}] [${level}] ${msg}\n`;
  const consoleMethod = STDERR_LEVELS.has(String(level).toUpperCase())
    ? console.error
    : console.log;
  consoleMethod(line.trimEnd());
  fs.appendFile(currentLogFile(), line, () => {});
  writeDbLog(level, msg, { line });
}

function currentLogFile() {
  const day = new Date().toISOString().slice(0, 10).replace(/-/g, '');
  fs.mkdirSync(LOG_DIR, { recursive: true });
  return path.join(LOG_DIR, `server-${day}.log`);
}

export function logRequest(req, status, extra) {
  const method = req.method;
  const url = req.url;
  const detail = extra ? ` ${extra}` : '';
  log('REQ', `${method} ${url} -> ${status}${detail}`);
}

// ─── 请求体解析 ──────────────────────────

export function readBody(req) {
  if (req._parsedBody) return Promise.resolve(req._parsedBody);
  return new Promise((resolve, reject) => {
    let body = '';
    let settled = false;
    req.on('data', c => {
      if (settled) return;
      body += c;
      if (Buffer.byteLength(body, 'utf8') > MAX_REQUEST_BODY_BYTES) {
        settled = true;
        body = '';
        const error = new Error('request body exceeds 1 MiB limit');
        error.statusCode = 413;
        req.resume();
        reject(error);
      }
    });
    req.on('end', () => {
      if (settled) return;
      try {
        const parsed = body ? JSON.parse(body) : {};
        req._parsedBody = parsed;
        resolve(parsed);
      } catch (e) {
        const error = new Error('invalid JSON request body');
        error.statusCode = 400;
        reject(error);
      }
    });
    req.on('error', error => {
      if (!settled) reject(error);
    });
  });
}

// ─── JSON 响应 ──────────────────────────

export function json(res, status, data) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(data));
}

// ─── 静态文件服务 ─────────────────────────

export function serveStatic(req, res, urlPath) {
  let decodedPath;
  try {
    decodedPath = decodeURIComponent(urlPath);
  } catch {
    res.writeHead(400, { 'Content-Type': 'text/plain' });
    res.end('Bad Request');
    return true;
  }

  const normalizedUrlPath = decodedPath.replace(/\\/g, '/');
  const parts = normalizedUrlPath.split('/').filter(Boolean);
  const lowerBase = path.basename(normalizedUrlPath).toLowerCase();
  const requestedExt = path.extname(lowerBase).toLowerCase();
  if (
    parts.includes('..') ||
    SENSITIVE_STATIC_NAMES.has(lowerBase) ||
    SENSITIVE_STATIC_EXTS.has(requestedExt)
  ) {
    res.writeHead(404, { 'Content-Type': 'text/plain' });
    res.end('Not Found');
    return true;
  }

  const relPath = normalizedUrlPath === '/' ? 'index.html' : normalizedUrlPath.replace(/^\/+/, '');
  let filePath = path.resolve(STATIC_ROOT, relPath);
  if (filePath !== STATIC_ROOT && !filePath.startsWith(STATIC_ROOT + path.sep)) {
    res.writeHead(404, { 'Content-Type': 'text/plain' });
    res.end('Not Found');
    return true;
  }
  if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
    filePath = path.join(STATIC_ROOT, 'index.html');
  }
  if (!fs.existsSync(filePath)) return false;

  const ext = path.extname(filePath).toLowerCase();
  const contentType = MIME[ext] || 'application/octet-stream';
  res.writeHead(200, { 'Content-Type': contentType });
  res.end(fs.readFileSync(filePath));
  return true;
}

// ─── HTTP GET 请求 ──────────────────

import http from 'http';
import https from 'https';

export function fetchNode(url, options = {}) {
  return new Promise((resolve, reject) => {
    const opts = {
      headers: { 'User-Agent': 'Mozilla/5.0', ...options.headers },
      timeout: 15000,
      ...options,
    };
    const mod = url.startsWith('https') ? https : http;
    const req = mod.get(url, opts, (resp) => {
      let body = '';
      resp.on('data', c => body += c);
      resp.on('end', () => {
        try { resolve(JSON.parse(body)); }
        catch { reject(new Error('parse error')); }
      });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('timeout')); });
  });
}

// ─── 自动日志包装 ─────────────────────────

export function wrapResponseLogging(req, res) {
  const origEnd = res.end.bind(res);
  res.end = (data) => {
    const status = res.statusCode || 200;
    let detail = '';
    if (data && typeof data === 'string') {
      try { const j = JSON.parse(data); if (!j.success) detail = j.error || j.message || ''; }
      catch {}
    }
    logRequest(req, status, detail || '');
    origEnd(data);
  };
}

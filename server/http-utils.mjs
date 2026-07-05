/**
 * HTTP 工具模块：请求解析、响应、静态文件、日志
 */
import fs from 'fs';
import path from 'path';
import { LOG_FILE, MIME, STATIC_DIR } from './config.mjs';

// ─── 日志 ───────────────────────────────

export function log(level, msg) {
  const ts = new Date().toISOString();
  const line = `[${ts}] [${level}] ${msg}\n`;
  console.error(line.trimEnd());
  fs.appendFile(LOG_FILE, line, () => {});
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
    req.on('data', c => { body += c; });
    req.on('end', () => {
      try {
        const parsed = body ? JSON.parse(body) : {};
        req._parsedBody = parsed;
        resolve(parsed);
      } catch (e) {
        console.log('[readBody] parse error:', e.message, 'body:', JSON.stringify(body));
        req._parsedBody = {};
        resolve({});
      }
    });
    req.on('error', reject);
  });
}

// ─── JSON 响应 ──────────────────────────

export function json(res, status, data) {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(data));
}

// ─── 静态文件服务 ─────────────────────────

export function serveStatic(req, res, urlPath) {
  let filePath = path.join(STATIC_DIR, urlPath === '/' ? 'index.html' : urlPath);
  if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
    filePath = path.join(STATIC_DIR, 'index.html');
  }
  if (!fs.existsSync(filePath)) return false;

  const ext = path.extname(filePath).toLowerCase();
  const contentType = MIME[ext] || 'application/octet-stream';
  res.writeHead(200, { 'Content-Type': contentType });
  res.end(fs.readFileSync(filePath));
  return true;
}

// ─── HTTP GET 请求代理 ──────────────────

import http from 'http';
import https from 'https';
import { SocksProxyAgent } from 'socks-proxy-agent';
import { SOCKS_PROXY } from './config.mjs';

export function fetchNode(url, options = {}) {
  return new Promise((resolve, reject) => {
    const opts = {
      headers: { 'User-Agent': 'Mozilla/5.0', ...options.headers },
      timeout: 15000,
      ...options,
    };
    if (options.useProxy !== false) {
      opts.agent = new SocksProxyAgent(SOCKS_PROXY);
    }
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

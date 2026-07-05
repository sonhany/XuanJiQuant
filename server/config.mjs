/**
 * 配置模块：环境变量 + 全局常量
 */
import fs from 'fs';
import path from 'path';
import { execSync } from 'child_process';
import { fileURLToPath } from 'url';

export const __dirname = path.dirname(fileURLToPath(import.meta.url));
export const ROOT_DIR = path.resolve(__dirname, '..');
export const STATIC_DIR = path.join(ROOT_DIR, 'dist');
export const LOG_FILE = path.join(ROOT_DIR, 'server.log');

// SOCKS5 代理地址
export const SOCKS_PROXY = 'socks5://127.0.0.1:1088';

// MIME 类型映射
export const MIME = {
  '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg',
  '.json': 'application/json', '.ico': 'image/x-icon', '.woff2': 'font/woff2',
};

// 手动解析 .env
const envPath = path.join(ROOT_DIR, '.env');
if (fs.existsSync(envPath)) {
  const content = fs.readFileSync(envPath, 'utf-8');
  for (const line of content.split('\n')) {
    const t = line.trim();
    if (!t || t.startsWith('#')) continue;
    const i = t.indexOf('=');
    if (i > 0) {
      let v = t.slice(i + 1).trim();
      if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) v = v.slice(1, -1);
      process.env[t.slice(0, i).trim()] = v;
    }
  }
}

// 服务器端口 / 主机。默认仅监听本机, 避免控制面暴露到局域网。
export const PORT = Number(process.env.PORT || 3334);
export const HOST = process.env.HOST || '127.0.0.1';
export const API_TOKEN = process.env.ALPHACOUNCIL_API_TOKEN || '';
export const ALLOWED_ORIGINS = (process.env.ALLOWED_ORIGINS || 'http://localhost:3333,http://127.0.0.1:3333')
  .split(',').map(s => s.trim()).filter(Boolean);

export const JUHE_API_KEY = process.env.JUHE_API_KEY;
export const GEMINI_API_KEY = process.env.GEMINI_API_KEY;
export const DEEPSEEK_API_KEY = process.env.DEEPSEEK_API_KEY;
export const QWEN_API_KEY = process.env.QWEN_API_KEY;

export function resolvePython() {
  if (process.env.PYTHON) return process.env.PYTHON;
  try {
    const out = execSync('where python', { encoding: 'utf-8', windowsHide: true }).trim();
    const lines = out.split(/\r?\n/);
    for (const line of lines) {
      if (!line.includes('uv\\') && !line.includes('WindowsApps')) return line.trim();
    }
    return lines[0] || 'python';
  } catch { return 'python'; }
}

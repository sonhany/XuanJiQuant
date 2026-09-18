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
export const LOG_DIR = path.join(ROOT_DIR, 'logs');
fs.mkdirSync(LOG_DIR, { recursive: true });

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
export const PORT = Number(process.env.PORT || 8880);
export const HOST = process.env.HOST || '127.0.0.1';
export const API_TOKEN = process.env.XUANJI_API_TOKEN || '';
export const ALLOWED_ORIGINS = (process.env.ALLOWED_ORIGINS || 'http://localhost:8888,http://127.0.0.1:8888')
  .split(',').map(s => s.trim()).filter(Boolean);

export function resolvePython() {
  if (process.env.PYTHON) return process.env.PYTHON;
  // 跨平台查找: Linux/macOS 用 which, Windows 用 where
  const isWin = process.platform === 'win32';
  const finder = isWin ? 'where' : 'which';
  const candidates = isWin ? ['python', 'python3'] : ['python3', 'python'];
  for (const name of candidates) {
    try {
      const out = execSync(`${finder} ${name}`, { encoding: 'utf-8', windowsHide: true }).trim();
      const lines = out.split(/\r?\n/);
      // Windows: 跳过 uv\ 和 WindowsApps 的 shim; Linux: 取第一行
      const hit = isWin
        ? lines.find(l => !l.includes('uv\\') && !l.includes('WindowsApps'))
        : lines[0];
      if (hit) return hit.trim();
    } catch { /* 继续尝试下一个候选 */ }
  }
  return 'python3';
}

/**
 * 轻量请求缓存 (SWR 风格) — 降低页面切换/轮询的后端压力
 *
 * 设计:
 *   - cachedApi(body, ttl): 相同 body 在 ttl 秒内复用结果 (去重并发请求)
 *   - invalidate(action): 手动失效某 action 的缓存 (写操作后调用)
 *   - 纯前端, 零依赖, 仅用于轮询类只读请求
 *
 * 用法:
 *   import { cachedApi } from './lib/apiCache';
 *   const data = await cachedApi({ action: 'ai_all_status' }, 10);  // 10s 内复用
 *   invalidate('status');  // 写操作后清缓存
 */
const API_BASE = 'http://localhost:3334';

interface CacheEntry {
  data: any;
  expiresAt: number;
  promise?: Promise<any>;  // 进行中的请求 (去重并发)
}

const _cache = new Map<string, CacheEntry>();

/** 生成缓存 key (基于 action + 关键参数)。 */
function cacheKey(body: any): string {
  // 只用 action + 少量参数做 key, 忽略时间戳类字段
  const { action, provider, days, limit } = body || {};
  return JSON.stringify({ action, provider, days, limit });
}

/**
 * 带缓存的 API 调用。
 * @param body 请求体 (含 action)
 * @param ttl 缓存秒数 (默认 0 = 不缓存)
 * @param force 强制刷新 (跳过缓存)
 */
export async function cachedApi(body: any, ttl: number = 0, force: boolean = false): Promise<any> {
  // 不缓存: 直接请求
  if (ttl <= 0 || force) {
    return rawApi(body);
  }
  const key = cacheKey(body);
  const now = Date.now();

  // 命中未过期缓存
  const entry = _cache.get(key);
  if (entry && entry.expiresAt > now) {
    return entry.data;
  }
  // 已有进行中的相同请求 → 复用 (去重并发)
  if (entry?.promise) {
    return entry.promise;
  }

  // 发起新请求
  const promise = rawApi(body).then(d => {
    _cache.set(key, { data: d, expiresAt: Date.now() + ttl * 1000 });
    return d;
  }).catch(e => {
    _cache.delete(key);  // 失败不缓存
    throw e;
  });
  _cache.set(key, { data: undefined, expiresAt: now, promise });
  return promise;
}

/** 原始 API 调用 (无缓存)。 */
export async function rawApi(body: any): Promise<any> {
  const r = await fetch(`${API_BASE}/api/paper`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return r.json();
}

/** 失效缓存: 清掉匹配某 action 的所有缓存项。 */
export function invalidate(action: string): void {
  for (const key of _cache.keys()) {
    if (key.includes(`"action":"${action}"`)) {
      _cache.delete(key);
    }
  }
}

/** 清空全部缓存。 */
export function clearCache(): void {
  _cache.clear();
}

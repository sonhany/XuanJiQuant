"""缓存层 — 默认 SQLite，可选 Redis / 内存

设计目标: 零外部依赖，双击即可运行。
- SqliteCache (默认): 单文件 data/quant.db，Python 内置 sqlite3，重启不丢数据
- RedisCache  (可选):  环境变量 QUANT_CACHE=redis 时启用，需本机 Redis
- MemoryCache (兜底):  纯内存，进程结束即失，仅用于无磁盘权限场景

统一接口 (所有实现必须满足):
    get(key)         -> Any | None
    set(key, value, ttl=None)
    delete(key)
    keys(pattern='') -> list[str]
    clear()
    size()           -> int          # 键总数 (替代 Redis 的 dbsize)

历史问题修复:
    旧版在 Redis 端口未开放时不定义 RedisCache 类，导致
    `from .cache import RedisCache` 在普通机器上 ImportError，
    连带整个 quant.data 包无法导入。现在所有类无条件定义。
"""
import json
import logging
import os
import sqlite3
import threading
import time
from typing import Any, Optional

logger = logging.getLogger("quant.cache")

# ─── 数据库文件位置 ──────────────────────────────────────────
# quant/data/cache.py -> 上两级是项目根目录
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DB_DIR = os.path.join(_ROOT, 'data')
_DEFAULT_DB_PATH = os.path.join(_DB_DIR, 'quant.db')


# ═══════════════════════════════════════════════════════════
#  SqliteCache — 默认存储，零外部依赖
# ═══════════════════════════════════════════════════════════
class SqliteCache:
    """基于 SQLite 的持久化 KV 存储

    表结构:
        kv (key TEXT PRIMARY KEY, value TEXT, exp REAL)
    - value 以 JSON 序列化存储 (ensure_ascii=False)
    - exp 为过期时间戳 (epoch 秒), NULL 表示永不过期
    - 线程安全: RLock 保护 + 单连接 check_same_thread=False
    """

    def __init__(self, db_path: Optional[str] = None, default_ttl: Optional[int] = None):
        self._db_path = db_path or os.environ.get('QUANT_DB_PATH', _DEFAULT_DB_PATH)
        self._default_ttl = default_ttl  # None = 永不过期
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")  # 并发读写更稳
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()
        logger.info(f"SqliteCache ready: {self._db_path}")

    def _init_schema(self):
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS kv (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    exp   REAL
                )
            """)
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_kv_exp ON kv(exp)")
            self._conn.commit()

    def _purge_expired(self):
        """删除已过期键 (惰性清理之外的主动清理)"""
        now = time.time()
        with self._lock:
            self._conn.execute("DELETE FROM kv WHERE exp IS NOT NULL AND exp < ?", (now,))
            self._conn.commit()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT value, exp FROM kv WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        value, exp = row
        if exp is not None and time.time() > exp:
            self.delete(key)  # 惰性删除
            return None
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value  # 非 JSON 原样返回

    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """存储数据。ttl=None 表示永不过期 (或用 default_ttl)"""
        effective_ttl = ttl if ttl is not None else self._default_ttl
        exp = (time.time() + effective_ttl) if effective_ttl else None
        data = json.dumps(value, default=str, ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO kv (key, value, exp) VALUES (?, ?, ?)",
                (key, data, exp),
            )
            self._conn.commit()

    def delete(self, key: str):
        with self._lock:
            self._conn.execute("DELETE FROM kv WHERE key = ?", (key,))
            self._conn.commit()

    def clear(self):
        with self._lock:
            self._conn.execute("DELETE FROM kv")
            self._conn.commit()

    def keys(self, pattern: str = "") -> list:
        """支持 glob 风格模式 (如 kline:*:d)。

        把 * -> %、? -> _ 转成 SQL LIKE，并转义字面量 % _。
        """
        self._purge_expired()
        if not pattern:
            rows = self._conn.execute("SELECT key FROM kv").fetchall()
        else:
            like = pattern.replace('%', '\\%').replace('_', '\\_')
            like = like.replace('*', '%').replace('?', '_')
            rows = self._conn.execute(
                "SELECT key FROM kv WHERE key LIKE ? ESCAPE '\\'", (like,)
            ).fetchall()
        return [r[0] for r in rows]

    def size(self) -> int:
        """键总数 (替代 Redis 的 dbsize)"""
        self._purge_expired()
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM kv").fetchone()
        return int(row[0]) if row else 0

    # ── 兼容性: 旧代码 cache.client.keys()/dbsize() ──
    @property
    def client(self):
        """返回自身。SqliteCache 自身已实现 keys()/size()/scan_iter()，
        使旧代码 cache.client.xxx() 无需改动即可工作。"""
        return self

    def dbsize(self) -> int:
        """Redis 兼容方法"""
        return self.size()

    def scan_iter(self, match: str = None, count: int = None):
        """Redis 兼容方法: 生成器 yield key"""
        for k in self.keys(match):
            yield k


# ═══════════════════════════════════════════════════════════
#  MemoryCache — 纯内存兜底
# ═══════════════════════════════════════════════════════════
class MemoryCache:
    def __init__(self, default_ttl: Optional[int] = 60):
        self._store: dict = {}
        self._default_ttl = default_ttl

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.time() > entry["exp"]:
            del self._store[key]
            return None
        return entry["data"]

    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        effective_ttl = ttl if ttl is not None else self._default_ttl
        self._store[key] = {
            "data": value,
            "exp": time.time() + effective_ttl if effective_ttl else float('inf'),
        }

    def delete(self, key: str):
        self._store.pop(key, None)

    def clear(self):
        self._store.clear()

    def keys(self, pattern: str = "") -> list:
        if not pattern:
            return list(self._store.keys())
        import fnmatch
        return [k for k in self._store if fnmatch.fnmatch(k, pattern)]

    def size(self) -> int:
        return len(self._store)

    def dbsize(self) -> int:
        return self.size()

    @property
    def client(self):
        return self

    def scan_iter(self, match: str = None, count: int = None):
        for k in self.keys(match):
            yield k


# ═══════════════════════════════════════════════════════════
#  RedisCache — 可选，需本机 Redis (无条件定义，避免 ImportError)
# ═══════════════════════════════════════════════════════════
def _redis_available(host="127.0.0.1", port=6379) -> bool:
    """Fast TCP port probe (200ms timeout)"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.2)
    try:
        s.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


class RedisCache:
    """Redis 缓存。Redis 不可用时实例化会抛异常 (用 create_cache() 自动降级)"""

    def __init__(self, host="127.0.0.1", port=6379, db=0, default_ttl: Optional[int] = 60):
        import redis as _redis  # 延迟导入: 不装 redis 包也能用 SqliteCache
        self._client = _redis.Redis(
            host=host, port=port, db=db,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=2,
        )
        self._default_ttl = default_ttl
        self._client.ping()  # 不可用即抛异常
        logger.info(f"RedisCache connected: {host}:{port}/{db}")

    def get(self, key: str) -> Optional[Any]:
        val = self._client.get(key)
        if val is None:
            return None
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return val

    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        effective_ttl = ttl if ttl is not None else self._default_ttl
        data = json.dumps(value, default=str, ensure_ascii=False)
        if effective_ttl:
            self._client.setex(key, effective_ttl, data)
        else:
            self._client.set(key, data)

    def delete(self, key: str):
        self._client.delete(key)

    def clear(self):
        self._client.flushdb()

    def keys(self, pattern: str = "") -> list:
        return self._client.keys(pattern or "*")

    def size(self) -> int:
        return self._client.dbsize()

    def dbsize(self) -> int:
        return self._client.dbsize()

    @property
    def client(self):
        return self._client

    def scan_iter(self, match: str = None, count: int = None):
        return self._client.scan_iter(match=match or '*', count=count or 1000)


# ═══════════════════════════════════════════════════════════
#  工厂函数 — 统一数据访问出口
# ═══════════════════════════════════════════════════════════
_cache_instance = None


def create_cache(host="127.0.0.1", port=6379, db=0, default_ttl: Optional[int] = None):
    """获取缓存单例 (线程安全)

    优先级 (通过环境变量 QUANT_CACHE 控制):
        QUANT_CACHE=sqlite (默认) -> SqliteCache  零依赖，推荐
        QUANT_CACHE=redis         -> RedisCache   不可用时自动降级 SqliteCache
        QUANT_CACHE=memory        -> MemoryCache  纯内存
    """
    global _cache_instance
    if _cache_instance is not None:
        return _cache_instance

    backend = os.environ.get('QUANT_CACHE', 'sqlite').lower().strip()

    if backend == 'memory':
        _cache_instance = MemoryCache(default_ttl)
        logger.info("Using MemoryCache (QUANT_CACHE=memory)")
        return _cache_instance

    if backend == 'redis':
        try:
            _cache_instance = RedisCache(host, port, db, default_ttl)
            return _cache_instance
        except Exception as e:
            logger.warning(f"Redis unavailable ({e}), fallback to SqliteCache")
            _cache_instance = SqliteCache(default_ttl=default_ttl)
            return _cache_instance

    # 默认 SQLite
    _cache_instance = SqliteCache(default_ttl=default_ttl)
    return _cache_instance


def reset_cache():
    """重置单例 (仅测试用)"""
    global _cache_instance
    if _cache_instance is not None and hasattr(_cache_instance, '_conn'):
        try:
            _cache_instance._conn.close()
        except Exception:
            pass
    _cache_instance = None

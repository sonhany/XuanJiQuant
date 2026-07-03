"""Data Layer — 数据源: 腾讯日 K + AKShare A 股特色数据

模块结构:
  cache:          SQLite(默认)/Redis/内存 缓存
  schema:         数据契约 + 校验
  tencent_source: 日 K 线数据源 (前复权)
  akshare_source: A 股特色数据源 (财务/北向/龙虎榜/涨停)
  loader:         K 线 DataFrame 加载器
  sync_service:   后台同步进程
  health:         数据健康检查

推荐用 create_cache() 获取缓存实例 (默认 SQLite，零外部依赖)。
"""
from .cache import create_cache, SqliteCache, RedisCache, MemoryCache
from .schema import (
    REQUIRED_FIELDS, REQUIRED_QUOTE_FIELDS, SchemaError,
    validate_bar, validate_series, validate_quote,
)
from .tencent_source import (
    fetch_klines, fetch_quotes, load_universe,
    normalize_code, tencent_symbol,
)
from .akshare_source import (
    fetch_financial_abstract, fetch_core_financials,
    list_financial_fields, CORE_FINANCIAL_FIELDS,
)
from .loader import load_kline_df

__all__ = [
    'create_cache', 'SqliteCache', 'RedisCache', 'MemoryCache',
    'REQUIRED_FIELDS', 'REQUIRED_QUOTE_FIELDS', 'SchemaError',
    'validate_bar', 'validate_series', 'validate_quote',
    'fetch_klines', 'fetch_quotes', 'load_universe',
    'normalize_code', 'tencent_symbol',
    'fetch_financial_abstract', 'fetch_core_financials',
    'list_financial_fields', 'CORE_FINANCIAL_FIELDS',
    'load_kline_df',
]

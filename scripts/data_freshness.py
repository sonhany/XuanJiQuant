"""统一数据新鲜度判断 — 全系统唯一的 stale 检查入口

所有模块必须调用此模块的函数判断数据是否过期, 禁止各自实现采样逻辑。
这消除了"5个文件各自判断、口径不一致"的根本问题。

用法:
  from scripts.data_freshness import is_data_stale, get_latest_kline_date, get_expected_date
  if is_data_stale():
      # 数据过期
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache

_cache = create_cache()


def get_expected_date(now: datetime = None) -> str:
    """计算预期最新交易日的日期 (YYYYMMDD)。
    
    规则:
    - 周末: 预期上周五
    - 收盘前 (15:00 前): 预期上一交易日 (因为当日K线还没出)
    - 收盘后 (15:00 后): 预期今天
    """
    now = now or datetime.now()
    # 周末回退到周五
    d = now
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    # 收盘前回退一天 (再跳过周末)
    if now.hour < 15:
        d -= timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
    return d.strftime("%Y%m%d")


def get_latest_kline_date() -> str:
    """获取最新K线日期。优先查股票池, 其次全市场。"""
    latest = ""
    try:
        # 1. 优先查股票池
        cfg = _cache.get("paper:config") or {}
        universe = cfg.get("universe", []) or []
        for code in universe[:30]:
            raw = _cache.get(f"kline:{code}:d")
            if raw and isinstance(raw, list) and raw:
                d = str(raw[-1].get("date") or raw[-1].get("d") or "")
                if d and d > latest:
                    latest = d
        if latest:
            return latest
        # 2. 股票池无数据则采样全市场 (仅用于判断"是否有任何数据")
        for k in _cache.keys("kline:*:d")[:80]:
            raw = _cache.get(k)
            if raw and isinstance(raw, list) and raw:
                d = str(raw[-1].get("date") or raw[-1].get("d") or "")
                if d and d > latest:
                    latest = d
    except Exception:
        pass
    return latest


def is_data_stale() -> bool:
    """判断数据是否过期。全系统唯一的判断入口。
    
    Returns:
        True = 数据过期 (不可交易)
        False = 数据正常 (可交易)
    """
    latest = get_latest_kline_date()
    if not latest:
        return True  # 无数据视为过期
    expected = get_expected_date()
    return latest < expected


def check_integrity() -> dict:
    """完整的数据完整性检查。"""
    cfg = _cache.get("paper:config") or {}
    universe = cfg.get("universe", []) or []
    expected = get_expected_date()
    latest = get_latest_kline_date()
    stale = is_data_stale()

    stocks = []
    summary = {"ok": 0, "stale": 0, "missing": 0, "partial": 0}
    for code in universe[:50]:
        code = str(code).split(".")[0].strip()
        raw = _cache.get(f"kline:{code}:d")
        if not raw or not isinstance(raw, list) or not raw:
            summary["missing"] += 1
            stocks.append({"code": code, "status": "missing", "latest_date": "", "bar_count": 0})
            continue
        bar_count = len(raw)
        stock_latest = str(raw[-1].get("date") or "")
        if stock_latest < expected:
            status = "stale"
        elif bar_count < 20:
            status = "partial"
        else:
            status = "ok"
        summary[status] += 1
        stocks.append({"code": code, "status": status, "latest_date": stock_latest, "bar_count": bar_count})

    return {
        "expected_latest": expected,
        "today": datetime.now().strftime("%Y%m%d"),
        "global_latest": latest,
        "data_stale": stale,
        "universe_size": len(universe),
        "summary": summary,
        "stocks": stocks,
    }

"""统一数据新鲜度判断 — 全系统唯一的 stale 检查入口

所有模块必须调用此模块的函数判断数据是否过期, 禁止各自实现采样逻辑。
这消除了"5个文件各自判断、口径不一致"的根本问题。

用法:
  from scripts.data_freshness import is_data_stale, get_latest_kline_date, get_expected_date
  if is_data_stale():
      # 数据过期
"""
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache

_cache = create_cache()
_BAR_DATE_PATTERN = re.compile(
    r'"(?:date|d)"\s*:\s*"?(\d{8}|\d{4}-\d{2}-\d{2})'
)


def _full_market_minimum_coverage() -> float:
    try:
        value = float(os.getenv("FULL_MARKET_KLINE_MIN_COVERAGE", "0.95"))
    except (TypeError, ValueError):
        value = 0.95
    return max(0.8, min(value, 1.0))


def assess_market_kline_coverage(
    *,
    cache=None,
    expected_date: str = "",
    minimum_coverage: float | None = None,
) -> dict:
    """Assess full-market daily-bar coverage without trusting one newest symbol."""
    active_cache = cache or _cache
    expected = str(expected_date or get_expected_date()).replace("-", "")[:8]
    threshold = (
        _full_market_minimum_coverage()
        if minimum_coverage is None
        else max(0.0, min(float(minimum_coverage), 1.0))
    )
    counts: Counter[str] = Counter()
    conn = getattr(active_cache, "_conn", None)
    if conn is not None:
        try:
            # Daily bar values contain multi-year JSON arrays. Extracting JSON
            # from every full value makes a health request scan gigabytes. The
            # last bar is compact, so read only a bounded serialized tail and
            # derive its final date without deserializing the historical array.
            rows = conn.execute(
                "SELECT substr(value, -?) "
                "FROM kv WHERE key LIKE 'kline:%:d' "
                "AND (exp IS NULL OR exp >= ?)",
                (512, datetime.now().timestamp()),
            ).fetchall()
            for (tail,) in rows:
                matches = _BAR_DATE_PATTERN.findall(str(tail or ""))
                if matches:
                    counts[matches[-1].replace("-", "")[:8]] += 1
        except Exception:
            counts.clear()
    if not counts:
        try:
            keys = active_cache.keys("kline:*:d")
        except Exception:
            keys = []
        for key in keys:
            try:
                bars = active_cache.get(key)
            except Exception:
                continue
            if not isinstance(bars, list) or not bars:
                continue
            latest = bars[-1] if isinstance(bars[-1], dict) else {}
            date_text = str(latest.get("date") or latest.get("d") or "").replace("-", "")[:8]
            if date_text:
                counts[date_text] += 1
    total = sum(counts.values())
    coverage_date = ""
    dominant_count = 0
    if counts:
        coverage_date, dominant_count = max(
            counts.items(), key=lambda item: (item[1], item[0])
        )
    expected_count = sum(count for date_text, count in counts.items() if date_text >= expected)
    expected_coverage = expected_count / total if total else 0.0
    return {
        "fresh": bool(
            total
            and coverage_date >= expected
            and expected_coverage >= threshold
        ),
        "expected_date": expected,
        "coverage_date": coverage_date,
        "dominant_count": dominant_count,
        "expected_count": expected_count,
        "total_count": total,
        "expected_coverage": round(expected_coverage, 6),
        "minimum_coverage": threshold,
        "date_counts": dict(sorted(counts.items(), reverse=True)[:10]),
    }


def get_expected_date(now: datetime = None) -> str:
    """计算预期最新交易日的日期 (YYYYMMDD)。
    
    规则:
    - 周末: 预期上周五
    - 日K就绪时间前 (默认 15:30): 预期上一交易日
    - 日K就绪时间后: 预期今天
    """
    now = now or datetime.now()
    # 周末直接回退到周五。不能再套用“盘前回退一天”，否则周日早上会错误落到周四。
    d = now
    if d.weekday() >= 5:
        while d.weekday() >= 5:
            d -= timedelta(days=1)
    else:
        configured = os.getenv("DAILY_BAR_READY_TIME", "15:30").strip()
        try:
            hour_text, minute_text = configured.split(":", 1)
            ready_minutes = int(hour_text) * 60 + int(minute_text)
            if not 15 * 60 <= ready_minutes <= 18 * 60:
                raise ValueError
        except (AttributeError, TypeError, ValueError):
            ready_minutes = 15 * 60 + 30
        current_minutes = now.hour * 60 + now.minute
        if current_minutes >= ready_minutes:
            return d.strftime("%Y%m%d")
        # 交易日的日K尚处于收盘结算窗口，继续使用上一交易日。
        d -= timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
    return d.strftime("%Y%m%d")


def get_latest_kline_date(cache=None) -> str:
    """获取最新K线日期。优先查股票池, 其次全市场。"""
    active_cache = cache or _cache
    latest = ""
    try:
        # 1. 优先查股票池
        cfg = active_cache.get("paper:config") or {}
        universe = cfg.get("universe", []) or []
        for code in universe[:30]:
            raw = active_cache.get(f"kline:{code}:d")
            if raw and isinstance(raw, list) and raw:
                d = str(raw[-1].get("date") or raw[-1].get("d") or "")
                if d and d > latest:
                    latest = d
        if latest:
            return latest
        # 2. 股票池无数据则采样全市场 (仅用于判断"是否有任何数据")
        for k in active_cache.keys("kline:*:d")[:80]:
            raw = active_cache.get(k)
            if raw and isinstance(raw, list) and raw:
                d = str(raw[-1].get("date") or raw[-1].get("d") or "")
                if d and d > latest:
                    latest = d
    except Exception:
        pass
    return latest


def is_data_stale(cache=None, now: datetime = None) -> bool:
    """判断数据是否过期。全系统唯一的判断入口。
    
    Returns:
        True = 数据过期 (不可交易)
        False = 数据正常 (可交易)
    """
    expected = get_expected_date(now)
    return not assess_market_kline_coverage(
        cache=cache,
        expected_date=expected,
    )["fresh"]


def check_integrity(cache=None, now: datetime = None) -> dict:
    """完整的数据完整性检查。"""
    active_cache = cache or _cache
    current = now or datetime.now()
    cfg = active_cache.get("paper:config") or {}
    universe = cfg.get("universe", []) or []
    expected = get_expected_date(current)
    market_coverage = assess_market_kline_coverage(
        cache=active_cache,
        expected_date=expected,
    )
    latest = market_coverage.get("coverage_date") or ""
    stale = not market_coverage.get("fresh", False)

    stocks = []
    summary = {"ok": 0, "stale": 0, "missing": 0, "partial": 0}
    for code in universe[:50]:
        code = str(code).split(".")[0].strip()
        raw = active_cache.get(f"kline:{code}:d")
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
        "today": current.strftime("%Y%m%d"),
        "global_latest": latest,
        "data_stale": stale,
        "market_coverage": market_coverage,
        "universe_size": len(universe),
        "summary": summary,
        "stocks": stocks,
    }

"""Trading Calendar — A股交易日历

设计原则:
  - 不引入新数据源，从已有 K 线数据推导交易日
  - 从缓存里的 K 线日期集推导"哪些日期是交易日"
  - 覆盖近2-3年足够日常使用
  - 节假日靠已有数据反推：如果某工作日在任何股票的K线里都没出现 → 非交易日

Key:
  calendar:trade_dates  -> sorted list of YYYYMMDD strings (近2年交易日)
  calendar:built_at     -> 构建时间

用法:
  from scripts.trading_calendar import build_trading_calendar, is_trade_date, prev_trade_date, next_trade_date
"""
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache

logger = logging.getLogger("calendar")
cache = create_cache()

CALENDAR_KEY = "calendar:trade_dates"
BUILT_AT_KEY = "calendar:built_at"


def _scan_latest_kline_date() -> str:
    """直接扫描 K线缓存拿最新日期 (避免循环依赖 data_freshness)。"""
    try:
        latest = ""
        for k in cache.keys("kline:*:d")[:50]:  # 采样前50只
            raw = cache.get(k)
            if raw and isinstance(raw, list) and raw:
                d = str(raw[-1].get("date") or raw[-1].get("d") or "")
                if len(d) == 8 and d.isdigit() and d > latest:
                    latest = d
        return latest
    except Exception:
        return ""


def build_trading_calendar(force: bool = False) -> List[str]:
    """从已有K线数据推导交易日历。
    采样多只股票的K线日期，取并集，得到交易日集合。
    """
    if not force:
        existing = cache.get(CALENDAR_KEY)
        # 自动重建: 若 K线最新日期 > 日历最新日期, 说明有新数据入库但日历没更新
        if existing and isinstance(existing, list) and len(existing) > 100:
            kline_latest = _scan_latest_kline_date()
            if kline_latest and kline_latest > existing[-1]:
                logger.info(f"日历落后于K线 (cal={existing[-1]} < kline={kline_latest}), 自动重建")
                force = True

    date_set = set()
    try:
        keys = cache.keys("kline:*:d")
        # 采样前500只(足够覆盖近2年所有交易日)
        for k in keys[:500]:
            raw = cache.get(k)
            if raw and isinstance(raw, list):
                for bar in raw:
                    d = str(bar.get("date") or bar.get("d") or "")
                    if len(d) == 8 and d.isdigit():
                        date_set.add(d)
    except Exception as e:
        logger.warning(f"build_trading_calendar failed: {e}")

    dates = sorted(date_set)
    if len(dates) > 10:
        cache.set(CALENDAR_KEY, dates)
        cache.set(BUILT_AT_KEY, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        logger.info(f"交易日历构建: {len(dates)} 个交易日 ({dates[0]} ~ {dates[-1]})")
    return dates


def get_trade_dates() -> List[str]:
    """获取交易日列表，不存在则自动构建。"""
    dates = cache.get(CALENDAR_KEY)
    if not dates or not isinstance(dates, list) or len(dates) < 10:
        dates = build_trading_calendar(force=True)
    return dates if dates else []


# ── A股固定节假日 (月-日, 不依赖外部库) ──────────────────
# 仅用于日历范围外的日期推断; 日历范围内的日期以 K线推导为准。
# 调休补班不在内 (无法静态判断), 偶尔多算一天无害 (调度器多跑一轮轻量巡检)。
_FIXED_HOLIDAYS = {
    "01-01",          # 元旦
    "02-10", "02-11", "02-12",  # 春节 (2026年正月初一=2/17, 假期通常前后延伸, 取保守值)
    "02-16", "02-17", "02-18",
    "04-04", "04-05", "04-06",  # 清明
    "05-01", "05-02", "05-03",  # 劳动节
    "06-19", "06-20", "06-21",  # 端午
    "09-25", "09-26", "09-27",  # 中秋
    "10-01", "10-02", "10-03", "10-04", "10-05", "10-06", "10-07",  # 国庆
}


def _is_fixed_holiday(date_str: str) -> bool:
    """检查是否固定节假日 (MM-DD 格式匹配)。"""
    try:
        d = datetime.strptime(date_str, "%Y%m%d")
        return d.strftime("%m-%d") in _FIXED_HOLIDAYS
    except Exception:
        return False


def is_trade_date(date_str: str) -> bool:
    """判断指定日期是否为交易日。
    date_str: 'YYYYMMDD' 或 'YYYY-MM-DD'

    策略:
      - 日历范围内 (≤ 日历最新日期): 以 K线推导的日历为准 (准确)
      - 日历范围外 (> 日历最新日期, 如今天/未来): 工作日 且 非固定节假日 → 视为交易日
        (推断式, 偶尔多算调休补班日, 但不会漏判真实交易日)
    """
    d = str(date_str).replace("-", "").strip()
    if not d or len(d) != 8:
        return False
    dates = get_trade_dates()
    date_set = set(dates)
    # 在日历内: 直接查
    if d in date_set:
        return True
    # 早于日历范围: 不在日历 = 不是交易日 (历史已确定)
    if dates and d < dates[0]:
        return False
    # 晚于日历最新日期 (今天/未来): 推断 = 工作日 且 非固定节假日
    try:
        dt = datetime.strptime(d, "%Y%m%d")
        if dt.weekday() >= 5:  # 周六周日
            return False
        if _is_fixed_holiday(d):
            return False
        return True  # 工作日且非节假日 → 视为交易日
    except Exception:
        return False


def prev_trade_date(date_str: Optional[str] = None) -> str:
    """前一个交易日。默认基于今天。"""
    d = str(date_str or datetime.now().strftime("%Y%m%d")).replace("-", "").strip()
    dates = get_trade_dates()
    if not dates:
        # fallback: 往前找最近的工作日
        dt = datetime.strptime(d, "%Y%m%d")
        for _ in range(10):
            dt -= timedelta(days=1)
            if dt.weekday() < 5:
                return dt.strftime("%Y%m%d")
        return d
    prev_dates = [x for x in dates if x < d]
    return prev_dates[-1] if prev_dates else dates[0]


def next_trade_date(date_str: Optional[str] = None) -> str:
    """后一个交易日。默认基于今天。"""
    d = str(date_str or datetime.now().strftime("%Y%m%d")).replace("-", "").strip()
    dates = get_trade_dates()
    if not dates:
        dt = datetime.strptime(d, "%Y%m%d")
        for _ in range(15):
            dt += timedelta(days=1)
            if dt.weekday() < 5:
                return dt.strftime("%Y%m%d")
        return d
    next_dates = [x for x in dates if x > d]
    return next_dates[0] if next_dates else dates[-1]


def latest_trade_date(date_str: Optional[str] = None) -> str:
    """最近的交易日（含今天，如果今天是交易日；否则是上一个交易日）。
    用于模拟盘判断"数据应该到哪天"。
    """
    d = str(date_str or datetime.now().strftime("%Y%m%d")).replace("-", "").strip()
    if is_trade_date(d):
        return d
    return prev_trade_date(d)


def calendar_info() -> dict:
    """返回日历摘要信息。"""
    dates = get_trade_dates()
    if not dates:
        return {"total": 0, "start": "", "end": "", "built_at": ""}
    return {
        "total": len(dates),
        "start": dates[0],
        "end": dates[-1],
        "latest_trade_date": latest_trade_date(),
        "is_today_trade_date": is_trade_date(datetime.now().strftime("%Y%m%d")),
        "built_at": cache.get(BUILT_AT_KEY) or "",
    }

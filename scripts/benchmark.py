"""Benchmark Tracker — 基准（沪深300）对比

设计原则:
  - 不引入新数据源，复用新浪指数实时行情 + 指数历史 K 线缓存
  - 把基准当作一个"影子账户"：模拟盘启动时同步记一笔初始净值
  - 每次刷新把基准当日涨跌计入影子净值，便于和策略组合对比
  - 状态存 SQLite KV (paper:benchmark)

Key:
  paper:benchmark -> {
      initial_capital, initial_date,
      equity, prev_close, daily_return_pct, total_return_pct,
      history: [{date, equity, daily_return_pct}]
  }

调用方式:
  from scripts.benchmark import init_benchmark, refresh_benchmark, get_benchmark
  init_benchmark(1_000_000)   # 与模拟盘同初始资金
  refresh_benchmark()         # 刷新当日基准行情
"""
import json
import logging
import os
import sys
import urllib.request
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache

logger = logging.getLogger("benchmark")
cache = create_cache()

BENCHMARK_KEY = "paper:benchmark"
DEFAULT_BENCHMARK = "sh000300"  # 沪深300
DEFAULT_NAME = "沪深300"


def _fetch_index_quote(code: str = DEFAULT_BENCHMARK) -> Optional[dict]:
    """从新浪拉指数实时行情。
    返回 {name, price, prev_close, change_pct} 或 None。
    """
    url = f"http://hq.sinajs.cn/list={code}"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "http://finance.sina.com.cn",
        })
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("gbk", errors="replace")
        for line in raw.split("\n"):
            if "=" not in line:
                continue
            fields = line.split('"')[1].split(",") if '"' in line else []
            if len(fields) < 6:
                continue
            price = float(fields[3]) if fields[3] else 0.0
            prev_close = float(fields[2]) if fields[2] else 0.0
            if price == 0 and prev_close > 0:
                price = prev_close
            if prev_close <= 0:
                continue
            change_pct = (price - prev_close) / prev_close * 100
            return {
                "name": fields[0],
                "price": round(price, 4),
                "prev_close": round(prev_close, 4),
                "change_pct": round(change_pct, 4),
            }
    except Exception as e:
        logger.debug(f"fetch_index_quote({code}) failed: {e}")
    return None


def init_benchmark(initial_capital: float = 1_000_000.0, code: str = DEFAULT_BENCHMARK,
                   name: str = DEFAULT_NAME) -> dict:
    """初始化或对齐基准影子账户。已存在则不覆盖 history。"""
    existing = cache.get(BENCHMARK_KEY)
    if existing and isinstance(existing, dict) and existing.get("initial_capital"):
        return existing
    state = {
        "code": code,
        "name": name,
        "initial_capital": round(float(initial_capital), 2),
        "initial_date": datetime.now().strftime("%Y-%m-%d"),
        "equity": round(float(initial_capital), 2),
        "prev_close": 0.0,
        "daily_return_pct": 0.0,
        "total_return_pct": 0.0,
        "history": [],
    }
    cache.set(BENCHMARK_KEY, state)
    logger.info(f"benchmark init: {name} {initial_capital}")
    return state


def refresh_benchmark() -> dict:
    """刷新基准行情并更新影子净值。每日涨跌乘进 equity。
    同一交易日内多次调用，只按 prev_close 计一次涨跌。"""
    state = cache.get(BENCHMARK_KEY)
    if not isinstance(state, dict):
        state = init_benchmark()
    quote = _fetch_index_quote(state.get("code", DEFAULT_BENCHMARK))
    if not quote:
        state["last_error"] = "无法获取基准行情"
        cache.set(BENCHMARK_KEY, state)
        return state

    today = datetime.now().strftime("%Y-%m-%d")
    prev_close = quote["prev_close"]
    price = quote["price"]
    daily_ret = quote["change_pct"] / 100.0  # 转小数

    # 当日已记录过则只更新价格，不重复乘 equity
    last_hist = state.get("history", [])[-1] if state.get("history") else None
    already_logged_today = last_hist and last_hist.get("date") == today

    if not already_logged_today and prev_close > 0 and state.get("equity", 0) > 0:
        new_equity = state["equity"] * (1.0 + daily_ret)
        state["equity"] = round(new_equity, 2)
        state["daily_return_pct"] = round(daily_ret * 100, 4)
        total = (state["equity"] - state["initial_capital"]) / state["initial_capital"] * 100
        state["total_return_pct"] = round(total, 4)
        hist = state.get("history", [])
        hist.append({
            "date": today,
            "price": price,
            "daily_return_pct": round(daily_ret * 100, 4),
            "equity": state["equity"],
        })
        state["history"] = hist[-400:]
    elif already_logged_today:
        # 同日多次刷新只更新当日 price，equity 不变
        state["daily_return_pct"] = round(daily_ret * 100, 4)

    state["prev_close"] = prev_close
    state["price"] = price
    state["name"] = quote.get("name", state.get("name", DEFAULT_NAME))
    state.pop("last_error", None)
    cache.set(BENCHMARK_KEY, state)
    return state


def get_benchmark() -> dict:
    """读取基准影子账户状态。"""
    state = cache.get(BENCHMARK_KEY)
    if not isinstance(state, dict):
        state = init_benchmark()
    return state


def reset_benchmark(initial_capital: float = 1_000_000.0) -> dict:
    """重置基准账户。"""
    cache.delete(BENCHMARK_KEY)
    return init_benchmark(initial_capital)

"""统一行情数据服务 — 所有外部行情抓取的唯一入口

设计目标:
  - 单一数据源: Sina(实时/指数) + Eastmoney(板块/北向), 不再有重复代码
  - 统一缓存: 所有结果写入 quant.db (create_cache)
  - 内置重试: 网络抖动容错 (复用 global_context 的重试模式)
  - 斩断循环依赖: ai_data_agent 直接 import 本模块, 不再反向调 Node /api/market

数据源:
  - Sina hq.sinajs.cn: A股实时行情 + 全球指数 (复用 global_context._parse_sina_line)
  - Eastmoney push2.eastmoney.com: 板块资金流 + 北向资金 (从 data-source.js 移植)

缓存键:
  stock:realtime:<code>       TTL 120s  逐代码实时行情统一缓存
  market:realtime:batch      兼容旧批量缓存, 内部 _ts 5s
  market:sector_flow:latest         板块资金流
  market:northbound:latest          北向资金

用法:
  from scripts.market_data import fetch_realtime, fetch_indices, fetch_sector_flow, fetch_northbound
"""
import json
import logging
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger("market_data")


def _cache():
    """延迟导入, 避免循环依赖。"""
    from quant.data.cache import create_cache
    return create_cache()


def _safe_float(v):
    try:
        return float(v) if v not in (None, "") else 0.0
    except (ValueError, TypeError):
        return 0.0


def _safe_int(v):
    try:
        return int(float(v)) if v not in (None, "") else 0
    except (ValueError, TypeError):
        return 0


def _normalize_sina_code(raw) -> str:
    """归一化为 Sina 代码: 600519/600519.SH/sh600519 -> sh600519。"""
    c = str(raw or "").strip().lower()
    if not c:
        return ""
    c = c.replace(".sh", "").replace(".sz", "")
    if c.startswith(("sh", "sz")):
        return c
    if len(c) == 6 and c.isdigit():
        # A股常用规则: 6/5/9 为上海, 其余为深圳/北交兼容走 sz
        return ("sh" if c[0] in ("5", "6", "9") else "sz") + c
    return c


def _pure_code(sina_code: str) -> str:
    code = str(sina_code or "").lower()
    if code.startswith(("sh", "sz")):
        return code[2:]
    return code


def _is_index_code(code: str) -> bool:
    return str(code).lower().startswith(("sh0", "sh5", "sz3", "sz1"))


def _parse_sina_quote(code: str, fields: list):
    """解析 Sina 行情。指数必须先于普通股票解析, 因指数字段也可能超过 10 个。"""
    if not fields:
        return None

    # 指数格式(实测): [0]名称 [1]今开 [2]昨收 [3]当前价 [4]高 [5]低 [8]成交量 [9]成交额
    if _is_index_code(code) and len(fields) >= 6:
        price = _safe_float(fields[3]) if len(fields) > 3 else 0
        prev_close = _safe_float(fields[2]) if len(fields) > 2 else 0
        chg_pct = ((price / prev_close - 1) * 100) if prev_close > 0 else 0
        return {
            "name": fields[0] or code,
            "open": _safe_float(fields[1]) if len(fields) > 1 else 0,
            "close": prev_close,
            "price": price,
            "high": _safe_float(fields[4]) if len(fields) > 4 else 0,
            "low": _safe_float(fields[5]) if len(fields) > 5 else 0,
            "volume": _safe_int(fields[8]) if len(fields) > 8 else 0,
            "amount": _safe_float(fields[9]) if len(fields) > 9 else 0,
            "chg_pct": round(chg_pct, 2),
            "time": fields[31] if len(fields) > 31 else "",
            "source": "sina",
        }

    # A股实时格式: [0]名称 [1]今开 [2]昨收 [3]当前价 [4]高 [5]低 ... [8]成交量 [9]成交额
    if len(fields) >= 10:
        price = _safe_float(fields[3])
        prev_close = _safe_float(fields[2])
        chg_pct = ((price / prev_close - 1) * 100) if prev_close > 0 else 0
        return {
            "name": fields[0] or code,
            "open": _safe_float(fields[1]),
            "close": prev_close,  # 昨收 (字段名兼容前端)
            "price": price,
            "high": _safe_float(fields[4]),
            "low": _safe_float(fields[5]),
            "volume": _safe_int(fields[8]),
            "amount": _safe_float(fields[9]),
            "chg_pct": round(chg_pct, 2),
            "time": fields[31] if len(fields) > 31 else "",
            "source": "sina",
        }

    # 兜底指数短格式: [0]名称 [1]现价 [2]昨收
    if len(fields) >= 3:
        price = _safe_float(fields[1])
        prev_close = _safe_float(fields[2])
        chg_pct = ((price / prev_close - 1) * 100) if prev_close > 0 else 0
        return {
            "name": fields[0] or code,
            "open": price,
            "close": prev_close,
            "price": price,
            "high": price,
            "low": price,
            "volume": 0,
            "amount": 0,
            "chg_pct": round(chg_pct, 2),
            "source": "sina",
        }
    return None


# ── Sina 实时行情 (A股格式) ─────────────────────────────
def fetch_realtime(codes: list, use_cache: bool = True) -> dict:
    """获取 A股实时行情 (Sina)。

    Args:
        codes: 股票代码列表, 支持 ['sh600519','sz000001'] 或 ['600519','000001'] 格式
        use_cache: 是否用缓存 (逐代码 120s + 批量 5s)
    Returns:
        {"sh600519": {name, open, close, price, high, low, volume, amount, chg_pct}, ...}
    """
    if not codes:
        return {}

    sina_codes = []
    for raw in codes:
        code = _normalize_sina_code(raw)
        if code:
            sina_codes.append(code)
    sina_codes = list(dict.fromkeys(sina_codes))
    if not sina_codes:
        return {}

    c = _cache()
    result = {}
    missing = []

    # 1) 兼容旧 batch 缓存: 完整 codes 一致且 5s 内直接返回
    if use_cache:
        cached = c.get("market:realtime:batch") or {}
        cache_age = cached.get("_ts", 0)
        if time.time() - cache_age < 5 and cached.get("_codes") == sorted(sina_codes):
            return cached.get("_data", {})

    # 2) 逐代码统一缓存: 与 sync_service.py 共用 stock:realtime:<code>
    for code in sina_codes:
        cached_quote = c.get(f"stock:realtime:{_pure_code(code)}") if use_cache else None
        if cached_quote:
            result[code] = cached_quote
        else:
            missing.append(code)

    # 3) 缺失/过期才拉 Sina
    if missing:
        try:
            url = f"http://hq.sinajs.cn/list={','.join(missing)}"
            req = urllib.request.Request(url, headers={
                "Referer": "https://finance.sina.com.cn",
                "User-Agent": "Mozilla/5.0",
            })
            with urllib.request.urlopen(req, timeout=8) as resp:
                body = resp.read().decode("gbk", errors="replace")

            for line in body.strip().split("\n"):
                m = re.match(r'var hq_str_(\S+)="(.*)"', line.strip())
                if not m or not m.group(2):
                    continue
                code = m.group(1)
                fields = m.group(2).split(",")
                quote = _parse_sina_quote(code, fields)
                if not quote:
                    continue
                result[code] = quote
                pure = _pure_code(code)
                c.set(f"stock:realtime:{pure}", quote, ttl=120)
                if quote.get("name"):
                    c.set(f"stock:name:{pure}", quote["name"])
        except Exception as e:
            logger.debug(f"fetch_realtime failed: {e}")

    # 4) 网络失败时, 尝试回退旧 batch 缓存中的交集, 避免 UI 直接归零
    if len(result) < len(sina_codes):
        cached = c.get("market:realtime:batch") or {}
        old_data = cached.get("_data", {}) if isinstance(cached, dict) else {}
        for code in sina_codes:
            if code not in result and code in old_data:
                result[code] = old_data[code]

    if use_cache and result:
        c.set("market:realtime:batch", {"_ts": time.time(), "_codes": sorted(sina_codes), "_data": result})
    return result


# ── 全球指数 (复用 global_context) ──────────────────────
def fetch_indices() -> dict:
    """获取全球指数实时数据 (复用 global_context 的多品种解析)。

    Returns:
        global_context.collect_global_context() 的完整结果 (含 risk_level/trade_policy)。
    """
    from scripts.global_context import collect_global_context
    return collect_global_context()


# ── Eastmoney 板块资金流 (从 data-source.js 移植) ────────
def fetch_sector_flow() -> list:
    """获取板块资金流排行 (Eastmoney)。

    Returns:
        [{name, inflow(亿), chg_pct, top_stock}, ...] 前10名
    """
    c = _cache()
    try:
        url = (
            "http://push2.eastmoney.com/api/qt/clist/get"
            "?pn=1&pz=10&po=1&np=1"
            "&fields=f2,f3,f4,f12,f14,f62,f184"
            "&fid=f62&fs=m:90+t:2"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = json.loads(resp.read().decode("utf-8"))

        diff = (raw.get("data") or {}).get("diff") or []
        result = [{
            "name": item.get("f14", ""),
            "inflow": round((item.get("f62", 0) or 0) / 1e8, 2),
            "chg_pct": round((item.get("f3", 0) or 0) / 100, 2),
            "top_stock": item.get("f12", ""),
        } for item in diff]

        if result:
            c.set("market:sector_flow:latest", result)
        return result
    except Exception as e:
        logger.debug(f"fetch_sector_flow failed: {e}")
        return c.get("market:sector_flow:latest") or []


# ── Eastmoney 北向资金 (从 data-source.js 移植) ──────────
def fetch_northbound() -> dict:
    """获取北向资金净流入 (Eastmoney)。

    Returns:
        {northFlow(亿), trend(strong_inflow/strong_outflow/neutral), history:[]}
    """
    c = _cache()
    try:
        url = (
            "http://push2.eastmoney.com/api/qt/kamt.kline/get"
            "?kamt=1&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55&lmt=5"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = json.loads(resp.read().decode("utf-8"))

        lines = (raw.get("data") or {}).get("klines") or []
        if not lines:
            return c.get("market:northbound:latest") or {"northFlow": 0, "trend": "neutral"}

        history = []
        for line in lines:
            parts = line.split(",")
            if len(parts) >= 5:
                history.append({
                    "date": parts[0],
                    "hk_to_sh": round(float(parts[1]) / 1e4, 2) if parts[1] else 0,
                    "hk_to_sz": round(float(parts[2]) / 1e4, 2) if parts[2] else 0,
                    "total": round(float(parts[3]) / 1e4, 2) if parts[3] else 0,
                    "northFlow": round(float(parts[4]) / 1e8, 2) if parts[4] else 0,
                })

        last = history[-1] if history else {"northFlow": 0}
        north_flow = last.get("northFlow", 0)
        trend = "strong_inflow" if north_flow > 20 else ("strong_outflow" if north_flow < -20 else "neutral")
        result = {"northFlow": north_flow, "trend": trend, "history": history}

        c.set("market:northbound:latest", result)
        return result
    except Exception as e:
        logger.debug(f"fetch_northbound failed: {e}")
        return c.get("market:northbound:latest") or {"northFlow": 0, "trend": "neutral"}


# ── CLI 测试 ─────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print("=== 实时行情 ===")
    rt = fetch_realtime(["sh600519", "sz000001", "sh000001"])
    for code, d in rt.items():
        print(f"  {d.get('name','')} ({code}): {d.get('price')} ({d.get('chg_pct',0):+.2f}%)")

    print("\n=== 板块资金流 ===")
    sf = fetch_sector_flow()
    for s in sf[:5]:
        print(f"  {s['name']}: 净流入 {s['inflow']}亿 ({s['chg_pct']:+.2f}%)")

    print("\n=== 北向资金 ===")
    nb = fetch_northbound()
    print(f"  净流入: {nb.get('northFlow')}亿 趋势: {nb.get('trend')}")

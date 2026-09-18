"""统一行情数据服务 — 所有外部行情抓取的唯一入口

设计目标:
  - 单一入口: TdxQuant(实时/指数/K线) 优先, Sina/Tencent/Eastmoney/Jin10 按品种兜底
  - 统一缓存: 所有结果写入 quant.db (create_cache)
  - 内置重试: 网络抖动容错 (复用 global_context 的重试模式)
  - 数据源适配器由数据层直接调用，不反向依赖 Node /api/market

数据源:
  - TdxQuant 本地 TQ HTTP: A股股票/指数实时行情主源
  - Sina hq.sinajs.cn: A股/全球指数兜底
  - Tencent: A股成交额/名称补全兜底
  - Eastmoney push2.eastmoney.com: 板块资金流 + 北向资金

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
import math
import os
import re
import sys
import threading
import time
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger("market_data")

INDEX_CODES = {
    "sh000001", "sh000016", "sh000300", "sh000688", "sh000852", "sh000905",
    "sz399001", "sz399006",
}

STOCK_METRICS_TTL = 20
STOCK_METRICS_BATCH_SIZE = 50
_STOCK_METRICS_CACHE = {}
_STOCK_METRICS_LOCK = threading.Lock()


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


def _ensure_quote_timestamp(quote: dict, *, now: datetime | None = None) -> dict:
    """Preserve vendor dates; undated Sina prices must not become today's data."""
    if not isinstance(quote, dict):
        return quote
    current = now or datetime.now()
    raw = str(quote.get("timestamp") or quote.get("time") or "").strip()
    digits = "".join(character for character in raw if character.isdigit())
    if quote.get("source") == "sina" and len(digits) not in (12, 14):
        quote["timestamp"] = ""
        return quote
    if len(digits) >= 14:
        quote["timestamp"] = digits[:14]
    elif len(digits) == 12:
        quote["timestamp"] = f"{digits}00"
    elif len(digits) == 6:
        quote["timestamp"] = f"{current.strftime('%Y%m%d')}{digits}"
    elif len(digits) == 4:
        quote["timestamp"] = f"{current.strftime('%Y%m%d')}{digits}00"
    return quote


def _ensure_quote_timestamps(quotes: dict, *, now: datetime | None = None) -> dict:
    current = now or datetime.now()
    for quote in (quotes or {}).values():
        _ensure_quote_timestamp(quote, now=current)
    return quotes


def _fill_missing_amount(quote: dict) -> dict:
    if not isinstance(quote, dict):
        return quote
    if quote.get("is_index"):
        return quote
    amount = _safe_float(quote.get("amount"))
    if amount <= 0:
        price = _safe_float(quote.get("price"))
        volume = _safe_int(quote.get("volume"))
        if price > 0 and volume > 0:
            if quote.get("source") == "tdx_quant" or quote.get("volume_unit") == "hand":
                quote["amount"] = round(price * volume * 100, 2)
                quote["amount_source"] = "derived_lot_volume"
            else:
                quote["amount"] = round(price * volume, 2)
                quote["amount_source"] = "derived_volume"
    return quote


def _fresh_batch_fallback(cached: dict, *, now: float | None = None, max_age: float = 120.0) -> dict:
    if not isinstance(cached, dict):
        return {}
    ts = _safe_float(cached.get("_ts"))
    current = time.time() if now is None else float(now)
    if ts <= 0 or current - ts > max_age:
        return {}
    data = cached.get("_data")
    return data if isinstance(data, dict) else {}


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


def _sina_venue(code: str) -> str:
    value = str(code or "").lower()
    if value.startswith("sh"):
        return "XSHG"
    if value.startswith("sz"):
        return "XSHE"
    return ""


def _is_index_code(code: str) -> bool:
    c = str(code or "").lower()
    return c in INDEX_CODES or c.startswith("sh000") or c.startswith("sz399")


def source_policy() -> dict:
    from quant.data.source_policy import get_source_policy
    return get_source_policy()


def _realtime_cache_key(code: str) -> str:
    from quant.data.source_policy import realtime_cache_key
    return realtime_cache_key(code)


def _is_stock_quote_code(code: str) -> bool:
    if _is_index_code(code):
        return False
    pure = _pure_code(code)
    return not _is_index_code(code) and len(pure) == 6 and pure.isdigit()


def _has_index_code_collision(pure_code: str) -> bool:
    pure = str(pure_code or "").strip()
    return any(index_code[2:] == pure for index_code in INDEX_CODES if index_code.startswith(("sh", "sz")))


def _stock_name_cache_keys(code: str) -> list:
    pure = _pure_code(code)
    if pure and len(pure) == 6 and pure.isdigit() and not _has_index_code_collision(pure):
        return [f"stock:name:{pure}"]
    return []


def _get_cached_stock_name(cache, code: str) -> str:
    for key in _stock_name_cache_keys(code):
        value = cache.get(key)
        if value:
            return value
    return ""


def _set_cached_stock_name(cache, code: str, name: str) -> None:
    if not name:
        return
    for key in _stock_name_cache_keys(code):
        cache.set(key, name)


def _tdx_quant_enabled() -> bool:
    value = str(os.getenv("XUANJI_TDX_QUANT_FIRST", "1")).strip().lower()
    return value not in ("0", "false", "no", "off")


def _convert_tdx_quote(q: dict) -> dict:
    price = _safe_float(q.get("price"))
    prev_close = _safe_float(q.get("prev_close") or q.get("close"))
    chg_pct = ((price / prev_close - 1) * 100) if prev_close > 0 and price > 0 else 0
    quote_code = str(q.get("code") or "")
    is_index = bool(q.get("is_index")) or _is_index_code(quote_code)
    return {
        "name": q.get("name") or q.get("code") or "",
        "open": _safe_float(q.get("open")) or price,
        "close": prev_close,
        "price": price,
        "high": _safe_float(q.get("high")) or price,
        "low": _safe_float(q.get("low")) or price,
        "volume": _safe_int(q.get("volume")),
        "amount": _safe_float(q.get("amount")),
        "chg_pct": round(chg_pct, 2),
        "time": str(q.get("timestamp") or q.get("time") or ""),
        "source": "tdx_quant",
        "trading_state": q.get("trading_state") or "",
        "volume_unit": "hand",
        "is_index": is_index,
    }


def _convert_tencent_quote(q: dict) -> dict:
    price = _safe_float(q.get("price"))
    prev_close = _safe_float(q.get("prev_close"))
    chg_pct = ((price / prev_close - 1) * 100) if prev_close > 0 else 0
    return _fill_missing_amount({
        "name": q.get("name") or q.get("code") or "",
        "open": _safe_float(q.get("open")),
        "close": prev_close,
        "price": price,
        "high": _safe_float(q.get("high")),
        "low": _safe_float(q.get("low")),
        "volume": _safe_int(q.get("volume")),
        "amount": _safe_float(q.get("amount")) * 10000,
        "chg_pct": round(chg_pct, 2),
        "time": str(q.get("timestamp") or q.get("date_time") or ""),
        "source": "tencent",
    })


def _merge_quote_enrichment(primary: dict, fallback: dict, amount_source: str) -> dict:
    if not isinstance(primary, dict) or not isinstance(fallback, dict):
        return primary
    amount = _safe_float(fallback.get("amount"))
    if amount > 0 and _safe_float(primary.get("amount")) <= 0:
        primary["amount"] = amount
        primary["amount_source"] = amount_source
    name = str(fallback.get("name") or "").strip()
    primary_name = str(primary.get("name") or "").strip()
    if name and (not primary_name or primary_name == str(fallback.get("code") or "") or primary_name.isdigit()):
        primary["name"] = name
    for key in ("open", "high", "low"):
        if _safe_float(primary.get(key)) <= 0 and _safe_float(fallback.get(key)) > 0:
            primary[key] = _safe_float(fallback.get(key))
    fallback_time = str(fallback.get("time") or "")
    if fallback_time and not primary.get("fallback_time"):
        primary["fallback_time"] = fallback_time
    return primary


def _parse_sina_quote(code: str, fields: list):
    """解析 Sina 行情。指数必须先于普通股票解析, 因指数字段也可能超过 10 个。"""
    if not fields:
        return None
    vendor_timestamp = ""
    if len(fields) > 31:
        try:
            vendor_timestamp = datetime.strptime(
                f"{fields[30]} {fields[31]}", "%Y-%m-%d %H:%M:%S"
            ).strftime("%Y%m%d%H%M%S")
        except (ValueError, TypeError):
            pass

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
            "timestamp": vendor_timestamp,
            "source": "sina",
        }

    # A股实时格式: [0]名称 [1]今开 [2]昨收 [3]当前价 [4]高 [5]低 ... [8]成交量 [9]成交额
    if len(fields) >= 10:
        price = _safe_float(fields[3])
        prev_close = _safe_float(fields[2])
        chg_pct = ((price / prev_close - 1) * 100) if prev_close > 0 else 0
        bid = str(fields[11] if len(fields) > 11 and _safe_float(fields[11]) > 0 else fields[6] if len(fields) > 6 else "")
        ask = str(fields[21] if len(fields) > 21 and _safe_float(fields[21]) > 0 else fields[7] if len(fields) > 7 else "")
        return {
            "code": _pure_code(code),
            "venue": _sina_venue(code),
            "name": fields[0] or code,
            "open": _safe_float(fields[1]),
            "close": prev_close,  # 昨收 (字段名兼容前端)
            "price": price,
            "high": _safe_float(fields[4]),
            "low": _safe_float(fields[5]),
            "bid": bid,
            "ask": ask,
            "bid_size": _safe_int(fields[10]) if len(fields) > 10 else 0,
            "ask_size": _safe_int(fields[20]) if len(fields) > 20 else 0,
            "size_unit": "shares",
            "volume": _safe_int(fields[8]),
            "amount": _safe_float(fields[9]),
            "chg_pct": round(chg_pct, 2),
            "time": fields[31] if len(fields) > 31 else "",
            "timestamp": vendor_timestamp,
            "timestamp_kind": "exchange" if vendor_timestamp else "",
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
    """获取 A股实时行情。

    Source chain: TdxQuant primary, Tencent amount enrichment when needed,
    Sina fallback, then Tencent fallback for still-missing stock quotes.

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
        from quant.data.source_policy import REALTIME_CACHE_VERSION
        if (
            time.time() - cache_age < 5
            and cached.get("_codes") == sorted(sina_codes)
            and cached.get("_cache_version") == REALTIME_CACHE_VERSION
        ):
            return _ensure_quote_timestamps(cached.get("_data", {}))

    # 2) 逐代码统一缓存: 与 sync_service.py 共用 stock:realtime:<code>
    for code in sina_codes:
        cached_quote = c.get(_realtime_cache_key(code)) if use_cache else None
        if cached_quote:
            result[code] = cached_quote
        else:
            missing.append(code)

    if missing and _tdx_quant_enabled():
        tdx_index_missing = [code for code in missing if _is_index_code(code)]
        if tdx_index_missing:
            try:
                from quant.data.tdx_quant_source import fetch_realtime_quotes as fetch_tdx_realtime_quotes
                tdx_quotes = fetch_tdx_realtime_quotes(tdx_index_missing)
                for code in tdx_index_missing:
                    q = tdx_quotes.get(code)
                    if not q:
                        continue
                    quote = _convert_tdx_quote(q)
                    result[code] = quote
                    c.set(_realtime_cache_key(code), quote, ttl=120)
            except Exception as e:
                logger.debug(f"fetch_realtime tdx_quant index primary failed: {e}")

        tdx_stock_missing = [code for code in missing if _is_stock_quote_code(code)]
        if tdx_stock_missing:
            try:
                from quant.data.tdx_quant_source import fetch_quotes as fetch_tdx_quotes
                tdx_quotes = fetch_tdx_quotes([_pure_code(code) for code in tdx_stock_missing])
                for code in tdx_stock_missing:
                    pure = _pure_code(code)
                    q = tdx_quotes.get(pure)
                    if not q:
                        continue
                    quote = _convert_tdx_quote(q)
                    cached_name = _get_cached_stock_name(c, code)
                    if cached_name and (not quote.get("name") or quote.get("name") == pure):
                        quote["name"] = cached_name
                    result[code] = quote
                    c.set(_realtime_cache_key(code), quote, ttl=120)
                    if quote.get("name") and quote.get("name") != pure:
                        _set_cached_stock_name(c, code, quote["name"])
            except Exception as e:
                logger.debug(f"fetch_realtime tdx_quant primary failed: {e}")

    tdx_amount_missing = [
        code for code in sina_codes
        if code in result
        and result[code].get("source") == "tdx_quant"
        and _safe_float(result[code].get("amount")) <= 0
        and _is_stock_quote_code(code)
    ]
    if tdx_amount_missing:
        try:
            from quant.data.tencent_source import fetch_quotes
            tx_quotes = fetch_quotes([_pure_code(code) for code in tdx_amount_missing])
            for code in tdx_amount_missing:
                pure = _pure_code(code)
                q = tx_quotes.get(pure)
                if not q:
                    continue
                fallback = _convert_tencent_quote(q)
                _merge_quote_enrichment(result[code], fallback, "tencent")
                if fallback.get("name"):
                    _set_cached_stock_name(c, code, fallback["name"])
        except Exception as e:
            logger.debug(f"fetch_realtime tencent amount enrichment failed: {e}")

    missing = [code for code in sina_codes if code not in result]

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
                c.set(_realtime_cache_key(code), quote, ttl=120)
                if quote.get("name") and _is_stock_quote_code(code):
                    _set_cached_stock_name(c, code, quote["name"])
        except Exception as e:
            logger.debug(f"fetch_realtime sina primary failed: {e}")

    # Tencent fallback for missing stock quotes. Index quotes still require Sina
    # to avoid stock/index collisions such as 000001 versus sh000001.
    still_missing = [code for code in sina_codes if code not in result and _is_stock_quote_code(code)]

    # 4) Sina 缺失时, 股票报价由腾讯补位；指数仍只接受 Sina, 避免 000001 股票/指数歧义。
    still_missing = [code for code in sina_codes if code not in result and _is_stock_quote_code(code)]
    if still_missing:
        try:
            from quant.data.tencent_source import fetch_quotes
            tx_quotes = fetch_quotes([_pure_code(code) for code in still_missing])
            for code in still_missing:
                pure = _pure_code(code)
                q = tx_quotes.get(pure)
                if not q:
                    continue
                quote = _convert_tencent_quote(q)
                result[code] = quote
                c.set(_realtime_cache_key(code), quote, ttl=120)
                if quote.get("name"):
                    _set_cached_stock_name(c, code, quote["name"])
        except Exception as e:
            logger.debug(f"fetch_realtime tencent fallback failed: {e}")

    # 5) 网络失败时, 尝试回退 batch 缓存中的交集, 避免 UI 直接归零
    if len(result) < len(sina_codes):
        cached = c.get("market:realtime:batch") or {}
        old_data = _fresh_batch_fallback(cached)
        for code in sina_codes:
            if code not in result and code in old_data:
                result[code] = old_data[code]

    normalized_at = datetime.now()
    for code, quote in result.items():
        _ensure_quote_timestamp(quote, now=normalized_at)
        _fill_missing_amount(quote)
        c.set(_realtime_cache_key(code), quote, ttl=120)

    if use_cache and result:
        from quant.data.source_policy import REALTIME_CACHE_VERSION
        c.set("market:realtime:batch", {
            "_ts": time.time(),
            "_codes": sorted(sina_codes),
            "_cache_version": REALTIME_CACHE_VERSION,
            "_data": result,
        })
    return result


# ── 全球指数 (复用 global_context) ──────────────────────
def fetch_indices(*, force_refresh: bool = False, now=None) -> dict:
    """读取后台维护的全球指数快照；仅显式请求时同步刷新。

    Returns:
        global_context.collect_global_context() 的完整结果 (含 risk_level/trade_policy)。
    """
    from scripts.global_context import assess_context_freshness, collect_global_context

    if force_refresh:
        return collect_global_context()
    latest = _cache().get("global:context:latest") or {}
    return assess_context_freshness(latest, now=now)


def _optional_float(value):
    if value in (None, "", "-"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _metric_code(value):
    pure = re.sub(r"\D", "", str(value or ""))[-6:]
    return pure if len(pure) == 6 else ""


def _eastmoney_secid(code):
    pure = _metric_code(code)
    if not pure:
        return ""
    market = "1" if pure.startswith(("5", "6", "9")) else "0"
    return f"{market}.{pure}"


def _empty_stock_metric():
    return {
        "turnover_rate": None,
        "main_net_inflow": None,
        "main_net_inflow_pct": None,
        "money_flow_source": None,
        "turnover_source": None,
    }


def _fetch_eastmoney_stock_metrics(codes):
    result = {}
    for start in range(0, len(codes), STOCK_METRICS_BATCH_SIZE):
        chunk = codes[start:start + STOCK_METRICS_BATCH_SIZE]
        secids = ",".join(filter(None, (_eastmoney_secid(code) for code in chunk)))
        if not secids:
            continue
        url = (
            "https://push2delay.eastmoney.com/api/qt/ulist.np/get"
            "?fltt=2&invt=2&fields=f8,f12,f62,f184&secids=" + secids
        )
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://quote.eastmoney.com/",
            },
        )
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        for item in ((payload.get("data") or {}).get("diff") or []):
            code = str(item.get("f12") or "")
            if not code:
                continue
            result[code] = {
                "turnover_rate": _optional_float(item.get("f8")),
                "main_net_inflow": _optional_float(item.get("f62")),
                "main_net_inflow_pct": _optional_float(item.get("f184")),
                "money_flow_source": "eastmoney",
                "turnover_source": "eastmoney",
            }
    return result


def fetch_stock_market_metrics(codes, use_cache=True):
    normalized = []
    for value in codes or []:
        code = _metric_code(value)
        if code and code not in normalized:
            normalized.append(code)
    if not normalized:
        return {"items": {}, "fetched_at": "", "source": "unavailable"}

    cache_key = tuple(normalized)
    now = time.time()
    if use_cache:
        with _STOCK_METRICS_LOCK:
            cached = _STOCK_METRICS_CACHE.get(cache_key)
            if cached and now - cached["time"] < STOCK_METRICS_TTL:
                return cached["payload"]

    items = {code: _empty_stock_metric() for code in normalized}
    eastmoney_items = {}
    try:
        eastmoney_items = _fetch_eastmoney_stock_metrics(normalized)
    except Exception as exc:
        logger.debug("fetch stock metrics from eastmoney failed: %s", exc)
    for code, metric in eastmoney_items.items():
        if code in items:
            items[code].update(metric)

    missing_turnover = [
        code for code in normalized if items[code]["turnover_rate"] is None
    ]
    tencent_items = {}
    if missing_turnover:
        try:
            from quant.data.tencent_source import fetch_quotes as fetch_tencent_quotes
            tencent_items = fetch_tencent_quotes(missing_turnover)
        except Exception as exc:
            logger.debug("fetch turnover fallback from tencent failed: %s", exc)

    tencent_turnover_used = False
    for code in missing_turnover:
        turnover = _optional_float(
            (tencent_items.get(code) or {}).get("turnover_rate")
        )
        if turnover is not None:
            items[code]["turnover_rate"] = turnover
            items[code]["turnover_source"] = "tencent"
            tencent_turnover_used = True

    payload = {
        "items": items,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": (
            "eastmoney"
            if eastmoney_items
            else ("tencent_turnover" if tencent_turnover_used else "unavailable")
        ),
    }
    if eastmoney_items or tencent_turnover_used:
        with _STOCK_METRICS_LOCK:
            _STOCK_METRICS_CACHE[cache_key] = {"time": now, "payload": payload}
    return payload


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

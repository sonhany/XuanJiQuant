"""全球实时动态采集 — 全球指数/汇率/商品 → AI risk regime 判断

安全设计:
  - 全球动态只能影响风险状态和仓位建议, 不能直接触发买入
  - trade_policy 分级: normal / reduce_only / no_new_position
  - 极端波动时自动收紧

数据源: TdxQuant A股指数主源 + Sina 全球指数兜底 + Jin10 宏观行情 + 板块资金流 + 北向资金
持久化: global:context:latest, global:context:<YYYYMMDD>
"""
import json
import math
import os
import re
import sys
from datetime import datetime
from threading import Lock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache
from scripts import market_sentiment

cache = create_cache()
_GLOBAL_CONTEXT_REFRESH_LOCK = Lock()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _context_ttl_seconds() -> int:
    try:
        value = int(os.getenv("GLOBAL_CONTEXT_TTL_SEC", "1800"))
    except (TypeError, ValueError):
        value = 1800
    return max(60, min(value, 86_400))


def _context_timestamp(value) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        return None


def assess_context_freshness(
    context: dict | None,
    *,
    now: datetime | None = None,
    ttl_sec: int | None = None,
) -> dict:
    """Expire macro conclusions without turning missing data into a low-risk claim."""
    result = dict(context) if isinstance(context, dict) else {}
    current = now or datetime.now()
    if current.tzinfo is not None:
        current = current.astimezone().replace(tzinfo=None)
    ttl = _context_ttl_seconds() if ttl_sec is None else max(1, int(ttl_sec))
    observed_at = _context_timestamp(
        result.get("collected_at") or result.get("generated_at")
    )
    age_seconds = None
    if observed_at is not None:
        age_seconds = max(0, int((current - observed_at).total_seconds()))

    if observed_at is None:
        reason = "macro_context_timestamp_missing"
    elif result.get("stale") is True:
        reason = "macro_context_source_stale"
    elif age_seconds is not None and age_seconds > ttl:
        reason = "macro_context_expired"
    else:
        reason = ""

    stale = bool(reason)
    result["freshness"] = {
        "state": "stale" if stale else "fresh",
        "reason": reason or None,
        "age_seconds": age_seconds,
        "ttl_seconds": ttl,
    }
    result["stale"] = stale
    if stale:
        result["raw_risk_level"] = result.get("risk_level")
        result["raw_trade_policy"] = result.get("trade_policy")
        result["raw_risk_signals"] = list(result.get("risk_signals") or [])[:8]
        result["risk_level"] = "unknown"
        result["trade_policy"] = "no_new_position"
        result["risk_signals"] = []
    return result


_SENTIMENT_REGIMES = {
    "extreme_fear",
    "fear",
    "neutral",
    "greed",
    "extreme_greed",
}
_SENTIMENT_SOURCE_STATUSES = {"live", "stale", "unavailable"}
_SECRET_VALUE_RE = re.compile(
    r"(?i)\b(api[_-]?key|key|token|secret|password)\b\s*[:=]\s*([^&\s,;]+)"
)
_QUERY_VALUE_RE = re.compile(r"([?&][^=\s&]+)=([^&\s]+)")
_URL_WITH_QUERY_RE = re.compile(r"(?i)\b(https?://[^\s?#]+)\?[^\s#]*")


def _sanitize_warning(value) -> str:
    if not isinstance(value, str):
        return ""
    text = _URL_WITH_QUERY_RE.sub(r"\1?<redacted-query>", value.strip())
    text = _QUERY_VALUE_RE.sub(r"\1=<redacted>", text)
    text = _SECRET_VALUE_RE.sub(r"\1=<redacted>", text)
    return " ".join(text.split())[:120]


def _bounded_number(value, *, default: float, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    number = float(value)
    if not math.isfinite(number):
        return default
    return max(minimum, min(maximum, number))


def _sentiment_regime(score: float) -> str:
    if score <= 20:
        return "extreme_fear"
    if score <= 40:
        return "fear"
    if score < 60:
        return "neutral"
    if score < 80:
        return "greed"
    return "extreme_greed"


def _neutral_sentiment(warning: str) -> dict:
    return {
        "sentiment_score": 50.0,
        "sentiment_regime": "neutral",
        "confidence": 0.0,
        "mode": "shadow_only",
        "can_change_trade_policy": False,
        "can_trigger_order": False,
        "sources": [],
        "warnings": [warning],
    }


def _sanitize_sentiment(payload) -> dict:
    if not isinstance(payload, dict):
        return _neutral_sentiment("invalid_sentiment_payload")

    score = _bounded_number(
        payload.get("sentiment_score"),
        default=50.0,
        minimum=0.0,
        maximum=100.0,
    )
    confidence = _bounded_number(
        payload.get("confidence"),
        default=0.0,
        minimum=0.0,
        maximum=1.0,
    )
    raw_regime = payload.get("sentiment_regime")
    regime = (
        raw_regime
        if isinstance(raw_regime, str) and raw_regime in _SENTIMENT_REGIMES
        else _sentiment_regime(score)
    )

    sources = []
    raw_sources = payload.get("sources")
    if isinstance(raw_sources, list):
        for item in raw_sources:
            if not isinstance(item, dict):
                continue
            source = item.get("source")
            status = item.get("status")
            if (
                isinstance(source, str)
                and 0 < len(source.strip()) <= 64
                and isinstance(status, str)
                and status in _SENTIMENT_SOURCE_STATUSES
            ):
                sources.append({"source": source.strip(), "status": status})

    warnings = []
    raw_warnings = payload.get("warnings")
    if isinstance(raw_warnings, list):
        for item in raw_warnings:
            warning = _sanitize_warning(item)
            if warning:
                warnings.append(warning)

    out = {
        "sentiment_score": score,
        "sentiment_regime": regime,
        "confidence": confidence,
        "mode": "shadow_only",
        "can_change_trade_policy": False,
        "can_trigger_order": False,
    }
    if "sources" in payload:
        out["sources"] = sources
    if warnings or "warnings" in payload:
        out["warnings"] = warnings
    if isinstance(payload.get("stale"), bool):
        out["stale"] = payload["stale"]
    return out


def _parse_sina_line(code: str, parts: list) -> dict:
    """按品种解析 Sina 行情 (不同品种字段含义不同, 不能统一解析)。

    格式参考 (实测):
      A股/港股指数 (sh/sz/hk): [0]=名称 [1]=现价 [2]=昨收 → chg=(price/prev-1)*100
      美股 (gb_):   [0]=名称 [1]=现价 [2]=涨跌幅(%) → chg 直接取
      台湾 (b_):    [0]=名称 [1]=现价 [2]=涨跌额 [3]=涨跌幅(%) → chg 取 [3]
      期货 (hf_):   [0]=现价 [2]=昨收 → chg=(price/prev-1)*100
      汇率 (fx_):   [0]=时间 [1]=买入 [2]=卖出 [5]=昨收 → 用 [2]/[5] 算 chg
    """
    if not parts or (len(parts) == 1 and not parts[0]):
        return None  # 空数据 (接口失效)

    def safe_float(v):
        try:
            return float(v) if v and v.strip() else 0
        except (ValueError, TypeError):
            return 0

    name, price, prev_close, chg_pct = code, 0, 0, 0

    if code.startswith(("sh", "sz")):
        # A股指数实时格式(实测): [0]名称 [1]今开 [2]昨收 [3]当前价 [4]高 [5]低
        # 注意: 不能按 [1]=现价 解析, 否则会把开盘价当作最新价, 全球动态显示失真。
        if len(parts) >= 4:
            name = parts[0] or code
            price = safe_float(parts[3])
            prev_close = safe_float(parts[2])
            chg_pct = ((price / prev_close - 1) * 100) if prev_close > 0 else 0
    elif code.startswith("gb_"):
        # 美股: [0]名 [1]现价 [2]=涨跌幅(%)直接给
        if len(parts) >= 3:
            name = parts[0] or code
            price = safe_float(parts[1])
            chg_pct = safe_float(parts[2])  # 已是百分比
            prev_close = price / (1 + chg_pct / 100) if chg_pct else price
    elif code.startswith("b_"):
        # 台湾等: [0]名 [1]现价 [2]涨跌额 [3]涨跌幅(%)
        if len(parts) >= 4:
            name = parts[0] or code
            price = safe_float(parts[1])
            chg_pct = safe_float(parts[3])
            prev_close = price - safe_float(parts[2])
    elif code.startswith("hf_"):
        # 期货: [0]现价 [2]昨收 (无名称, 由调用方汉化)
        if len(parts) >= 3:
            price = safe_float(parts[0])
            prev_close = safe_float(parts[2])
            chg_pct = ((price / prev_close - 1) * 100) if prev_close > 0 else 0
            name = ""
    elif code.startswith("fx_"):
        # 汇率: [0]时间 [1]买入 [2]卖出 [5]昨收 (无名称, 由调用方汉化)
        if len(parts) >= 6:
            price = safe_float(parts[2])  # 卖出价
            prev_close = safe_float(parts[5])
            chg_pct = ((price / prev_close - 1) * 100) if prev_close > 0 else 0
            name = ""
    elif code.startswith("hk_") or code.startswith("rt_"):
        # 港股指数: rt_ 格式 [0]代码 [1]名称 [2]现价 [3]昨收; hk_ 常返回空
        if code.startswith("rt_") and len(parts) >= 4:
            name = parts[1] or parts[0] or code
            price = safe_float(parts[2])
            prev_close = safe_float(parts[3])
            chg_pct = ((price / prev_close - 1) * 100) if prev_close > 0 else 0
        elif len(parts) >= 3:
            name = parts[0] or code
            price = safe_float(parts[1])
            prev_close = safe_float(parts[2])
            chg_pct = ((price / prev_close - 1) * 100) if prev_close > 0 else 0
    else:
        # 兜底: 按 A股格式试
        if len(parts) >= 3:
            name = parts[0] or code
            price = safe_float(parts[1])
            prev_close = safe_float(parts[2])
            chg_pct = ((price / prev_close - 1) * 100) if prev_close > 0 else 0

    return {"name": name, "price": round(price, 4), "close": round(prev_close, 4), "prev_close": round(prev_close, 4), "chg_pct": round(chg_pct, 2)}


def _fetch_sina_indices(codes: list) -> dict:
    """通过 Sina 行情接口获取全球指数/汇率实时数据。

    按品种分别解析 (A股/美股/台湾/期货/汇率字段含义不同)。
    内置 1 次重试 (网络抖动容错): 首次失败 sleep 1s 后重试一次。
    """
    import time
    import urllib.request
    result = {}
    for attempt in range(2):  # 1 次初始 + 1 次重试
        try:
            url = f"http://hq.sinajs.cn/list={','.join(codes)}"
            req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                import re
                lines = resp.read().decode("gbk", errors="replace").split("\n")
                for line in lines:
                    m = re.match(r'var hq_str_(\S+)="(.*)"', line.strip())
                    if m and m.group(2):
                        code = m.group(1)
                        parts = m.group(2).split(",")
                        parsed = _parse_sina_line(code, parts)
                        if parsed:
                            parsed["source"] = "sina"
                            result[code] = parsed
            if result:
                return result  # 成功拿到数据, 不再重试
        except Exception:
            if attempt == 0:
                time.sleep(1)  # 首次失败, 等 1s 重试
                continue
    return result


def _fetch_tdx_indices(codes: list) -> dict:
    """Fetch A-share index quotes through TdxQuant when local TQ is available."""
    tdx_codes = [code for code in codes if str(code).lower().startswith(("sh", "sz"))]
    if not tdx_codes:
        return {}
    try:
        from quant.data.tdx_quant_source import fetch_realtime_quotes

        quotes = fetch_realtime_quotes(tdx_codes)
    except Exception:
        return {}
    out = {}
    for code in tdx_codes:
        q = quotes.get(code)
        if not q:
            continue
        prev_close = q.get("prev_close") or q.get("close") or 0
        out[code] = {
            "name": q.get("name") or code,
            "price": round(float(q.get("price") or 0), 4),
            "close": round(float(prev_close or 0), 4),
            "prev_close": round(float(prev_close or 0), 4),
            "chg_pct": round(float(q.get("chg_pct") or 0), 2),
            "source": "tdx_quant",
            "time": q.get("time") or "",
        }
    return out


# 全球关键标的 Sina 代码 (已验证可用, 2026-07-03 实测)
# 注: Sina 不同品种前缀不同, _parse_sina_line 按前缀分别解析
GLOBAL_INDICES = {
    "A股大盘": ["sh000001", "sz399001", "sz399006", "sh000300"],
    "亚太": ["b_HSI", "rt_hkHSTECH", "b_TWSE", "b_NKY", "b_TPX", "b_KOSPI", "b_KOSDAQ"],   # 恒指/恒生科技/台湾/日韩
    "美股": ["gb_$ndx", "gb_dji"],                 # 纳指100/道指
    "汇率商品": ["hf_CL", "hf_GC", "fx_susdcny"],   # 原油/黄金/离岸人民币
}


JIN10_MACRO_CODES = {
    "XAUUSD": "Spot Gold",
    "USOIL": "WTI Crude Oil",
    "USDCNH": "USD/CNH",
    "USDJPY": "USD/JPY",
}


def _fetch_jin10_macro() -> dict:
    """Fetch Jin10 macro quotes with a short TTL to avoid burning MCP quota."""
    cached = cache.get("global:jin10:macro:latest")
    if cached:
        return cached

    try:
        from scripts.jin10_runner import ResilientJin10MCPClient

        client = ResilientJin10MCPClient.from_env()
        if not client.token:
            return {"enabled": False, "quotes": [], "calendar": [], "error": "JIN10_MCP_BEARER_TOKEN not configured"}

        quotes = []
        for code, fallback_name in JIN10_MACRO_CODES.items():
            result = client.call_tool("get_quote", {"code": code})
            data = (result.get("data") or {}).get("data") or {}
            if not data:
                continue
            close = data.get("close")
            price = close if close not in (None, "") else data.get("price")
            quotes.append({
                "code": data.get("code") or code,
                "name": data.get("name") or fallback_name,
                "price": price or 0,
                "open": data.get("open") or 0,
                "close": close or price or 0,
                "high": data.get("high") or 0,
                "low": data.get("low") or 0,
                "volume": data.get("volume") or 0,
                "chg_pct": data.get("ups_percent") or data.get("chg_pct") or 0,
                "chg_price": data.get("ups_price") or 0,
                "time": data.get("time") or "",
                "source": "jin10_mcp",
            })

        calendar = []
        calendar_result = client.call_tool("list_calendar", {})
        calendar_data = (calendar_result.get("data") or {}).get("data") or []
        if isinstance(calendar_data, list):
            calendar = calendar_data[:10]

        out = {
            "enabled": True,
            "quotes": quotes,
            "calendar": calendar,
            "fetched_at": _now(),
            "source": "jin10_mcp",
        }
        cache.set("global:jin10:macro:latest", out, ttl=90)
        cache.set("global:jin10:latest", out)
        return out
    except Exception as exc:
        cached_latest = cache.get("global:jin10:latest")
        if cached_latest:
            cached_latest = dict(cached_latest)
            cached_latest["stale"] = True
            cached_latest["error"] = str(exc)[:200]
            return cached_latest
        return {"enabled": False, "quotes": [], "calendar": [], "error": str(exc)[:200]}


def assess_market_risk(
    quotes: dict,
    northbound: dict,
    jin10_macro: dict,
) -> dict:
    """Apply directional deterministic guardrails to verified macro quotes."""
    risk_level = "low"
    risk_signals = []

    a_sh = quotes.get("sh000001", {})
    a_chg = abs(float(a_sh.get("chg_pct") or 0))
    if a_chg > 2.0:
        risk_signals.append(f"A股大盘波动{a_chg:.1f}%")
        risk_level = "medium"

    ndx = quotes.get("gb_$ndx", {})
    ndx_chg = float(ndx.get("chg_pct") or 0)
    if ndx_chg <= -3.0:
        risk_signals.append(f"纳斯达克下跌{abs(ndx_chg):.1f}%")
        risk_level = "high"
    elif ndx_chg >= 3.0:
        risk_signals.append(f"纳斯达克上涨{ndx_chg:.1f}%")
        if risk_level == "low":
            risk_level = "medium"

    usdcny = quotes.get("fx_susdcny", {})
    if usdcny and abs(float(usdcny.get("chg_pct") or 0)) > 0.5:
        risk_signals.append(f"人民币汇率波动{float(usdcny['chg_pct']):.2f}%")
        if risk_level == "low":
            risk_level = "medium"

    nb_trend = northbound.get("trend", "")
    nb_flow = northbound.get("northFlow", 0)
    if nb_trend == "strong_outflow" or (
        isinstance(nb_flow, (int, float)) and nb_flow < -50
    ):
        risk_signals.append(f"北向资金净流出{nb_flow}亿")
        if risk_level == "low":
            risk_level = "medium"

    for jq in jin10_macro.get("quotes", []):
        try:
            move = abs(float(jq.get("chg_pct") or 0))
        except (TypeError, ValueError):
            move = 0
        code = str(jq.get("code") or "")
        name = jq.get("name") or code
        if code in ("XAUUSD", "USOIL") and move >= 2.5:
            risk_signals.append(f"Jin10 macro volatility: {name} {move:.2f}%")
            if risk_level == "low":
                risk_level = "medium"
            if move >= 5.0:
                risk_level = "high"
        if code in ("USDCNH", "USDJPY") and move >= 0.7:
            risk_signals.append(f"Jin10 FX volatility: {name} {move:.2f}%")
            if risk_level == "low":
                risk_level = "medium"
            if move >= 1.5:
                risk_level = "high"

    trade_policy = {
        "high": "no_new_position",
        "medium": "reduce_only",
        "low": "normal",
    }[risk_level]
    return {
        "risk_level": risk_level,
        "risk_signals": risk_signals,
        "trade_policy": trade_policy,
    }


def collect_global_context() -> dict:
    """采集全球实时动态, 输出 risk regime。"""
    all_codes = []
    for codes in GLOBAL_INDICES.values():
        all_codes.extend(codes)

    a_share_codes = GLOBAL_INDICES.get("A股大盘", [])
    tdx_quotes = _fetch_tdx_indices(a_share_codes)
    sina_codes = [code for code in all_codes if code not in tdx_quotes]
    quotes = _fetch_sina_indices(sina_codes) if sina_codes else {}
    quotes.update(tdx_quotes)

    try:
        sentiment = _sanitize_sentiment(
            market_sentiment.collect_market_sentiment()
        )
    except Exception:
        sentiment = _neutral_sentiment("sentiment_unavailable:collector_error")

    if not quotes:
        cached = cache.get("global:context:latest") or {}
        if cached:
            cached = dict(cached)
            cached["sentiment"] = sentiment
            cached["stale"] = True
            cached["error"] = "全球行情源暂不可用, 已回退最近一次缓存"
            cache.set("global:context:latest", cached)
            return cached

    # 按类别组织 (商品/汇率类无中文名, 用映射汉化)
    NAME_MAP = {
        "hf_CL": "纽约原油",
        "hf_GC": "纽约黄金",
        "fx_susdcny": "离岸人民币",
    }
    categories = {}
    for cat, codes in GLOBAL_INDICES.items():
        cat_data = []
        for code in codes:
            if code in quotes:
                q = dict(quotes[code])
                if not q.get("name") or q["name"] == code:
                    q["name"] = NAME_MAP.get(code, q.get("name") or code)
                cat_data.append(q)
        categories[cat] = cat_data

    jin10_macro = _fetch_jin10_macro()
    if jin10_macro.get("quotes"):
        categories["Jin10 Macro"] = jin10_macro.get("quotes") or []

    # 读取/刷新市场动态 (板块/北向)。失败时 market_data 内部会回退缓存。
    try:
        from scripts.market_data import fetch_sector_flow, fetch_northbound
        sector_flow = fetch_sector_flow()
        northbound = fetch_northbound()
    except Exception:
        sector_flow = cache.get("market:sector_flow:latest") or []
        northbound = cache.get("market:northbound:latest") or {}

    assessed_risk = assess_market_risk(quotes, northbound, jin10_macro)
    risk_level = assessed_risk["risk_level"]
    risk_signals = assessed_risk["risk_signals"]
    trade_policy = assessed_risk["trade_policy"]

    context = {
        "collected_at": _now(),
        "date": _today(),
        "global_indices": categories,
        "northbound": northbound,
        "sector_flow_top3": sector_flow[:3],
        "jin10": jin10_macro,
        "data_sources": {
            "a_share_indices": "tdx_quant" if tdx_quotes else "sina",
            "global_indices": "sina",
            "macro": jin10_macro.get("source") or ("jin10_mcp" if jin10_macro.get("quotes") else ""),
            "sector_flow": "eastmoney",
            "northbound": "eastmoney",
        },
        "risk_level": risk_level,
        "risk_signals": risk_signals,
        "trade_policy": trade_policy,
        "sentiment": sentiment,
    }

    cache.set("global:context:latest", context)
    cache.set(f"global:context:{_today()}", context)
    return context


def _context_refresh_interval_seconds() -> int:
    try:
        value = int(os.getenv("GLOBAL_CONTEXT_REFRESH_INTERVAL_SEC", "300"))
    except (TypeError, ValueError):
        value = 300
    return max(60, min(value, _context_ttl_seconds()))


def _refresh_global_context_if_due_unlocked(
    *,
    now: datetime | None = None,
    refresh_interval_sec: int | None = None,
) -> dict:
    """Keep the deterministic macro sensor fresh for scheduled research."""
    current = now or datetime.now()
    interval = (
        _context_refresh_interval_seconds()
        if refresh_interval_sec is None
        else max(1, int(refresh_interval_sec))
    )
    latest = cache.get("global:context:latest") or {}
    assessed = assess_context_freshness(latest, now=current)
    freshness = assessed.get("freshness") or {}
    age_seconds = freshness.get("age_seconds")
    if (
        freshness.get("state") == "fresh"
        and isinstance(age_seconds, int)
        and age_seconds <= interval
    ):
        return {
            "status": "cached",
            "fresh": True,
            "collected_at": assessed.get("collected_at"),
            "age_seconds": age_seconds,
            "risk_level": assessed.get("risk_level", "unknown"),
            "trade_policy": assessed.get("trade_policy", "no_new_position"),
            "reason": None,
        }

    try:
        collected = collect_global_context()
    except Exception:
        collected = latest
    refreshed = assess_context_freshness(collected, now=current)
    refreshed_freshness = refreshed.get("freshness") or {}
    fresh = refreshed_freshness.get("state") == "fresh"
    return {
        "status": "refreshed" if fresh else "failed",
        "fresh": fresh,
        "collected_at": refreshed.get("collected_at"),
        "age_seconds": refreshed_freshness.get("age_seconds"),
        "risk_level": refreshed.get("risk_level", "unknown"),
        "trade_policy": refreshed.get("trade_policy", "no_new_position"),
        "reason": refreshed_freshness.get("reason") if not fresh else None,
    }


def refresh_global_context_if_due(
    *,
    now: datetime | None = None,
    refresh_interval_sec: int | None = None,
) -> dict:
    """Serialize deterministic macro refreshes across maintenance threads."""
    with _GLOBAL_CONTEXT_REFRESH_LOCK:
        return _refresh_global_context_if_due_unlocked(
            now=now,
            refresh_interval_sec=refresh_interval_sec,
        )


def get_status() -> dict:
    latest = cache.get("global:context:latest")
    return assess_context_freshness(latest) if latest else {"success": True, "latest": None}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="全球实时动态")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    if args.run:
        out = collect_global_context()
    else:
        out = get_status()
    print(json.dumps({"success": True, "data": out}, ensure_ascii=False, default=str))

"""Data 数据层 API: 股票列表 + Kline 查询 + Redis 状态

所有数据已通过 schema 校验，字段名固定为完整英文小写。
"""
import sys, json, os, math, time, threading, hashlib, logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time as clock_time
from decimal import Decimal, ROUND_HALF_UP

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache
from quant.data.daily_summary import ensure_table, populate_from_kv, summary_count, top_stocks
from quant.data.sync_policy import load_sync_policy
from quant.data.universe import is_supported_trade_universe_code

cache = create_cache()
_SYNC_POLICIES = load_sync_policy()
REALTIME_TOP_TTL = max(1, _SYNC_POLICIES["market_top100"].active_interval_ms // 1000)
REALTIME_TOP_FETCH_WORKERS = 6
REALTIME_TOP_KEY = "market:top_amount:realtime"
REALTIME_TOP_STALE_KEY = "market:top_amount:realtime:stale"
_SNAPSHOT_NAME_CACHE = None
_TOP_REFRESHING = set()
_TOP_REFRESH_LOCK = threading.Lock()
REALTIME_VIEW_TTL = max(1, _SYNC_POLICIES["hot_quotes"].active_interval_ms // 1000)
REALTIME_VIEW_KEY = "market:realtime:view"
REALTIME_VIEW_STALE_KEY = "market:realtime:view:stale"
HOT_SNAPSHOT_KEY = "market:hot:snapshot:latest"
_REALTIME_VIEW_REFRESHING = set()
_REALTIME_VIEW_REFRESH_LOCK = threading.Lock()
logger = logging.getLogger("data_runner")

MARKET_METRIC_FIELDS = (
    "turnover_rate",
    "main_net_inflow",
    "main_net_inflow_pct",
    "money_flow_source",
    "turnover_source",
)


class NpEncoder(json.JSONEncoder):
    def default(self, obj):
        item = getattr(obj, "item", None)
        if callable(item):
            try:
                value = item()
                if isinstance(value, float):
                    return None if (math.isnan(value) or math.isinf(value)) else round(value, 6)
                return value
            except Exception:
                pass
        return str(obj)


def j(data): return json.dumps(data, cls=NpEncoder, ensure_ascii=False)


def _available_stock_codes():
    out = []
    for code in (cache.get('stock:universe') or []):
        c = _normalize_code(str(code))
        if c and is_supported_trade_universe_code(c) and c not in out:
            out.append(c)
    try:
        if ensure_table(cache) and getattr(cache, "_conn", None) is not None:
            with cache._lock:
                rows = cache._conn.execute("SELECT code FROM stock_daily_summary ORDER BY amount DESC").fetchall()
            for (code,) in rows:
                c = _normalize_code(str(code))
                if c and is_supported_trade_universe_code(c) and c not in out:
                    out.append(c)
    except Exception:
        pass
    for key in cache.keys('kline:*:d'):
        parts = str(key).split(':')
        c = _normalize_code(parts[1] if len(parts) >= 3 else '')
        if c and is_supported_trade_universe_code(c) and c not in out:
            out.append(c)
    for key in cache.keys('stock:name:*'):
        c = _normalize_code(str(key).split(':')[-1])
        if c and is_supported_trade_universe_code(c) and c not in out:
            out.append(c)
    return out


def _latest_kline_trade_date(codes=None) -> str:
    latest = ""
    keys = [f"kline:{c}:d" for c in codes] if codes else cache.keys('kline:*:d')
    for key in keys:
        raw = cache.get(key)
        if raw and isinstance(raw, list):
            d = str((raw[-1] or {}).get('date') or '')
            if len(d) == 8 and d.isdigit() and d > latest:
                latest = d
    return latest


def _today_yyyymmdd() -> str:
    return datetime.now().strftime("%Y%m%d")


def _realtime_trade_date(codes=None) -> str:
    """Return the exchange trade date represented by realtime quotes.

    Realtime quote providers may still return cached snapshots on weekends or
    holidays. The market browser should expose the latest A-share trade date,
    not the local machine date, otherwise non-trading-day TOP lists look newer
    than the underlying market data.
    """
    today = _today_yyyymmdd()
    try:
        from scripts.trading_calendar import latest_trade_date
        trade_date = latest_trade_date(today)
    except Exception:
        trade_date = today if datetime.now().weekday() < 5 else (_latest_kline_trade_date(codes) or today)

    latest_kline = _latest_kline_trade_date(codes)
    # During an open trading day the realtime snapshot legitimately belongs to
    # today even though the daily K-line is not expected until after close.
    # The exchange calendar already rolls weekends/holidays back safely.
    return trade_date or latest_kline or today


def _snapshot_name_map():
    global _SNAPSHOT_NAME_CACHE
    if _SNAPSHOT_NAME_CACHE is not None:
        return _SNAPSHOT_NAME_CACHE
    names = {}
    snap = cache.get("factor:snapshot") or {}
    rows = snap.get("rows") if isinstance(snap, dict) else None
    if not rows:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "factor_snapshot_latest.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                rows = (json.load(f) or {}).get("rows") or []
        except Exception:
            rows = []
    for row in rows or []:
        code = _normalize_code(row.get("code"))
        name = str(row.get("name") or "").strip()
        if code and name and name != code:
            names[code] = name
    _SNAPSHOT_NAME_CACHE = names
    return names


def _stock_name(code: str) -> str:
    pure = _normalize_code(code)
    return cache.get(f"stock:name:{pure}") or _snapshot_name_map().get(pure) or pure


def _is_realtime_top_stock(code: str, name: str = "") -> bool:
    pure = _normalize_code(code)
    if not pure:
        return False
    if pure.startswith("399"):
        return False
    n = str(name or "")
    return not any(mark in n for mark in ("指数", "成指", "综指", "创业板指", "科创50"))


def _quote_for_code(quotes: dict, code: str) -> dict:
    pure = _normalize_code(code)
    if not pure or not isinstance(quotes, dict):
        return {}
    for key in (pure, f"sh{pure}", f"sz{pure}", f"{pure}.SH", f"{pure}.SZ"):
        q = quotes.get(key)
        if isinstance(q, dict):
            return q
    return {}


def _now_local() -> datetime:
    return datetime.now()


def _market_phase(value: datetime) -> str:
    if value.weekday() >= 5:
        return "closed"
    hhmm = value.hour * 100 + value.minute
    if 915 <= hhmm < 930:
        return "opening_auction"
    if 930 <= hhmm <= 1130 or 1300 <= hhmm <= 1500:
        return "continuous_auction"
    if 1130 < hhmm < 1300:
        return "midday_break"
    return "closed"


def _quote_datetime(value) -> datetime | None:
    text = str(value or "").strip()
    digits = "".join(character for character in text if character.isdigit())
    if len(digits) >= 14:
        try:
            return datetime.strptime(digits[:14], "%Y%m%d%H%M%S")
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _snapshot_calendar(received_at: datetime) -> tuple[list[str], str]:
    day = received_at.strftime("%Y%m%d")
    iso_day = received_at.strftime("%Y-%m-%d")
    try:
        from scripts.trading_calendar import is_trade_date

        if is_trade_date(day):
            return [iso_day], "project_trading_calendar"
        return [], "project_trading_calendar"
    except Exception:
        if received_at.weekday() < 5:
            return [iso_day], "weekday_fallback"
        return [], "weekday_fallback"


def _board_limit_rate(code: str, name: str) -> Decimal:
    label = str(name or "").upper().replace(" ", "")
    if "ST" in label or "退" in label:
        return Decimal("0.05")
    if code.startswith(("300", "301", "688")):
        return Decimal("0.20")
    if code.startswith(("4", "8")):
        return Decimal("0.30")
    return Decimal("0.10")


def _money_string(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f")


def _derived_market_state(code: str, source: dict, received_at: datetime, market_phase: str) -> dict | None:
    if isinstance(source.get("market"), dict):
        return dict(source["market"])
    previous_close = _safe_float(source.get("prev_close") or source.get("close"))
    if previous_close <= 0:
        return None
    close = Decimal(str(previous_close))
    rate = _board_limit_rate(code, str(source.get("name") or ""))
    price = _safe_float(source.get("price"))
    volume = _safe_int(source.get("volume"))
    suspended = bool(price <= 0 or (market_phase == "continuous_auction" and volume <= 0))
    return {
        "date": received_at.strftime("%Y-%m-%d"),
        "version": f"derived_price_band_{received_at.strftime('%Y%m%d')}",
        "suspended": suspended,
        "lower_limit": _money_string(close * (Decimal("1") - rate)),
        "upper_limit": _money_string(close * (Decimal("1") + rate)),
        "status_source": "quote_activity",
        "price_band_source": "prev_close_board_rule",
    }


def normalize_hot_snapshot(codes, quotes, *, received_at: datetime) -> dict:
    """Normalize one trusted hot quote batch with per-symbol freshness truth."""
    normalized_codes = tuple(
        dict.fromkeys(pure for pure in (_normalize_code(code) for code in codes) if pure)
    )
    stale_after_ms = _SYNC_POLICIES["hot_quotes"].stale_after_ms
    valuation_stale_after_ms = _SYNC_POLICIES["cockpit_account"].stale_after_ms
    current_trade_date = received_at.strftime("%Y%m%d")
    market_phase = _market_phase(received_at)
    calendar, calendar_source = _snapshot_calendar(received_at)
    normalized_quotes = {}
    timestamps = []
    ages = []
    for code in normalized_codes:
        source = dict(_quote_for_code(quotes, code))
        quote_time = _quote_datetime(
            source.get("quote_timestamp") or source.get("timestamp") or source.get("time")
        )
        price = float(source.get("price") or 0)
        age_ms = (
            max(0, int((received_at - quote_time).total_seconds() * 1000))
            if quote_time is not None
            else None
        )
        reason = ""
        if not source:
            reason = "quote_missing"
        elif price <= 0:
            reason = "quote_price_invalid"
        elif quote_time is None:
            reason = "quote_timestamp_missing"
        elif quote_time.strftime("%Y%m%d") != current_trade_date:
            reason = "quote_trade_date_mismatch"
        elif quote_time > received_at and (quote_time - received_at).total_seconds() > 5:
            reason = "quote_timestamp_future"
        session_endpoint = bool(
            quote_time is not None
            and (
                (market_phase == "midday_break" and quote_time.time() >= clock_time(11, 29))
                or (market_phase == "closed" and received_at.time() >= clock_time(15, 0) and quote_time.time() >= clock_time(14, 59))
            )
        )
        if not reason and age_ms is not None and age_ms > stale_after_ms and not session_endpoint:
            reason = "quote_stale"
        valuation_reason = reason
        if (
            valuation_reason == "quote_stale"
            and age_ms is not None
            and age_ms <= valuation_stale_after_ms
        ):
            valuation_reason = ""
        row = {
            **source,
            "code": code,
            "price": price,
            "quote_timestamp": quote_time.strftime("%Y%m%d%H%M%S") if quote_time else "",
            "received_at": received_at.isoformat(timespec="seconds"),
            "market": _derived_market_state(code, source, received_at, market_phase),
            "age_ms": age_ms,
            "stale": bool(reason),
            "stale_reason": reason,
            "valuation_stale": bool(valuation_reason),
            "valuation_stale_reason": valuation_reason,
        }
        normalized_quotes[code] = row
        if quote_time is not None:
            timestamps.append(row["quote_timestamp"])
        if age_ms is not None:
            ages.append(age_ms)
    identity_rows = [
        {
            "code": code,
            "price": normalized_quotes[code]["price"],
            "quote_timestamp": normalized_quotes[code]["quote_timestamp"],
            "source": normalized_quotes[code].get("source") or "",
            "stale": normalized_quotes[code]["stale"],
        }
        for code in sorted(normalized_quotes)
    ]
    identity = json.dumps(identity_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "snapshot_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        "quote_timestamp": max(timestamps, default=""),
        "received_at": received_at.isoformat(timespec="seconds"),
        "market_phase": market_phase,
        "calendar": calendar,
        "calendar_source": calendar_source,
        "quotes": normalized_quotes,
        "stale": any(row["stale"] for row in normalized_quotes.values()) or not normalized_quotes,
        "valuation_stale": any(
            row["valuation_stale"] for row in normalized_quotes.values()
        ) or not normalized_quotes,
        "age_ms": max(ages, default=None),
        "requested": len(normalized_codes),
        "observed": sum(1 for row in normalized_quotes.values() if row.get("price", 0) > 0),
    }


def action_hot_snapshot(req):
    from scripts.market_data import fetch_realtime

    codes = tuple(
        dict.fromkeys(
            pure
            for pure in (_normalize_code(code) for code in (req.get("codes") or []))
            if pure
        )
    )
    data = fetch_realtime(list(codes), use_cache=False) if codes else {}
    snapshot = normalize_hot_snapshot(codes, data, received_at=_now_local())
    cache.set(HOT_SNAPSHOT_KEY, snapshot, ttl=max(60, REALTIME_VIEW_TTL * 10))
    return {"success": True, "data": snapshot}


def complete_top_generation(rows, meta) -> dict:
    ordered = sorted(
        (dict(row) for row in rows),
        key=lambda row: (-float(row.get("amount") or 0), str(row.get("code") or "")),
    )
    requested = max(0, int(meta.get("requested") or len(ordered)))
    observed = max(0, int(meta.get("observed") or len(ordered)))
    coverage = observed / requested if requested else 0.0
    identity_payload = {
        "latest_date": str(meta.get("latest_date") or ""),
        "latest_time": str(meta.get("latest_time") or ""),
        "rows": [
            {
                "code": str(row.get("code") or ""),
                "price": float(row.get("price") or 0),
                "amount": float(row.get("amount") or 0),
            }
            for row in ordered
        ],
    }
    encoded = json.dumps(identity_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "generation_id": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        "complete": bool(requested and coverage >= 0.98),
        "coverage": coverage,
        "requested": requested,
        "observed": observed,
        "refreshing": False,
    }


def _top_cache_key(order_key: str, limit: int) -> str:
    return f"{REALTIME_TOP_KEY}:{order_key}:{limit}"


def _top_stale_cache_key(order_key: str, limit: int) -> str:
    return f"{REALTIME_TOP_STALE_KEY}:{order_key}:{limit}"


def _schedule_top_refresh(sort_by="amount", limit=30):
    order_key = "volume" if sort_by == "volume" else "amount"
    refresh_key = f"{order_key}:{limit}"
    with _TOP_REFRESH_LOCK:
        if refresh_key in _TOP_REFRESHING:
            return False
        _TOP_REFRESHING.add(refresh_key)

    def _worker():
        try:
            _top_realtime_stocks(sort_by=sort_by, limit=limit, bypass_cache=True, allow_stale=False, background_refresh=True)
        finally:
            with _TOP_REFRESH_LOCK:
                _TOP_REFRESHING.discard(refresh_key)

    t = threading.Thread(target=_worker, name=f"top-refresh-{refresh_key}", daemon=True)
    t.start()
    return True


def _quote_volume_shares(q: dict) -> tuple[int, int, str]:
    raw_volume = int(float((q or {}).get("volume") or 0))
    raw_unit = str((q or {}).get("volume_unit") or "").strip().lower()
    if not raw_unit:
        raw_unit = "hand" if str((q or {}).get("source") or "").lower() == "tdx_quant" else "share"
    volume = raw_volume * 100 if raw_unit in ("hand", "hands", "lot", "lots") else raw_volume
    return volume, raw_volume, raw_unit


def _enrich_stock_market_metrics(stocks):
    default_meta = {"source": "unavailable", "fetched_at": "", "available": False}
    if not stocks:
        return default_meta
    try:
        from scripts.market_data import fetch_stock_market_metrics

        payload = fetch_stock_market_metrics(
            [row.get("code") for row in stocks],
            use_cache=True,
        )
        items = payload.get("items") if isinstance(payload, dict) else {}
        items = items if isinstance(items, dict) else {}
        for row in stocks:
            metric = items.get(str(row.get("code") or ""), {})
            for field in MARKET_METRIC_FIELDS:
                row[field] = metric.get(field)
        available = any(
            float(metric.get("turnover_rate") or 0) > 0
            or metric.get("main_net_inflow") is not None
            or metric.get("main_net_inflow_pct") is not None
            for metric in items.values()
            if isinstance(metric, dict)
        )
        if not available:
            for row in stocks:
                for field in MARKET_METRIC_FIELDS:
                    row[field] = None
            return default_meta
        return {
            "source": payload.get("source") or "unavailable",
            "fetched_at": payload.get("fetched_at") or "",
            "available": available,
        }
    except Exception as exc:
        logger.debug("stock market metric enrichment failed: %s", exc)
        for row in stocks:
            for field in MARKET_METRIC_FIELDS:
                row[field] = None
        return default_meta


def _fetch_realtime_quotes_in_batches(
    codes,
    *,
    use_cache=True,
    chunk_size=300,
    max_workers=REALTIME_TOP_FETCH_WORKERS,
):
    """Fetch the full-market snapshot with bounded batch concurrency.

    TdxQuant keeps its own process-level call lock, while the fallback amount
    enrichment performs independent network I/O. Bounded outer concurrency
    lets those waits overlap without changing source priority or provider
    batch limits. A failed batch is isolated so the remaining market snapshot
    can still be ranked.
    """
    from scripts.market_data import fetch_realtime

    size = max(1, int(chunk_size))
    batches = [codes[i:i + size] for i in range(0, len(codes), size)]
    if not batches:
        return {}
    if len(batches) == 1 or int(max_workers) <= 1:
        return fetch_realtime(batches[0], use_cache=use_cache)

    quotes = {}
    worker_count = min(len(batches), max(1, int(max_workers)))
    with ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="market-top",
    ) as executor:
        futures = {
            executor.submit(fetch_realtime, batch, use_cache=use_cache): batch
            for batch in batches
        }
        for future in as_completed(futures):
            try:
                quotes.update(future.result() or {})
            except Exception as exc:
                logger.warning(
                    "realtime market batch failed (%s codes): %s",
                    len(futures[future]),
                    exc,
                )
    return quotes


def _top_realtime_stocks(sort_by="amount", limit=30, bypass_cache=False, allow_stale=False, background_refresh=False):
    order_key = "volume" if sort_by == "volume" else "amount"
    cache_key = _top_cache_key(order_key, limit)
    stale_key = _top_stale_cache_key(order_key, limit)
    cached = cache.get(cache_key)
    if not bypass_cache and cached and isinstance(cached, dict) and cached.get("stocks"):
        return cached

    if allow_stale and not bypass_cache:
        stale = cache.get(stale_key)
        if stale and isinstance(stale, dict) and stale.get("stocks"):
            _schedule_top_refresh(sort_by=sort_by, limit=limit)
            out = dict(stale)
            out["source"] = "realtime_stale"
            out["stale"] = True
            out["refreshing"] = True
            return out

    codes = _available_stock_codes()
    if not codes:
        return None

    try:
        quotes = _fetch_realtime_quotes_in_batches(
            codes,
            use_cache=not bypass_cache,
        )
    except Exception:
        return None

    trade_date = _realtime_trade_date(codes)
    rows = []
    latest_time = ""
    for raw_code, q in (quotes or {}).items():
        pure = _normalize_code(raw_code)
        name = q.get("name") or _stock_name(pure)
        if not _is_realtime_top_stock(pure, name):
            continue
        amount = float(q.get("amount") or 0)
        volume, raw_volume, raw_volume_unit = _quote_volume_shares(q)
        if amount <= 0 and volume <= 0:
            continue
        qt = str(q.get("time") or "")
        if qt > latest_time:
            latest_time = qt
        price_v = float(q.get("price") or 0)
        prev_close_v = float(q.get("prev_close") or q.get("close") or 0)
        high_v = float(q.get("high") or 0)
        low_v = float(q.get("low") or 0)
        # 涨跌额 = 现价 - 前收 (A 股看盘标配)
        change_v = round(price_v - prev_close_v, 3) if prev_close_v else 0.0
        # 振幅(%) = (最高 - 最低) / 前收 * 100
        amplitude_v = round((high_v - low_v) / prev_close_v * 100, 2) if prev_close_v else 0.0
        rows.append({
            "code": pure,
            "name": name,
            "latest_date": trade_date,
            "latest_time": qt,
            "price": price_v,
            "prev_close": prev_close_v,
            "high": high_v,
            "low": low_v,
            "change": change_v,
            "change_pct": round(float(q.get("chg_pct") or 0), 2),
            "amplitude": amplitude_v,
            "volume": volume,
            "volume_unit": "share",
            "raw_volume": raw_volume,
            "raw_volume_unit": raw_volume_unit,
            "amount": amount,
            "amount_source": q.get("amount_source") or "",
            "source": q.get("source") or "realtime",
        })

    if not rows:
        return None
    rows.sort(key=lambda x: float(x.get(order_key) or 0), reverse=True)
    stocks = rows[:limit] if limit > 0 else rows
    market_metrics = _enrich_stock_market_metrics(stocks)
    snapshot_stale = bool(trade_date and trade_date < _today_yyyymmdd())
    out = {
        "count": len(stocks),
        "stocks": stocks,
        "latest_date": trade_date,
        "latest_time": latest_time,
        "source": "realtime_stale" if snapshot_stale else "realtime",
        "stale": snapshot_stale,
        "refreshing": False,
        "ttl_seconds": REALTIME_TOP_TTL,
        "market_metrics": market_metrics,
    }
    out.update(
        complete_top_generation(
            rows,
            {
                "latest_date": trade_date,
                "latest_time": latest_time,
                "requested": len(codes),
                "observed": len(rows),
                "background_refresh": background_refresh,
            },
        )
    )
    cache.set(cache_key, out, ttl=REALTIME_TOP_TTL)
    cache.set(stale_key, out)
    return out


def _top_summary_stocks_with_realtime(sort_by="amount", limit=30):
    if summary_count(cache) == 0:
        populate_from_kv(cache)
    summary = top_stocks(cache, sort_by=sort_by, limit=limit)
    if not summary or not summary.get("stocks"):
        return None

    stocks = summary["stocks"]
    latest_time = ""
    try:
        from scripts.market_data import fetch_realtime

        quotes = fetch_realtime([s["code"] for s in stocks], use_cache=True)
    except Exception:
        quotes = {}

    for item in stocks:
        code = item.get("code")
        q = _quote_for_code(quotes or {}, code)
        bars = cache.get(f"kline:{code}:d") or []
        fallback_price = 0.0
        if bars and isinstance(bars, list):
            try:
                fallback_price = float((bars[-1] or {}).get("close") or 0)
            except Exception:
                fallback_price = 0.0
        if q:
            name = q.get("name") or item.get("name") or _stock_name(code)
            volume, raw_volume, raw_volume_unit = _quote_volume_shares(q)
            price_v = float(q.get("price") or fallback_price or 0)
            prev_close_v = float(q.get("prev_close") or q.get("close") or 0)
            high_v = float(q.get("high") or 0)
            low_v = float(q.get("low") or 0)
            change_v = round(price_v - prev_close_v, 3) if prev_close_v else 0.0
            amplitude_v = round((high_v - low_v) / prev_close_v * 100, 2) if prev_close_v else 0.0
            item["name"] = name
            item["price"] = price_v
            item["prev_close"] = prev_close_v
            item["high"] = high_v
            item["low"] = low_v
            item["change"] = change_v
            item["change_pct"] = round(float(q.get("chg_pct") or 0), 2)
            item["amplitude"] = amplitude_v
            item["volume"] = volume or int(float(item.get("volume") or 0))
            item["volume_unit"] = "share"
            item["raw_volume"] = raw_volume
            item["raw_volume_unit"] = raw_volume_unit
            item["amount"] = float(q.get("amount") or item.get("amount") or 0)
            item["realtime_change_pct"] = item["change_pct"]
            qt = str(q.get("time") or "")
            item["latest_time"] = qt
            item["realtime_source"] = q.get("source") or "realtime"
            if qt > latest_time:
                latest_time = qt
        else:
            item["name"] = item.get("name") or _stock_name(code)
            item["price"] = fallback_price
            item["latest_time"] = ""
    order_key = "volume" if sort_by == "volume" else "amount"
    stocks.sort(key=lambda row: float(row.get(order_key) or 0), reverse=True)
    market_metrics = _enrich_stock_market_metrics(stocks)
    return {
        "count": len(stocks),
        "stocks": stocks,
        "latest_date": summary.get("latest_date") or "",
        "latest_time": latest_time,
        "source": "daily_summary+realtime",
        "market_metrics": market_metrics,
    }


def action_stocks(req=None):
    req = req or {}
    limit = int(req.get('limit', 200))
    sort_by = str(req.get('sort_by') or req.get('sort') or '').lower()
    force_refresh = bool(req.get("force_refresh"))
    refresh_if_stale = bool(req.get("refresh_if_stale"))
    if sort_by in ('volume', 'amount'):
        ranked = _top_realtime_stocks(
            sort_by=sort_by,
            limit=limit,
            bypass_cache=force_refresh,
            allow_stale=refresh_if_stale,
        )
        if ranked and ranked.get("stocks"):
            return {"success": True, "data": ranked}
        if refresh_if_stale and not force_refresh:
            _schedule_top_refresh(sort_by=sort_by, limit=limit)
        ranked = _top_summary_stocks_with_realtime(sort_by=sort_by, limit=limit)
        if ranked and ranked.get("stocks"):
            if refresh_if_stale and not force_refresh:
                ranked["refreshing"] = True
            return {"success": True, "data": ranked}

    universe = cache.get('stock:universe') or []
    if sort_by in ('volume', 'amount'):
        codes = _available_stock_codes()
    else:
        base_codes = [_normalize_code(str(c)) for c in universe]
        base_codes = [c for c in base_codes if c and is_supported_trade_universe_code(c)]
        # 数据重建或精简沙箱中 universe 可能尚未恢复，但 K 线缓存已有可用股票。
        # 默认股票列表应退化到可用 K 线，而不是返回空列表。
        codes = base_codes or _available_stock_codes()
        if limit > 0:
            codes = codes[:limit]
    latest_date = _latest_kline_trade_date(codes) if sort_by in ('volume', 'amount') else ""
    stocks = []
    for code in codes:
        name = _stock_name(code)
        item = {"code": code, "name": name}
        # 尝试从 K 线尾部取涨跌幅
        raw = cache.get(f'kline:{code}:d')
        if raw and isinstance(raw, list) and len(raw) >= 2:
            try:
                last = raw[-1]
                prev = raw[-2]
                item['latest_date'] = str(last.get('date') or '')
                last_c = float(last.get('close', 0) or 0)
                prev_c = float(prev.get('close', 0) or 0)
                pct = ((last_c - prev_c) / prev_c * 100.0) if prev_c else 0.0
                if latest_date and item['latest_date'] != latest_date:
                    item['change_pct'] = 0
                    item['volume'] = 0
                    item['amount'] = 0
                else:
                    item['change_pct'] = round(pct, 2)
                    item['volume'] = int(last.get('volume', 0) or 0)
                    item['amount'] = float(last.get('amount', 0) or 0)
            except Exception:
                item['change_pct'] = 0
                item['volume'] = 0
                item['amount'] = 0
                item['latest_date'] = ''
        else:
            item['change_pct'] = 0
            item['volume'] = 0
            item['amount'] = 0
            item['latest_date'] = ''
        stocks.append(item)
    if sort_by == 'volume':
        stocks.sort(key=lambda x: float(x.get('volume') or 0), reverse=True)
    elif sort_by == 'amount':
        stocks.sort(key=lambda x: float(x.get('amount') or 0), reverse=True)
    if limit > 0:
        stocks = stocks[:limit]
    market_metrics = (
        _enrich_stock_market_metrics(stocks)
        if sort_by in ("volume", "amount")
        else {"source": "unavailable", "fetched_at": "", "available": False}
    )
    return {
        "success": True,
        "data": {
            "count": len(stocks),
            "stocks": stocks,
            "latest_date": latest_date,
            "market_metrics": market_metrics,
        },
    }


def _normalize_code(code: str) -> str:
    c = str(code or "").strip().upper()
    c = c.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
    if c.startswith(("SH", "SZ", "BJ")):
        c = c[2:]
    return c if len(c) == 6 and c.isdigit() else ""


def _financial_json_safe(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {
            str(key): _financial_json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_financial_json_safe(item) for item in value]
    return value


def action_financials(req):
    from quant.data.financial_quality import analyze_financial_history

    raw_code = req.get("code", "")
    code = _normalize_code(raw_code)
    if raw_code and not code:
        return {"success": False, "status": 400, "error": "invalid code"}
    if not code:
        return {"success": False, "status": 400, "error": "code required"}

    suffix = f":{code}"
    keys = sorted(
        key
        for key in cache.keys(f"fin:*:{code}")
        if isinstance(key, str) and key.startswith("fin:") and key.endswith(suffix)
    )
    datasets = {
        key: _financial_json_safe(cache.get(key))
        for key in keys
    }
    history_key = f"fin:abstract:{code}"
    history_value = datasets.get(history_key)
    history = history_value if isinstance(history_value, list) else []
    report_dates = [
        str(row.get("report_date") or row.get("period") or "")
        for row in history
        if isinstance(row, dict)
    ]
    report_dates = [date for date in report_dates if date]
    quality = analyze_financial_history(
        history,
        as_of_date=_today_yyyymmdd(),
    )

    return {
        "success": True,
        "data": {
            "code": code,
            "name": _stock_name(code),
            "keys": keys,
            "datasets": datasets,
            "history": history,
            "history_count": len(history),
            "latest_report_date": max(report_dates, default=""),
            "quality": quality,
        },
    }


def action_klines(req):
    raw_code = req.get("code", "")
    code = _normalize_code(raw_code)
    limit = int(req.get("limit", 300))
    if raw_code and not code:
        return {"success": False, "status": 400, "error": "invalid code"}
    if not code:
        return {"success": False, "status": 400, "error": "code required"}
    name = _stock_name(code)

    # 周期/复权支持: period ∈ {1d(默认), 5m, 15m, 30m, 60m} / fq ∈ {none, qfq, hfq}
    period = str(req.get("period") or "1d").lower()
    fq = str(req.get("fq") or "none").lower()

    # 周期参数映射到 tdx_quant 的 period 格式 (60m 报错, 必须用 1h)
    PERIOD_MAP = {
        "1d": "1d", "daily": "1d", "day": "1d",
        "1m": "1m", "1min": "1m", "minute": "1m",
        "5m": "5m", "5min": "5m",
        "15m": "15m", "15min": "15m",
        "30m": "30m", "30min": "30m",
        "60m": "1h", "60min": "1h", "1h": "1h", "hour": "1h",
        "1w": "1w", "week": "1w", "weekly": "1w",
        "1M": "1M", "month": "1M", "monthly": "1M",
    }
    DIVIDEND_MAP = {"none": "none", "qfq": "front", "hfq": "back", "前复权": "front", "后复权": "back"}

    # 日K + 不复权 + 无 start/end → 走 cache (快路径, 兼容旧逻辑)
    use_cache_fast_path = (period in ("1d", "daily", "day")) and (fq in ("none", "")) and not (req.get("start") or req.get("end"))
    if use_cache_fast_path:
        raw = cache.get(f"kline:{code}:d")
        if not raw:
            return {"success": True, "data": {"code": code, "name": name, "klines": [], "count": 0}}
        rows = raw[-limit:] if limit > 0 else raw
        return {"success": True, "data": {
            "code": code, "name": name, "klines": rows, "count": len(rows),
            "period": "1d", "fq": "none",
            "dateRange": {"from": rows[0]['date'] if rows else '', "to": rows[-1]['date'] if rows else ''}
        }}

    # 慢路径: 多周期 / 复权 → 实时拉取 tdx_quant
    tdx_period = PERIOD_MAP.get(period, "1d")
    tdx_dividend = DIVIDEND_MAP.get(fq, "none")
    try:
        from quant.data.tdx_quant_source import fetch_klines
        rows = fetch_klines(code, count=max(50, limit), period=tdx_period, dividend_type=tdx_dividend)
        if not rows:
            return {"success": True, "data": {"code": code, "name": name, "klines": [], "count": 0, "period": period, "fq": fq}}
        return {"success": True, "data": {
            "code": code, "name": name, "klines": rows, "count": len(rows),
            "period": period, "fq": fq,
            "dateRange": {"from": rows[0].get('date', '') if rows else '', "to": rows[-1].get('date', '') if rows else ''}
        }}
    except Exception as e:
        return {"success": False, "status": 500, "error": f"kline fetch failed: {e}"}


def action_stats(req=None):
    # cache 已统一实现 size()/keys()，无需直连 .client
    from quant.data.source_policy import get_source_policy
    dbsize = cache.size() if hasattr(cache, 'size') else 0
    universe = cache.get('stock:universe') or []
    universe_codes = {
        code for code in (_normalize_code(str(raw)) for raw in universe) if code
    }
    kline_keys = cache.keys("kline:*:d") if hasattr(cache, 'keys') else []
    kline_codes = {
        code
        for code in (
            _normalize_code(str(key).split(':')[1])
            for key in kline_keys
            if len(str(key).split(':')) >= 3
        )
        if code
    }
    covered_codes = kline_codes & universe_codes
    extra_codes = sorted(kline_codes - universe_codes)
    return {"success": True, "data": {
        "dbsize": int(dbsize),
        "kline_count": len(covered_codes),
        "kline_total_count": len(kline_codes),
        "kline_extra_count": len(extra_codes),
        "kline_extra_codes": extra_codes[:100],
        "universe_size": len(universe_codes),
        "source_policy": get_source_policy(),
    }}


# ── 统一行情数据 actions (委托给 market_data 模块) ────────
def _realtime_view_codes(codes):
    out = []
    for raw in codes or []:
        code = str(raw or "").strip().lower().replace(".sh", "").replace(".sz", "")
        if not code:
            continue
        if not code.startswith(("sh", "sz")) and len(code) == 6 and code.isdigit():
            code = ("sh" if code[0] in ("5", "6", "9") else "sz") + code
        if code not in out:
            out.append(code)
    return out


def _realtime_view_id(codes):
    raw = ",".join(sorted(_realtime_view_codes(codes)))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _realtime_view_cache_key(codes, stale=False):
    prefix = REALTIME_VIEW_STALE_KEY if stale else REALTIME_VIEW_KEY
    return f"{prefix}:{_realtime_view_id(codes)}"


def _realtime_view_fallback(codes):
    from quant.data.source_policy import realtime_cache_key

    out = {}
    for code in _realtime_view_codes(codes):
        quote = cache.get(realtime_cache_key(code))
        if isinstance(quote, dict) and float(quote.get("price") or 0) > 0:
            out[code] = quote
            continue

        pure = _normalize_code(code)
        bars = cache.get(f"kline:{pure}:d") or []
        if not isinstance(bars, list) or not bars:
            continue
        latest = bars[-1] or {}
        previous = bars[-2] if len(bars) > 1 else latest
        price = float(latest.get("close") or latest.get("c") or 0)
        prev_close = float(previous.get("close") or previous.get("c") or price)
        if price <= 0:
            continue
        out[code] = {
            "name": _stock_name(pure),
            "open": float(latest.get("open") or latest.get("o") or price),
            "close": prev_close,
            "price": price,
            "high": float(latest.get("high") or latest.get("h") or price),
            "low": float(latest.get("low") or latest.get("l") or price),
            "volume": int(float(latest.get("volume") or latest.get("v") or 0)),
            "amount": float(latest.get("amount") or 0),
            "chg_pct": round((price / prev_close - 1) * 100, 2) if prev_close > 0 else 0,
            "time": str(latest.get("date") or latest.get("d") or ""),
            "source": "local_kline_snapshot",
            "stale": True,
        }
    return out


def _schedule_realtime_view_refresh(codes):
    normalized = _realtime_view_codes(codes)
    refresh_key = _realtime_view_id(normalized)
    with _REALTIME_VIEW_REFRESH_LOCK:
        if refresh_key in _REALTIME_VIEW_REFRESHING:
            return False
        _REALTIME_VIEW_REFRESHING.add(refresh_key)

    def _worker():
        try:
            from scripts.market_data import fetch_realtime
            data = fetch_realtime(normalized, use_cache=False)
            if data:
                payload = {"data": data, "updated_at": time.time()}
                cache.set(_realtime_view_cache_key(normalized), payload, ttl=REALTIME_VIEW_TTL)
                cache.set(_realtime_view_cache_key(normalized, stale=True), payload)
        finally:
            with _REALTIME_VIEW_REFRESH_LOCK:
                _REALTIME_VIEW_REFRESHING.discard(refresh_key)

    thread = threading.Thread(
        target=_worker,
        name=f"realtime-view-refresh-{refresh_key}",
        daemon=True,
    )
    thread.start()
    return True


def action_realtime_prices(req):
    """实时行情 — 委托 market_data.fetch_realtime。"""
    from scripts.market_data import fetch_realtime
    codes = _realtime_view_codes(req.get("codes") or [])
    force_refresh = bool(req.get("force_refresh"))
    refresh_if_stale = bool(req.get("refresh_if_stale"))
    if refresh_if_stale and not force_refresh:
        fresh = cache.get(_realtime_view_cache_key(codes)) or {}
        if isinstance(fresh, dict) and isinstance(fresh.get("data"), dict) and fresh["data"]:
            return {
                "success": True,
                "data": fresh["data"],
                "stale": False,
                "refreshing": False,
                "updated_at": fresh.get("updated_at"),
            }

        stale = cache.get(_realtime_view_cache_key(codes, stale=True)) or {}
        data = stale.get("data") if isinstance(stale, dict) else None
        if not isinstance(data, dict) or not data:
            data = _realtime_view_fallback(codes)
        scheduled = _schedule_realtime_view_refresh(codes)
        return {
            "success": True,
            "data": data,
            "stale": True,
            "refreshing": scheduled or _realtime_view_id(codes) in _REALTIME_VIEW_REFRESHING,
            "updated_at": stale.get("updated_at") if isinstance(stale, dict) else None,
        }

    data = fetch_realtime(codes, use_cache=not force_refresh)
    return {"success": True, "data": data}


def action_indices(req=None):
    """全球指数 + 风险等级 — 默认读取后台维护快照。"""
    from scripts.market_data import fetch_indices
    request = req if isinstance(req, dict) else {}
    data = fetch_indices(force_refresh=request.get("force_refresh") is True)
    return {"success": True, "data": data}


def action_sector_flow(req=None):
    """板块资金流 — 委托 market_data.fetch_sector_flow。"""
    from scripts.market_data import fetch_sector_flow
    data = fetch_sector_flow()
    return {"success": True, "data": data}


def action_northbound(req=None):
    """北向资金 — 委托 market_data.fetch_northbound。"""
    from scripts.market_data import fetch_northbound
    data = fetch_northbound()
    return {"success": True, "data": data}


def action_tdx_quant_test(req=None):
    """Diagnose local TdxQuant data source with small read-only sample calls."""
    req = req or {}
    codes = req.get("codes") or ["600519", "000001"]
    if isinstance(codes, str):
        codes = [x.strip() for x in codes.split(",") if x.strip()]
    codes = [_normalize_code(c) for c in codes]
    codes = [c for c in codes if c][:5]
    sample = codes[0] if codes else "600519"
    index_codes = req.get("index_codes") or ["sh000001", "sz399001", "sz399006", "sh000300", "sh000905", "sh000688"]
    if isinstance(index_codes, str):
        index_codes = [x.strip() for x in index_codes.split(",") if x.strip()]
    index_codes = [str(c or "").strip().lower() for c in index_codes if str(c or "").strip()][:8]

    from quant.data import tdx_quant_source as tdx

    health = tdx.health_check(sample)
    out = {
        "health": health,
        "codes": codes,
        "index_codes": index_codes,
        "capabilities": {
            "realtime_stock": {"available": False, "method": "get_pricevol"},
            "realtime_index": {"available": False, "method": "get_pricevol"},
            "snapshot_order_book": {"available": False, "method": "get_market_snapshot"},
            "daily_kline": {"available": False, "method": "get_market_data", "period": str(req.get("period") or "1d")},
            "tick": {"available": False, "method": "get_market_data", "period": "tick"},
            "stock_info": {"available": False, "method": "get_stock_info"},
        },
        "quotes": {},
        "index_quotes": {},
        "snapshot": {},
        "klines": {"code": sample, "rows": [], "count": 0},
        "stock_info": {},
        "tick_probe": {},
    }
    if not health.get("available"):
        return {"success": False, "status": 503, "data": out, "error": health.get("error") or "tdx_quant unavailable"}

    try:
        out["quotes"] = tdx.fetch_quotes(codes)
        out["capabilities"]["realtime_stock"]["available"] = bool(out["quotes"])
    except Exception as exc:
        out["capabilities"]["realtime_stock"]["error"] = str(exc)[:240]

    try:
        out["index_quotes"] = tdx.fetch_realtime_quotes(index_codes)
        out["capabilities"]["realtime_index"]["available"] = bool(out["index_quotes"])
    except Exception as exc:
        out["capabilities"]["realtime_index"]["error"] = str(exc)[:240]

    try:
        out["snapshot"] = tdx.fetch_snapshot(sample)
        out["capabilities"]["snapshot_order_book"]["available"] = bool(out["snapshot"])
    except Exception as exc:
        out["capabilities"]["snapshot_order_book"]["error"] = str(exc)[:240]

    try:
        bars = tdx.fetch_klines(sample, count=int(req.get("kline_count") or 5), period=str(req.get("period") or "1d"))
        out["klines"] = {"code": sample, "rows": bars, "count": len(bars)}
        out["capabilities"]["daily_kline"]["available"] = bool(bars)
    except Exception as exc:
        out["capabilities"]["daily_kline"]["error"] = str(exc)[:240]

    try:
        info = tdx.fetch_stock_info(sample, field_list=[])
        out["stock_info"] = {
            "code": sample,
            "name": info.get("Name") or sample,
            "start": info.get("J_start"),
            "eps": info.get("J_mgsy"),
            "total_capital": info.get("J_zgb"),
            "error_id": info.get("ErrorId"),
        }
        out["capabilities"]["stock_info"]["available"] = bool(info)
    except Exception as exc:
        out["capabilities"]["stock_info"]["error"] = str(exc)[:240]

    try:
        tick_probe = tdx.diagnose_ticks(sample, count=int(req.get("tick_count") or 20))
        out["tick_probe"] = tick_probe
        out["capabilities"]["tick"]["available"] = bool(tick_probe.get("fetched_count", 0) > 0)
        out["capabilities"]["tick"]["reason"] = tick_probe.get("likely_reason")
    except Exception as exc:
        out["capabilities"]["tick"]["error"] = str(exc)[:240]
    return {"success": True, "data": out}


def action_tick_collect(req):
    """Collect true transaction ticks first; use snapshot rows only as fallback."""
    from quant.data.tdx_quant_source import fetch_tick_snapshot
    from quant.data import tdx_quant_source, tdxrs_tick_source
    from quant.data.tick_store import latest_ticks, store_ticks, tick_microstructure

    codes = req.get("codes") or []
    if req.get("code"):
        codes = [req.get("code")]
    if isinstance(codes, str):
        codes = [x.strip() for x in codes.split(",") if x.strip()]
    codes = [_normalize_code(c) for c in codes]
    codes = [c for c in codes if c]
    codes = list(dict.fromkeys(codes))[:20]
    if not codes:
        return {"success": False, "status": 400, "error": "code or codes required"}

    count = max(1, min(int(req.get("count") or 200), 2000))
    start_time = str(req.get("start_time") or "")
    end_time = str(req.get("end_time") or "")
    snapshot_fallback = req.get("snapshot_fallback", True) is not False
    out = {}
    total_written = 0
    errors = []
    for code in codes:
        try:
            ticks = []
            fallback = ""
            source = "tdxrs_transaction"
            source_errors = []
            try:
                ticks = tdxrs_tick_source.fetch_ticks(code, count=min(count, 500))
            except Exception as exc:
                source_errors.append({"source": "tdxrs_transaction", "error": str(exc)[:240]})
            if not ticks:
                try:
                    ticks = tdx_quant_source.fetch_ticks(code, count=count, start_time=start_time, end_time=end_time)
                    source = str((ticks[0] or {}).get("source") or "tdx_quant") if ticks else "tdx_quant"
                except Exception as exc:
                    source_errors.append({"source": "tdx_quant", "error": str(exc)[:240]})
            if not ticks and snapshot_fallback:
                snapshot_tick = fetch_tick_snapshot(code)
                if snapshot_tick:
                    ticks = [snapshot_tick]
                    fallback = "tdx_quant_snapshot"
                    source = "tdx_quant_snapshot"
            written = store_ticks(cache, code, ticks)
            total_written += written
            latest = latest_ticks(cache, code, limit=min(count, 200))
            out[code] = {
                "fetched": len(ticks),
                "written": written,
                "latest": latest,
                "stats": tick_microstructure(cache, code, limit=min(count, 500)),
                "source": str((ticks[0] or {}).get("source") or source) if ticks else source,
                "fallback": fallback,
                "source_errors": source_errors,
            }
        except Exception as exc:
            errors.append({"code": code, "error": str(exc)[:240]})
            out[code] = {"fetched": 0, "written": 0, "latest": [], "stats": {}, "source": "tdxrs_transaction", "error": str(exc)[:240]}
    return {
        "success": not errors or bool(out),
        "data": {
            "codes": codes,
            "count": count,
            "total_written": total_written,
            "items": out,
            "errors": errors,
            "note": "True transaction ticks prefer tdxrs get_transaction_data and are stored as tdxrs_transaction. TdxQuant snapshot rows are only used as an explicitly marked tdx_quant_snapshot fallback.",
        },
    }


def action_tick_probe(req):
    """Diagnose current TdxQuant Tick availability for one code."""
    from quant.data.tdx_quant_source import diagnose_ticks

    code = _normalize_code(req.get("code") or "600519")
    if not code:
        return {"success": False, "status": 400, "error": "valid code required"}
    count = max(1, min(int(req.get("count") or 200), 2000))
    try:
        data = diagnose_ticks(code, count=count)
        return {"success": True, "data": data}
    except Exception as exc:
        return {"success": False, "status": 503, "error": str(exc)[:300], "data": {"code": code}}


def action_tick_collect_full_day(req):
    """Backfill one stock's current-day transaction ticks with tdxrs pagination."""
    from quant.data import tdxrs_tick_source
    from quant.data.tick_store import day_ticks, delete_day_ticks, store_ticks, tick_day_microstructure, tick_day_summary

    code = _normalize_code(req.get("code"))
    if not code:
        return {"success": False, "status": 400, "error": "code required"}
    page_size = max(20, min(int(req.get("page_size") or 500), 500))
    max_pages = max(1, min(int(req.get("max_pages") or 80), 200))
    display_limit = max(100, min(int(req.get("display_limit") or req.get("limit") or 20000), 50000))

    def build_response(fetched, written=0, source_error=""):
        day = tick_day_summary(cache, code, fetched.get("trade_date"))
        rows = day_ticks(cache, code, trade_date=day.get("trade_date") or fetched.get("trade_date"), limit=display_limit)
        stats = tick_day_microstructure(cache, code, trade_date=day.get("trade_date") or fetched.get("trade_date"), limit=display_limit)
        storage_complete = bool(
            int(day.get("count") or 0) > 0
            and str(day.get("first_time") or "") <= "09:30:00"
            and str(day.get("last_time") or "") >= "15:00:00"
        )
        return {
            "success": True,
            "data": {
                "code": code,
                "trade_date": fetched.get("trade_date") or day.get("trade_date") or "",
                "fetched": int(fetched.get("fetched") or 0),
                "written": written,
                "stored_count": int(day.get("count") or 0),
                "first_time": day.get("first_time") or fetched.get("first_time") or "",
                "last_time": day.get("last_time") or fetched.get("last_time") or "",
                "pages": int(fetched.get("pages") or 0),
                "page_size": page_size,
                "complete": bool(fetched.get("complete")) or storage_complete,
                "source": fetched.get("source") or "tdxrs_transaction",
                "source_error": source_error,
                "from_cache": bool(source_error),
                "display_limit": display_limit,
                "ticks": rows,
                "day_summary": day,
                "stats": stats,
                "order_book": _snapshot_order_book(code),
            },
        }

    try:
        fetched = tdxrs_tick_source.fetch_full_day_ticks(code, page_size=page_size, max_pages=max_pages)
        ticks = fetched.get("ticks") or []
        if ticks:
            trade_date = fetched.get("trade_date") or ticks[0].get("date") or ""
            delete_day_ticks(cache, code, trade_date)
        written = store_ticks(cache, code, ticks)
        fetched["fetched"] = int(fetched.get("fetched") or len(ticks))
        return build_response(fetched, written=written)
    except Exception as exc:
        fallback = build_response({"source": "tdxrs_transaction"}, written=0, source_error=str(exc)[:300])
        if fallback["data"]["stored_count"] > 0:
            return fallback
        return {"success": False, "status": 503, "error": str(exc)[:300], "data": {"code": code}}


def _safe_float(value, default=0.0):
    try:
        return float(value) if value not in (None, "") else default
    except Exception:
        return default


def _safe_int(value, default=0):
    try:
        return int(float(value)) if value not in (None, "") else default
    except Exception:
        return default


def _snapshot_order_book(code: str) -> dict:
    """Build a visible bid/ask ladder from TdxQuant snapshot arrays.

    TdxQuant exposes snapshot-level bid/ask ladders, not the full exchange L2
    order queue. Volumes are returned in hands and normalized to shares.
    """
    try:
        from quant.data import tdx_quant_source

        snap = tdx_quant_source.fetch_snapshot(code)
        bid_prices = snap.get("bid_prices") or []
        bid_volumes = snap.get("bid_volumes") or []
        ask_prices = snap.get("ask_prices") or []
        ask_volumes = snap.get("ask_volumes") or []
        bids = []
        asks = []
        for i in range(5):
            price = bid_prices[i] if i < len(bid_prices) else 0
            px = _safe_float(price)
            vol = _safe_int(bid_volumes[i] if i < len(bid_volumes) else 0) * 100
            bids.append({"level": i + 1, "price": px, "volume": vol})
        for i in range(5):
            price = ask_prices[i] if i < len(ask_prices) else 0
            px = _safe_float(price)
            vol = _safe_int(ask_volumes[i] if i < len(ask_volumes) else 0) * 100
            asks.append({"level": i + 1, "price": px, "volume": vol})
        return {
            "code": _normalize_code(code),
            "bids": bids,
            "asks": asks,
            "source": "tdx_quant_snapshot",
            "note": "snapshot bid/ask ladder; not full L2 order queue",
        }
    except Exception as exc:
        return {
            "code": _normalize_code(code),
            "bids": [],
            "asks": [],
            "source": "unavailable",
            "error": str(exc)[:240],
        }


def action_ticks(req):
    """Read persisted ticks; optionally fetch first when force_refresh is true."""
    from quant.data.tick_store import latest_ticks, tick_microstructure, tick_day_microstructure

    code = _normalize_code(req.get("code"))
    if not code:
        return {"success": False, "status": 400, "error": "code required"}
    limit = max(1, min(int(req.get("limit") or req.get("count") or 200), 2000))
    trade_date = str(req.get("trade_date") or "").replace("-", "")[:8]
    if req.get("force_refresh"):
        collected = action_tick_collect({**req, "code": code, "count": limit})
        rows = ((collected.get("data") or {}).get("items") or {}).get(code, {}).get("latest") or []
        if trade_date:
            rows = latest_ticks(cache, code, limit=limit, trade_date=trade_date)
            stats = tick_day_microstructure(cache, code, trade_date=trade_date, limit=limit)
        else:
            stats = ((collected.get("data") or {}).get("items") or {}).get(code, {}).get("stats") or tick_microstructure(cache, code, limit=limit)
        return {"success": True, "data": {"code": code, "ticks": rows, "count": len(rows), "stats": stats, "order_book": _snapshot_order_book(code), "source": stats.get("source") or "sqlite", "collect": collected.get("data")}}
    rows = latest_ticks(cache, code, limit=limit, trade_date=trade_date)
    stats = tick_day_microstructure(cache, code, trade_date=trade_date, limit=limit) if trade_date else tick_microstructure(cache, code, limit=limit)
    return {"success": True, "data": {"code": code, "ticks": rows, "count": len(rows), "stats": stats, "order_book": _snapshot_order_book(code), "source": "sqlite", "trade_date": trade_date or stats.get("trade_date") or ""}}


WATCHLIST_KEY = "watchlist:default"
DEFAULT_WATCHLIST = ['000001','600519','600036','000858','300750','601318','600276','000333','601398','600030','601166','002594','000651','600887','601012','002475']


def _normalize_watch_code(code: str) -> str:
    """统一自选股代码为 6 位数字。支持 sh600519 / 600519.SH / 000001.SZ。"""
    c = str(code or "").strip().upper()
    c = c.replace(".SH", "").replace(".SZ", "")
    if c.startswith(("SH", "SZ")):
        c = c[2:]
    return c if len(c) == 6 and c.isdigit() else ""


def _load_watchlist() -> list:
    arr = cache.get(WATCHLIST_KEY)
    if isinstance(arr, list) and arr:
        source = arr
    else:
        source = DEFAULT_WATCHLIST
    out = []
    for code in list(source):
        c = _normalize_watch_code(code)
        if c and c not in out:
            out.append(c)
    cache.set(WATCHLIST_KEY, out)
    return out


def action_watchlist_get(req=None):
    return {"success": True, "data": {"codes": _load_watchlist()}}


def action_watchlist_set(req):
    raw = req.get("codes") or []
    if not isinstance(raw, list):
        return {"success": False, "error": "codes must be list"}
    codes = []
    for item in list(raw):
        c = _normalize_watch_code(item)
        if c and c not in codes:
            codes.append(c)
    if not codes:
        codes = list(DEFAULT_WATCHLIST)
    cache.set(WATCHLIST_KEY, codes)
    return {"success": True, "data": {"codes": codes}}


def action_watchlist_add(req):
    code = _normalize_watch_code(req.get("code"))
    if not code:
        return {"success": False, "error": "请输入合法的6位A股代码"}
    codes = _load_watchlist()
    if code not in codes:
        codes.append(code)
        cache.set(WATCHLIST_KEY, codes)
    return {"success": True, "data": {"codes": codes}}


def action_watchlist_remove(req):
    code = _normalize_watch_code(req.get("code"))
    if not code:
        return {"success": False, "error": "code required"}
    codes = [c for c in _load_watchlist() if c != code]
    cache.set(WATCHLIST_KEY, codes)
    return {"success": True, "data": {"codes": codes}}


def action_watchlist_reset(req=None):
    cache.set(WATCHLIST_KEY, DEFAULT_WATCHLIST)
    return {"success": True, "data": {"codes": DEFAULT_WATCHLIST}}


ACTIONS = {
    "stocks": action_stocks,
    "klines": action_klines,
    "financials": action_financials,
    "stats": action_stats,
    "realtime_prices": action_realtime_prices,
    "hot_snapshot": action_hot_snapshot,
    "indices": action_indices,
    "sector_flow": action_sector_flow,
    "northbound": action_northbound,
    "tdx_quant_test": action_tdx_quant_test,
    "ticks": action_ticks,
    "tick_collect": action_tick_collect,
    "tick_collect_full_day": action_tick_collect_full_day,
    "tick_probe": action_tick_probe,
    "watchlist_get": action_watchlist_get,
    "watchlist_set": action_watchlist_set,
    "watchlist_add": action_watchlist_add,
    "watchlist_remove": action_watchlist_remove,
    "watchlist_reset": action_watchlist_reset,
}

if __name__ == "__main__":
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            print(j({"success": False, "error": "invalid JSON"}))
            sys.stdout.flush()
            continue
        req_id = req.get("__id")
        action = req.get("action", "stats")
        handler = ACTIONS.get(action)
        if not handler:
            out = {"success": False, "error": f"unknown action: {action}"}
            if req_id: out["__id"] = req_id
            print(j(out))
            sys.stdout.flush()
            continue
        try:
            out = handler(req)
            if req_id and isinstance(out, dict): out["__id"] = req_id
            print(j(out))
        except Exception as e:
            import traceback
            traceback.print_exc()
            out = {"success": False, "error": str(e)[:500]}
            if req_id: out["__id"] = req_id
            print(j(out))
        sys.stdout.flush()

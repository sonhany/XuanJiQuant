from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal, DecimalException, ROUND_HALF_EVEN, localcontext
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from quant.data.cache import create_cache


cache = create_cache()

VIX_ANCHORS = [
    (12.0, 90.0),
    (15.0, 75.0),
    (20.0, 50.0),
    (30.0, 25.0),
    (40.0, 10.0),
]
NFCI_ANCHORS = [
    (-0.8, 85.0),
    (-0.3, 65.0),
    (0.0, 50.0),
    (0.5, 25.0),
    (1.0, 10.0),
]
CFFEX_BASIS_ANCHORS = [
    (Decimal("-2"), Decimal("10")),
    (Decimal("-1"), Decimal("25")),
    (Decimal("0"), Decimal("50")),
    (Decimal("1"), Decimal("75")),
    (Decimal("2"), Decimal("90")),
]
CBOE_VIX_URL = (
    "https://cdn.cboe.com/api/global/us_indices/daily_prices/"
    "VIX_History.csv"
)
FRED_OBSERVATIONS_URL = (
    "https://api.stlouisfed.org/fred/series/observations"
)
HKEX_DAILY_URL = (
    "https://www.hkex.com.hk/eng/csm/DailyStat/"
    "data_tab_daily_{date}e.js"
)
HTTP_USER_AGENT = "XuanJiQuant/market-sentiment"
HTTP_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
TWO_PLACES = Decimal("0.01")
THREE_PLACES = Decimal("0.001")


def _normalize_now(value: datetime | None = None) -> datetime:
    if value is None:
        return datetime.now(SHANGHAI_TZ)
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI_TZ)
    return value.astimezone(SHANGHAI_TZ)


def _now() -> str:
    return _normalize_now().strftime("%Y-%m-%d %H:%M:%S")


def _interpolate(
    value: float,
    anchors: list[tuple[float, float]],
) -> float:
    value = float(value)
    if not isfinite(value):
        raise ValueError("value must be finite")
    if value <= anchors[0][0]:
        return anchors[0][1]
    if value >= anchors[-1][0]:
        return anchors[-1][1]

    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
        if x0 <= value <= x1:
            ratio = (value - x0) / (x1 - x0)
            return round(y0 + ratio * (y1 - y0), 2)

    return 50.0


def score_vix(value: float) -> float:
    return _interpolate(value, VIX_ANCHORS)


def score_nfci(value: float) -> float:
    return _interpolate(value, NFCI_ANCHORS)


def _regime(score: Decimal) -> str:
    if score <= 20:
        return "extreme_fear"
    if score <= 40:
        return "fear"
    if score < 60:
        return "neutral"
    if score < 80:
        return "greed"
    return "extreme_greed"


def _is_valid_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return isfinite(float(value))
    except OverflowError:
        return False


def _validated_components(
    inputs: dict[str, dict[str, Any]],
) -> list[tuple[Decimal, Decimal, bool]]:
    components = []
    for item in inputs.values():
        if not isinstance(item, dict) or item.get("available") is not True:
            continue

        stale = item.get("stale")
        if type(stale) is not bool:
            continue

        score = item.get("score")
        weight = item.get("weight")
        if not _is_valid_number(score) or not _is_valid_number(weight):
            continue

        numeric_score = Decimal(str(score))
        numeric_weight = Decimal(str(weight))
        if (
            not Decimal("0") <= numeric_score <= Decimal("100")
            or numeric_weight <= Decimal("0")
        ):
            continue

        components.append((
            numeric_score,
            numeric_weight,
            stale,
        ))
    return components


def _quantize_two_places(value: Decimal) -> Decimal:
    integer_digits = max(1, value.adjusted() + 1)
    with localcontext() as context:
        context.prec = max(28, integer_digits + 2)
        return value.quantize(TWO_PLACES, rounding=ROUND_HALF_EVEN)


def score_market_sentiment(
    inputs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    available = _validated_components(inputs)
    if not available:
        return {
            "generated_at": _now(),
            "sentiment_score": 50.0,
            "sentiment_regime": "neutral",
            "confidence": 0.0,
            "mode": "shadow_only",
            "can_change_trade_policy": False,
            "can_trigger_order": False,
            "stale": False,
            "warnings": ["official_sources_unavailable"],
        }

    denominator = sum(
        (weight for _, weight, _ in available),
        Decimal("0"),
    )
    score = sum(
        component_score * weight
        for component_score, weight, _ in available
    ) / denominator
    confidence = sum(
        weight * (Decimal("0.5") if stale else Decimal("1"))
        for _, weight, stale in available
    ) / Decimal("100")
    normalized_score = _quantize_two_places(score)
    normalized_confidence = _quantize_two_places(confidence)
    normalized_confidence = max(
        Decimal("0"),
        min(Decimal("1"), normalized_confidence),
    )

    return {
        "generated_at": _now(),
        "sentiment_score": float(normalized_score),
        "sentiment_regime": _regime(normalized_score),
        "confidence": float(normalized_confidence),
        "mode": "shadow_only",
        "can_change_trade_policy": False,
        "can_trigger_order": False,
        "stale": any(stale for _, _, stale in available),
        "warnings": [],
    }


def _safe_reason(
    error: BaseException | str,
    *,
    secrets: tuple[str, ...] = (),
) -> str:
    text = str(error)
    text = re.sub(r"https?://[^\s'\"<>]+", "<redacted-url>", text)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "<redacted>")
    text = re.sub(
        r"(?i)(?:api[_-]?key|token|access[_-]?token|secret)"
        r"\s*=\s*[^&\s,;]+",
        "<redacted-query>",
        text,
    )
    return text[:160]


def _http_get_text(url: str) -> str:
    last_error: BaseException | None = None
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.netloc
    ):
        raise RuntimeError("unsupported_HTTP_URL")
    query_secrets = tuple(
        value
        for _, value in urllib.parse.parse_qsl(
            parsed.query,
            keep_blank_values=True,
        )
        if value
    )
    for attempt in range(2):
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": HTTP_USER_AGENT},
            )
            with urllib.request.urlopen(request, timeout=8) as response:
                body = response.read(HTTP_MAX_RESPONSE_BYTES + 1)
                if len(body) > HTTP_MAX_RESPONSE_BYTES:
                    raise RuntimeError("HTTP_response_too_large")
                return body.decode("utf-8", errors="replace")
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(0.5)
    raise RuntimeError(
        _safe_reason(last_error or "HTTP request failed", secrets=query_secrets),
    )


def _number(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("numeric value required")
    number = float(str(value).replace(",", "").strip())
    if not isfinite(number):
        raise ValueError("finite numeric value required")
    return number


def _decimal_number(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("numeric value required")
    number = Decimal(str(value).replace(",", "").strip())
    if not number.is_finite():
        raise ValueError("finite numeric value required")
    return number


def _decimal_json_number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def _unavailable(
    source: str,
    *,
    reason: str,
    series: str | None = None,
    directional: bool | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "source": source,
        "official": True,
        "available": False,
        "as_of": None,
        "reason": reason[:160],
    }
    if series is not None:
        result["series"] = series
    if directional is not None:
        result["directional"] = directional
    return result


def fetch_cboe_vix() -> dict[str, Any]:
    try:
        rows = csv.DictReader(io.StringIO(_http_get_text(CBOE_VIX_URL)))
        valid_rows: list[tuple[datetime, float]] = []
        for row in rows:
            raw_date = str(row.get("DATE") or "").strip()
            raw_close = row.get("CLOSE")
            if not raw_date or raw_close in (None, ""):
                continue
            try:
                day = datetime.strptime(raw_date, "%m/%d/%Y")
                close = _number(raw_close)
            except (TypeError, ValueError):
                continue
            valid_rows.append((day, close))
        if not valid_rows:
            return _unavailable(
                "cboe",
                series="VIX",
                reason="no_valid_VIX_rows",
            )
        day, close = max(valid_rows, key=lambda item: item[0])
        return {
            "source": "cboe",
            "series": "VIX",
            "official": True,
            "available": True,
            "value": close,
            "as_of": day.strftime("%Y-%m-%d"),
        }
    except Exception as exc:
        return _unavailable(
            "cboe",
            series="VIX",
            reason=_safe_reason(exc),
        )


def fetch_fred_nfci(
    api_key: str | None = None,
) -> dict[str, Any]:
    key = api_key if api_key is not None else os.getenv(
        "FRED_API_KEY",
        "",
    )
    if not key:
        return _unavailable(
            "fred",
            series="NFCI",
            reason="FRED_API_KEY_not_configured",
        )
    query = urllib.parse.urlencode({
        "series_id": "NFCI",
        "api_key": key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 10,
    })
    try:
        payload = json.loads(
            _http_get_text(f"{FRED_OBSERVATIONS_URL}?{query}"),
        )
        valid_rows: list[tuple[datetime, float]] = []
        for row in payload.get("observations") or []:
            raw_date = str(row.get("date") or "").strip()
            raw_value = row.get("value")
            if not raw_date or raw_value in (None, "", "."):
                continue
            try:
                day = datetime.strptime(raw_date, "%Y-%m-%d")
                value = _number(raw_value)
            except (TypeError, ValueError):
                continue
            valid_rows.append((day, value))
        if not valid_rows:
            return _unavailable(
                "fred",
                series="NFCI",
                reason="no_valid_NFCI_observations",
            )
        day, value = max(valid_rows, key=lambda item: item[0])
        return {
            "source": "fred",
            "series": "NFCI",
            "official": True,
            "available": True,
            "value": value,
            "as_of": day.strftime("%Y-%m-%d"),
        }
    except Exception as exc:
        return _unavailable(
            "fred",
            series="NFCI",
            reason=_safe_reason(exc, secrets=(key,)),
        )


HKEX_EXPECTED_FIELDS = {
    "Total Turnover",
    "Total Trade Count",
    "DQB",
    "ETF Turnover",
}


def _hkex_table_values(
    table: dict[str, Any],
) -> dict[str, Any] | None:
    schema_rows = table.get("schema") or []
    names = schema_rows[0] if schema_rows else []
    if (
        not isinstance(names, list)
        or not HKEX_EXPECTED_FIELDS.issubset(set(names))
        or len(names) != len(set(names))
    ):
        return None
    values = []
    for row in table.get("tr") or []:
        cells = row.get("td") or []
        values.append(
            cells[0][0]
            if cells and cells[0]
            else "",
        )
    data = dict(zip(names, values))
    if not HKEX_EXPECTED_FIELDS.issubset(data):
        return None
    return data


def fetch_hkex_activity(
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _normalize_now(now)
    for offset in range(7):
        day = current - timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        try:
            text = _http_get_text(
                HKEX_DAILY_URL.format(date=day.strftime("%Y%m%d")),
            )
            match = re.search(r"\btabData\s*=\s*", text)
            if not match:
                continue
            rows, _ = json.JSONDecoder().raw_decode(text[match.end():])
            totals = {
                "total_turnover": Decimal("0"),
                "trade_count": Decimal("0"),
                "daily_quota_balance": Decimal("0"),
                "etf_turnover": Decimal("0"),
            }
            found = False
            invalid_day = False
            for market in rows:
                if market.get("market") not in {
                    "SSE Northbound",
                    "SZSE Northbound",
                }:
                    continue
                table = next(
                    (
                        item.get("table") or {}
                        for item in market.get("content") or []
                        if item.get("style") == 1
                    ),
                    {},
                )
                data = _hkex_table_values(table)
                if data is None:
                    invalid_day = True
                    break
                turnover = _decimal_number(data["Total Turnover"])
                trade_count = _decimal_number(data["Total Trade Count"])
                quota_balance = _decimal_number(data["DQB"])
                etf_turnover = _decimal_number(data["ETF Turnover"])
                if (
                    turnover <= 0
                    or trade_count <= 0
                    or quota_balance < 0
                    or etf_turnover < 0
                ):
                    invalid_day = True
                    break
                totals["total_turnover"] += turnover
                totals["trade_count"] += trade_count
                totals["daily_quota_balance"] += quota_balance
                totals["etf_turnover"] += etf_turnover
                found = True
            if invalid_day:
                continue
            if found:
                return {
                    "source": "hkex",
                    "official": True,
                    "available": True,
                    "directional": False,
                    "as_of": day.strftime("%Y-%m-%d"),
                    **{
                        name: float(value)
                        for name, value in totals.items()
                    },
                }
        except Exception:
            # A transport failure is endpoint-wide rather than date-specific.
            # Retrying older dates multiplies the same timeout without adding
            # evidence, so leave date fallback to successful HTTP responses
            # whose payload simply has no usable record.
            break
    return _unavailable(
        "hkex",
        directional=False,
        reason="no_recent_northbound_daily_record",
    )


def _interpolate_decimal(
    value: Decimal,
    anchors: list[tuple[Decimal, Decimal]],
) -> Decimal:
    if value <= anchors[0][0]:
        return anchors[0][1]
    if value >= anchors[-1][0]:
        return anchors[-1][1]
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
        if x0 <= value <= x1:
            return y0 + ((value - x0) / (x1 - x0)) * (y1 - y0)
    return Decimal("50")


def _parse_cffex_trading_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        date_format = "%Y-%m-%d"
    elif re.fullmatch(r"\d{8}", value):
        date_format = "%Y%m%d"
    else:
        return None
    try:
        return datetime.strptime(value, date_format).strftime("%Y-%m-%d")
    except ValueError:
        return None


def fetch_cffex_positioning(
    url: str | None = None,
) -> dict[str, Any]:
    endpoint = url if url is not None else os.getenv(
        "CFFEX_MARKET_DATA_URL",
        "",
    )
    if not endpoint:
        return _unavailable(
            "cffex",
            reason="CFFEX_MARKET_DATA_URL_not_configured",
        )
    required = {
        "contract",
        "trading_date",
        "close",
        "spot_close",
        "volume",
        "open_interest",
        "previous_open_interest",
    }
    try:
        payload = json.loads(_http_get_text(endpoint))
        record = payload[0] if isinstance(payload, list) and payload else payload
        if not isinstance(record, dict) or not required.issubset(record):
            return _unavailable(
                "cffex",
                reason="invalid_authorized_CFFEX_payload",
            )
        contract = str(record["contract"] or "").strip().upper()
        if re.fullmatch(
            r"IF\d{2}(?:0[1-9]|1[0-2])",
            contract,
        ) is None:
            return _unavailable(
                "cffex",
                reason="unsupported_CFFEX_contract",
            )
        trading_date = _parse_cffex_trading_date(
            record["trading_date"],
        )
        if trading_date is None:
            return _unavailable(
                "cffex",
                reason="invalid_CFFEX_trading_date",
            )
        try:
            close = _decimal_number(record["close"])
            spot_close = _decimal_number(record["spot_close"])
            volume = _decimal_number(record["volume"])
            open_interest = _decimal_number(record["open_interest"])
            previous_open_interest = _decimal_number(
                record["previous_open_interest"],
            )
            if (
                close <= 0
                or spot_close <= 0
                or open_interest <= 0
                or previous_open_interest <= 0
                or volume < 0
                or volume != volume.to_integral_value()
                or open_interest != open_interest.to_integral_value()
                or (
                    previous_open_interest
                    != previous_open_interest.to_integral_value()
                )
            ):
                raise ValueError("CFFEX numeric value outside domain")
            basis_pct = (
                (close / spot_close) - Decimal("1")
            ) * Decimal("100")
            oi_change_pct = (
                (open_interest / previous_open_interest) - Decimal("1")
            ) * Decimal("100")
            score = _interpolate_decimal(
                basis_pct,
                CFFEX_BASIS_ANCHORS,
            )
            if oi_change_pct > Decimal("5"):
                if score > Decimal("50"):
                    score += Decimal("5")
                elif score < Decimal("50"):
                    score -= Decimal("5")
            score = max(Decimal("0"), min(Decimal("100"), score))
            basis_output = float(
                basis_pct.quantize(
                    THREE_PLACES,
                    rounding=ROUND_HALF_EVEN,
                ),
            )
            oi_change_output = float(
                oi_change_pct.quantize(
                    THREE_PLACES,
                    rounding=ROUND_HALF_EVEN,
                ),
            )
            score_output = float(_quantize_two_places(score))
        except (
            DecimalException,
            OverflowError,
            TypeError,
            ValueError,
        ):
            return _unavailable(
                "cffex",
                reason="invalid_CFFEX_numeric_values",
            )
        return {
            "source": "cffex",
            "official": True,
            "available": True,
            "as_of": trading_date,
            "contract": contract,
            "basis_pct": basis_output,
            "oi_change_pct": oi_change_output,
            "volume": _decimal_json_number(volume),
            "score": score_output,
        }
    except Exception as exc:
        parsed = urllib.parse.urlsplit(endpoint)
        secrets = tuple(
            value
            for _, value in urllib.parse.parse_qsl(
                parsed.query,
                keep_blank_values=True,
            )
            if value
        )
        return _unavailable(
            "cffex",
            reason=_safe_reason(exc, secrets=secrets),
        )


def _parse_as_of(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _normalize_now(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _valid_component_score(value: Any) -> bool:
    return (
        _is_valid_number(value)
        and Decimal("0") <= Decimal(str(value)) <= Decimal("100")
    )


def _prepare_source_record(
    raw: Any,
    *,
    source: str,
    now: datetime,
    max_age_days: int,
    absolute_max_age_days: int,
    weight: int | None = None,
    scorer: Any = None,
) -> tuple[dict[str, Any], str, str | None]:
    if not isinstance(raw, dict):
        record = _unavailable(
            source,
            reason="invalid_source_record",
        )
        if weight is not None:
            record["weight"] = weight
            record["stale"] = False
        return record, "unavailable", record["reason"]

    record = dict(raw)
    reported_source = record.get("source")
    if reported_source != source:
        record.update({
            "source": source,
            "reported_source": reported_source,
            "available": False,
            "reason": "source_mismatch",
        })
        if weight is not None:
            record["weight"] = weight
            record["stale"] = False
        else:
            record.pop("score", None)
            record.pop("weight", None)
        return record, "unavailable", "source_mismatch"
    record["source"] = source
    if weight is None:
        record.pop("score", None)
        record.pop("weight", None)
    if record.get("official") is not True:
        record.update({
            "official": bool(record.get("official")),
            "available": False,
            "as_of": record.get("as_of"),
            "reason": "unofficial_source",
        })
        if weight is not None:
            record["weight"] = weight
            record["stale"] = False
        return record, "unavailable", "unofficial_source"

    if record.get("available") is not True:
        record["available"] = False
        record["as_of"] = record.get("as_of")
        reason = _safe_reason(
            record.get("reason") or "source_unavailable",
        )
        record["reason"] = reason
        if weight is not None:
            record["weight"] = weight
            record["stale"] = False
        return record, "unavailable", reason

    if scorer is not None:
        try:
            record["score"] = scorer(record["value"])
        except (KeyError, TypeError, ValueError, OverflowError):
            record["available"] = False
            record["reason"] = "invalid_source_value"
            if weight is not None:
                record["weight"] = weight
                record["stale"] = False
            return record, "unavailable", "invalid_source_value"
    elif weight is not None and not _valid_component_score(
        record.get("score"),
    ):
        record["available"] = False
        record["reason"] = "invalid_component_score"
        record["weight"] = weight
        record["stale"] = False
        return record, "unavailable", "invalid_component_score"

    as_of = _parse_as_of(record.get("as_of"))
    if as_of is None:
        record["available"] = False
        record["reason"] = "invalid_as_of_date"
        if weight is not None:
            record["weight"] = weight
            record["stale"] = False
        return record, "unavailable", "invalid_as_of_date"
    age_days = (now.date() - as_of.date()).days
    if age_days < 0:
        record["available"] = False
        record["reason"] = "future_as_of_date"
        if weight is not None:
            record["weight"] = weight
            record["stale"] = False
        return record, "unavailable", "future_as_of_date"
    if age_days > absolute_max_age_days:
        record["available"] = False
        record["reason"] = "source_too_old"
        if weight is not None:
            record["weight"] = weight
            record["stale"] = False
        return record, "unavailable", "source_too_old"

    stale = age_days > max_age_days
    record["available"] = True
    record["as_of"] = as_of.strftime("%Y-%m-%d")
    record["stale"] = stale
    record.pop("reason", None)
    if weight is not None:
        record["weight"] = weight
    return (
        record,
        "stale" if stale else "live",
        "stale_as_of_date" if stale else None,
    )


def _prepare_cached_fallback(
    previous: Any,
    *,
    component_name: str,
    source: str,
    now: datetime,
    absolute_max_age_days: int,
    weight: int | None = None,
    scorer: Any = None,
) -> dict[str, Any] | None:
    if not isinstance(previous, dict):
        return None
    components = previous.get("components")
    if not isinstance(components, dict):
        return None
    cached = components.get(component_name)
    if not isinstance(cached, dict):
        return None
    if (
        cached.get("available") is not True
        or cached.get("official") is not True
        or cached.get("source") != source
    ):
        return None
    record = dict(cached)
    if scorer is not None:
        try:
            record["score"] = scorer(record["value"])
        except (KeyError, TypeError, ValueError, OverflowError):
            return None
    elif weight is not None and not _valid_component_score(
        record.get("score"),
    ):
        return None
    as_of = _parse_as_of(record.get("as_of"))
    if as_of is None:
        return None
    age_days = (now.date() - as_of.date()).days
    if age_days < 0 or age_days > absolute_max_age_days:
        return None
    record["as_of"] = as_of.strftime("%Y-%m-%d")
    record["available"] = True
    record["stale"] = True
    record["fallback_from_cache"] = True
    record.pop("reason", None)
    if weight is not None:
        record["weight"] = weight
    else:
        record.pop("weight", None)
        record.pop("score", None)
    return record


def _should_use_cached_fallback(
    current: dict[str, Any],
    status: str,
    cached: dict[str, Any] | None,
) -> bool:
    if cached is None:
        return False
    if status == "unavailable":
        return True
    if status != "stale":
        return False
    current_date = _parse_as_of(current.get("as_of"))
    cached_date = _parse_as_of(cached.get("as_of"))
    return bool(
        cached_date
        and (
            current_date is None
            or cached_date.date() >= current_date.date()
        )
    )


def _source_audit(
    record: dict[str, Any],
    *,
    status: str,
    reason: str | None,
) -> dict[str, Any]:
    return {
        "source": record.get("source"),
        "official": bool(record.get("official")),
        "status": status,
        "as_of": record.get("as_of"),
        "reason": reason,
    }


def collect_market_sentiment(
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _normalize_now(now)
    previous = cache.get("global:sentiment:latest")
    with ThreadPoolExecutor(
        max_workers=4,
        thread_name_prefix="market-sentiment",
    ) as executor:
        source_futures = {
            "cboe": executor.submit(fetch_cboe_vix),
            "fred": executor.submit(fetch_fred_nfci),
            "hkex": executor.submit(fetch_hkex_activity, now=current),
            "cffex": executor.submit(fetch_cffex_positioning),
        }
        raw_sources = {
            source: future.result()
            for source, future in source_futures.items()
        }
    specifications = [
        {
            "component": "volatility",
            "source": "cboe",
            "max_age_days": 4,
            "absolute_max_age_days": 10,
            "weight": 50,
            "scorer": score_vix,
        },
        {
            "component": "financial_conditions",
            "source": "fred",
            "max_age_days": 10,
            "absolute_max_age_days": 30,
            "weight": 30,
            "scorer": score_nfci,
        },
        {
            "component": "cross_border_activity",
            "source": "hkex",
            "max_age_days": 4,
            "absolute_max_age_days": 10,
            "weight": None,
            "scorer": None,
        },
        {
            "component": "futures_positioning",
            "source": "cffex",
            "max_age_days": 4,
            "absolute_max_age_days": 10,
            "weight": 20,
            "scorer": None,
        },
    ]
    components: dict[str, dict[str, Any]] = {}
    audits: dict[str, dict[str, Any]] = {}
    source_warnings: list[str] = []

    for spec in specifications:
        source = spec["source"]
        component_name = spec["component"]
        prepared, status, reason = _prepare_source_record(
            raw_sources[source],
            source=source,
            now=current,
            max_age_days=spec["max_age_days"],
            absolute_max_age_days=spec["absolute_max_age_days"],
            weight=spec["weight"],
            scorer=spec["scorer"],
        )
        fallback = _prepare_cached_fallback(
            previous,
            component_name=component_name,
            source=source,
            now=current,
            absolute_max_age_days=spec["absolute_max_age_days"],
            weight=spec["weight"],
            scorer=spec["scorer"],
        )
        if _should_use_cached_fallback(prepared, status, fallback):
            original_reason = reason or "source_unavailable"
            prepared = fallback
            status = "stale"
            reason = f"{original_reason}; cache_fallback"
            source_warnings.append(f"{source}:stale_cache_fallback")
        elif status == "stale":
            source_warnings.append(f"{source}:stale")
        elif status == "unavailable":
            source_warnings.append(f"{source}:unavailable")

        components[component_name] = prepared
        audits[source] = _source_audit(
            prepared,
            status=status,
            reason=reason,
        )

    result = score_market_sentiment({
        name: component
        for name, component in components.items()
        if name != "cross_border_activity"
    })
    result["generated_at"] = current.strftime("%Y-%m-%d %H:%M:%S")
    result["components"] = components
    result["sources"] = [
        audits[source]
        for source in ("cboe", "fred", "hkex", "cffex")
    ]
    result["stale"] = result["stale"] or any(
        source["status"] == "stale"
        for source in result["sources"]
    )
    result["warnings"] = [
        *result["warnings"],
        *source_warnings,
    ]
    cache.set("global:sentiment:latest", result)
    cache.set(
        f"global:sentiment:{current:%Y%m%d}",
        result,
    )
    return result


def get_market_sentiment_status() -> dict[str, Any]:
    cached = cache.get("global:sentiment:latest")
    valid_regimes = {
        "extreme_fear",
        "fear",
        "neutral",
        "greed",
        "extreme_greed",
    }
    if not isinstance(cached, dict):
        return score_market_sentiment({})

    score = cached.get("sentiment_score")
    confidence = cached.get("confidence")
    regime = cached.get("sentiment_regime")
    if (
        not _is_valid_number(score)
        or not Decimal("0") <= Decimal(str(score)) <= Decimal("100")
        or not _is_valid_number(confidence)
        or not Decimal("0") <= Decimal(str(confidence)) <= Decimal("1")
        or regime not in valid_regimes
    ):
        return score_market_sentiment({})

    result = dict(cached)
    result.update({
        "mode": "shadow_only",
        "can_change_trade_policy": False,
        "can_trigger_order": False,
    })
    return result


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Collect official market sentiment in shadow-only mode.",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="collect official sources and print the JSON result",
    )
    args = parser.parse_args(argv)
    if not args.run:
        return 0

    result = dict(collect_market_sentiment())
    result.update({
        "mode": "shadow_only",
        "can_change_trade_policy": False,
        "can_trigger_order": False,
    })
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())

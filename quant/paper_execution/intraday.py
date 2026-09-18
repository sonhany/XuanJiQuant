"""Trading-window and realtime-quote contracts for F5 intraday simulation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any, Iterable, Mapping


class IntradayQuoteError(ValueError):
    """A required realtime market fact is missing or unsafe."""


@dataclass(frozen=True, slots=True)
class IntradayWindow:
    allowed: bool
    session: str
    reason_code: str


def classify_intraday_window(now: datetime) -> IntradayWindow:
    if now.weekday() >= 5:
        return IntradayWindow(False, "closed", "non_trading_weekday")
    current = now.time()
    if time(9, 35) <= current <= time(11, 25):
        return IntradayWindow(True, "morning", "intraday_window_open")
    if time(13, 5) <= current <= time(14, 50):
        return IntradayWindow(True, "afternoon", "intraday_window_open")
    return IntradayWindow(False, "closed", "outside_intraday_window")


def _pure_code(value: Any) -> str:
    digits = "".join(char for char in str(value or "") if char.isdigit())
    return digits[-6:].zfill(6) if digits else ""


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip().replace("-", "").replace(":", "").replace(" ", "")
    for length, pattern in ((14, "%Y%m%d%H%M%S"), (12, "%Y%m%d%H%M")):
        if len(text) >= length:
            try:
                return datetime.strptime(text[:length], pattern)
            except ValueError:
                continue
    return None


def normalize_intraday_quotes(
    raw_quotes: Mapping[str, Mapping[str, Any]],
    required_codes: Iterable[str],
    *,
    now: datetime,
    max_age_seconds: int = 120,
) -> dict[str, dict[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for vendor_code, quote in raw_quotes.items():
        pure = _pure_code(quote.get("code") or vendor_code)
        if pure:
            indexed[pure] = quote

    normalized: dict[str, dict[str, Any]] = {}
    for raw_code in required_codes:
        code = _pure_code(raw_code)
        quote = indexed.get(code)
        if not quote:
            raise IntradayQuoteError(f"intraday_quote_missing:{code}")
        quote_time = _parse_timestamp(quote.get("timestamp") or quote.get("time"))
        if quote_time is None:
            raise IntradayQuoteError(f"intraday_quote_timestamp_invalid:{code}")
        if quote_time.date() != now.date():
            raise IntradayQuoteError(f"intraday_quote_wrong_date:{code}")
        age = int((now - quote_time).total_seconds())
        if age < -5 or age > int(max_age_seconds):
            raise IntradayQuoteError(f"intraday_quote_stale:{code}")
        try:
            price = float(quote.get("price"))
            volume = float(quote.get("volume"))
        except (TypeError, ValueError):
            price, volume = 0.0, 0.0
        source_volume_unit = str(quote.get("volume_unit") or "share").lower()
        if source_volume_unit in {"hand", "lot", "lots", "手"}:
            volume *= 100
        if not math.isfinite(price) or price <= 0:
            raise IntradayQuoteError(f"intraday_price_invalid:{code}")
        if not math.isfinite(volume) or volume <= 0:
            raise IntradayQuoteError(f"intraday_volume_invalid:{code}")
        change = float(quote.get("chg_pct") or quote.get("change_pct") or 0)
        normalized[code] = {
            **dict(quote),
            "code": code,
            "price": price,
            "volume": volume,
            "volume_unit": "share",
            "source_volume_unit": source_volume_unit,
            "quote_timestamp": quote_time.strftime("%Y%m%d%H%M%S"),
            "quote_age_seconds": max(0, age),
            "date": now.strftime("%Y%m%d"),
            "suspended": str(quote.get("trading_state") or "active") != "active",
            "limit_up": change >= 9.9,
            "limit_down": change <= -9.9,
        }
    return normalized

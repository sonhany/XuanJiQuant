"""Shared validation and result contracts for stock valuation."""
from __future__ import annotations

import math
import re
from statistics import median
from typing import Any


VALID_STATUSES = {"success", "partial", "unavailable", "error"}
SZ_CODE_PREFIXES = (
    "000",
    "001",
    "002",
    "003",
    "300",
    "301",
)
SH_CODE_PREFIXES = (
    "600",
    "601",
    "603",
    "605",
    "688",
    "689",
)
VALID_CODE_PREFIXES = SZ_CODE_PREFIXES + SH_CODE_PREFIXES


def normalize_code(value: object) -> str:
    """Return a supported six-digit A-share code or an empty string."""
    raw = str(value or "").strip().upper()
    exchange = ""
    if re.fullmatch(r"(?:SH|SZ|BJ)\d{6}", raw):
        exchange = raw[:2]
        raw = raw[2:]
    elif re.fullmatch(r"\d{6}\.(?:SH|SZ|BJ)", raw):
        exchange = raw[-2:]
        raw = raw[:6]
    elif not re.fullmatch(r"\d{6}", raw):
        return ""

    if exchange == "BJ" or raw.startswith("920"):
        return ""
    if not raw.startswith(VALID_CODE_PREFIXES):
        return ""
    if exchange == "SH" and not raw.startswith(SH_CODE_PREFIXES):
        return ""
    if exchange == "SZ" and not raw.startswith(SZ_CODE_PREFIXES):
        return ""
    return raw


def safe_number(value: Any) -> float | None:
    """Convert a finite numeric value while preserving missing values."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def derive_growth_rate(records: list[dict]) -> float | None:
    """Derive a robust annual revenue growth rate from normalized history."""
    annual_revenue: list[tuple[str, float]] = []
    raw_annual_growth: list[tuple[str, float]] = []
    raw_all_growth: list[tuple[str, float]] = []
    for row in records:
        if not isinstance(row, dict):
            continue
        period = str(
            row.get("report_period")
            or row.get("report_date")
            or row.get("end_date")
            or ""
        )
        if len(period) < 8:
            continue
        revenue = safe_number(row.get("revenue"))
        growth = safe_number(row.get("revenue_growth"))
        if revenue is not None and revenue > 0 and period.endswith("1231"):
            annual_revenue.append((period, revenue))
        if growth is not None:
            raw_all_growth.append((period, growth))
            if period.endswith("1231"):
                raw_annual_growth.append((period, growth))

    annual_revenue.sort(key=lambda item: item[0])
    if len(annual_revenue) >= 2:
        first_period, first_value = annual_revenue[0]
        last_period, last_value = annual_revenue[-1]
        years = max(1, int(last_period[:4]) - int(first_period[:4]))
        growth = (last_value / first_value) ** (1 / years) - 1
        if math.isfinite(growth):
            return growth

    raw_candidates = raw_annual_growth or raw_all_growth
    percentage_units = any(abs(value) > 1 for _period, value in raw_candidates)
    candidates = [
        (period, value / 100.0 if percentage_units else value)
        for period, value in raw_candidates
        if -100.0 < value < 500.0
    ]
    candidates.sort(key=lambda item: item[0])
    recent = [value for _period, value in candidates[-5:]]
    return median(recent) if recent else None


def model_result(
    kind: str,
    status: str,
    *,
    low: Any = None,
    mid: Any = None,
    high: Any = None,
    confidence: Any = None,
    error: str = "",
    details: dict | None = None,
    warnings: list | None = None,
) -> dict:
    """Build one valuation-track result without inventing missing values."""
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid valuation status: {status}")
    return {
        "type": str(kind or ""),
        "status": status,
        "low": safe_number(low),
        "mid": safe_number(mid),
        "high": safe_number(high),
        "confidence": safe_number(confidence),
        "details": details if details is not None else {},
        "warnings": warnings if warnings is not None else [],
        "error": str(error or ""),
    }

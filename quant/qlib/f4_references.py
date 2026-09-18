"""Point-in-time industry and benchmark reference builders for F4 research."""

from __future__ import annotations

import hashlib
import json
from bisect import bisect_right
from datetime import date, datetime
from typing import Any, Iterable, Mapping, Sequence

from .sources import normalize_instrument


INDUSTRY_MIN_COVERAGE = 0.95
BENCHMARK_MIN_COVERAGE = 0.99


def _iso_date(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    text = str(value or "").strip()[:10]
    digits = "".join(char for char in text if char.isdigit())[:8]
    if len(digits) != 8:
        return ""
    try:
        return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8])).isoformat()
    except ValueError:
        return ""


def _first(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip():
            return value
    return ""


def _content_hash(payload: object) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_industry_records(
    rows: Iterable[Mapping[str, Any]], *, standard_code: str = "008002"
) -> list[dict[str, str]]:
    """Normalize effective-dated CNINFO classifications without historical backfill."""
    normalized: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        standard = str(
            _first(row, "分类标准编码", "STANDARD_CODE", "standard_code")
        ).strip()
        if standard != standard_code:
            continue
        instrument = normalize_instrument(
            str(_first(row, "证券代码", "SECCODE", "instrument", "symbol"))
        )
        effective_from = _iso_date(
            _first(row, "变更日期", "纳入日期", "VARYDATE", "effective_from")
        )
        industry_code = str(
            _first(
                row,
                "行业大类编码",
                "行业门类编码",
                "行业编码",
                "INDUSTRYCODE",
                "industry_code",
            )
        ).strip()
        industry_name = str(
            _first(row, "行业大类", "行业门类", "INDUSTRYNAME", "industry_name")
        ).strip()
        if not effective_from or not industry_code or not industry_name:
            continue
        normalized[(instrument, effective_from)] = {
            "instrument": instrument,
            "effective_from": effective_from,
            "industry_code": industry_code,
            "industry_name": industry_name,
            "standard_code": standard,
            "source": "cninfo_p_stock2110",
        }
    return [normalized[key] for key in sorted(normalized)]


def build_industry_payload(
    records: Iterable[Mapping[str, Any]],
    eligible_dates: Mapping[str, Sequence[object]],
    *,
    standard_code: str = "008002",
) -> dict[str, Any]:
    canonical = [dict(row) for row in records]
    canonical.sort(key=lambda row: (str(row.get("instrument")), str(row.get("effective_from"))))
    effective_by_symbol: dict[str, list[str]] = {}
    for row in canonical:
        effective_by_symbol.setdefault(str(row.get("instrument") or ""), []).append(
            str(row.get("effective_from") or "")
        )

    expected = 0
    covered = 0
    covered_symbols = 0
    for raw_symbol, raw_dates in eligible_dates.items():
        symbol = normalize_instrument(raw_symbol)
        effective_dates = sorted(value for value in effective_by_symbol.get(symbol, []) if value)
        symbol_covered = False
        for raw_date in raw_dates:
            sample_date = _iso_date(raw_date)
            if not sample_date:
                continue
            expected += 1
            if bisect_right(effective_dates, sample_date):
                covered += 1
                symbol_covered = True
        if symbol_covered:
            covered_symbols += 1
    coverage = covered / expected if expected else 0.0
    digest = _content_hash(canonical)
    return {
        "status": "passed" if coverage >= INDUSTRY_MIN_COVERAGE else "failed",
        "version": f"cninfo-{standard_code}-{digest[:16]}",
        "effective_dated": True,
        "standard_code": standard_code,
        "source": "cninfo_p_stock2110",
        "expected_samples": expected,
        "covered_samples": covered,
        "coverage": coverage,
        "eligible_symbols": len(eligible_dates),
        "covered_symbols": covered_symbols,
        "record_count": len(canonical),
        "records": canonical,
        "sha256": digest,
    }


def build_benchmark_payload(
    rows: Iterable[Mapping[str, Any]],
    *,
    expected_dates: Sequence[object],
    code: str = "000300",
) -> dict[str, Any]:
    by_date: dict[str, dict[str, Any]] = {}
    numeric_fields = {
        "open": ("开盘", "open"),
        "high": ("最高", "high"),
        "low": ("最低", "low"),
        "close": ("收盘", "close"),
        "volume": ("成交量", "volume"),
        "amount": ("成交额", "amount"),
    }
    for row in rows:
        trade_date = _iso_date(_first(row, "日期", "date", "datetime"))
        if not trade_date:
            continue
        normalized: dict[str, Any] = {"date": trade_date}
        for target, aliases in numeric_fields.items():
            value = _first(row, *aliases)
            if value == "":
                continue
            try:
                normalized[target] = float(value)
            except (TypeError, ValueError):
                continue
        if "close" in normalized:
            by_date[trade_date] = normalized
    expected = sorted({_iso_date(value) for value in expected_dates if _iso_date(value)})
    expected_set = set(expected)
    bars = [by_date[key] for key in sorted(by_date) if not expected_set or key in expected_set]
    observed = len({row["date"] for row in bars} & expected_set) if expected_set else len(bars)
    coverage = observed / len(expected) if expected else 0.0
    observed_dates = {row["date"] for row in bars}
    missing_dates = [value for value in expected if value not in observed_dates]
    latest_date_complete = bool(expected and expected[-1] in observed_dates)
    digest = _content_hash(bars)
    return {
        "status": (
            "passed"
            if coverage >= BENCHMARK_MIN_COVERAGE and latest_date_complete
            else "failed"
        ),
        "code": str(code),
        "version": f"{code}-{digest[:16]}",
        "source": "akshare_index_zh_a_hist",
        "expected_dates": len(expected),
        "observed_dates": observed,
        "coverage": coverage,
        "latest_date_complete": latest_date_complete,
        "missing_dates": missing_dates,
        "start_date": expected[0] if expected else "",
        "end_date": expected[-1] if expected else "",
        "bars": bars,
        "sha256": digest,
    }

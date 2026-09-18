from __future__ import annotations

from typing import Any, Iterable


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _date_key(row: dict[str, Any]) -> str:
    value = str(row.get("datetime") or row.get("date") or "")[:10]
    digits = value.replace("-", "")
    if len(digits) >= 8 and digits[:8].isdigit():
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return ""


def compare_front_prices(
    raw_close: float,
    factor: float,
    observed_front_close: float,
    *,
    tolerance: float = 0.01,
) -> dict[str, Any]:
    expected = _number(raw_close) * _number(factor)
    observed = _number(observed_front_close)
    deviation = abs(observed / expected - 1.0) if expected > 0 and observed > 0 else float("inf")
    return {
        "expected": expected,
        "observed": observed,
        "deviation": deviation,
        "passed": deviation <= float(tolerance),
    }


def _factor_by_date(rows: Iterable[dict[str, Any]]) -> dict[str, float]:
    result: dict[str, float] = {}
    for row in rows or []:
        trade_date = _date_key(row)
        factor = _number(
            row.get("factor")
            or row.get("foreAdjustFactor")
            or row.get("adjustFactor")
            or row.get("forward_factor")
        )
        if trade_date and factor > 0:
            result[trade_date] = factor
    return result


def reconcile_adjustment_rows(
    raw: Iterable[dict[str, Any]],
    front: Iterable[dict[str, Any]],
    baostock_factors: Iterable[dict[str, Any]],
    *,
    tolerance: float = 0.01,
) -> list[dict[str, Any]]:
    front_by_date = {_date_key(row): row for row in front or [] if _date_key(row)}
    fallback_factors = _factor_by_date(baostock_factors)
    result = []
    for raw_row in raw or []:
        row = dict(raw_row)
        trade_date = _date_key(row)
        front_row = front_by_date.get(trade_date) or {}
        raw_close = _number(row.get("close"))
        observed_front = _number(front_row.get("close"))
        tdx_factor = _number(row.get("factor"))
        baostock_factor = fallback_factors.get(trade_date, 0.0)
        derived_factor = observed_front / raw_close if raw_close > 0 and observed_front > 0 else 0.0
        tdx_comparison = compare_front_prices(
            raw_close,
            tdx_factor,
            observed_front,
            tolerance=tolerance,
        )
        if tdx_factor > 0 and (observed_front <= 0 or tdx_comparison["passed"]):
            factor = tdx_factor
            source = "tdxquant"
        elif baostock_factor > 0:
            factor = baostock_factor
            source = "baostock"
        elif derived_factor > 0:
            factor = derived_factor
            source = "derived"
        else:
            factor = tdx_factor
            source = "tdxquant" if tdx_factor else "missing"
        comparison = compare_front_prices(
            raw_close,
            factor,
            observed_front,
            tolerance=tolerance,
        )
        row.update(
            {
                "datetime": trade_date,
                "factor": factor,
                "factor_source": source,
                "tdxquant_factor": tdx_factor,
                "front_close_observed": observed_front,
                "front_close_expected": comparison["expected"],
                "front_price_deviation": comparison["deviation"],
                "front_price_valid": comparison["passed"],
            }
        )
        result.append(row)
    return result


def validate_adjustment_rows(
    rows: Iterable[dict[str, Any]],
    *,
    tolerance: float = 0.01,
) -> dict[str, Any]:
    reason_codes: set[str] = set()
    anomalies = 0
    count = 0
    for row in rows or []:
        count += 1
        factor = _number(row.get("factor"))
        if factor <= 0:
            reason_codes.add("non_positive_factor")
        deviation = _number(row.get("front_price_deviation"))
        if deviation > tolerance:
            anomalies += 1
    if anomalies:
        reason_codes.add("front_price_deviation")
    return {
        "passed": not reason_codes,
        "reason_codes": sorted(reason_codes),
        "rows": count,
        "front_price_anomalies": anomalies,
    }

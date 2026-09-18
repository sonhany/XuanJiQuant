"""Deterministic market-regime adjustment for stock valuation."""
from __future__ import annotations

from typing import Any

from .contracts import model_result, safe_number


FORMULA_VERSION = "market-regime-v1"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _percentile(value: float, sample: list[float]) -> float | None:
    if not sample:
        return None
    below = sum(1 for item in sample if item < value)
    equal = sum(1 for item in sample if item == value)
    return (below + 0.5 * equal) / len(sample)


def _factor_from_percentile(value: float | None, *, inverse: bool) -> float | None:
    if value is None:
        return None
    centered = _clamp(2 * (value - 0.5), -1.0, 1.0)
    return -centered if inverse else centered


def _coverage_months(history: list[dict]) -> int:
    months = {
        str(row.get("date") or row.get("time") or "")[:6]
        for row in history
        if len(str(row.get("date") or row.get("time") or "")) >= 6
    }
    return len(months)


def market_valuation(
    target: dict,
    history: list[dict],
    market_context: dict,
    *,
    peers: list[dict] | None = None,
    reference_mid: float | None = None,
) -> dict:
    """Apply a bounded market-state adjustment to a deterministic midpoint."""
    reference = safe_number(reference_mid)
    if reference is None or reference <= 0:
        return model_result(
            "market",
            "unavailable",
            error="缺少绝对或相对估值中枢，市场调整无法独立定价",
            details={"formula_version": FORMULA_VERSION},
        )

    rows = [row for row in history if isinstance(row, dict)]
    closes = [
        value
        for row in rows
        if (value := safe_number(row.get("close"))) is not None and value > 0
    ]
    current_price = safe_number(target.get("price"))
    own_percentile = (
        _percentile(current_price, closes)
        if current_price is not None and closes
        else None
    )
    own_factor = _factor_from_percentile(own_percentile, inverse=True)

    peer_rows = [row for row in (peers or []) if isinstance(row, dict)]
    peer_pes = [
        value
        for row in peer_rows
        if (value := safe_number(row.get("pe"))) is not None and value > 0
    ]
    target_eps = safe_number(target.get("eps"))
    target_pe = (
        current_price / target_eps
        if current_price is not None
        and target_eps is not None
        and target_eps > 0
        else None
    )
    industry_percentile = (
        _percentile(target_pe, peer_pes)
        if target_pe is not None and peer_pes
        else None
    )
    industry_factor = _factor_from_percentile(
        industry_percentile, inverse=True
    )

    index = (
        market_context.get("index")
        if isinstance(market_context.get("index"), dict)
        else {}
    )
    index_percentile = safe_number(index.get("percentile"))
    regime = str(index.get("regime") or "").lower()
    if index_percentile is not None:
        index_factor = _factor_from_percentile(
            index_percentile, inverse=False
        )
    elif regime in {"bull", "risk_on", "uptrend"}:
        index_factor = 0.5
    elif regime in {"bear", "risk_off", "downtrend"}:
        index_factor = -0.5
    else:
        index_factor = None

    breadth = (
        market_context.get("breadth")
        if isinstance(market_context.get("breadth"), dict)
        else {}
    )
    advance_ratio = safe_number(breadth.get("advance_ratio"))
    breadth_factor = (
        _clamp(2 * (advance_ratio - 0.5), -1.0, 1.0)
        if advance_ratio is not None
        else None
    )
    liquidity = (
        market_context.get("liquidity")
        if isinstance(market_context.get("liquidity"), dict)
        else {}
    )
    amount_ratio = safe_number(liquidity.get("amount_ratio"))
    liquidity_factor_raw = (
        _clamp(amount_ratio - 1.0, -1.0, 1.0)
        if amount_ratio is not None
        else None
    )
    available_liquidity = [
        value
        for value in (breadth_factor, liquidity_factor_raw)
        if value is not None
    ]
    liquidity_factor = (
        sum(available_liquidity) / len(available_liquidity)
        if available_liquidity
        else None
    )

    factors = {
        "own": own_factor,
        "industry": industry_factor,
        "index": index_factor,
        "liquidity": liquidity_factor,
    }
    weights = {"own": 0.40, "industry": 0.30, "index": 0.20, "liquidity": 0.10}
    available_weight = sum(
        weights[name] for name, value in factors.items() if value is not None
    )
    raw_adjustment = (
        sum(
            weights[name] * value
            for name, value in factors.items()
            if value is not None
        )
        if available_weight
        else 0.0
    )
    adjustment = _clamp(raw_adjustment, -0.20, 0.20)
    midpoint = reference * (1 + adjustment)
    coverage = _coverage_months(rows)
    warnings: list[str] = []
    if coverage < 36:
        warnings.append(f"个股历史覆盖仅{coverage}个月，不足3年")
    missing = [name for name, value in factors.items() if value is None]
    if missing:
        warnings.append("市场维度缺失: " + ", ".join(missing))
    state = "discount" if adjustment < -0.05 else (
        "premium" if adjustment > 0.05 else "neutral"
    )
    return model_result(
        "market",
        "partial" if warnings else "success",
        low=midpoint * 0.85,
        mid=midpoint,
        high=midpoint * 1.15,
        confidence=max(0.0, min(1.0, available_weight * min(1.0, coverage / 36))),
        details={
            "formula_version": FORMULA_VERSION,
            "reference_mid": reference,
            "coverage_months": coverage,
            "own_percentile": own_percentile,
            "industry_percentile": industry_percentile,
            "factors": factors,
            "weights": weights,
            "available_weight": available_weight,
            "raw_adjustment": raw_adjustment,
            "adjustment": adjustment,
            "state": state,
        },
        warnings=warnings,
    )

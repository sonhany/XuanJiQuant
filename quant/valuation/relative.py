"""Deterministic peer-multiple stock valuation."""
from __future__ import annotations

import math
from statistics import median, quantiles
from typing import Any

from .contracts import model_result, safe_number


FORMULA_VERSION = "relative-multiples-v2"
_MULTIPLES = ("pe", "pb", "ps")


def _quartiles(values: list[float]) -> tuple[float, float]:
    if len(values) < 2:
        return values[0], values[0]
    cuts = quantiles(values, n=4, method="inclusive")
    return cuts[0], cuts[2]


def _outlier_bounds(values: list[float]) -> tuple[float, float]:
    q1, q3 = _quartiles(values)
    spread = q3 - q1
    return q1 - 1.5 * spread, q3 + 1.5 * spread


def _positive(value: Any) -> float | None:
    number = safe_number(value)
    return number if number is not None and number > 0 else None


def _weighted_quantile(values: list[tuple[float, float]], percentile: float) -> float:
    ordered = sorted(values, key=lambda item: item[0])
    total = sum(weight for _, weight in ordered)
    if total <= 0:
        return median(value for value, _ in ordered)
    threshold = total * percentile
    running = 0.0
    for value, weight in ordered:
        running += weight
        if running >= threshold:
            return value
    return ordered[-1][0]


def _distance(target: dict, peer: dict) -> float:
    components: list[float] = []
    target_cap = _positive(target.get("market_cap"))
    peer_cap = _positive(peer.get("market_cap"))
    if target_cap and peer_cap:
        components.append(min(3.0, abs(math.log(peer_cap / target_cap))))
    for field, scale in (
        ("earnings_growth_rate", 0.25),
        ("roe", 20.0),
        ("net_margin", 20.0),
    ):
        left = safe_number(target.get(field))
        right = safe_number(peer.get(field))
        if left is not None and right is not None:
            components.append(min(3.0, abs(left - right) / scale))
    return sum(components) / len(components) if components else 1.0


def _peer_weight(target: dict, peer: dict) -> float:
    return max(0.05, math.exp(-_distance(target, peer)))


def _method_result(
    values: list[tuple[float, float]],
    target_metric: float,
) -> dict[str, float]:
    q25 = _weighted_quantile(values, 0.25)
    middle = _weighted_quantile(values, 0.50)
    q75 = _weighted_quantile(values, 0.75)
    return {
        "peer_q25": q25,
        "peer_median": middle,
        "peer_q75": q75,
        "low": q25 * target_metric,
        "mid": middle * target_metric,
        "high": q75 * target_metric,
    }


def _method_quality(method: dict, sample_count: int) -> float:
    middle = max(1e-9, float(method["peer_median"]))
    dispersion = max(0.0, float(method["peer_q75"]) - float(method["peer_q25"])) / middle
    sample_score = min(1.0, sample_count / 8)
    return max(0.10, sample_score / (1 + dispersion))


def relative_valuation(target: dict, peers: list[dict]) -> dict:
    """Value a target from outlier-filtered, similarity-weighted peers."""
    rows = [row for row in peers if isinstance(row, dict)]
    candidate_values = {
        metric: [
            value
            for row in rows
            if (value := _positive(row.get(metric))) is not None
        ]
        for metric in _MULTIPLES
    }
    bounds = {
        metric: _outlier_bounds(values)
        for metric, values in candidate_values.items()
        if values
    }
    eligible: list[dict] = []
    for row in rows:
        valid_any = False
        outlier = False
        for metric, (low, high) in bounds.items():
            value = _positive(row.get(metric))
            if value is None:
                continue
            valid_any = True
            if value < low or value > high:
                outlier = True
        if valid_any and not outlier:
            eligible.append(row)

    weights = {
        str(row.get("code") or index): _peer_weight(target, row)
        for index, row in enumerate(eligible)
    }

    def weighted_values(field: str) -> list[tuple[float, float]]:
        return [
            (value, weights[str(row.get("code") or index)])
            for index, row in enumerate(eligible)
            if (value := _positive(row.get(field))) is not None
        ]

    methods: dict[str, dict[str, float]] = {}
    eps = _positive(target.get("eps"))
    bvps = _positive(target.get("bvps"))
    revenue = _positive(target.get("revenue"))
    shares = _positive(target.get("total_shares"))
    earnings_growth = _positive(target.get("earnings_growth_rate"))
    growth_metric = "earnings_growth_rate"
    if earnings_growth is None:
        earnings_growth = _positive(target.get("growth_rate"))
        growth_metric = "growth_rate_fallback"

    pe_values = weighted_values("pe")
    if eps is not None and pe_values:
        methods["pe"] = _method_result(pe_values, eps)
    pb_values = weighted_values("pb")
    if bvps is not None and pb_values:
        methods["pb"] = _method_result(pb_values, bvps)
    ps_values = weighted_values("ps")
    if revenue is not None and shares is not None and ps_values:
        methods["ps"] = _method_result(ps_values, revenue / shares)

    peg_values: list[tuple[float, float]] = []
    for index, row in enumerate(eligible):
        peer_pe = _positive(row.get("pe"))
        peer_growth = _positive(row.get("earnings_growth_rate"))
        if peer_growth is None:
            peer_growth = _positive(row.get("growth_rate"))
        if peer_pe is None or peer_growth is None:
            continue
        growth_percent = peer_growth * 100 if peer_growth <= 1 else peer_growth
        if growth_percent > 0:
            peg_values.append(
                (
                    peer_pe / growth_percent,
                    weights[str(row.get("code") or index)],
                )
            )
    if eps is not None and earnings_growth is not None and peg_values:
        target_growth_percent = earnings_growth * 100 if earnings_growth <= 1 else earnings_growth
        methods["peg"] = _method_result(peg_values, target_growth_percent * eps)

    if not methods:
        return model_result(
            "relative",
            "unavailable",
            error="目标指标或同行倍数不足，无法形成相对估值",
            details={
                "formula_version": FORMULA_VERSION,
                "sample_count": len(eligible),
                "excluded_count": len(rows) - len(eligible),
                "methods": {},
                "peer_codes": [str(row.get("code") or "") for row in eligible],
                "growth_metric": growth_metric,
                "peer_weights": weights,
            },
        )

    method_weights = {
        name: _method_quality(method, len(eligible))
        for name, method in methods.items()
    }
    total_method_weight = sum(method_weights.values())
    normalized_method_weights = {
        name: value / total_method_weight
        for name, value in method_weights.items()
    }
    combined = {
        field: sum(
            normalized_method_weights[name] * method[field]
            for name, method in methods.items()
        )
        for field in ("low", "mid", "high")
    }
    low, mid, high = sorted((combined["low"], combined["mid"], combined["high"]))
    warnings: list[str] = []
    missing = sorted({"pe", "pb", "ps", "peg"} - set(methods))
    if missing:
        warnings.append("部分估值方法不可用: " + ", ".join(missing))
    if len(eligible) < 5:
        warnings.append("有效同行样本少于5只")
    confidence = min(1.0, len(eligible) / 8) * (
        sum(method_weights.values()) / len(method_weights)
    )
    return model_result(
        "relative",
        "partial" if warnings else "success",
        low=low,
        mid=mid,
        high=high,
        confidence=min(1.0, confidence),
        details={
            "formula_version": FORMULA_VERSION,
            "sample_count": len(eligible),
            "excluded_count": len(rows) - len(eligible),
            "methods": methods,
            "method_weights": normalized_method_weights,
            "peer_codes": [str(row.get("code") or "") for row in eligible],
            "peer_weights": weights,
            "growth_metric": growth_metric,
            "target_percentiles": {metric: None for metric in _MULTIPLES},
        },
        warnings=warnings,
    )

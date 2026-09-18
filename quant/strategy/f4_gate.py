"""Single deterministic F4 research gate."""

from __future__ import annotations

from typing import Iterable, Mapping

from .f4_contracts import (
    F4_BLOCKED,
    F4_REJECTED,
    F4_RESEARCH_CANDIDATE,
    authority_fields,
)

GATE_VERSION = "f4-gate-v4"


def evaluate_f4_gate(
    metrics: Mapping[str, object], blocked_reasons: Iterable[str]
) -> dict[str, object]:
    blocked = list(dict.fromkeys(str(reason) for reason in blocked_reasons if reason))
    if blocked:
        return {
            "status": F4_BLOCKED,
            "reasons": blocked,
            "gate_version": GATE_VERSION,
            **authority_fields(),
        }
    reasons: list[str] = []
    if int(metrics.get("window_count") or 0) < 4:
        reasons.append("window_count_below_4")
    if float(metrics.get("positive_excess_window_ratio") or 0.0) < 0.60:
        reasons.append("positive_excess_window_ratio_below_0_60")
    if float(metrics.get("after_cost_excess_return") or 0.0) <= 0:
        reasons.append("after_cost_excess_return_not_positive")
    if float(metrics.get("sharpe") or 0.0) < 0.80:
        reasons.append("sharpe_below_0_80")
    if float(metrics.get("max_drawdown") or 0.0) < -0.20:
        reasons.append("max_drawdown_below_minus_0_20")
    if float(metrics.get("double_cost_excess_return") or 0.0) <= 0:
        reasons.append("double_cost_excess_return_not_positive")
    if int(metrics.get("constraint_violation_count") or 0) != 0:
        reasons.append("portfolio_constraint_failed")
    if int(metrics.get("future_data_violation_count") or 0) != 0:
        reasons.append("future_data_detected")
    return {
        "status": F4_REJECTED if reasons else F4_RESEARCH_CANDIDATE,
        "reasons": reasons,
        "gate_version": GATE_VERSION,
        "metrics": dict(metrics),
        **authority_fields(),
    }

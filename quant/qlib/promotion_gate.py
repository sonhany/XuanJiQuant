from __future__ import annotations

import hashlib
import json
from typing import Any


GATE_VERSION = "qlib_phase1_gate_v1"
SIGNAL_LIMITS = {
    "window_count": 4,
    "median_rank_ic": 0.02,
    "median_icir": 0.30,
    "positive_rank_ic_ratio": 0.70,
    "aggregate_sharpe": 0.80,
    "max_drawdown": -0.20,
    "worst_rank_ic": -0.03,
}
BACKTEST_LIMITS = {
    "after_cost_return": 0.0,
    "sharpe": 0.80,
    "max_drawdown": -0.20,
}
DIVERGENCE_LIMITS = {
    "annual_return_abs": 0.05,
    "max_drawdown_abs": 0.05,
    "turnover_relative": 0.25,
}


def _number(payload: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(payload.get(key, default))
    except (TypeError, ValueError):
        return default


def evaluate_signal_stage(
    *,
    quality_passed: bool,
    signal_metrics: dict[str, Any],
) -> dict[str, Any]:
    reasons = []
    if not quality_passed:
        reasons.append("dataset_quality_failed")
    checks = (
        (
            _number(signal_metrics, "window_count", 0) < SIGNAL_LIMITS["window_count"],
            "signal_window_count_below_4",
        ),
        (
            _number(signal_metrics, "median_rank_ic", float("-inf"))
            < SIGNAL_LIMITS["median_rank_ic"],
            "signal_median_rank_ic_below_0_02",
        ),
        (
            _number(signal_metrics, "median_icir", float("-inf"))
            < SIGNAL_LIMITS["median_icir"],
            "signal_median_icir_below_0_30",
        ),
        (
            _number(signal_metrics, "positive_rank_ic_ratio", 0)
            < SIGNAL_LIMITS["positive_rank_ic_ratio"],
            "signal_positive_rank_ic_ratio_below_0_70",
        ),
        (
            _number(signal_metrics, "aggregate_after_cost_long_short", 0) <= 0,
            "signal_after_cost_return_not_positive",
        ),
        (
            _number(signal_metrics, "aggregate_sharpe", float("-inf"))
            < SIGNAL_LIMITS["aggregate_sharpe"],
            "signal_sharpe_below_0_80",
        ),
        (
            _number(signal_metrics, "max_drawdown", float("-inf"))
            < SIGNAL_LIMITS["max_drawdown"],
            "signal_max_drawdown_below_minus_0_20",
        ),
        (
            _number(signal_metrics, "worst_rank_ic", float("-inf"))
            < SIGNAL_LIMITS["worst_rank_ic"],
            "signal_worst_rank_ic_below_minus_0_03",
        ),
    )
    reasons.extend(reason for failed, reason in checks if failed)
    return {
        "status": "candidate" if not reasons else "rejected",
        "reason_codes": reasons,
    }


def _backtest_reasons(prefix: str, metrics: dict[str, Any]) -> list[str]:
    reasons = []
    if _number(metrics, "after_cost_return", float("-inf")) <= 0:
        reasons.append(f"{prefix}_after_cost_return_not_positive")
    if _number(metrics, "sharpe", float("-inf")) < BACKTEST_LIMITS["sharpe"]:
        reasons.append(f"{prefix}_sharpe_below_0_80")
    if (
        _number(metrics, "max_drawdown", float("-inf"))
        < BACKTEST_LIMITS["max_drawdown"]
    ):
        reasons.append(f"{prefix}_max_drawdown_below_minus_0_20")
    return reasons


def _divergence_reasons(
    official: dict[str, Any],
    ashare: dict[str, Any],
) -> list[str]:
    reasons = []
    if abs(
        _number(official, "annual_return", 0)
        - _number(ashare, "annual_return", 0)
    ) > DIVERGENCE_LIMITS["annual_return_abs"]:
        reasons.append("annual_return_divergence")
    if abs(
        _number(official, "max_drawdown", 0)
        - _number(ashare, "max_drawdown", 0)
    ) > DIVERGENCE_LIMITS["max_drawdown_abs"]:
        reasons.append("max_drawdown_divergence")
    official_turnover = abs(_number(official, "annual_turnover", 0))
    ashare_turnover = abs(_number(ashare, "annual_turnover", 0))
    denominator = max(official_turnover, ashare_turnover, 1e-12)
    if (
        abs(official_turnover - ashare_turnover) / denominator
        > DIVERGENCE_LIMITS["turnover_relative"]
    ):
        reasons.append("annual_turnover_divergence")
    return reasons


def evaluate_promotion_gate(
    *,
    quality_passed: bool,
    signal_metrics: dict[str, Any],
    official_backtest: dict[str, Any],
    ashare_backtest: dict[str, Any],
    divergence_reviewed: bool,
) -> dict[str, Any]:
    signal_stage = evaluate_signal_stage(
        quality_passed=quality_passed,
        signal_metrics=signal_metrics,
    )
    hard_failures = [
        *signal_stage["reason_codes"],
        *_backtest_reasons("official", official_backtest),
        *_backtest_reasons("ashare", ashare_backtest),
    ]
    divergence = _divergence_reasons(official_backtest, ashare_backtest)
    if hard_failures:
        status = "rejected"
        reasons = hard_failures
    elif divergence and not divergence_reviewed:
        status = "review_required"
        reasons = divergence
    else:
        status = "candidate"
        reasons = []
    identity = {
        "gate_version": GATE_VERSION,
        "quality_passed": bool(quality_passed),
        "signal_metrics": signal_metrics,
        "official_backtest": official_backtest,
        "ashare_backtest": ashare_backtest,
        "divergence_reviewed": bool(divergence_reviewed),
        "status": status,
        "reason_codes": reasons,
    }
    gate_id = "gate_" + hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:20]
    return {
        **identity,
        "gate_id": gate_id,
        "hard_failure_codes": hard_failures,
        "divergence_codes": divergence,
        "limits": {
            "signal": dict(SIGNAL_LIMITS),
            "backtest": dict(BACKTEST_LIMITS),
            "divergence": dict(DIVERGENCE_LIMITS),
        },
    }

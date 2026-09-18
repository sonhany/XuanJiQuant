"""Portfolio, benchmark and stability metrics for F4 research."""

from __future__ import annotations

import math
from typing import Iterable, Mapping

import numpy as np


_V2_FAMILIES = (
    "momentum",
    "reversal",
    "defensive",
    "liquidity",
    "ensemble",
    "qlib",
)


def _finite(values: Iterable[object]) -> np.ndarray:
    out = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            out.append(number)
    return np.asarray(out, dtype=float)


def calculate_return_metrics(
    portfolio_returns: Iterable[object],
    benchmark_returns: Iterable[object],
    *,
    periods_per_year: int = 252,
) -> dict[str, float]:
    portfolio = _finite(portfolio_returns)
    benchmark = _finite(benchmark_returns)
    count = min(len(portfolio), len(benchmark))
    if count == 0:
        return {
            "period_count": 0,
            "total_return": 0.0,
            "benchmark_return": 0.0,
            "excess_return": 0.0,
            "annual_return": 0.0,
            "annual_volatility": 0.0,
            "sharpe": 0.0,
            "information_ratio": 0.0,
            "max_drawdown": 0.0,
            "calmar": 0.0,
        }
    portfolio = portfolio[:count]
    benchmark = benchmark[:count]
    curve = np.cumprod(1.0 + portfolio)
    benchmark_curve = np.cumprod(1.0 + benchmark)
    total = float(curve[-1] - 1.0)
    benchmark_total = float(benchmark_curve[-1] - 1.0)
    annual = float((1.0 + total) ** (periods_per_year / count) - 1.0) if total > -1 else -1.0
    volatility = float(np.std(portfolio, ddof=1) * math.sqrt(periods_per_year)) if count > 1 else 0.0
    sharpe = float(np.mean(portfolio) / np.std(portfolio, ddof=1) * math.sqrt(periods_per_year)) if count > 1 and np.std(portfolio, ddof=1) > 0 else 0.0
    excess_series = portfolio - benchmark
    information_ratio = float(np.mean(excess_series) / np.std(excess_series, ddof=1) * math.sqrt(periods_per_year)) if count > 1 and np.std(excess_series, ddof=1) > 0 else 0.0
    running_peak = np.maximum.accumulate(curve)
    drawdowns = curve / running_peak - 1.0
    max_drawdown = float(np.min(drawdowns))
    calmar = annual / abs(max_drawdown) if max_drawdown < 0 else 0.0
    return {
        "period_count": int(count),
        "total_return": total,
        "benchmark_return": benchmark_total,
        "excess_return": total - benchmark_total,
        "annual_return": annual,
        "annual_volatility": volatility,
        "sharpe": sharpe,
        "information_ratio": information_ratio,
        "max_drawdown": max_drawdown,
        "calmar": float(calmar),
    }


def aggregate_window_metrics(
    windows: Iterable[Mapping[str, object]],
    *,
    double_cost_excess_return: float,
    constraint_violation_count: int = 0,
    future_data_violation_count: int = 0,
) -> dict[str, float | int]:
    rows = list(windows)
    positive = sum(float(row.get("excess_return") or 0.0) > 0 for row in rows)
    return {
        "window_count": len(rows),
        "positive_excess_window_ratio": positive / len(rows) if rows else 0.0,
        "after_cost_excess_return": float(sum(float(row.get("excess_return") or 0.0) for row in rows)),
        "sharpe": float(np.median([float(row.get("sharpe") or 0.0) for row in rows])) if rows else 0.0,
        "max_drawdown": min((float(row.get("max_drawdown") or 0.0) for row in rows), default=0.0),
        "double_cost_excess_return": float(double_cost_excess_return),
        "constraint_violation_count": int(constraint_violation_count),
        "future_data_violation_count": int(future_data_violation_count),
    }


def aggregate_v2_window_metrics(
    *,
    locked_tests: Iterable[Mapping[str, object]],
    validation_rows: Iterable[Mapping[str, object]] = (),
    double_cost_excess_return: float,
    constraint_violation_count: int = 0,
    future_data_violation_count: int = 0,
) -> dict[str, float | int]:
    """Aggregate only locked-winner test rows; validation is audit-only input."""

    del validation_rows
    rows = list(locked_tests)
    window_ids: set[str] = set()
    for row in rows:
        window_id = str(row.get("window_id") or "")
        candidate_id = str(row.get("candidate_id") or "")
        if not window_id or not candidate_id or window_id in window_ids:
            raise ValueError("f4_v2_locked_test_identity_invalid")
        window_ids.add(window_id)
        for field in ("excess_return", "sharpe", "max_drawdown"):
            value = row.get(field)
            if type(value) not in {int, float} or not math.isfinite(float(value)):
                raise ValueError("f4_v2_metric_non_finite")
    if type(double_cost_excess_return) not in {int, float} or not math.isfinite(
        float(double_cost_excess_return)
    ):
        raise ValueError("f4_v2_metric_non_finite")
    return aggregate_window_metrics(
        rows,
        double_cost_excess_return=double_cost_excess_return,
        constraint_violation_count=constraint_violation_count,
        future_data_violation_count=future_data_violation_count,
    )


def build_family_diagnostics(
    registry: Iterable[object],
    candidate_statuses: Iterable[Mapping[str, object]],
    selection_locks: Iterable[Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    """Build deterministic six-family research diagnostics without gate effects."""

    candidates = tuple(registry)
    statuses = tuple(candidate_statuses)
    locks = tuple(selection_locks)
    known_ids = {str(getattr(candidate, "candidate_id")): str(getattr(candidate, "family")) for candidate in candidates}
    if set(known_ids.values()) != set(_V2_FAMILIES):
        raise ValueError("f4_v2_family_registry_invalid")
    reason_counts: dict[str, dict[str, int]] = {family: {} for family in _V2_FAMILIES}
    available = {family: 0 for family in _V2_FAMILIES}
    unavailable = {family: 0 for family in _V2_FAMILIES}
    status_ids: set[str] = set()
    for status in statuses:
        candidate_id = str(status.get("candidate_id") or "")
        family = str(status.get("family") or known_ids.get(candidate_id, ""))
        if known_ids.get(candidate_id) != family or candidate_id in status_ids:
            raise ValueError("f4_v2_family_status_identity_invalid")
        status_ids.add(candidate_id)
        is_available = status.get("available") is True
        (available if is_available else unavailable)[family] += 1
        reason = str(status.get("reason_code") or "")
        if not is_available and reason:
            reason_counts[family][reason] = reason_counts[family].get(reason, 0) + 1
    wins = {family: 0 for family in _V2_FAMILIES}
    lock_windows: set[str] = set()
    for lock in locks:
        window_id = str(lock.get("window_id") or "")
        candidate_id = str(lock.get("candidate_id") or "")
        family = str(lock.get("family") or known_ids.get(candidate_id, ""))
        if (
            not window_id
            or window_id in lock_windows
            or known_ids.get(candidate_id) != family
        ):
            raise ValueError("f4_v2_family_lock_identity_invalid")
        lock_windows.add(window_id)
        wins[family] += 1
    return {
        family: {
            "registered": sum(value == family for value in known_ids.values()),
            "available": available[family],
            "unavailable": unavailable[family],
            "validation_wins": wins[family],
            "reason_counts": dict(sorted(reason_counts[family].items())),
        }
        for family in _V2_FAMILIES
    }

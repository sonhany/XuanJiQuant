from __future__ import annotations

from statistics import median
from typing import Any, Iterable

import pandas as pd


def _last_on_or_before(calendar: pd.DatetimeIndex, value: pd.Timestamp) -> pd.Timestamp | None:
    eligible = calendar[calendar <= value]
    return eligible[-1] if len(eligible) else None


def _first_on_or_after(calendar: pd.DatetimeIndex, value: pd.Timestamp) -> pd.Timestamp | None:
    eligible = calendar[calendar >= value]
    return eligible[0] if len(eligible) else None


def build_walk_forward_windows(
    calendar: Iterable[Any],
    *,
    train_months: int = 36,
    valid_months: int = 6,
    test_months: int = 6,
    step_months: int = 3,
) -> list[dict[str, Any]]:
    values = pd.DatetimeIndex(calendar).drop_duplicates().sort_values()
    if values.empty:
        return []
    windows = []
    anchor = values[0]
    index = 1
    while True:
        train_start = _first_on_or_after(values, anchor)
        train_end = _last_on_or_before(
            values,
            anchor + pd.DateOffset(months=train_months) - pd.Timedelta(days=1),
        )
        valid_start = _first_on_or_after(
            values,
            anchor + pd.DateOffset(months=train_months),
        )
        valid_end = _last_on_or_before(
            values,
            anchor
            + pd.DateOffset(months=train_months + valid_months)
            - pd.Timedelta(days=1),
        )
        test_start = _first_on_or_after(
            values,
            anchor + pd.DateOffset(months=train_months + valid_months),
        )
        test_end = _last_on_or_before(
            values,
            anchor
            + pd.DateOffset(months=train_months + valid_months + test_months)
            - pd.Timedelta(days=1),
        )
        if None in {train_start, train_end, valid_start, valid_end, test_start, test_end}:
            break
        if test_end > values[-1] or test_start > test_end:
            break
        windows.append(
            {
                "id": f"wf_{index:02d}_{test_start:%Y%m%d}_{test_end:%Y%m%d}",
                "train": (train_start.strftime("%Y-%m-%d"), train_end.strftime("%Y-%m-%d")),
                "valid": (valid_start.strftime("%Y-%m-%d"), valid_end.strftime("%Y-%m-%d")),
                "test": (test_start.strftime("%Y-%m-%d"), test_end.strftime("%Y-%m-%d")),
            }
        )
        anchor += pd.DateOffset(months=step_months)
        index += 1
    return windows


def aggregate_walk_forward_metrics(windows: Iterable[dict[str, Any]]) -> dict[str, float]:
    rows = list(windows)
    if not rows:
        return {}
    rank_ics = [float(row.get("rank_ic") or 0) for row in rows]
    return {
        "window_count": len(rows),
        "median_rank_ic": median(rank_ics),
        "median_icir": median(float(row.get("icir") or 0) for row in rows),
        "positive_rank_ic_ratio": sum(value > 0 for value in rank_ics) / len(rows),
        "aggregate_after_cost_long_short": sum(
            float(row.get("after_cost_long_short") or 0) for row in rows
        ),
        "aggregate_sharpe": median(float(row.get("sharpe") or 0) for row in rows),
        "max_drawdown": min(float(row.get("max_drawdown") or 0) for row in rows),
        "worst_rank_ic": min(rank_ics),
    }


def aggregate_promotion_status(
    windows: Iterable[dict[str, Any]],
    quality_passed: bool,
) -> str:
    metrics = aggregate_walk_forward_metrics(windows)
    from .promotion_gate import evaluate_signal_stage

    return evaluate_signal_stage(
        quality_passed=quality_passed,
        signal_metrics=metrics,
    )["status"]

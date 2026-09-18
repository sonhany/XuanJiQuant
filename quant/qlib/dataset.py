from __future__ import annotations

from typing import Iterable

import pandas as pd


def build_excess_label(
    close: pd.Series,
    benchmark_close: pd.Series,
    *,
    horizon: int = 5,
) -> pd.Series:
    stock_return = close.shift(-horizon) / close - 1.0
    benchmark_return = benchmark_close.shift(-horizon) / benchmark_close - 1.0
    return stock_return - benchmark_return


def chronological_segments(
    dates: Iterable,
    *,
    train_ratio: float = 0.6,
    valid_ratio: float = 0.2,
) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    ordered = pd.DatetimeIndex(sorted(pd.to_datetime(list(dates)).unique()))
    if len(ordered) < 3:
        raise ValueError("at least three dates are required")
    train_end = max(1, int(len(ordered) * train_ratio))
    valid_end = max(train_end + 1, int(len(ordered) * (train_ratio + valid_ratio)))
    valid_end = min(valid_end, len(ordered) - 1)
    return {
        "train": (ordered[0], ordered[train_end - 1]),
        "valid": (ordered[train_end], ordered[valid_end - 1]),
        "test": (ordered[valid_end], ordered[-1]),
    }


def eligible_instrument(
    code: str,
    name: str,
    valid_days: int,
    total_days: int,
) -> tuple[bool, str]:
    pure = str(code).upper().replace("SH", "").replace("SZ", "").replace("BJ", "")[:6]
    upper_name = str(name or "").upper()
    if pure.startswith("920"):
        return False, "excluded_920"
    if "ST" in upper_name or "退" in str(name or ""):
        return False, "special_treatment_or_delisting"
    if total_days < 120:
        return False, "listing_history_lt_120"
    if valid_days < 18:
        return False, "valid_days_lt_18_of_20"
    return True, ""

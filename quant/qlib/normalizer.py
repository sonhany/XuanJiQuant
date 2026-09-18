from __future__ import annotations

from datetime import datetime
from typing import Iterable

import pandas as pd


REQUIRED_COLUMNS = [
    "instrument",
    "datetime",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
]
PIT_COLUMNS = [
    "tradable",
    "is_st",
    "st_unknown",
    "listed",
    "delisted",
    "paused",
    "limit_up",
    "limit_down",
]


class DataQualityError(ValueError):
    pass


def normalize_daily_bars(
    rows: Iterable[dict],
    *,
    data_version: str = "",
) -> pd.DataFrame:
    frame = pd.DataFrame(list(rows))
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise DataQualityError(f"missing columns: {', '.join(missing)}")
    frame = frame.copy()
    frame["instrument"] = frame["instrument"].astype(str).str.upper()
    frame["datetime"] = pd.to_datetime(frame["datetime"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume", "amount", "factor"):
        if column not in frame.columns:
            frame[column] = 1.0 if column == "factor" else 0.0
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame["datetime"].isna().any():
        raise DataQualityError("invalid datetime")
    if frame.duplicated(["instrument", "datetime"]).any():
        raise DataQualityError("duplicate instrument/datetime rows")
    invalid_price = (
        (frame[["open", "high", "low", "close"]] <= 0).any(axis=1)
        | (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
        | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
    )
    if invalid_price.any():
        raise DataQualityError("invalid OHLC relationship")
    frame["volume"] = frame["volume"].fillna(0).clip(lower=0)
    frame["amount"] = frame["amount"].fillna(0).clip(lower=0)
    frame["factor"] = frame["factor"].fillna(1.0)
    frame["source"] = frame.get("source", "unknown")
    frame["fetched_at"] = frame.get(
        "fetched_at",
        datetime.now().astimezone().isoformat(timespec="seconds"),
    )
    frame["data_version"] = data_version or "unversioned"
    frame["paused"] = (frame["volume"] <= 0).astype(int)
    defaults = {
        "tradable": 1,
        "is_st": 0,
        "st_unknown": 0,
        "listed": 1,
        "delisted": 0,
        "limit_up": 0,
        "limit_down": 0,
    }
    for column in PIT_COLUMNS:
        if column not in frame.columns:
            frame[column] = defaults.get(column, 0)
        frame[column] = (
            pd.to_numeric(frame[column], errors="coerce")
            .fillna(defaults.get(column, 0))
            .astype(int)
        )
    return frame.sort_values(["datetime", "instrument"]).reset_index(drop=True)

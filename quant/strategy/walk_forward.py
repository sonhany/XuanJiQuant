"""Deterministic purged walk-forward windows for F4 research."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from .f4_contracts import F4Blocked


@dataclass(frozen=True, slots=True)
class F4Window:
    window_id: str
    train_dates: tuple[pd.Timestamp, ...]
    valid_dates: tuple[pd.Timestamp, ...]
    test_dates: tuple[pd.Timestamp, ...]
    purge_bars: int
    embargo_bars: int

    @property
    def train_end(self) -> pd.Timestamp:
        return self.train_dates[-1]

    @property
    def valid_start(self) -> pd.Timestamp:
        return self.valid_dates[0]

    @property
    def valid_end(self) -> pd.Timestamp:
        return self.valid_dates[-1]

    @property
    def test_start(self) -> pd.Timestamp:
        return self.test_dates[0]

    @property
    def test_end(self) -> pd.Timestamp:
        return self.test_dates[-1]

    def to_dict(self) -> dict[str, object]:
        return {
            "window_id": self.window_id,
            "train": [str(self.train_dates[0].date()), str(self.train_end.date())],
            "valid": [str(self.valid_start.date()), str(self.valid_end.date())],
            "test": [str(self.test_start.date()), str(self.test_end.date())],
            "purge_bars": self.purge_bars,
            "embargo_bars": self.embargo_bars,
        }


def build_f4_windows(
    calendar: Iterable[object],
    *,
    train_bars: int = 504,
    valid_bars: int = 126,
    test_bars: int = 126,
    purge_bars: int = 20,
    embargo_bars: int = 5,
    step_bars: int = 126,
    minimum_windows: int = 4,
) -> list[F4Window]:
    raw = [pd.Timestamp(value).normalize() for value in calendar]
    if len(set(raw)) != len(raw):
        raise F4Blocked("walk_forward_calendar_duplicate")
    dates = sorted(raw)
    required = train_bars + purge_bars + valid_bars + embargo_bars + test_bars
    windows: list[F4Window] = []
    start = 0
    while start + required <= len(dates):
        train_start = start
        train_end = train_start + train_bars
        valid_start = train_end + purge_bars
        valid_end = valid_start + valid_bars
        test_start = valid_end + embargo_bars
        test_end = test_start + test_bars
        index = len(windows) + 1
        windows.append(
            F4Window(
                window_id=f"wf-{index:02d}",
                train_dates=tuple(dates[train_start:train_end]),
                valid_dates=tuple(dates[valid_start:valid_end]),
                test_dates=tuple(dates[test_start:test_end]),
                purge_bars=purge_bars,
                embargo_bars=embargo_bars,
            )
        )
        start += step_bars
    if len(windows) < minimum_windows:
        raise F4Blocked(
            "walk_forward_window_insufficient",
            f"actual={len(windows)} required={minimum_windows}",
        )
    return windows

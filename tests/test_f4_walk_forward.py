import pandas as pd
import pytest

from quant.strategy.f4_contracts import F4Blocked
from quant.strategy.walk_forward import build_f4_windows


def test_windows_are_non_overlapping_and_apply_purge_and_embargo():
    calendar = pd.bdate_range("2020-01-01", periods=1300)
    windows = build_f4_windows(calendar)
    assert len(windows) >= 4
    for window in windows:
        assert window.train_end < window.valid_start
        assert window.valid_end < window.test_start
        assert window.purge_bars == 20
        assert window.embargo_bars == 5
        assert len(window.train_dates) == 504
        assert len(window.valid_dates) == 126
        assert len(window.test_dates) == 126


def test_insufficient_calendar_fails_closed():
    with pytest.raises(F4Blocked, match="walk_forward_window_insufficient"):
        build_f4_windows(pd.bdate_range("2024-01-01", periods=800))


def test_duplicate_calendar_date_fails_closed():
    calendar = list(pd.bdate_range("2020-01-01", periods=1300))
    calendar.append(calendar[-1])
    with pytest.raises(F4Blocked, match="walk_forward_calendar_duplicate"):
        build_f4_windows(calendar)

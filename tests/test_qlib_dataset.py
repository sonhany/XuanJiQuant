import pandas as pd
import pytest


def test_five_day_excess_label_uses_future_only():
    from quant.qlib.dataset import build_excess_label

    index = pd.date_range("2026-01-01", periods=6)
    close = pd.Series([10, 11, 12, 13, 14, 15], index=index)
    benchmark = pd.Series([100, 101, 102, 103, 104, 105], index=index)

    label = build_excess_label(close, benchmark, horizon=5)

    expected = (15 / 10 - 1) - (105 / 100 - 1)
    assert label.iloc[0] == pytest.approx(expected)
    assert label.iloc[1:].isna().all()


def test_chronological_split_does_not_overlap():
    from quant.qlib.dataset import chronological_segments

    dates = pd.date_range("2024-01-01", periods=100, freq="B")
    segments = chronological_segments(dates)

    assert segments["train"][1] < segments["valid"][0]
    assert segments["valid"][1] < segments["test"][0]
    assert segments["train"][0] == dates[0]
    assert segments["test"][1] == dates[-1]

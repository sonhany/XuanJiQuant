import pandas as pd

from quant.strategy.engine import expanding_zscore


def test_expanding_zscore_does_not_change_history_when_future_changes():
    left = expanding_zscore(pd.Series([1.0, 2.0, 3.0, 100.0]))
    right = expanding_zscore(pd.Series([1.0, 2.0, 3.0, -100.0]))

    pd.testing.assert_series_equal(left.iloc[:3], right.iloc[:3])

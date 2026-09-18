from __future__ import annotations

import warnings

import pandas as pd

from quant.factor.price_volume import compute_price_volume


def test_zero_volume_pct_change_has_explicit_stable_fill_semantics():
    frame = pd.DataFrame(
        {
            "open": [10.0, 10.0, 10.0],
            "high": [10.5, 10.5, 10.5],
            "low": [9.5, 9.5, 9.5],
            "close": [10.0, 10.1, 10.2],
            "volume": [100.0, 0.0, 120.0],
            "amount": [1000.0, 0.0, 1224.0],
        }
    )

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        result = compute_price_volume(frame)

    assert not [item for item in captured if issubclass(item.category, FutureWarning)]
    assert "pvbeta_20" in result

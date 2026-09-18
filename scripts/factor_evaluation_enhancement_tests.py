from __future__ import annotations

import pandas as pd


def test_factor_evaluation_window_group_cost_and_correlation_metrics():
    from quant.factor.evaluation import (
        build_evaluation_metadata,
        factor_correlation_top,
        group_and_long_short_returns,
    )

    mf = {
        "000001": pd.DataFrame({"date": ["20260101", "20260102"], "alpha": [0.1, 0.4], "beta": [1.0, 0.7]}),
        "000002": pd.DataFrame({"date": ["20260101", "20260102"], "alpha": [0.3, 0.2], "beta": [0.8, 0.9]}),
        "000003": pd.DataFrame({"date": ["20260101", "20260102"], "alpha": [0.5, 0.1], "beta": [0.6, 1.0]}),
    }
    mk = {
        "000001": pd.DataFrame({"date": ["20260101", "20260102"], "close": [10.0, 11.0]}),
        "000002": pd.DataFrame({"date": ["20260101", "20260102"], "close": [20.0, 21.0]}),
        "000003": pd.DataFrame({"date": ["20260101", "20260102"], "close": [30.0, 29.0]}),
    }

    meta = build_evaluation_metadata(mk, lookback_bars=300, fwd_horizons=[1, 5, 10, 20])
    assert meta["data_start_date"] == "20260101"
    assert meta["data_end_date"] == "20260102"
    assert meta["latest_kline_date"] == "20260102"
    assert meta["lookback_bars"] == 300
    assert meta["fwd_horizons"] == [1, 5, 10, 20]

    long_df = pd.DataFrame(
        [
            {"date": "20260101", "code": "000001", "alpha": 0.1, "fwd_1": 0.01},
            {"date": "20260101", "code": "000002", "alpha": 0.3, "fwd_1": 0.02},
            {"date": "20260101", "code": "000003", "alpha": 0.5, "fwd_1": 0.03},
            {"date": "20260102", "code": "000001", "alpha": 0.4, "fwd_1": 0.03},
            {"date": "20260102", "code": "000002", "alpha": 0.2, "fwd_1": 0.01},
            {"date": "20260102", "code": "000003", "alpha": 0.1, "fwd_1": -0.01},
        ]
    )
    metrics = group_and_long_short_returns(long_df, "alpha", horizon=1, n_groups=3, cost_bps=20)
    assert metrics["groups"]["top"]["mean_return"] != 0
    assert metrics["long_short"]["mean_return"] > 0
    assert metrics["long_short_after_cost"]["mean_return"] < metrics["long_short"]["mean_return"]
    assert metrics["turnover"] > 0

    corr = factor_correlation_top(mf, factor_names=["alpha", "beta"], top_n=1)
    assert corr["alpha"][0]["factor"] == "beta"
    assert "correlation" in corr["alpha"][0]


def test_evaluate_factors_script_declares_enhanced_outputs():
    src = open("scripts/evaluate_factors.py", encoding="utf-8").read()

    assert "fwd_horizons=[1, 5, 10, 20]" in src
    assert "build_evaluation_metadata" in src
    assert "group_and_long_short_returns" in src
    assert "factor_correlation_top" in src
    assert "long_short_after_cost" in src
    assert "build_factor_snapshot_latest" in src

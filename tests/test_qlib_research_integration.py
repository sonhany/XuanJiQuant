import pandas as pd

from quant.factor import FactorEngine
from quant.strategy import StrategyEngine


def _bars(code: str, closes: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=len(closes), freq="D").strftime("%Y%m%d")
    return pd.DataFrame(
        {
            "date": dates,
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1000] * len(closes),
            "amount": [c * 1000 for c in closes],
            "code": code,
        }
    )


class _ScoreFactorEngine:
    def compute_multi(self, klines_dict, use_cache=False):
        return {
            "000001": pd.DataFrame({"date": ["20240101", "20240102", "20240103"], "score": [3.0, 3.0, 1.0]}),
            "000002": pd.DataFrame({"date": ["20240101", "20240102", "20240103"], "score": [2.0, 2.0, 3.0]}),
            "000003": pd.DataFrame({"date": ["20240101", "20240102", "20240103"], "score": [1.0, 1.0, 2.0]}),
        }


def test_topk_dropout_keeps_topk_and_rotates_only_drop_count():
    klines = {
        "000001": _bars("000001", [10, 11, 10, 10.5]),
        "000002": _bars("000002", [10, 10.2, 10.4, 10.6]),
        "000003": _bars("000003", [10, 10.1, 10.3, 10.7]),
    }
    engine = StrategyEngine(factor_engine=_ScoreFactorEngine())

    result = engine.run_strategy(
        "topk_dropout",
        {"factor_name": "score", "topk": 2, "n_drop": 1},
        klines,
    )

    assert result["signals"]["000001"] == [
        {"date": "20240101", "signal": 1, "score": 3.0, "rank": 1, "topk": 2},
        {"date": "20240103", "signal": 0, "score": 1.0, "rank": 3, "topk": 2},
    ]
    assert result["signals"]["000002"] == [
        {"date": "20240101", "signal": 1, "score": 2.0, "rank": 2, "topk": 2}
    ]
    assert result["signals"]["000003"] == [
        {"date": "20240103", "signal": 1, "score": 2.0, "rank": 2, "topk": 2}
    ]


def test_qlib_adapter_converts_kline_dict_to_panel():
    from quant.qlib_adapter import to_qlib_panel

    panel = to_qlib_panel(
        {
            "000001": _bars("000001", [10, 11]),
            "600000": _bars("600000", [20, 21]),
        }
    )

    assert list(panel.columns) == [
        "datetime",
        "instrument",
        "$open",
        "$high",
        "$low",
        "$close",
        "$volume",
        "$amount",
    ]
    assert panel["instrument"].tolist() == ["000001", "600000", "000001", "600000"]
    assert panel["datetime"].tolist() == ["2024-01-01", "2024-01-01", "2024-01-02", "2024-01-02"]


def test_factor_engine_returns_qlib_style_train_valid_test_metrics():
    dates = pd.date_range("2024-01-01", periods=15, freq="D").strftime("%Y%m%d")
    multi_factor = {}
    multi_klines = {}
    for idx, code in enumerate(["000001", "000002", "000003", "000004"]):
        closes = [10 + idx + day * (0.1 + idx * 0.02) for day in range(15)]
        multi_klines[code] = _bars(code, closes)
        multi_factor[code] = pd.DataFrame(
            {
                "date": dates,
                "alpha_score": [idx + day * 0.01 for day in range(15)],
            }
        )

    result = FactorEngine().evaluate_factor_segments(
        multi_factor,
        multi_klines,
        "alpha_score",
        fwd_horizons=[1, 5],
    )

    assert result["factor_name"] == "alpha_score"
    assert set(result["segments"]) == {"train", "valid", "test", "all"}
    assert result["segments"]["train"]["date_range"][1] < result["segments"]["valid"]["date_range"][0]
    assert result["segments"]["valid"]["date_range"][1] < result["segments"]["test"]["date_range"][0]
    assert result["segments"]["all"]["decay"]["1d"]["n_periods"] > 0
    assert result["segments"]["all"]["decay"]["5d"]["n_periods"] > 0

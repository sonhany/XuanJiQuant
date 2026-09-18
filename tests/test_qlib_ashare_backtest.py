import pandas as pd
import pytest

from quant.qlib.ashare_backtest import (
    ASHARE_BACKTEST_V1,
    build_signal_bundle,
    run_ashare_backtest,
)


def sample_prediction():
    index = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2026-07-01"), "SH600000"),
            (pd.Timestamp("2026-07-01"), "SZ000001"),
            (pd.Timestamp("2026-07-02"), "SH600000"),
            (pd.Timestamp("2026-07-02"), "SZ000001"),
        ],
        names=["datetime", "instrument"],
    )
    return pd.Series([0.8, 0.2, 0.1, 0.9], index=index, name="score")


def test_signal_bundle_has_provenance_and_no_orders():
    bundle = build_signal_bundle(
        prediction=sample_prediction(),
        workflow_run_id="wf_1",
        dataset_version="daily-pit-v1",
        topk=1,
        n_drop=1,
    )

    assert len(bundle["signal_hash"]) == 64
    assert "orders" not in bundle
    assert bundle["signals"]["600000"] == [
        {"date": "2026-07-01", "score": 0.8, "signal": 1},
        {"date": "2026-07-02", "score": 0.1, "signal": -1},
    ]
    assert bundle["signals"]["000001"][-1]["signal"] == 1


def test_signal_bundle_excludes_reference_benchmark_from_trading_signals():
    index = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2026-01-02"), "SH000300"),
            (pd.Timestamp("2026-01-02"), "SH600000"),
        ],
        names=["datetime", "instrument"],
    )
    prediction = pd.Series([9.0, 1.0], index=index)

    bundle = build_signal_bundle(
        prediction,
        "workflow-1",
        "dataset-v1",
        topk=1,
        n_drop=1,
        excluded_instruments={"SH000300"},
    )

    assert set(bundle["signals"]) == {"600000"}


def test_signal_bundle_only_emits_position_change_events():
    index = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2026-01-02"), "SH600000"),
            (pd.Timestamp("2026-01-02"), "SZ000001"),
            (pd.Timestamp("2026-01-02"), "SH600001"),
            (pd.Timestamp("2026-01-05"), "SH600000"),
            (pd.Timestamp("2026-01-05"), "SZ000001"),
            (pd.Timestamp("2026-01-05"), "SH600001"),
        ],
        names=["datetime", "instrument"],
    )
    prediction = pd.Series([3.0, 2.0, 1.0, 3.0, 2.0, 1.0], index=index)

    bundle = build_signal_bundle(
        prediction,
        "workflow-1",
        "dataset-v1",
        topk=2,
        n_drop=1,
    )

    assert set(bundle["signals"]) == {"600000", "000001"}
    assert all(
        event["signal"] != 0
        for events in bundle["signals"].values()
        for event in events
    )
    assert sum(len(events) for events in bundle["signals"].values()) == 2


class CapturingSimulator:
    kwargs = {}

    def __init__(self, **kwargs):
        type(self).kwargs = kwargs

    def add_signals(self, signals):
        self.signals = signals

    def add_klines(self, klines):
        self.klines = klines

    def run(self):
        return {"metrics": {"sharpe": 1.0}}


def test_bridge_passes_all_market_rules_to_simulator():
    bundle = build_signal_bundle(
        sample_prediction(),
        "wf_1",
        "daily-pit-v1",
        topk=1,
        n_drop=1,
    )
    result = run_ashare_backtest(
        signal_bundle=bundle,
        klines={
            "600000": pd.DataFrame(
                [
                    {
                        "date": "2026-07-01",
                        "open": 10,
                        "high": 10.2,
                        "low": 9.8,
                        "close": 10.1,
                        "amount": 1_000_000,
                        "paused": 0,
                        "tradable": 1,
                    }
                ]
            ),
            "000001": pd.DataFrame(
                [
                    {
                        "date": "2026-07-01",
                        "open": 12,
                        "high": 12.2,
                        "low": 11.8,
                        "close": 12.1,
                        "amount": 1_000_000,
                        "paused": 0,
                        "tradable": 1,
                    }
                ]
            ),
        },
        config=ASHARE_BACKTEST_V1,
        simulator_factory=CapturingSimulator,
    )

    assert CapturingSimulator.kwargs["enforce_t1"] is True
    assert CapturingSimulator.kwargs["enforce_limit"] is True
    assert CapturingSimulator.kwargs["stamp_tax_rate"] == 0.001
    assert CapturingSimulator.kwargs["max_volume_pct"] == 0.10
    assert result["engine"] == "xuanji_ashare"
    assert result["signal_hash"] == bundle["signal_hash"]
    assert result["config_version"] == "ashare_backtest_v1"


def test_bridge_rejects_missing_required_market_columns():
    bundle = build_signal_bundle(
        sample_prediction(), "wf_1", "daily-pit-v1", topk=1, n_drop=1
    )

    with pytest.raises(ValueError, match="missing columns: amount"):
        run_ashare_backtest(
            signal_bundle=bundle,
            klines={
                "600000": pd.DataFrame(
                    [
                        {
                            "date": "2026-07-01",
                            "open": 10,
                            "high": 10,
                            "low": 10,
                            "close": 10,
                        }
                    ]
                ),
                "000001": pd.DataFrame(
                    [
                        {
                            "date": "2026-07-01",
                            "open": 12,
                            "high": 12,
                            "low": 12,
                            "close": 12,
                            "amount": 1_000_000,
                        }
                    ]
                ),
            },
        )

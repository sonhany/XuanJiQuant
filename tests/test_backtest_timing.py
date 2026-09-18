import json

import pandas as pd

from quant.backtest.engine import BacktestSimulator, PerformanceTracker, PortfolioSnapshot


def bars():
    return pd.DataFrame([
        {"date": "20260105", "open": 10, "high": 10.5, "low": 9.5, "close": 10, "volume": 100000, "amount": 1_000_000},
        {"date": "20260106", "open": 11, "high": 12.5, "low": 10.5, "close": 12, "volume": 100000, "amount": 1_200_000},
        {"date": "20260107", "open": 9, "high": 10, "low": 8.5, "close": 9, "volume": 100000, "amount": 900_000},
    ])


def test_signal_executes_on_next_trading_day_open_and_negative_signal_flattens():
    sim = BacktestSimulator(
        initial_cash=100_000,
        commission_rate=0,
        slippage_rate=0,
        enforce_limit=False,
        enforce_t1=True,
        max_volume_pct=1,
    )
    sim.add_klines({"600519": bars()})
    sim.add_signals({
        "600519": [
            {"date": "20260105", "signal": 1},
            {"date": "20260106", "signal": -1},
        ],
    })

    result = sim.run()

    assert [(row["date"], row["direction"], row["price"]) for row in result["fills"]] == [
        ("20260106", "buy", 11.0),
        ("20260107", "sell", 9.0),
    ]

    serialized = json.dumps(result)
    assert '"type": "fill"' in serialized


def test_performance_total_return_is_measured_from_initial_cash():
    tracker = PerformanceTracker(1000)
    tracker.add_snapshot(PortfolioSnapshot("20260105", 990, 990, 0, 0, 0, {}))
    tracker.add_snapshot(PortfolioSnapshot("20260106", 990, 990, 0, 0, 0, {}))

    assert tracker.compute_metrics()["total_return_pct"] == -1.0


def test_pending_order_is_rejected_when_next_day_is_suspended():
    frame = pd.DataFrame(
        [
            {
                "date": "20260105",
                "open": 10,
                "high": 10,
                "low": 10,
                "close": 10,
                "volume": 100000,
                "amount": 1_000_000,
                "paused": 0,
                "tradable": 1,
            },
            {
                "date": "20260106",
                "open": 10,
                "high": 10,
                "low": 10,
                "close": 10,
                "volume": 0,
                "amount": 0,
                "paused": 1,
                "tradable": 0,
            },
        ]
    )
    sim = BacktestSimulator(
        initial_cash=100_000,
        commission_rate=0,
        slippage_rate=0,
        enforce_limit=False,
        enforce_t1=True,
        max_volume_pct=1,
    )
    sim.add_klines({"600519": frame})
    sim.add_signals({"600519": [{"date": "20260105", "signal": 1}]})

    result = sim.run()

    assert result["metrics"]["fill_count"] == 0
    assert result["metrics"]["suspended_rejected"] == 1
    assert any(row["type"] == "suspended_rejected" for row in result["event_log"])

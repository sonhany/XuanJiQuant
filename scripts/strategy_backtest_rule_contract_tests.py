from __future__ import annotations

import pandas as pd


def test_backtest_applies_min_commission_stamp_tax_and_exposes_rule_config():
    from quant.backtest import BacktestSimulator

    sim = BacktestSimulator(
        initial_cash=100_000,
        commission_rate=0.0003,
        min_commission=5,
        stamp_tax_rate=0.0005,
        slippage_rate=0,
        position_size_pct=0.2,
        enforce_limit=False,
    )
    klines = {
        "000001": pd.DataFrame(
            {
                "date": ["20260101", "20260102", "20260103"],
                "open": [10, 10, 10],
                "high": [10, 10, 10],
                "low": [10, 10, 10],
                "close": [10, 10, 10],
                "volume": [1_000_000, 1_000_000, 1_000_000],
                "amount": [10_000_000, 10_000_000, 10_000_000],
            }
        )
    }
    sim.add_klines(klines)
    sim.add_signals({"000001": [{"date": "20260101", "signal": 1}, {"date": "20260102", "signal": 0}]})

    result = sim.run()
    metrics = result["metrics"]

    assert metrics["rules"]["min_commission"] == 5
    assert metrics["rules"]["stamp_tax_rate"] == 0.0005
    assert metrics["commission_paid"] >= 10
    assert metrics["stamp_tax_paid"] > 0


def test_strategy_engine_passes_unified_backtest_rules():
    from quant.strategy.engine import StrategyEngine

    src = open("quant/strategy/engine.py", encoding="utf-8").read()

    assert "min_commission" in src
    assert "stamp_tax_rate" in src
    assert "enforce_t1" in src
    assert "BacktestSimulator" in src
    assert "params.get(\"commission_rate\"" in src

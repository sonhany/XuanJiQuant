"""Tests for BigQuant architecture gap fixes:
- Strategy Callback Framework
- Multi-Frequency Backtest
- Data Prefetch
- Stop-Loss Engine
"""
import pytest
import numpy as np
import pandas as pd


# ═══════════════════════════════════════════════════════════════
# 1. Strategy Callback Framework
# ═══════════════════════════════════════════════════════════════

class TestCallbackFramework:
    def test_null_callback(self):
        from quant.strategy.callbacks import NullCallback, StrategyContext, BarEvent
        cb = NullCallback()
        ctx = StrategyContext(cash=1_000_000)
        cb.on_init(ctx)
        bar = BarEvent(code="000001", date="20260901", frequency="1d",
                       open=10, high=11, low=9, close=10.5)
        cb.on_bar(ctx, bar)
        cb.on_stop(ctx)

    def test_dispatcher(self):
        from quant.strategy.callbacks import CallbackDispatcher, NullCallback, StrategyContext, BarEvent
        dispatcher = CallbackDispatcher()
        cb1 = NullCallback()
        cb2 = NullCallback()
        dispatcher.register(cb1)
        dispatcher.register(cb2)
        ctx = StrategyContext()
        bar = BarEvent(code="000001", date="20260901", frequency="1d",
                       open=10, high=11, low=9, close=10.5)
        dispatcher.dispatch_bar(ctx, bar)  # should not raise
        dispatcher.dispatch_stop(ctx)

    def test_context_state(self):
        from quant.strategy.callbacks import StrategyContext
        ctx = StrategyContext(cash=500_000)
        ctx.set_state("last_signal", "buy")
        assert ctx.get_state("last_signal") == "buy"
        assert ctx.get_state("missing", "default") == "default"

    def test_callback_protocol(self):
        from quant.strategy.callbacks import StrategyCallback, NullCallback
        assert isinstance(NullCallback(), StrategyCallback)


# ═══════════════════════════════════════════════════════════════
# 2. Multi-Frequency Backtest
# ═══════════════════════════════════════════════════════════════

class TestMultiFreqBacktest:
    def _make_data(self, n_bars=200, frequency="1d"):
        np.random.seed(42)
        if frequency == "1d":
            timestamps = pd.date_range("20260101", periods=n_bars, freq="B").strftime("%Y%m%d").tolist()
        elif frequency == "1m":
            timestamps = pd.date_range("20260901 09:30", periods=n_bars, freq="min").strftime("%Y%m%d %H:%M").tolist()
        else:
            timestamps = [f"20260901 {9+i//60:02d}:{i%60:02d}:{(i*3)%60:02d}" for i in range(n_bars)]
        codes = ["000001", "600000"]
        bars = {}
        for code in codes:
            close = 10 + np.cumsum(np.random.randn(n_bars) * 0.05)
            bars[code] = pd.DataFrame({
                "timestamp": timestamps, "open": close - 0.05,
                "high": close + 0.1, "low": close - 0.1,
                "close": close, "volume": np.random.randint(1000, 5000, n_bars),
            })
        ts_col = "timestamp"
        signals = []
        for i in range(10, n_bars, 5):
            for c in codes:
                signals.append({ts_col: timestamps[i], "code": c, "weight": 1.0 / len(codes)})
        return pd.DataFrame(signals), bars

    def test_daily(self):
        from quant.backtest.multi_freq import MultiFreqBacktest
        signals, bars = self._make_data(200, "1d")
        engine = MultiFreqBacktest()
        result = engine.run(signals, bars, frequency="1d")
        assert result.frequency == "1d"
        assert result.n_bars > 0

    def test_minute(self):
        from quant.backtest.multi_freq import MultiFreqBacktest
        signals, bars = self._make_data(200, "1m")
        engine = MultiFreqBacktest()
        result = engine.run(signals, bars, frequency="1m")
        assert result.frequency == "1m"
        assert result.n_bars > 0

    def test_invalid_freq(self):
        from quant.backtest.multi_freq import MultiFreqBacktest
        engine = MultiFreqBacktest()
        with pytest.raises(ValueError, match="Unsupported frequency"):
            engine.run(pd.DataFrame(), {}, frequency="5m")

    def test_empty_signals(self):
        from quant.backtest.multi_freq import MultiFreqBacktest
        engine = MultiFreqBacktest()
        result = engine.run(pd.DataFrame(), {}, frequency="1d")
        assert result.total_return == 0.0

    def test_batch_run(self):
        from quant.backtest.multi_freq import MultiFreqBacktest
        signals_a, bars = self._make_data(200, "1d")
        signals_b = signals_a.copy()
        engine = MultiFreqBacktest()
        results = engine.batch_run({"a": signals_a, "b": signals_b}, bars)
        assert "a" in results and "b" in results


# ═══════════════════════════════════════════════════════════════
# 3. Data Prefetch
# ═══════════════════════════════════════════════════════════════

class TestPrefetchManager:
    class _FakeCache:
        def __init__(self, store=None):
            self._store = store or {}
        def get(self, key):
            return self._store.get(key)
        def keys(self, pattern=""):
            import fnmatch
            return [k for k in self._store if fnmatch.fnmatch(k, pattern)]
        def size(self):
            return len(self._store)

    def test_warmup(self):
        from quant.data.prefetch import PrefetchManager
        cache = self._FakeCache({
            "stock:universe": ["000001", "600000"],
            "kline:000001:d": [
                {"date": "20260901", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000, "amount": 10500},
            ],
            "kline:600000:d": [
                {"date": "20260901", "open": 8, "high": 9, "low": 7.5, "close": 8.5, "volume": 2000, "amount": 17000},
            ],
        })
        pm = PrefetchManager(cache)
        count = pm.warmup()
        assert count == 2
        assert pm.cached_count == 2

    def test_batch_get(self):
        from quant.data.prefetch import PrefetchManager
        cache = self._FakeCache({
            "kline:000001:d": [
                {"date": "20260901", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000, "amount": 10500},
            ],
        })
        pm = PrefetchManager(cache)
        pm.warmup(["000001"])
        result = pm.batch_get(["000001", "NONEXIST"])
        assert "000001" in result
        assert "NONEXIST" not in result


# ═══════════════════════════════════════════════════════════════
# 4. Stop-Loss Engine
# ═══════════════════════════════════════════════════════════════

class TestStopLossEngine:
    def test_stock_stop_loss(self):
        from quant.risk.stop_loss import StopLossEngine, StopLossConfig
        engine = StopLossEngine(StopLossConfig(stock_stop_loss_pct=0.05))
        positions = {"000001": {"quantity": 1000, "avg_price": 10.0, "current_price": 9.0}}
        signals = engine.check(positions, current_equity=100_000)
        assert len(signals) == 1
        assert signals[0].code == "000001"
        assert signals[0].reason == "stock_stop_loss"

    def test_stock_stop_profit(self):
        from quant.risk.stop_loss import StopLossEngine, StopLossConfig
        engine = StopLossEngine(StopLossConfig(stock_stop_profit_pct=0.15))
        positions = {"000001": {"quantity": 1000, "avg_price": 10.0, "current_price": 12.0}}
        signals = engine.check(positions, current_equity=100_000)
        assert len(signals) == 1
        assert signals[0].reason == "stock_stop_profit"

    def test_portfolio_stop_loss(self):
        from quant.risk.stop_loss import StopLossEngine, StopLossConfig
        engine = StopLossEngine(StopLossConfig(portfolio_stop_loss_pct=0.10))
        engine._peak_equity = 1_000_000
        signals = engine.check({}, current_equity=850_000)
        assert len(signals) == 1
        assert signals[0].reason == "portfolio_stop_loss"

    def test_no_trigger(self):
        from quant.risk.stop_loss import StopLossEngine, StopLossConfig
        engine = StopLossEngine(StopLossConfig(stock_stop_loss_pct=0.10))
        positions = {"000001": {"quantity": 1000, "avg_price": 10.0, "current_price": 9.5}}
        signals = engine.check(positions, current_equity=100_000)
        assert len(signals) == 0

    def test_reset(self):
        from quant.risk.stop_loss import StopLossEngine
        engine = StopLossEngine()
        engine._peak_equity = 1_000_000
        engine._position_highs["000001"] = 15.0
        engine.reset()
        assert engine._peak_equity == 0.0
        assert len(engine._position_highs) == 0

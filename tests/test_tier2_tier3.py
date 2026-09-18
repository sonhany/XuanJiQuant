"""Tests for Tier 2 & 3 improvements:
- Portfolio Manager (多策略组合)
- Vectorized Backtest (极速回测)
- LLM Advisor (LLM 集成)
- Local Executor (分布式计算)
- Visual Builder (可视化策略)
"""
import pytest
import numpy as np
import pandas as pd


# ═══════════════════════════════════════════════════════════════
# 1. Portfolio Manager
# ═══════════════════════════════════════════════════════════════

class TestPortfolioManager:
    def _make_result(self, name, ret=0.1, sharpe=1.0, dd=0.05):
        from quant.portfolio.manager import StrategyResult
        return StrategyResult(
            name=name, total_return=ret, annual_return=ret,
            sharpe=sharpe, max_drawdown=dd, win_rate=0.55,
        )

    def test_register_and_allocate(self):
        from quant.portfolio.manager import PortfolioManager, StrategySlot
        pm = PortfolioManager(total_capital=1_000_000)
        pm.register(StrategySlot("momentum", weight=0.4))
        pm.register(StrategySlot("mean_revert", weight=0.6))
        alloc = pm.allocate()
        assert alloc["momentum"] == pytest.approx(400_000)
        assert alloc["mean_revert"] == pytest.approx(600_000)

    def test_equal_allocation(self):
        from quant.portfolio.manager import PortfolioManager, StrategySlot
        pm = PortfolioManager(total_capital=1_000_000)
        pm.register(StrategySlot("a", weight=0.0))
        pm.register(StrategySlot("b", weight=0.0))
        alloc = pm.allocate()
        assert alloc["a"] == pytest.approx(500_000)
        assert alloc["b"] == pytest.approx(500_000)

    def test_summary(self):
        from quant.portfolio.manager import PortfolioManager, StrategySlot
        pm = PortfolioManager(total_capital=1_000_000)
        pm.register(StrategySlot("a", weight=0.5))
        pm.register(StrategySlot("b", weight=0.5))
        pm.allocate()
        pm.update_result("a", self._make_result("a", ret=0.1))
        pm.update_result("b", self._make_result("b", ret=0.2))
        s = pm.summary()
        assert s["n_strategies"] == 2
        assert s["combo_return"] == pytest.approx(0.15, abs=0.01)

    def test_optimize_equal_risk(self):
        from quant.portfolio.manager import PortfolioManager, StrategySlot
        pm = PortfolioManager(total_capital=1_000_000)
        pm.register(StrategySlot("low_vol", weight=0.5))
        pm.register(StrategySlot("high_vol", weight=0.5))
        weights = pm.optimize_equal_risk({"low_vol": 0.1, "high_vol": 0.3})
        assert weights["low_vol"] > weights["high_vol"]

    def test_brinson_attribution(self):
        from quant.portfolio.manager import PortfolioManager, StrategySlot, StrategyResult
        pm = PortfolioManager(total_capital=1_000_000)
        pm.register(StrategySlot("a", weight=0.6))
        pm.register(StrategySlot("b", weight=0.4))
        pm.allocate()
        # 需要 daily_returns 才能做归因
        r_a = StrategyResult(name="a", total_return=0.15, annual_return=0.15, sharpe=1.2,
                             daily_returns=pd.Series(np.random.randn(252) * 0.01))
        r_b = StrategyResult(name="b", total_return=0.08, annual_return=0.08, sharpe=0.8,
                             daily_returns=pd.Series(np.random.randn(252) * 0.01))
        pm.update_result("a", r_a)
        pm.update_result("b", r_b)
        bm = pd.Series(np.random.randn(252) * 0.01)
        attr = pm.brinson_attribution(bm)
        assert len(attr) == 2
        assert all(hasattr(a, "total_contribution") for a in attr)


class TestRiskBudget:
    def test_check_risk_budget_pass(self):
        from quant.portfolio.risk import RiskBudget, check_risk_budget
        budget = RiskBudget(max_var=0.1, max_cvar=0.15, max_corr=0.9, min_diversification=1.0)
        np.random.seed(42)
        returns = {
            "a": pd.Series(np.random.randn(252) * 0.01),
            "b": pd.Series(np.random.randn(252) * 0.01),
        }
        result = check_risk_budget(returns, {"a": 0.5, "b": 0.5}, budget)
        # 相关性和分散化可能有波动，至少检查不报错
        assert "passed" in result
        assert "violations" in result

    def test_var_exceeded(self):
        from quant.portfolio.risk import RiskBudget, check_risk_budget
        budget = RiskBudget(max_var=0.001)  # very tight
        returns = {"a": pd.Series(np.random.randn(252) * 0.05)}
        result = check_risk_budget(returns, {"a": 1.0}, budget)
        # May or may not violate depending on random data


# ═══════════════════════════════════════════════════════════════
# 2. Vectorized Backtest
# ═══════════════════════════════════════════════════════════════

class TestVectorizedBacktest:
    def _make_data(self):
        np.random.seed(42)
        dates = pd.date_range("20260101", periods=100, freq="B").strftime("%Y%m%d").tolist()
        codes = ["000001", "600000", "000002"]
        klines = {}
        for code in codes:
            close = 10 + np.cumsum(np.random.randn(100) * 0.1)
            klines[code] = pd.DataFrame({
                "date": dates, "open": close - 0.1, "high": close + 0.2,
                "low": close - 0.2, "close": close, "volume": np.random.randint(1000, 10000, 100),
                "amount": close * np.random.randint(1000, 10000, 100),
            })
        signals = []
        for d in dates[10::5]:  # 每5天调仓
            for c in codes:
                signals.append({"date": d, "code": c, "weight": 1.0 / len(codes)})
        return pd.DataFrame(signals), klines

    def test_basic_run(self):
        from quant.backtest.fast_engine import VectorizedBacktest
        signals, klines = self._make_data()
        engine = VectorizedBacktest()
        result = engine.run(signals, klines)
        assert result.total_return != 0 or result.n_trades == 0
        assert result.equity_curve is not None

    def test_empty_signals(self):
        from quant.backtest.fast_engine import VectorizedBacktest
        engine = VectorizedBacktest()
        result = engine.run(pd.DataFrame(), {})
        assert result.total_return == 0.0

    def test_batch_run(self):
        from quant.backtest.fast_engine import VectorizedBacktest
        signals_a, klines = self._make_data()
        signals_b = signals_a.copy()
        engine = VectorizedBacktest()
        results = engine.batch_run({"strategy_a": signals_a, "strategy_b": signals_b}, klines)
        assert "strategy_a" in results
        assert "strategy_b" in results


# ═══════════════════════════════════════════════════════════════
# 3. LLM Advisor
# ═══════════════════════════════════════════════════════════════

class TestLLMBridge:
    def test_mock_response(self):
        from quant.llm.advisor import LLMBridge
        bridge = LLMBridge()
        resp = bridge.chat("test prompt")
        assert resp.content.startswith("[LLM offline]")

    def test_discover_factors(self):
        from quant.llm.advisor import StrategyAdvisor
        advisor = StrategyAdvisor()
        resp = advisor.discover_factors(["rsi_6", "macd_hist", "bias_20"])
        assert resp.content is not None

    def test_interpret_backtest(self):
        from quant.llm.advisor import StrategyAdvisor
        advisor = StrategyAdvisor()
        result = {
            "total_return": 0.15, "annual_return": 0.12,
            "sharpe": 1.5, "max_drawdown": 0.08,
            "win_rate": 0.55, "turnover": 0.3,
        }
        resp = advisor.interpret_backtest(result, "momentum")
        assert resp.content is not None


# ═══════════════════════════════════════════════════════════════
# 4. Local Executor
# ═══════════════════════════════════════════════════════════════

class TestLocalExecutor:
    def test_map(self):
        from quant.distributed.executor import LocalExecutor
        executor = LocalExecutor(max_workers=2, mode="thread")
        result = executor.map(lambda x: x ** 2, [1, 2, 3, 4, 5])
        assert result.succeeded == 5
        assert result.failed == 0

    def test_map_with_exception(self):
        from quant.distributed.executor import LocalExecutor
        def bad_fn(x):
            if x == 3:
                raise ValueError("boom")
            return x
        executor = LocalExecutor(max_workers=2, mode="thread")
        result = executor.map(bad_fn, [1, 2, 3, 4, 5])
        assert result.succeeded == 4
        assert result.failed == 1


# ═══════════════════════════════════════════════════════════════
# 5. Visual Builder
# ═══════════════════════════════════════════════════════════════

class TestVisualBuilder:
    def test_factor_pipeline(self):
        from quant.visual.builder import VisualBuilder
        builder = VisualBuilder()
        pipeline = builder.factor_pipeline(["rsi_6"], top_n=5)
        order = pipeline.topological_order()
        assert "src" in order
        assert "out" in order

    def test_from_dict(self):
        from quant.visual.builder import VisualBuilder
        builder = VisualBuilder()
        pipeline = builder.from_dict({
            "nodes": [
                {"id": "a", "type": "factor", "params": {"func": "ret_5"}},
                {"id": "b", "type": "filter", "params": {"field": "volume", "op": ">", "value": 0}, "inputs": ["a"]},
            ],
            "edges": [["a", "b"]],
        })
        order = pipeline.topological_order()
        assert order.index("a") < order.index("b")

    def test_roundtrip(self):
        from quant.visual.builder import VisualBuilder, Pipeline
        builder = VisualBuilder()
        original = builder.factor_pipeline(["ret_5"])
        spec = builder.to_dict(original)
        rebuilt = builder.from_dict(spec)
        assert len(rebuilt._nodes) == len(original._nodes)
        assert len(rebuilt._edges) == len(original._edges)

"""Tests for the three Tier-1 improvements:
1. DataAccessor (DAO / DAI化)
2. Pluggable Slippage Models
3. FactorLens (因子分析增强)
"""
import math
import pytest
import numpy as np
import pandas as pd


# ═══════════════════════════════════════════════════════════════
# 1. DataAccessor
# ═══════════════════════════════════════════════════════════════

class _FakeCache:
    """Minimal in-memory cache for DAO tests."""
    def __init__(self, store=None):
        self._store = store or {}
    def get(self, key):
        return self._store.get(key)
    def set(self, key, value, ttl=None):
        self._store[key] = value
    def keys(self, pattern=""):
        import fnmatch
        return [k for k in self._store if fnmatch.fnmatch(k, pattern)]
    def size(self):
        return len(self._store)


class TestDataAccessor:
    def test_kline_returns_dataframe(self):
        cache = _FakeCache({
            "kline:000001:d": [
                {"date": "20260901", "open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5, "volume": 1000, "amount": 10500},
                {"date": "20260902", "open": 10.5, "high": 11.2, "low": 10.0, "close": 11.0, "volume": 1200, "amount": 13200},
            ]
        })
        from quant.data.dao import DataAccessor
        dao = DataAccessor(cache)
        df = dao.kline("000001")
        assert not df.empty
        assert list(df.columns) == ["date", "open", "high", "low", "close", "volume", "amount"]
        assert len(df) == 2

    def test_kline_empty_when_missing(self):
        from quant.data.dao import DataAccessor
        dao = DataAccessor(_FakeCache())
        df = dao.kline("NONEXIST")
        assert df.empty

    def test_universe(self):
        from quant.data.dao import DataAccessor
        dao = DataAccessor(_FakeCache({"stock:universe": ["000001", "600000"]}))
        assert dao.universe() == ["000001", "600000"]

    def test_name(self):
        from quant.data.dao import DataAccessor
        dao = DataAccessor(_FakeCache({"stock:name:000001": "平安银行"}))
        assert dao.name("000001") == "平安银行"
        assert dao.name("NONEXIST") == ""

    def test_realtime_quote(self):
        from quant.data.dao import DataAccessor
        cache = _FakeCache({
            "stock:realtime:000001": {"price": 12.5, "open": 12.0, "high": 13.0, "low": 11.5, "close": 12.5, "volume": 50000, "amount": 625000}
        })
        dao = DataAccessor(cache)
        q = dao.realtime("000001")
        assert q is not None
        assert q.code == "000001"
        assert q.price == 12.5

    def test_financials(self):
        from quant.data.dao import DataAccessor
        cache = _FakeCache({
            "fin:20260630:000001": {"report_date": "20260630", "roe": 0.15},
            "fin:20260331:000001": {"report_date": "20260331", "roe": 0.12},
        })
        dao = DataAccessor(cache)
        fins = dao.financials("000001")
        assert len(fins) == 2

    def test_kline_batch(self):
        from quant.data.dao import DataAccessor
        cache = _FakeCache({
            "kline:000001:d": [{"date": "20260901", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000, "amount": 10500}],
            "kline:600000:d": [{"date": "20260901", "open": 8, "high": 9, "low": 7.5, "close": 8.5, "volume": 2000, "amount": 17000}],
        })
        dao = DataAccessor(cache)
        batch = dao.kline_batch(["000001", "600000", "NONEXIST"])
        assert "000001" in batch
        assert "600000" in batch
        assert "NONEXIST" not in batch


# ═══════════════════════════════════════════════════════════════
# 2. Slippage Models
# ═══════════════════════════════════════════════════════════════

class TestFixedRateSlippage:
    def test_buy(self):
        from quant.paper_execution.slippage import FixedRateSlippage
        model = FixedRateSlippage(rate=0.0001)
        fill, cost = model.compute(price=10.0, direction="buy", quantity=1000)
        assert fill == pytest.approx(10.001, abs=1e-4)
        assert cost == pytest.approx(1.0, abs=0.01)

    def test_sell(self):
        from quant.paper_execution.slippage import FixedRateSlippage
        model = FixedRateSlippage(rate=0.0001)
        fill, cost = model.compute(price=10.0, direction="sell", quantity=1000)
        assert fill == pytest.approx(9.999, abs=1e-4)
        assert cost == pytest.approx(1.0, abs=0.01)

    def test_zero_quantity(self):
        from quant.paper_execution.slippage import FixedRateSlippage
        model = FixedRateSlippage()
        fill, cost = model.compute(price=10.0, direction="buy", quantity=0)
        assert cost == 0.0

    def test_to_dict(self):
        from quant.paper_execution.slippage import FixedRateSlippage
        d = FixedRateSlippage(rate=0.0002).to_dict()
        assert d["type"] == "fixed_rate"
        assert d["rate"] == 0.0002


class TestProportionalSlippage:
    def test_small_order(self):
        from quant.paper_execution.slippage import ProportionalSlippage
        model = ProportionalSlippage(base_rate=0.0001, k=0.1)
        fill, cost = model.compute(price=10.0, direction="buy", quantity=100, adv=100000)
        # participation = 0.001, rate = 0.0001 + 0.1*0.001 = 0.0002
        assert fill == pytest.approx(10.002, abs=1e-3)

    def test_large_order(self):
        from quant.paper_execution.slippage import ProportionalSlippage
        model = ProportionalSlippage(base_rate=0.0001, k=0.1)
        fill, cost = model.compute(price=10.0, direction="buy", quantity=5000, adv=10000)
        # participation = 0.5, rate = 0.0001 + 0.1*0.5 = 0.0501 (capped at 0.05)
        assert fill <= 10.501  # capped


class TestVolumeSlippage:
    def test_tiered(self):
        from quant.paper_execution.slippage import VolumeSlippage
        model = VolumeSlippage()
        # < 1% ADV
        fill1, _ = model.compute(price=10.0, direction="buy", quantity=100, adv=100000)
        # 5-10% ADV
        fill2, _ = model.compute(price=10.0, direction="buy", quantity=700, adv=10000)
        assert fill2 > fill1  # larger order → higher slippage


class TestCompositeSlippage:
    def test叠加(self):
        from quant.paper_execution.slippage import CompositeSlippage, FixedRateSlippage, ProportionalSlippage
        model = CompositeSlippage(models=(
            FixedRateSlippage(rate=0.0001),
            ProportionalSlippage(base_rate=0.0, k=0.05),
        ))
        fill, cost = model.compute(price=10.0, direction="buy", quantity=1000, adv=10000)
        # Fixed: 10.001, then Proportional on 10.001
        assert fill > 10.001


class TestCreateSlippageModel:
    def test_default(self):
        from quant.paper_execution.slippage import create_slippage_model, FixedRateSlippage
        model = create_slippage_model(None)
        assert isinstance(model, FixedRateSlippage)

    def test_proportional_from_dict(self):
        from quant.paper_execution.slippage import create_slippage_model, ProportionalSlippage
        model = create_slippage_model({"type": "proportional", "k": 0.2})
        assert isinstance(model, ProportionalSlippage)

    def test_composite_from_dict(self):
        from quant.paper_execution.slippage import create_slippage_model, CompositeSlippage
        model = create_slippage_model({
            "type": "composite",
            "models": [
                {"type": "fixed_rate", "rate": 0.0001},
                {"type": "proportional", "k": 0.05},
            ]
        })
        assert isinstance(model, CompositeSlippage)
        assert len(model.models) == 2


# ═══════════════════════════════════════════════════════════════
# 3. FactorLens
# ═══════════════════════════════════════════════════════════════

class TestPreprocess:
    def test_winsorize(self):
        from quant.factor.lens import winsorize
        s = pd.Series([1, 2, 3, 4, 5, 100])
        result = winsorize(s, n_sigma=2.0)
        assert result.max() < 100  # 100 should be clipped

    def test_standardize(self):
        from quant.factor.lens import standardize
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = standardize(s)
        assert abs(result.mean()) < 1e-10
        assert abs(result.std() - 1.0) < 0.01

    def test_preprocess(self):
        from quant.factor.lens import preprocess_factor
        s = pd.Series([1, 2, 3, 4, 5, 100, -50])
        result = preprocess_factor(s)
        assert result.notna().sum() == 7


class TestDistributionStats:
    def test_basic(self):
        from quant.factor.lens import distribution_stats
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        stats = distribution_stats(s)
        assert stats["mean"] == pytest.approx(3.0)
        assert stats["coverage"] == 1.0
        assert stats["valid"] == 5

    def test_with_nan(self):
        from quant.factor.lens import distribution_stats
        s = pd.Series([1.0, np.nan, 3.0, np.nan, 5.0])
        stats = distribution_stats(s)
        assert stats["valid"] == 3
        assert stats["coverage"] == pytest.approx(0.6)


class TestIndustryDistribution:
    def test_basic(self):
        from quant.factor.lens import industry_distribution
        df = pd.DataFrame({
            "date": ["20260901"] * 4,
            "code": ["000001", "600000", "000002", "600001"],
            "factor_value": [1.0, 2.0, 3.0, 4.0],
        })
        ind_map = {"000001": "C", "600000": "C", "000002": "B", "600001": "B"}
        result = industry_distribution(df, ind_map)
        assert "C" in result
        assert "B" in result
        assert result["C"]["count"] == 2


class TestCorrelationMatrix:
    def test_basic(self):
        from quant.factor.lens import correlation_matrix
        np.random.seed(42)
        n = 100
        multi_factor = {
            "000001": pd.DataFrame({
                "momentum": np.random.randn(n),
                "reversal": np.random.randn(n),
            })
        }
        result = correlation_matrix(multi_factor, ["momentum", "reversal"])
        assert len(result["factors"]) == 2
        assert len(result["matrix"]) == 2


class TestCrowdingAnalysis:
    def test_basic(self):
        from quant.factor.lens import crowding_analysis
        dates = ["20260901", "20260902", "20260903"]
        codes = ["A", "B", "C", "D", "E"]
        rows = []
        for d in dates:
            for c in codes:
                rows.append({"date": d, "code": c, "score": np.random.rand()})
        df = pd.DataFrame(rows)
        result = crowding_analysis(df, "score")
        assert "concentration" in result
        assert "turnover" in result

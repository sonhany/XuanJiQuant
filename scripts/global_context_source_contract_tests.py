import os
import sys
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class FakeCache:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ttl=None):
        self.data[key] = value


def test_global_context_prefers_tdx_quant_for_a_share_indices():
    from scripts import global_context

    sentiment = {
        "sentiment_score": 50.0,
        "sentiment_regime": "neutral",
        "confidence": 0.5,
        "mode": "shadow_only",
        "can_change_trade_policy": False,
        "can_trigger_order": False,
        "sources": [{"source": "cboe", "status": "live"}],
    }
    tdx_quotes = {
        "sh000001": {"name": "上证指数", "price": 3996.16, "close": 4036.59, "prev_close": 4036.59, "chg_pct": -1.0, "source": "tdx_quant"},
        "sz399001": {"name": "深证成指", "price": 15046.67, "close": 15398.73, "prev_close": 15398.73, "chg_pct": -2.29, "source": "tdx_quant"},
        "sz399006": {"name": "创业板指", "price": 3842.73, "close": 4018.17, "prev_close": 4018.17, "chg_pct": -4.37, "source": "tdx_quant"},
        "sh000300": {"name": "沪深300", "price": 4780.79, "close": 4876.31, "prev_close": 4876.31, "chg_pct": -1.96, "source": "tdx_quant"},
    }
    sina_quotes = {"gb_$ndx": {"name": "纳斯达克100", "price": 100.0, "close": 99.0, "prev_close": 99.0, "chg_pct": 1.01}}

    with patch.object(global_context, "cache", FakeCache()), \
            patch.object(global_context, "_fetch_tdx_indices", return_value=tdx_quotes), \
            patch.object(global_context, "_fetch_sina_indices", return_value=sina_quotes), \
            patch.object(global_context, "_fetch_jin10_macro", return_value={"quotes": [], "calendar": []}), \
            patch("scripts.market_data.fetch_sector_flow", return_value=[]), \
            patch("scripts.market_data.fetch_northbound", return_value={"northFlow": 0, "trend": "neutral"}), \
            patch("scripts.market_sentiment.collect_market_sentiment", return_value=sentiment):
        context = global_context.collect_global_context()

    a_share = context["global_indices"]["A股大盘"]
    assert [row["source"] for row in a_share] == ["tdx_quant", "tdx_quant", "tdx_quant", "tdx_quant"]
    assert a_share[0]["name"] == "上证指数"
    assert a_share[0]["price"] == 3996.16
    assert context["data_sources"]["a_share_indices"] == "tdx_quant"
    assert context["sentiment"] == sentiment


if __name__ == "__main__":
    test_global_context_prefers_tdx_quant_for_a_share_indices()
    print("global_context_source_contract_tests: OK")

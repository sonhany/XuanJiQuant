"""Data source chain contract tests.

Validates the intended policy:
  - Realtime: TdxQuant primary, Sina/Tencent fallback.
  - Daily K-line: TdxQuant primary, Tencent cross-check, Sina/Baostock fallback.
  - Minute K-line: TdxQuant primary, Tencent fallback.
  - Fundamentals: AkShare primary, Tushare cross-check.
  - Storage: SQLite realtime cache, optional ClickHouse historical store.
"""
import os
import sys
from datetime import datetime
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


def test_source_policy_matches_tdx_quant_first_plan():
    from quant.data.source_policy import get_source_policy, REALTIME_CACHE_VERSION

    policy = get_source_policy()
    assert policy["realtime_primary"] == "tdx_quant"
    assert policy["realtime_fallbacks"] == ["sina", "tencent"]
    assert policy["kline_primary"] == "tdx_quant"
    assert policy["kline_cross_check"] == "tencent"
    assert policy["kline_fallbacks"] == ["sina", "baostock"]
    assert policy["minute_kline_primary"] == "tdx_quant"
    assert policy["minute_kline_fallback"] == "tencent"
    assert policy["fundamental_primary"] == "akshare"
    assert policy["fundamental_cross_checks"] == ["tushare"]
    assert policy["realtime_store"] == "sqlite"
    assert policy["historical_store"] == "sqlite"
    assert policy["historical_store_target"] == "clickhouse"
    assert policy["historical_store_target_deployed"] is False
    assert REALTIME_CACHE_VERSION >= 3


def test_realtime_fetch_uses_tdx_quant_before_sina_or_tencent():
    from scripts import market_data
    from quant.data import tdx_quant_source

    def fake_tdx_quotes(codes):
        assert codes == ["600519"]
        return {
            "600519": {
                "code": "600519",
                "name": "贵州茅台",
                "price": 1190.0,
                "prev_close": 1188.8,
                "open": 1189.0,
                "high": 1199.0,
                "low": 1180.0,
                "volume": 100,
                "amount": 1000000.0,
                "source": "tdx_quant",
            }
        }

    with patch.object(market_data, "_cache", return_value=FakeCache()), \
            patch.object(tdx_quant_source, "fetch_quotes", side_effect=fake_tdx_quotes), \
            patch("urllib.request.urlopen", side_effect=AssertionError("Sina should not be called when TdxQuant has data")):
        result = market_data.fetch_realtime(["600519"], use_cache=False)

    assert result["sh600519"]["source"] == "tdx_quant"
    assert result["sh600519"]["name"] == "贵州茅台"
    assert result["sh600519"]["price"] == 1190.0


def test_realtime_fetch_uses_tdx_quant_for_index_before_sina():
    from scripts import market_data
    from quant.data import tdx_quant_source

    def fake_tdx_realtime(codes):
        assert codes == ["sh000001"]
        return {
            "sh000001": {
                "code": "sh000001",
                "symbol": "000001.SH",
                "name": "上证指数",
                "price": 3996.16,
                "prev_close": 4036.59,
                "open": 3996.16,
                "high": 3996.16,
                "low": 3996.16,
                "volume": 627450065,
                "amount": 0.0,
                "source": "tdx_quant",
            }
        }

    with patch.object(market_data, "_cache", return_value=FakeCache()), \
            patch.object(tdx_quant_source, "fetch_realtime_quotes", side_effect=fake_tdx_realtime), \
            patch("urllib.request.urlopen", side_effect=AssertionError("Sina should not be called when TdxQuant has index data")):
        result = market_data.fetch_realtime(["sh000001"], use_cache=False)

    assert result["sh000001"]["source"] == "tdx_quant"
    assert result["sh000001"]["name"] == "上证指数"
    assert result["sh000001"]["price"] == 3996.16
    assert result["sh000001"]["amount"] == 0.0
    assert "amount_source" not in result["sh000001"]


def test_realtime_fetch_enriches_missing_tdx_amount_from_tencent():
    from scripts import market_data
    from quant.data import tdx_quant_source, tencent_source

    def fake_tdx_quotes(codes):
        assert codes == ["600519"]
        return {
            "600519": {
                "code": "600519",
                "name": "600519",
                "price": 1190.0,
                "prev_close": 1188.8,
                "open": 1189.0,
                "high": 1199.0,
                "low": 1180.0,
                "volume": 100,
                "amount": 0.0,
                "source": "tdx_quant",
            }
        }

    def fake_tencent_quotes(codes):
        assert codes == ["600519"]
        return {
            "600519": {
                "code": "600519",
                "name": "Guizhou Maotai",
                "price": 1190.0,
                "prev_close": 1188.8,
                "open": 1189.0,
                "high": 1199.0,
                "low": 1180.0,
                "volume": 100,
                "amount": 11.9,
                "timestamp": "20260709103000",
            }
        }

    with patch.object(market_data, "_cache", return_value=FakeCache()), \
            patch.object(tdx_quant_source, "fetch_quotes", side_effect=fake_tdx_quotes), \
            patch.object(tencent_source, "fetch_quotes", side_effect=fake_tencent_quotes), \
            patch("urllib.request.urlopen", side_effect=AssertionError("Sina should not be needed when Tencent enriches amount")):
        result = market_data.fetch_realtime(["600519"], use_cache=False)

    quote = result["sh600519"]
    assert quote["source"] == "tdx_quant"
    assert quote["amount"] == 119000.0
    assert quote["amount_source"] == "tencent"
    assert quote["name"] == "Guizhou Maotai"
    assert quote["price"] == 1190.0


def test_realtime_fetch_derives_missing_tdx_amount_with_lot_volume():
    from scripts import market_data

    quote = {
        "source": "tdx_quant",
        "price": 10.0,
        "volume": 100,
        "amount": 0.0,
    }

    market_data._fill_missing_amount(quote)

    assert quote["amount"] == 100000.0
    assert quote["amount_source"] == "derived_lot_volume"


def test_realtime_batch_fallback_rejects_expired_payload():
    from scripts import market_data

    cached = {"_ts": 100.0, "_data": {"sh600519": {"price": 100.0}}}

    assert market_data._fresh_batch_fallback(cached, now=500.0) == {}
    assert market_data._fresh_batch_fallback(cached, now=150.0)["sh600519"]["price"] == 100.0


def test_realtime_quote_time_only_is_bound_to_current_trade_date():
    from scripts import market_data

    quote = {"time": "09:48:06", "source": "sina"}
    market_data._ensure_quote_timestamp(
        quote,
        now=datetime(2026, 9, 2, 9, 48, 7),
    )

    assert quote["time"] == "09:48:06"
    assert quote["timestamp"] == "20260902094806"


def test_realtime_quote_full_timestamp_is_not_rebased():
    from scripts import market_data

    quote = {"timestamp": "20260902094806", "time": "09:48:06"}
    market_data._ensure_quote_timestamp(
        quote,
        now=datetime(2026, 9, 3, 9, 48, 7),
    )

    assert quote["timestamp"] == "20260902094806"


def test_summary_realtime_fallback_resorts_after_amount_refresh(monkeypatch):
    import scripts.data_runner as data_runner
    import scripts.market_data as market_data

    class FakeCache:
        def get(self, key):
            return [{"close": 10.0}] if key.startswith("kline:") else None

    monkeypatch.setattr(data_runner, "cache", FakeCache())
    monkeypatch.setattr(data_runner, "summary_count", lambda cache: 2)
    monkeypatch.setattr(data_runner, "top_stocks", lambda cache, sort_by, limit: {
        "latest_date": "20260710",
        "stocks": [
            {"code": "600001", "name": "A", "amount": 1000.0, "volume": 100},
            {"code": "600002", "name": "B", "amount": 900.0, "volume": 90},
        ],
    })
    monkeypatch.setattr(market_data, "fetch_realtime", lambda codes, use_cache=True: {
        "sh600001": {"name": "A", "price": 10.0, "chg_pct": 0, "volume": 100, "volume_unit": "share", "amount": 100.0, "time": "10:00:00"},
        "sh600002": {"name": "B", "price": 10.0, "chg_pct": 0, "volume": 100, "volume_unit": "share", "amount": 5000.0, "time": "10:00:00"},
    })

    result = data_runner._top_summary_stocks_with_realtime(sort_by="amount", limit=2)

    assert [row["code"] for row in result["stocks"]] == ["600002", "600001"]


def test_market_top_converts_tdx_hand_volume_to_shares(tmp_path, monkeypatch):
    from quant.data.cache import SqliteCache
    from scripts import data_runner
    from scripts import market_data

    cache = SqliteCache(db_path=str(tmp_path / "top.db"))
    monkeypatch.setattr(data_runner, "cache", cache)
    monkeypatch.setattr(data_runner, "_available_stock_codes", lambda: ["603986"])
    monkeypatch.setattr(data_runner, "_stock_name", lambda code: "兆易创新")
    monkeypatch.setattr(market_data, "fetch_realtime", lambda codes, use_cache=True: {
        "sh603986": {
            "name": "兆易创新",
            "price": 612.0,
            "chg_pct": -7.76,
            "volume": 887456,
            "volume_unit": "hand",
            "amount": 59381240000.0,
            "amount_source": "tencent",
            "source": "tdx_quant",
            "time": "20260711150000",
        }
    })

    out = data_runner.action_stocks({"sort_by": "amount", "limit": 30, "force_refresh": True})
    stock = out["data"]["stocks"][0]

    assert stock["code"] == "603986"
    assert stock["volume"] == 88745600
    assert stock["raw_volume"] == 887456
    assert stock["volume_unit"] == "share"
    assert stock["raw_volume_unit"] == "hand"


def test_kline_dual_fetch_uses_tdx_primary_and_tencent_cross_check():
    from quant.data import kline_reconciler

    tdx_bars = [
        {"date": "20260707", "open": 10.0, "high": 10.2, "low": 9.8, "close": 10.0, "volume": 100, "amount": 1000.0},
        {"date": "20260708", "open": 10.1, "high": 10.4, "low": 10.0, "close": 10.2, "volume": 120, "amount": 1200.0},
    ]
    tencent_bars = list(tdx_bars)

    with patch.object(kline_reconciler, "fetch_tdx_klines", return_value=tdx_bars), \
            patch.object(kline_reconciler, "fetch_tencent_klines", return_value=tencent_bars):
        result = kline_reconciler.fetch_kline_dual("600519", count=2, period="1d")

    assert result["ok"] is True
    assert result["primary_source"] == "tdx_quant"
    assert result["cross_check_source"] == "tencent"
    assert result["cross_check_status"] == "matched"
    assert result["bars"] == tdx_bars


def test_kline_dual_fetch_marks_tencent_mismatch_without_replacing_tdx_primary():
    from quant.data import kline_reconciler

    tdx_bars = [
        {"date": "20260708", "open": 10.0, "high": 10.2, "low": 9.8, "close": 10.0, "volume": 100, "amount": 1000.0},
    ]
    tencent_bars = [
        {"date": "20260708", "open": 10.0, "high": 10.2, "low": 9.8, "close": 10.8, "volume": 100, "amount": 1000.0},
    ]

    with patch.object(kline_reconciler, "fetch_tdx_klines", return_value=tdx_bars), \
            patch.object(kline_reconciler, "fetch_tencent_klines", return_value=tencent_bars):
        result = kline_reconciler.fetch_kline_dual("600519", count=1, period="1d", tolerance_pct=0.5)

    assert result["ok"] is True
    assert result["primary_source"] == "tdx_quant"
    assert result["cross_check_status"] == "mismatch"
    assert result["bars"] == tdx_bars


def test_kline_dual_fetch_marks_date_mismatch_even_when_close_matches():
    from quant.data import kline_reconciler

    tdx_bars = [
        {"date": "20260710", "open": 10.0, "high": 10.2, "low": 9.8, "close": 10.0, "volume": 100, "amount": 1000.0},
    ]
    tencent_bars = [
        {"date": "20260711", "open": 10.0, "high": 10.2, "low": 9.8, "close": 10.0, "volume": 100, "amount": 1000.0},
    ]

    with patch.object(kline_reconciler, "fetch_tdx_klines", return_value=tdx_bars), \
            patch.object(kline_reconciler, "fetch_tencent_klines", return_value=tencent_bars):
        result = kline_reconciler.fetch_kline_dual("600519", count=1, period="1d")

    assert result["cross_check_status"] == "date_mismatch"
    assert "date mismatch" in result["warnings"][0]


def test_kline_dual_fetch_uses_unchecked_tdx_bars_for_corporate_action_jump():
    from quant.data import kline_reconciler
    from quant.data.schema import SchemaError

    tdx_bars = [
        {"date": "20260710", "open": 10.0, "high": 10.2, "low": 9.8, "close": 10.0, "volume": 100, "amount": 1000.0},
    ]

    with patch.object(kline_reconciler, "fetch_tdx_klines", side_effect=SchemaError("price jump detected")), \
            patch.object(kline_reconciler, "fetch_tdx_klines_allow_price_jumps", return_value=tdx_bars, create=True), \
            patch.object(kline_reconciler, "fetch_tencent_klines", return_value=tdx_bars):
        result = kline_reconciler.fetch_kline_dual("600519", count=1, period="1d")

    assert result["primary_source"] == "tdx_quant"
    assert result["bars"] == tdx_bars
    assert any("corporate-action" in warning for warning in result["warnings"])


def test_kline_dual_fetch_falls_back_to_tencent_when_tdx_empty():
    from quant.data import kline_reconciler

    tencent_bars = [
        {"date": "20260707", "open": 10.0, "high": 10.2, "low": 9.8, "close": 10.0, "volume": 100, "amount": 1000.0},
    ]

    with patch.object(kline_reconciler, "fetch_tdx_klines", return_value=[]), \
            patch.object(kline_reconciler, "fetch_tencent_klines", return_value=tencent_bars):
        result = kline_reconciler.fetch_kline_dual("600519", count=1, period="1d")

    assert result["ok"] is True
    assert result["primary_source"] == "tencent"
    assert "tdx_quant primary unavailable" in result["warnings"][0]
    assert result["bars"] == tencent_bars


def test_kline_dual_fetch_falls_back_to_sina_then_baostock_for_daily():
    from quant.data import kline_reconciler

    sina_bars = [
        {"date": "20260707", "open": 10.0, "high": 10.2, "low": 9.8, "close": 10.0, "volume": 100, "amount": 1000.0},
    ]

    with patch.object(kline_reconciler, "fetch_tdx_klines", return_value=[]), \
            patch.object(kline_reconciler, "fetch_tencent_klines", return_value=[]), \
            patch.object(kline_reconciler, "fetch_sina_klines", return_value=sina_bars), \
            patch.object(kline_reconciler, "_fetch_baostock_fallback", return_value=[]):
        result = kline_reconciler.fetch_kline_dual("600519", count=1, period="1d")

    assert result["ok"] is True
    assert result["primary_source"] == "sina"
    assert result["bars"] == sina_bars


def test_minute_kline_uses_tdx_primary_then_tencent_fallback():
    from quant.data import kline_reconciler

    tdx_bars = [
        {"date": "20260708", "time": "0930", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 10, "amount": 100.0},
    ]
    with patch.object(kline_reconciler, "fetch_tdx_klines", return_value=tdx_bars), \
            patch.object(kline_reconciler, "fetch_tencent_minute_klines", return_value=[]):
        result = kline_reconciler.fetch_kline_dual("600519", count=1, period="1m")

    assert result["ok"] is True
    assert result["primary_source"] == "tdx_quant"
    assert result["bars"] == tdx_bars


def test_financial_crosscheck_uses_akshare_primary():
    from quant.data import financial_reconciler

    ak_rows = [{"report_date": "20260331", "code": "600519", "roe": 8.2}]

    with patch.object(financial_reconciler, "_fetch_akshare_records", return_value=ak_rows), \
            patch.object(financial_reconciler, "_fetch_tushare_records", return_value=[]), \
            patch.object(financial_reconciler, "_akshare_stock_info", return_value={"股票简称": "贵州茅台"}):
        result = financial_reconciler.fetch_financial_crosscheck("600519")

    assert result["ok"] is True
    assert result["primary_source"] == "akshare"
    assert result["sources"]["akshare"]["available"] is True
    assert result["sources"]["tushare"]["available"] is False
    assert result["merged"]["name"] == "贵州茅台"
    assert result["akshare_records"] == ak_rows


def test_financial_crosscheck_selects_latest_report_by_date():
    from quant.data import financial_reconciler

    ak_rows = [
        {"report_date": "20181231", "code": "600519", "roe": 1.0},
        {"report_date": "20260331", "code": "600519", "roe": 8.2},
    ]

    with patch.object(financial_reconciler, "_fetch_akshare_records", return_value=ak_rows), \
            patch.object(financial_reconciler, "_fetch_tushare_records", return_value=[]), \
            patch.object(financial_reconciler, "_akshare_stock_info", return_value={}):
        result = financial_reconciler.fetch_financial_crosscheck("600519")

    assert result["merged"]["latest_akshare_report"]["report_date"] == "20260331"


def test_financial_crosscheck_uses_tushare_when_akshare_empty():
    from quant.data import financial_reconciler

    ts_rows = [{"ts_code": "600519.SH", "roe": 8.5}]

    with patch.object(financial_reconciler, "_fetch_akshare_records", return_value=[]), \
            patch.object(financial_reconciler, "_fetch_tushare_records", return_value=ts_rows), \
            patch.object(financial_reconciler, "_akshare_stock_info", return_value={}):
        result = financial_reconciler.fetch_financial_crosscheck("600519")

    assert result["ok"] is True
    assert result["sources"]["tushare"]["available"] is True
    assert result["sources"]["akshare"]["available"] is False


if __name__ == "__main__":
    test_source_policy_matches_tdx_quant_first_plan()
    test_realtime_fetch_uses_tdx_quant_before_sina_or_tencent()
    test_realtime_fetch_uses_tdx_quant_for_index_before_sina()
    test_realtime_fetch_enriches_missing_tdx_amount_from_tencent()
    test_realtime_fetch_derives_missing_tdx_amount_with_lot_volume()
    test_kline_dual_fetch_uses_tdx_primary_and_tencent_cross_check()
    test_kline_dual_fetch_marks_tencent_mismatch_without_replacing_tdx_primary()
    test_kline_dual_fetch_falls_back_to_tencent_when_tdx_empty()
    test_kline_dual_fetch_falls_back_to_sina_then_baostock_for_daily()
    test_minute_kline_uses_tdx_primary_then_tencent_fallback()
    test_financial_crosscheck_uses_akshare_primary()
    test_financial_crosscheck_uses_tushare_when_akshare_empty()
    print("data_source_chain_contract_tests: OK")

import os
import sys
import threading
import time as pytime
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def test_symbol_normalization():
    from quant.data.tdx_quant_source import normalize_code, tdx_symbol

    assert normalize_code("sh600519") == "600519"
    assert normalize_code("000001.SZ") == "000001"
    assert tdx_symbol("600519") == "600519.SH"
    assert tdx_symbol("000001") == "000001.SZ"
    assert tdx_symbol("sh000001") == "000001.SH"
    assert tdx_symbol("sz399001") == "399001.SZ"
    assert tdx_symbol("sh000300") == "000300.SH"
    assert tdx_symbol("430047") == "430047.BJ"


def test_call_tdx_uses_unique_request_ids_even_with_same_clock_tick():
    from quant.data import tdx_quant_source as tdx

    payloads = []

    def fake_post(payload, *, timeout=tdx.DEFAULT_TIMEOUT, base_url=tdx.DEFAULT_BASE_URL):
        payloads.append(payload)
        return {"ErrorId": "0", "Value": {}}

    with patch.object(tdx, "_post_json", fake_post), patch.object(tdx.time, "time", return_value=1000.0):
        for _ in range(5):
            tdx.call_tdx("get_pricevol", {"stock_list": ["600519.SH"]})

    request_ids = [payload["id"] for payload in payloads]
    assert len(set(request_ids)) == len(request_ids)


def test_call_tdx_serializes_local_client_requests():
    from quant.data import tdx_quant_source as tdx

    state = {"active": 0, "max_active": 0}
    state_lock = threading.Lock()

    def fake_post(payload, *, timeout=tdx.DEFAULT_TIMEOUT, base_url=tdx.DEFAULT_BASE_URL):
        with state_lock:
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
        pytime.sleep(0.02)
        with state_lock:
            state["active"] -= 1
        return {"ErrorId": "0", "Value": {}}

    with patch.object(tdx, "_post_json", fake_post):
        with ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(lambda _: tdx.call_tdx("get_pricevol", {"stock_list": ["600519.SH"]}), range(5)))

    assert state["max_active"] == 1


def test_fetch_quotes_maps_pricevol_to_project_quote_schema():
    from quant.data import tdx_quant_source as tdx

    def fake_post(method, params, *, timeout=tdx.DEFAULT_TIMEOUT):
        assert method == "get_pricevol"
        assert params["stock_list"] == ["600519.SH", "000001.SZ"]
        return {
            "ErrorId": "0",
            "Value": {
                "600519.SH": {"LastClose": "1188.80", "Now": "1190.00", "Volume": "100"},
                "000001.SZ": {"LastClose": "10.47", "Now": "0.00", "Volume": "0"},
            },
        }

    with patch.object(tdx, "call_tdx", fake_post):
        quotes = tdx.fetch_quotes(["600519", "000001"])

    assert quotes["600519"]["code"] == "600519"
    assert quotes["600519"]["price"] == 1190.0
    assert quotes["600519"]["prev_close"] == 1188.8
    assert quotes["600519"]["chg_pct"] == 0.1
    assert quotes["600519"]["source"] == "tdx_quant"
    assert quotes["000001"]["price"] == 10.47
    assert quotes["000001"]["trading_state"] == "preopen_or_no_tick"


def test_fetch_realtime_quotes_preserves_index_and_stock_keys():
    from quant.data import tdx_quant_source as tdx

    def fake_post(method, params, *, timeout=tdx.DEFAULT_TIMEOUT):
        assert method == "get_pricevol"
        assert params["stock_list"] == ["000001.SH", "399001.SZ", "600519.SH"]
        return {
            "ErrorId": "0",
            "Value": {
                "000001.SH": {"LastClose": "4036.59", "Now": "3996.16", "Volume": "627450065"},
                "399001.SZ": {"LastClose": "15398.73", "Now": "15046.67", "Volume": "828811173"},
                "600519.SH": {"LastClose": "1188.80", "Now": "1190.00", "Volume": "100"},
            },
        }

    with patch.object(tdx, "call_tdx", fake_post):
        quotes = tdx.fetch_realtime_quotes(["sh000001", "sz399001", "600519"])

    assert set(quotes.keys()) == {"sh000001", "sz399001", "sh600519"}
    assert quotes["sh000001"]["source"] == "tdx_quant"
    assert quotes["sh000001"]["code"] == "sh000001"
    assert quotes["sh000001"]["symbol"] == "000001.SH"
    assert quotes["sh000001"]["price"] == 3996.16
    assert quotes["sz399001"]["price"] == 15046.67
    assert quotes["sh600519"]["price"] == 1190.0


def test_fetch_klines_maps_tdx_arrays_to_valid_bars():
    from quant.data import tdx_quant_source as tdx

    def fake_post(method, params, *, timeout=tdx.DEFAULT_TIMEOUT):
        assert method == "get_market_data"
        assert params["stock_list"] == ["600519.SH"]
        assert params["period"] == "1d"
        return {
            "ErrorId": "0",
            "Value": {
                "600519.SH": {
                    "Date": ["20260707", "20260708"],
                    "Open": ["1180.00", "1188.80"],
                    "High": ["1199.00", "1190.00"],
                    "Low": ["1170.00", "1188.00"],
                    "Close": ["1188.80", "1189.80"],
                    "Volume": ["12345", "23456"],
                    "Amount": ["100.50", "200.00"],
                }
            },
        }

    with patch.object(tdx, "call_tdx", fake_post):
        bars = tdx.fetch_klines("600519", count=2, period="1d")

    assert bars == [
        {
            "date": "20260707",
            "open": 1180.0,
            "high": 1199.0,
            "low": 1170.0,
            "close": 1188.8,
            "volume": 12345,
            "amount": 1005000.0,
        },
        {
            "date": "20260708",
            "open": 1188.8,
            "high": 1190.0,
            "low": 1188.0,
            "close": 1189.8,
            "volume": 23456,
            "amount": 2000000.0,
        },
    ]


def test_fetch_klines_preserves_forward_factor_when_available():
    from quant.data import tdx_quant_source as tdx

    def fake_post(method, params, *, timeout=tdx.DEFAULT_TIMEOUT):
        assert method == "get_market_data"
        return {
            "ErrorId": "0",
            "Value": {
                "600519.SH": {
                    "Date": ["20260710"],
                    "Open": ["1400.00"],
                    "High": ["1410.00"],
                    "Low": ["1390.00"],
                    "Close": ["1405.00"],
                    "Volume": ["1000"],
                    "Amount": ["140.50"],
                    "ForwardFactor": ["0.8123"],
                }
            },
        }

    with patch.object(tdx, "call_tdx", fake_post):
        bars = tdx.fetch_klines_allow_price_jumps("600519", count=1)

    assert bars[0]["factor"] == 0.8123


def test_fetch_klines_batch_uses_bounded_stock_lists_and_preserves_identity():
    from quant.data import tdx_quant_source as tdx

    calls = []

    def fake_post(method, params, *, timeout=tdx.DEFAULT_TIMEOUT):
        assert method == "get_market_data"
        calls.append(list(params["stock_list"]))
        values = {}
        for symbol in params["stock_list"]:
            values[symbol] = {
                "Date": ["20260710"],
                "Open": ["10.00"],
                "High": ["10.50"],
                "Low": ["9.80"],
                "Close": ["10.20"],
                "Volume": ["100"],
                "Amount": ["0.102"],
                "ForwardFactor": ["0.9"],
            }
        return {"ErrorId": "0", "Value": values}

    with patch.object(tdx, "call_tdx", fake_post):
        rows = tdx.fetch_klines_batch_allow_price_jumps(
            ["600519", "000001", "600000"],
            count=20,
            batch_size=2,
        )

    assert calls == [["600519.SH", "000001.SZ"], ["600000.SH"]]
    assert set(rows) == {"600519.SH", "000001.SZ", "600000.SH"}
    assert rows["600519.SH"][0]["date"] == "20260710"
    assert rows["000001.SZ"][0]["factor"] == 0.9


def test_fetch_klines_normalizes_lot_volume_when_amount_implies_100x():
    from quant.data import tdx_quant_source as tdx

    def fake_post(method, params, *, timeout=tdx.DEFAULT_TIMEOUT):
        assert method == "get_market_data"
        return {
            "ErrorId": "0",
            "Value": {
                "000880.SZ": {
                    "Date": ["20260710"],
                    "Open": ["24.00"],
                    "High": ["24.50"],
                    "Low": ["23.80"],
                    "Close": ["24.18"],
                    "Volume": ["389921"],
                    "Amount": ["95088.34"],
                }
            },
        }

    with patch.object(tdx, "call_tdx", fake_post):
        bars = tdx.fetch_klines("000880", count=1, period="1d")

    assert bars[0]["volume"] == 38992100
    assert bars[0]["amount"] == 950883400.0


def test_fetch_stock_universe_uses_official_all_a_share_market():
    from quant.data import tdx_quant_source as tdx

    def fake_post(method, params, *, timeout=tdx.DEFAULT_TIMEOUT):
        assert method == "get_stock_list"
        assert params == {"market": "5", "list_type": 1}
        return {
            "ErrorId": "0",
            "Value": [
                {"Code": "600000.SH", "Name": "浦发银行"},
                {"Code": "000001.SZ", "Name": "平安银行"},
                {"Code": "920001.BJ", "Name": "北交测试"},
            ],
        }

    with patch.object(tdx, "call_tdx", fake_post):
        rows = tdx.fetch_stock_universe()

    assert rows[0] == {"code": "600000", "symbol": "600000.SH", "market": "SH", "name": "浦发银行"}
    assert rows[1]["code"] == "000001"
    assert rows[2]["code"] == "920001"


def test_fetch_ticks_uses_tdx_tick_period_and_normalizes_rows():
    from quant.data import tdx_quant_source as tdx

    def fake_post(method, params, *, timeout=tdx.DEFAULT_TIMEOUT):
        assert method == "get_market_data"
        assert params["stock_list"] == ["600519.SH"]
        assert params["period"] == "tick"
        assert params["count"] == 2
        return {
            "ErrorId": "0",
            "Value": {
                "600519.SH": {
                    "ErrorId": "0",
                    "Value": [
                        {"Date": "20260709", "Time": "09:30:01", "Price": "1188.80", "Volume": "100", "Amount": "118880", "BuyOrSell": "B"},
                        ["20260709", "09:30:02", "1189.20", "200", "237840", "S"],
                    ],
                }
            },
        }

    with patch.object(tdx, "call_tdx", fake_post):
        ticks = tdx.fetch_ticks("600519", count=2)

    assert ticks[0]["code"] == "600519"
    assert ticks[0]["date"] == "20260709"
    assert ticks[0]["time"] == "09:30:01"
    assert ticks[0]["price"] == 1188.8
    assert ticks[0]["volume"] == 100
    assert ticks[0]["amount"] == 118880.0
    assert ticks[0]["direction"] == "B"
    assert ticks[1]["time"] == "09:30:02"
    assert ticks[1]["direction"] == "S"


def test_diagnose_ticks_reports_empty_tick_attempts_and_snapshot():
    from quant.data import tdx_quant_source as tdx

    def fake_post(method, params, *, timeout=tdx.DEFAULT_TIMEOUT):
        if method == "get_market_snapshot":
            return {
                "ErrorId": "0",
                "LastClose": "1182.19",
                "Now": "0.00",
                "Volume": "0",
                "Amount": "0.00",
            }
        assert method == "get_market_data"
        assert params["period"] == "tick"
        return {"ErrorId": "0", "Value": {"600519.SH": {"ErrorId": "0", "Value": []}}}

    with patch.object(tdx, "call_tdx", fake_post):
        diag = tdx.diagnose_ticks("600519", count=2)

    assert diag["code"] == "600519"
    assert diag["symbol"] == "600519.SH"
    assert diag["supported_method"] == "get_market_data"
    assert diag["snapshot"]["trading_state"] == "preopen_or_no_tick"
    assert diag["attempts"][0]["period"] == "tick"
    assert diag["attempts"][0]["row_count"] == 0
    assert diag["likely_reason"] in {"preopen_or_no_tick", "no_tick_cache_or_no_trade"}


def test_fetch_tick_snapshot_maps_active_snapshot_to_fallback_tick():
    from quant.data import tdx_quant_source as tdx

    def fake_post(method, params, *, timeout=tdx.DEFAULT_TIMEOUT):
        assert method == "get_market_snapshot"
        return {
            "ErrorId": "0",
            "LastClose": "10.49",
            "Now": "10.43",
            "NowVol": "616",
            "Volume": "33811",
            "Amount": "3532.78",
            "InOutFlag": "1",
        }

    with patch.object(tdx, "call_tdx", fake_post):
        tick = tdx.fetch_tick_snapshot("000001")

    assert tick["code"] == "000001"
    assert tick["price"] == 10.43
    assert tick["volume"] == 61600
    assert tick["amount"] == round(10.43 * 61600, 2)
    assert tick["direction"] == "S"
    assert tick["source"] == "tdx_quant_snapshot"


def test_tick_store_persists_and_reads_latest_rows(tmp_path):
    from quant.data.cache import SqliteCache
    from quant.data.tick_store import latest_ticks, store_ticks

    cache = SqliteCache(db_path=str(tmp_path / "ticks.db"))
    ticks = [
        {"code": "600519", "date": "20260709", "time": "09:30:01", "price": 1188.8, "volume": 100, "amount": 118880, "direction": "B", "source": "tdx_quant"},
        {"code": "600519", "date": "20260709", "time": "09:30:02", "price": 1189.2, "volume": 200, "amount": 237840, "direction": "S", "source": "tdx_quant"},
    ]

    written = store_ticks(cache, "600519", ticks)
    rows = latest_ticks(cache, "600519", limit=5)

    assert written == 2
    assert [r["time"] for r in rows] == ["09:30:02", "09:30:01"]
    assert rows[0]["price"] == 1189.2


def test_tick_store_microstructure_summary(tmp_path):
    from quant.data.cache import SqliteCache
    from quant.data.tick_store import store_ticks, tick_microstructure

    cache = SqliteCache(db_path=str(tmp_path / "ticks.db"))
    store_ticks(cache, "600519", [
        {"code": "600519", "date": "20260709", "time": "09:30:01", "price": 10.0, "volume": 100, "amount": 1000, "direction": "B", "source": "tdx_quant"},
        {"code": "600519", "date": "20260709", "time": "09:30:02", "price": 10.2, "volume": 200, "amount": 2040, "direction": "S", "source": "tdx_quant"},
    ])

    summary = tick_microstructure(cache, "600519", limit=20)

    assert summary["count"] == 2
    assert summary["latest_price"] == 10.2
    assert round(summary["vwap"], 4) == round(3040 / 300, 4)
    assert summary["buy_volume"] == 100
    assert summary["sell_volume"] == 200
    assert round(summary["imbalance"], 4) == round((100 - 200) / 300, 4)
    assert summary["source"] == "tdx_quant"
    assert summary["true_tick_count"] == 0
    assert summary["snapshot_count"] == 0


def test_data_runner_tick_collect_prefers_tdxrs_transactions(tmp_path, monkeypatch):
    from quant.data.cache import SqliteCache
    from quant.data.tick_store import latest_ticks
    from quant.data import tdx_quant_source, tdxrs_tick_source
    import scripts.data_runner as data_runner

    cache = SqliteCache(db_path=str(tmp_path / "ticks.db"))
    monkeypatch.setattr(data_runner, "cache", cache)
    monkeypatch.setattr(tdxrs_tick_source, "fetch_ticks", lambda code, count=200: [
        {"code": code, "date": "20260710", "time": "10:08:00", "price": 10.1, "volume": 1000, "amount": 10100, "direction": "B", "source": "tdxrs_transaction"},
    ])
    monkeypatch.setattr(tdx_quant_source, "fetch_ticks", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("tdx_quant tick should not be called before tdxrs")))
    monkeypatch.setattr(tdx_quant_source, "fetch_tick_snapshot", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("snapshot fallback should not be called when tdxrs returns true ticks")))

    out = data_runner.action_tick_collect({"code": "600519", "count": 20, "snapshot_fallback": True})
    rows = latest_ticks(cache, "600519", limit=5)

    assert out["data"]["items"]["600519"]["source"] == "tdxrs_transaction"
    assert out["data"]["items"]["600519"]["fallback"] == ""
    assert out["data"]["items"]["600519"]["fetched"] == 1
    assert rows[0]["source"] == "tdxrs_transaction"


def test_data_runner_tick_collect_uses_marked_snapshot_only_as_fallback(tmp_path, monkeypatch):
    from quant.data.cache import SqliteCache
    from quant.data.tick_store import latest_ticks
    from quant.data import tdx_quant_source, tdxrs_tick_source
    import scripts.data_runner as data_runner

    cache = SqliteCache(db_path=str(tmp_path / "ticks.db"))
    monkeypatch.setattr(data_runner, "cache", cache)
    monkeypatch.setattr(tdxrs_tick_source, "fetch_ticks", lambda code, count=200: [])
    monkeypatch.setattr(tdx_quant_source, "fetch_ticks", lambda *args, **kwargs: [])
    monkeypatch.setattr(tdx_quant_source, "fetch_tick_snapshot", lambda code: {
        "code": code, "date": "20260710", "time": "10:09:00", "price": 10.2, "volume": 2000, "amount": 20400, "direction": "S", "source": "tdx_quant_snapshot",
    })

    out = data_runner.action_tick_collect({"code": "600519", "count": 20, "snapshot_fallback": True})
    rows = latest_ticks(cache, "600519", limit=5)

    assert out["data"]["items"]["600519"]["source"] == "tdx_quant_snapshot"
    assert out["data"]["items"]["600519"]["fallback"] == "tdx_quant_snapshot"
    assert rows[0]["source"] == "tdx_quant_snapshot"


def test_data_runner_ticks_includes_snapshot_order_book(tmp_path, monkeypatch):
    from quant.data.cache import SqliteCache
    from quant.data.tick_store import store_ticks
    from quant.data import tdx_quant_source
    import scripts.data_runner as data_runner

    cache = SqliteCache(db_path=str(tmp_path / "ticks.db"))
    monkeypatch.setattr(data_runner, "cache", cache)
    store_ticks(cache, "600519", [
        {"code": "600519", "date": "20260710", "time": "10:00:00", "price": 10.0, "volume": 1000, "amount": 10000, "direction": "B", "source": "tdxrs_transaction"},
    ])
    monkeypatch.setattr(tdx_quant_source, "fetch_snapshot", lambda code: {
        "bid_prices": ["9.99", "9.98", "0.00", "0.00", "0.00"],
        "bid_volumes": ["100", "200", "0", "0", "0"],
        "ask_prices": ["10.01", "10.02", "0.00", "0.00", "0.00"],
        "ask_volumes": ["150", "250", "0", "0", "0"],
        "source": "tdx_quant",
    })

    out = data_runner.action_ticks({"code": "600519", "limit": 100})

    assert out["data"]["order_book"]["source"] == "tdx_quant_snapshot"
    assert len(out["data"]["order_book"]["bids"]) == 5
    assert len(out["data"]["order_book"]["asks"]) == 5
    assert out["data"]["order_book"]["bids"][0] == {"level": 1, "price": 9.99, "volume": 10000}
    assert out["data"]["order_book"]["asks"][0] == {"level": 1, "price": 10.01, "volume": 15000}
    assert out["data"]["order_book"]["bids"][4] == {"level": 5, "price": 0.0, "volume": 0}
    assert out["data"]["order_book"]["asks"][4] == {"level": 5, "price": 0.0, "volume": 0}


def test_data_runner_ticks_can_filter_by_trade_date(tmp_path, monkeypatch):
    from quant.data.cache import SqliteCache
    from quant.data.tick_store import store_ticks
    from quant.data import tdx_quant_source
    import scripts.data_runner as data_runner

    cache = SqliteCache(db_path=str(tmp_path / "ticks.db"))
    monkeypatch.setattr(data_runner, "cache", cache)
    store_ticks(cache, "600519", [
        {"code": "600519", "date": "20260710", "time": "15:00:00", "price": 9.8, "volume": 100, "amount": 980, "direction": "S", "source": "tdxrs_transaction"},
        {"code": "600519", "date": "20260711", "time": "09:30:00", "price": 10.0, "volume": 100, "amount": 1000, "direction": "B", "source": "tdxrs_transaction"},
        {"code": "600519", "date": "20260711", "time": "09:31:00", "price": 10.1, "volume": 200, "amount": 2020, "direction": "B", "source": "tdxrs_transaction"},
    ])
    monkeypatch.setattr(tdx_quant_source, "fetch_snapshot", lambda code: {
        "bid_prices": [],
        "bid_volumes": [],
        "ask_prices": [],
        "ask_volumes": [],
        "source": "tdx_quant",
    })

    out = data_runner.action_ticks({"code": "600519", "limit": 10, "trade_date": "20260711"})

    assert out["success"] is True
    assert out["data"]["trade_date"] == "20260711"
    assert out["data"]["count"] == 2
    assert {row["date"] for row in out["data"]["ticks"]} == {"20260711"}
    assert out["data"]["stats"]["total_amount"] == 3020


def test_data_runner_tick_collect_full_day_persists_and_reports_range(tmp_path, monkeypatch):
    from quant.data.cache import SqliteCache
    from quant.data.tick_store import latest_ticks
    from quant.data import tdxrs_tick_source
    import scripts.data_runner as data_runner

    cache = SqliteCache(db_path=str(tmp_path / "ticks.db"))
    monkeypatch.setattr(data_runner, "cache", cache)
    monkeypatch.setattr(tdxrs_tick_source, "fetch_full_day_ticks", lambda code, page_size=500, max_pages=80: {
        "code": code,
        "ticks": [
            {"code": code, "date": "20260711", "time": "09:30:01", "price": 10.0, "volume": 100, "amount": 1000, "direction": "B", "source": "tdxrs_transaction"},
            {"code": code, "date": "20260711", "time": "15:00:00", "price": 10.5, "volume": 200, "amount": 2100, "direction": "S", "source": "tdxrs_transaction"},
        ],
        "fetched": 2,
        "pages": 1,
        "complete": True,
        "first_time": "09:30:01",
        "last_time": "15:00:00",
        "source": "tdxrs_transaction",
    })

    out = data_runner.action_tick_collect_full_day({"code": "600519", "page_size": 500, "max_pages": 80})
    rows = latest_ticks(cache, "600519", limit=10)

    assert out["success"] is True
    assert out["data"]["code"] == "600519"
    assert out["data"]["fetched"] == 2
    assert out["data"]["stored_count"] == 2
    assert out["data"]["first_time"] == "09:30:01"
    assert out["data"]["last_time"] == "15:00:00"
    assert out["data"]["complete"] is True
    assert out["data"]["day_summary"]["total_amount"] == 3100
    assert out["data"]["stats"]["total_amount"] == 3100
    assert len(out["data"]["ticks"]) == 2
    assert len(rows) == 2


def test_data_runner_tick_collect_full_day_replaces_polluted_same_day_rows(tmp_path, monkeypatch):
    from quant.data.cache import SqliteCache
    from quant.data.tick_store import store_ticks
    from quant.data import tdxrs_tick_source
    import scripts.data_runner as data_runner

    cache = SqliteCache(db_path=str(tmp_path / "ticks.db"))
    monkeypatch.setattr(data_runner, "cache", cache)
    store_ticks(cache, "600519", [
        {"code": "600519", "date": "20260711", "time": "09:29:00", "price": 100.0, "volume": 999999, "amount": 99999900, "direction": "B", "source": "tdxrs_transaction"},
    ])
    monkeypatch.setattr(tdxrs_tick_source, "fetch_full_day_ticks", lambda code, page_size=500, max_pages=80: {
        "code": code,
        "trade_date": "20260711",
        "ticks": [
            {"code": code, "date": "20260711", "time": "09:30:01", "price": 10.0, "volume": 100, "amount": 1000, "direction": "B", "source": "tdxrs_transaction"},
            {"code": code, "date": "20260711", "time": "15:00:00", "price": 10.5, "volume": 200, "amount": 2100, "direction": "S", "source": "tdxrs_transaction"},
        ],
        "fetched": 2,
        "pages": 1,
        "complete": True,
        "first_time": "09:30:01",
        "last_time": "15:00:00",
        "source": "tdxrs_transaction",
    })

    out = data_runner.action_tick_collect_full_day({"code": "600519", "page_size": 500, "max_pages": 80})

    assert out["success"] is True
    assert out["data"]["stored_count"] == 2
    assert out["data"]["stats"]["total_volume"] == 300
    assert out["data"]["stats"]["total_amount"] == 3100


def test_data_runner_tick_collect_full_day_returns_stored_rows_when_source_fails(tmp_path, monkeypatch):
    from quant.data.cache import SqliteCache
    from quant.data.tick_store import store_ticks
    from quant.data import tdxrs_tick_source
    import scripts.data_runner as data_runner

    cache = SqliteCache(db_path=str(tmp_path / "ticks.db"))
    monkeypatch.setattr(data_runner, "cache", cache)
    store_ticks(cache, "600519", [
        {"code": "600519", "date": "20260711", "time": "09:30:01", "price": 10.0, "volume": 100, "amount": 1000, "direction": "B", "source": "tdxrs_transaction"},
        {"code": "600519", "date": "20260711", "time": "15:00:00", "price": 10.5, "volume": 200, "amount": 2100, "direction": "S", "source": "tdxrs_transaction"},
    ])
    monkeypatch.setattr(tdxrs_tick_source, "fetch_full_day_ticks", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("tdxrs unavailable")))

    out = data_runner.action_tick_collect_full_day({"code": "600519", "display_limit": 20000})

    assert out["success"] is True
    assert out["data"]["source_error"] == "tdxrs unavailable"
    assert out["data"]["stored_count"] == 2
    assert out["data"]["fetched"] == 0
    assert out["data"]["stats"]["total_amount"] == 3100
    assert len(out["data"]["ticks"]) == 2


def test_data_runner_exposes_tdx_quant_test_action():
    import scripts.data_runner as data_runner

    assert "tdx_quant_test" in data_runner.ACTIONS
    assert callable(data_runner.ACTIONS["tdx_quant_test"])


def test_data_runner_tdx_quant_test_reports_stock_index_and_tick_capabilities(monkeypatch):
    from quant.data import tdx_quant_source as tdx
    import scripts.data_runner as data_runner

    monkeypatch.setattr(tdx, "health_check", lambda sample: {"available": True, "source": "tdx_quant"})
    monkeypatch.setattr(tdx, "fetch_quotes", lambda codes: {"600519": {"source": "tdx_quant", "price": 1190.0}})
    monkeypatch.setattr(tdx, "fetch_realtime_quotes", lambda codes: {
        "sh000001": {"source": "tdx_quant", "price": 3996.16, "code": "sh000001"}
    })
    monkeypatch.setattr(tdx, "fetch_snapshot", lambda code: {"source": "tdx_quant", "amount": 1000.0})
    monkeypatch.setattr(tdx, "fetch_klines", lambda code, count=5, period="1d": [{"date": "20260710", "close": 10.0}])
    monkeypatch.setattr(tdx, "fetch_stock_info", lambda code, field_list=None: {"Name": "贵州茅台", "ErrorId": "0"})
    monkeypatch.setattr(tdx, "diagnose_ticks", lambda code, count=20: {
        "supported_method": "get_market_data",
        "supported_period": "tick",
        "fetched_count": 0,
        "likely_reason": "no_tick_cache_or_no_trade",
    })

    out = data_runner.action_tdx_quant_test({"codes": ["600519"], "index_codes": ["sh000001"]})
    data = out["data"]

    assert data["capabilities"]["realtime_stock"]["available"] is True
    assert data["capabilities"]["realtime_index"]["available"] is True
    assert data["capabilities"]["snapshot_order_book"]["available"] is True
    assert data["capabilities"]["daily_kline"]["available"] is True
    assert data["capabilities"]["tick"]["method"] == "get_market_data"
    assert data["index_quotes"]["sh000001"]["source"] == "tdx_quant"
    assert data["tick_probe"]["supported_period"] == "tick"


def test_data_runner_exposes_tick_actions():
    import scripts.data_runner as data_runner

    assert "ticks" in data_runner.ACTIONS
    assert "tick_collect" in data_runner.ACTIONS
    assert "tick_collect_full_day" in data_runner.ACTIONS
    assert "tick_probe" in data_runner.ACTIONS


def test_router_protects_data_collection_actions():
    with open(os.path.join(ROOT, "server", "router.mjs"), "r", encoding="utf-8") as f:
        src = f.read()

    data_line = next(line for line in src.splitlines() if "'/api/data'" in line and "new Set" in line)
    assert "tdx_quant_test" not in data_line
    assert "ticks" in data_line
    assert "'tick_collect'" not in data_line
    assert "'tick_collect_full_day'" not in data_line
    assert "tick_probe" in data_line


if __name__ == "__main__":
    test_symbol_normalization()
    test_fetch_quotes_maps_pricevol_to_project_quote_schema()
    test_fetch_klines_maps_tdx_arrays_to_valid_bars()
    test_fetch_klines_batch_uses_bounded_stock_lists_and_preserves_identity()
    test_fetch_ticks_uses_tdx_tick_period_and_normalizes_rows()
    test_diagnose_ticks_reports_empty_tick_attempts_and_snapshot()
    test_fetch_tick_snapshot_maps_active_snapshot_to_fallback_tick()
    import tempfile
    from pathlib import Path
    test_tick_store_persists_and_reads_latest_rows(Path(tempfile.mkdtemp()))
    test_tick_store_microstructure_summary(Path(tempfile.mkdtemp()))
    test_pretrade_market_snapshot_includes_tick_microstructure(Path(tempfile.mkdtemp()))
    test_data_runner_exposes_tdx_quant_test_action()
    test_data_runner_exposes_tick_actions()
    test_router_allows_tdx_quant_test_as_readonly_data_action()
    print("tdx_quant_source_contract_tests: OK")

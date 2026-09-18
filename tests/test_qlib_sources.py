from pathlib import Path
import sys
import types

import pandas as pd
import pytest


def test_source_circuit_opens_after_consecutive_failures_and_recovers():
    from quant.qlib.sources import SourceCircuitBreaker

    clock = [100.0]
    circuit = SourceCircuitBreaker(
        failure_threshold=2,
        cooldown_seconds=30,
        clock=lambda: clock[0],
    )

    assert circuit.allow("tdxquant") is True
    circuit.failure("tdxquant")
    assert circuit.allow("tdxquant") is True
    circuit.failure("tdxquant")
    assert circuit.allow("tdxquant") is False
    clock[0] = 131.0
    assert circuit.allow("tdxquant") is True
    circuit.success("tdxquant")
    assert circuit.snapshot("tdxquant")["consecutive_failures"] == 0


def test_guarded_source_raises_bounded_timeout():
    import time
    from quant.qlib.sources import SourceCircuitBreaker, guarded_source_call

    circuit = SourceCircuitBreaker(failure_threshold=1, cooldown_seconds=30)

    with pytest.raises(TimeoutError, match="source timeout"):
        guarded_source_call(
            "unit",
            lambda: time.sleep(0.2),
            timeout_seconds=0.01,
            circuit=circuit,
        )

    assert circuit.allow("unit") is False


def test_guarded_batch_source_waits_for_circuit_recovery():
    from quant.qlib.sources import SourceCircuitBreaker, guarded_source_call

    clock = [100.0]
    sleeps = []
    circuit = SourceCircuitBreaker(
        failure_threshold=1,
        cooldown_seconds=2,
        clock=lambda: clock[0],
    )
    circuit.failure("unit")

    def recover(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    result = guarded_source_call(
        "unit",
        lambda: "ok",
        timeout_seconds=1,
        circuit=circuit,
        wait_for_recovery=True,
        sleep=recover,
    )

    assert result == "ok"
    assert sleeps == [2.0]


def test_qlib_sources_do_not_import_trading_cache():
    source = Path("quant/qlib/sources.py").read_text(encoding="utf-8")

    assert "create_cache" not in source
    assert "quant.data.cache" not in source


def test_normalize_instrument_uses_qlib_market_prefix():
    from quant.qlib.sources import normalize_instrument

    assert normalize_instrument("600000") == "SH600000"
    assert normalize_instrument("000001") == "SZ000001"
    assert normalize_instrument("920001") == "BJ920001"


def test_fetch_daily_history_filters_compact_tdx_dates(monkeypatch):
    from quant.qlib import sources

    fake_tdx = types.ModuleType("quant.data.tdx_quant_source")
    fake_tdx.fetch_klines_allow_price_jumps = lambda *args, **kwargs: [
        {
            "date": "20260709",
            "open": 8.90,
            "high": 9.01,
            "low": 8.87,
            "close": 8.98,
            "volume": 100,
            "amount": 898.0,
        },
        {
            "date": "20260710",
            "open": 8.98,
            "high": 9.11,
            "low": 8.92,
            "close": 9.06,
            "volume": 200,
            "amount": 1812.0,
        },
    ]
    monkeypatch.setitem(sys.modules, "quant.data.tdx_quant_source", fake_tdx)

    rows = sources.fetch_daily_history("SH600000", "2026-07-09", "2026-07-10")

    assert [row["datetime"] for row in rows] == ["2026-07-09", "2026-07-10"]
    assert all(row["source"] == "tdxquant_unadjusted" for row in rows)


def test_load_universe_prefers_tdxquant_and_excludes_920(monkeypatch):
    from quant.qlib import sources

    fake_tdx = types.ModuleType("quant.data.tdx_quant_source")
    fake_tdx.fetch_stock_universe = lambda: [
        {"code": "600000", "name": "浦发银行", "market": "SH"},
        {"code": "000001", "name": "平安银行", "market": "SZ"},
        {"code": "920001", "name": "北交测试", "market": "BJ"},
    ]
    monkeypatch.setitem(sys.modules, "quant.data.tdx_quant_source", fake_tdx)

    rows = sources.load_universe("2026-07-10")

    assert rows == [
        {"instrument": "SH600000", "name": "浦发银行", "trade_status": "1"},
        {"instrument": "SZ000001", "name": "平安银行", "trade_status": "1"},
    ]


def test_fetch_daily_history_tracks_requests_raw_and_front(monkeypatch):
    from quant.qlib import sources

    calls = []
    fake_tdx = types.ModuleType("quant.data.tdx_quant_source")

    def fake_fetch(code, *, count, period, dividend_type):
        calls.append(dividend_type)
        close = 10.0 if dividend_type == "none" else 8.0
        return [
            {
                "date": "20260710",
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 100,
                "amount": close * 100,
                "factor": 0.8 if dividend_type == "none" else 1.0,
            }
        ]

    fake_tdx.fetch_klines_allow_price_jumps = fake_fetch
    monkeypatch.setitem(sys.modules, "quant.data.tdx_quant_source", fake_tdx)

    tracks = sources.fetch_daily_history_tracks(
        "SH600000",
        "2026-07-10",
        "2026-07-10",
    )

    assert calls == ["none", "front"]
    assert tracks["raw"][0]["close"] == 10.0
    assert tracks["raw"][0]["factor"] == 0.8
    assert tracks["front"][0]["close"] == 8.0
    assert tracks["raw"][0]["front_price_valid"] is True


def test_fetch_daily_history_tracks_batch_normalizes_two_validated_tracks(monkeypatch):
    from quant.qlib import sources

    calls = []
    fake_tdx = types.ModuleType("quant.data.tdx_quant_source")
    fake_tdx.tdx_symbol = lambda code: (
        f"{str(code)[2:]}.{str(code)[:2]}" if str(code)[:2] in {"SH", "SZ"} else str(code)
    )
    fake_tdx.health_check = lambda: {"available": True}

    def fake_batch(codes, *, count, period, dividend_type, batch_size):
        calls.append((tuple(codes), count, period, dividend_type, batch_size))
        close = 10.0 if dividend_type == "none" else 8.0
        return {
            fake_tdx.tdx_symbol(code): [
                {
                    "date": "20260710",
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 100,
                    "amount": close * 100,
                    "factor": 0.8 if dividend_type == "none" else 1.0,
                }
            ]
            for code in codes
        }

    fake_tdx.fetch_klines_batch_allow_price_jumps = fake_batch
    monkeypatch.setitem(sys.modules, "quant.data.tdx_quant_source", fake_tdx)

    tracks = sources.fetch_daily_history_tracks_batch(
        ["SH600000", "SZ000001"],
        "2026-07-11",
        "2026-07-20",
    )

    assert [item[3] for item in calls] == ["none", "front"]
    assert set(tracks) == {"SH600000", "SZ000001"}
    assert tracks["SH600000"]["raw"][0]["close"] == 10.0
    assert tracks["SH600000"]["front"][0]["close"] == 8.0
    assert tracks["SZ000001"]["raw"][0]["front_price_valid"] is True


def test_batch_prefetch_fails_before_large_request_when_tdx_health_is_unavailable(monkeypatch):
    from quant.qlib import sources

    fake_tdx = types.ModuleType("quant.data.tdx_quant_source")
    fake_tdx.tdx_symbol = lambda code: str(code)
    fake_tdx.health_check = lambda: {
        "available": False,
        "error": "connection timed out",
    }
    fake_tdx.fetch_klines_batch_allow_price_jumps = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("large batch request must not start")
    )
    monkeypatch.setitem(sys.modules, "quant.data.tdx_quant_source", fake_tdx)

    with pytest.raises(RuntimeError, match="tdxquant_batch_unavailable"):
        sources.fetch_daily_history_tracks_batch(
            ["SH600000", "SZ000001"],
            "2026-07-11",
            "2026-07-20",
        )


def test_akshare_reference_data_normalizes_exchange_records(monkeypatch):
    from quant.qlib import sources

    fake_ak = types.ModuleType("akshare")
    fake_ak.stock_info_a_code_name = lambda: (_ for _ in ()).throw(
        RuntimeError("excluded BSE endpoint unavailable")
    )
    fake_ak.stock_info_sh_name_code = lambda symbol="主板A股": pd.DataFrame(
        [{"证券代码": "600000", "证券简称": "浦发银行", "上市日期": "1999-11-10"}]
        if symbol == "主板A股"
        else []
    )
    fake_ak.stock_info_sz_name_code = lambda symbol="A股列表": pd.DataFrame(
        [{"A股代码": "000001", "A股简称": "平安银行", "A股上市日期": "1991-04-03"}]
    )
    name_change_calls = []

    def load_name_changes(symbol="简称变更"):
        name_change_calls.append(symbol)
        if len(name_change_calls) == 1:
            raise TimeoutError("transient SZSE failure")
        return pd.DataFrame(
            [
                {
                    "证券代码": "000001",
                    "变更日期": "20210105",
                    "变更前简称": "平安银行",
                    "变更后简称": "ST平安",
                }
            ]
        )

    fake_ak.stock_info_sz_change_name = load_name_changes
    fake_ak.stock_info_sh_delist = lambda symbol="全部": pd.DataFrame(
        [{"公司代码": "600087", "上市日期": "1995-05-25", "暂停上市日期": "2014-06-05"}]
    )
    fake_ak.stock_info_sz_delist = lambda symbol="终止上市公司": pd.DataFrame(
        [{"证券代码": "000005", "上市日期": "1990-12-10", "终止上市日期": "2024-04-26"}]
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_ak)
    monkeypatch.setattr(sources.time, "sleep", lambda _: None)

    result = sources.fetch_akshare_reference_data()

    assert result["current_universe"][0]["instrument"] == "SH600000"
    assert result["current_universe"][0]["listing_date"] == "1999-11-10"
    assert result["name_changes"][0]["instrument"] == "SZ000001"
    assert result["name_changes"][0]["date"] == "2021-01-05"
    assert result["delistings"] == [
        {
            "instrument": "SH600087",
            "listing_date": "1995-05-25",
            "delisting_date": "2014-06-05",
            "source": "akshare_sse_delist",
        },
        {
            "instrument": "SZ000005",
            "listing_date": "1990-12-10",
            "delisting_date": "2024-04-26",
            "source": "akshare_szse_delist",
        },
    ]
    assert result["source_health"]["passed"] is True
    assert len(name_change_calls) == 2


def test_fetch_daily_history_tracks_uses_baostock_dual_track_when_tdx_is_empty(
    monkeypatch,
):
    from quant.qlib import sources

    fake_tdx = types.ModuleType("quant.data.tdx_quant_source")
    fake_tdx.fetch_klines_allow_price_jumps = lambda *args, **kwargs: []
    monkeypatch.setitem(sys.modules, "quant.data.tdx_quant_source", fake_tdx)

    calls = []
    fake_baostock = types.ModuleType("quant.data.baostock_source")

    def fake_range(
        code, start_date, end_date, adjustflag, *, allow_price_jumps=False
    ):
        calls.append((adjustflag, allow_price_jumps))
        close = 10.0 if adjustflag == "3" else 8.0
        return [
            {
                "date": "20240102",
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 100,
                "amount": close * 100,
            }
        ]

    fake_baostock.fetch_klines_range = fake_range
    monkeypatch.setitem(sys.modules, "quant.data.baostock_source", fake_baostock)

    tracks = sources.fetch_daily_history_tracks(
        "SZ000005",
        "2024-01-02",
        "2024-01-02",
    )

    assert calls == [("3", True), ("2", True)]
    assert tracks["raw"][0]["factor"] == pytest.approx(0.8)
    assert tracks["front"][0]["close"] == 8.0
    assert tracks["source_health"]["sources"] == ["baostock"]


def test_fetch_daily_history_tracks_rejects_single_track_fallback(monkeypatch):
    from quant.qlib import sources

    monkeypatch.setattr(
        sources,
        "guarded_source_call",
        lambda source, operation, **kwargs: {"raw": [], "front": []}
        if source == "akshare"
        else ([], []),
    )
    monkeypatch.setattr(
        sources,
        "fetch_daily_history",
        lambda *args, **kwargs: [
            {
                "instrument": "SH600000",
                "datetime": "2026-08-14",
                "open": 10.0,
                "high": 10.2,
                "low": 9.8,
                "close": 10.1,
                "volume": 100.0,
                "amount": 1010.0,
            }
        ],
    )

    with pytest.raises(RuntimeError, match="front-adjusted validation track unavailable"):
        sources.fetch_daily_history_tracks("SH600000", "2026-08-14", "2026-08-14")


def test_fetch_daily_history_tracks_uses_akshare_for_delisted_history(monkeypatch):
    from quant.qlib import sources

    fake_tdx = types.ModuleType("quant.data.tdx_quant_source")
    fake_tdx.fetch_klines_allow_price_jumps = lambda *args, **kwargs: []
    monkeypatch.setitem(sys.modules, "quant.data.tdx_quant_source", fake_tdx)
    fake_baostock = types.ModuleType("quant.data.baostock_source")
    fake_baostock.fetch_klines_range = lambda *args, **kwargs: []
    monkeypatch.setitem(sys.modules, "quant.data.baostock_source", fake_baostock)

    fake_ak = types.ModuleType("akshare")

    def fake_hist(symbol, period, start_date, end_date, adjust):
        close = 10.0 if adjust == "" else 8.0
        return pd.DataFrame(
            [
                {
                    "日期": "2024-01-02",
                    "开盘": close,
                    "最高": close,
                    "最低": close,
                    "收盘": close,
                    "成交量": 100,
                    "成交额": close * 10000,
                }
            ]
        )

    fake_ak.stock_zh_a_hist = fake_hist
    monkeypatch.setitem(sys.modules, "akshare", fake_ak)

    tracks = sources.fetch_daily_history_tracks(
        "SZ000005",
        "2024-01-02",
        "2024-01-02",
    )

    assert tracks["source_health"]["sources"] == ["akshare"]
    assert tracks["raw"][0]["volume"] == 10000
    assert tracks["raw"][0]["factor"] == pytest.approx(0.8)


def test_tdx_history_is_supplemented_when_single_call_does_not_cover_start(
    monkeypatch,
):
    from quant.qlib import sources

    fake_tdx = types.ModuleType("quant.data.tdx_quant_source")

    def fake_tdx_fetch(*args, dividend_type, **kwargs):
        close = 10.0 if dividend_type == "none" else 8.0
        return [
            {
                "date": "20210802",
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 100,
                "amount": close * 100,
            }
        ]

    fake_tdx.fetch_klines_allow_price_jumps = fake_tdx_fetch
    monkeypatch.setitem(sys.modules, "quant.data.tdx_quant_source", fake_tdx)
    fake_baostock = types.ModuleType("quant.data.baostock_source")
    fake_baostock.fetch_klines_range = lambda *args, **kwargs: []
    monkeypatch.setitem(sys.modules, "quant.data.baostock_source", fake_baostock)

    fake_ak = types.ModuleType("akshare")

    def fake_hist(symbol, period, start_date, end_date, adjust):
        close = 9.0 if adjust == "" else 7.2
        return pd.DataFrame(
            [
                {
                    "日期": "2020-07-01",
                    "开盘": close,
                    "最高": close,
                    "最低": close,
                    "收盘": close,
                    "成交量": 100,
                    "成交额": close * 10000,
                }
            ]
        )

    fake_ak.stock_zh_a_hist = fake_hist
    monkeypatch.setitem(sys.modules, "akshare", fake_ak)

    tracks = sources.fetch_daily_history_tracks(
        "SH600000",
        "2020-07-01",
        "2021-08-02",
    )

    assert [row["datetime"] for row in tracks["raw"]] == [
        "2020-07-01",
        "2021-08-02",
    ]
    assert tracks["source_health"]["sources"] == ["akshare", "tdxquant"]


def test_tdx_prefix_falls_back_to_baostock_without_refetching_full_window(
    monkeypatch,
):
    from quant.qlib import sources

    fake_tdx = types.ModuleType("quant.data.tdx_quant_source")

    def fake_tdx_fetch(*args, dividend_type, **kwargs):
        close = 10.0 if dividend_type == "none" else 8.0
        return [
            {
                "date": "20210802",
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 100,
                "amount": close * 100,
            }
        ]

    fake_tdx.fetch_klines_allow_price_jumps = fake_tdx_fetch
    monkeypatch.setitem(sys.modules, "quant.data.tdx_quant_source", fake_tdx)
    monkeypatch.setattr(
        sources,
        "_fetch_akshare_daily_tracks",
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("akshare down")),
    )
    calls = []
    fake_baostock = types.ModuleType("quant.data.baostock_source")

    def fake_range(code, start_date, end_date, adjustflag, **kwargs):
        calls.append((start_date, end_date, adjustflag))
        if end_date != "2021-08-01":
            return []
        close = 9.0 if adjustflag == "3" else 7.2
        return [
            {
                "date": "20200701",
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 100,
                "amount": close * 100,
            }
        ]

    fake_baostock.fetch_klines_range = fake_range
    monkeypatch.setitem(sys.modules, "quant.data.baostock_source", fake_baostock)

    tracks = sources.fetch_daily_history_tracks(
        "SH600000", "2020-07-01", "2021-08-02"
    )

    assert [row["datetime"] for row in tracks["raw"]] == [
        "2020-07-01",
        "2021-08-02",
    ]
    assert tracks["source_health"]["sources"] == ["baostock", "tdxquant"]
    assert calls == [
        ("2020-07-01", "2021-08-01", "3"),
        ("2020-07-01", "2021-08-01", "2"),
    ]


def test_tdx_history_does_not_require_bars_before_listing(monkeypatch):
    from quant.qlib import sources

    fake_tdx = types.ModuleType("quant.data.tdx_quant_source")

    def fake_tdx_fetch(*args, dividend_type, **kwargs):
        close = 10.0 if dividend_type == "none" else 8.0
        return [
            {
                "date": "20260401",
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 100,
                "amount": close * 100,
            }
        ]

    fake_tdx.fetch_klines_allow_price_jumps = fake_tdx_fetch
    monkeypatch.setitem(sys.modules, "quant.data.tdx_quant_source", fake_tdx)

    def guarded(source, operation, **kwargs):
        if source == "tdxquant":
            return operation()
        raise AssertionError("listed-later symbol must not request a pre-listing prefix")

    monkeypatch.setattr(sources, "guarded_source_call", guarded)

    tracks = sources.fetch_daily_history_tracks(
        "SZ301683",
        "2020-08-01",
        "2026-08-14",
        listing_date="2026-04-01",
    )

    assert len(tracks["raw"]) == 1
    assert tracks["source_health"]["sources"] == ["tdxquant"]


def test_akshare_daily_tracks_accepts_shanghai_field_aliases(monkeypatch):
    from quant.qlib import sources

    fake_ak = types.ModuleType("akshare")
    fake_ak.stock_zh_a_hist = lambda **kwargs: pd.DataFrame(
        [
            {
                "\u65e5\u671f": "2026-01-02",
                "\u5f00\u76d8": 10.0,
                "\u6700\u9ad8": 11.0,
                "\u6700\u4f4e": 9.0,
                "\u6536\u76d8": 10.5,
                "\u6210\u4ea4\u91cf": 123,
                "\u6210\u4ea4\u989d": 4567.0,
            }
        ]
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_ak)

    tracks = sources._fetch_akshare_daily_tracks(
        "SH600000", "2026-01-02", "2026-01-02"
    )

    assert tracks["raw"][0]["datetime"] == "2026-01-02"
    assert tracks["raw"][0]["volume"] == 12300
    assert tracks["raw"][0]["amount"] == 4567.0


def test_akshare_daily_tracks_rejects_missing_volume(monkeypatch):
    from quant.qlib import sources

    fake_ak = types.ModuleType("akshare")
    fake_ak.stock_zh_a_hist = lambda **kwargs: pd.DataFrame(
        [
            {
                "\u65e5\u671f": "2026-01-02",
                "\u5f00\u76d8": 10.0,
                "\u6700\u9ad8": 11.0,
                "\u6700\u4f4e": 9.0,
                "\u6536\u76d8": 10.5,
                "\u6210\u4ea4\u989d": 4567.0,
            }
        ]
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_ak)

    with pytest.raises(ValueError, match="missing columns: volume"):
        sources._fetch_akshare_daily_tracks(
            "SH600000", "2026-01-02", "2026-01-02"
        )

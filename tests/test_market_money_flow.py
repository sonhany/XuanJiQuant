import json
import threading
import time


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_tencent_quote_preserves_turnover_rate():
    from quant.data.tencent_source import _parse_qt_line

    parts = [""] * 39
    parts[1] = "贵州茅台"
    parts[2] = "600519"
    parts[3] = "1350.60"
    parts[4] = "1348.00"
    parts[5] = "1349.00"
    parts[6] = "1000"
    parts[30] = "20260801103000"
    parts[33] = "1360.00"
    parts[34] = "1340.00"
    parts[37] = "737346"
    parts[38] = "0.44"

    quote = _parse_qt_line('v_sh600519="' + "~".join(parts) + '";')

    assert quote["turnover_rate"] == 0.44
    assert quote["amount"] == 737346.0


def test_eastmoney_metrics_keep_zero_and_missing_distinct(monkeypatch):
    from quant.data import tencent_source
    from scripts import market_data

    payload = {
        "data": {
            "diff": [
                {"f12": "600519", "f8": 0.44, "f62": -218031792.0, "f184": -2.96},
                {"f12": "000001", "f8": 0, "f62": 0, "f184": 0},
                {"f12": "300750", "f8": "-", "f62": None, "f184": None},
            ]
        }
    }
    monkeypatch.setattr(
        market_data.urllib.request,
        "urlopen",
        lambda *args, **kwargs: FakeResponse(payload),
    )
    monkeypatch.setattr(tencent_source, "fetch_quotes", lambda codes: {})
    market_data._STOCK_METRICS_CACHE.clear()

    result = market_data.fetch_stock_market_metrics(
        ["600519", "000001", "300750"],
        use_cache=False,
    )

    assert result["items"]["600519"]["main_net_inflow"] == -218031792.0
    assert result["items"]["600519"]["main_net_inflow_pct"] == -2.96
    assert result["items"]["600519"]["turnover_rate"] == 0.44
    assert result["items"]["000001"]["turnover_rate"] == 0.0
    assert result["items"]["300750"]["turnover_rate"] is None


def test_eastmoney_metrics_use_reachable_delay_host(monkeypatch):
    from scripts import market_data

    seen_urls = []

    def fake_urlopen(request, timeout):
        seen_urls.append(request.full_url)
        return FakeResponse({"data": {"diff": []}})

    monkeypatch.setattr(market_data.urllib.request, "urlopen", fake_urlopen)

    market_data._fetch_eastmoney_stock_metrics(["600519"])

    assert len(seen_urls) == 1
    assert seen_urls[0].startswith(
        "https://push2delay.eastmoney.com/api/qt/ulist.np/get?"
    )
    assert "fields=f8,f12,f62,f184" in seen_urls[0]
    assert "secids=1.600519" in seen_urls[0]


def test_metrics_use_tencent_only_for_missing_turnover(monkeypatch):
    from quant.data import tencent_source
    from scripts import market_data

    monkeypatch.setattr(
        market_data,
        "_fetch_eastmoney_stock_metrics",
        lambda codes: {
            "600519": {
                "turnover_rate": None,
                "main_net_inflow": -10.0,
                "main_net_inflow_pct": -1.0,
                "money_flow_source": "eastmoney",
                "turnover_source": "eastmoney",
            }
        },
    )
    monkeypatch.setattr(
        tencent_source,
        "fetch_quotes",
        lambda codes: {"600519": {"turnover_rate": 0.44}},
    )
    market_data._STOCK_METRICS_CACHE.clear()

    result = market_data.fetch_stock_market_metrics(["600519"], use_cache=False)

    assert result["items"]["600519"]["turnover_rate"] == 0.44
    assert result["items"]["600519"]["turnover_source"] == "tencent"
    assert result["items"]["600519"]["main_net_inflow"] == -10.0


def test_metrics_reuse_process_cache(monkeypatch):
    from scripts import market_data

    calls = []

    def fake_eastmoney(codes):
        calls.append(list(codes))
        return {
            "600519": {
                "turnover_rate": 0.44,
                "main_net_inflow": -10.0,
                "main_net_inflow_pct": -1.0,
                "money_flow_source": "eastmoney",
                "turnover_source": "eastmoney",
            }
        }

    monkeypatch.setattr(market_data, "_fetch_eastmoney_stock_metrics", fake_eastmoney)
    market_data._STOCK_METRICS_CACHE.clear()

    first = market_data.fetch_stock_market_metrics(["600519"], use_cache=True)
    second = market_data.fetch_stock_market_metrics(["600519"], use_cache=True)

    assert first is second
    assert calls == [["600519"]]


def test_top_stocks_enrich_after_limit_without_resorting(monkeypatch):
    from scripts import data_runner, market_data

    monkeypatch.setattr(
        data_runner,
        "_available_stock_codes",
        lambda: ["600001", "600002", "600003"],
    )
    monkeypatch.setattr(data_runner, "_stock_name", lambda code: code)
    monkeypatch.setattr(
        market_data,
        "fetch_realtime",
        lambda codes, use_cache=True: {
            "sh600001": {
                "name": "A", "price": 10, "prev_close": 9, "high": 10,
                "low": 9, "chg_pct": 1, "volume": 10, "amount": 300,
                "source": "sina", "time": "10:00:00",
            },
            "sh600002": {
                "name": "B", "price": 10, "prev_close": 9, "high": 10,
                "low": 9, "chg_pct": 1, "volume": 10, "amount": 200,
                "source": "sina", "time": "10:00:00",
            },
            "sh600003": {
                "name": "C", "price": 10, "prev_close": 9, "high": 10,
                "low": 9, "chg_pct": 1, "volume": 10, "amount": 100,
                "source": "sina", "time": "10:00:00",
            },
        },
    )
    seen = []

    def fake_metrics(codes, use_cache=True):
        seen.extend(codes)
        return {
            "items": {
                code: {
                    "turnover_rate": index + 1.0,
                    "main_net_inflow": index * 10.0,
                    "main_net_inflow_pct": index * 0.1,
                }
                for index, code in enumerate(codes)
            },
            "fetched_at": "2026-08-01T10:00:00",
            "source": "eastmoney",
        }

    monkeypatch.setattr(market_data, "fetch_stock_market_metrics", fake_metrics)

    result = data_runner._top_realtime_stocks(
        sort_by="amount",
        limit=2,
        bypass_cache=True,
    )

    assert seen == ["600001", "600002"]
    assert [row["code"] for row in result["stocks"]] == ["600001", "600002"]
    assert result["stocks"][0]["turnover_rate"] == 1.0
    assert result["market_metrics"]["source"] == "eastmoney"


def test_metric_failure_does_not_break_top_stocks(monkeypatch):
    from scripts import data_runner, market_data

    rows = [{"code": "600519", "amount": 100.0}]

    def fail_metrics(*args, **kwargs):
        raise TimeoutError("upstream timeout")

    monkeypatch.setattr(market_data, "fetch_stock_market_metrics", fail_metrics)

    meta = data_runner._enrich_stock_market_metrics(rows)

    assert rows[0]["code"] == "600519"
    assert rows[0]["main_net_inflow"] is None
    assert meta["available"] is False


def test_all_zero_turnover_without_money_flow_is_not_an_available_metric_snapshot(
    monkeypatch,
):
    from scripts import data_runner, market_data

    rows = [{"code": "600519"}, {"code": "000001"}]
    monkeypatch.setattr(
        market_data,
        "fetch_stock_market_metrics",
        lambda codes, use_cache=True: {
            "items": {
                code: {
                    "turnover_rate": 0.0,
                    "main_net_inflow": None,
                    "main_net_inflow_pct": None,
                    "money_flow_source": "eastmoney",
                    "turnover_source": "eastmoney",
                }
                for code in codes
            },
            "fetched_at": "2026-08-07T08:49:43+0800",
            "source": "eastmoney",
        },
    )

    meta = data_runner._enrich_stock_market_metrics(rows)

    assert meta["available"] is False
    assert meta["source"] == "unavailable"
    assert all(row["turnover_rate"] is None for row in rows)
    assert all(row["main_net_inflow"] is None for row in rows)


def test_prior_trade_date_snapshot_is_not_labeled_realtime(monkeypatch):
    from scripts import data_runner, market_data

    monkeypatch.setattr(data_runner, "_available_stock_codes", lambda: ["600519"])
    monkeypatch.setattr(data_runner, "_stock_name", lambda code: "贵州茅台")
    monkeypatch.setattr(data_runner, "_realtime_trade_date", lambda codes=None: "20260806")
    monkeypatch.setattr(data_runner, "_today_yyyymmdd", lambda: "20260807")
    monkeypatch.setattr(
        market_data,
        "fetch_realtime",
        lambda codes, use_cache=True: {
            "sh600519": {
                "name": "贵州茅台",
                "price": 1308.55,
                "prev_close": 1308.55,
                "high": 1308.55,
                "low": 1308.55,
                "chg_pct": 0,
                "volume": 100,
                "amount": 1000,
                "source": "tdx_quant",
                "time": "20260807084933",
            }
        },
    )
    monkeypatch.setattr(
        data_runner,
        "_enrich_stock_market_metrics",
        lambda stocks: {"source": "unavailable", "fetched_at": "", "available": False},
    )

    result = data_runner._top_realtime_stocks(
        sort_by="amount",
        limit=1,
        bypass_cache=True,
    )

    assert result["latest_date"] == "20260806"
    assert result["source"] == "realtime_stale"
    assert result["stale"] is True


def test_realtime_trade_date_does_not_wait_for_intraday_daily_bar(monkeypatch):
    from scripts import data_runner, trading_calendar

    monkeypatch.setattr(data_runner, "_today_yyyymmdd", lambda: "20260807")
    monkeypatch.setattr(data_runner, "_latest_kline_trade_date", lambda codes=None: "20260806")
    monkeypatch.setattr(trading_calendar, "latest_trade_date", lambda today: "20260807")

    assert data_runner._realtime_trade_date(["600519"]) == "20260807"


def test_full_market_quotes_use_bounded_parallel_batches(monkeypatch):
    from scripts import data_runner, market_data

    state_lock = threading.Lock()
    active = 0
    max_active = 0

    def fake_realtime(codes, use_cache=True):
        nonlocal active, max_active
        with state_lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.03)
            return {
                code: {"code": code, "amount": index + 1}
                for index, code in enumerate(codes)
            }
        finally:
            with state_lock:
                active -= 1

    monkeypatch.setattr(market_data, "fetch_realtime", fake_realtime)
    codes = [f"{600000 + index:06d}" for index in range(1500)]

    result = data_runner._fetch_realtime_quotes_in_batches(
        codes,
        use_cache=False,
        chunk_size=300,
    )

    assert len(result) == len(codes)
    assert 1 < max_active <= data_runner.REALTIME_TOP_FETCH_WORKERS

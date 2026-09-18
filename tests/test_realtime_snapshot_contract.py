from __future__ import annotations

from datetime import datetime

import scripts.data_runner as data_runner
import scripts.market_data as market_data


NOW = datetime(2026, 9, 1, 9, 35, 2)


def _quotes():
    return {
        "sh600519": {
            "name": "贵州茅台",
            "price": 1190.0,
            "prev_close": 1188.0,
            "volume": 100,
            "amount": 11900000.0,
            "source": "tdx_quant",
            "time": "20260901093501",
        },
        "sz000001": {
            "name": "平安银行",
            "price": 11.7,
            "prev_close": 11.6,
            "volume": 200,
            "amount": 234000.0,
            "source": "tdx_quant",
            "time": "20260901093501",
        },
    }


def test_hot_snapshot_has_identity_and_per_symbol_freshness():
    out = data_runner.normalize_hot_snapshot(
        ["600519", "000001"], _quotes(), received_at=NOW
    )

    assert len(out["snapshot_id"]) == 64
    assert out["quote_timestamp"] == "20260901093501"
    assert out["received_at"] == "2026-09-01T09:35:02"
    assert out["market_phase"] == "continuous_auction"
    assert out["stale"] is False
    assert out["age_ms"] == 1000
    assert out["quotes"]["600519"]["stale"] is False
    assert out["quotes"]["600519"]["age_ms"] == 1000


def test_hot_snapshot_exposes_execution_prerequisite_fields_when_source_provides_them():
    quotes = _quotes()
    quotes["sh600519"].update({
        "venue": "XSHG",
        "timestamp_kind": "exchange",
        "size_unit": "shares",
        "bid": "1189.99",
        "ask": "1190.00",
        "bid_size": 1200,
        "ask_size": 800,
    })

    out = data_runner.normalize_hot_snapshot(
        ["600519"], quotes, received_at=NOW
    )
    row = out["quotes"]["600519"]

    assert row["venue"] == "XSHG"
    assert row["timestamp_kind"] == "exchange"
    assert row["size_unit"] == "shares"
    assert row["bid"] == "1189.99"
    assert row["ask"] == "1190.00"
    assert row["bid_size"] == 1200
    assert row["ask_size"] == 800


def test_hot_snapshot_adds_current_calendar_and_derived_market_state():
    out = data_runner.normalize_hot_snapshot(
        ["600519"], _quotes(), received_at=NOW
    )
    row = out["quotes"]["600519"]

    assert out["calendar"] == ["2026-09-01"]
    assert out["calendar_source"] == "project_trading_calendar"
    assert row["market"] == {
        "date": "2026-09-01",
        "version": "derived_price_band_20260901",
        "suspended": False,
        "lower_limit": "1069.20",
        "upper_limit": "1306.80",
        "status_source": "quote_activity",
        "price_band_source": "prev_close_board_rule",
    }


def test_hot_snapshot_marks_only_invalid_symbol_stale():
    quotes = _quotes()
    quotes["sh600519"]["time"] = "20260831150000"

    out = data_runner.normalize_hot_snapshot(
        ["600519", "000001"], quotes, received_at=NOW
    )

    assert out["stale"] is True
    assert out["quotes"]["600519"]["stale"] is True
    assert out["quotes"]["600519"]["stale_reason"] == "quote_trade_date_mismatch"
    assert out["quotes"]["000001"]["stale"] is False


def test_sina_quote_can_be_hot_stale_but_still_fresh_for_portfolio_valuation():
    quotes = _quotes()
    for quote in quotes.values():
        quote["source"] = "sina"
        quote["time"] = "20260901093454"

    out = data_runner.normalize_hot_snapshot(
        ["600519", "000001"], quotes, received_at=NOW
    )

    assert out["stale"] is True
    assert out["valuation_stale"] is False
    assert all(row["stale"] is True for row in out["quotes"].values())
    assert all(row["valuation_stale"] is False for row in out["quotes"].values())


def test_midday_break_accepts_current_day_morning_close_as_session_endpoint():
    quotes = _quotes()
    for quote in quotes.values():
        quote["time"] = "20260902113000"
    received = datetime(2026, 9, 2, 11, 40, 0)

    out = data_runner.normalize_hot_snapshot(
        ["600519", "000001"], quotes, received_at=received
    )

    assert out["market_phase"] == "midday_break"
    assert out["stale"] is False
    assert all(row["stale"] is False for row in out["quotes"].values())


def test_hot_snapshot_action_fetches_once_and_returns_complete_contract(monkeypatch):
    calls = []
    monkeypatch.setattr(market_data, "fetch_realtime", lambda codes, use_cache=False: calls.append(tuple(codes)) or _quotes())
    monkeypatch.setattr(data_runner, "_now_local", lambda: NOW)

    out = data_runner.action_hot_snapshot({"codes": ["600519", "000001"]})

    assert calls == [("600519", "000001")]
    assert out["success"] is True
    assert out["data"]["snapshot_id"]
    assert out["data"]["stale"] is False


def test_completed_top_generation_is_atomic_and_not_refreshing():
    rows = [
        {"code": "600519", "amount": 20.0, "price": 10.0},
        {"code": "000001", "amount": 10.0, "price": 5.0},
    ]

    out = data_runner.complete_top_generation(
        rows,
        {
            "latest_date": "20260901",
            "latest_time": "20260901093501",
            "requested": 2,
            "observed": 2,
            "background_refresh": True,
        },
    )

    assert out["complete"] is True
    assert out["coverage"] == 1.0
    assert out["refreshing"] is False
    assert len(out["generation_id"]) == 64

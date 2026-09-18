from datetime import datetime

import pytest


def _quote(code="sh600016", timestamp="20260820105347", price=3.42, volume=981934):
    return {
        "code": code,
        "price": price,
        "volume": volume,
        "timestamp": timestamp,
        "source": "tdx_quant",
        "chg_pct": 1.2,
        "trading_state": "active",
    }


@pytest.mark.parametrize(
    "clock,session",
    [
        ("2026-08-20 09:35:00", "morning"),
        ("2026-08-20 11:25:00", "morning"),
        ("2026-08-20 13:05:00", "afternoon"),
        ("2026-08-20 14:50:00", "afternoon"),
    ],
)
def test_intraday_gate_accepts_only_governed_windows(clock, session):
    from quant.paper_execution.intraday import classify_intraday_window

    result = classify_intraday_window(datetime.fromisoformat(clock))

    assert result.allowed is True
    assert result.session == session
    assert result.reason_code == "intraday_window_open"


@pytest.mark.parametrize(
    "clock,reason",
    [
        ("2026-08-20 09:34:59", "outside_intraday_window"),
        ("2026-08-20 11:30:00", "outside_intraday_window"),
        ("2026-08-20 15:00:00", "outside_intraday_window"),
        ("2026-08-22 10:00:00", "non_trading_weekday"),
    ],
)
def test_intraday_gate_rejects_preopen_lunch_close_and_weekend(clock, reason):
    from quant.paper_execution.intraday import classify_intraday_window

    result = classify_intraday_window(datetime.fromisoformat(clock))

    assert result.allowed is False
    assert result.reason_code == reason


def test_quote_contract_normalizes_vendor_codes_and_current_quotes():
    from quant.paper_execution.intraday import normalize_intraday_quotes

    result = normalize_intraday_quotes(
        {"sh600016": _quote(), "sz000166": _quote("sz000166", price=4.41)},
        ["600016", "000166"],
        now=datetime.fromisoformat("2026-08-20 10:54:00"),
    )

    assert set(result) == {"600016", "000166"}
    assert result["600016"]["price"] == 3.42
    assert result["600016"]["quote_timestamp"] == "20260820105347"
    assert result["600016"]["quote_age_seconds"] == 13


def test_quote_contract_converts_lot_volume_to_shares_for_capacity():
    from quant.paper_execution.intraday import normalize_intraday_quotes

    quote = _quote(volume=130)
    quote["volume_unit"] = "hand"
    result = normalize_intraday_quotes(
        {"sh600016": quote},
        ["600016"],
        now=datetime.fromisoformat("2026-08-20 10:54:00"),
    )

    assert result["600016"]["volume"] == 13_000
    assert result["600016"]["volume_unit"] == "share"


@pytest.mark.parametrize(
    "quotes,reason",
    [
        ({}, "intraday_quote_missing:600016"),
        ({"sh600016": _quote(timestamp="20260819105347")}, "intraday_quote_wrong_date:600016"),
        ({"sh600016": _quote(timestamp="20260820105000")}, "intraday_quote_stale:600016"),
        ({"sh600016": _quote(price=0)}, "intraday_price_invalid:600016"),
        ({"sh600016": _quote(volume=0)}, "intraday_volume_invalid:600016"),
    ],
)
def test_quote_contract_fails_closed_for_missing_stale_or_invalid_quotes(quotes, reason):
    from quant.paper_execution.intraday import IntradayQuoteError, normalize_intraday_quotes

    with pytest.raises(IntradayQuoteError, match=reason):
        normalize_intraday_quotes(
            quotes,
            ["600016"],
            now=datetime.fromisoformat("2026-08-20 10:54:00"),
            max_age_seconds=120,
        )

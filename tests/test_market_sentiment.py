import json
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from scripts.market_sentiment import (
    _http_get_text,
    _main,
    collect_market_sentiment,
    fetch_cboe_vix,
    fetch_cffex_positioning,
    fetch_fred_nfci,
    fetch_hkex_activity,
    get_market_sentiment_status,
    score_market_sentiment,
    score_nfci,
    score_vix,
)


def _assert_shadow_only(result):
    assert result["mode"] == "shadow_only"
    assert result["can_change_trade_policy"] is False
    assert result["can_trigger_order"] is False


def _score_without_exception(component):
    try:
        return score_market_sentiment({"component": component})
    except Exception as exc:
        pytest.fail(f"invalid component raised {type(exc).__name__}: {exc}")


def test_vix_score_uses_defined_anchors_and_interpolation():
    assert score_vix(12) == 90
    assert score_vix(20) == 50
    assert score_vix(40) == 10
    assert score_vix(17.5) == 62.5


def test_nfci_score_uses_defined_anchors():
    assert score_nfci(-0.8) == 85
    assert score_nfci(0.0) == 50
    assert score_nfci(1.0) == 10


def test_interpolation_clamps_values_outside_anchor_endpoints():
    assert score_vix(-100) == 90
    assert score_vix(100) == 10
    assert score_nfci(-10) == 85
    assert score_nfci(10) == 10


@pytest.mark.parametrize("scorer", [score_vix, score_nfci])
@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), float("-inf")],
)
def test_score_rejects_non_finite_values(scorer, value):
    with pytest.raises(ValueError, match="finite"):
        scorer(value)


def test_partial_official_coverage_does_not_inflate_confidence():
    result = score_market_sentiment({
        "volatility": {
            "available": True,
            "score": 25,
            "weight": 50,
            "stale": False,
        },
        "financial_conditions": {"available": False, "weight": 30},
        "futures_positioning": {"available": False, "weight": 20},
    })

    assert result["sentiment_score"] == 25
    assert result["sentiment_regime"] == "fear"
    assert result["confidence"] == 0.5
    _assert_shadow_only(result)


def test_stale_component_reduces_confidence():
    result = score_market_sentiment({
        "volatility": {
            "available": True,
            "score": 50,
            "weight": 50,
            "stale": True,
        },
    })

    assert result["confidence"] == 0.25
    assert result["stale"] is True
    _assert_shadow_only(result)


@pytest.mark.parametrize("available", ["false", 1])
def test_available_requires_literal_true(available):
    result = score_market_sentiment({
        "component": {
            "available": available,
            "score": 25,
            "weight": 50,
            "stale": False,
        },
    })

    assert result["warnings"] == ["official_sources_unavailable"]
    assert result["confidence"] == 0


@pytest.mark.parametrize("stale", ["false", 0, 1, None])
def test_stale_requires_a_boolean(stale):
    result = score_market_sentiment({
        "component": {
            "available": True,
            "score": 25,
            "weight": 50,
            "stale": stale,
        },
    })

    assert result["warnings"] == ["official_sources_unavailable"]
    assert result["confidence"] == 0


@pytest.mark.parametrize(
    "component",
    [
        {"available": True, "score": True, "weight": 50},
        {"available": True, "score": 25, "weight": False},
        {"available": True, "score": "25", "weight": 50},
        {"available": True, "score": 25, "weight": "50"},
        {"available": True, "score": float("nan"), "weight": 50},
        {"available": True, "score": float("inf"), "weight": 50},
        {"available": True, "score": float("-inf"), "weight": 50},
        {"available": True, "score": 25, "weight": float("nan")},
        {"available": True, "score": 25, "weight": float("inf")},
        {"available": True, "score": 25, "weight": float("-inf")},
        {"available": True, "score": -0.01, "weight": 50},
        {"available": True, "score": 100.01, "weight": 50},
        {"available": True, "score": 25, "weight": 0},
        {"available": True, "score": 25, "weight": -1},
    ],
)
def test_invalid_available_component_uses_neutral_fallback(component):
    result = _score_without_exception(component)

    assert result["sentiment_score"] == 50
    assert result["sentiment_regime"] == "neutral"
    assert result["confidence"] == 0
    assert result["warnings"] == ["official_sources_unavailable"]
    _assert_shadow_only(result)


def test_invalid_component_is_ignored_when_valid_component_exists():
    result = score_market_sentiment({
        "valid": {
            "available": True,
            "score": 25,
            "weight": 50,
            "stale": False,
        },
        "invalid": {
            "available": True,
            "score": 101,
            "weight": 50,
            "stale": False,
        },
    })

    assert result["sentiment_score"] == 25
    assert result["confidence"] == 0.5


@pytest.mark.parametrize(
    ("stale", "expected_confidence"),
    [
        (False, 1.0),
        (True, 1.0),
    ],
)
def test_confidence_is_capped_at_one_for_large_weights(
    stale,
    expected_confidence,
):
    result = score_market_sentiment({
        "component": {
            "available": True,
            "score": 50,
            "weight": 1000,
            "stale": stale,
        },
    })

    assert result["confidence"] == expected_confidence
    assert 0 <= result["confidence"] <= 1


@pytest.mark.parametrize(
    ("boundary", "expected_regime"),
    [
        (20.0, "extreme_fear"),
        (40.0, "fear"),
        (60.0, "greed"),
        (80.0, "extreme_greed"),
    ],
)
def test_equal_weight_midpoints_use_decimal_half_even(
    boundary,
    expected_regime,
):
    result = score_market_sentiment({
        "lower": {
            "available": True,
            "score": boundary,
            "weight": 1,
            "stale": False,
        },
        "upper": {
            "available": True,
            "score": boundary + 0.01,
            "weight": 1,
            "stale": False,
        },
    })

    assert result["sentiment_score"] == boundary
    assert result["sentiment_regime"] == expected_regime


def test_non_equal_weighted_components_use_decimal_aggregation():
    result = score_market_sentiment({
        "first": {
            "available": True,
            "score": 10,
            "weight": 1,
            "stale": False,
        },
        "second": {
            "available": True,
            "score": 20,
            "weight": 2,
            "stale": False,
        },
        "third": {
            "available": True,
            "score": 40,
            "weight": 3,
            "stale": False,
        },
    })

    assert result["sentiment_score"] == 28.33
    assert result["confidence"] == 0.06


def test_confidence_uses_decimal_half_even_quantization():
    result = score_market_sentiment({
        "component": {
            "available": True,
            "score": 50,
            "weight": 0.5,
            "stale": False,
        },
    })

    assert result["confidence"] == 0.0


def test_regime_uses_the_displayed_rounded_score():
    result = score_market_sentiment({
        "component": {
            "available": True,
            "score": 20.005,
            "weight": 100,
            "stale": False,
        },
    })

    assert result["sentiment_score"] == 20.0
    assert result["sentiment_regime"] == "extreme_fear"


@pytest.mark.parametrize(
    ("score", "expected_regime"),
    [
        (19.99, "extreme_fear"),
        (20.0, "extreme_fear"),
        (20.01, "fear"),
        (39.99, "fear"),
        (40.0, "fear"),
        (40.01, "neutral"),
        (59.99, "neutral"),
        (60.0, "greed"),
        (60.01, "greed"),
        (79.99, "greed"),
        (80.0, "extreme_greed"),
        (80.01, "extreme_greed"),
    ],
)
def test_regime_boundaries(score, expected_regime):
    result = score_market_sentiment({
        "component": {
            "available": True,
            "score": score,
            "weight": 100,
            "stale": False,
        },
    })

    assert result["sentiment_regime"] == expected_regime


def test_no_official_components_returns_neutral_zero_confidence():
    result = score_market_sentiment({})

    assert result["sentiment_score"] == 50
    assert result["sentiment_regime"] == "neutral"
    assert result["confidence"] == 0
    assert result["warnings"] == ["official_sources_unavailable"]
    _assert_shadow_only(result)


def _http_response(text):
    response = MagicMock()
    response.read.return_value = text.encode("utf-8")
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


def test_http_get_text_sets_timeout_user_agent_and_retries_once():
    response = _http_response("ok")
    with patch(
        "scripts.market_sentiment.urllib.request.urlopen",
        side_effect=[OSError("temporary"), response],
    ) as urlopen, patch("scripts.market_sentiment.time.sleep") as sleep:
        assert _http_get_text("https://example.test/data") == "ok"

    assert urlopen.call_count == 2
    assert all(call.kwargs["timeout"] == 8 for call in urlopen.call_args_list)
    request = urlopen.call_args_list[-1].args[0]
    assert request.get_header("User-agent") == (
        "XuanJiQuant/market-sentiment"
    )
    sleep.assert_called_once()


def test_http_get_text_redacts_query_and_truncates_errors():
    secret = "TOP_SECRET_API_KEY"
    url = f"https://example.test/data?api_key={secret}&series=NFCI"
    message = f"request failed for {url}: {'x' * 500}"
    with patch(
        "scripts.market_sentiment.urllib.request.urlopen",
        side_effect=OSError(message),
    ), patch("scripts.market_sentiment.time.sleep"):
        with pytest.raises(RuntimeError) as raised:
            _http_get_text(url)

    error = str(raised.value)
    assert secret not in error
    assert "api_key=" not in error
    assert "series=NFCI" not in error
    assert len(error) <= 160


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/secret?token=query-secret",
        "data:text/plain,secret?token=query-secret",
        "ftp://example.test/data?token=query-secret",
        "example.test/data?token=query-secret",
    ],
)
def test_http_get_text_rejects_non_http_urls_without_query_leak(url):
    with patch(
        "scripts.market_sentiment.urllib.request.urlopen",
    ) as urlopen:
        with pytest.raises(
            RuntimeError,
            match="^unsupported_HTTP_URL$",
        ) as raised:
            _http_get_text(url)

    urlopen.assert_not_called()
    assert "query-secret" not in str(raised.value)
    assert "token=" not in str(raised.value)


def test_http_get_text_rejects_response_larger_than_two_mib():
    response = MagicMock()
    response.read.return_value = b"x" * ((2 * 1024 * 1024) + 1)
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    secret = "response-secret"
    with patch(
        "scripts.market_sentiment.urllib.request.urlopen",
        return_value=response,
    ), patch("scripts.market_sentiment.time.sleep"):
        with pytest.raises(
            RuntimeError,
            match="^HTTP_response_too_large$",
        ) as raised:
            _http_get_text(
                f"https://example.test/data?token={secret}",
            )

    assert secret not in str(raised.value)
    assert "token=" not in str(raised.value)
    assert all(
        call.args == ((2 * 1024 * 1024) + 1,)
        for call in response.read.call_args_list
    )


def test_http_get_text_accepts_response_at_two_mib_limit():
    response = MagicMock()
    response.read.return_value = b"x" * (2 * 1024 * 1024)
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    with patch(
        "scripts.market_sentiment.urllib.request.urlopen",
        return_value=response,
    ):
        out = _http_get_text("https://example.test/data")

    assert len(out) == 2 * 1024 * 1024


def test_cboe_adapter_reads_latest_valid_close():
    csv_text = (
        "DATE,OPEN,HIGH,LOW,CLOSE\n"
        "07/15/2026,16.20,16.57,15.64,15.67\n"
        "07/17/2026,broken,broken,broken,\n"
        "07/16/2026,15.82,17.23,15.77,16.73\n"
    )
    with patch(
        "scripts.market_sentiment._http_get_text",
        return_value=csv_text,
    ):
        out = fetch_cboe_vix()

    assert out == {
        "source": "cboe",
        "series": "VIX",
        "official": True,
        "available": True,
        "value": 16.73,
        "as_of": "2026-07-16",
    }


def test_cboe_adapter_returns_auditable_unavailable_record():
    with patch(
        "scripts.market_sentiment._http_get_text",
        side_effect=RuntimeError("network unavailable"),
    ):
        out = fetch_cboe_vix()

    assert out["source"] == "cboe"
    assert out["series"] == "VIX"
    assert out["official"] is True
    assert out["available"] is False
    assert out["as_of"] is None
    assert out["reason"] == "network unavailable"


def test_fred_without_key_is_unavailable(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)

    out = fetch_fred_nfci(api_key="")

    assert out["available"] is False
    assert out["reason"] == "FRED_API_KEY_not_configured"
    assert out["as_of"] is None


def test_fred_explicit_key_takes_priority_over_environment(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "environment-secret")
    payload = {
        "observations": [
            {"date": "2026-07-03", "value": "-0.45"},
        ],
    }
    with patch(
        "scripts.market_sentiment._http_get_text",
        return_value=json.dumps(payload),
    ) as get_text:
        out = fetch_fred_nfci(api_key="argument-secret")

    assert out["available"] is True
    assert out["value"] == -0.45
    requested_url = get_text.call_args.args[0]
    assert "argument-secret" in requested_url
    assert "environment-secret" not in requested_url


def test_fred_adapter_reads_latest_numeric_observation():
    payload = {
        "observations": [
            {"date": "2026-06-26", "value": "-0.31"},
            {"date": "2026-07-10", "value": "."},
            {"date": "2026-07-03", "value": "-0.45"},
        ],
    }
    with patch(
        "scripts.market_sentiment._http_get_text",
        return_value=json.dumps(payload),
    ):
        out = fetch_fred_nfci(api_key="test")

    assert out["available"] is True
    assert out["value"] == -0.45
    assert out["as_of"] == "2026-07-03"


def test_fred_error_reason_does_not_leak_api_key():
    secret = "fred-secret"
    with patch(
        "scripts.market_sentiment._http_get_text",
        side_effect=RuntimeError(
            f"failed https://fred.test?api_key={secret}",
        ),
    ):
        out = fetch_fred_nfci(api_key=secret)

    assert out["available"] is False
    assert secret not in out["reason"]
    assert "api_key=" not in out["reason"]


def _hkex_market(market, turnover, trades, quota, etf):
    return {
        "date": "2026-07-17",
        "market": market,
        "tradingDay": 1,
        "content": [
            {
                "style": 1,
                "table": {
                    "schema": [[
                        "Total Turnover",
                        "Total Trade Count",
                        "DQB",
                        "ETF Turnover",
                    ]],
                    "tr": [
                        {"td": [[turnover]]},
                        {"td": [[trades]]},
                        {"td": [[quota]]},
                        {"td": [[etf]]},
                    ],
                },
            },
        ],
    }


def test_hkex_adapter_treats_one_northbound_market_as_activity_only():
    js_text = (
        "tabData = "
        + json.dumps(
            [_hkex_market(
                "SSE Northbound",
                "181,148.72",
                "8,426,622",
                "999,999,999",
                "3,477.57",
            )],
        )
        + ";"
    )
    with patch(
        "scripts.market_sentiment._http_get_text",
        return_value=js_text,
    ):
        out = fetch_hkex_activity(
            now=datetime(2026, 7, 17, 18, 0),
        )

    assert out["available"] is True
    assert out["directional"] is False
    assert out["as_of"] == "2026-07-17"
    assert out["total_turnover"] == 181148.72
    assert out["trade_count"] == 8426622
    assert out["daily_quota_balance"] == 999999999
    assert out["etf_turnover"] == 3477.57
    assert "score" not in out


def test_hkex_adapter_aggregates_sse_and_szse_northbound():
    js_text = (
        "window.payload = 1;\n"
        "tabData = "
        + json.dumps([
            _hkex_market("SSE Northbound", "100", "10", "1000", "3"),
            _hkex_market("SZSE Northbound", "200", "20", "2000", "4"),
            _hkex_market("Southbound", "900", "90", "9000", "9"),
        ])
        + ";\nwindow.done = true;"
    )
    with patch(
        "scripts.market_sentiment._http_get_text",
        return_value=js_text,
    ):
        out = fetch_hkex_activity(
            now=datetime(2026, 7, 17, 18, 0),
        )

    assert out["total_turnover"] == 300
    assert out["trade_count"] == 30
    assert out["daily_quota_balance"] == 3000
    assert out["etf_turnover"] == 7
    assert "score" not in out


def test_hkex_adapter_parses_tabdata_without_trailing_semicolon():
    js_text = (
        "tabData = "
        + json.dumps([
            _hkex_market("SSE Northbound", "100", "10", "1000", "3"),
        ])
    )
    with patch(
        "scripts.market_sentiment._http_get_text",
        return_value=js_text,
    ):
        out = fetch_hkex_activity(
            now=datetime(2026, 7, 17, 18, 0),
        )

    assert out["available"] is True
    assert out["total_turnover"] == 100


@pytest.mark.parametrize(
    "missing_field",
    [
        "Total Turnover",
        "Total Trade Count",
        "DQB",
        "ETF Turnover",
    ],
)
def test_hkex_rejects_schema_missing_expected_field(missing_field):
    market = _hkex_market(
        "SSE Northbound",
        "100",
        "10",
        "0",
        "0",
    )
    table = market["content"][0]["table"]
    index = table["schema"][0].index(missing_field)
    table["schema"][0].pop(index)
    table["tr"].pop(index)
    with patch(
        "scripts.market_sentiment._http_get_text",
        return_value="tabData = " + json.dumps([market]) + ";",
    ):
        out = fetch_hkex_activity(
            now=datetime(2026, 7, 17, 18, 0),
        )

    assert out["available"] is False


@pytest.mark.parametrize(
    ("turnover", "trades", "quota", "etf"),
    [
        ("0", "10", "0", "0"),
        ("-1", "10", "0", "0"),
        ("100", "0", "0", "0"),
        ("100", "-1", "0", "0"),
        ("100", "10", "-1", "0"),
        ("100", "10", "0", "-1"),
        ("bad", "10", "0", "0"),
        ("100", "bad", "0", "0"),
        ("0", "0", "0", "0"),
    ],
)
def test_hkex_rejects_invalid_or_non_positive_activity_values(
    turnover,
    trades,
    quota,
    etf,
):
    market = _hkex_market(
        "SSE Northbound",
        turnover,
        trades,
        quota,
        etf,
    )
    with patch(
        "scripts.market_sentiment._http_get_text",
        return_value="tabData = " + json.dumps([market]) + ";",
    ):
        out = fetch_hkex_activity(
            now=datetime(2026, 7, 17, 18, 0),
        )

    assert out["available"] is False


def test_hkex_accepts_zero_quota_and_etf_with_positive_activity():
    market = _hkex_market(
        "SSE Northbound",
        "100",
        "10",
        "0",
        "0",
    )
    with patch(
        "scripts.market_sentiment._http_get_text",
        return_value="tabData = " + json.dumps([market]) + ";",
    ):
        out = fetch_hkex_activity(
            now=datetime(2026, 7, 17, 18, 0),
        )

    assert out["available"] is True
    assert out["daily_quota_balance"] == 0
    assert out["etf_turnover"] == 0


def test_hkex_converts_aware_utc_now_to_shanghai_date():
    market = _hkex_market(
        "SSE Northbound",
        "100",
        "10",
        "0",
        "0",
    )
    with patch(
        "scripts.market_sentiment._http_get_text",
        return_value="tabData = " + json.dumps([market]) + ";",
    ) as get_text:
        out = fetch_hkex_activity(
            now=datetime(
                2026,
                7,
                19,
                16,
                30,
                tzinfo=timezone.utc,
            ),
        )

    assert get_text.call_args_list[0].args[0].endswith(
        "20260720e.js",
    )
    assert out["as_of"] == "2026-07-20"


def test_hkex_adapter_stops_date_fallback_after_transport_failure():
    with patch(
        "scripts.market_sentiment._http_get_text",
        side_effect=RuntimeError("unavailable"),
    ) as get_text:
        out = fetch_hkex_activity(
            now=datetime(2026, 7, 19, 18, 0),
        )

    assert out["available"] is False
    assert get_text.call_count == 1
    requested = [call.args[0] for call in get_text.call_args_list]
    assert all("20260718" not in url and "20260719" not in url for url in requested)
    assert requested[0].endswith("20260717e.js")


def test_cffex_requires_configured_authorized_endpoint(monkeypatch):
    monkeypatch.delenv("CFFEX_MARKET_DATA_URL", raising=False)

    out = fetch_cffex_positioning(url="")

    assert out["available"] is False
    assert out["reason"] == "CFFEX_MARKET_DATA_URL_not_configured"
    assert out["as_of"] is None


def test_cffex_validates_required_fields():
    with patch(
        "scripts.market_sentiment._http_get_text",
        return_value=json.dumps({"contract": "IF2607"}),
    ):
        out = fetch_cffex_positioning(
            url="https://licensed.test/cffex",
        )

    assert out["available"] is False
    assert out["reason"] == "invalid_authorized_CFFEX_payload"


def _cffex_payload(contract):
    return {
        "contract": contract,
        "trading_date": "2026-07-17",
        "close": "4040",
        "spot_close": "4000",
        "volume": "123456",
        "open_interest": "106000",
        "previous_open_interest": "100000",
    }


@pytest.mark.parametrize(
    "contract",
    [
        "IH2607",
        "IC2607",
        "IM2607",
        "IF9999",
        "IF2600",
        "IF2613",
        "",
        "   ",
        None,
        "IF",
        "IF260",
        "IF26070",
        "XIF2607",
        "IF2607X",
        "IF26A7",
    ],
)
def test_cffex_rejects_non_csi_300_or_malformed_contracts(contract):
    with patch(
        "scripts.market_sentiment._http_get_text",
        return_value=json.dumps(_cffex_payload(contract)),
    ):
        out = fetch_cffex_positioning(
            url="https://licensed.test/cffex",
        )

    assert out["available"] is False
    assert out["reason"] == "unsupported_CFFEX_contract"


def test_cffex_accepts_trimmed_case_insensitive_if_contract():
    with patch(
        "scripts.market_sentiment._http_get_text",
        return_value=json.dumps(_cffex_payload("  if2607  ")),
    ):
        out = fetch_cffex_positioning(
            url="https://licensed.test/cffex",
        )

    assert out["available"] is True
    assert out["contract"] == "IF2607"


@pytest.mark.parametrize(
    "trading_date",
    [
        "garbage",
        "2026-02-30",
        "20260230",
        "2026-07-17T12:00:00",
        " 2026-07-17 ",
        "",
        None,
    ],
)
def test_cffex_rejects_invalid_or_non_strict_trading_dates(
    trading_date,
):
    payload = {
        **_cffex_payload("IF2607"),
        "trading_date": trading_date,
    }
    with patch(
        "scripts.market_sentiment._http_get_text",
        return_value=json.dumps(payload),
    ):
        out = fetch_cffex_positioning(
            url="https://licensed.test/cffex",
        )

    assert out["available"] is False
    assert out["reason"] == "invalid_CFFEX_trading_date"


def test_cffex_accepts_and_normalizes_compact_trading_date():
    payload = {
        **_cffex_payload("IF2607"),
        "trading_date": "20260717",
    }
    with patch(
        "scripts.market_sentiment._http_get_text",
        return_value=json.dumps(payload),
    ):
        out = fetch_cffex_positioning(
            url="https://licensed.test/cffex",
        )

    assert out["available"] is True
    assert out["as_of"] == "2026-07-17"


@pytest.mark.parametrize(
    "field",
    [
        "volume",
        "open_interest",
        "previous_open_interest",
    ],
)
@pytest.mark.parametrize("value", [1.5, "1.5"])
def test_cffex_rejects_fractional_integer_fields(field, value):
    payload = _cffex_payload("IF2607")
    payload[field] = value
    with patch(
        "scripts.market_sentiment._http_get_text",
        return_value=json.dumps(payload),
    ):
        out = fetch_cffex_positioning(
            url="https://licensed.test/cffex",
        )

    assert out["available"] is False
    assert out["reason"] == "invalid_CFFEX_numeric_values"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("close", 0),
        ("close", -1),
        ("spot_close", 0),
        ("spot_close", -1),
        ("open_interest", 0),
        ("open_interest", -1),
        ("previous_open_interest", 0),
        ("previous_open_interest", -1),
        ("volume", -1),
    ],
)
def test_cffex_rejects_numeric_values_outside_domain(field, value):
    payload = _cffex_payload("IF2607")
    payload[field] = value
    with patch(
        "scripts.market_sentiment._http_get_text",
        return_value=json.dumps(payload),
    ):
        out = fetch_cffex_positioning(
            url="https://licensed.test/cffex",
        )

    assert out["available"] is False
    assert out["reason"] == "invalid_CFFEX_numeric_values"


@pytest.mark.parametrize(
    "field",
    [
        "close",
        "spot_close",
        "open_interest",
        "previous_open_interest",
        "volume",
    ],
)
@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        True,
        False,
        "not-a-number",
    ],
)
def test_cffex_rejects_non_finite_bool_and_malformed_numbers(
    field,
    value,
):
    secret = "payload-secret"
    payload = _cffex_payload("IF2607")
    payload[field] = value if value != "not-a-number" else secret
    endpoint = "https://licensed.test/cffex?token=url-secret"
    with patch(
        "scripts.market_sentiment._http_get_text",
        return_value=json.dumps(payload),
    ):
        out = fetch_cffex_positioning(url=endpoint)

    assert out["available"] is False
    assert out["reason"] == "invalid_CFFEX_numeric_values"
    assert secret not in out["reason"]
    assert "url-secret" not in out["reason"]
    assert "token=" not in out["reason"]


def test_cffex_accepts_zero_volume_with_positive_price_and_interest():
    payload = {
        **_cffex_payload("IF2607"),
        "volume": 0,
    }
    with patch(
        "scripts.market_sentiment._http_get_text",
        return_value=json.dumps(payload),
    ):
        out = fetch_cffex_positioning(
            url="https://licensed.test/cffex",
        )

    assert out["available"] is True
    assert out["volume"] == 0


def test_cffex_scores_basis_and_open_interest_with_decimal_half_even():
    payload = _cffex_payload("IF2607")
    with patch(
        "scripts.market_sentiment._http_get_text",
        return_value=json.dumps(payload),
    ):
        out = fetch_cffex_positioning(
            url="https://licensed.test/cffex",
        )

    assert out["available"] is True
    assert out["basis_pct"] == 1.0
    assert out["oi_change_pct"] == 6.0
    assert out["score"] == 80.0
    assert out["volume"] == 123456


def test_cffex_preserves_authorized_decimal_input_without_float_round_trip():
    payload = {
        **_cffex_payload("IF2607"),
        "volume": "9007199254740993",
    }
    with patch(
        "scripts.market_sentiment._http_get_text",
        return_value=json.dumps(payload),
    ):
        out = fetch_cffex_positioning(
            url="https://licensed.test/cffex",
        )

    assert out["volume"] == 9007199254740993


def test_cffex_error_reason_does_not_leak_endpoint_query():
    secret = "cffex-secret"
    endpoint = f"https://licensed.test/cffex?token={secret}"
    with patch(
        "scripts.market_sentiment._http_get_text",
        side_effect=RuntimeError(f"failed endpoint {endpoint}"),
    ):
        out = fetch_cffex_positioning(url=endpoint)

    assert out["available"] is False
    assert secret not in out["reason"]
    assert "token=" not in out["reason"]


class _FakeCache:
    def __init__(self, initial=None):
        self.data = dict(initial or {})
        self.set_calls = []

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ttl=None):
        self.data[key] = value
        self.set_calls.append((key, value, ttl))


def _available_source(source, as_of, **values):
    return {
        "source": source,
        "official": True,
        "available": True,
        "as_of": as_of,
        **values,
    }


def _unavailable_source(source, reason="not available", **values):
    return {
        "source": source,
        "official": True,
        "available": False,
        "as_of": None,
        "reason": reason,
        **values,
    }


def _cached_component(source, as_of):
    base = {
        "source": source,
        "official": True,
        "available": True,
        "as_of": as_of,
        "stale": False,
    }
    if source == "cboe":
        return {
            **base,
            "series": "VIX",
            "value": 20,
            "score": 50,
            "weight": 50,
        }
    if source == "fred":
        return {
            **base,
            "series": "NFCI",
            "value": 0,
            "score": 50,
            "weight": 30,
        }
    if source == "cffex":
        return {
            **base,
            "score": 50,
            "weight": 20,
        }
    return {
        **base,
        "directional": False,
        "total_turnover": 100,
        "trade_count": 10,
        "daily_quota_balance": 0,
        "etf_turnover": 0,
    }


def _collect_with_sources(
    *,
    now,
    cboe=None,
    fred=None,
    hkex=None,
    cffex=None,
    fake_cache=None,
):
    target_cache = fake_cache or _FakeCache()
    with patch("scripts.market_sentiment.cache", target_cache), patch(
        "scripts.market_sentiment.fetch_cboe_vix",
        return_value=cboe or _unavailable_source("cboe", series="VIX"),
    ), patch(
        "scripts.market_sentiment.fetch_fred_nfci",
        return_value=fred or _unavailable_source("fred", series="NFCI"),
    ), patch(
        "scripts.market_sentiment.fetch_hkex_activity",
        return_value=hkex or _unavailable_source(
            "hkex",
            directional=False,
        ),
    ), patch(
        "scripts.market_sentiment.fetch_cffex_positioning",
        return_value=cffex or _unavailable_source("cffex"),
    ):
        return collect_market_sentiment(now=now), target_cache


def test_collection_uses_shanghai_date_for_aware_utc_now():
    now = datetime(
        2026,
        7,
        17,
        16,
        30,
        tzinfo=timezone.utc,
    )
    result, fake_cache = _collect_with_sources(now=now)

    assert result["generated_at"] == "2026-07-18 00:30:00"
    assert [call[0] for call in fake_cache.set_calls] == [
        "global:sentiment:latest",
        "global:sentiment:20260718",
    ]


def test_collection_interprets_naive_now_as_shanghai_time():
    fake_cache = _FakeCache()
    with patch(
        "scripts.market_sentiment.cache",
        fake_cache,
    ), patch(
        "scripts.market_sentiment.fetch_cboe_vix",
        return_value=_unavailable_source("cboe"),
    ), patch(
        "scripts.market_sentiment.fetch_fred_nfci",
        return_value=_unavailable_source("fred"),
    ), patch(
        "scripts.market_sentiment.fetch_hkex_activity",
        return_value=_unavailable_source(
            "hkex",
            directional=False,
        ),
    ) as fetch_hkex, patch(
        "scripts.market_sentiment.fetch_cffex_positioning",
        return_value=_unavailable_source("cffex"),
    ):
        result = collect_market_sentiment(
            now=datetime(2026, 7, 17, 18, 0),
        )

    passed_now = fetch_hkex.call_args.kwargs["now"]
    assert passed_now.tzinfo == ZoneInfo("Asia/Shanghai")
    assert passed_now.utcoffset() == timedelta(hours=8)
    assert result["generated_at"] == "2026-07-17 18:00:00"


def test_collection_starts_independent_sources_concurrently():
    barrier = threading.Barrier(4)
    failures = []

    def unavailable(source, **values):
        def fetch(*args, **kwargs):
            try:
                barrier.wait(timeout=1)
            except threading.BrokenBarrierError:
                failures.append(source)
            return _unavailable_source(source, **values)

        return fetch

    fake_cache = _FakeCache()
    with patch(
        "scripts.market_sentiment.cache",
        fake_cache,
    ), patch(
        "scripts.market_sentiment.fetch_cboe_vix",
        side_effect=unavailable("cboe"),
    ), patch(
        "scripts.market_sentiment.fetch_fred_nfci",
        side_effect=unavailable("fred"),
    ), patch(
        "scripts.market_sentiment.fetch_hkex_activity",
        side_effect=unavailable("hkex", directional=False),
    ), patch(
        "scripts.market_sentiment.fetch_cffex_positioning",
        side_effect=unavailable("cffex"),
    ):
        collect_market_sentiment(now=datetime(2026, 7, 17, 18, 0))

    assert failures == []


def test_collection_rejects_mismatched_reported_source():
    result, _ = _collect_with_sources(
        now=datetime(2026, 7, 17, 18, 0),
        cboe=_available_source(
            "fred",
            "2026-07-17",
            series="VIX",
            value=12,
        ),
    )

    component = result["components"]["volatility"]
    source = next(
        item for item in result["sources"]
        if item["source"] == "cboe"
    )
    assert component["available"] is False
    assert component["reported_source"] == "fred"
    assert source["status"] == "unavailable"
    assert source["reason"] == "source_mismatch"
    assert result["confidence"] == 0
    assert "cboe:unavailable" in result["warnings"]


def test_collection_weights_only_directional_official_components():
    now = datetime(2026, 7, 17, 18, 0)
    result, _ = _collect_with_sources(
        now=now,
        cboe=_available_source(
            "cboe",
            "2026-07-17",
            series="VIX",
            value=20,
        ),
        fred=_available_source(
            "fred",
            "2026-07-10",
            series="NFCI",
            value=0,
        ),
        hkex=_available_source(
            "hkex",
            "2026-07-17",
            directional=False,
            total_turnover=999999999,
        ),
        cffex=_available_source(
            "cffex",
            "2026-07-17",
            score=75,
        ),
    )

    assert result["sentiment_score"] == 55
    assert result["confidence"] == 1
    assert result["generated_at"] == "2026-07-17 18:00:00"
    assert result["components"]["volatility"]["weight"] == 50
    assert result["components"]["financial_conditions"]["weight"] == 30
    assert result["components"]["futures_positioning"]["weight"] == 20
    hkex = result["components"]["cross_border_activity"]
    assert hkex["directional"] is False
    assert "score" not in hkex
    assert "weight" not in hkex
    _assert_shadow_only(result)


@pytest.mark.parametrize(
    ("source_name", "as_of", "expected_status", "expected_confidence"),
    [
        ("cboe", "2026-07-13", "live", 0.5),
        ("cboe", "2026-07-12", "stale", 0.25),
        ("fred", "2026-07-07", "live", 0.3),
        ("fred", "2026-07-06", "stale", 0.15),
        ("cffex", "2026-07-13", "live", 0.2),
        ("cffex", "2026-07-12", "stale", 0.1),
    ],
)
def test_collection_applies_calendar_day_freshness_boundaries(
    source_name,
    as_of,
    expected_status,
    expected_confidence,
):
    now = datetime(2026, 7, 17, 18, 0)
    sources = {
        "cboe": _unavailable_source("cboe", series="VIX"),
        "fred": _unavailable_source("fred", series="NFCI"),
        "hkex": _unavailable_source("hkex", directional=False),
        "cffex": _unavailable_source("cffex"),
    }
    if source_name == "cboe":
        sources["cboe"] = _available_source(
            "cboe",
            as_of,
            series="VIX",
            value=20,
        )
    elif source_name == "fred":
        sources["fred"] = _available_source(
            "fred",
            as_of,
            series="NFCI",
            value=0,
        )
    else:
        sources["cffex"] = _available_source(
            "cffex",
            as_of,
            score=50,
        )

    result, _ = _collect_with_sources(now=now, **sources)

    source = next(
        item for item in result["sources"]
        if item["source"] == source_name
    )
    assert source["status"] == expected_status
    assert result["confidence"] == expected_confidence
    assert result["components"][
        {
            "cboe": "volatility",
            "fred": "financial_conditions",
            "cffex": "futures_positioning",
        }[source_name]
    ]["stale"] is (expected_status == "stale")


@pytest.mark.parametrize(
    ("source_name", "component_name"),
    [
        ("cboe", "volatility"),
        ("fred", "financial_conditions"),
        ("hkex", "cross_border_activity"),
        ("cffex", "futures_positioning"),
    ],
)
def test_collection_rejects_sources_from_2020_as_too_old(
    source_name,
    component_name,
):
    sources = {
        "cboe": _unavailable_source("cboe", series="VIX"),
        "fred": _unavailable_source("fred", series="NFCI"),
        "hkex": _unavailable_source("hkex", directional=False),
        "cffex": _unavailable_source("cffex"),
    }
    if source_name == "cboe":
        sources["cboe"] = _available_source(
            "cboe",
            "2020-01-01",
            series="VIX",
            value=20,
        )
    elif source_name == "fred":
        sources["fred"] = _available_source(
            "fred",
            "2020-01-01",
            series="NFCI",
            value=0,
        )
    elif source_name == "hkex":
        sources["hkex"] = _available_source(
            "hkex",
            "2020-01-01",
            directional=False,
            total_turnover=100,
            trade_count=10,
            daily_quota_balance=0,
            etf_turnover=0,
        )
    else:
        sources["cffex"] = _available_source(
            "cffex",
            "2020-01-01",
            score=50,
        )

    result, _ = _collect_with_sources(
        now=datetime(2026, 7, 17, 18, 0),
        **sources,
    )

    source = next(
        item for item in result["sources"]
        if item["source"] == source_name
    )
    assert source["status"] == "unavailable"
    assert source["reason"] == "source_too_old"
    assert result["components"][component_name]["available"] is False
    assert result["confidence"] == 0


@pytest.mark.parametrize(
    (
        "source_name",
        "component_name",
        "as_of",
        "expected_confidence",
    ),
    [
        ("cboe", "volatility", "2026-07-07", 0.25),
        ("cffex", "futures_positioning", "2026-07-07", 0.1),
        ("hkex", "cross_border_activity", "2026-07-07", 0.0),
        ("fred", "financial_conditions", "2026-06-17", 0.15),
    ],
)
def test_cached_fallback_is_allowed_at_absolute_age_boundary(
    source_name,
    component_name,
    as_of,
    expected_confidence,
):
    fake_cache = _FakeCache({
        "global:sentiment:latest": {
            "components": {
                component_name: _cached_component(source_name, as_of),
            },
        },
    })

    result, _ = _collect_with_sources(
        now=datetime(2026, 7, 17, 18, 0),
        fake_cache=fake_cache,
    )

    source = next(
        item for item in result["sources"]
        if item["source"] == source_name
    )
    component = result["components"][component_name]
    assert source["status"] == "stale"
    assert component["fallback_from_cache"] is True
    assert component["as_of"] == as_of
    assert result["confidence"] == expected_confidence


@pytest.mark.parametrize(
    ("source_name", "component_name", "as_of"),
    [
        ("cboe", "volatility", "2026-07-06"),
        ("cffex", "futures_positioning", "2026-07-06"),
        ("hkex", "cross_border_activity", "2026-07-06"),
        ("fred", "financial_conditions", "2026-06-16"),
    ],
)
def test_cached_fallback_is_rejected_one_day_past_absolute_age(
    source_name,
    component_name,
    as_of,
):
    fake_cache = _FakeCache({
        "global:sentiment:latest": {
            "components": {
                component_name: _cached_component(source_name, as_of),
            },
        },
    })

    result, _ = _collect_with_sources(
        now=datetime(2026, 7, 17, 18, 0),
        fake_cache=fake_cache,
    )

    source = next(
        item for item in result["sources"]
        if item["source"] == source_name
    )
    assert source["status"] == "unavailable"
    assert result["components"][component_name]["available"] is False
    assert result["confidence"] == 0


def test_consecutive_cache_fallback_keeps_original_as_of_and_expires():
    original_as_of = "2026-07-07"
    fake_cache = _FakeCache({
        "global:sentiment:latest": {
            "components": {
                "volatility": _cached_component(
                    "cboe",
                    original_as_of,
                ),
            },
        },
    })

    first, _ = _collect_with_sources(
        now=datetime(2026, 7, 17, 18, 0),
        fake_cache=fake_cache,
    )
    second, _ = _collect_with_sources(
        now=datetime(2026, 7, 18, 18, 0),
        fake_cache=fake_cache,
    )

    assert first["components"]["volatility"]["as_of"] == original_as_of
    assert first["components"]["volatility"]["fallback_from_cache"] is True
    assert second["components"]["volatility"]["available"] is False
    assert second["confidence"] == 0


def test_hkex_freshness_is_audited_without_affecting_score_or_confidence():
    result, _ = _collect_with_sources(
        now=datetime(2026, 7, 17, 18, 0),
        cboe=_available_source(
            "cboe",
            "2026-07-17",
            series="VIX",
            value=20,
        ),
        hkex=_available_source(
            "hkex",
            "2026-07-12",
            directional=False,
            total_turnover=123,
        ),
    )

    hkex_source = next(
        item for item in result["sources"]
        if item["source"] == "hkex"
    )
    assert hkex_source["status"] == "stale"
    assert result["sentiment_score"] == 50
    assert result["confidence"] == 0.5
    assert result["stale"] is True
    assert "score" not in result["components"]["cross_border_activity"]
    assert "weight" not in result["components"]["cross_border_activity"]


def test_collection_strips_any_directional_fields_from_hkex_context():
    result, _ = _collect_with_sources(
        now=datetime(2026, 7, 17, 18, 0),
        hkex=_available_source(
            "hkex",
            "2026-07-17",
            directional=False,
            total_turnover=123,
            score=100,
            weight=100,
        ),
    )

    hkex = result["components"]["cross_border_activity"]
    assert "score" not in hkex
    assert "weight" not in hkex
    assert result["sentiment_score"] == 50
    assert result["confidence"] == 0


@pytest.mark.parametrize("source_name", ["cboe", "fred", "hkex", "cffex"])
def test_future_dated_source_is_invalid_and_does_not_contribute(
    source_name,
):
    sources = {
        "cboe": _unavailable_source("cboe", series="VIX"),
        "fred": _unavailable_source("fred", series="NFCI"),
        "hkex": _unavailable_source("hkex", directional=False),
        "cffex": _unavailable_source("cffex"),
    }
    if source_name == "cboe":
        sources["cboe"] = _available_source(
            "cboe",
            "2026-07-18",
            series="VIX",
            value=12,
        )
    elif source_name == "fred":
        sources["fred"] = _available_source(
            "fred",
            "2026-07-18",
            series="NFCI",
            value=-0.8,
        )
    elif source_name == "hkex":
        sources["hkex"] = _available_source(
            "hkex",
            "2026-07-18",
            directional=False,
            total_turnover=123,
        )
    else:
        sources["cffex"] = _available_source(
            "cffex",
            "2026-07-18",
            score=90,
        )

    result, _ = _collect_with_sources(
        now=datetime(2026, 7, 17, 18, 0),
        **sources,
    )

    source = next(
        item for item in result["sources"]
        if item["source"] == source_name
    )
    assert source["status"] == "unavailable"
    assert source["reason"] == "future_as_of_date"
    assert result["sentiment_score"] == 50
    assert result["confidence"] == 0


def test_failed_current_fetch_reuses_cached_component_as_stale():
    cached_component = {
        "source": "cboe",
        "series": "VIX",
        "official": True,
        "available": True,
        "value": 30,
        "as_of": "2026-07-16",
        "score": 25,
        "weight": 50,
        "stale": False,
    }
    fake_cache = _FakeCache({
        "global:sentiment:latest": {
            "components": {
                "volatility": cached_component,
            },
        },
    })

    result, _ = _collect_with_sources(
        now=datetime(2026, 7, 17, 18, 0),
        cboe=_unavailable_source("cboe", reason="network down"),
        fake_cache=fake_cache,
    )

    component = result["components"]["volatility"]
    assert component["value"] == 30
    assert component["score"] == 25
    assert component["as_of"] == "2026-07-16"
    assert component["stale"] is True
    assert component["fallback_from_cache"] is True
    assert result["sentiment_score"] == 25
    assert result["confidence"] == 0.25
    assert "cboe:stale_cache_fallback" in result["warnings"]
    source = next(
        item for item in result["sources"]
        if item["source"] == "cboe"
    )
    assert source["status"] == "stale"
    assert source["reason"] == "network down; cache_fallback"


def test_expired_current_fetch_prefers_newer_cached_component():
    fake_cache = _FakeCache({
        "global:sentiment:latest": {
            "components": {
                "financial_conditions": {
                    "source": "fred",
                    "series": "NFCI",
                    "official": True,
                    "available": True,
                    "value": 0,
                    "as_of": "2026-07-10",
                    "score": 50,
                    "weight": 30,
                    "stale": False,
                },
            },
        },
    })

    result, _ = _collect_with_sources(
        now=datetime(2026, 7, 17, 18, 0),
        fred=_available_source(
            "fred",
            "2026-06-01",
            series="NFCI",
            value=1,
        ),
        fake_cache=fake_cache,
    )

    component = result["components"]["financial_conditions"]
    assert component["as_of"] == "2026-07-10"
    assert component["value"] == 0
    assert component["stale"] is True
    assert component["fallback_from_cache"] is True
    assert result["confidence"] == 0.15
    assert "fred:stale_cache_fallback" in result["warnings"]


def test_failed_fetch_without_cache_returns_neutral_zero_confidence():
    result, _ = _collect_with_sources(
        now=datetime(2026, 7, 17, 18, 0),
    )

    assert result["sentiment_score"] == 50
    assert result["sentiment_regime"] == "neutral"
    assert result["confidence"] == 0
    assert result["warnings"][0] == "official_sources_unavailable"
    assert all(
        source["status"] == "unavailable"
        for source in result["sources"]
    )
    _assert_shadow_only(result)


def test_collection_writes_latest_and_now_dated_cache_keys():
    now = datetime(2026, 7, 17, 23, 59, 59)
    result, fake_cache = _collect_with_sources(now=now)

    assert [call[0] for call in fake_cache.set_calls] == [
        "global:sentiment:latest",
        "global:sentiment:20260717",
    ]
    assert fake_cache.data["global:sentiment:latest"] == result
    assert fake_cache.data["global:sentiment:20260717"] == result


def test_sources_always_have_audit_fields():
    result, _ = _collect_with_sources(
        now=datetime(2026, 7, 17, 18, 0),
    )

    for source in result["sources"]:
        assert set(source) == {
            "source",
            "official",
            "status",
            "as_of",
            "reason",
        }


def test_get_market_sentiment_status_returns_cached_result():
    expected = {
        "sentiment_score": 42,
        "sentiment_regime": "neutral",
        "confidence": 0.5,
        "mode": "shadow_only",
        "can_change_trade_policy": False,
        "can_trigger_order": False,
    }
    with patch(
        "scripts.market_sentiment.cache",
        _FakeCache({"global:sentiment:latest": expected}),
    ):
        assert get_market_sentiment_status() == expected


def test_get_market_sentiment_status_overrides_polluted_authority_flags():
    cached = {
        "sentiment_score": 75,
        "sentiment_regime": "greed",
        "confidence": 0.8,
        "mode": "live_trading",
        "can_change_trade_policy": True,
        "can_trigger_order": True,
    }
    with patch(
        "scripts.market_sentiment.cache",
        _FakeCache({"global:sentiment:latest": cached}),
    ):
        result = get_market_sentiment_status()

    assert result["sentiment_score"] == 75
    _assert_shadow_only(result)


@pytest.mark.parametrize(
    "cached",
    [
        "polluted",
        [],
        123,
        {},
        {"sentiment_score": 42},
        {
            "sentiment_score": 42,
            "sentiment_regime": "neutral",
        },
        {
            "sentiment_score": float("nan"),
            "sentiment_regime": "neutral",
            "confidence": 0.5,
        },
    ],
)
def test_get_market_sentiment_status_rejects_invalid_cached_shapes(
    cached,
):
    with patch(
        "scripts.market_sentiment.cache",
        _FakeCache({"global:sentiment:latest": cached}),
    ):
        result = get_market_sentiment_status()

    assert result["sentiment_score"] == 50
    assert result["sentiment_regime"] == "neutral"
    assert result["confidence"] == 0
    _assert_shadow_only(result)


def test_get_market_sentiment_status_returns_safe_neutral_fallback():
    with patch("scripts.market_sentiment.cache", _FakeCache()):
        result = get_market_sentiment_status()

    assert result["sentiment_score"] == 50
    assert result["confidence"] == 0
    _assert_shadow_only(result)


def test_cli_run_outputs_json_with_enforced_shadow_only_flags(capsys):
    collected = {
        "sentiment_score": 61,
        "mode": "unsafe",
        "can_change_trade_policy": True,
        "can_trigger_order": True,
    }
    with patch(
        "scripts.market_sentiment.collect_market_sentiment",
        return_value=collected,
    ) as collect:
        exit_code = _main(["--run"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    collect.assert_called_once_with()
    assert payload["sentiment_score"] == 61
    assert payload["mode"] == "shadow_only"
    assert payload["can_change_trade_policy"] is False
    assert payload["can_trigger_order"] is False


def test_cli_without_run_does_not_collect(capsys):
    with patch(
        "scripts.market_sentiment.collect_market_sentiment",
    ) as collect:
        exit_code = _main([])

    assert exit_code == 0
    collect.assert_not_called()
    assert capsys.readouterr().out == ""


def test_script_entrypoint_without_run_exits_cleanly_without_network():
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(root / "scripts" / "market_sentiment.py")],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout == ""
    assert completed.stderr == ""

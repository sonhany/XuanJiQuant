from __future__ import annotations

import json
from contextlib import ExitStack
from unittest.mock import patch

import pytest


class FakeCache:
    def __init__(self, data=None):
        self.data = dict(data or {})

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ttl=None):
        self.data[key] = value


class SerializationFakeCache(FakeCache):
    def set(self, key, value, ttl=None):
        self.data[key] = json.loads(json.dumps(value, allow_nan=False))


def _collect_context_with_sentiment(sentiment=None, *, sentiment_error=None):
    from scripts import global_context

    with ExitStack() as stack:
        stack.enter_context(patch.object(global_context, "cache", FakeCache()))
        stack.enter_context(
            patch.object(global_context, "_fetch_tdx_indices", return_value={})
        )
        stack.enter_context(
            patch.object(global_context, "_fetch_sina_indices", return_value={})
        )
        stack.enter_context(
            patch.object(
                global_context,
                "_fetch_jin10_macro",
                return_value={"quotes": [], "calendar": []},
            )
        )
        stack.enter_context(
            patch("scripts.market_data.fetch_sector_flow", return_value=[])
        )
        stack.enter_context(
            patch(
                "scripts.market_data.fetch_northbound",
                return_value={"northFlow": 0, "trend": "neutral"},
            )
        )
        collector = stack.enter_context(
            patch("scripts.market_sentiment.collect_market_sentiment")
        )
        if sentiment_error is not None:
            collector.side_effect = sentiment_error
        else:
            collector.return_value = sentiment
        return global_context.collect_global_context()


def test_global_context_adds_sentiment_without_changing_legacy_policy():
    sentiment = {
        "sentiment_score": 10,
        "sentiment_regime": "extreme_fear",
        "confidence": 1.0,
        "mode": "shadow_only",
        "can_change_trade_policy": False,
        "can_trigger_order": False,
        "sources": [{"source": "cboe", "status": "live"}],
    }

    out = _collect_context_with_sentiment(sentiment)

    assert out["sentiment"] == sentiment
    assert out["risk_level"] == "low"
    assert out["risk_signals"] == []
    assert out["trade_policy"] == "normal"


def test_global_context_sentiment_collection_failure_is_fail_closed():
    out = _collect_context_with_sentiment(
        sentiment_error=RuntimeError("official feed unavailable")
    )

    assert out["sentiment"]["sentiment_score"] == 50.0
    assert out["sentiment"]["sentiment_regime"] == "neutral"
    assert out["sentiment"]["confidence"] == 0.0
    assert out["sentiment"]["mode"] == "shadow_only"
    assert out["sentiment"]["can_change_trade_policy"] is False
    assert out["sentiment"]["can_trigger_order"] is False
    assert out["sentiment"]["warnings"] == ["sentiment_unavailable:collector_error"]
    assert out["trade_policy"] == "normal"


def test_global_context_exception_warning_does_not_leak_secrets():
    out = _collect_context_with_sentiment(
        sentiment_error=RuntimeError(
            "https://official.example/data?api_key=TOPSECRET&token=TOKENVALUE "
            "password=PASSVALUE secret=SECRETVALUE key=KEYVALUE"
        )
    )

    serialized = json.dumps(out["sentiment"], ensure_ascii=False)
    for secret in (
        "TOPSECRET",
        "TOKENVALUE",
        "PASSVALUE",
        "SECRETVALUE",
        "KEYVALUE",
    ):
        assert secret not in serialized
    assert out["sentiment"]["warnings"] == ["sentiment_unavailable:collector_error"]
    assert len(out["sentiment"]["warnings"][0]) <= 120


@pytest.mark.parametrize(
    "bad_sentiment",
    [
        [],
        "fear",
        True,
        None,
    ],
)
def test_global_context_non_dict_sentiment_becomes_safe_neutral(bad_sentiment):
    out = _collect_context_with_sentiment(bad_sentiment)

    assert out["sentiment"] == {
        "sentiment_score": 50.0,
        "sentiment_regime": "neutral",
        "confidence": 0.0,
        "mode": "shadow_only",
        "can_change_trade_policy": False,
        "can_trigger_order": False,
        "sources": [],
        "warnings": ["invalid_sentiment_payload"],
    }
    assert out["trade_policy"] == "normal"


@pytest.mark.parametrize(
    ("score", "confidence"),
    [
        (float("nan"), float("inf")),
        (float("-inf"), float("nan")),
        (True, False),
    ],
)
def test_global_context_invalid_numeric_sentiment_is_neutral(score, confidence):
    out = _collect_context_with_sentiment(
        {
            "sentiment_score": score,
            "sentiment_regime": ["extreme_greed"],
            "confidence": confidence,
        }
    )

    assert out["sentiment"]["sentiment_score"] == 50.0
    assert out["sentiment"]["sentiment_regime"] == "neutral"
    assert out["sentiment"]["confidence"] == 0.0


def test_global_context_sanitizes_polluted_sentiment_contract():
    out = _collect_context_with_sentiment(
        {
            "sentiment_score": 140,
            "sentiment_regime": "not-a-regime",
            "confidence": -3,
            "mode": "unsafe",
            "can_change_trade_policy": True,
            "can_trigger_order": True,
            "sources": [
                {
                    "source": " cboe ",
                    "status": "live",
                    "reason": "must be removed",
                    "payload": {"secret": "hidden"},
                },
                {"source": "fred", "status": "stale"},
                {"source": "cffex", "status": "unavailable"},
                {"source": "bad-status", "status": ["live"]},
                {"source": True, "status": "live"},
                {"source": "x" * 65, "status": "live"},
                [],
            ],
            "warnings": [
                "https://example.test/feed?api_key=TOPSECRET&token=TOKENVALUE",
                "password=PASSVALUE secret=SECRETVALUE key=KEYVALUE",
                123,
                "x" * 200,
            ],
            "components": {"unsafe": object()},
        }
    )

    sentiment = out["sentiment"]
    assert sentiment["sentiment_score"] == 100.0
    assert sentiment["sentiment_regime"] == "extreme_greed"
    assert sentiment["confidence"] == 0.0
    assert sentiment["mode"] == "shadow_only"
    assert sentiment["can_change_trade_policy"] is False
    assert sentiment["can_trigger_order"] is False
    assert sentiment["sources"] == [
        {"source": "cboe", "status": "live"},
        {"source": "fred", "status": "stale"},
        {"source": "cffex", "status": "unavailable"},
    ]
    assert "components" not in sentiment
    assert all(isinstance(item, str) and len(item) <= 120 for item in sentiment["warnings"])
    serialized = json.dumps(sentiment, ensure_ascii=False)
    for secret in (
        "TOPSECRET",
        "TOKENVALUE",
        "PASSVALUE",
        "SECRETVALUE",
        "KEYVALUE",
        "hidden",
    ):
        assert secret not in serialized


def test_global_context_clamps_numeric_sentiment():
    low = _collect_context_with_sentiment(
        {
            "sentiment_score": -5,
            "sentiment_regime": "invalid",
            "confidence": -1,
        }
    )["sentiment"]
    high = _collect_context_with_sentiment(
        {
            "sentiment_score": 105,
            "sentiment_regime": "invalid",
            "confidence": 2,
        }
    )["sentiment"]

    assert (low["sentiment_score"], low["sentiment_regime"], low["confidence"]) == (
        0.0,
        "extreme_fear",
        0.0,
    )
    assert (
        high["sentiment_score"],
        high["sentiment_regime"],
        high["confidence"],
    ) == (100.0, "extreme_greed", 1.0)


def test_global_context_persists_sentiment_during_cached_quote_fallback():
    from scripts import global_context

    sentiment = {
        "sentiment_score": 40,
        "sentiment_regime": "fear",
        "confidence": 0.5,
        "mode": "shadow_only",
        "can_change_trade_policy": False,
        "can_trigger_order": False,
    }
    cache = FakeCache(
        {
            "global:context:latest": {
                "risk_level": "low",
                "risk_signals": [],
                "trade_policy": "normal",
            }
        }
    )

    with patch.object(global_context, "cache", cache), patch.object(
        global_context, "_fetch_tdx_indices", return_value={}
    ), patch.object(
        global_context, "_fetch_sina_indices", return_value={}
    ), patch(
        "scripts.market_sentiment.collect_market_sentiment",
        return_value=sentiment,
    ):
        out = global_context.collect_global_context()

    assert out["sentiment"] == sentiment
    assert cache.get("global:context:latest")["sentiment"] == sentiment
    assert out["trade_policy"] == "normal"


def test_global_context_cached_quote_fallback_persists_complete_serialized_value():
    from scripts import global_context

    cache = SerializationFakeCache(
        {
            "global:context:latest": {
                "risk_level": "low",
                "risk_signals": [],
                "trade_policy": "normal",
            }
        }
    )
    sentiment = {
        "sentiment_score": 50,
        "sentiment_regime": "neutral",
        "confidence": 0.5,
    }

    with patch.object(global_context, "cache", cache), patch.object(
        global_context, "_fetch_tdx_indices", return_value={}
    ), patch.object(
        global_context, "_fetch_sina_indices", return_value={}
    ), patch(
        "scripts.market_sentiment.collect_market_sentiment",
        return_value=sentiment,
    ):
        out = global_context.collect_global_context()

    persisted = cache.get("global:context:latest")
    assert persisted == out
    assert persisted["stale"] is True
    assert isinstance(persisted["error"], str)
    assert persisted["error"]


def test_shadow_signals_include_sentiment_without_execution_authority():
    from quant.research.shadow_signals import build_shadow_signals

    cache = FakeCache(
        {
            "global:context:latest": {
                "sentiment": {
                    "sentiment_score": 25,
                    "sentiment_regime": "fear",
                    "confidence": 0.5,
                    "sources": [
                        {"source": "cboe", "status": "live"},
                        {"source": "fred", "status": "stale"},
                        {"source": "cffex", "status": "unavailable"},
                    ],
                }
            }
        }
    )

    out = build_shadow_signals(cache, source="unit")

    sentiment = next(
        item for item in out["signals"] if item["type"] == "market_sentiment"
    )
    assert sentiment == {
        "type": "market_sentiment",
        "signal": "fear",
        "value": 25,
        "confidence": 0.5,
        "sources": ["cboe", "fred"],
        "severity": "info",
    }
    assert out["can_change_trade_policy"] is False
    assert out["can_trigger_order"] is False


def test_shadow_signals_ignore_polluted_sentiment_permissions():
    from quant.research.shadow_signals import build_shadow_signals

    cache = FakeCache(
        {
            "global:context:latest": {
                "sentiment": {
                    "sentiment_score": 90,
                    "sentiment_regime": "extreme_greed",
                    "confidence": 1.0,
                    "can_change_trade_policy": True,
                    "can_trigger_order": True,
                    "sources": [{"source": "cboe", "status": "live"}],
                }
            }
        }
    )

    out = build_shadow_signals(cache, source="unit")

    assert out["can_change_trade_policy"] is False
    assert out["can_trigger_order"] is False
    assert all("can_change_trade_policy" not in item for item in out["signals"])
    assert all("can_trigger_order" not in item for item in out["signals"])


def test_shadow_signals_tolerate_missing_sentiment():
    from quant.research.shadow_signals import build_shadow_signals

    out = build_shadow_signals(
        FakeCache({"global:context:latest": {"risk_signals": ["legacy signal"]}}),
        source="unit",
    )

    assert {
        "type": "macro_market",
        "signal": "legacy signal",
        "severity": "info",
    } in out["signals"]
    assert not any(item["type"] == "market_sentiment" for item in out["signals"])
    assert out["can_change_trade_policy"] is False
    assert out["can_trigger_order"] is False


@pytest.mark.parametrize(
    "global_ctx",
    [
        [],
        "bad-context",
        True,
    ],
)
def test_shadow_signals_tolerate_non_dict_global_context(global_ctx):
    from quant.research.shadow_signals import build_shadow_signals

    out = build_shadow_signals(
        FakeCache({"global:context:latest": global_ctx}),
        source="unit",
    )

    assert out["signals"] == []
    assert out["can_change_trade_policy"] is False
    assert out["can_trigger_order"] is False


@pytest.mark.parametrize(
    "sentiment",
    [
        [],
        "fear",
        True,
    ],
)
def test_shadow_signals_skip_non_dict_sentiment(sentiment):
    from quant.research.shadow_signals import build_shadow_signals

    out = build_shadow_signals(
        FakeCache({"global:context:latest": {"sentiment": sentiment}}),
        source="unit",
    )

    assert not any(item["type"] == "market_sentiment" for item in out["signals"])


@pytest.mark.parametrize(
    ("score", "confidence", "expected_score", "expected_confidence"),
    [
        (float("nan"), float("inf"), 50.0, 0.0),
        (float("-inf"), float("nan"), 50.0, 0.0),
        (True, False, 50.0, 0.0),
        (-10, -2, 0.0, 0.0),
        (120, 3, 100.0, 1.0),
    ],
)
def test_shadow_signals_sanitize_numeric_sentiment(
    score,
    confidence,
    expected_score,
    expected_confidence,
):
    from quant.research.shadow_signals import build_shadow_signals

    out = build_shadow_signals(
        FakeCache(
            {
                "global:context:latest": {
                    "sentiment": {
                        "sentiment_score": score,
                        "sentiment_regime": ["invalid"],
                        "confidence": confidence,
                        "sources": [
                            {"source": "cboe", "status": "live"},
                            {"source": "fred", "status": "stale"},
                            {"source": "cffex", "status": "unavailable"},
                            {"source": "bad", "status": ["live"]},
                            {"source": [], "status": "live"},
                            [],
                        ],
                        "can_change_trade_policy": True,
                        "can_trigger_order": True,
                    }
                }
            }
        ),
        source="unit",
    )

    sentiment = next(
        item for item in out["signals"] if item["type"] == "market_sentiment"
    )
    assert sentiment["value"] == expected_score
    assert sentiment["confidence"] == expected_confidence
    assert sentiment["sources"] == ["cboe", "fred"]
    if expected_score == 0.0:
        assert sentiment["signal"] == "extreme_fear"
    elif expected_score == 100.0:
        assert sentiment["signal"] == "extreme_greed"
    else:
        assert sentiment["signal"] == "neutral"
    assert out["can_change_trade_policy"] is False
    assert out["can_trigger_order"] is False

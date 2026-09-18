from datetime import datetime, timedelta

from scripts import global_context
from scripts.global_context import assess_context_freshness


def test_fresh_macro_context_keeps_current_risk_assessment():
    now = datetime(2026, 8, 4, 10, 0, 0)
    result = assess_context_freshness(
        {
            "collected_at": (now - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S"),
            "risk_level": "high",
            "trade_policy": "no_new_position",
            "risk_signals": ["原油波动"],
        },
        now=now,
        ttl_sec=1800,
    )
    assert result["freshness"]["state"] == "fresh"
    assert result["risk_level"] == "high"
    assert result["risk_signals"] == ["原油波动"]


def test_expired_macro_context_does_not_keep_a_high_risk_label():
    now = datetime(2026, 8, 4, 10, 0, 0)
    result = assess_context_freshness(
        {
            "collected_at": (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
            "risk_level": "high",
            "trade_policy": "no_new_position",
            "risk_signals": ["原油波动"],
        },
        now=now,
        ttl_sec=1800,
    )
    assert result["freshness"]["state"] == "stale"
    assert result["freshness"]["reason"] == "macro_context_expired"
    assert result["risk_level"] == "unknown"
    assert result["trade_policy"] == "no_new_position"
    assert result["risk_signals"] == []
    assert result["raw_risk_level"] == "high"


def test_missing_macro_timestamp_fails_closed_without_claiming_high_risk():
    result = assess_context_freshness(
        {"risk_level": "high", "trade_policy": "normal"},
        now=datetime(2026, 8, 4, 10, 0, 0),
        ttl_sec=1800,
    )
    assert result["freshness"]["reason"] == "macro_context_timestamp_missing"
    assert result["risk_level"] == "unknown"
    assert result["trade_policy"] == "no_new_position"


class _Cache:
    def __init__(self, latest):
        self.latest = latest

    def get(self, key):
        assert key == "global:context:latest"
        return self.latest


def test_refresh_if_due_uses_recent_cache_without_collecting(monkeypatch):
    now = datetime(2026, 8, 4, 10, 0, 0)
    monkeypatch.setattr(global_context, "cache", _Cache({
        "collected_at": "2026-08-04 09:58:00",
        "risk_level": "low",
        "trade_policy": "normal",
        "risk_signals": [],
    }))
    monkeypatch.setattr(
        global_context,
        "collect_global_context",
        lambda: (_ for _ in ()).throw(AssertionError("recent context must be reused")),
    )

    result = global_context.refresh_global_context_if_due(
        now=now,
        refresh_interval_sec=300,
    )

    assert result["status"] == "cached"
    assert result["fresh"] is True
    assert result["age_seconds"] == 120


def test_refresh_if_due_collects_when_cache_is_old(monkeypatch):
    now = datetime(2026, 8, 4, 10, 0, 0)
    monkeypatch.setattr(global_context, "cache", _Cache({
        "collected_at": "2026-08-04 09:40:00",
        "risk_level": "high",
        "trade_policy": "no_new_position",
        "risk_signals": ["old"],
    }))
    calls = []
    monkeypatch.setattr(
        global_context,
        "collect_global_context",
        lambda: calls.append(True) or {
            "collected_at": "2026-08-04 10:00:00",
            "risk_level": "low",
            "trade_policy": "normal",
            "risk_signals": [],
        },
    )

    result = global_context.refresh_global_context_if_due(
        now=now,
        refresh_interval_sec=300,
    )

    assert calls == [True]
    assert result["status"] == "refreshed"
    assert result["fresh"] is True
    assert result["risk_level"] == "low"

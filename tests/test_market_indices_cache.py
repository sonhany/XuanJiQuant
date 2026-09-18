from scripts import global_context, market_data


class FakeCache:
    def __init__(self, value):
        self.value = value

    def get(self, key):
        assert key == "global:context:latest"
        return self.value


def test_fetch_indices_reads_maintained_snapshot_without_network(monkeypatch):
    snapshot = {
        "collected_at": "2026-08-05 16:30:00",
        "risk_level": "medium",
        "trade_policy": "reduce_only",
        "global_indices": {"美股": [{"name": "纳斯达克100"}]},
    }
    monkeypatch.setattr(market_data, "_cache", lambda: FakeCache(snapshot))
    monkeypatch.setattr(
        global_context,
        "collect_global_context",
        lambda: (_ for _ in ()).throw(AssertionError("unexpected network refresh")),
    )

    result = market_data.fetch_indices(
        now=global_context._context_timestamp("2026-08-05 16:31:00")
    )

    assert result["risk_level"] == "medium"
    assert result["freshness"]["state"] == "fresh"


def test_fetch_indices_allows_explicit_refresh(monkeypatch):
    refreshed = {
        "collected_at": "2026-08-05 16:31:00",
        "risk_level": "low",
        "trade_policy": "normal",
    }
    monkeypatch.setattr(
        global_context,
        "collect_global_context",
        lambda: refreshed,
    )

    assert market_data.fetch_indices(force_refresh=True) == refreshed

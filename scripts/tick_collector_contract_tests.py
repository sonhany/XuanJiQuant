from __future__ import annotations

from datetime import datetime


def test_order_book_store_skips_unchanged_snapshots(tmp_path):
    from quant.data.cache import SqliteCache
    from quant.data.order_book_store import latest_order_book, store_order_book_snapshot

    cache = SqliteCache(db_path=str(tmp_path / "ticks.db"))
    book = {
        "code": "600519",
        "bids": [{"level": 1, "price": 9.99, "volume": 10000}],
        "asks": [{"level": 1, "price": 10.01, "volume": 15000}],
        "source": "tdx_quant_snapshot",
    }

    first = store_order_book_snapshot(cache, "600519", book)
    second = store_order_book_snapshot(cache, "600519", book)
    latest = latest_order_book(cache, "600519")

    assert first["stored"] == 1
    assert second["stored"] == 0
    assert second["reason"] == "unchanged"
    assert latest["best_bid"] == 9.99
    assert latest["best_ask"] == 10.01


def test_tick_collector_targets_positions_watchlist_and_pending_orders(tmp_path, monkeypatch):
    from quant.data.cache import SqliteCache
    import scripts.tick_collector as collector
    from scripts.data_freshness import get_expected_date

    cache = SqliteCache(db_path=str(tmp_path / "ticks.db"))
    monkeypatch.setattr(collector, "cache", cache)
    monkeypatch.setattr(collector, "load_active_account_projection", lambda: {
        "positions": [{"code": "600519", "quantity": 100}],
        "orders": [
            {"code": "000001", "status": "pending"},
            {"code": "000002", "status": "filled"},
        ],
    })
    cache.set("watchlist:default", ["300750", "000001"])
    cache.set("ai:screen:candidate_pool", ["600999"])
    cache.set("ai:screen:latest", {
        "success": True,
        "screened_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "latest_date": get_expected_date(),
        "top": [{"code": "002594"}, {"code": "600519"}],
    })
    cache.set("ai:execution:latest", {"proposed_orders": [{"code": "601318", "action": "buy"}]})

    targets = collector.target_codes(max_codes=20)

    assert targets == ["600519", "300750", "000001"]


def test_tick_collector_does_not_follow_stale_screen_candidates(tmp_path, monkeypatch):
    from quant.data.cache import SqliteCache
    import scripts.tick_collector as collector

    cache = SqliteCache(db_path=str(tmp_path / "ticks.db"))
    monkeypatch.setattr(collector, "cache", cache)
    monkeypatch.setattr(
        collector,
        "load_active_account_projection",
        lambda: {"positions": [], "orders": []},
    )
    cache.set("ai:screen:candidate_pool", ["600817"])
    cache.set("ai:screen:latest", {
        "success": True,
        "screened_at": "2026-08-03 17:44:43",
        "latest_date": "20260803",
        "top": [{"code": "600817"}],
    })

    assert collector.target_codes(max_codes=20) == []

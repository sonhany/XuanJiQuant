from datetime import datetime

from quant.data.cache import MemoryCache
from quant.data.snapshot import DataSnapshot, publish_snapshot, read_latest_passed_snapshot


def _snapshot(*, snapshot_id: str, quality_status: str = "passed") -> DataSnapshot:
    return DataSnapshot(
        snapshot_id=snapshot_id,
        dataset="a_share_daily",
        as_of="2026-08-12",
        published_at="2026-08-13T15:00:00+08:00",
        universe_version="universe-20260813",
        expected_count=5203,
        available_count=5201,
        source_chain=("tdx_quant", "tencent_cross_check"),
        content_hash="a" * 64,
        quality_status=quality_status,
        freshness_status="fresh" if quality_status == "passed" else "stale",
        failure_reasons=() if quality_status == "passed" else ("coverage_below_gate",),
    )


def test_snapshot_contract_calculates_coverage_and_never_grants_execution():
    snapshot = _snapshot(snapshot_id="daily-20260812-v1")

    payload = snapshot.to_dict()

    assert payload["coverage"] == 5201 / 5203
    assert payload["execution_authority"] is False
    assert payload["source_chain"] == ["tdx_quant", "tencent_cross_check"]


def test_failed_publication_does_not_replace_latest_passed_snapshot():
    cache = MemoryCache()
    passed = _snapshot(snapshot_id="daily-passed")
    failed = _snapshot(snapshot_id="daily-failed", quality_status="failed")

    publish_snapshot(cache, passed)
    publish_snapshot(cache, failed)

    assert read_latest_passed_snapshot(cache, "a_share_daily")["snapshot_id"] == "daily-passed"
    assert cache.get("data:snapshot:a_share_daily:latest_attempt")["snapshot_id"] == "daily-failed"


def test_snapshot_rejects_inconsistent_or_invalid_fields():
    try:
        DataSnapshot(
            snapshot_id="bad",
            dataset="a_share_daily",
            as_of="2026-08-12",
            published_at=datetime.now().isoformat(),
            universe_version="u",
            expected_count=1,
            available_count=2,
            source_chain=(),
            content_hash="a" * 64,
            quality_status="passed",
            freshness_status="fresh",
        )
    except ValueError as exc:
        assert "available_count" in str(exc)
    else:
        raise AssertionError("invalid snapshot must be rejected")


def test_daily_update_publishes_a_versioned_daily_snapshot(monkeypatch):
    from scripts import daily_update

    cache = MemoryCache()
    cache.set("kline:600519:d", [{"date": "20260812"}])
    cache.set("kline:000001:d", [{"date": "20260812"}])
    monkeypatch.setattr(daily_update, "create_cache", lambda: cache)
    monkeypatch.setattr(daily_update, "sync_universe", lambda force=False: ["600519", "000001"])
    monkeypatch.setattr(daily_update, "_expected_kline_date", lambda: "20260812")
    monkeypatch.setattr(
        daily_update,
        "incremental_klines",
        lambda codes, passed_cache, **kwargs: {
            "ok": 1,
            "skip": 1,
            "err": 0,
            "new_bars": 1,
            "remote_fetches": 1,
            "sources": ["tdx_quant", "tencent_cross_check"],
        },
    )

    result = daily_update.run_daily_update(workers=1)

    snapshot = result["data_snapshot"]
    assert snapshot["dataset"] == "a_share_daily"
    assert snapshot["as_of"] == "2026-08-12"
    assert snapshot["quality_status"] == "passed"
    assert snapshot["expected_count"] == 2
    assert snapshot["available_count"] == 2
    assert snapshot["execution_authority"] is False


def test_daily_update_allows_coverage_pass_with_nonfatal_fetch_warning(monkeypatch):
    from scripts import daily_update

    cache = MemoryCache()
    codes = ["600519", "000001", "300001"]
    for code in codes:
        cache.set(f"kline:{code}:d", [{"date": "20260813"}])
    monkeypatch.setattr(daily_update, "create_cache", lambda: cache)
    monkeypatch.setattr(daily_update, "sync_universe", lambda force=False: codes)
    monkeypatch.setattr(daily_update, "_expected_kline_date", lambda: "20260813")
    monkeypatch.setenv("FULL_MARKET_KLINE_MIN_COVERAGE", "0.95")
    monkeypatch.setattr(
        daily_update,
        "incremental_klines",
        lambda *_args, **_kwargs: {
            "ok": 2,
            "skip": 0,
            "err": 1,
            "new_bars": 2,
            "sources": ["tdx_quant", "tencent_cross_check"],
        },
    )

    snapshot = daily_update.run_daily_update(workers=1)["data_snapshot"]

    assert snapshot["quality_status"] == "passed"
    assert snapshot["freshness_status"] == "fresh"
    assert snapshot["warnings"] == ["nonfatal_fetch_errors:1"]
    assert cache.get("data:snapshot:a_share_daily:latest_passed")["snapshot_id"] == snapshot["snapshot_id"]


def test_financial_only_cli_actually_enables_financial_refresh(monkeypatch):
    from scripts import daily_update

    captured = {}
    monkeypatch.setattr(
        daily_update,
        "run_daily_update",
        lambda **kwargs: captured.update(kwargs) or {"financial": {"ok": 1}},
    )
    monkeypatch.setattr(daily_update, "create_cache", lambda: object())
    monkeypatch.setattr(daily_update, "_kline_key_count", lambda _cache: 0)
    monkeypatch.setattr("sys.argv", ["daily_update.py", "--financial-only"])

    daily_update.main()

    assert captured["financial"] is True
    assert captured["financial_only"] is True


def test_incremental_update_never_persists_bars_after_authoritative_expected_date(monkeypatch):
    from scripts import daily_update

    cache = MemoryCache()
    cache.set("kline:600519:d", [{"date": "20260812", "close": 10}])
    monkeypatch.setattr(
        daily_update,
        "_fetch_incremental_remote",
        lambda *_args, **_kwargs: {
            "bars": [
                {"date": "20260813", "close": 11},
                {"date": "20260814", "close": 12},
            ],
            "source": "test",
        },
    )

    daily_update.incremental_klines(
        ["600519"],
        cache,
        expected_date="20260813",
        workers=1,
    )

    assert [bar["date"] for bar in cache.get("kline:600519:d")] == [
        "20260812",
        "20260813",
    ]


def test_incremental_update_removes_preexisting_future_partial_bar():
    from scripts import daily_update

    cache = MemoryCache()
    cache.set(
        "kline:600519:d",
        [
            {"date": "20260812", "close": 10},
            {"date": "20260813", "close": 11},
            {"date": "20260814", "close": 12},
        ],
    )

    result = daily_update.incremental_klines(
        ["600519"],
        cache,
        expected_date="20260813",
        workers=1,
    )

    assert result["skip"] == 1
    assert [bar["date"] for bar in cache.get("kline:600519:d")] == [
        "20260812",
        "20260813",
    ]

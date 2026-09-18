from __future__ import annotations

from quant.data.cache import SqliteCache
from quant.data.sync_policy import REQUIRED_DATASETS
from quant.data.sync_catalog import build_sync_catalog


def test_sync_catalog_exposes_every_policy_with_truth_fields(tmp_path):
    cache = SqliteCache(db_path=str(tmp_path / "catalog.db"))
    catalog = build_sync_catalog(cache)

    assert catalog["schema_version"] == "xuanji-sync-catalog-v1"
    assert {row["dataset"] for row in catalog["items"]} == set(REQUIRED_DATASETS)
    for row in catalog["items"]:
        assert {
            "dataset", "owner", "authority", "fact_boundary", "active_interval_ms",
            "background_interval_ms", "stale_after_ms", "fact_as_of", "last_success",
            "coverage", "state", "reason", "execution_authority",
        }.issubset(row)
        assert row["execution_authority"] is False


def test_sync_catalog_reads_hot_snapshot_fact_time_without_marking_old_data_live(tmp_path):
    cache = SqliteCache(db_path=str(tmp_path / "hot.db"))
    cache.set("market:hot:snapshot:latest", {
        "snapshot_id": "snap-1",
        "quote_timestamp": "20260901093501",
        "received_at": "2026-09-01T09:35:02+08:00",
        "requested": 10,
        "observed": 9,
        "stale": True,
    })

    item = next(row for row in build_sync_catalog(cache)["items"] if row["dataset"] == "hot_quotes")

    assert item["fact_as_of"] == "20260901093501"
    assert item["coverage"] == 0.9
    assert item["state"] == "stale"
    assert item["reason"] == "source_snapshot_stale"

from __future__ import annotations

import json

import pytest

from quant.data.sync_policy import (
    REQUIRED_DATASETS,
    load_sync_policy,
    policy_snapshot,
)


def test_policy_contains_every_governed_data_domain():
    policies = load_sync_policy()

    assert set(policies) == set(REQUIRED_DATASETS)
    assert policies["hot_quotes"].active_interval_ms == 1_000
    assert policies["hot_quotes"].stale_after_ms == 5_000
    assert policies["market_top100"].active_interval_ms == 8_000
    assert policies["cockpit_risk"].active_interval_ms == 2_000
    assert policies["jin10_flash"].active_interval_ms == 30_000
    assert policies["cninfo_latest"].active_interval_ms == 60_000
    assert policies["factor_research"].fact_boundary == "complete_daily_generation"
    assert policies["qlib_research"].fact_boundary == "weekly_monthly_quarterly_schedule"


def test_policy_snapshot_is_json_safe_and_preserves_authority():
    snapshot = policy_snapshot()

    assert snapshot["schema_version"] == "xuanji-data-sync-policy-v1"
    assert snapshot["datasets"]["cockpit_account"]["authority"] == "f5_ledger"
    assert snapshot["datasets"]["cockpit_account"]["execution_authority"] is False
    json.dumps(snapshot, ensure_ascii=False)


def test_policy_rejects_active_interval_below_hard_floor(tmp_path):
    source = policy_snapshot()
    source["datasets"]["hot_quotes"]["active_interval_ms"] = 100
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(source), encoding="utf-8")

    with pytest.raises(ValueError, match="hard floor"):
        load_sync_policy(path)


def test_policy_rejects_missing_domain_and_nonpositive_cadence(tmp_path):
    missing = policy_snapshot()
    missing["datasets"].pop("system_health")
    missing_path = tmp_path / "missing.json"
    missing_path.write_text(json.dumps(missing), encoding="utf-8")
    with pytest.raises(ValueError, match="missing datasets"):
        load_sync_policy(missing_path)

    invalid = policy_snapshot()
    invalid["datasets"]["alerts"]["background_interval_ms"] = 0
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(ValueError, match="positive"):
        load_sync_policy(invalid_path)

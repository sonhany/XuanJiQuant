from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import threading

import pytest

from quant.adaptive.health import (
    compute_approval_evidence_sha256,
    evaluate_health_state,
    model_health_approval_key,
    model_health_approval_consumed_key,
    model_health_history_key,
    model_health_key,
    normalize_approval_ref,
    normalize_model_id,
    runtime_eligible,
    validate_health_record,
)
from quant.data.cache import MemoryCache, SqliteCache
from scripts.adaptive_health import publish_model_health


class FakeCache:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.written_keys = []
        self._lock = threading.RLock()

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, ttl=None):
        self.values[key] = value
        self.written_keys.append(key)

    def atomic_update(self, keys, updater):
        with self._lock:
            snapshot = {key: deepcopy(self.values.get(key)) for key in keys}
            writes = updater(snapshot)
            if not isinstance(writes, dict) or any(key not in keys for key in writes):
                raise ValueError("invalid atomic writes")
            prepared = deepcopy(writes)
            self.values.update(prepared)
            self.written_keys.extend(prepared)
            return deepcopy(prepared)


ARTIFACT_SHA256 = "a" * 64


def approval_record(
    model_id="model-a",
    approval_ref="review-42",
    artifact_sha256=ARTIFACT_SHA256,
    **overrides,
):
    now = datetime.now(timezone.utc)
    record = {
        "approval_ref": approval_ref,
        "model_id": model_id,
        "artifact_sha256": artifact_sha256,
        "validation_run_id": "validation-20260720",
        "approver_id": "reviewer@example.com",
        "approved_at": (now - timedelta(minutes=5)).isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "retrained": True,
        "validation_passed": True,
        "human_approved": True,
    }
    record["evidence_sha256"] = compute_approval_evidence_sha256(record)
    record.update(overrides)
    return record


@pytest.mark.parametrize(
    "value",
    [
        " model-a",
        "model-a ",
        "model a",
        "model:a",
        "model/a",
        "model\\a",
        "_model",
        "latest",
        "HISTORY",
        "Approval",
        "a" * 97,
        "模型",
        "",
        None,
    ],
)
def test_model_ids_reject_noncanonical_or_reserved_values(value):
    with pytest.raises(ValueError, match="model_id"):
        normalize_model_id(value)


def test_canonical_ids_and_health_keys_are_consistent():
    assert normalize_model_id("Model_1.v2-beta") == "Model_1.v2-beta"
    assert normalize_approval_ref("review_2026.07-42") == "review_2026.07-42"
    assert model_health_key("Model_1") == "adaptive:model_health:Model_1"
    assert model_health_history_key("Model_1") == "adaptive:model_health:history:Model_1"
    assert model_health_approval_key("review-42") == "adaptive:model_health:approval:review-42"
    assert model_health_approval_consumed_key("review-42") == "adaptive:model_health:approval_consumed:review-42"


@pytest.mark.parametrize("value", [" review", "review ", "latest", "x/y", "x:y", "a" * 129])
def test_approval_refs_require_canonical_safe_tokens(value):
    with pytest.raises(ValueError, match="approval_ref"):
        normalize_approval_ref(value)


@pytest.mark.parametrize(
    "record",
    [
        "invalid",
        {"health_state": "invalid", "artifact_valid": True, "data_fresh": True},
        {"health_state": "healthy", "data_fresh": True},
        {"health_state": "healthy", "artifact_valid": True},
        {"health_state": "healthy", "artifact_valid": 1, "data_fresh": True},
    ],
)
def test_existing_health_records_require_complete_exact_gates(record):
    with pytest.raises(ValueError, match="health record"):
        validate_health_record(record)


def test_missing_health_record_has_explicit_legacy_compatibility_defaults():
    assert validate_health_record(None, allow_missing=True) == {
        "health_state": "watch",
        "artifact_valid": True,
        "data_fresh": True,
    }
    with pytest.raises(ValueError, match="health record"):
        validate_health_record(None)


def test_single_failure_moves_to_watch_only():
    out = evaluate_health_state(
        previous="healthy",
        recent_windows=[{"hard_failure": False, "drift_failed": True}],
        failure_windows=3,
    )
    assert out["health_state"] == "watch"


def test_three_failures_quarantine_model():
    rows = [{"hard_failure": False, "drift_failed": True}] * 3
    out = evaluate_health_state(
        previous="degraded", recent_windows=rows, failure_windows=3
    )
    assert out["health_state"] == "quarantined"
    assert runtime_eligible("approved", out["health_state"]) is False


def test_hard_data_failure_quarantines_immediately():
    out = evaluate_health_state(
        previous="healthy",
        recent_windows=[{"hard_failure": True, "drift_failed": False}],
        failure_windows=3,
    )
    assert out["health_state"] == "quarantined"


def test_hard_failure_quarantines_even_when_other_window_fields_are_malformed():
    out = evaluate_health_state(
        previous="healthy",
        recent_windows=[{"hard_failure": True}],
        failure_windows=3,
    )

    assert out["health_state"] == "quarantined"


def test_failure_threshold_degrades_a_non_degraded_model():
    out = evaluate_health_state(
        previous="watch",
        recent_windows=[{"hard_failure": False, "drift_failed": True}] * 2,
        failure_windows=2,
    )

    assert out == {
        "health_state": "degraded",
        "reason": "drift_failure_threshold_reached",
        "trailing_failure_streak": 2,
        "failure_windows": 2,
        "revalidation_accepted": False,
    }


def test_health_recovery_requires_explicit_healthy_windows():
    healthy = {"hard_failure": False, "drift_failed": False}

    assert evaluate_health_state("degraded", [healthy], 3)["health_state"] == "watch"
    assert evaluate_health_state("watch", [healthy], 3)["health_state"] == "watch"
    assert evaluate_health_state("watch", [healthy, healthy], 3)["health_state"] == "healthy"
    assert evaluate_health_state("quarantined", [healthy, healthy], 3)["health_state"] == "quarantined"


def test_degraded_does_not_recover_without_explicit_healthy_evidence():
    out = evaluate_health_state("degraded", [], 3)

    assert out["health_state"] == "degraded"


def test_incomplete_revalidation_keeps_model_quarantined():
    healthy = {"hard_failure": False, "drift_failed": False}

    out = evaluate_health_state(
        "quarantined",
        [healthy, healthy],
        3,
        revalidation_verified=False,
    )

    assert out["health_state"] == "quarantined"
    assert out["reason"] == "manual_revalidation_required"
    assert out["revalidation_accepted"] is False


def test_complete_revalidation_recovers_quarantine_to_watch_only():
    healthy = {"hard_failure": False, "drift_failed": False}

    out = evaluate_health_state(
        "quarantined",
        [healthy, healthy, healthy],
        3,
        revalidation_verified=True,
    )

    assert out["health_state"] == "watch"
    assert out["health_state"] != "healthy"
    assert out["reason"] == "manual_revalidation_accepted"
    assert out["revalidation_accepted"] is True


@pytest.mark.parametrize(
    "failure",
    [
        {"hard_failure": True, "drift_failed": False},
        {"hard_failure": False, "drift_failed": True},
    ],
)
def test_failure_wins_over_complete_revalidation(failure):
    healthy = {"hard_failure": False, "drift_failed": False}

    out = evaluate_health_state(
        "quarantined",
        [healthy, healthy, failure],
        3,
        revalidation_verified=True,
    )

    assert out["health_state"] == "quarantined"
    assert out["revalidation_accepted"] is False


def test_prior_hard_failure_blocks_revalidation_despite_healthy_tail():
    healthy = {"hard_failure": False, "drift_failed": False}

    out = evaluate_health_state(
        "quarantined",
        [{"hard_failure": True, "drift_failed": False}, healthy, healthy],
        3,
        revalidation_verified=True,
    )

    assert out["health_state"] == "quarantined"
    assert out["revalidation_accepted"] is False


@pytest.mark.parametrize("failure_windows", [None, "bad", True, 0, -2])
def test_failure_window_threshold_is_normalized_safely(failure_windows):
    out = evaluate_health_state(
        "healthy",
        [{"hard_failure": False, "drift_failed": True}],
        failure_windows,
    )

    expected = 1 if isinstance(failure_windows, int) and not isinstance(failure_windows, bool) else 3
    assert out["failure_windows"] == expected


def test_invalid_previous_state_fails_closed_to_quarantine():
    healthy = {"hard_failure": False, "drift_failed": False}

    out = evaluate_health_state("unknown", [healthy, healthy], 3)

    assert out["health_state"] == "quarantined"
    assert out["reason"] == "invalid_previous_state"


@pytest.mark.parametrize(
    ("promotion_state", "health_state", "artifact_valid", "data_fresh", "expected"),
    [
        ("approved", "healthy", True, True, True),
        ("paper_active", "watch", True, True, True),
        ("candidate", "healthy", True, True, False),
        ("approved", "quarantined", True, True, False),
        ("approved", "healthy", False, True, False),
        ("approved", "healthy", True, False, False),
        ("approved", "invalid", True, True, False),
    ],
)
def test_runtime_eligibility_requires_all_gates(
    promotion_state, health_state, artifact_valid, data_fresh, expected
):
    assert runtime_eligible(
        promotion_state,
        health_state,
        artifact_valid=artifact_valid,
        data_fresh=data_fresh,
    ) is expected


def test_publisher_writes_bounded_health_records_and_aggregate_summary():
    cache = FakeCache(
        {
            "adaptive:model_health:history:model-a": [
                {"model_id": "model-a", "sequence": i} for i in range(40)
            ]
        }
    )
    windows = [
        {"hard_failure": False, "drift_failed": False, "sequence": i}
        for i in range(35)
    ]

    out = publish_model_health(cache, "model-a", "approved", windows)

    assert out["model_id"] == "model-a"
    assert out["promotion_state"] == "approved"
    assert out["health_state"] == "healthy"
    assert out["runtime_eligible"] is True
    assert len(out["recent_windows"]) == 30
    assert out["recent_windows"][0]["sequence"] == 5
    assert datetime.fromisoformat(out["updated_at"]).utcoffset() is not None
    assert cache.get("adaptive:model_health:model-a") == out
    history = cache.get("adaptive:model_health:history:model-a")
    assert len(history) == 30
    assert history[-1] == out
    latest = cache.get("adaptive:model_health:latest")
    assert latest["models"]["model-a"] == out
    assert latest["summary"] == {
        "total": 1,
        "healthy": 1,
        "watch": 0,
        "degraded": 0,
        "quarantined": 0,
        "runtime_eligible": 1,
    }


@pytest.mark.parametrize(
    ("artifact_valid", "data_fresh", "expected_reason"),
    [
        (False, True, "artifact_invalid"),
        (True, False, "data_stale"),
        (False, False, "artifact_invalid_and_data_stale"),
    ],
)
def test_publisher_quarantines_hard_artifact_or_data_failures(
    artifact_valid, data_fresh, expected_reason
):
    cache = FakeCache()

    out = publish_model_health(
        cache,
        "model-a",
        "approved",
        [],
        artifact_valid=artifact_valid,
        data_fresh=data_fresh,
    )

    assert out["health_state"] == "quarantined"
    assert out["runtime_eligible"] is False
    assert out["reason"] == expected_reason
    assert out["recent_windows"][-1]["hard_failure"] is True


def test_publisher_only_writes_model_health_keys():
    cache = FakeCache()

    publish_model_health(cache, "model-a", "approved", [])

    assert set(cache.written_keys) == {
        "adaptive:model_health:model-a",
        "adaptive:model_health:history:model-a",
        "adaptive:model_health:latest",
    }
    assert all(key.startswith("adaptive:model_health:") for key in cache.written_keys)


def test_publisher_rejects_empty_model_id_without_writes():
    cache = FakeCache()

    with pytest.raises(ValueError, match="model_id"):
        publish_model_health(cache, "  ", "approved", [])

    assert cache.written_keys == []


def test_publisher_rejects_reserved_model_id_without_writes():
    cache = FakeCache()

    with pytest.raises(ValueError, match="model_id"):
        publish_model_health(cache, "latest", "approved", [])

    assert cache.written_keys == []


def test_publisher_malformed_windows_fail_closed():
    cache = FakeCache()

    out = publish_model_health(cache, "model-a", "approved", "invalid")

    assert out["health_state"] == "quarantined"
    assert out["runtime_eligible"] is False
    assert out["reason"] == "invalid_recent_windows"


def test_publisher_any_malformed_window_prevents_later_healthy_recovery():
    cache = FakeCache()
    healthy = {"hard_failure": False, "drift_failed": False}

    out = publish_model_health(
        cache,
        "model-a",
        "approved",
        [{"hard_failure": "no", "drift_failed": False}, healthy, healthy],
    )

    assert out["health_state"] == "quarantined"
    assert out["runtime_eligible"] is False
    assert out["reason"] == "invalid_recent_windows"


def test_approval_evidence_hash_is_canonical_and_ignores_consumption_fields():
    record = approval_record()
    reordered = dict(reversed(list(record.items())))
    reordered["consumed_at"] = "later"
    reordered["consumed_by_model_id"] = "model-a"

    assert compute_approval_evidence_sha256(record) == compute_approval_evidence_sha256(reordered)


def test_publisher_consumes_and_persists_sanitized_approval_evidence():
    approval = approval_record()
    cache = MemoryCache(default_ttl=None)
    cache.set("adaptive:model_health:model-a", {
        "health_state": "quarantined",
        "artifact_valid": True,
        "data_fresh": True,
    })
    cache.create_immutable(model_health_approval_key("review-42"), approval)
    healthy = {"hard_failure": False, "drift_failed": False}

    out = publish_model_health(
        cache,
        "model-a",
        "approved",
        [healthy, healthy],
        artifact_sha256=ARTIFACT_SHA256,
        revalidation={"approval_ref": "review-42", "human_approved": False},
    )

    expected_evidence = {
        "approval_ref": "review-42",
        "artifact_sha256": ARTIFACT_SHA256,
        "validation_run_id": approval["validation_run_id"],
        "approver_id": approval["approver_id"],
        "approved_at": approval["approved_at"],
        "expires_at": approval["expires_at"],
        "evidence_sha256": approval["evidence_sha256"],
    }
    assert out["health_state"] == "watch"
    assert out["runtime_eligible"] is True
    assert out["revalidation_accepted"] is True
    assert out["reason"] == "manual_revalidation_accepted"
    assert out["revalidation"] == expected_evidence
    assert cache.get("adaptive:model_health:model-a")["revalidation"] == expected_evidence
    assert cache.get("adaptive:model_health:history:model-a")[-1]["revalidation"] == expected_evidence
    assert cache.get("adaptive:model_health:latest")["models"]["model-a"]["revalidation"] == expected_evidence
    assert cache.get(model_health_approval_key("review-42")) == approval
    consumed = cache.get(model_health_approval_consumed_key("review-42"))
    assert consumed["evidence_sha256"] == approval["evidence_sha256"]
    assert consumed["model_id"] == "model-a"
    assert datetime.fromisoformat(consumed["consumed_at"]).utcoffset() is not None
    assert "human_approved" not in out["revalidation"]


@pytest.mark.parametrize(
    ("artifact_valid", "data_fresh"),
    [(False, True), (True, False)],
)
def test_publisher_validity_failure_blocks_complete_revalidation(
    artifact_valid, data_fresh
):
    approval = approval_record()
    cache = MemoryCache(default_ttl=None)
    cache.set("adaptive:model_health:model-a", {
        "health_state": "quarantined",
        "artifact_valid": True,
        "data_fresh": True,
    })
    cache.create_immutable(model_health_approval_key("review-42"), approval)
    healthy = {"hard_failure": False, "drift_failed": False}

    out = publish_model_health(
        cache,
        "model-a",
        "approved",
        [healthy, healthy],
        artifact_valid=artifact_valid,
        data_fresh=data_fresh,
        artifact_sha256=ARTIFACT_SHA256,
        revalidation={"approval_ref": "review-42"},
    )

    assert out["health_state"] == "quarantined"
    assert out["runtime_eligible"] is False
    assert out["revalidation_accepted"] is False
    assert cache.get(model_health_approval_consumed_key("review-42")) is None


@pytest.mark.parametrize(
    "persisted",
    [
        "invalid",
        {"health_state": "invalid", "artifact_valid": True, "data_fresh": True},
        {"health_state": "healthy"},
    ],
)
def test_publisher_malformed_persisted_health_quarantines(persisted):
    cache = FakeCache({model_health_key("model-a"): persisted})

    out = publish_model_health(cache, "model-a", "approved", [])

    assert out["health_state"] == "quarantined"
    assert out["runtime_eligible"] is False
    assert out["reason"] == "invalid_persisted_health"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda record: None,
        lambda record: "invalid",
        lambda record: {**record, "approval_ref": "other-review"},
        lambda record: {**record, "model_id": "model-b"},
        lambda record: {**record, "artifact_sha256": "b" * 64},
        lambda record: {**record, "validation_run_id": "invalid run"},
        lambda record: {**record, "approver_id": "  "},
        lambda record: {**record, "expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()},
        lambda record: {**record, "approved_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()},
        lambda record: {**record, "approved_at": datetime.now().isoformat()},
        lambda record: {**record, "retrained": False},
        lambda record: {**record, "evidence_sha256": "0" * 64},
        lambda record: {key: value for key, value in record.items() if key != "evidence_sha256"},
    ],
)
def test_invalid_approval_evidence_cannot_release_quarantine(mutation):
    approval = mutation(approval_record())
    approval_key = model_health_approval_key("review-42")
    cache = MemoryCache(default_ttl=None)
    cache.set(model_health_key("model-a"), {
        "health_state": "quarantined",
        "artifact_valid": True,
        "data_fresh": True,
    })
    cache.create_immutable(approval_key, approval)
    healthy = {"hard_failure": False, "drift_failed": False}

    out = publish_model_health(
        cache,
        "model-a",
        "approved",
        [healthy, healthy],
        artifact_sha256=ARTIFACT_SHA256,
        revalidation={"approval_ref": "review-42"},
    )

    assert out["health_state"] == "quarantined"
    assert out["revalidation_accepted"] is False
    assert cache.get(approval_key) == approval


def test_consumed_approval_cannot_be_replayed():
    approval = approval_record()
    approval_key = model_health_approval_key("review-42")
    cache = MemoryCache(default_ttl=None)
    cache.set(model_health_key("model-a"), {
        "health_state": "quarantined",
        "artifact_valid": True,
        "data_fresh": True,
    })
    cache.create_immutable(approval_key, approval)
    healthy = {"hard_failure": False, "drift_failed": False}
    first = publish_model_health(
        cache,
        "model-a",
        "approved",
        [healthy, healthy],
        artifact_sha256=ARTIFACT_SHA256,
        revalidation={"approval_ref": "review-42"},
    )
    replay = publish_model_health(
        cache,
        "model-a",
        "approved",
        [healthy, healthy],
        artifact_sha256=ARTIFACT_SHA256,
        revalidation={"approval_ref": "review-42"},
    )

    assert replay["health_state"] == "quarantined"
    assert replay["runtime_eligible"] is False
    assert replay["revalidation_accepted"] is False


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_concurrent_revalidation_consumes_approval_once(backend, tmp_path):
    cache = (
        MemoryCache(default_ttl=None)
        if backend == "memory"
        else SqliteCache(str(tmp_path / "consume.db"), default_ttl=None)
    )
    approval = approval_record()
    healthy = {"hard_failure": False, "drift_failed": False}
    cache.set(model_health_key("model-a"), {
        "health_state": "quarantined",
        "artifact_valid": True,
        "data_fresh": True,
    })
    cache.create_immutable(model_health_approval_key("review-42"), approval)

    def revalidate(_worker):
        return publish_model_health(
            cache,
            "model-a",
            "approved",
            [healthy, healthy],
            artifact_sha256=ARTIFACT_SHA256,
            revalidation={"approval_ref": "review-42"},
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(revalidate, range(2)))

        assert sum(row["revalidation_accepted"] is True for row in results) == 1
        assert sum(row["health_state"] == "quarantined" for row in results) == 1
        consumed = cache.get(model_health_approval_consumed_key("review-42"))
        assert consumed["model_id"] == "model-a"
    finally:
        if isinstance(cache, SqliteCache):
            cache._conn.close()


def test_concurrent_publishers_merge_latest_without_lost_models():
    cache = MemoryCache(default_ttl=None)
    healthy = {"hard_failure": False, "drift_failed": False}

    def publish(model_id):
        return publish_model_health(
            cache, model_id, "approved", [healthy, healthy]
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(publish, ["model-a", "model-b"]))

    latest = cache.get("adaptive:model_health:latest")
    assert set(latest["models"]) == {"model-a", "model-b"}
    assert latest["summary"]["total"] == 2


def test_health_atomic_serialization_failure_writes_nothing(tmp_path):
    model_key = model_health_key("model-a")

    class CorruptingSqliteCache(SqliteCache):
        def atomic_update(self, keys, updater):
            def corrupt(snapshot):
                writes = updater(snapshot)
                circular = []
                circular.append(circular)
                writes[model_key]["injected"] = circular
                return writes

            return super().atomic_update(keys, corrupt)

    cache = CorruptingSqliteCache(str(tmp_path / "health-atomic.db"), default_ttl=None)
    try:
        with pytest.raises(ValueError, match="Circular reference"):
            publish_model_health(cache, "model-a", "approved", [])

        assert cache.get(model_key) is None
        assert cache.get(model_health_history_key("model-a")) is None
        assert cache.get("adaptive:model_health:latest") is None
    finally:
        cache._conn.close()


def test_health_publisher_rejects_non_atomic_cache():
    class LegacyCache:
        def get(self, key):
            return None

        def set(self, key, value, ttl=None):
            raise AssertionError("must not write")

    with pytest.raises(RuntimeError, match="atomic_update"):
        publish_model_health(LegacyCache(), "model-a", "approved", [])

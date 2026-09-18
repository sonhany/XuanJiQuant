import json
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest
import quant.research.publication as publication

from quant.research.publication import (
    PublicationError,
    begin_refresh,
    mark_refresh_failed,
    publish_generation,
    read_publication_status,
    resolve_complete_artifact,
    resolve_complete_generation,
)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _stage_complete(generation, *, date: str, snapshot_id: str, version: str) -> None:
    authority = {"promotion_state": "research_only", "execution_authority": False}
    _write(
        generation.staging_dir / "factor_snapshot_latest.json",
        {
            "as_of": date,
            "latest_kline_date": date,
            "snapshot_id": snapshot_id,
            "data_version": version,
            "n": 1,
            "active_count": 1,
            "data_count": 1,
            "eligible_count": 1,
            "data_coverage": 1.0,
            "rows": [
                {
                    "code": "000001",
                    "date": date,
                    "factors": {"range_pct": 1.0},
                }
            ],
            **authority,
        },
    )
    _write(
        generation.staging_dir / "factor_evaluation.json",
        {
            "data_end_date": date,
            "snapshot_id": snapshot_id,
            "data_version": version,
            "n_stocks": 1,
            "active_count": 1,
            "data_count": 1,
            "eligible_count": 1,
            "factors": [{"factor": "range_pct"}],
            **authority,
        },
    )
    _write(
        generation.staging_dir / "selection.json",
        {
            "selection_date": date,
            "portfolio_id": f"portfolio-{date}",
            "generated_from_snapshot_id": snapshot_id,
            "snapshot_data_version": version,
            "positions": [{"code": "000001", "weight": 0.1}],
            "position_count": 1,
            "not_a_trade_signal": True,
            **authority,
        },
    )


def _publish(root: Path, *, date: str, snapshot_id: str, version: str, compatibility_paths=None):
    generation = begin_refresh(
        root,
        target_date=date,
        snapshot_id=snapshot_id,
        data_version=version,
        started_at=f"{date[:4]}-{date[4:6]}-{date[6:]}T16:20:00+08:00",
    )
    _stage_complete(generation, date=date, snapshot_id=snapshot_id, version=version)
    return publish_generation(
        root,
        generation,
        finished_at=f"{date[:4]}-{date[4:6]}-{date[6:]}T16:40:00+08:00",
        compatibility_paths=compatibility_paths,
    )


def test_refresh_keeps_previous_complete_pointer_visible(tmp_path):
    root = tmp_path / "daily"
    first = _publish(root, date="20260818", snapshot_id="daily-18", version="v18")

    pending = begin_refresh(
        root,
        target_date="20260819",
        snapshot_id="daily-19",
        data_version="v19",
        started_at="2026-08-19T16:20:00+08:00",
    )

    status = read_publication_status(root)
    resolved = resolve_complete_artifact(root, "factor_evaluation.json")
    assert status["state"] == "refreshing"
    assert status["target_date"] == "20260819"
    assert status["last_complete_generation_id"] == first["generation_id"]
    assert pending.generation_id != first["generation_id"]
    assert json.loads(resolved.read_text(encoding="utf-8"))["data_version"] == "v18"


@pytest.mark.parametrize("field", ["target_date", "snapshot_id", "data_version"])
def test_pointer_identity_tamper_is_rejected(tmp_path, field):
    root = tmp_path / "daily"
    _publish(root, date="20260818", snapshot_id="daily-18", version="v18")
    pointer_path = root / "latest.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer[field] = "forged"
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")

    with pytest.raises(PublicationError, match="publication_pointer_identity_mismatch"):
        resolve_complete_generation(root)


def test_incomplete_generation_fails_closed_without_switching_pointer(tmp_path):
    root = tmp_path / "daily"
    first = _publish(root, date="20260818", snapshot_id="daily-18", version="v18")
    pending = begin_refresh(
        root,
        target_date="20260819",
        snapshot_id="daily-19",
        data_version="v19",
        started_at="2026-08-19T16:20:00+08:00",
    )
    _write(
        pending.staging_dir / "factor_evaluation.json",
        {
            "data_end_date": "20260819",
            "snapshot_id": "daily-19",
            "data_version": "v19",
            "factors": [{"factor": "range_pct"}],
            "promotion_state": "research_only",
            "execution_authority": False,
        },
    )

    with pytest.raises(PublicationError, match="artifact_missing"):
        publish_generation(root, pending, finished_at="2026-08-19T16:21:00+08:00")

    status = read_publication_status(root)
    assert status["state"] == "failed"
    assert status["reason_code"] == "artifact_missing"
    assert status["last_complete_generation_id"] == first["generation_id"]
    assert json.loads((root / "latest.json").read_text(encoding="utf-8"))["generation_id"] == first["generation_id"]


def test_complete_same_version_artifacts_switch_one_authoritative_pointer(tmp_path):
    root = tmp_path / "daily"
    _publish(root, date="20260818", snapshot_id="daily-18", version="v18")
    mirrors = {
        "factor_snapshot_latest.json": tmp_path / "compat" / "factor_snapshot_latest.json",
        "factor_evaluation.json": tmp_path / "compat" / "factor_evaluation.json",
        "selection.json": tmp_path / "compat" / "selections" / "latest.json",
    }
    second = _publish(
        root,
        date="20260819",
        snapshot_id="daily-19",
        version="v19",
        compatibility_paths=mirrors,
    )

    pointer = json.loads((root / "latest.json").read_text(encoding="utf-8"))
    status = read_publication_status(root)
    assert pointer["generation_id"] == second["generation_id"]
    assert pointer["target_date"] == "20260819"
    assert set(pointer["artifact_sha256"]) == {
        "factor_snapshot_latest.json",
        "factor_evaluation.json",
        "selection.json",
    }
    assert all(len(value) == 64 for value in pointer["artifact_sha256"].values())
    assert status["state"] == "completed"
    assert status["last_complete_generation_id"] == second["generation_id"]
    assert json.loads(resolve_complete_artifact(root, "selection.json").read_text(encoding="utf-8"))["snapshot_data_version"] == "v19"
    assert json.loads(mirrors["factor_evaluation.json"].read_text(encoding="utf-8"))["data_version"] == "v19"
    assert json.loads(mirrors["selection.json"].read_text(encoding="utf-8"))["snapshot_data_version"] == "v19"
    assert json.loads(mirrors["factor_snapshot_latest.json"].read_text(encoding="utf-8"))["data_version"] == "v19"


def test_resolver_rejects_unregistered_artifact_name(tmp_path):
    root = tmp_path / "daily"
    _publish(root, date="20260818", snapshot_id="daily-18", version="v18")

    with pytest.raises(PublicationError, match="artifact_name_invalid"):
        resolve_complete_artifact(root, "../factor_evaluation.json")


def test_same_generation_retries_use_unique_attempts_and_stale_handle_cannot_overwrite(tmp_path):
    root = tmp_path / "daily"
    first = begin_refresh(
        root,
        target_date="20260819",
        snapshot_id="daily-19",
        data_version="v19",
        started_at="2026-08-19T16:20:00+08:00",
    )
    second = begin_refresh(
        root,
        target_date="20260819",
        snapshot_id="daily-19",
        data_version="v19",
        started_at="2026-08-19T16:21:00+08:00",
    )
    assert first.generation_id == second.generation_id
    assert first.attempt_id != second.attempt_id
    assert first.staging_dir != second.staging_dir

    with pytest.raises(PublicationError, match="generation_attempt_mismatch"):
        mark_refresh_failed(
            root,
            first,
            reason_code="stale_owner",
            finished_at="2026-08-19T16:22:00+08:00",
        )


def test_pointer_cannot_resolve_another_generation_even_with_matching_hash(tmp_path):
    root = tmp_path / "daily"
    first = _publish(root, date="20260818", snapshot_id="daily-18", version="v18")
    first_path = resolve_complete_artifact(root, "factor_evaluation.json")
    first_hash = __import__("hashlib").sha256(first_path.read_bytes()).hexdigest()
    second = _publish(root, date="20260819", snapshot_id="daily-19", version="v19")
    pointer_path = root / "latest.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["artifact_paths"]["factor_evaluation.json"] = (
        f"generations/{first['generation_id']}/factor_evaluation.json"
    )
    pointer["artifact_sha256"]["factor_evaluation.json"] = first_hash
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")

    with pytest.raises(PublicationError, match="publication_path_identity_mismatch"):
        resolve_complete_artifact(root, "factor_evaluation.json")


def test_hash_tampering_is_rejected(tmp_path):
    root = tmp_path / "daily"
    _publish(root, date="20260818", snapshot_id="daily-18", version="v18")
    path = resolve_complete_artifact(root, "factor_evaluation.json")
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(PublicationError, match="publication_artifact_integrity_failed"):
        resolve_complete_artifact(root, "factor_evaluation.json")


@pytest.mark.parametrize(
    ("artifact", "field", "value", "reason"),
    [
        ("factor_evaluation.json", "execution_authority", True, "artifact_authority_invalid"),
        ("factor_snapshot_latest.json", "data_version", "wrong", "factor_projection_identity_mismatch"),
        ("selection.json", "selection_date", "20260818", "selection_identity_mismatch"),
    ],
)
def test_authority_and_cross_artifact_identity_drift_fail_closed(
    tmp_path, artifact, field, value, reason
):
    root = tmp_path / "daily"
    generation = begin_refresh(
        root,
        target_date="20260819",
        snapshot_id="daily-19",
        data_version="v19",
        started_at="2026-08-19T16:20:00+08:00",
    )
    _stage_complete(generation, date="20260819", snapshot_id="daily-19", version="v19")
    path = generation.staging_dir / artifact
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[field] = value
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PublicationError, match=reason):
        publish_generation(root, generation, finished_at="2026-08-19T16:40:00+08:00")
    assert read_publication_status(root)["state"] == "failed"


def test_mirror_failure_does_not_undo_completed_pointer(tmp_path):
    root = tmp_path / "daily"
    generation = begin_refresh(
        root,
        target_date="20260819",
        snapshot_id="daily-19",
        data_version="v19",
        started_at="2026-08-19T16:20:00+08:00",
    )
    _stage_complete(generation, date="20260819", snapshot_id="daily-19", version="v19")
    invalid_target = tmp_path / "is-a-directory"
    invalid_target.mkdir()

    result = publish_generation(
        root,
        generation,
        finished_at="2026-08-19T16:40:00+08:00",
        compatibility_paths={"factor_evaluation.json": invalid_target},
    )

    status = read_publication_status(root)
    assert result["generation_id"] == generation.generation_id
    assert status["state"] == "completed"
    assert status["mirror_sync_state"] == "failed"
    assert json.loads((root / "latest.json").read_text(encoding="utf-8"))["generation_id"] == generation.generation_id


def test_forged_generation_paths_are_rejected(tmp_path):
    root = tmp_path / "daily"
    generation = begin_refresh(
        root,
        target_date="20260819",
        snapshot_id="daily-19",
        data_version="v19",
        started_at="2026-08-19T16:20:00+08:00",
    )
    forged = replace(generation, staging_dir=tmp_path / "outside")

    with pytest.raises(PublicationError, match="generation_path_invalid"):
        publish_generation(root, forged, finished_at="2026-08-19T16:40:00+08:00")


def test_pointer_commit_is_not_reported_failed_when_completed_status_sync_fails(
    tmp_path, monkeypatch
):
    root = tmp_path / "daily"
    generation = begin_refresh(
        root,
        target_date="20260819",
        snapshot_id="daily-19",
        data_version="v19",
        started_at="2026-08-19T16:20:00+08:00",
    )
    _stage_complete(generation, date="20260819", snapshot_id="daily-19", version="v19")
    original = publication._atomic_json

    def fail_completed_status(path, payload):
        if path.name == "status.json" and payload.get("state") == "completed":
            raise OSError("status unavailable")
        return original(path, payload)

    monkeypatch.setattr(publication, "_atomic_json", fail_completed_status)
    result = publish_generation(
        root, generation, finished_at="2026-08-19T16:40:00+08:00"
    )

    assert result["generation_id"] == generation.generation_id
    assert result["status_sync_state"] == "failed"
    assert json.loads((root / "latest.json").read_text(encoding="utf-8"))["generation_id"] == generation.generation_id
    recovered = read_publication_status(root)
    assert recovered["state"] == "completed"
    assert recovered["status_sync_state"] == "recovered_from_pointer"


def test_old_mirror_completion_cannot_overwrite_new_refresh_status(tmp_path, monkeypatch):
    root = tmp_path / "daily"
    generation = begin_refresh(
        root,
        target_date="20260819",
        snapshot_id="daily-19",
        data_version="v19",
        started_at="2026-08-19T16:20:00+08:00",
    )
    _stage_complete(generation, date="20260819", snapshot_id="daily-19", version="v19")
    original = publication._atomic_bytes
    mirror_started = threading.Event()
    release_mirror = threading.Event()
    next_started = threading.Event()
    results = {}

    def block_mirror(path, content):
        mirror_started.set()
        assert release_mirror.wait(5)
        original(path, content)

    def publish_old():
        results["published"] = publish_generation(
            root,
            generation,
            finished_at="2026-08-19T16:40:00+08:00",
            compatibility_paths={
                "factor_evaluation.json": tmp_path / "compat" / "factor_evaluation.json"
            },
        )

    def start_new():
        results["next"] = begin_refresh(
            root,
            target_date="20260820",
            snapshot_id="daily-20",
            data_version="v20",
            started_at="2026-08-20T16:20:00+08:00",
        )
        next_started.set()

    monkeypatch.setattr(publication, "_atomic_bytes", block_mirror)
    publisher = threading.Thread(target=publish_old)
    follower = threading.Thread(target=start_new)
    publisher.start()
    assert mirror_started.wait(5)
    follower.start()
    time.sleep(0.1)
    assert next_started.is_set() is False
    release_mirror.set()
    publisher.join(5)
    follower.join(5)
    assert not publisher.is_alive()
    assert not follower.is_alive()

    status = read_publication_status(root)
    assert status["state"] == "refreshing"
    assert status["generation_id"] == results["next"].generation_id
    assert status["attempt_id"] == results["next"].attempt_id


def test_existing_final_tampering_cannot_be_republished(tmp_path):
    root = tmp_path / "daily"
    first = _publish(root, date="20260819", snapshot_id="daily-19", version="v19")
    final_eval = root / "generations" / first["generation_id"] / "factor_evaluation.json"
    final_eval.write_text(
        final_eval.read_text(encoding="utf-8") + " ", encoding="utf-8"
    )
    retry = begin_refresh(
        root,
        target_date="20260819",
        snapshot_id="daily-19",
        data_version="v19",
        started_at="2026-08-19T17:20:00+08:00",
    )
    _stage_complete(retry, date="20260819", snapshot_id="daily-19", version="v19")

    with pytest.raises(PublicationError, match="generation_identity_collision"):
        publish_generation(root, retry, finished_at="2026-08-19T17:40:00+08:00")


@pytest.mark.parametrize(
    ("artifact", "field", "value", "reason"),
    [
        ("factor_snapshot_latest.json", "rows", "bad", "factor_projection_identity_mismatch"),
        ("factor_evaluation.json", "factors", {"bad": 1}, "factor_evaluation_identity_mismatch"),
        ("selection.json", "positions", "bad", "selection_identity_mismatch"),
    ],
)
def test_malformed_artifact_schema_is_rejected(tmp_path, artifact, field, value, reason):
    root = tmp_path / "daily"
    generation = begin_refresh(
        root,
        target_date="20260819",
        snapshot_id="daily-19",
        data_version="v19",
        started_at="2026-08-19T16:20:00+08:00",
    )
    _stage_complete(generation, date="20260819", snapshot_id="daily-19", version="v19")
    path = generation.staging_dir / artifact
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[field] = value
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PublicationError, match=reason):
        publish_generation(root, generation, finished_at="2026-08-19T16:40:00+08:00")
    assert not generation.staging_dir.exists()


def test_idempotent_same_generation_retry_cleans_attempt_staging(tmp_path):
    root = tmp_path / "daily"
    _publish(root, date="20260819", snapshot_id="daily-19", version="v19")
    retry = begin_refresh(
        root,
        target_date="20260819",
        snapshot_id="daily-19",
        data_version="v19",
        started_at="2026-08-19T17:20:00+08:00",
    )
    _stage_complete(retry, date="20260819", snapshot_id="daily-19", version="v19")

    publish_generation(root, retry, finished_at="2026-08-19T17:40:00+08:00")

    assert not retry.staging_dir.exists()


def test_same_process_atomic_json_writers_use_distinct_temp_files(tmp_path):
    target = tmp_path / "status.json"
    errors = []

    def writer(value):
        try:
            publication._atomic_json(target, {"value": value})
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)

    assert errors == []
    assert json.loads(target.read_text(encoding="utf-8"))["value"] in range(8)
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize("weight", [float("nan"), float("inf"), True])
def test_non_finite_or_boolean_selection_weight_is_rejected(tmp_path, weight):
    root = tmp_path / "daily"
    generation = begin_refresh(
        root,
        target_date="20260819",
        snapshot_id="daily-19",
        data_version="v19",
        started_at="2026-08-19T16:20:00+08:00",
    )
    _stage_complete(generation, date="20260819", snapshot_id="daily-19", version="v19")
    path = generation.staging_dir / "selection.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["positions"][0]["weight"] = weight
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PublicationError, match="selection_identity_mismatch"):
        publish_generation(root, generation, finished_at="2026-08-19T16:40:00+08:00")


def test_cleanup_failure_after_commit_does_not_turn_success_into_failure(
    tmp_path, monkeypatch
):
    root = tmp_path / "daily"
    _publish(root, date="20260819", snapshot_id="daily-19", version="v19")
    retry = begin_refresh(
        root,
        target_date="20260819",
        snapshot_id="daily-19",
        data_version="v19",
        started_at="2026-08-19T17:20:00+08:00",
    )
    _stage_complete(retry, date="20260819", snapshot_id="daily-19", version="v19")
    monkeypatch.setattr(
        publication.shutil,
        "rmtree",
        lambda _path: (_ for _ in ()).throw(PermissionError("busy")),
    )

    result = publish_generation(
        root, retry, finished_at="2026-08-19T17:40:00+08:00"
    )

    assert result["generation_id"] == retry.generation_id
    assert result["staging_cleanup_state"] == "failed"
    assert read_publication_status(root)["state"] == "completed"


def test_cleanup_failure_does_not_mask_original_publication_error(tmp_path, monkeypatch):
    root = tmp_path / "daily"
    generation = begin_refresh(
        root,
        target_date="20260819",
        snapshot_id="daily-19",
        data_version="v19",
        started_at="2026-08-19T16:20:00+08:00",
    )
    monkeypatch.setattr(
        publication.shutil,
        "rmtree",
        lambda _path: (_ for _ in ()).throw(PermissionError("busy")),
    )

    with pytest.raises(PublicationError, match="artifact_missing"):
        publish_generation(root, generation, finished_at="2026-08-19T16:40:00+08:00")

    status = read_publication_status(root)
    assert status["state"] == "failed"
    assert status["reason_code"] == "artifact_missing"
    assert status["staging_cleanup_state"] == "failed"


@pytest.mark.parametrize("drift", ["count", "duplicate_code", "row_date"])
def test_cross_artifact_coverage_and_row_identity_must_be_complete(tmp_path, drift):
    root = tmp_path / "daily"
    generation = begin_refresh(
        root,
        target_date="20260819",
        snapshot_id="daily-19",
        data_version="v19",
        started_at="2026-08-19T16:20:00+08:00",
    )
    _stage_complete(generation, date="20260819", snapshot_id="daily-19", version="v19")
    projection_path = generation.staging_dir / "factor_snapshot_latest.json"
    projection = json.loads(projection_path.read_text(encoding="utf-8"))
    if drift == "count":
        projection["eligible_count"] = 2
    elif drift == "duplicate_code":
        projection["n"] = 2
        projection["eligible_count"] = 2
        projection["rows"].append(dict(projection["rows"][0]))
    else:
        projection["rows"][0]["date"] = "20260818"
    projection_path.write_text(json.dumps(projection), encoding="utf-8")

    with pytest.raises(PublicationError, match="factor_projection_coverage_mismatch"):
        publish_generation(root, generation, finished_at="2026-08-19T16:40:00+08:00")


def test_failed_attempt_archives_research_job_ledger_before_staging_cleanup(tmp_path):
    root = tmp_path / "daily"
    generation = begin_refresh(
        root,
        target_date="20260819",
        snapshot_id="daily-19",
        data_version="v19",
        started_at="2026-08-19T16:20:00+08:00",
    )
    ledger = generation.staging_dir / "research_jobs.db"
    ledger.write_bytes(b"sqlite-audit-evidence")

    status = mark_refresh_failed(
        root,
        generation,
        reason_code="research_training_failed",
        finished_at="2026-08-19T16:21:00+08:00",
    )

    archive = (
        root
        / "failed-attempts"
        / f"{generation.generation_id}.{generation.attempt_id}"
    )
    assert status["failure_audit_state"] == "completed"
    assert not generation.staging_dir.exists()
    assert (archive / "research_jobs.db").read_bytes() == b"sqlite-audit-evidence"
    summary = json.loads((archive / "failure.json").read_text(encoding="utf-8"))
    assert summary["reason_code"] == "research_training_failed"
    assert summary["attempt_id"] == generation.attempt_id

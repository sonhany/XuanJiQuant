from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import quant.strategy.f4_v2_publication as publication
from quant.strategy.f4_alpha_contracts import build_v2_candidate_registry
from quant.strategy.f4_candidate_factory import (
    canonical_payload_hash,
    candidate_factory_id,
    candidate_registry_hash,
)
from quant.strategy.f4_v2_publication import (
    F4V2PublicationError,
    F4V2PublicationHandle,
    REQUIRED_V2_ARTIFACTS,
    begin_v2_publication,
    publication_base_pointer,
    publish_v2_generation,
    resolve_committed_v2_generation,
    resolve_committed_v2_candidate_evidence,
    write_v2_compatibility_projection,
)


AUTHORITY = {"promotion_state": "research_only", "execution_authority": False}


def _write(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


_IDENTITY_BY_FACTORY_ID: dict[str, dict] = {}


def _factory_identity(label: str = "factory-a") -> dict:
    return {
        "pipeline_version": "f4-real-pipeline-v4-multi-alpha-candidates",
        "dataset_version": "pit-v1",
        "manifest_hash": "manifest-v1",
        "industry_version": "industry-v1",
        "industry_hash": "industry-hash-v1",
        "benchmark_version": "benchmark-v1",
        "code_version": f"code-{label}",
    }


def _factory_id(label: str = "factory-a") -> str:
    identity = _factory_identity(label)
    value = candidate_factory_id(identity, build_v2_candidate_registry())
    _IDENTITY_BY_FACTORY_ID[value] = identity
    return value


def _complete_staging(
    tmp_path: Path,
    *,
    factory_run_id: str | None = None,
    winner_alpha: str = "M1",
    aggregate_sharpe: float = 1.0,
) -> F4V2PublicationHandle:
    factory_run_id = factory_run_id or _factory_id()
    handle = begin_v2_publication(tmp_path, factory_run_id=factory_run_id)
    registry = build_v2_candidate_registry()
    candidate = next(
        item for item in registry if item.alpha_spec.alpha_id == winner_alpha
    )
    registry_hash = candidate_registry_hash(registry)
    input_identity = _IDENTITY_BY_FACTORY_ID.get(
        factory_run_id, _factory_identity("factory-a")
    )

    locked_root = (
        handle.factory_root / "locked-artifacts" / factory_run_id / "wf-01"
    )
    fit_path = _write(
        locked_root / "alpha-fit.json",
        {"alpha_fit_hash": "fit-semantic-v1", **AUTHORITY},
    )
    score_path = locked_root / "validation-score.csv"
    score_path.write_text("date,code,score\n2026-01-02,SH600000,1.0\n", encoding="utf-8")

    leaderboard = {
        "factory_run_id": factory_run_id,
        "window_id": "wf-01",
        "candidate_registry_hash": registry_hash,
        "candidate_count": 24,
        "candidates": [
            {
                "candidate_id": item.candidate_id,
                "eligible": True,
                "selected": item.candidate_id == candidate.candidate_id,
                "validation_rank": index,
                "metrics": {"after_cost_excess_return": 0.01 / index},
                **AUTHORITY,
            }
            for index, item in enumerate(registry, 1)
        ],
        **AUTHORITY,
    }
    leaderboard_path = _write(
        handle.factory_root
        / "locks"
        / factory_run_id
        / "wf-01.leaderboard.json",
        leaderboard,
    )
    lock_core = {
        "factory_run_id": factory_run_id,
        "window_id": "wf-01",
        "candidate_id": candidate.candidate_id,
        "candidate_registry_hash": registry_hash,
        "candidate_count": 24,
        "alpha_spec_hash": canonical_payload_hash(candidate.to_dict()["alpha_spec"]),
        "alpha_fit_path": str(fit_path.resolve()),
        "alpha_fit_hash": "fit-semantic-v1",
        "alpha_fit_artifact_hash": _sha256(fit_path),
        "model_artifact_path": None,
        "model_artifact_hash": None,
        "validation_score_path": str(score_path.resolve()),
        "validation_score_hash": _sha256(score_path),
        "portfolio_policy_hash": canonical_payload_hash(
            candidate.to_dict()["portfolio_policy"]
        ),
        "validation_leaderboard_path": str(leaderboard_path.resolve()),
        "validation_leaderboard_hash": _sha256(leaderboard_path),
        "selection_scope": "current_window_validation_only",
        "test_scope": "locked_winner_only",
    }
    lock = {
        **lock_core,
        "lock_hash": canonical_payload_hash(lock_core),
        **AUTHORITY,
    }

    artifacts = {
        "registry.json": {
            "factory_run_id": factory_run_id,
            "factory_version": "f4-multi-alpha-candidate-factory-v2",
            "candidate_registry_hash": registry_hash,
            "candidate_count": 24,
            "input_identity": input_identity,
            "candidates": [item.to_dict() for item in registry],
            **AUTHORITY,
        },
        "window_definitions.json": {
            "factory_run_id": factory_run_id,
            "windows": [{"window_id": "wf-01", "status": "completed"}],
            **AUTHORITY,
        },
        "alpha_fits.json": {
            "factory_run_id": factory_run_id,
            "fits": [
                {
                    "window_id": "wf-01",
                    "candidate_id": candidate.candidate_id,
                    "alpha_spec_hash": lock["alpha_spec_hash"],
                    "alpha_fit_path": lock["alpha_fit_path"],
                    "alpha_fit_hash": lock["alpha_fit_hash"],
                    "alpha_fit_artifact_hash": lock["alpha_fit_artifact_hash"],
                }
            ],
            **AUTHORITY,
        },
        "model_artifacts.json": {
            "factory_run_id": factory_run_id,
            "models": [],
            **AUTHORITY,
        },
        "validation_leaderboards.json": {
            "factory_run_id": factory_run_id,
            "leaderboards": [leaderboard],
            **AUTHORITY,
        },
        "candidate_selection_locks.json": {
            "factory_run_id": factory_run_id,
            "locks": [lock],
            **AUTHORITY,
        },
        "test_window_metrics.json": {
            "factory_run_id": factory_run_id,
            "windows": [
                {
                    "window_id": "wf-01",
                    "candidate_id": candidate.candidate_id,
                    "metrics": {"1.0": {"excess_return": 0.01}},
                    **AUTHORITY,
                }
            ],
            **AUTHORITY,
        },
        "cost_stress_metrics.json": {
            "factory_run_id": factory_run_id,
            "multipliers": {
                "1.0": {"excess_return": 0.01},
                "1.5": {"excess_return": 0.005},
                "2.0": {"excess_return": 0.001},
            },
            **AUTHORITY,
        },
        "family_diagnostics.json": {
            "factory_run_id": factory_run_id,
            "families": {
                name: {"candidate_count": 4}
                for name in (
                    "momentum",
                    "reversal",
                    "defensive",
                    "liquidity",
                    "ensemble",
                    "qlib",
                )
            },
            **AUTHORITY,
        },
    }
    for name, payload in artifacts.items():
        _write(handle.staging_dir / name, payload)
    _write(
        handle.staging_dir / "factory_report.json",
        {
            "factory_run_id": factory_run_id,
            "factory_version": "f4-multi-alpha-candidate-factory-v2",
            "candidate_registry_hash": registry_hash,
            "input_identity": input_identity,
            "candidate_count": 24,
            "family_count": 6,
            "candidate_factory_status": "completed",
            "runtime_seconds": 1.25,
            "family_status": {name: "available" for name in artifacts["family_diagnostics.json"]["families"]},
            "aggregate_metrics": {"sharpe": aggregate_sharpe},
            "gate_version": "f4-gate-v4",
            "failure_reasons": [],
            "publication_base_pointer": publication_base_pointer(handle),
            "artifact_hashes": {
                name: _sha256(handle.staging_dir / name)
                for name in REQUIRED_V2_ARTIFACTS
                if name != "factory_report.json"
            },
            **AUTHORITY,
        },
    )
    return handle


def _rehash_report(staging: Path) -> None:
    report_path = staging / "factory_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["artifact_hashes"] = {
        name: _sha256(staging / name)
        for name in REQUIRED_V2_ARTIFACTS
        if name != "factory_report.json"
    }
    _write(report_path, report)


def test_candidate_evidence_resolver_verifies_report_and_only_required_child(
    tmp_path,
):
    factory_run_id = _factory_id("candidate-evidence")
    handle = _complete_staging(tmp_path, factory_run_id=factory_run_id)
    report_path = handle.staging_dir / "factory_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    candidate_spec = {
        "version": "f4-multi-alpha-candidate-factory-v2",
        "factory_run_id": factory_run_id,
        "factor_fits": [],
        "selected_policies": [],
        "selection_locks": [],
        "promotion_state": "research_only",
        "execution_authority": False,
    }
    report["pipeline_result"] = {
        "candidate_spec": candidate_spec,
        "promotion_state": "research_only",
        "execution_authority": False,
    }
    report["pipeline_result_sha256"] = canonical_payload_hash(
        report["pipeline_result"]
    )
    _write(report_path, report)
    publish_v2_generation(handle)

    resolved = resolve_committed_v2_candidate_evidence(
        tmp_path, expected_factory_run_id=factory_run_id
    )

    assert resolved["candidate_spec"]["factory_run_id"] == factory_run_id
    assert resolved["model_artifacts"] == []


def _read_pointer(tmp_path: Path) -> dict:
    return json.loads(
        (tmp_path / "data" / "research" / "f4" / "factory-v2" / "latest.json").read_text(
            encoding="utf-8"
        )
    )


def test_v2_publication_requires_exactly_all_ten_artifacts(tmp_path):
    handle = _complete_staging(tmp_path)
    (handle.staging_dir / "family_diagnostics.json").unlink()
    with pytest.raises(F4V2PublicationError, match="f4_v2_artifact_missing"):
        publish_v2_generation(handle)

    handle = _complete_staging(tmp_path, factory_run_id=_factory_id("factory-b"))
    _write(handle.staging_dir / "unexpected.json", AUTHORITY)
    with pytest.raises(F4V2PublicationError, match="f4_v2_artifact_set_invalid"):
        publish_v2_generation(handle)


def test_non_winner_test_artifact_blocks_publication(tmp_path):
    handle = _complete_staging(tmp_path)
    registry = build_v2_candidate_registry()
    test_path = handle.staging_dir / "test_window_metrics.json"
    payload = json.loads(test_path.read_text(encoding="utf-8"))
    payload["windows"][0]["candidate_id"] = registry[1].candidate_id
    _write(test_path, payload)
    _rehash_report(handle.staging_dir)

    with pytest.raises(F4V2PublicationError, match="f4_v2_test_without_lock"):
        publish_v2_generation(handle)


@pytest.mark.parametrize(
    "mutation",
    [
        "nan",
        "authority",
        "candidate_hash",
        "lock_hash",
        "fit_hash",
        "leaderboard_hash",
        "nested_authority",
    ],
)
def test_integrity_failure_preserves_old_authoritative_pointer(tmp_path, mutation):
    old_id = _factory_id("old")
    publish_v2_generation(_complete_staging(tmp_path, factory_run_id=old_id))
    old_pointer = _read_pointer(tmp_path)
    handle = _complete_staging(tmp_path, factory_run_id=_factory_id(mutation))

    if mutation == "nan":
        report = json.loads((handle.staging_dir / "factory_report.json").read_text())
        report["aggregate_metrics"]["sharpe"] = float("nan")
        _write(handle.staging_dir / "factory_report.json", report)
    elif mutation == "authority":
        payload_path = handle.staging_dir / "family_diagnostics.json"
        payload = json.loads(payload_path.read_text())
        payload["execution_authority"] = True
        _write(payload_path, payload)
        _rehash_report(handle.staging_dir)
    elif mutation == "candidate_hash":
        payload_path = handle.staging_dir / "registry.json"
        payload = json.loads(payload_path.read_text())
        payload["candidates"][0]["candidate_id"] = "0" * 64
        _write(payload_path, payload)
        _rehash_report(handle.staging_dir)
    elif mutation == "lock_hash":
        payload_path = handle.staging_dir / "candidate_selection_locks.json"
        payload = json.loads(payload_path.read_text())
        payload["locks"][0]["lock_hash"] = "0" * 64
        _write(payload_path, payload)
        _rehash_report(handle.staging_dir)
    elif mutation == "fit_hash":
        fit_path = next((handle.factory_root / "locked-artifacts").rglob("alpha-fit.json"))
        fit_path.write_text("tampered", encoding="utf-8")
    elif mutation == "leaderboard_hash":
        leaderboard_path = next((handle.factory_root / "locks").rglob("*.leaderboard.json"))
        leaderboard_path.write_text("{}", encoding="utf-8")
    else:
        payload_path = handle.staging_dir / "cost_stress_metrics.json"
        payload = json.loads(payload_path.read_text())
        payload["multipliers"]["2.0"]["execution_authority"] = True
        _write(payload_path, payload)
        _rehash_report(handle.staging_dir)

    with pytest.raises(F4V2PublicationError):
        publish_v2_generation(handle)
    assert _read_pointer(tmp_path) == old_pointer


def test_complete_same_identity_is_strict_idempotent_no_op(tmp_path):
    first_handle = _complete_staging(tmp_path)
    first = publish_v2_generation(first_handle)

    second = begin_v2_publication(tmp_path, factory_run_id=first["factory_run_id"])
    (second.staging_dir / "forbidden-runner-called.txt").write_text("no", encoding="utf-8")
    reused = publish_v2_generation(second)

    assert reused["publication_no_op"] is True
    assert reused["factory_run_id"] == first["factory_run_id"]
    assert _read_pointer(tmp_path)["factory_run_id"] == first["factory_run_id"]

    corrupted_retry = begin_v2_publication(
        tmp_path, factory_run_id=first["factory_run_id"]
    )
    final_report = first_handle.final_dir / "factory_report.json"
    final_report.write_text("{}", encoding="utf-8")
    with pytest.raises(F4V2PublicationError, match="f4_v2_final_integrity_failed"):
        publish_v2_generation(corrupted_retry)


def test_complete_generation_without_pointer_is_recovered_after_full_revalidation(tmp_path):
    handle = _complete_staging(tmp_path)
    publish_v2_generation(handle)
    (handle.factory_root / "latest.json").unlink()

    recovered = publish_v2_generation(
        begin_v2_publication(tmp_path, factory_run_id=handle.factory_run_id)
    )

    assert recovered["publication_recovered"] is True
    assert recovered["publication_no_op"] is True
    assert _read_pointer(tmp_path)["factory_run_id"] == handle.factory_run_id
    resolved = resolve_committed_v2_generation(
        tmp_path, expected_factory_run_id=handle.factory_run_id
    )
    assert resolved["factory_report_sha256"] == _read_pointer(tmp_path)[
        "factory_report_sha256"
    ]


def test_complete_generation_based_on_old_pointer_cannot_recover_when_pointer_is_missing(
    tmp_path, monkeypatch
):
    old = _complete_staging(tmp_path, factory_run_id=_factory_id("missing-base-old"))
    publish_v2_generation(old)
    pending = _complete_staging(
        tmp_path, factory_run_id=_factory_id("missing-base-pending")
    )
    original_atomic = publication._atomic_json

    def crash_before_pointer(path, payload):
        if (
            path == pending.factory_root / "latest.json"
            and payload.get("factory_run_id") == pending.factory_run_id
        ):
            raise OSError("simulated pointer crash")
        original_atomic(path, payload)

    monkeypatch.setattr(publication, "_atomic_json", crash_before_pointer)
    with pytest.raises(OSError, match="simulated pointer crash"):
        publish_v2_generation(pending)
    monkeypatch.setattr(publication, "_atomic_json", original_atomic)
    (pending.factory_root / "latest.json").unlink()

    with pytest.raises(F4V2PublicationError, match="f4_v2_pointer_conflict"):
        publish_v2_generation(
            begin_v2_publication(tmp_path, factory_run_id=pending.factory_run_id)
        )

    assert not (pending.factory_root / "latest.json").exists()


def test_same_generation_pointer_hash_tampering_blocks_no_op(tmp_path):
    handle = _complete_staging(tmp_path)
    publish_v2_generation(handle)
    retry = begin_v2_publication(tmp_path, factory_run_id=handle.factory_run_id)
    pointer_path = handle.factory_root / "latest.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["factory_report_sha256"] = "0" * 64
    _write(pointer_path, pointer)

    with pytest.raises(F4V2PublicationError, match="f4_v2_pointer_integrity_failed"):
        publish_v2_generation(retry)


def test_old_complete_generation_retry_cannot_replace_newer_complete_pointer(tmp_path):
    old = _complete_staging(tmp_path, factory_run_id=_factory_id("complete-old"))
    publish_v2_generation(old)
    newer = _complete_staging(tmp_path, factory_run_id=_factory_id("complete-newer"))
    publish_v2_generation(newer)
    pointer_before = _read_pointer(tmp_path)

    retry = begin_v2_publication(tmp_path, factory_run_id=old.factory_run_id)
    with pytest.raises(F4V2PublicationError, match="f4_v2_pointer_conflict"):
        publish_v2_generation(retry)

    assert _read_pointer(tmp_path) == pointer_before


def test_compatibility_failure_after_authoritative_commit_is_reported_not_rolled_back(tmp_path):
    handle = _complete_staging(tmp_path)

    def fail_compatibility(_path, _payload):
        raise OSError("compatibility mirror locked")

    result = publish_v2_generation(
        handle,
        compatibility_projection={"status": "f4_rejected_exhausted"},
        compatibility_writer=fail_compatibility,
    )

    assert result["publication_state"] == "committed"
    assert result["compatibility_projection_state"] == "failed"
    assert "compatibility mirror locked" in result["compatibility_projection_error"]
    assert _read_pointer(tmp_path)["factory_run_id"] == handle.factory_run_id
    assert handle.final_dir.is_dir()
    assert not (tmp_path / "data" / "research" / "f4" / "latest.json").exists()


def test_stale_attempt_cannot_replace_newer_pointer_or_change_committed_state(tmp_path):
    stale = _complete_staging(tmp_path, factory_run_id=_factory_id("stale"))
    newer = _complete_staging(tmp_path, factory_run_id=_factory_id("newer"))
    committed = publish_v2_generation(newer)

    with pytest.raises(F4V2PublicationError, match="f4_v2_attempt_stale"):
        publish_v2_generation(stale)

    assert _read_pointer(tmp_path)["factory_run_id"] == committed["factory_run_id"]
    assert not stale.final_dir.exists()


def test_handle_paths_must_be_contained_in_factory_root(tmp_path):
    handle = _complete_staging(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    escaped = F4V2PublicationHandle(
        project_root=handle.project_root,
        f4_root=handle.f4_root,
        factory_root=handle.factory_root,
        factory_run_id=handle.factory_run_id,
        attempt_id=handle.attempt_id,
        staging_dir=outside,
        final_dir=handle.final_dir,
        expected_latest_factory_run_id=handle.expected_latest_factory_run_id,
        expected_latest_pointer_sha256=handle.expected_latest_pointer_sha256,
    )

    with pytest.raises(F4V2PublicationError, match="f4_v2_publication_path_invalid"):
        publish_v2_generation(escaped)
    assert outside.is_dir()


def test_final_commit_after_old_pointer_recovers_only_when_base_pointer_is_unchanged(
    tmp_path, monkeypatch
):
    old = _complete_staging(tmp_path, factory_run_id=_factory_id("crash-old"))
    publish_v2_generation(old)
    pending = _complete_staging(tmp_path, factory_run_id=_factory_id("crash-pending"))
    old_pointer = _read_pointer(tmp_path)
    original_atomic = publication._atomic_json

    def crash_before_pointer(path, payload):
        if (
            path == pending.factory_root / "latest.json"
            and payload.get("factory_run_id") == pending.factory_run_id
        ):
            raise OSError("simulated pointer crash")
        original_atomic(path, payload)

    monkeypatch.setattr(publication, "_atomic_json", crash_before_pointer)
    with pytest.raises(OSError, match="simulated pointer crash"):
        publish_v2_generation(pending)
    assert pending.final_dir.is_dir()
    assert _read_pointer(tmp_path) == old_pointer

    monkeypatch.setattr(publication, "_atomic_json", original_atomic)
    recovered = publish_v2_generation(
        begin_v2_publication(tmp_path, factory_run_id=pending.factory_run_id)
    )
    assert recovered["publication_recovered"] is True
    assert _read_pointer(tmp_path)["factory_run_id"] == pending.factory_run_id


def test_old_pending_final_cannot_recover_after_intermediate_generation_commits(
    tmp_path, monkeypatch
):
    old = _complete_staging(tmp_path, factory_run_id=_factory_id("race-old"))
    publish_v2_generation(old)
    pending = _complete_staging(tmp_path, factory_run_id=_factory_id("race-pending"))
    original_atomic = publication._atomic_json

    def crash_before_pointer(path, payload):
        if (
            path == pending.factory_root / "latest.json"
            and payload.get("factory_run_id") == pending.factory_run_id
        ):
            raise OSError("simulated pointer crash")
        original_atomic(path, payload)

    monkeypatch.setattr(publication, "_atomic_json", crash_before_pointer)
    with pytest.raises(OSError):
        publish_v2_generation(pending)
    monkeypatch.setattr(publication, "_atomic_json", original_atomic)

    newer = _complete_staging(tmp_path, factory_run_id=_factory_id("race-newer"))
    publish_v2_generation(newer)
    pointer_before = _read_pointer(tmp_path)
    with pytest.raises(F4V2PublicationError, match="f4_v2_pointer_conflict"):
        publish_v2_generation(
            begin_v2_publication(tmp_path, factory_run_id=pending.factory_run_id)
        )
    assert _read_pointer(tmp_path) == pointer_before


def test_compatibility_projection_uses_authoritative_pointer_cas(tmp_path):
    old = _complete_staging(tmp_path, factory_run_id=_factory_id("cas-old"))
    publish_v2_generation(old)
    old_pointer = _read_pointer(tmp_path)
    newer = _complete_staging(tmp_path, factory_run_id=_factory_id("cas-newer"))
    publish_v2_generation(newer)

    result = write_v2_compatibility_projection(
        tmp_path,
        expected_factory_run_id=old.factory_run_id,
        expected_factory_report_sha256=old_pointer["factory_report_sha256"],
        projection={"status": "f4_rejected"},
    )

    assert result["compatibility_projection_state"] == "projection_conflict"
    assert not (old.f4_root / "latest.json").exists()
    assert _read_pointer(tmp_path)["factory_run_id"] == newer.factory_run_id


def test_same_identity_no_op_retries_failed_compatibility_projection(tmp_path):
    handle = _complete_staging(tmp_path, factory_run_id=_factory_id("compat-retry"))

    def fail_writer(_path, _payload):
        raise OSError("compat locked")

    first = publish_v2_generation(
        handle,
        compatibility_projection={"status": "f4_rejected"},
        compatibility_writer=fail_writer,
    )
    assert first["compatibility_projection_state"] == "failed"

    second = publish_v2_generation(
        begin_v2_publication(tmp_path, factory_run_id=handle.factory_run_id),
        compatibility_projection={"status": "f4_rejected"},
    )
    assert second["publication_no_op"] is True
    assert second["compatibility_projection_state"] == "completed"
    assert json.loads((handle.f4_root / "latest.json").read_text())["factory_run_id"] == handle.factory_run_id


def test_arbitrary_sha256_shaped_factory_id_is_rejected(tmp_path):
    forged = _complete_staging(tmp_path, factory_run_id="d" * 64)
    with pytest.raises(F4V2PublicationError, match="f4_v2_factory_identity_invalid"):
        publish_v2_generation(forged)

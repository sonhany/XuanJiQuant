"""Strict, atomic publication boundary for research-only F4 v2 evidence."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import threading
import time
import uuid
from collections import Counter
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from .f4_alpha_contracts import build_v2_candidate_registry
from .f4_candidate_factory import (
    canonical_payload_hash,
    candidate_factory_id,
    candidate_registry_hash,
)


REQUIRED_V2_ARTIFACTS = (
    "registry.json",
    "window_definitions.json",
    "alpha_fits.json",
    "model_artifacts.json",
    "validation_leaderboards.json",
    "candidate_selection_locks.json",
    "test_window_metrics.json",
    "cost_stress_metrics.json",
    "family_diagnostics.json",
    "factory_report.json",
)
_CHILD_ARTIFACTS = REQUIRED_V2_ARTIFACTS[:-1]
_FACTORY_VERSION = "f4-multi-alpha-candidate-factory-v2"
_AUTHORITY = {"promotion_state": "research_only", "execution_authority": False}
_FACTORY_ID = re.compile(r"^[0-9a-f]{64}$")
_ATTEMPT_ID = re.compile(r"^[0-9a-f]{32}$")
_LOCK_HASH_EXCLUDED = frozenset(
    {"lock_hash", "promotion_state", "execution_authority"}
)
_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


class F4V2PublicationError(RuntimeError):
    """Fail-closed publication error with a stable reason-code prefix."""


@dataclass(frozen=True, slots=True)
class F4V2PublicationHandle:
    project_root: Path
    f4_root: Path
    factory_root: Path
    factory_run_id: str
    attempt_id: str
    staging_dir: Path
    final_dir: Path
    expected_latest_factory_run_id: str | None
    expected_latest_pointer_sha256: str | None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _json_object(path: Path, reason_code: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), parse_constant=_reject_constant
        )
    except (OSError, TypeError, ValueError) as exc:
        raise F4V2PublicationError(f"{reason_code}:{path.name}") from exc
    if type(value) is not dict:
        raise F4V2PublicationError(f"{reason_code}:{path.name}")
    _validate_finite(value, path.name)
    return value


def _validate_finite(value: Any, location: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise F4V2PublicationError(f"f4_v2_json_nonfinite:{location}")
    if isinstance(value, Mapping):
        for key, item in value.items():
            _validate_finite(item, f"{location}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_finite(item, f"{location}[{index}]")


def _validate_authority(payload: Mapping[str, Any], name: str) -> None:
    if any(payload.get(key) != value for key, value in _AUTHORITY.items()):
        raise F4V2PublicationError(f"f4_v2_authority_invalid:{name}")


def _validate_nested_authority(value: Any, location: str) -> None:
    if isinstance(value, Mapping):
        if any(key in value for key in _AUTHORITY) and any(
            value.get(key) != expected for key, expected in _AUTHORITY.items()
        ):
            raise F4V2PublicationError(f"f4_v2_authority_invalid:{location}")
        for key, item in value.items():
            _validate_nested_authority(item, f"{location}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_nested_authority(item, f"{location}[{index}]")


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    encoded = json.dumps(
        dict(payload), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
    ).encode("utf-8")
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        with suppress(OSError):
            temporary.unlink()


def _thread_lock(root: Path) -> threading.Lock:
    key = str(root.resolve()).casefold()
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.Lock())


@contextmanager
def _publication_lock(factory_root: Path):
    root = factory_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".publication.lock"
    with _thread_lock(root):
        with lock_path.open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                deadline = time.monotonic() + 120.0
                while True:
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise F4V2PublicationError("f4_v2_publication_lock_timeout")
                        time.sleep(0.05)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _latest_factory_run_id(factory_root: Path) -> str | None:
    pointer = factory_root / "latest.json"
    if not pointer.is_file():
        return None
    return str(_resolve_pointer_unlocked(factory_root)["factory_run_id"])


def _latest_pointer_identity(factory_root: Path) -> tuple[str | None, str | None]:
    pointer_path = factory_root / "latest.json"
    if not pointer_path.is_file():
        return None, None
    resolved = _resolve_pointer_unlocked(factory_root)
    return str(resolved["factory_run_id"]), _sha256(pointer_path)


def _resolve_pointer_unlocked(
    factory_root: Path,
    *,
    expected_factory_run_id: str | None = None,
) -> dict[str, Any]:
    pointer_path = factory_root / "latest.json"
    if not pointer_path.is_file():
        raise F4V2PublicationError("f4_v2_pointer_missing")
    try:
        pointer = _json_object(pointer_path, "f4_v2_pointer_integrity_failed")
        _validate_authority(pointer, "latest.json")
        run_id = str(pointer.get("factory_run_id") or "")
        if (
            not _FACTORY_ID.fullmatch(run_id)
            or pointer.get("schema_version") != "f4-v2-publication-pointer-v1"
            or pointer.get("factory_version") != _FACTORY_VERSION
            or pointer.get("generation_path") != f"factory-v2/{run_id}"
        ):
            raise F4V2PublicationError("f4_v2_pointer_integrity_failed")
        if expected_factory_run_id is not None and run_id != expected_factory_run_id:
            raise F4V2PublicationError("f4_v2_pointer_conflict")
        final_dir = factory_root / run_id
        artifacts = _validate_artifacts(final_dir, run_id)
        report_hash = _sha256(final_dir / "factory_report.json")
        report = artifacts["factory_report.json"]
        if (
            pointer.get("factory_report_sha256") != report_hash
            or pointer.get("candidate_registry_hash")
            != report.get("candidate_registry_hash")
        ):
            raise F4V2PublicationError("f4_v2_pointer_integrity_failed")
    except F4V2PublicationError as exc:
        if str(exc) == "f4_v2_pointer_conflict":
            raise
        if str(exc).startswith("f4_v2_pointer_integrity_failed"):
            raise
        raise F4V2PublicationError(
            f"f4_v2_pointer_integrity_failed:{exc}"
        ) from exc
    return {
        **pointer,
        "generation_dir": str(final_dir.resolve()),
        "factory_report": report,
    }


def resolve_committed_v2_generation(
    project_root: Path | str,
    *,
    expected_factory_run_id: str | None = None,
) -> dict[str, Any]:
    """Resolve the authoritative pointer and revalidate its complete generation."""

    root = Path(project_root).resolve()
    factory_root = (
        root / "data" / "research" / "f4" / "factory-v2"
    ).resolve()
    with _publication_lock(factory_root):
        return _resolve_pointer_unlocked(
            factory_root,
            expected_factory_run_id=expected_factory_run_id,
        )


def resolve_committed_v2_candidate_evidence(
    project_root: Path | str,
    *,
    expected_factory_run_id: str | None = None,
) -> dict[str, Any]:
    """Resolve the candidate contract without revalidating large test metrics."""

    root = Path(project_root).resolve()
    factory_root = (
        root / "data" / "research" / "f4" / "factory-v2"
    ).resolve()
    with _publication_lock(factory_root):
        pointer_path = factory_root / "latest.json"
        pointer = _json_object(
            pointer_path, "f4_v2_pointer_integrity_failed"
        )
        _validate_authority(pointer, "latest.json")
        run_id = str(pointer.get("factory_run_id") or "")
        if (
            not _FACTORY_ID.fullmatch(run_id)
            or pointer.get("schema_version")
            != "f4-v2-publication-pointer-v1"
            or pointer.get("factory_version") != _FACTORY_VERSION
            or pointer.get("generation_path") != f"factory-v2/{run_id}"
            or (
                expected_factory_run_id is not None
                and run_id != expected_factory_run_id
            )
        ):
            raise F4V2PublicationError("f4_v2_pointer_integrity_failed")
        generation_dir = (factory_root / run_id).resolve()
        try:
            generation_dir.relative_to(factory_root)
        except ValueError as exc:
            raise F4V2PublicationError(
                "f4_v2_pointer_integrity_failed"
            ) from exc
        report_path = generation_dir / "factory_report.json"
        if _sha256(report_path) != pointer.get("factory_report_sha256"):
            raise F4V2PublicationError("f4_v2_pointer_integrity_failed")
        report = _json_object(report_path, "f4_v2_factory_report_invalid")
        _validate_authority(report, "factory_report.json")
        pipeline = report.get("pipeline_result")
        candidate_spec = (
            dict(pipeline.get("candidate_spec") or {})
            if isinstance(pipeline, dict)
            else {}
        )
        if (
            report.get("factory_run_id") != run_id
            or report.get("factory_version") != _FACTORY_VERSION
            or report.get("candidate_registry_hash")
            != pointer.get("candidate_registry_hash")
            or not isinstance(pipeline, dict)
            or report.get("pipeline_result_sha256")
            != canonical_payload_hash(pipeline)
            or candidate_spec.get("version") != _FACTORY_VERSION
            or candidate_spec.get("factory_run_id") != run_id
            or candidate_spec.get("promotion_state") != "research_only"
            or candidate_spec.get("execution_authority") is not False
        ):
            raise F4V2PublicationError("f4_v2_candidate_evidence_invalid")
        _validate_nested_authority(candidate_spec, "candidate_spec")
        model_path = generation_dir / "model_artifacts.json"
        declared_hashes = report.get("artifact_hashes")
        if (
            not isinstance(declared_hashes, dict)
            or declared_hashes.get("model_artifacts.json")
            != _sha256(model_path)
        ):
            raise F4V2PublicationError("f4_v2_model_artifact_hash_invalid")
        model_payload = _json_object(
            model_path, "f4_v2_model_artifact_invalid"
        )
        _validate_authority(model_payload, "model_artifacts.json")
        models = model_payload.get("models")
        if (
            model_payload.get("factory_run_id") != run_id
            or not isinstance(models, list)
        ):
            raise F4V2PublicationError("f4_v2_model_artifact_invalid")
        return {
            **pointer,
            "generation_dir": str(generation_dir),
            "candidate_spec": candidate_spec,
            "model_artifacts": list(models),
        }


def begin_v2_publication(
    project_root: Path | str, *, factory_run_id: str
) -> F4V2PublicationHandle:
    root = Path(project_root).resolve()
    run_id = str(factory_run_id)
    if not _FACTORY_ID.fullmatch(run_id):
        raise F4V2PublicationError("f4_v2_factory_identity_invalid")
    f4_root = (root / "data" / "research" / "f4").resolve()
    factory_root = (f4_root / "factory-v2").resolve()
    with _publication_lock(factory_root):
        expected, expected_pointer_hash = _latest_pointer_identity(factory_root)
        attempt_id = uuid.uuid4().hex
        staging = factory_root / f".{run_id}.{attempt_id}.tmp"
        staging.mkdir(parents=False, exist_ok=False)
    return F4V2PublicationHandle(
        project_root=root,
        f4_root=f4_root,
        factory_root=factory_root,
        factory_run_id=run_id,
        attempt_id=attempt_id,
        staging_dir=staging,
        final_dir=factory_root / run_id,
        expected_latest_factory_run_id=expected,
        expected_latest_pointer_sha256=expected_pointer_hash,
    )


def publication_base_pointer(handle: F4V2PublicationHandle) -> dict[str, Any]:
    """Identity of the authoritative pointer observed before this attempt."""

    return {
        "factory_run_id": handle.expected_latest_factory_run_id,
        "pointer_sha256": handle.expected_latest_pointer_sha256,
    }


def write_v2_staging_artifact(
    handle: F4V2PublicationHandle,
    name: str,
    payload: Mapping[str, Any],
) -> Path:
    """Write one governed artifact inside its owned staging attempt."""

    _validate_handle(handle)
    if name not in REQUIRED_V2_ARTIFACTS or not handle.staging_dir.is_dir():
        raise F4V2PublicationError("f4_v2_staging_artifact_invalid")
    target = handle.staging_dir / name
    _atomic_json(target, payload)
    return target


def _validate_handle(handle: F4V2PublicationHandle) -> None:
    project_root = Path(handle.project_root).resolve()
    expected_f4 = (project_root / "data" / "research" / "f4").resolve()
    expected_factory = (expected_f4 / "factory-v2").resolve()
    if (
        handle.f4_root.resolve() != expected_f4
        or handle.factory_root.resolve() != expected_factory
        or not _FACTORY_ID.fullmatch(str(handle.factory_run_id))
        or not _ATTEMPT_ID.fullmatch(str(handle.attempt_id))
        or handle.staging_dir.resolve()
        != (
            expected_factory
            / f".{handle.factory_run_id}.{handle.attempt_id}.tmp"
        ).resolve()
        or handle.final_dir.resolve()
        != (expected_factory / handle.factory_run_id).resolve()
        or (
            (handle.expected_latest_factory_run_id is None)
            != (handle.expected_latest_pointer_sha256 is None)
        )
    ):
        raise F4V2PublicationError("f4_v2_publication_path_invalid")
    try:
        handle.staging_dir.resolve().relative_to(expected_factory)
        handle.final_dir.resolve().relative_to(expected_factory)
    except ValueError as exc:
        raise F4V2PublicationError("f4_v2_publication_path_invalid") from exc


def _verify_file_path(
    raw_path: Any, *, expected_root: Path, expected_hash: Any, reason: str
) -> Path:
    path = Path(str(raw_path or "")).resolve()
    try:
        path.relative_to(expected_root.resolve())
    except ValueError as exc:
        raise F4V2PublicationError(f"{reason}:path") from exc
    if (
        type(expected_hash) is not str
        or len(expected_hash) != 64
        or not path.is_file()
        or _sha256(path) != expected_hash
    ):
        raise F4V2PublicationError(reason)
    return path


def _verify_semantic_fit(path: Path, semantic_hash: Any) -> None:
    if type(semantic_hash) is not str or not semantic_hash:
        raise F4V2PublicationError("f4_v2_alpha_fit_hash_invalid")
    if _sha256(path) == semantic_hash:
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        raise F4V2PublicationError("f4_v2_alpha_fit_hash_invalid") from exc
    if type(payload) is not dict or semantic_hash not in {
        payload.get("artifact_hash"),
        payload.get("config_hash"),
        payload.get("alpha_fit_hash"),
    }:
        raise F4V2PublicationError("f4_v2_alpha_fit_hash_invalid")


def _validate_registry(payload: Mapping[str, Any], factory_run_id: str) -> tuple[list[dict[str, Any]], str]:
    if (
        payload.get("factory_run_id") != factory_run_id
        or payload.get("factory_version") != _FACTORY_VERSION
        or payload.get("candidate_count") != 24
        or type(payload.get("candidates")) is not list
    ):
        raise F4V2PublicationError("f4_v2_registry_invalid")
    candidates = list(payload["candidates"])
    expected_registry = build_v2_candidate_registry()
    expected_payloads = json.loads(
        json.dumps(
            [candidate.to_dict() for candidate in expected_registry],
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if candidates != expected_payloads:
        raise F4V2PublicationError("f4_v2_candidate_hash_invalid")
    ids = [str(candidate.get("candidate_id") or "") for candidate in candidates]
    if len(set(ids)) != 24 or Counter(candidate.get("family") for candidate in candidates) != {
        "momentum": 4,
        "reversal": 4,
        "defensive": 4,
        "liquidity": 4,
        "ensemble": 4,
        "qlib": 4,
    }:
        raise F4V2PublicationError("f4_v2_registry_invalid")
    expected_hash = candidate_registry_hash(expected_registry)
    if payload.get("candidate_registry_hash") != expected_hash:
        raise F4V2PublicationError("f4_v2_registry_hash_invalid")
    input_identity = payload.get("input_identity")
    if type(input_identity) is not dict:
        raise F4V2PublicationError("f4_v2_factory_identity_invalid")
    try:
        recomputed_run_id = candidate_factory_id(input_identity, expected_registry)
    except (TypeError, ValueError) as exc:
        raise F4V2PublicationError("f4_v2_factory_identity_invalid") from exc
    if recomputed_run_id != factory_run_id:
        raise F4V2PublicationError("f4_v2_factory_identity_invalid")
    return candidates, expected_hash


def _validate_artifacts(directory: Path, factory_run_id: str) -> dict[str, dict[str, Any]]:
    if not directory.is_dir():
        raise F4V2PublicationError("f4_v2_staging_missing")
    actual = {path.name for path in directory.iterdir() if path.is_file()}
    required = set(REQUIRED_V2_ARTIFACTS)
    missing = required - actual
    if missing:
        raise F4V2PublicationError(
            f"f4_v2_artifact_missing:{sorted(missing)[0]}"
        )
    if actual != required or any(path.is_dir() for path in directory.iterdir()):
        raise F4V2PublicationError("f4_v2_artifact_set_invalid")

    artifacts = {
        name: _json_object(directory / name, "f4_v2_artifact_json_invalid")
        for name in REQUIRED_V2_ARTIFACTS
    }
    for name, payload in artifacts.items():
        _validate_authority(payload, name)
        _validate_nested_authority(payload, name)
        if payload.get("factory_run_id") != factory_run_id:
            raise F4V2PublicationError(f"f4_v2_artifact_identity_mismatch:{name}")

    registry_payload = artifacts["registry.json"]
    candidates, registry_hash = _validate_registry(registry_payload, factory_run_id)
    by_id = {candidate["candidate_id"]: candidate for candidate in candidates}

    report = artifacts["factory_report.json"]
    base_pointer = report.get("publication_base_pointer")
    if (
        report.get("factory_version") != _FACTORY_VERSION
        or report.get("candidate_registry_hash") != registry_hash
        or report.get("candidate_count") != 24
        or report.get("family_count") != 6
        or report.get("input_identity") != registry_payload.get("input_identity")
        or type(report.get("runtime_seconds")) not in {int, float}
        or float(report["runtime_seconds"]) < 0.0
        or not str(report.get("gate_version") or "")
        or type(report.get("failure_reasons")) is not list
        or type(report.get("aggregate_metrics")) is not dict
        or type(report.get("family_status")) is not dict
        or type(base_pointer) is not dict
        or set(base_pointer) != {"factory_run_id", "pointer_sha256"}
        or ((base_pointer.get("factory_run_id") is None) != (base_pointer.get("pointer_sha256") is None))
        or (
            base_pointer.get("factory_run_id") is not None
            and (
                not _FACTORY_ID.fullmatch(str(base_pointer.get("factory_run_id")))
                or not re.fullmatch(r"[0-9a-f]{64}", str(base_pointer.get("pointer_sha256")))
            )
        )
    ):
        raise F4V2PublicationError("f4_v2_factory_report_invalid")
    declared_hashes = report.get("artifact_hashes")
    if type(declared_hashes) is not dict or set(declared_hashes) != set(_CHILD_ARTIFACTS):
        raise F4V2PublicationError("f4_v2_artifact_hash_set_invalid")
    for name in _CHILD_ARTIFACTS:
        if declared_hashes.get(name) != _sha256(directory / name):
            raise F4V2PublicationError(f"f4_v2_artifact_hash_mismatch:{name}")

    leaderboards = artifacts["validation_leaderboards.json"].get("leaderboards")
    locks = artifacts["candidate_selection_locks.json"].get("locks")
    tests = artifacts["test_window_metrics.json"].get("windows")
    fits = artifacts["alpha_fits.json"].get("fits")
    models = artifacts["model_artifacts.json"].get("models")
    if any(type(value) is not list for value in (leaderboards, locks, tests, fits, models)):
        raise F4V2PublicationError("f4_v2_evidence_schema_invalid")

    def unique_by_window(rows: list[dict[str, Any]], reason: str) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            if type(row) is not dict:
                raise F4V2PublicationError(reason)
            window_id = str(row.get("window_id") or "")
            if not window_id or window_id in result:
                raise F4V2PublicationError(reason)
            result[window_id] = row
        return result

    leaderboard_by_window = unique_by_window(leaderboards, "f4_v2_leaderboard_invalid")
    lock_by_window = unique_by_window(locks, "f4_v2_lock_invalid")
    test_by_window = unique_by_window(tests, "f4_v2_test_without_lock")
    fit_by_window = unique_by_window(fits, "f4_v2_alpha_fit_invalid")
    model_by_window = unique_by_window(models, "f4_v2_model_artifact_invalid")
    if set(lock_by_window) != set(test_by_window):
        raise F4V2PublicationError("f4_v2_test_without_lock")
    if set(lock_by_window) != set(fit_by_window):
        raise F4V2PublicationError("f4_v2_alpha_fit_lock_mismatch")

    locked_root = directory.parent / "locked-artifacts" / factory_run_id
    lock_root = directory.parent / "locks" / factory_run_id
    expected_model_windows: set[str] = set()
    for window_id, lock in lock_by_window.items():
        _validate_authority(lock, f"lock:{window_id}")
        candidate_id = str(lock.get("candidate_id") or "")
        candidate = by_id.get(candidate_id)
        if candidate is None:
            raise F4V2PublicationError("f4_v2_lock_candidate_invalid")
        lock_core = {
            key: value
            for key, value in lock.items()
            if key not in _LOCK_HASH_EXCLUDED
        }
        if (
            lock.get("factory_run_id") != factory_run_id
            or lock.get("candidate_registry_hash") != registry_hash
            or lock.get("candidate_count") != 24
            or lock.get("selection_scope") != "current_window_validation_only"
            or lock.get("test_scope") != "locked_winner_only"
            or lock.get("lock_hash") != canonical_payload_hash(lock_core)
            or lock.get("alpha_spec_hash")
            != canonical_payload_hash(candidate["alpha_spec"])
            or lock.get("portfolio_policy_hash")
            != canonical_payload_hash(candidate["portfolio_policy"])
        ):
            raise F4V2PublicationError("f4_v2_lock_hash_invalid")

        window_artifact_root = locked_root / window_id
        fit_path = _verify_file_path(
            lock.get("alpha_fit_path"),
            expected_root=window_artifact_root,
            expected_hash=lock.get("alpha_fit_artifact_hash"),
            reason="f4_v2_alpha_fit_artifact_hash_invalid",
        )
        _verify_semantic_fit(fit_path, lock.get("alpha_fit_hash"))
        _verify_file_path(
            lock.get("validation_score_path"),
            expected_root=window_artifact_root,
            expected_hash=lock.get("validation_score_hash"),
            reason="f4_v2_validation_score_hash_invalid",
        )
        leaderboard_path = _verify_file_path(
            lock.get("validation_leaderboard_path"),
            expected_root=lock_root,
            expected_hash=lock.get("validation_leaderboard_hash"),
            reason="f4_v2_validation_leaderboard_hash_invalid",
        )
        stable_leaderboard = _json_object(
            leaderboard_path, "f4_v2_validation_leaderboard_invalid"
        )
        published_leaderboard = leaderboard_by_window.get(window_id)
        selected = [
            row
            for row in (stable_leaderboard.get("candidates") or [])
            if isinstance(row, dict) and row.get("selected") is True
        ]
        if (
            published_leaderboard != stable_leaderboard
            or len(selected) != 1
            or selected[0].get("candidate_id") != candidate_id
        ):
            raise F4V2PublicationError("f4_v2_validation_leaderboard_invalid")

        fit = fit_by_window[window_id]
        for field in (
            "candidate_id",
            "alpha_spec_hash",
            "alpha_fit_path",
            "alpha_fit_hash",
            "alpha_fit_artifact_hash",
        ):
            if fit.get(field) != lock.get(field):
                raise F4V2PublicationError("f4_v2_alpha_fit_lock_mismatch")

        test = test_by_window[window_id]
        _validate_authority(test, f"test:{window_id}")
        if test.get("candidate_id") != candidate_id:
            raise F4V2PublicationError("f4_v2_test_without_lock")

        model_path = lock.get("model_artifact_path")
        model_hash = lock.get("model_artifact_hash")
        if (model_path is None) != (model_hash is None):
            raise F4V2PublicationError("f4_v2_model_artifact_invalid")
        if model_path is not None:
            expected_model_windows.add(window_id)
            _verify_file_path(
                model_path,
                expected_root=window_artifact_root,
                expected_hash=model_hash,
                reason="f4_v2_model_artifact_hash_invalid",
            )
            model = model_by_window.get(window_id)
            if (
                model is None
                or model.get("candidate_id") != candidate_id
                or model.get("model_artifact_path") != model_path
                or model.get("model_artifact_hash") != model_hash
            ):
                raise F4V2PublicationError("f4_v2_model_artifact_lock_mismatch")
    if set(model_by_window) != expected_model_windows:
        raise F4V2PublicationError("f4_v2_model_artifact_lock_mismatch")
    return artifacts


def _validate_final(handle: F4V2PublicationHandle) -> dict[str, dict[str, Any]]:
    try:
        return _validate_artifacts(handle.final_dir, handle.factory_run_id)
    except F4V2PublicationError as exc:
        raise F4V2PublicationError(
            f"f4_v2_final_integrity_failed:{exc}"
        ) from exc


def _pointer_payload(handle: F4V2PublicationHandle, artifacts: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    report = artifacts["factory_report.json"]
    return {
        "schema_version": "f4-v2-publication-pointer-v1",
        "factory_run_id": handle.factory_run_id,
        "factory_version": _FACTORY_VERSION,
        "generation_path": f"factory-v2/{handle.factory_run_id}",
        "factory_report_sha256": _sha256(handle.final_dir / "factory_report.json"),
        "candidate_registry_hash": report["candidate_registry_hash"],
        "published_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        **_AUTHORITY,
    }


def write_v2_compatibility_projection(
    project_root: Path | str,
    *,
    expected_factory_run_id: str,
    expected_factory_report_sha256: str,
    projection: Mapping[str, Any],
    writer: Callable[[Path, Mapping[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """CAS-write the legacy projection while holding the v2 publication lock."""

    root = Path(project_root).resolve()
    f4_root = (root / "data" / "research" / "f4").resolve()
    factory_root = (f4_root / "factory-v2").resolve()
    with _publication_lock(factory_root):
        try:
            resolved = _resolve_pointer_unlocked(
                factory_root,
                expected_factory_run_id=expected_factory_run_id,
            )
        except F4V2PublicationError as exc:
            if str(exc) in {"f4_v2_pointer_conflict", "f4_v2_pointer_missing"}:
                return {
                    "compatibility_projection_state": "projection_conflict",
                    "compatibility_projection_error": str(exc),
                }
            return {
                "compatibility_projection_state": "failed",
                "compatibility_projection_error": str(exc),
            }
        if resolved.get("factory_report_sha256") != expected_factory_report_sha256:
            return {
                "compatibility_projection_state": "projection_conflict",
                "compatibility_projection_error": "f4_v2_report_identity_conflict",
            }
        compatibility_path = f4_root / "latest.json"
        compatibility_payload = {
            **dict(projection),
            "factory_run_id": expected_factory_run_id,
            "factory_v2_artifact_path": str(
                Path(str(resolved["generation_dir"])) / "factory_report.json"
            ),
            **_AUTHORITY,
        }
        _validate_finite(compatibility_payload, "compatibility_projection")
        active_writer = writer or _atomic_json
        try:
            active_writer(compatibility_path, compatibility_payload)
        except Exception as exc:
            return {
                "compatibility_projection_state": "failed",
                "compatibility_projection_error": str(exc),
            }
        return {
            "compatibility_projection_state": "completed",
            "compatibility_projection_path": str(compatibility_path.resolve()),
        }


def publish_v2_generation(
    handle: F4V2PublicationHandle,
    *,
    compatibility_projection: Mapping[str, Any] | None = None,
    compatibility_writer: Callable[[Path, Mapping[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Validate and commit one immutable v2 generation, then mirror compatibility."""

    _validate_handle(handle)
    with _publication_lock(handle.factory_root):
        if handle.final_dir.exists():
            artifacts = _validate_final(handle)
            pointer_path = handle.factory_root / "latest.json"
            recovered = False
            base = artifacts["factory_report.json"]["publication_base_pointer"]
            if pointer_path.is_file():
                current = _resolve_pointer_unlocked(handle.factory_root)
                if current["factory_run_id"] != handle.factory_run_id:
                    current_hash = _sha256(pointer_path)
                    if (
                        base.get("factory_run_id") != current["factory_run_id"]
                        or base.get("pointer_sha256") != current_hash
                    ):
                        raise F4V2PublicationError("f4_v2_pointer_conflict")
                    _atomic_json(pointer_path, _pointer_payload(handle, artifacts))
                    _resolve_pointer_unlocked(
                        handle.factory_root,
                        expected_factory_run_id=handle.factory_run_id,
                    )
                    recovered = True
            else:
                if (
                    base.get("factory_run_id") is not None
                    or base.get("pointer_sha256") is not None
                ):
                    raise F4V2PublicationError("f4_v2_pointer_conflict")
                _atomic_json(pointer_path, _pointer_payload(handle, artifacts))
                _resolve_pointer_unlocked(
                    handle.factory_root,
                    expected_factory_run_id=handle.factory_run_id,
                )
                recovered = True
            if handle.staging_dir.is_dir():
                shutil.rmtree(handle.staging_dir)
            result = {
                "factory_run_id": handle.factory_run_id,
                "publication_state": "committed",
                "publication_no_op": True,
                "publication_recovered": recovered,
                "authoritative_pointer": str(
                    (handle.factory_root / "latest.json").resolve()
                ),
                "factory_report": artifacts["factory_report.json"],
                "compatibility_projection_state": "not_requested",
                **_AUTHORITY,
            }
        else:
            current_id, current_pointer_hash = _latest_pointer_identity(
                handle.factory_root
            )
            if (
                current_id != handle.expected_latest_factory_run_id
                or current_pointer_hash != handle.expected_latest_pointer_sha256
            ):
                raise F4V2PublicationError("f4_v2_attempt_stale")
            artifacts = _validate_artifacts(
                handle.staging_dir, handle.factory_run_id
            )
            if artifacts["factory_report.json"].get(
                "publication_base_pointer"
            ) != publication_base_pointer(handle):
                raise F4V2PublicationError("f4_v2_publication_base_mismatch")
            os.replace(handle.staging_dir, handle.final_dir)
            artifacts = _validate_final(handle)
            pointer_path = handle.factory_root / "latest.json"
            pointer = _pointer_payload(handle, artifacts)
            _atomic_json(pointer_path, pointer)
            _resolve_pointer_unlocked(
                handle.factory_root,
                expected_factory_run_id=handle.factory_run_id,
            )
            result = {
                "factory_run_id": handle.factory_run_id,
                "publication_state": "committed",
                "publication_no_op": False,
                "publication_recovered": False,
                "authoritative_pointer": str(pointer_path.resolve()),
                "factory_report": artifacts["factory_report.json"],
                "compatibility_projection_state": "not_requested",
                **_AUTHORITY,
            }
    if compatibility_projection is not None:
        result.update(
            write_v2_compatibility_projection(
                handle.project_root,
                expected_factory_run_id=handle.factory_run_id,
                expected_factory_report_sha256=_sha256(
                    handle.final_dir / "factory_report.json"
                ),
                projection=compatibility_projection,
                writer=compatibility_writer,
            )
        )
    return result


__all__ = [
    "F4V2PublicationError",
    "F4V2PublicationHandle",
    "REQUIRED_V2_ARTIFACTS",
    "begin_v2_publication",
    "publication_base_pointer",
    "publish_v2_generation",
    "resolve_committed_v2_generation",
    "resolve_committed_v2_candidate_evidence",
    "write_v2_staging_artifact",
    "write_v2_compatibility_projection",
]

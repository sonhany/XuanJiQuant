"""Atomic publication boundary for a complete daily research generation.

The public pointer is the only authority for cross-artifact consistency.  A
generation stays invisible until its factor projection, factor evaluation and
research selection all prove the same governed data identity.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import threading
import time
import uuid
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


ARTIFACT_NAMES = (
    "factor_snapshot_latest.json",
    "factor_evaluation.json",
    "selection.json",
)

_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


class PublicationError(RuntimeError):
    """Raised when a research generation cannot be safely published."""


def _replace_file(temporary: Path, target: Path) -> None:
    deadline = time.monotonic() + 2.0
    while True:
        try:
            os.replace(temporary, target)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


@dataclass(frozen=True, slots=True)
class ResearchGeneration:
    root: Path
    generation_id: str
    attempt_id: str
    target_date: str
    snapshot_id: str
    data_version: str
    staging_dir: Path
    final_dir: Path


def _compact_date(value: object) -> str:
    return str(value or "").replace("-", "")[:8]


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    encoded = json.dumps(
        dict(payload), ensure_ascii=False, sort_keys=True, indent=2
    ).encode("utf-8")
    try:
        with temporary.open("wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_file(temporary, path)
    finally:
        with suppress(OSError):
            temporary.unlink()


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    try:
        with temporary.open("wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_file(temporary, path)
    finally:
        with suppress(OSError):
            temporary.unlink()


def _thread_lock(root: Path) -> threading.Lock:
    key = str(root.resolve()).casefold()
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.Lock())


@contextmanager
def _publication_lock(root: Path):
    """Serialize ownership transitions across threads and processes."""
    publication_root = root.resolve()
    publication_root.mkdir(parents=True, exist_ok=True)
    lock_path = publication_root / ".publication.lock"
    with _thread_lock(publication_root):
        with lock_path.open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                deadline = time.monotonic() + 2 * 60 * 60
                while True:
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise PublicationError("publication_lock_timeout")
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _generation_id(target_date: str, snapshot_id: str, data_version: str) -> str:
    payload = json.dumps(
        {
            "schema": "daily-research-generation-v1",
            "target_date": _compact_date(target_date),
            "snapshot_id": str(snapshot_id),
            "data_version": str(data_version),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _last_complete_id(root: Path) -> str | None:
    value = _json_object(root / "latest.json")
    generation_id = str(value.get("generation_id") or "").strip()
    return generation_id or None


def _begin_refresh_unlocked(
    root: Path | str,
    *,
    target_date: str,
    snapshot_id: str,
    data_version: str,
    started_at: str,
) -> ResearchGeneration:
    publication_root = Path(root).resolve()
    compact_date = _compact_date(target_date)
    if len(compact_date) != 8 or not snapshot_id or not data_version:
        raise PublicationError("generation_identity_invalid")
    generation_id = _generation_id(compact_date, snapshot_id, data_version)
    attempt_id = uuid.uuid4().hex
    generations = publication_root / "generations"
    generations.mkdir(parents=True, exist_ok=True)
    generation = ResearchGeneration(
        root=publication_root,
        generation_id=generation_id,
        attempt_id=attempt_id,
        target_date=compact_date,
        snapshot_id=str(snapshot_id),
        data_version=str(data_version),
        staging_dir=generations / f"{generation_id}.{attempt_id}.staging",
        final_dir=generations / generation_id,
    )
    generation.staging_dir.mkdir(parents=True, exist_ok=True)
    _atomic_json(
        publication_root / "status.json",
        {
            "schema_version": "daily-research-publication-status-v1",
            "state": "refreshing",
            "generation_id": generation_id,
            "attempt_id": attempt_id,
            "target_date": compact_date,
            "target_snapshot_id": str(snapshot_id),
            "target_data_version": str(data_version),
            "started_at": str(started_at),
            "finished_at": None,
            "reason_code": None,
            "last_complete_generation_id": _last_complete_id(publication_root),
            "promotion_state": "research_only",
            "execution_authority": False,
        },
    )
    return generation


def begin_refresh(
    root: Path | str,
    *,
    target_date: str,
    snapshot_id: str,
    data_version: str,
    started_at: str,
) -> ResearchGeneration:
    publication_root = Path(root).resolve()
    with _publication_lock(publication_root):
        return _begin_refresh_unlocked(
            publication_root,
            target_date=target_date,
            snapshot_id=snapshot_id,
            data_version=data_version,
            started_at=started_at,
        )


def read_publication_status(root: Path | str) -> dict[str, Any]:
    publication_root = Path(root).resolve()
    status = _json_object(publication_root / "status.json")
    pointer = _json_object(publication_root / "latest.json")
    if (
        status.get("state") == "refreshing"
        and status.get("generation_id")
        and status.get("generation_id") == pointer.get("generation_id")
        and status.get("attempt_id") == pointer.get("attempt_id")
        and pointer.get("published_at")
    ):
        return {
            **status,
            "state": "completed",
            "finished_at": pointer.get("published_at"),
            "reason_code": None,
            "last_complete_generation_id": pointer.get("generation_id"),
            "status_sync_state": "recovered_from_pointer",
        }
    return status


def _mark_refresh_failed_unlocked(
    root: Path | str,
    generation: ResearchGeneration,
    *,
    reason_code: str,
    finished_at: str,
) -> dict[str, Any]:
    publication_root = Path(root).resolve()
    if generation.root != publication_root:
        raise PublicationError("generation_root_mismatch")
    _validate_generation_paths(generation)
    current = read_publication_status(publication_root)
    if (
        current.get("generation_id") != generation.generation_id
        or current.get("attempt_id") != generation.attempt_id
        or current.get("state") != "refreshing"
    ):
        raise PublicationError("generation_attempt_mismatch")
    audit_state = _archive_failed_attempt(
        generation,
        reason_code=str(reason_code or "research_refresh_failed"),
        finished_at=str(finished_at),
    )
    cleanup_state = (
        _safe_cleanup_staging(generation)
        if audit_state == "completed"
        else "retained_for_audit"
    )
    payload = {
        **current,
        "state": "failed",
        "finished_at": str(finished_at),
        "reason_code": str(reason_code or "research_refresh_failed"),
        "last_complete_generation_id": _last_complete_id(publication_root),
        "staging_cleanup_state": cleanup_state,
        "failure_audit_state": audit_state,
        "promotion_state": "research_only",
        "execution_authority": False,
    }
    _atomic_json(publication_root / "status.json", payload)
    return payload


def mark_refresh_failed(
    root: Path | str,
    generation: ResearchGeneration,
    *,
    reason_code: str,
    finished_at: str,
) -> dict[str, Any]:
    publication_root = Path(root).resolve()
    with _publication_lock(publication_root):
        return _mark_refresh_failed_unlocked(
            publication_root,
            generation,
            reason_code=reason_code,
            finished_at=finished_at,
        )


def _validate_authority(payload: Mapping[str, Any], name: str) -> None:
    if (
        payload.get("promotion_state") != "research_only"
        or payload.get("execution_authority") is not False
    ):
        raise PublicationError(f"artifact_authority_invalid:{name}")


def _validate_generation_artifacts(
    directory: Path, generation: ResearchGeneration
) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    for name in ARTIFACT_NAMES:
        path = directory / name
        if not path.is_file():
            raise PublicationError(f"artifact_missing:{name}")
        payload = _json_object(path)
        if not payload:
            raise PublicationError(f"artifact_invalid:{name}")
        _validate_authority(payload, name)
        artifacts[name] = payload

    projection = artifacts["factor_snapshot_latest.json"]
    evaluation = artifacts["factor_evaluation.json"]
    selection = artifacts["selection.json"]
    rows = projection.get("rows")
    if (
        _compact_date(projection.get("as_of") or projection.get("latest_kline_date"))
        != generation.target_date
        or projection.get("snapshot_id") != generation.snapshot_id
        or projection.get("data_version") != generation.data_version
        or not isinstance(rows, list)
        or not rows
        or any(
            not isinstance(row, dict)
            or not str(row.get("code") or "").strip()
            or not isinstance(row.get("factors"), dict)
            for row in rows
        )
    ):
        raise PublicationError("factor_projection_identity_mismatch")
    factors = evaluation.get("factors")
    if (
        _compact_date(evaluation.get("data_end_date")) != generation.target_date
        or evaluation.get("snapshot_id") != generation.snapshot_id
        or evaluation.get("data_version") != generation.data_version
        or not isinstance(factors, list)
        or not factors
        or any(
            not isinstance(factor, dict)
            or not str(factor.get("factor") or "").strip()
            for factor in factors
        )
    ):
        raise PublicationError("factor_evaluation_identity_mismatch")
    positions = selection.get("positions")
    weights: list[float] = []
    invalid_weight = False
    if isinstance(positions, list):
        for position in positions:
            raw_weight = (
                position.get("target_weight", position.get("weight"))
                if isinstance(position, dict)
                else None
            )
            if isinstance(raw_weight, bool):
                invalid_weight = True
            try:
                weight = float(raw_weight)
            except (TypeError, ValueError):
                weight = -1.0
            if not math.isfinite(weight):
                invalid_weight = True
            weights.append(weight)
    projection_codes = [str(row.get("code") or "").strip() for row in rows]
    try:
        projection_n = int(projection.get("n"))
        projection_eligible = int(projection.get("eligible_count"))
        projection_active = int(projection.get("active_count"))
        projection_data = int(projection.get("data_count"))
        evaluation_n = int(evaluation.get("n_stocks"))
        evaluation_eligible = int(evaluation.get("eligible_count"))
        evaluation_active = int(evaluation.get("active_count"))
        evaluation_data = int(evaluation.get("data_count"))
        projection_coverage = float(projection.get("data_coverage"))
    except (TypeError, ValueError):
        raise PublicationError("factor_projection_coverage_mismatch")
    if (
        any(
            isinstance(value, bool)
            for value in (
                projection.get("n"),
                projection.get("eligible_count"),
                projection.get("active_count"),
                projection.get("data_count"),
                evaluation.get("n_stocks"),
                evaluation.get("eligible_count"),
                evaluation.get("active_count"),
                evaluation.get("data_count"),
            )
        )
        or projection_n != len(rows)
        or projection_eligible != len(rows)
        or len(set(projection_codes)) != len(projection_codes)
        or any(_compact_date(row.get("date")) != generation.target_date for row in rows)
        or projection_active <= 0
        or projection_data <= 0
        or projection_data > projection_active
        or not math.isfinite(projection_coverage)
        or abs(projection_coverage - projection_data / projection_active) > 1e-6
        or evaluation_n != len(rows)
        or evaluation_eligible != projection_eligible
        or evaluation_active != projection_active
        or evaluation_data != projection_data
    ):
        raise PublicationError("factor_projection_coverage_mismatch")
    if (
        _compact_date(selection.get("selection_date")) != generation.target_date
        or selection.get("generated_from_snapshot_id") != generation.snapshot_id
        or selection.get("snapshot_data_version") != generation.data_version
        or selection.get("not_a_trade_signal") is not True
        or not str(selection.get("portfolio_id") or "").strip()
        or not isinstance(positions, list)
        or not positions
        or not isinstance(selection.get("position_count"), int)
        or isinstance(selection.get("position_count"), bool)
        or selection.get("position_count") != len(positions)
        or any(
            not isinstance(position, dict)
            or not str(position.get("code") or "").strip()
            for position in positions
        )
        or invalid_weight
        or any(weight < 0.0 or weight > 1.0 for weight in weights)
        or sum(weights) > 1.0 + 1e-9
        or any(str(position.get("code") or "").strip() not in set(projection_codes) for position in positions)
    ):
        raise PublicationError("selection_identity_mismatch")
    return artifacts


def _validate_generation_paths(generation: ResearchGeneration) -> None:
    expected_staging = (
        generation.root
        / "generations"
        / f"{generation.generation_id}.{generation.attempt_id}.staging"
    ).resolve()
    expected_final = (
        generation.root / "generations" / generation.generation_id
    ).resolve()
    if (
        generation.staging_dir.resolve() != expected_staging
        or generation.final_dir.resolve() != expected_final
    ):
        raise PublicationError("generation_path_invalid")
    try:
        expected_staging.relative_to(generation.root)
        expected_final.relative_to(generation.root)
    except ValueError as exc:
        raise PublicationError("generation_path_escape") from exc


def _safe_cleanup_staging(generation: ResearchGeneration) -> str:
    _validate_generation_paths(generation)
    if not generation.staging_dir.is_dir():
        return "not_required"
    try:
        shutil.rmtree(generation.staging_dir)
    except OSError:
        return "failed"
    return "completed"


def _archive_failed_attempt(
    generation: ResearchGeneration,
    *,
    reason_code: str,
    finished_at: str,
) -> str:
    archive_root = generation.root / "failed-attempts"
    archive = archive_root / f"{generation.generation_id}.{generation.attempt_id}"
    temporary = archive_root / f"{archive.name}.{uuid.uuid4().hex}.tmp"
    try:
        archive_root.mkdir(parents=True, exist_ok=True)
        temporary.mkdir(parents=False, exist_ok=False)
        summary = {
            "schema_version": "daily-research-failed-attempt-v1",
            "generation_id": generation.generation_id,
            "attempt_id": generation.attempt_id,
            "target_date": generation.target_date,
            "snapshot_id": generation.snapshot_id,
            "data_version": generation.data_version,
            "reason_code": str(reason_code),
            "finished_at": str(finished_at),
            "promotion_state": "research_only",
            "execution_authority": False,
        }
        _atomic_json(temporary / "failure.json", summary)
        for name in ("research_jobs.db", "research_jobs.db-wal", "research_jobs.db-shm"):
            source = generation.staging_dir / name
            if source.is_file():
                shutil.copy2(source, temporary / name)
        if archive.exists():
            return "completed"
        os.replace(temporary, archive)
        retained = sorted(
            (path for path in archive_root.iterdir() if path.is_dir() and ".tmp" not in path.name),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for expired in retained[20:]:
            with suppress(OSError):
                shutil.rmtree(expired)
        return "completed"
    except OSError:
        return "failed"
    finally:
        if temporary.exists():
            with suppress(OSError):
                shutil.rmtree(temporary)


def _write_owned_completed_status(
    root: Path,
    generation: ResearchGeneration,
    updates: Mapping[str, Any],
) -> bool:
    current = read_publication_status(root)
    if (
        current.get("state") != "completed"
        or current.get("generation_id") != generation.generation_id
        or current.get("attempt_id") != generation.attempt_id
    ):
        return False
    _atomic_json(root / "status.json", {**current, **dict(updates)})
    return True


def _publish_generation_unlocked(
    root: Path | str,
    generation: ResearchGeneration,
    *,
    finished_at: str,
    compatibility_paths: Mapping[str, Path | str] | None = None,
) -> dict[str, Any]:
    publication_root = Path(root).resolve()
    if generation.root != publication_root:
        raise PublicationError("generation_root_mismatch")
    _validate_generation_paths(generation)
    current = read_publication_status(publication_root)
    if (
        current.get("generation_id") != generation.generation_id
        or current.get("attempt_id") != generation.attempt_id
        or current.get("state") != "refreshing"
    ):
        raise PublicationError("generation_attempt_mismatch")

    mirrors = dict(compatibility_paths or {})
    invalid_names = set(mirrors) - set(ARTIFACT_NAMES)
    if invalid_names:
        raise PublicationError("compatibility_artifact_name_invalid")

    try:
        source = generation.staging_dir
        _validate_generation_artifacts(source, generation)
        hashes = {name: _sha256(source / name) for name in ARTIFACT_NAMES}
        manifest = {
            "schema_version": "daily-research-generation-manifest-v1",
            "generation_id": generation.generation_id,
            "target_date": generation.target_date,
            "snapshot_id": generation.snapshot_id,
            "data_version": generation.data_version,
            "artifact_sha256": hashes,
            "promotion_state": "research_only",
            "execution_authority": False,
        }
        _atomic_json(source / "manifest.json", manifest)

        if generation.final_dir.exists():
            _validate_generation_artifacts(generation.final_dir, generation)
            existing = _json_object(generation.final_dir / "manifest.json")
            final_hashes = {
                name: _sha256(generation.final_dir / name) for name in ARTIFACT_NAMES
            }
            if (
                existing.get("generation_id") != generation.generation_id
                or existing.get("target_date") != generation.target_date
                or existing.get("snapshot_id") != generation.snapshot_id
                or existing.get("data_version") != generation.data_version
                or existing.get("promotion_state") != "research_only"
                or existing.get("execution_authority") is not False
                or existing.get("artifact_sha256") != final_hashes
                or final_hashes != hashes
            ):
                raise PublicationError("generation_identity_collision")
            committed_source = generation.final_dir
        else:
            os.replace(generation.staging_dir, generation.final_dir)
            committed_source = generation.final_dir

        pointer = {
            **manifest,
            "attempt_id": generation.attempt_id,
            "published_at": str(finished_at),
            "artifact_paths": {
                name: f"generations/{generation.generation_id}/{name}"
                for name in ARTIFACT_NAMES
            },
        }
        _atomic_json(publication_root / "latest.json", pointer)
    except Exception as exc:
        if isinstance(exc, PublicationError):
            reason = str(exc).split(":", 1)[0] or "research_publish_failed"
        elif isinstance(exc, OSError):
            reason = "publication_io_error"
        else:
            reason = "research_publish_failed"
        latest_status = read_publication_status(publication_root)
        if (
            latest_status.get("state") == "refreshing"
            and latest_status.get("generation_id") == generation.generation_id
            and latest_status.get("attempt_id") == generation.attempt_id
        ):
            try:
                _mark_refresh_failed_unlocked(
                    publication_root,
                    generation,
                    reason_code=reason,
                    finished_at=str(finished_at),
                )
            except Exception:
                pass
        raise

    status_sync_state = "completed"
    status = {
        **current,
        "state": "completed",
        "finished_at": str(finished_at),
        "reason_code": None,
        "last_complete_generation_id": generation.generation_id,
        "mirror_sync_state": "pending" if mirrors else "not_required",
        "mirror_sync_reason": None,
        "promotion_state": "research_only",
        "execution_authority": False,
    }
    try:
        _atomic_json(publication_root / "status.json", status)
    except Exception:
        status_sync_state = "failed"

    if mirrors:
        try:
            for name, target in mirrors.items():
                _atomic_bytes(Path(target), (committed_source / name).read_bytes())
        except Exception as exc:
            try:
                _write_owned_completed_status(
                    publication_root,
                    generation,
                    {
                        "mirror_sync_state": "failed",
                        "mirror_sync_reason": type(exc).__name__,
                    },
                )
            except Exception:
                status_sync_state = "failed"
            result = {
                **pointer,
                "status_sync_state": status_sync_state,
                "mirror_sync_state": "failed",
                "mirror_sync_reason": type(exc).__name__,
            }
            result["staging_cleanup_state"] = _safe_cleanup_staging(generation)
            return result
        try:
            _write_owned_completed_status(
                publication_root,
                generation,
                {"mirror_sync_state": "completed", "mirror_sync_reason": None},
            )
        except Exception:
            status_sync_state = "failed"
        result = {
            **pointer,
            "status_sync_state": status_sync_state,
            "mirror_sync_state": "completed",
        }
        result["staging_cleanup_state"] = _safe_cleanup_staging(generation)
        return result
    result = {
        **pointer,
        "status_sync_state": status_sync_state,
        "mirror_sync_state": "not_required",
    }
    result["staging_cleanup_state"] = _safe_cleanup_staging(generation)
    return result


def publish_generation(
    root: Path | str,
    generation: ResearchGeneration,
    *,
    finished_at: str,
    compatibility_paths: Mapping[str, Path | str] | None = None,
) -> dict[str, Any]:
    publication_root = Path(root).resolve()
    with _publication_lock(publication_root):
        return _publish_generation_unlocked(
            publication_root,
            generation,
            finished_at=finished_at,
            compatibility_paths=compatibility_paths,
        )


def resolve_complete_generation(root: Path | str) -> dict[str, Any]:
    """Resolve and validate one immutable three-artifact generation bundle."""
    publication_root = Path(root).resolve()
    pointer = _json_object(publication_root / "latest.json")
    generation_id = str(pointer.get("generation_id") or "")
    if not generation_id or any(char not in "0123456789abcdef" for char in generation_id):
        raise PublicationError("publication_generation_id_invalid")
    final_dir = (publication_root / "generations" / generation_id).resolve()
    try:
        final_dir.relative_to(publication_root)
    except ValueError as exc:
        raise PublicationError("publication_path_escape") from exc
    manifest = _json_object(final_dir / "manifest.json")
    identity_fields = ("generation_id", "target_date", "snapshot_id", "data_version")
    if (
        manifest.get("schema_version") != "daily-research-generation-manifest-v1"
        or any(pointer.get(key) != manifest.get(key) for key in identity_fields)
        or pointer.get("promotion_state") != "research_only"
        or pointer.get("execution_authority") is not False
        or manifest.get("promotion_state") != "research_only"
        or manifest.get("execution_authority") is not False
    ):
        raise PublicationError("publication_pointer_identity_mismatch")
    generation = ResearchGeneration(
        root=publication_root,
        generation_id=generation_id,
        attempt_id=str(pointer.get("attempt_id") or "resolved"),
        target_date=_compact_date(pointer.get("target_date")),
        snapshot_id=str(pointer.get("snapshot_id") or ""),
        data_version=str(pointer.get("data_version") or ""),
        staging_dir=final_dir,
        final_dir=final_dir,
    )
    paths: dict[str, Path] = {}
    pointer_paths = pointer.get("artifact_paths") or {}
    pointer_hashes = pointer.get("artifact_sha256") or {}
    if set(pointer_paths) != set(ARTIFACT_NAMES) or set(pointer_hashes) != set(ARTIFACT_NAMES):
        raise PublicationError("publication_pointer_missing")
    for artifact_name in ARTIFACT_NAMES:
        relative = str(pointer_paths.get(artifact_name) or "")
        expected_hash = str(pointer_hashes.get(artifact_name) or "")
        path = (publication_root / relative).resolve()
        expected_path = (final_dir / artifact_name).resolve()
        if path != expected_path:
            raise PublicationError("publication_path_identity_mismatch")
        try:
            path.relative_to(publication_root)
        except ValueError as exc:
            raise PublicationError("publication_path_escape") from exc
        if not path.is_file() or _sha256(path) != expected_hash:
            raise PublicationError("publication_artifact_integrity_failed")
        paths[artifact_name] = path
    if pointer_hashes != manifest.get("artifact_sha256"):
        raise PublicationError("publication_pointer_identity_mismatch")
    _validate_generation_artifacts(final_dir, generation)
    return {"pointer": pointer, "manifest": manifest, "paths": paths}


def resolve_complete_artifact(root: Path | str, artifact_name: str) -> Path:
    if artifact_name not in ARTIFACT_NAMES:
        raise PublicationError("artifact_name_invalid")
    return resolve_complete_generation(root)["paths"][artifact_name]


def retry_compatibility_mirrors(
    root: Path | str,
    compatibility_paths: Mapping[str, Path | str],
) -> dict[str, Any]:
    """Idempotently resync mirrors from the already committed generation."""
    publication_root = Path(root).resolve()
    mirrors = dict(compatibility_paths)
    if not mirrors or set(mirrors) - set(ARTIFACT_NAMES):
        raise PublicationError("compatibility_artifact_name_invalid")
    with _publication_lock(publication_root):
        pointer = _json_object(publication_root / "latest.json")
        generation_id = str(pointer.get("generation_id") or "")
        attempt_id = str(pointer.get("attempt_id") or "")
        if not generation_id or not attempt_id:
            raise PublicationError("publication_pointer_missing")
        try:
            for name, target in mirrors.items():
                source = resolve_complete_artifact(publication_root, name)
                _atomic_bytes(Path(target), source.read_bytes())
        except Exception as exc:
            current = _json_object(publication_root / "status.json")
            if (
                current.get("generation_id") == generation_id
                and current.get("attempt_id") == attempt_id
                and current.get("state") == "completed"
            ):
                with suppress(OSError):
                    _atomic_json(
                        publication_root / "status.json",
                        {
                            **current,
                            "mirror_sync_state": "failed",
                            "mirror_sync_reason": type(exc).__name__,
                        },
                    )
            return {
                "success": False,
                "generation_id": generation_id,
                "attempt_id": attempt_id,
                "mirror_sync_state": "failed",
                "mirror_sync_reason": type(exc).__name__,
            }
        current = _json_object(publication_root / "status.json")
        if (
            current.get("generation_id") == generation_id
            and current.get("attempt_id") == attempt_id
            and current.get("state") == "completed"
        ):
            _atomic_json(
                publication_root / "status.json",
                {
                    **current,
                    "mirror_sync_state": "completed",
                    "mirror_sync_reason": None,
                },
            )
        return {
            "success": True,
            "generation_id": generation_id,
            "attempt_id": attempt_id,
            "mirror_sync_state": "completed",
        }

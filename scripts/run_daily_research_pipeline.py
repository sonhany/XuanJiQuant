"""Deterministic end-of-day data -> quality gate -> factor research pipeline.

This entry point owns orchestration only. It never invokes an AI Agent, never
promotes research output, and never grants execution authority.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from quant.data.cache import create_cache
from quant.data.snapshot import read_latest_passed_snapshot
from quant.research.publication import (
    PublicationError,
    ResearchGeneration,
    begin_refresh,
    mark_refresh_failed,
    publish_generation,
    read_publication_status,
    resolve_complete_artifact,
    retry_compatibility_mirrors,
)
from scripts.data_freshness import get_expected_date
from quant.strategy.f4_readiness import build_f4_readiness


FACTOR_EVALUATION_PATH = PROJECT_ROOT / "data" / "factor_evaluation.json"
SELECTION_LATEST_PATH = (
    PROJECT_ROOT / "data" / "research" / "selections" / "latest.json"
)
PIPELINE_LOCK_PATH = PROJECT_ROOT / "data" / "runtime" / "daily_research_pipeline.lock"
PUBLICATION_ROOT = PROJECT_ROOT / "data" / "research" / "daily"
RESEARCH_GENERATION_DIR_ENV = "XUANJI_RESEARCH_GENERATION_DIR"
DEFAULT_COMPATIBILITY_MIRRORS = {
    "factor_snapshot_latest.json": PROJECT_ROOT / "data" / "factor_snapshot_latest.json",
    "factor_evaluation.json": FACTOR_EVALUATION_PATH,
    "selection.json": SELECTION_LATEST_PATH,
}

SnapshotReader = Callable[[], dict[str, Any] | None]
ArtifactReader = Callable[[], dict[str, Any]]
CommandRunner = Callable[[str, tuple[str, ...], int], dict[str, Any]]
ReadinessBuilder = Callable[[], dict[str, Any]]


def _shadow_base_from_publication_root(publication_root: str | Path) -> Path:
    resolved = Path(publication_root).resolve()
    try:
        data_root = resolved.parents[1]
    except IndexError:
        data_root = PROJECT_ROOT / "data"
    return data_root / "nautilus-baseline"


def _compact_date(value: object) -> str:
    return str(value or "").replace("-", "")[:8]


def _snapshot_gate(snapshot: dict[str, Any] | None, expected_date: str) -> bool:
    value = snapshot or {}
    return bool(
        _compact_date(value.get("as_of")) == expected_date
        and value.get("quality_status") == "passed"
        and value.get("freshness_status") == "fresh"
        and str(value.get("snapshot_id") or "")
        and str(value.get("content_hash") or "")
        and int(value.get("expected_count") or 0) > 0
        and int(value.get("available_count") or 0) > 0
    )


def _factor_artifact_gate(
    artifact: dict[str, Any],
    *,
    snapshot: dict[str, Any],
    expected_date: str,
) -> bool:
    return bool(
        _compact_date(artifact.get("data_end_date")) == expected_date
        and artifact.get("data_version") == snapshot.get("content_hash")
        and artifact.get("promotion_state") == "research_only"
        and artifact.get("execution_authority") is False
        and artifact.get("factors")
    )


def _selection_artifact_gate(
    artifact: dict[str, Any],
    *,
    snapshot: dict[str, Any],
    expected_date: str,
) -> bool:
    return bool(
        _compact_date(artifact.get("selection_date")) == expected_date
        and artifact.get("generated_from_snapshot_id") == snapshot.get("snapshot_id")
        and artifact.get("snapshot_data_version") == snapshot.get("content_hash")
        and artifact.get("promotion_state") == "research_only"
        and artifact.get("execution_authority") is False
        and artifact.get("not_a_trade_signal") is True
        and isinstance(artifact.get("positions"), list)
        and artifact.get("positions")
    )


def _read_factor_artifact() -> dict[str, Any]:
    try:
        value = json.loads(FACTOR_EVALUATION_PATH.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_selection_artifact() -> dict[str, Any]:
    try:
        value = json.loads(SELECTION_LATEST_PATH.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


@contextmanager
def _temporary_environment(name: str, value: str):
    previous = os.environ.get(name)
    os.environ[name] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


def _fail_generation(
    publication_root: Path,
    generation: ResearchGeneration,
    *,
    reason_code: str,
    finished_at: str,
) -> None:
    try:
        status = read_publication_status(publication_root)
        if (
            status.get("state") == "refreshing"
            and status.get("generation_id") == generation.generation_id
            and status.get("attempt_id") == generation.attempt_id
        ):
            mark_refresh_failed(
                publication_root,
                generation,
                reason_code=reason_code,
                finished_at=finished_at,
            )
    except Exception:
        return


def _run_script(
    script_name: str,
    arguments: tuple[str, ...],
    timeout_seconds: int,
) -> dict[str, Any]:
    command = [sys.executable, str(PROJECT_ROOT / "scripts" / script_name), *arguments]
    print(
        json.dumps(
            {"stage": script_name, "status": "started", "command": command},
            ensure_ascii=False,
        ),
        flush=True,
    )
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "success": False,
            "reason_code": "pipeline_stage_timeout",
            "error": str(exc),
        }
    return {
        "success": completed.returncode == 0,
        "exit_code": completed.returncode,
        "reason_code": "" if completed.returncode == 0 else "pipeline_stage_failed",
        "stdout_tail": completed.stdout[-2000:],
        "stderr_tail": completed.stderr[-2000:],
    }


def _run_experimental_selection(
    runner: CommandRunner,
    generation_id: object,
) -> dict[str, Any]:
    identity = str(generation_id or "")
    if not identity:
        return {
            "success": False,
            "reason_code": "research_generation_identity_missing",
        }
    return runner(
        "generate_experimental_portfolio.py",
        ("--generation-id", identity),
        10 * 60,
    )


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _shadow_target_weights(selection_artifact: dict[str, Any]) -> list[dict[str, Any]]:
    weights: list[dict[str, Any]] = []
    for position in selection_artifact.get("positions") or []:
        if not isinstance(position, dict):
            continue
        code = str(position.get("code") or "")
        if not (len(code) == 6 and code.isdigit()):
            continue
        weight = position.get("target_weight", position.get("weight"))
        weights.append({"code": code, "weight": weight})
    return weights


def _run_shadow_research_after_baseline(
    *,
    publication_root: str | Path,
    expected_date: str,
    snapshot: dict[str, Any],
    factor_artifact: dict[str, Any],
    selection_artifact: dict[str, Any],
    f4_readiness: dict[str, Any],
    generation_id: object,
    baseline_result_path: str | Path | None,
    raw_output_path: str | Path | None,
    artifact_root: str | Path | None,
    shadow_store_path: str | Path | None,
) -> dict[str, Any] | None:
    base = _shadow_base_from_publication_root(publication_root)
    baseline_path = Path(baseline_result_path) if baseline_result_path else base / "baseline_result.json"
    if not baseline_path.exists():
        return None
    raw_path = Path(raw_output_path) if raw_output_path else base / "ai_raw_output.json"
    root = Path(artifact_root) if artifact_root else base / "shadow-daily"
    store_path = Path(shadow_store_path) if shadow_store_path else base / "shadow_decisions.sqlite3"
    generation = str(generation_id or "committed")
    run_dir = root / expected_date / f"{generation}-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    runtime_path = run_dir / "runtime_summary.json"
    context_path = run_dir / "context.json"
    report_path = run_dir / "shadow_cycle_report.json"
    try:
        from trading_system.shadow_cycle import run_shadow_cycle
        from trading_system.shadow_decision_store import ShadowDecisionJournal
        from trading_system.shadow_runtime_summary import build_shadow_runtime_summary

        baseline_result = _read_json_object(baseline_path)
        market_summary = {
            "snapshot_id": snapshot.get("snapshot_id"),
            "received_at": snapshot.get("received_at") or snapshot.get("as_of"),
            "market_phase": snapshot.get("market_phase") or "",
            "execution_ready": True,
            "coverage": {
                "available_count": snapshot.get("available_count"),
                "expected_count": snapshot.get("expected_count"),
                "ratio": (
                    int(snapshot.get("available_count") or 0)
                    / int(snapshot.get("expected_count") or 1)
                ),
            },
        }
        factor_summary = {
            "version": factor_artifact.get("data_version"),
            "evaluated_at": factor_artifact.get("data_end_date"),
            "factor_count": len(factor_artifact.get("factors") or []),
            "top_codes": [item["code"] for item in _shadow_target_weights(selection_artifact)],
        }
        strategy_summary = {
            "version": generation,
            "status": selection_artifact.get("status") or "generated",
            "target_weights": _shadow_target_weights(selection_artifact),
        }
        risk_summary = {
            "level": f4_readiness.get("status") or "",
            "summary": f4_readiness.get("reason_code") or "",
            "computed_at": datetime.now().astimezone().isoformat(),
        }
        runtime_summary = build_shadow_runtime_summary(
            baseline_result=baseline_result,
            market_summary=market_summary,
            risk_summary=risk_summary,
            factor_summary=factor_summary,
            strategy_summary=strategy_summary,
            history_summary={
                "pipeline": "daily_research",
                "expected_date": expected_date,
                "generation_id": generation,
            },
        )
        _atomic_write_json(runtime_path, runtime_summary)
        if not raw_path.exists():
            return {
                "stage": "shadow_research",
                "success": True,
                "status": "skipped",
                "reason_code": "shadow_ai_raw_output_missing",
                "runtime_summary_path": str(runtime_path),
                "execution_authority": False,
                "can_trigger_order": False,
                "live_execution_authority": False,
            }
        with ShadowDecisionJournal(store_path) as journal:
            result = run_shadow_cycle(
                runtime_summary=runtime_summary,
                raw_output=raw_path.read_text(encoding="utf-8"),
                journal=journal,
                context_output=context_path,
                report_output=report_path,
            )
        status = str(result.get("status") or "")
        success = status in {"recorded", "existing"}
        return {
            "stage": "shadow_research",
            "success": success,
            "reason_code": "" if success else "shadow_cycle_validation_failed",
            "status": status,
            "runtime_summary_path": str(runtime_path),
            "context_output_path": str(context_path),
            "report_output_path": str(report_path),
            "shadow_store_path": str(store_path),
            "execution_authority": False,
            "can_trigger_order": False,
            "live_execution_authority": False,
        }
    except Exception as exc:
        return {
            "stage": "shadow_research",
            "success": False,
            "reason_code": "shadow_research_failed",
            "error": str(exc),
            "execution_authority": False,
            "can_trigger_order": False,
            "live_execution_authority": False,
        }


def run_daily_pipeline(
    *,
    now: datetime | None = None,
    workers: int = 8,
    snapshot_reader: SnapshotReader | None = None,
    factor_artifact_reader: ArtifactReader | None = None,
    selection_artifact_reader: ArtifactReader | None = None,
    command_runner: CommandRunner | None = None,
    publication_root: str | Path = PUBLICATION_ROOT,
    compatibility_mirrors: dict[str, str | Path] | None = None,
    readiness_builder: ReadinessBuilder | None = None,
    shadow_baseline_result_path: str | Path | None = None,
    shadow_raw_output_path: str | Path | None = None,
    shadow_artifact_root: str | Path | None = None,
    shadow_store_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run the daily chain and fail closed when any evidence gate is unmet."""

    current = now or datetime.now()
    expected_date = get_expected_date(current)
    if snapshot_reader is None:
        cache = create_cache()
        snapshot_reader = lambda: read_latest_passed_snapshot(cache, "a_share_daily")
    injected_artifact_readers = (
        factor_artifact_reader is not None or selection_artifact_reader is not None
    )
    artifact_reader = factor_artifact_reader or _read_factor_artifact
    selection_reader = selection_artifact_reader or _read_selection_artifact
    runner = command_runner or _run_script

    before = snapshot_reader() or {}
    refresh_performed = not _snapshot_gate(before, expected_date)
    stages: list[dict[str, Any]] = []
    if refresh_performed:
        update = runner(
            "daily_update.py",
            ("--workers", str(max(1, int(workers)))),
            3 * 60 * 60,
        )
        stages.append({"stage": "daily_update", **update})
        if update.get("success") is not True:
            return {
                "success": False,
                "reason_code": "daily_update_failed",
                "expected_date": expected_date,
                "data_refresh_performed": True,
                "stages": stages,
            }
        current_snapshot = snapshot_reader() or {}
    else:
        current_snapshot = before

    if not _snapshot_gate(current_snapshot, expected_date):
        return {
            "success": False,
            "reason_code": "daily_snapshot_gate_failed",
            "expected_date": expected_date,
            "snapshot": current_snapshot,
            "data_refresh_performed": refresh_performed,
            "stages": stages,
        }

    mirrors = (
        DEFAULT_COMPATIBILITY_MIRRORS
        if compatibility_mirrors is None
        else compatibility_mirrors
    )
    if not injected_artifact_readers and mirrors:
        committed = _read_json_object(Path(publication_root).resolve() / "latest.json")
        publication_status = read_publication_status(publication_root)
        same_committed_identity = (
            _compact_date(committed.get("target_date")) == expected_date
            and committed.get("snapshot_id") == current_snapshot.get("snapshot_id")
            and committed.get("data_version") == current_snapshot.get("content_hash")
        )
        if (
            same_committed_identity
            and publication_status.get("generation_id") == committed.get("generation_id")
        ):
            prior_mirror_state = str(
                publication_status.get("mirror_sync_state") or "pending"
            )
            recovery = retry_compatibility_mirrors(publication_root, mirrors)
            if recovery.get("success") is not True:
                return {
                    "success": False,
                    "reason_code": "research_compatibility_mirror_sync_failed",
                    "publication_committed": True,
                    **recovery,
                    "expected_date": expected_date,
                    "snapshot": current_snapshot,
                    "data_refresh_performed": refresh_performed,
                    "stages": [{"stage": "compatibility_mirror_recovery", **recovery}],
                }
            factor_artifact = _read_json_object(
                resolve_complete_artifact(publication_root, "factor_evaluation.json")
            )
            selection_artifact = _read_json_object(
                resolve_complete_artifact(publication_root, "selection.json")
            )
            experimental = _run_experimental_selection(
                runner, recovery.get("generation_id")
            )
            if experimental.get("success") is not True:
                return {
                    "success": False,
                    "reason_code": "experimental_selection_failed",
                    "publication_committed": True,
                    "generation_id": recovery.get("generation_id"),
                    "expected_date": expected_date,
                    "snapshot": current_snapshot,
                    "data_refresh_performed": refresh_performed,
                    "stages": [
                        {"stage": "compatibility_mirror_recovery", **recovery},
                        {"stage": "experimental_selection", **experimental},
                    ],
                }
            success_stages = [
                {"stage": "compatibility_mirror_recovery", **recovery},
                {"stage": "experimental_selection", **experimental},
            ]
            shadow = _run_shadow_research_after_baseline(
                publication_root=publication_root,
                expected_date=expected_date,
                snapshot=current_snapshot,
                factor_artifact=factor_artifact,
                selection_artifact=selection_artifact,
                f4_readiness={},
                generation_id=recovery.get("generation_id"),
                baseline_result_path=shadow_baseline_result_path,
                raw_output_path=shadow_raw_output_path,
                artifact_root=shadow_artifact_root,
                shadow_store_path=shadow_store_path,
            )
            if shadow is not None:
                success_stages.append(shadow)
                if shadow.get("success") is not True:
                    return {
                        "success": False,
                        "reason_code": "shadow_research_failed",
                        "publication_committed": True,
                        "generation_id": recovery.get("generation_id"),
                        "expected_date": expected_date,
                        "snapshot": current_snapshot,
                        "data_refresh_performed": refresh_performed,
                        "stages": success_stages,
                    }
            return {
                "success": True,
                "reason_code": "",
                "publication_recovered": prior_mirror_state != "completed",
                "publication_no_op": prior_mirror_state == "completed",
                "generation_id": recovery.get("generation_id"),
                "mirror_sync_state": "completed",
                "expected_date": expected_date,
                "snapshot_id": current_snapshot.get("snapshot_id"),
                "data_version": current_snapshot.get("content_hash"),
                "factor_count": len(factor_artifact.get("factors") or []),
                "portfolio_id": selection_artifact.get("portfolio_id"),
                "selection_position_count": len(selection_artifact.get("positions") or []),
                "promotion_state": "research_only",
                "execution_authority": False,
                "data_refresh_performed": refresh_performed,
                "stages": success_stages,
            }

    publication_directory = Path(publication_root).resolve()
    generation: ResearchGeneration | None = None
    f4_readiness: dict[str, Any] = {}
    if not injected_artifact_readers:
        generation = begin_refresh(
            publication_directory,
            target_date=expected_date,
            snapshot_id=str(current_snapshot.get("snapshot_id") or ""),
            data_version=str(current_snapshot.get("content_hash") or ""),
            started_at=current.isoformat(timespec="seconds"),
        )
        try:
            with _temporary_environment(
                RESEARCH_GENERATION_DIR_ENV,
                str(generation.staging_dir),
            ):
                research = runner(
                    "research_training_scheduler.py",
                    ("--once", "--lane", "daily"),
                    2 * 60 * 60,
                )
        except Exception as exc:
            _fail_generation(
                publication_directory,
                generation,
                reason_code="research_training_exception",
                finished_at=datetime.now().isoformat(timespec="seconds"),
            )
            return {
                "success": False,
                "reason_code": "research_training_exception",
                "error": str(exc),
                "expected_date": expected_date,
                "snapshot": current_snapshot,
                "data_refresh_performed": refresh_performed,
                "stages": stages,
            }
    else:
        research = runner(
            "research_training_scheduler.py",
            ("--once", "--lane", "daily"),
            2 * 60 * 60,
        )
    stages.append({"stage": "research_training", **research})
    if research.get("success") is not True:
        if generation is not None:
            _fail_generation(
                publication_directory,
                generation,
                reason_code="research_training_failed",
                finished_at=datetime.now().isoformat(timespec="seconds"),
            )
        return {
            "success": False,
            "reason_code": "research_training_failed",
            "expected_date": expected_date,
            "snapshot": current_snapshot,
            "data_refresh_performed": refresh_performed,
            "stages": stages,
        }

    factor_artifact = (
        _read_json_object(generation.staging_dir / "factor_evaluation.json")
        if generation is not None
        else artifact_reader()
    )
    if not _factor_artifact_gate(
        factor_artifact,
        snapshot=current_snapshot,
        expected_date=expected_date,
    ):
        if generation is not None:
            _fail_generation(
                publication_directory,
                generation,
                reason_code="factor_artifact_gate_failed",
                finished_at=datetime.now().isoformat(timespec="seconds"),
            )
        return {
            "success": False,
            "reason_code": "factor_artifact_gate_failed",
            "expected_date": expected_date,
            "snapshot": current_snapshot,
            "factor_artifact": factor_artifact,
            "data_refresh_performed": refresh_performed,
            "stages": stages,
        }

    selection_artifact = (
        _read_json_object(generation.staging_dir / "selection.json")
        if generation is not None
        else selection_reader()
    )
    if not _selection_artifact_gate(
        selection_artifact,
        snapshot=current_snapshot,
        expected_date=expected_date,
    ):
        if generation is not None:
            _fail_generation(
                publication_directory,
                generation,
                reason_code="research_selection_gate_failed",
                finished_at=datetime.now().isoformat(timespec="seconds"),
            )
        return {
            "success": False,
            "reason_code": "research_selection_gate_failed",
            "expected_date": expected_date,
            "snapshot": current_snapshot,
            "factor_artifact": factor_artifact,
            "selection_artifact": selection_artifact,
            "data_refresh_performed": refresh_performed,
            "stages": stages,
        }

    pointer: dict[str, Any] = {}
    if generation is not None:
        try:
            pointer = publish_generation(
                publication_directory,
                generation,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                compatibility_paths=mirrors,
            )
        except (OSError, PublicationError, TypeError, ValueError) as exc:
            _fail_generation(
                publication_directory,
                generation,
                reason_code=str(exc).split(":", 1)[0]
                or "research_generation_publish_failed",
                finished_at=datetime.now().isoformat(timespec="seconds"),
            )
            return {
                "success": False,
                "reason_code": "research_generation_publish_failed",
                "publication_error": str(exc),
                "expected_date": expected_date,
                "snapshot": current_snapshot,
                "factor_artifact": factor_artifact,
                "selection_artifact": selection_artifact,
                "data_refresh_performed": refresh_performed,
                "stages": stages,
            }

        if mirrors and pointer.get("mirror_sync_state") != "completed":
            return {
                "success": False,
                "reason_code": "research_compatibility_mirror_sync_failed",
                "publication_committed": True,
                "generation_id": pointer.get("generation_id"),
                "mirror_sync_state": pointer.get("mirror_sync_state"),
                "mirror_sync_reason": pointer.get("mirror_sync_reason"),
                "expected_date": expected_date,
                "snapshot": current_snapshot,
                "factor_artifact": factor_artifact,
                "selection_artifact": selection_artifact,
                "data_refresh_performed": refresh_performed,
                "stages": stages,
            }

        experimental = _run_experimental_selection(
            runner, pointer.get("generation_id")
        )
        stages.append({"stage": "experimental_selection", **experimental})
        if experimental.get("success") is not True:
            return {
                "success": False,
                "reason_code": "experimental_selection_failed",
                "publication_committed": True,
                "generation_id": pointer.get("generation_id"),
                "expected_date": expected_date,
                "snapshot": current_snapshot,
                "factor_artifact": factor_artifact,
                "selection_artifact": selection_artifact,
                "data_refresh_performed": refresh_performed,
                "stages": stages,
            }
        f4_readiness = (readiness_builder or (lambda: build_f4_readiness(PROJECT_ROOT)))()
        stages.append({"stage": "f4_readiness", **f4_readiness})
        shadow = _run_shadow_research_after_baseline(
            publication_root=publication_root,
            expected_date=expected_date,
            snapshot=current_snapshot,
            factor_artifact=factor_artifact,
            selection_artifact=selection_artifact,
            f4_readiness=f4_readiness,
            generation_id=pointer.get("generation_id"),
            baseline_result_path=shadow_baseline_result_path,
            raw_output_path=shadow_raw_output_path,
            artifact_root=shadow_artifact_root,
            shadow_store_path=shadow_store_path,
        )
        if shadow is not None:
            stages.append(shadow)
            if shadow.get("success") is not True:
                return {
                    "success": False,
                    "reason_code": "shadow_research_failed",
                    "publication_committed": True,
                    "generation_id": pointer.get("generation_id"),
                    "expected_date": expected_date,
                    "snapshot": current_snapshot,
                    "factor_artifact": factor_artifact,
                    "selection_artifact": selection_artifact,
                    "data_refresh_performed": refresh_performed,
                    "stages": stages,
                }

    return {
        "success": True,
        "reason_code": "",
        "expected_date": expected_date,
        "snapshot_id": current_snapshot.get("snapshot_id"),
        "data_version": current_snapshot.get("content_hash"),
        "coverage": (
            int(current_snapshot.get("available_count") or 0)
            / int(current_snapshot.get("expected_count") or 1)
        ),
        "factor_count": len(factor_artifact.get("factors") or []),
        "portfolio_id": selection_artifact.get("portfolio_id"),
        "selection_status": selection_artifact.get("status") or "generated",
        "selection_position_count": len(selection_artifact.get("positions") or []),
        "generation_id": pointer.get("generation_id"),
        "f4_readiness": f4_readiness,
        "mirror_sync_state": pointer.get("mirror_sync_state"),
        "promotion_state": "research_only",
        "execution_authority": False,
        "data_refresh_performed": refresh_performed,
        "stages": stages,
    }


@contextmanager
def _single_instance(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    if path.stat().st_size == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise RuntimeError("daily_research_pipeline_already_running") from exc
    try:
        yield
    finally:
        handle.seek(0)
        if os.name == "nt":
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="日终数据与确定性研究流水线")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    try:
        with _single_instance(PIPELINE_LOCK_PATH):
            result = run_daily_pipeline(workers=args.workers)
    except RuntimeError as exc:
        result = {"success": False, "reason_code": str(exc)}
    print(json.dumps(result, ensure_ascii=False, default=str), flush=True)
    return 0 if result.get("success") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())

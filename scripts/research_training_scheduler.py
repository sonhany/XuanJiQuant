from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from quant.qlib.paths import resolve_data_path
from quant.data.cache import create_cache
from quant.data.snapshot import read_latest_passed_snapshot
from quant.research.job_store import ResearchJobStore
from quant.research.publication import resolve_complete_generation
from quant.research.training_schedule import ScheduledResearchJob, due_research_jobs
from quant.strategy.f4_readiness import build_f4_readiness


Handler = Callable[
    [ScheduledResearchJob, Callable[[str, float], None]],
    dict[str, Any],
]
FACTOR_EVALUATION_PATH = PROJECT_ROOT / "data" / "factor_evaluation.json"
F4_LATEST_PATH = PROJECT_ROOT / "data" / "research" / "f4" / "latest.json"
SELECTION_LATEST_PATH = (
    PROJECT_ROOT / "data" / "research" / "selections" / "latest.json"
)
DAILY_RESEARCH_ROOT = PROJECT_ROOT / "data" / "research" / "daily"
RESEARCH_GENERATION_DIR_ENV = "XUANJI_RESEARCH_GENERATION_DIR"
LANE_KINDS = {
    "all": None,
    "daily": {"factor_daily", "research_selection_daily"},
    "strategy": {"strategy_weekly"},
    "qlib": {"qlib_weekly", "qlib_monthly", "qlib_quarterly"},
}


def _generation_dir() -> Path | None:
    value = str(os.environ.get(RESEARCH_GENERATION_DIR_ENV) or "").strip()
    if not value:
        return None
    directory = Path(value).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _factor_evaluation_path() -> Path:
    directory = _generation_dir()
    return directory / "factor_evaluation.json" if directory else FACTOR_EVALUATION_PATH


def _selection_path() -> Path:
    directory = _generation_dir()
    return directory / "selection.json" if directory else SELECTION_LATEST_PATH


def _research_job_store_path() -> Path:
    directory = _generation_dir()
    return directory / "research_jobs.db" if directory else resolve_data_path(
        "research_jobs.db"
    )


def _process_is_alive(pid: int) -> bool:
    """Return whether an owner PID still exists without mutating the process."""
    process_id = int(pid or 0)
    if process_id <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, process_id)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return ctypes.get_last_error() == 5
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _existing_factor_artifact(job: ScheduledResearchJob) -> dict[str, Any] | None:
    try:
        artifact = json.loads(_factor_evaluation_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    compact_market_date = job.market_date.replace("-", "")
    if (
        artifact.get("data_version") != job.data_version
        or str(artifact.get("data_end_date") or "").replace("-", "")[:8]
        != compact_market_date
        or artifact.get("promotion_state") != "research_only"
        or artifact.get("execution_authority") is not False
        or not artifact.get("factors")
    ):
        return None
    return {
        "success": True,
        "no_op": True,
        "reason_code": "factor_version_already_evaluated",
        "dataset_version": job.data_version,
        "snapshot_id": artifact.get("snapshot_id"),
        "factor_count": len(artifact.get("factors") or []),
        "promotion_state": "research_only",
        "execution_authority": False,
    }


def _run_deterministic_research_script(
    script_name: str,
    *arguments: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    """运行固定研究程序；不生成代码、不调用 Agent、不晋升生产。"""
    completed = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / script_name), *arguments],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
    )
    if completed.returncode != 0:
        return {
            "success": False,
            "reason_code": "deterministic_research_failed",
            "exit_code": completed.returncode,
            "stderr": completed.stderr[-1000:],
        }
    return {
        "success": True,
        "promotion_state": "research_only",
        "script": script_name,
        "stdout_tail": completed.stdout[-1000:],
    }


def _factor_handler(
    job: ScheduledResearchJob,
    heartbeat: Callable[[str, float], None],
) -> dict[str, Any]:
    existing = _existing_factor_artifact(job)
    if existing is not None:
        heartbeat("factor_artifact_verified", 1.0)
        return existing
    heartbeat("factor_evaluation", 0.1)
    result = _run_deterministic_research_script(
        "evaluate_factors.py",
        "--no-cache",
        timeout_seconds=60 * 60,
    )
    heartbeat("ic_validation", 0.9)
    return result


def _strategy_handler(
    _job: ScheduledResearchJob,
    heartbeat: Callable[[str, float], None],
) -> dict[str, Any]:
    heartbeat("f4_validation", 0.1)
    result = _run_deterministic_research_script(
        "validate_strategy_portfolios.py",
        "--once",
        timeout_seconds=12 * 60 * 60,
    )
    if result.get("success") is not True:
        return result
    try:
        projection = json.loads(F4_LATEST_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        return {
            "success": False,
            "reason_code": "f4_evidence_missing",
            "error": str(exc),
        }
    if (
        not isinstance(projection, dict)
        or projection.get("promotion_state") != "research_only"
        or projection.get("execution_authority") is not False
        or not projection.get("status")
    ):
        return {"success": False, "reason_code": "artifact_integrity_failed"}
    heartbeat("f4_gate_complete", 0.9)
    if projection.get("status") == "f4_rejected":
        try:
            generation_id = str(
                resolve_complete_generation(DAILY_RESEARCH_ROOT)
                .get("pointer", {})
                .get("generation_id")
                or ""
            )
        except Exception as exc:
            return {
                "success": False,
                "reason_code": "research_generation_identity_missing",
                "error": str(exc),
            }
        if not generation_id:
            return {
                "success": False,
                "reason_code": "research_generation_identity_missing",
            }
        rebound = _run_deterministic_research_script(
            "generate_experimental_portfolio.py",
            "--generation-id",
            generation_id,
            timeout_seconds=60 * 60,
        )
        if rebound.get("success") is not True:
            return {
                "success": False,
                "reason_code": "experimental_selection_rebind_failed",
                "rebind_result": rebound,
            }
        heartbeat("experimental_selection_rebound", 0.95)
    return {"success": True, **projection}


def _selection_handler(
    job: ScheduledResearchJob,
    heartbeat: Callable[[str, float], None],
) -> dict[str, Any]:
    heartbeat("research_selection", 0.1)
    result = _run_deterministic_research_script(
        "generate_research_portfolio.py",
        "--once",
        timeout_seconds=60 * 60,
    )
    if result.get("success") is not True:
        return result
    try:
        projection = json.loads(_selection_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        return {
            "success": False,
            "reason_code": "research_selection_evidence_missing",
            "error": str(exc),
        }
    if (
        not isinstance(projection, dict)
        or str(projection.get("selection_date") or "").replace("-", "")[:8]
        != job.market_date.replace("-", "")
        or projection.get("snapshot_data_version") != job.data_version
        or projection.get("promotion_state") != "research_only"
        or projection.get("execution_authority") is not False
        or projection.get("not_a_trade_signal") is not True
        or not projection.get("portfolio_id")
        or not projection.get("positions")
    ):
        return {
            "success": False,
            "reason_code": "research_selection_artifact_integrity_failed",
        }
    heartbeat("selection_gate_complete", 0.9)
    return {"success": True, **projection}


def _qlib_handler(
    job: ScheduledResearchJob,
    heartbeat: Callable[[str, float], None],
) -> dict[str, Any]:
    from scripts.qlib_schedule import run_registered_cycle

    mode = job.kind.removeprefix("qlib_")
    heartbeat("qlib_cycle", 0.05)
    return run_registered_cycle(mode=mode, force=True, now=datetime.now())


DEFAULT_HANDLERS: Mapping[str, Handler] = {
    "factor_daily": _factor_handler,
    "research_selection_daily": _selection_handler,
    "strategy_weekly": _strategy_handler,
    "qlib_weekly": _qlib_handler,
    "qlib_monthly": _qlib_handler,
    "qlib_quarterly": _qlib_handler,
}


def _result_succeeded(result: dict[str, Any]) -> bool:
    if result.get("success") is False:
        return False
    status = str(result.get("status") or "").strip().lower()
    return status not in {"failed", "error", "blocked", "interrupted"}


def _factor_identity(job: ScheduledResearchJob, factor_version: str) -> str:
    return (
        f"factor_daily:{job.market_date}:{job.data_version}:{factor_version}"
    )


def _overdue_qlib_retry(
    *,
    store: ResearchJobStore,
    now: datetime,
    market_date: str,
    data_version: str,
    factor_version: str,
    qlib_version: str,
) -> ScheduledResearchJob | None:
    if not market_date:
        return None
    days_since_saturday = (now.weekday() - 5) % 7
    saturday = now.date() - timedelta(days=days_since_saturday)
    scheduled_at = datetime(
        saturday.year,
        saturday.month,
        saturday.day,
        18,
        30,
        tzinfo=now.tzinfo,
    )
    for candidate in store.list_jobs(500):
        if (
            candidate.get("kind") not in LANE_KINDS["qlib"]
            or candidate.get("status") not in {"failed", "blocked", "interrupted"}
        ):
            continue
        params = candidate.get("params") or {}
        if (
            str(params.get("market_date") or "") != market_date
            or str(params.get("factory_version") or "") != qlib_version
        ):
            continue
        qlib_data_version = str(params.get("data_version") or "")
        expected = next(
            (
                item
                for item in due_research_jobs(
                    now=scheduled_at,
                    trading_days=[market_date],
                    data_version=data_version,
                    factor_version=factor_version,
                    strategy_version="",
                    qlib_version=qlib_version,
                    qlib_data_version=qlib_data_version,
                )
                if item.kind.startswith("qlib_")
            ),
            None,
        )
        if expected and expected.idempotency_key == candidate.get("idempotency_key"):
            return expected
    return None


def _block_reason(
    job: ScheduledResearchJob,
    *,
    data_snapshot: Mapping[str, Any],
    store: ResearchJobStore,
    factor_version: str,
) -> str:
    if job.kind.startswith("qlib_"):
        if str(data_snapshot.get("qlib_data_version") or "") in {"", "missing"}:
            return "qlib_data_version_mismatch"
        return ""
    if data_snapshot.get("sync_complete") is not True:
        return "data_sync_incomplete"
    if str(data_snapshot.get("complete_market_date") or "") != job.market_date:
        return "complete_market_date_mismatch"
    if str(data_snapshot.get("data_version") or "") != job.data_version:
        return "data_version_mismatch"
    if job.kind == "factor_daily" and data_snapshot.get("factor_input_fresh") is not True:
        return "factor_input_stale"
    if job.kind == "research_selection_daily":
        factor_job = store.find(_factor_identity(job, factor_version))
        if not factor_job or factor_job.get("status") != "succeeded":
            return "factor_prerequisite_missing"
        if (factor_job.get("result") or {}).get("dataset_version", job.data_version) != job.data_version:
            return "factor_data_version_mismatch"
    if job.kind == "strategy_weekly":
        if data_snapshot.get("factor_publication_complete") is not True:
            return "factor_prerequisite_missing"
        if str(data_snapshot.get("factor_publication_market_date") or "").replace(
            "-", ""
        )[:8] != job.market_date.replace("-", "")[:8]:
            return "factor_market_date_mismatch"
        if str(data_snapshot.get("factor_publication_data_version") or "") != job.data_version:
            return "factor_data_version_mismatch"
    return ""


def run_due_once(
    *,
    now: datetime,
    trading_days: Iterable[date | datetime | str],
    data_snapshot: Mapping[str, Any],
    store: ResearchJobStore,
    factor_version: str,
    strategy_version: str,
    qlib_version: str,
    lane: str = "all",
    event_trigger: bool = False,
    handlers: Mapping[str, Handler] | None = None,
    process_alive: Callable[[int], bool] | None = None,
) -> list[dict[str, Any]]:
    """Claim and execute all deterministic jobs due at ``now`` exactly once."""

    store.recover_expired(
        now=now,
        process_alive=process_alive or _process_is_alive,
    )

    due = due_research_jobs(
        now=now,
        trading_days=trading_days,
        data_version=str(data_snapshot.get("data_version") or ""),
        factor_version=factor_version,
        strategy_version=strategy_version,
        qlib_version=qlib_version,
        qlib_data_version=str(data_snapshot.get("qlib_data_version") or ""),
        f4_validation_id=str(data_snapshot.get("f4_validation_id") or ""),
        portfolio_policy_version=str(
            data_snapshot.get("portfolio_policy_version") or ""
        ),
    )
    if lane not in LANE_KINDS:
        raise ValueError("research_scheduler_lane_invalid")
    allowed_kinds = LANE_KINDS[lane]
    if allowed_kinds is not None:
        due = [job for job in due if job.kind in allowed_kinds]
    if (
        event_trigger
        and lane == "strategy"
        and not due
        and data_snapshot.get("f4_trigger_required") is True
    ):
        market_date = str(data_snapshot.get("complete_market_date") or "")
        iso_year, iso_week, _ = now.date().isocalendar()
        due = [
            ScheduledResearchJob(
                kind="strategy_weekly",
                idempotency_key=(
                    f"strategy_weekly:{iso_year}-W{iso_week:02d}:"
                    f"{data_snapshot.get('data_version') or ''}:{strategy_version}"
                ),
                market_date=market_date,
                data_version=str(data_snapshot.get("data_version") or ""),
                factory_version=str(strategy_version),
                heavy=True,
            )
        ]
    if lane == "qlib" and not due:
        retry = _overdue_qlib_retry(
            store=store,
            now=now,
            market_date=str(data_snapshot.get("complete_market_date") or ""),
            data_version=str(data_snapshot.get("data_version") or ""),
            factor_version=factor_version,
            qlib_version=qlib_version,
        )
        if retry is not None:
            due = [retry]
    available = dict(DEFAULT_HANDLERS if handlers is None else handlers)
    outcomes: list[dict[str, Any]] = []
    for job in due:
        claim = store.claim(
            job.idempotency_key,
            kind=job.kind,
            heavy=job.heavy,
            owner_pid=os.getpid(),
            now=now,
            params={
                "market_date": job.market_date,
                "data_version": job.data_version,
                "factory_version": job.factory_version,
            },
        )
        if not claim.claimed:
            outcomes.append(
                {
                    "kind": job.kind,
                    "idempotency_key": job.idempotency_key,
                    "status": "skipped",
                    "reason_code": claim.reason,
                    "job_id": claim.job_id,
                }
            )
            continue

        reason = _block_reason(
            job,
            data_snapshot=data_snapshot,
            store=store,
            factor_version=factor_version,
        )
        if reason:
            stored = store.finish(
                claim.job_id,
                run_token=claim.run_token,
                status="blocked",
                result={
                    "reason_code": reason,
                    "dataset_version": job.data_version,
                },
                error_code=reason,
            )
            outcomes.append(
                {
                    "kind": job.kind,
                    "idempotency_key": job.idempotency_key,
                    "status": stored["status"],
                    "reason_code": reason,
                    "job_id": claim.job_id,
                }
            )
            continue

        handler = available.get(job.kind)
        if handler is None:
            stored = store.finish(
                claim.job_id,
                run_token=claim.run_token,
                status="failed",
                result={"reason_code": "handler_missing"},
                error_code="handler_missing",
            )
            outcomes.append(
                {
                    "kind": job.kind,
                    "idempotency_key": job.idempotency_key,
                    "status": stored["status"],
                    "reason_code": "handler_missing",
                    "job_id": claim.job_id,
                }
            )
            continue

        def heartbeat(stage: str, progress: float) -> None:
            store.heartbeat(
                claim.job_id,
                run_token=claim.run_token,
                stage=stage,
                progress=progress,
            )

        try:
            result = handler(job, heartbeat)
            payload = dict(result) if isinstance(result, dict) else {"result": result}
            payload.setdefault("dataset_version", job.data_version)
            payload["promotion_state"] = "research_only"
            payload["execution_authority"] = False
            succeeded = _result_succeeded(payload)
            status = "succeeded" if succeeded else "failed"
            error_code = "" if succeeded else str(
                payload.get("reason_code") or payload.get("error") or "handler_failed"
            )[:128]
            stored = store.finish(
                claim.job_id,
                run_token=claim.run_token,
                status=status,
                result=payload,
                error_code=error_code,
            )
            outcomes.append(
                {
                    "kind": job.kind,
                    "idempotency_key": job.idempotency_key,
                    "status": stored["status"],
                    "reason_code": error_code,
                    "job_id": claim.job_id,
                }
            )
        except Exception as exc:
            stored = store.finish(
                claim.job_id,
                run_token=claim.run_token,
                status="failed",
                result={"error": str(exc)[:500]},
                error_code=type(exc).__name__,
            )
            outcomes.append(
                {
                    "kind": job.kind,
                    "idempotency_key": job.idempotency_key,
                    "status": stored["status"],
                    "reason_code": type(exc).__name__,
                    "job_id": claim.job_id,
                }
            )
    return outcomes


def _load_runtime_inputs() -> tuple[list[str], dict[str, Any]]:
    cache = create_cache()
    daily = read_latest_passed_snapshot(cache, "a_share_daily") or {}
    daily_as_of = str(daily.get("as_of") or "")[:10]
    daily_complete = bool(
        daily.get("quality_status") == "passed"
        and daily.get("freshness_status") == "fresh"
        and daily_as_of
    )
    manifest_path = resolve_data_path(
        "datasets", "a_share_6y_daily", "manifest.json"
    )
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.is_file()
        else {}
    )
    data_version = str(manifest.get("dataset_version") or "")
    end_date = str(manifest.get("end_date") or "")[:10]
    quality_path = resolve_data_path(
        "datasets", "a_share_6y_daily", "quality_report.json"
    )
    quality = (
        json.loads(quality_path.read_text(encoding="utf-8"))
        if quality_path.is_file()
        else {}
    )
    qlib_market_date = str(
        quality.get("data_latest_date")
        or quality.get("expected_latest_date")
        or end_date
        or ""
    )[:10]
    calendar_candidates = (
        resolve_data_path(
            "qlib_bin", "a_share_6y_daily", "calendars", "day.txt"
        ),
        resolve_data_path("provider", "calendars", "day.txt"),
    )
    calendar_path = next(
        (path for path in calendar_candidates if path.is_file()), None
    )
    calendar = (
        [
            line.strip()[:10]
            for line in calendar_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if calendar_path is not None
        else ([qlib_market_date] if qlib_market_date else [])
    )
    if daily_as_of and daily_as_of not in calendar:
        calendar.append(daily_as_of)
    calendar = sorted(set(calendar))
    qlib_complete = manifest.get("status") == "complete"
    try:
        f4_projection = json.loads(F4_LATEST_PATH.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        f4_projection = {}
    try:
        factor_publication = resolve_complete_generation(DAILY_RESEARCH_ROOT)[
            "pointer"
        ]
        factor_publication_complete = bool(
            factor_publication.get("promotion_state") == "research_only"
            and factor_publication.get("execution_authority") is False
        )
    except Exception:
        factor_publication = {}
        factor_publication_complete = False
    readiness = build_f4_readiness(PROJECT_ROOT)
    return calendar, {
        "sync_complete": daily_complete,
        "complete_market_date": daily_as_of if daily_complete else "",
        "factor_input_fresh": daily_complete,
        "data_version": str(daily.get("content_hash") or daily.get("snapshot_id") or "missing"),
        "factor_publication_complete": factor_publication_complete,
        "factor_publication_market_date": str(
            factor_publication.get("target_date") or ""
        )[:10],
        "factor_publication_data_version": str(
            factor_publication.get("data_version") or ""
        ),
        "qlib_sync_complete": qlib_complete,
        "qlib_market_date": qlib_market_date if qlib_complete else "",
        "qlib_data_version": data_version or "missing",
        "f4_validation_id": str(f4_projection.get("validation_id") or ""),
        "portfolio_policy_version": str(
            f4_projection.get("portfolio_policy_version") or ""
        ),
        "f4_readiness_status": readiness.get("status"),
        "f4_readiness_reason": readiness.get("reason_code"),
        "f4_trigger_required": readiness.get("trigger_required") is True,
    }


def _once_exit_code(outcomes: Iterable[Mapping[str, Any]]) -> int:
    """Return success only when every due job completed or was already terminal."""

    for outcome in outcomes:
        status = str(outcome.get("status") or "")
        reason = str(outcome.get("reason_code") or "")
        if status == "succeeded":
            continue
        if status == "skipped" and reason == "idempotent_terminal":
            continue
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="XuanJiQuant deterministic research scheduler")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--factor-version", default="factor-factory-v1")
    parser.add_argument("--strategy-version", default="strategy-factory-v1")
    parser.add_argument("--qlib-version", default="qlib-schedule-v1")
    parser.add_argument("--lane", choices=tuple(LANE_KINDS), default="all")
    args = parser.parse_args()
    store = ResearchJobStore(_research_job_store_path())
    while True:
        calendar, snapshot = _load_runtime_inputs()
        outcomes = run_due_once(
            now=datetime.now().astimezone().replace(tzinfo=None),
            trading_days=calendar,
            data_snapshot=snapshot,
            store=store,
            factor_version=args.factor_version,
            strategy_version=args.strategy_version,
            qlib_version=args.qlib_version,
            lane=args.lane,
        )
        if args.lane == "qlib":
            refreshed_calendar, refreshed_snapshot = _load_runtime_inputs()
            outcomes.extend(
                run_due_once(
                    now=datetime.now().astimezone().replace(tzinfo=None),
                    trading_days=refreshed_calendar,
                    data_snapshot=refreshed_snapshot,
                    store=store,
                    factor_version=args.factor_version,
                    strategy_version=args.strategy_version,
                    qlib_version=args.qlib_version,
                    lane="strategy",
                    event_trigger=True,
                )
            )
        if outcomes:
            print(json.dumps(outcomes, ensure_ascii=False, default=str), flush=True)
        if args.once:
            return _once_exit_code(outcomes)
        time.sleep(max(15, min(int(args.poll_seconds), 300)))


if __name__ == "__main__":
    raise SystemExit(main())

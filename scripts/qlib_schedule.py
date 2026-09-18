"""Qlib 日频 A 股研究主链的周、月、季固定调度。"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, time
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quant.qlib.paths import resolve_data_path
from quant.qlib.jobs import JobManager, job_progress_callback
from quant.qlib.registry import Registry
from scripts.qlib_job_worker import dispatch_job


Dispatcher = Callable[[str, dict[str, Any], Callable[..., None]], dict[str, Any]]

PIPELINES = {
    "weekly": (
        "collect_six_years",
        "quality_six_years",
        "build_f4_references",
        "export_six_years",
        "workflow_baseline",
        "backtest_ashare",
    ),
    "monthly": (
        "collect_six_years",
        "quality_six_years",
        "build_f4_references",
        "export_six_years",
        "workflow_monthly_walk_forward",
        "backtest_ashare",
    ),
    "quarterly": (
        "collect_six_years",
        "quality_six_years",
        "build_f4_references",
        "export_six_years",
        "workflow_quarterly_matrix",
        "backtest_ashare",
    ),
}


def is_intraday_window(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    current = now.time()
    return time(9, 15) <= current <= time(15, 15)


def should_run(now: datetime, *, force: bool = False) -> bool:
    if is_intraday_window(now):
        return False
    if force:
        return True
    return now.weekday() == 5


def monthly_pit_refresh(now: datetime) -> bool:
    return (
        now.weekday() == 5
        and now.day <= 7
        and now.time() >= time(18, 30)
        and not is_intraday_window(now)
    )


def quarterly_walk_forward(now: datetime) -> bool:
    return monthly_pit_refresh(now) and now.month in {1, 4, 7, 10}


def select_mode(now: datetime) -> str:
    """Select exactly one fixed Qlib chain with quarterly-first priority."""

    if quarterly_walk_forward(now):
        return "quarterly"
    if monthly_pit_refresh(now):
        return "monthly"
    return "weekly"


def _is_due(mode: str, now: datetime, force: bool) -> bool:
    if is_intraday_window(now):
        return False
    if force:
        return True
    if mode == "weekly":
        return should_run(now)
    if mode == "monthly":
        return monthly_pit_refresh(now)
    if mode == "quarterly":
        return quarterly_walk_forward(now)
    raise ValueError(f"unsupported schedule mode: {mode}")


def _progress(*_args: Any) -> None:
    return None


def _audit_store(
    dispatcher: Dispatcher,
    store: Registry | None,
) -> Registry | None:
    if store is not None:
        return store
    if dispatcher is dispatch_job:
        return Registry(resolve_data_path("qlib_meta.db"))
    return None


def _audit_cycle(store: Registry | None, event_type: str, result: dict[str, Any]) -> None:
    if store is None:
        return
    store.audit(
        event_type,
        "qlib_schedule",
        str(result.get("mode") or "unknown"),
        result,
    )


def _failed(
    *,
    mode: str,
    checked_at: str,
    stages: dict[str, Any],
    reason_codes: list[str],
    workflow_run_ids: list[str] | None = None,
    status: str = "failed",
) -> dict[str, Any]:
    return {
        "status": status,
        "mode": mode,
        "checked_at": checked_at,
        "reason_codes": reason_codes,
        "workflow_run_ids": workflow_run_ids or [],
        "stages": stages,
    }


def run_six_year_cycle(
    *,
    mode: str,
    force: bool = False,
    now: datetime | None = None,
    dispatcher: Dispatcher = dispatch_job,
    store: Registry | None = None,
) -> dict[str, Any]:
    if mode not in PIPELINES:
        raise ValueError(f"unsupported schedule mode: {mode}")
    current = now or datetime.now()
    checked_at = current.astimezone().isoformat(timespec="seconds")
    if not _is_due(mode, current, force):
        return {
            "status": "skipped",
            "mode": mode,
            "reason": "计划尚未到期或处于盘中安全时段",
            "checked_at": checked_at,
        }

    audit_store = _audit_store(dispatcher, store)
    stages: dict[str, Any] = {}
    collection = dispatcher("collect_six_years", {}, _progress)
    stages["collect_six_years"] = collection
    if collection.get("no_op") is True:
        result = {
            "status": "succeeded",
            "mode": mode,
            "no_op": True,
            "reason": "没有新的交易日数据",
            "checked_at": checked_at,
            "stages": stages,
        }
        _audit_cycle(audit_store, "schedule_cycle_no_op", result)
        return result

    quality = dispatcher("quality_six_years", {}, _progress)
    stages["quality_six_years"] = quality
    if quality.get("passed") is not True:
        result = _failed(
            mode=mode,
            checked_at=checked_at,
            stages=stages,
            reason_codes=["six_year_quality_failed"],
        )
        _audit_cycle(audit_store, "schedule_cycle_failed", result)
        return result

    references = dispatcher("build_f4_references", {}, _progress)
    stages["build_f4_references"] = references
    if references.get("status") != "passed":
        result = _failed(
            mode=mode,
            checked_at=checked_at,
            stages=stages,
            reason_codes=["f4_reference_build_failed"],
        )
        _audit_cycle(audit_store, "schedule_cycle_failed", result)
        return result

    exported = dispatcher("export_six_years", {}, _progress)
    stages["export_six_years"] = exported
    if exported.get("status") in {"failed", "partial_failed", "incomplete"}:
        result = _failed(
            mode=mode,
            checked_at=checked_at,
            stages=stages,
            reason_codes=["qlib_export_failed"],
        )
        _audit_cycle(audit_store, "schedule_cycle_failed", result)
        return result

    workflow_kind = next(
        kind for kind in PIPELINES[mode] if kind.startswith("workflow_")
    )
    workflow = dispatcher(workflow_kind, {}, _progress)
    stages[workflow_kind] = workflow
    workflow_run_ids = [
        str(value) for value in workflow.get("workflow_run_ids", []) if str(value)
    ]
    if workflow.get("status") == "partial_failed":
        result = _failed(
            mode=mode,
            checked_at=checked_at,
            stages=stages,
            reason_codes=["workflow_matrix_partial_failed"],
            workflow_run_ids=workflow_run_ids,
            status="partial_failed",
        )
        _audit_cycle(audit_store, "schedule_cycle_failed", result)
        return result
    if workflow.get("artifacts_complete") is not True or not workflow_run_ids:
        result = _failed(
            mode=mode,
            checked_at=checked_at,
            stages=stages,
            reason_codes=["recorder_artifacts_incomplete"],
            workflow_run_ids=workflow_run_ids,
        )
        _audit_cycle(audit_store, "schedule_cycle_failed", result)
        return result

    backtests: list[dict[str, Any]] = []
    for workflow_run_id in workflow_run_ids:
        backtest = dispatcher(
            "backtest_ashare",
            {"workflow_run_id": workflow_run_id},
            _progress,
        )
        backtests.append(backtest)
    stages["backtest_ashare"] = backtests[0] if len(backtests) == 1 else backtests
    complete_backtests = all(
        item.get("status") == "succeeded"
        and {"qlib_official", "xuanji_ashare"}.issubset(set(item.get("engines") or []))
        and bool(item.get("gate_status"))
        for item in backtests
    )
    if not complete_backtests:
        result = _failed(
            mode=mode,
            checked_at=checked_at,
            stages=stages,
            reason_codes=["dual_backtest_or_gate_incomplete"],
            workflow_run_ids=workflow_run_ids,
        )
        _audit_cycle(audit_store, "schedule_cycle_failed", result)
        return result

    result = {
        "status": "succeeded",
        "mode": mode,
        "no_op": False,
        "checked_at": checked_at,
        "dataset_version": quality.get("dataset_version"),
        "quality_report_id": quality.get("report_id"),
        "workflow_run_ids": workflow_run_ids,
        "stages": stages,
    }
    _audit_cycle(audit_store, "schedule_cycle_succeeded", result)
    return result


_SCHEDULE_STAGE_RANGES = {
    "collect_six_years": (0.00, 0.55, "collect"),
    "quality_six_years": (0.55, 0.65, "quality"),
    "build_f4_references": (0.65, 0.72, "references"),
    "export_six_years": (0.72, 0.80, "export_stage"),
    "workflow_baseline": (0.80, 0.92, "workflow"),
    "workflow_monthly_walk_forward": (0.80, 0.92, "workflow"),
    "workflow_quarterly_matrix": (0.80, 0.92, "workflow"),
    "backtest_ashare": (0.92, 0.99, "backtest"),
}


def run_registered_cycle(
    *,
    mode: str,
    force: bool = False,
    now: datetime | None = None,
    dispatcher: Dispatcher = dispatch_job,
    store: Registry | None = None,
    pid: int | None = None,
) -> dict[str, Any]:
    """运行计划周期，并把长任务状态持续登记到 Qlib 控制索引。"""
    current = now or datetime.now()
    if mode in {"auto", "adaptive"}:
        mode = select_mode(current)
    registry = store or Registry(resolve_data_path("qlib_meta.db"))
    manager = JobManager(registry)
    manager.reconcile_orphaned_active_jobs()
    active = registry.active_heavy_job()
    if active is not None:
        result = {
            "status": "skipped",
            "mode": mode,
            "reason_code": "heavy_job_active",
            "active_job_id": active["id"],
            "active_job_kind": active["kind"],
            "checked_at": current.isoformat(timespec="seconds"),
        }
        registry.audit(
            "schedule_cycle_skipped",
            "qlib_schedule",
            mode,
            result,
        )
        return result
    job = manager.create(
        f"schedule_{mode}",
        heavy=True,
        params={"mode": mode, "force": bool(force)},
    )
    run_token = f"schedule_{uuid.uuid4().hex}"
    manager.transition(
        job["id"],
        "running",
        message=f"{mode} 研究周期已启动",
        pid=int(pid or os.getpid()),
        stage="collect",
        run_token=run_token,
    )
    persist_progress = job_progress_callback(registry, job["id"], run_token)

    def tracked_dispatch(
        kind: str,
        params: dict[str, Any],
        _progress: Callable[..., None],
    ) -> dict[str, Any]:
        start, end, stage = _SCHEDULE_STAGE_RANGES.get(
            kind,
            (0.0, 0.99, "workflow"),
        )
        persist_progress(start, stage, f"开始：{kind}")

        def stage_progress(
            value: float,
            stage_or_message: str,
            message: str | None = None,
        ) -> None:
            bounded = max(0.0, min(float(value), 1.0))
            detail = str(message if message is not None else stage_or_message)
            persist_progress(start + (end - start) * bounded, stage, detail)

        result = dispatcher(kind, params, stage_progress)
        persist_progress(end, stage, f"完成：{kind}")
        return result

    try:
        result = run_six_year_cycle(
            mode=mode,
            force=force,
            now=current,
            dispatcher=tracked_dispatch,
            store=registry,
        )
        result = {**result, "schedule_job_id": job["id"]}
        if result.get("status") in {"succeeded", "skipped"}:
            manager.transition(
                job["id"],
                "succeeded",
                message="计划周期完成",
                result=result,
                stage="report",
                run_token=run_token,
            )
            registry.audit(
                "job_succeeded",
                "job",
                job["id"],
                {"kind": f"schedule_{mode}"},
            )
        else:
            manager.transition(
                job["id"],
                "failed",
                message="计划周期未通过完整性门禁",
                result=result,
                stage="report",
                run_token=run_token,
            )
            registry.audit(
                "job_failed",
                "job",
                job["id"],
                {"kind": f"schedule_{mode}", "status": result.get("status")},
            )
        return result
    except Exception as exc:
        failure = {"error": str(exc), "mode": mode, "schedule_job_id": job["id"]}
        manager.transition(
            job["id"],
            "failed",
            message=str(exc)[:500],
            result=failure,
            stage="report",
            run_token=run_token,
        )
        registry.audit(
            "job_failed",
            "job",
            job["id"],
            {"kind": f"schedule_{mode}", "error": str(exc)[:500]},
        )
        raise


def run_weekly(
    *,
    force: bool = False,
    now: datetime | None = None,
    dispatcher: Dispatcher = dispatch_job,
    store: Registry | None = None,
) -> dict[str, Any]:
    return run_six_year_cycle(
        mode="weekly",
        force=force,
        now=now,
        dispatcher=dispatcher,
        store=store,
    )


def schedule_status(store: Registry, mode: str, *, limit: int = 500) -> dict[str, Any]:
    """统计最近同模式的真实完整周期；no-op/skipped 不计数也不中断。"""
    successes = 0
    latest: dict[str, Any] | None = None
    for event in store.list_audit_events(limit):
        if event.get("event_type") not in {
            "schedule_cycle_succeeded",
            "schedule_cycle_failed",
        }:
            continue
        detail = event.get("detail") or {}
        if detail.get("mode") != mode:
            continue
        if latest is None:
            latest = event
        if event.get("event_type") == "schedule_cycle_failed":
            break
        if detail.get("status") == "succeeded" and detail.get("no_op") is not True:
            successes += 1
    return {
        "mode": mode,
        "consecutive_successes": successes,
        "latest_complete_cycle": latest,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--mode",
        choices=["adaptive", "weekly", "monthly", "quarterly"],
        default="adaptive",
    )
    args = parser.parse_args()
    now = datetime.now()
    mode = select_mode(now) if args.mode == "adaptive" else args.mode
    result = run_registered_cycle(mode=mode, force=args.force, now=now)
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0 if result["status"] in {"succeeded", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

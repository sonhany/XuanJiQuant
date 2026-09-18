"""Qlib research controller.

This process is intentionally lightweight. It validates named actions, stores
job metadata in the external Qlib registry, and starts fixed worker commands.
It never executes caller-provided commands or reads the trading SQLite cache.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quant.qlib.jobs import ActiveJobError, JobManager, job_is_orphaned
from quant.qlib.artifact_importer import REQUIRED_ARTIFACTS
from quant.qlib.capabilities import build_capability_catalog
from quant.qlib.paths import data_root, resolve_data_path
from quant.qlib.promotion_gate import GATE_VERSION
from quant.qlib.registry import Registry
from quant.qlib.shadow_signal import write_shadow_signal


READ_ONLY_ACTIONS = {
    "status",
    "catalog",
    "datasets",
    "jobs",
    "experiments",
    "models",
    "reports",
    "job_log",
    "quality_reports",
    "workflow_runs",
    "backtests",
    "schedule_status",
}
CONTROL_ACTIONS = {
    "setup",
    "collect_one_year",
    "collect_six_years",
    "build_point_in_time",
    "quality_six_years",
    "export_six_years",
    "export",
    "train_smoke",
    "train_one_year",
    "train_walk_forward",
    "train_regime",
    "cancel_job",
    "promote_shadow",
    "workflow_baseline",
    "workflow_monthly_walk_forward",
    "workflow_quarterly_matrix",
    "backtest_ashare",
    "resolve_backtest_divergence",
}
JOB_ACTIONS = {
    "setup",
    "collect_one_year",
    "collect_six_years",
    "build_point_in_time",
    "quality_six_years",
    "export_six_years",
    "export",
    "train_smoke",
    "train_one_year",
    "train_walk_forward",
    "train_regime",
    "workflow_baseline",
    "workflow_monthly_walk_forward",
    "workflow_quarterly_matrix",
    "backtest_ashare",
}
COMMON_FIELDS = {"action", "token", "__id"}
FIELDS_BY_ACTION = {
    "status": COMMON_FIELDS,
    "catalog": COMMON_FIELDS,
    "datasets": COMMON_FIELDS | {"limit"},
    "jobs": COMMON_FIELDS | {"limit"},
    "experiments": COMMON_FIELDS | {"limit"},
    "models": COMMON_FIELDS | {"limit"},
    "reports": COMMON_FIELDS | {"limit"},
    "job_log": COMMON_FIELDS | {"job_id", "tail"},
    "quality_reports": COMMON_FIELDS | {"limit"},
    "workflow_runs": COMMON_FIELDS | {"limit"},
    "backtests": COMMON_FIELDS | {"limit", "workflow_run_id"},
    "schedule_status": COMMON_FIELDS,
    "setup": COMMON_FIELDS,
    "collect_one_year": COMMON_FIELDS,
    "collect_six_years": COMMON_FIELDS,
    "build_point_in_time": COMMON_FIELDS,
    "quality_six_years": COMMON_FIELDS,
    "export_six_years": COMMON_FIELDS,
    "export": COMMON_FIELDS | {"dataset_id"},
    "train_smoke": COMMON_FIELDS,
    "train_one_year": COMMON_FIELDS | {"dataset_id"},
    "train_walk_forward": COMMON_FIELDS,
    "train_regime": COMMON_FIELDS,
    "cancel_job": COMMON_FIELDS | {"job_id"},
    "promote_shadow": COMMON_FIELDS | {"model_id"},
    "workflow_baseline": COMMON_FIELDS,
    "workflow_monthly_walk_forward": COMMON_FIELDS,
    "workflow_quarterly_matrix": COMMON_FIELDS,
    "backtest_ashare": COMMON_FIELDS | {"workflow_run_id"},
    "resolve_backtest_divergence": COMMON_FIELDS
    | {"workflow_run_id", "review_note"},
}
ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")
VENV_STATUS_TTL_SECONDS = 300.0
_VENV_STATUS_CACHE: dict[str, Any] = {
    "expires_at": 0.0,
    "result": None,
}


def ok(data: dict[str, Any]) -> dict[str, Any]:
    return {"success": True, "data": data}


def fail(error: str) -> dict[str, Any]:
    return {"success": False, "error": error}


def registry() -> Registry:
    return Registry(resolve_data_path("qlib_meta.db"))


def validate_request(req: dict[str, Any]) -> dict[str, Any]:
    request = dict(req or {})
    action = str(request.get("action") or "status")
    if action not in READ_ONLY_ACTIONS | CONTROL_ACTIONS:
        raise ValueError(f"unsupported action: {action}")
    allowed = FIELDS_BY_ACTION[action]
    extras = sorted(set(request) - allowed)
    if extras:
        raise ValueError(f"unsupported request field: {extras[0]}")
    for field in ("job_id", "model_id", "dataset_id", "workflow_run_id"):
        if field in request and not ID_PATTERN.fullmatch(str(request[field] or "")):
            raise ValueError(f"invalid {field}")
    if action == "resolve_backtest_divergence":
        note = str(request.get("review_note") or "").strip()
        if not note or len(note) > 1000:
            raise ValueError("review_note must contain 1-1000 characters")
        request["review_note"] = note
    request["action"] = action
    return request


def worker_command(job_id: str) -> list[str]:
    return [
        str(ROOT / ".venv-qlib" / "Scripts" / "python.exe"),
        str(ROOT / "scripts" / "qlib_job_worker.py"),
        "--job-id",
        job_id,
    ]


def start_worker(job_id: str) -> int:
    command = worker_command(job_id)
    if not Path(command[0]).exists():
        raise RuntimeError("Qlib isolated Python is not installed")
    log_path = resolve_data_path("jobs", f"{job_id}.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "QLIB_DATA_ROOT": str(data_root()),
        "OMP_NUM_THREADS": os.environ.get("QLIB_OMP_NUM_THREADS", "8"),
    }
    creationflags = 0
    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
        )
    with log_path.open("a", encoding="utf-8") as log_handle:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
    registry().update_job(job_id, pid=process.pid)
    return int(process.pid)


def _venv_status() -> dict[str, Any]:
    python_path = ROOT / ".venv-qlib" / "Scripts" / "python.exe"
    result = {
        "python": str(python_path),
        "ready": False,
        "python_version": "",
        "qlib_version": "",
        "lightgbm_version": "",
        "xgboost_version": "",
        "hmmlearn_version": "",
        "error": "",
    }
    if not python_path.exists():
        return result
    now = time.monotonic()
    cached = _VENV_STATUS_CACHE.get("result")
    if cached and now < float(_VENV_STATUS_CACHE.get("expires_at") or 0.0):
        return dict(cached)
    probe = (
        "import json,platform,importlib.metadata as metadata;"
        "print(json.dumps({'python':platform.python_version(),"
        "'qlib':metadata.version('pyqlib'),"
        "'lightgbm':metadata.version('lightgbm'),"
        "'xgboost':metadata.version('xgboost'),"
        "'hmmlearn':metadata.version('hmmlearn')}))"
    )
    try:
        completed = subprocess.run(
            [str(python_path), "-c", probe],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
            check=True,
        )
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
        result.update(
            {
                "ready": True,
                "python_version": payload["python"],
                "qlib_version": payload["qlib"],
                "lightgbm_version": payload["lightgbm"],
                "xgboost_version": payload.get("xgboost", ""),
                "hmmlearn_version": payload["hmmlearn"],
            }
        )
        _VENV_STATUS_CACHE["result"] = dict(result)
        _VENV_STATUS_CACHE["expires_at"] = now + VENV_STATUS_TTL_SECONDS
    except Exception as exc:
        if cached:
            result = dict(cached)
            result["error"] = f"cached after probe failure: {exc}"[:500]
        else:
            result["error"] = str(exc)[:500]
    return result


def _workflow_view(workflow: dict[str, Any] | None) -> dict[str, Any] | None:
    if workflow is None:
        return None
    result = dict(workflow)
    artifacts = result.get("artifacts") or {}
    result["artifacts_complete"] = all(name in artifacts for name in REQUIRED_ARTIFACTS)
    return result


def _latest_workflow_evidence(workflows: list[dict[str, Any]]) -> dict[str, Any] | None:
    decorated = [_workflow_view(item) for item in workflows]
    complete = [
        item
        for item in decorated
        if item is not None
        and item.get("status") == "succeeded"
        and item.get("artifacts_complete") is True
    ]
    latest = decorated[0] if decorated else None
    if latest is None:
        return None
    latest["available_handlers"] = sorted(
        {str(item.get("handler")) for item in complete if item.get("handler")}
    )
    latest["available_models"] = sorted(
        {str(item.get("model_type")) for item in complete if item.get("model_type")}
    )
    return latest


def capability_catalog(
    environment: dict[str, Any],
    quality: dict[str, Any] | None,
    latest_workflow: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    return build_capability_catalog(
        environment,
        quality,
        latest_workflow,
        {"xgboost": bool(environment.get("xgboost_version"))},
    )


def _reports(limit: int) -> list[dict[str, Any]]:
    root = resolve_data_path("reports")
    root.mkdir(parents=True, exist_ok=True)
    result = []
    for path in sorted(root.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]:
        result.append(
            {
                "name": path.name,
                "size": path.stat().st_size,
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
            }
        )
    return result


def _six_year_quality() -> dict[str, Any] | None:
    path = resolve_data_path("datasets", "a_share_6y_daily", "quality_report.json")
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"passed": False, "reason_codes": ["quality_report_unreadable"]}


def _job_log(job_id: str, tail: int) -> dict[str, Any]:
    path = resolve_data_path("jobs", f"{job_id}.log")
    if not path.exists():
        return {"job_id": job_id, "lines": [], "exists": False}
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return {"job_id": job_id, "lines": lines[-tail:], "exists": True}


def _job_status_view(job: dict[str, Any]) -> dict[str, Any]:
    result = dict(job)
    if job_is_orphaned(result):
        result.update(
            {
                "status": "interrupted",
                "message": "worker process is no longer running",
                "stale_persisted_status": True,
            }
        )
    return result


def _cancel_job(job_id: str) -> dict[str, Any]:
    store = registry()
    manager = JobManager(store)
    job = store.get_job(job_id)
    if job is None:
        raise KeyError(job_id)
    if job["status"] == "queued":
        return manager.transition(job_id, "cancelled", message="已取消")
    if job["status"] != "running":
        raise ValueError(f"job is not cancellable: {job['status']}")
    manager.transition(job_id, "cancelling", message="正在取消")
    pid = int(job.get("pid") or 0)
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    return manager.transition(job_id, "cancelled", message="已取消")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _latest_shadow_predictions(path: Path) -> list[dict[str, Any]]:
    import pandas as pd

    payload = pd.read_pickle(path)
    if isinstance(payload, pd.DataFrame):
        if "score" in payload.columns:
            prediction = payload["score"]
        elif len(payload.columns) == 1:
            prediction = payload.iloc[:, 0]
        else:
            raise ValueError("Qlib pred.pkl has no unambiguous score column")
    elif isinstance(payload, pd.Series):
        prediction = payload
    else:
        raise ValueError("Qlib pred.pkl is not a Series or DataFrame")
    if not isinstance(prediction.index, pd.MultiIndex):
        raise ValueError("Qlib pred.pkl has no datetime/instrument MultiIndex")
    if "datetime" not in prediction.index.names or "instrument" not in prediction.index.names:
        raise ValueError("Qlib pred.pkl index is missing datetime/instrument")
    frame = prediction.rename("score").reset_index()
    frame["datetime"] = pd.to_datetime(frame["datetime"], errors="coerce")
    frame["score"] = pd.to_numeric(frame["score"], errors="coerce")
    frame = frame.dropna(subset=["datetime", "score"])
    if frame.empty:
        raise ValueError("Qlib pred.pkl has no valid prediction")
    latest = frame["datetime"].max()
    latest_frame = frame.loc[frame["datetime"] == latest].sort_values(
        ["score", "instrument"],
        ascending=[False, True],
    )
    return [
        {
            "date": latest.strftime("%Y-%m-%d"),
            "instrument": str(row.instrument),
            "score": float(row.score),
            "rank": rank,
        }
        for rank, row in enumerate(latest_frame.itertuples(index=False), start=1)
    ]


def _promote_shadow_model(store: Registry, model_id: str) -> dict[str, Any]:
    model = store.get_model(model_id)
    if model is None:
        raise KeyError(model_id)
    if model["status"] != "candidate":
        raise ValueError("only candidate models may be promoted to shadow")
    workflow = next(
        (
            item
            for item in store.list_workflow_runs(500)
            if item.get("experiment_id") == model.get("experiment_id")
        ),
        None,
    )
    if workflow is None:
        raise ValueError("candidate model has no imported Qlib workflow run")
    gate = dict(workflow.get("gate") or {})
    if gate.get("gate_version") != GATE_VERSION or gate.get("status") != "candidate":
        raise ValueError("workflow promotion gate is not candidate at current version")
    signal_hash = str(gate.get("signal_hash") or "")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", signal_hash):
        raise ValueError("workflow promotion gate has no valid signal hash")

    root = Path(workflow.get("resolved_path") or "").resolve()
    if workflow.get("path_state") not in {"active", "mapped_legacy"} or not root.is_dir():
        raise ValueError("workflow artifact path is not available")
    expected_hashes = dict(workflow.get("artifacts") or {})
    for name in ("params.pkl", "pred.pkl"):
        path = (root / name).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("workflow artifact path traversal rejected") from exc
        expected = str(expected_hashes.get(name) or "")
        if not path.is_file() or _sha256_file(path) != expected:
            raise ValueError(f"workflow artifact hash mismatch: {name}")
    model_path = Path(model["path"]).resolve()
    if not model_path.is_file() or _sha256_file(model_path) != model.get("sha256"):
        raise ValueError("model artifact hash mismatch")

    signal = write_shadow_signal(
        output_dir=resolve_data_path("shadow_signals"),
        model_id=model_id,
        workflow_run_id=workflow["id"],
        dataset_version=workflow["dataset_version"],
        signal_hash=signal_hash,
        predictions=_latest_shadow_predictions(root / "pred.pkl"),
    )
    updated = store.update_model_status(model_id, "shadow")
    store.audit(
        "model_promoted_shadow",
        "model",
        model_id,
        {
            "previous": "candidate",
            "workflow_run_id": workflow["id"],
            "gate_id": gate.get("gate_id"),
            "signal_path": str(signal["path"]),
            "signal_sha256": signal["sha256"],
        },
    )
    return {
        "model": updated,
        "workflow_run_id": workflow["id"],
        "gate": gate,
        "signal": signal,
    }


def handle(
    req: dict[str, Any],
    *,
    worker_starter: Callable[[str], int] = start_worker,
) -> dict[str, Any]:
    request = validate_request(req)
    action = request["action"]
    store = registry()
    limit = max(1, min(int(request.get("limit", 100)), 500))

    if action == "status":
        jobs = [_job_status_view(job) for job in store.list_jobs(20)]
        environment = _venv_status()
        quality = _six_year_quality()
        workflows = store.list_workflow_runs(500)
        latest_workflow = _latest_workflow_evidence(workflows)
        from scripts.qlib_schedule import schedule_status

        return ok(
            {
                "environment": environment,
                "data_root": str(data_root()),
                "data_root_override": bool(os.environ.get("QLIB_DATA_ROOT", "").strip()),
                "registry": str(store.db_path),
                "active_job": next(
                    (job for job in jobs if job["status"] in {"queued", "running", "cancelling"}),
                    None,
                ),
                "latest_job": jobs[0] if jobs else None,
                "six_year_quality": quality,
                "latest_workflow": latest_workflow,
                "schedule": {
                    mode: schedule_status(store, mode)
                    for mode in ("weekly", "monthly", "quarterly")
                },
                "safety_boundary": "offline_research_only",
                "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "catalog": capability_catalog(environment, quality, latest_workflow),
            }
        )
    if action == "catalog":
        environment = _venv_status()
        quality = _six_year_quality()
        workflows = store.list_workflow_runs(500)
        latest_workflow = _latest_workflow_evidence(workflows)
        return ok({"catalog": capability_catalog(environment, quality, latest_workflow)})
    if action == "datasets":
        return ok({"items": store.list_datasets(limit)})
    if action == "jobs":
        return ok({"items": [_job_status_view(job) for job in store.list_jobs(limit)]})
    if action == "experiments":
        return ok({"items": store.list_experiments(limit)})
    if action == "models":
        return ok({"items": store.list_models(limit)})
    if action == "reports":
        return ok({"items": _reports(limit)})
    if action == "job_log":
        return ok(_job_log(str(request["job_id"]), max(1, min(int(request.get("tail", 300)), 2000))))
    if action == "quality_reports":
        return ok({"items": store.list_quality_reports(limit)})
    if action == "workflow_runs":
        return ok(
            {
                "items": [
                    _workflow_view(workflow)
                    for workflow in store.list_workflow_runs(limit)
                ]
            }
        )
    if action == "backtests":
        return ok(
            {
                "items": store.list_backtest_results(
                    request.get("workflow_run_id"),
                    limit,
                )
            }
        )
    if action == "schedule_status":
        from scripts.qlib_schedule import schedule_status

        return ok(
            {
                "modes": {
                    mode: schedule_status(store, mode)
                    for mode in ("weekly", "monthly", "quarterly")
                }
            }
        )
    if action in JOB_ACTIONS:
        params = {
            key: request[key]
            for key in ("dataset_id", "workflow_run_id")
            if key in request
        }
        job = JobManager(store).create(action, heavy=action != "setup", params=params)
        try:
            pid = worker_starter(job["id"])
        except Exception as exc:
            JobManager(store).transition(job["id"], "running", message="启动失败")
            JobManager(store).transition(job["id"], "failed", message=str(exc)[:500])
            raise
        store.audit("job_submitted", "job", job["id"], {"kind": action, "pid": pid})
        return ok({"job": store.get_job(job["id"])})
    if action == "cancel_job":
        job = _cancel_job(str(request["job_id"]))
        store.audit("job_cancelled", "job", job["id"], {})
        return ok({"job": job})
    if action == "promote_shadow":
        model_id = str(request["model_id"])
        return ok(_promote_shadow_model(store, model_id))
    if action == "resolve_backtest_divergence":
        from quant.qlib.promotion_gate import evaluate_promotion_gate

        workflow_run_id = str(request["workflow_run_id"])
        workflow = store.get_workflow_run(workflow_run_id)
        if workflow is None:
            raise KeyError(workflow_run_id)
        current_gate = dict(workflow.get("gate") or {})
        if current_gate.get("status") != "review_required":
            raise ValueError("workflow gate is not awaiting divergence review")
        resolved_gate = evaluate_promotion_gate(
            quality_passed=bool(current_gate.get("quality_passed")),
            signal_metrics=dict(current_gate.get("signal_metrics") or {}),
            official_backtest=dict(current_gate.get("official_backtest") or {}),
            ashare_backtest=dict(current_gate.get("ashare_backtest") or {}),
            divergence_reviewed=True,
        )
        resolved_gate.update(
            {
                "signal_hash": current_gate.get("signal_hash"),
                "review_note": request["review_note"],
                "reviewed_at": datetime.now()
                .astimezone()
                .isoformat(timespec="seconds"),
            }
        )
        updated = store.update_workflow_gate(workflow_run_id, resolved_gate)
        store.audit(
            "backtest_divergence_reviewed",
            "workflow_run",
            workflow_run_id,
            {"status": resolved_gate["status"], "review_note": request["review_note"]},
        )
        return ok({"workflow": updated, "gate": resolved_gate})
    raise ValueError(f"unsupported action: {action}")


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        req_id = None
        try:
            request = json.loads(line)
            req_id = request.pop("__id", None)
            response = handle(request)
        except ActiveJobError as exc:
            response = fail(str(exc))
        except Exception as exc:
            response = fail(str(exc))
        if req_id is not None:
            response["__id"] = req_id
        print(json.dumps(response, ensure_ascii=False, default=str), flush=True)


if __name__ == "__main__":
    main()

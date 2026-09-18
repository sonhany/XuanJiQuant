from __future__ import annotations

import json
import os
import uuid
from typing import Any

from .registry import Registry, utc_now


class ActiveJobError(RuntimeError):
    pass


class InvalidTransitionError(RuntimeError):
    pass


TRANSITIONS = {
    "queued": {"running", "cancelled"},
    "running": {"succeeded", "failed", "cancelling", "interrupted"},
    "cancelling": {"cancelled", "failed", "interrupted"},
    "succeeded": set(),
    "failed": set(),
    "cancelled": set(),
    "interrupted": set(),
}


def pid_alive(pid: Any) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel32.GetExitCodeProcess.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel32.OpenProcess(0x1000, False, int(pid))
            if not handle:
                return False
            try:
                exit_code = wintypes.DWORD()
                return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))) and exit_code.value == 259
            finally:
                kernel32.CloseHandle(handle)
        except (OSError, TypeError, ValueError):
            return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def job_is_orphaned(job: dict[str, Any], *, process_alive=None) -> bool:
    process_alive = process_alive or pid_alive
    return (
        str(job.get("status") or "") in {"running", "cancelling"}
        and not process_alive(job.get("pid"))
    )


class JobManager:
    def __init__(self, registry: Registry):
        self.registry = registry

    def create(
        self,
        kind: str,
        *,
        heavy: bool = True,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if heavy:
            self.reconcile_orphaned_active_jobs()
            active = self.registry.active_heavy_job()
            if active is not None:
                raise ActiveJobError(
                    f"heavy job already active: {active['id']} ({active['kind']})"
                )
        now = utc_now()
        row = {
            "id": f"qlib_{uuid.uuid4().hex[:16]}",
            "kind": str(kind),
            "status": "queued",
            "heavy": bool(heavy),
            "progress": 0.0,
            "params": params or {},
            "result": {},
            "created_at": now,
            "updated_at": now,
            "stage": "queued",
            "heartbeat_at": None,
            "run_token": "",
        }
        self.registry.insert_job(row)
        return self.registry.get_job(row["id"]) or row

    def reconcile_orphaned_active_jobs(self) -> list[dict[str, Any]]:
        recovered_ids = self.recover_stale_jobs()
        return [
            job
            for job_id in recovered_ids
            if (job := self.registry.get_job(job_id)) is not None
        ]

    def recover_stale_jobs(self, *, process_alive=None) -> list[str]:
        alive = process_alive or pid_alive
        recovered = []
        for job in self.registry.list_jobs(500):
            if str(job.get("status") or "") not in {"running", "cancelling"}:
                continue
            if alive(job.get("pid")):
                continue
            saved_token = str(job.get("run_token") or "")
            updated = self.transition(
                job["id"],
                "interrupted",
                message="worker process is no longer running",
                stage=str(job.get("stage") or "interrupted"),
                run_token=saved_token,
            )
            self.registry.audit(
                "job_interrupted",
                "job",
                job["id"],
                {
                    "stage": updated.get("stage"),
                    "run_token": saved_token,
                    "result_preserved": True,
                },
            )
            recovered.append(job["id"])
        return recovered

    def transition(
        self,
        job_id: str,
        new_status: str,
        *,
        message: str = "",
        result: dict[str, Any] | None = None,
        pid: int | None = None,
        stage: str | None = None,
        heartbeat_at: str | None = None,
        run_token: str | None = None,
    ) -> dict[str, Any]:
        current = self.registry.get_job(job_id)
        if current is None:
            raise KeyError(job_id)
        old_status = str(current["status"])
        if new_status not in TRANSITIONS.get(old_status, set()):
            raise InvalidTransitionError(f"{old_status} -> {new_status} is not allowed")
        now = utc_now()
        changes: dict[str, Any] = {
            "status": new_status,
            "updated_at": now,
            "message": message,
        }
        if new_status == "running":
            changes["started_at"] = now
            changes["pid"] = pid
            changes["heartbeat_at"] = heartbeat_at or now
        if new_status in {"succeeded", "failed", "cancelled", "interrupted"}:
            changes["finished_at"] = now
            changes["progress"] = 1.0 if new_status == "succeeded" else current["progress"]
        if result is not None:
            changes["result_json"] = json.dumps(result, ensure_ascii=False)
        if stage is not None:
            changes["stage"] = str(stage)
        if heartbeat_at is not None:
            changes["heartbeat_at"] = heartbeat_at
        if run_token is not None:
            changes["run_token"] = str(run_token)
        return self.registry.update_job(job_id, **changes)


def job_progress_callback(
    store: Registry,
    job_id: str,
    run_token: str,
):
    token = str(run_token)

    def progress(value: float, stage: str, message: str | None = None) -> None:
        current = store.get_job(job_id)
        if current is None:
            raise KeyError(job_id)
        if str(current.get("run_token") or "") != token:
            raise RuntimeError("job run token mismatch")
        resolved_stage = str(stage)
        resolved_message = str(message) if message is not None else resolved_stage
        if message is None:
            resolved_stage = str(current.get("stage") or "running")
        store.update_job(
            job_id,
            progress=max(0.0, min(float(value), 0.99)),
            stage=resolved_stage,
            heartbeat_at=utc_now(),
            run_token=token,
            message=resolved_message[:500],
            updated_at=utc_now(),
        )

    return progress

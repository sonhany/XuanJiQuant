from __future__ import annotations

import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


TERMINAL_STATES = {"succeeded", "failed", "blocked", "interrupted", "cancelled"}
ACTIVE_STATES = {"queued", "running"}
FORBIDDEN_PROMOTION_STATES = {
    "paper_active",
    "production_candidate",
    "approved",
    "live",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime | None = None) -> str:
    return (value or _utc_now()).astimezone(timezone.utc).isoformat(timespec="seconds")


def _assert_research_only(value: Any, *, key: str = "") -> None:
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            _assert_research_only(child_value, key=str(child_key).lower())
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            _assert_research_only(child, key=key)
        return
    if key in {"promotion_state", "target_state", "target_status"}:
        normalized = str(value or "").strip().lower()
        if normalized in FORBIDDEN_PROMOTION_STATES:
            raise ValueError(
                f"research scheduler cannot write promotion state: {normalized}"
            )


@dataclass(frozen=True, slots=True)
class JobClaim:
    claimed: bool
    job_id: str
    run_token: str
    reason: str = ""


class ResearchJobStore:
    def __init__(
        self,
        db_path: str | Path,
        *,
        lease_seconds: int = 300,
        retry_delay_seconds: int = 900,
        max_attempts: int = 3,
    ):
        self.db_path = Path(db_path)
        self.lease_seconds = max(30, int(lease_seconds))
        self.retry_delay_seconds = max(30, int(retry_delay_seconds))
        self.max_attempts = max(1, min(int(max_attempts), 10))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS research_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    heavy INTEGER NOT NULL DEFAULT 0,
                    owner_pid INTEGER,
                    run_token TEXT NOT NULL,
                    stage TEXT NOT NULL DEFAULT 'claimed',
                    progress REAL NOT NULL DEFAULT 0,
                    attempt INTEGER NOT NULL DEFAULT 1,
                    params_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    error_code TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    heartbeat_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    finished_at TEXT,
                    retry_not_before TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_research_jobs_active
                    ON research_jobs(status, heavy);
                CREATE TABLE IF NOT EXISTS research_job_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER,
                    event_type TEXT NOT NULL,
                    detail_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                """
            )
            columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(research_jobs)").fetchall()
            }
            if "retry_not_before" not in columns:
                conn.execute(
                    "ALTER TABLE research_jobs ADD COLUMN retry_not_before TEXT"
                )

    def claim(
        self,
        idempotency_key: str,
        *,
        kind: str,
        heavy: bool,
        owner_pid: int,
        params: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> JobClaim:
        identity = str(idempotency_key).strip()
        if not identity:
            raise ValueError("idempotency_key is required")
        current = (now or _utc_now()).astimezone(timezone.utc)
        stamp = _stamp(current)
        token = secrets.token_hex(16)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM research_jobs WHERE idempotency_key=?",
                (identity,),
            ).fetchone()
            if existing is not None:
                existing_status = str(existing["status"])
                retryable = existing_status in {"failed", "blocked", "interrupted"}
                if not retryable:
                    reason = (
                        "idempotent_terminal"
                        if existing_status in TERMINAL_STATES
                        else "already_claimed"
                    )
                    return JobClaim(
                        False,
                        str(existing["id"]),
                        str(existing["run_token"]),
                        reason,
                    )
                if int(existing["attempt"] or 1) >= self.max_attempts:
                    return JobClaim(
                        False,
                        str(existing["id"]),
                        str(existing["run_token"]),
                        "retry_exhausted",
                    )
                retry_not_before = str(existing["retry_not_before"] or "")
                if retry_not_before and datetime.fromisoformat(retry_not_before) > current:
                    return JobClaim(
                        False,
                        str(existing["id"]),
                        str(existing["run_token"]),
                        "retry_backoff",
                    )
            if heavy:
                active = conn.execute(
                    """
                    SELECT id, run_token FROM research_jobs
                    WHERE heavy=1 AND status IN ('queued','running')
                      AND (? IS NULL OR id<>?)
                    ORDER BY id LIMIT 1
                    """,
                    (
                        int(existing["id"]) if existing is not None else None,
                        int(existing["id"]) if existing is not None else None,
                    ),
                ).fetchone()
                if active is not None:
                    return JobClaim(
                        False,
                        str(active["id"]),
                        str(active["run_token"]),
                        "heavy_job_active",
                    )
            if existing is not None:
                job_id = str(existing["id"])
                attempt = int(existing["attempt"] or 1) + 1
                conn.execute(
                    """
                    UPDATE research_jobs
                    SET status='running', owner_pid=?, run_token=?, stage='claimed',
                        progress=0, attempt=?, params_json=?, result_json='{}',
                        error_code='', started_at=?, heartbeat_at=?, updated_at=?,
                        finished_at=NULL, retry_not_before=NULL
                    WHERE id=?
                    """,
                    (
                        int(owner_pid),
                        token,
                        attempt,
                        json.dumps(params or {}, ensure_ascii=False, sort_keys=True),
                        stamp,
                        stamp,
                        stamp,
                        job_id,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO research_job_audit (job_id, event_type, detail_json, created_at)
                    VALUES (?, 'retried', ?, ?)
                    """,
                    (
                        job_id,
                        json.dumps(
                            {"owner_pid": int(owner_pid), "attempt": attempt},
                            sort_keys=True,
                        ),
                        stamp,
                    ),
                )
                return JobClaim(True, job_id, token, "retry")
            cursor = conn.execute(
                """
                INSERT INTO research_jobs (
                    idempotency_key, kind, status, heavy, owner_pid, run_token,
                    stage, progress, params_json, created_at, started_at,
                    heartbeat_at, updated_at
                ) VALUES (?, ?, 'running', ?, ?, ?, 'claimed', 0, ?, ?, ?, ?, ?)
                """,
                (
                    identity,
                    str(kind),
                    int(bool(heavy)),
                    int(owner_pid),
                    token,
                    json.dumps(params or {}, ensure_ascii=False, sort_keys=True),
                    stamp,
                    stamp,
                    stamp,
                    stamp,
                ),
            )
            job_id = str(cursor.lastrowid)
            conn.execute(
                """
                INSERT INTO research_job_audit (job_id, event_type, detail_json, created_at)
                VALUES (?, 'claimed', ?, ?)
                """,
                (job_id, json.dumps({"owner_pid": int(owner_pid)}), stamp),
            )
        return JobClaim(True, job_id, token)

    def _owned(self, conn: sqlite3.Connection, job_id: str, run_token: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM research_jobs WHERE id=? AND run_token=?",
            (str(job_id), str(run_token)),
        ).fetchone()
        if row is None:
            raise PermissionError("research job ownership mismatch")
        return row

    def heartbeat(
        self,
        job_id: str,
        *,
        run_token: str,
        stage: str,
        progress: float,
    ) -> dict[str, Any]:
        bounded_progress = max(0.0, min(float(progress), 1.0))
        now = _stamp()
        with self._connect() as conn:
            row = self._owned(conn, job_id, run_token)
            if str(row["status"]) not in ACTIVE_STATES:
                raise ValueError("cannot heartbeat terminal research job")
            conn.execute(
                """
                UPDATE research_jobs
                SET stage=?, progress=?, heartbeat_at=?, updated_at=?
                WHERE id=?
                """,
                (str(stage)[:96], bounded_progress, now, now, str(job_id)),
            )
        result = self.get(job_id)
        if result is None:
            raise KeyError(job_id)
        return result

    def finish(
        self,
        job_id: str,
        *,
        run_token: str,
        status: str,
        result: dict[str, Any] | None = None,
        error_code: str = "",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        terminal = str(status).strip().lower()
        if terminal not in TERMINAL_STATES:
            raise ValueError(f"invalid terminal research status: {terminal}")
        payload = dict(result or {})
        _assert_research_only(payload)
        current = (now or _utc_now()).astimezone(timezone.utc)
        stamp = _stamp(current)
        retry_not_before = (
            _stamp(current + timedelta(seconds=self.retry_delay_seconds))
            if terminal in {"failed", "blocked", "interrupted"}
            else None
        )
        with self._connect() as conn:
            self._owned(conn, job_id, run_token)
            conn.execute(
                """
                UPDATE research_jobs
                SET status=?, stage=?, progress=?, result_json=?, error_code=?,
                    heartbeat_at=?, updated_at=?, finished_at=?, retry_not_before=?
                WHERE id=?
                """,
                (
                    terminal,
                    "complete" if terminal == "succeeded" else terminal,
                    1.0 if terminal == "succeeded" else 0.0,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    str(error_code)[:128],
                    stamp,
                    stamp,
                    stamp,
                    retry_not_before,
                    str(job_id),
                ),
            )
            conn.execute(
                """
                INSERT INTO research_job_audit (job_id, event_type, detail_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    str(job_id),
                    terminal,
                    json.dumps({"error_code": str(error_code)[:128]}),
                    stamp,
                ),
            )
        completed = self.get(job_id)
        if completed is None:
            raise KeyError(job_id)
        return completed

    def recover_expired(
        self,
        *,
        now: datetime | None = None,
        process_alive: Callable[[int], bool],
    ) -> list[str]:
        current = (now or _utc_now()).astimezone(timezone.utc)
        cutoff = current - timedelta(seconds=self.lease_seconds)
        recovered: list[str] = []
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT * FROM research_jobs WHERE status IN ('queued','running')"
            ).fetchall()
            for row in rows:
                heartbeat = datetime.fromisoformat(str(row["heartbeat_at"]))
                if heartbeat > cutoff:
                    continue
                pid = int(row["owner_pid"] or 0)
                if pid > 0 and process_alive(pid):
                    continue
                job_id = str(row["id"])
                stamp = _stamp(current)
                conn.execute(
                    """
                    UPDATE research_jobs
                    SET status='interrupted', stage='interrupted', error_code='owner_lost',
                        updated_at=?, finished_at=?, retry_not_before=? WHERE id=?
                    """,
                    (
                        stamp,
                        stamp,
                        _stamp(current + timedelta(seconds=self.retry_delay_seconds)),
                        job_id,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO research_job_audit (job_id, event_type, detail_json, created_at)
                    VALUES (?, 'interrupted', '{"reason":"owner_lost"}', ?)
                    """,
                    (job_id, stamp),
                )
                recovered.append(job_id)
        return recovered

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM research_jobs WHERE id=?", (str(job_id),)
            ).fetchone()
        return self._decode(row) if row is not None else None

    def find(self, idempotency_key: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM research_jobs WHERE idempotency_key=?",
                (str(idempotency_key),),
            ).fetchone()
        return self._decode(row) if row is not None else None

    def list_jobs(self, limit: int = 100) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 500))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM research_jobs ORDER BY id DESC LIMIT ?", (bounded,)
            ).fetchall()
        return [self._decode(row) for row in rows]

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["heavy"] = bool(item["heavy"])
        item["params"] = json.loads(item.pop("params_json") or "{}")
        item["result"] = json.loads(item.pop("result_json") or "{}")
        item["id"] = str(item["id"])
        return item

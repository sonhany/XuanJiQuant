from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .paths import resolve_recorded_path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Registry:
    def __init__(self, db_path: Path, read_only: bool = False):
        self.db_path = Path(db_path)
        self.read_only = bool(read_only)
        if self.read_only:
            if not self.db_path.is_file():
                raise FileNotFoundError(f"Qlib registry not found: {self.db_path}")
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        if self.read_only:
            # immutable=1 can ignore current committed rows in an active WAL.
            uri = f"{self.db_path.resolve().as_uri()}?mode=ro"
            conn = sqlite3.connect(uri, timeout=30, uri=True)
        else:
            conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        if self.read_only:
            conn.execute("PRAGMA query_only=ON")
        else:
            conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            if not self.read_only:
                conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    start_date TEXT,
                    end_date TEXT,
                    latest_date TEXT,
                    instruments INTEGER NOT NULL DEFAULT 0,
                    rows INTEGER NOT NULL DEFAULT 0,
                    coverage REAL NOT NULL DEFAULT 0,
                    path TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    heavy INTEGER NOT NULL DEFAULT 1,
                    progress REAL NOT NULL DEFAULT 0,
                    pid INTEGER,
                    message TEXT NOT NULL DEFAULT '',
                    params_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
                CREATE TABLE IF NOT EXISTS experiments (
                    id TEXT PRIMARY KEY,
                    dataset_id TEXT,
                    job_id TEXT,
                    status TEXT NOT NULL,
                    model_type TEXT NOT NULL,
                    metrics_json TEXT NOT NULL DEFAULT '{}',
                    config_json TEXT NOT NULL DEFAULT '{}',
                    path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS models (
                    id TEXT PRIMARY KEY,
                    experiment_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    model_type TEXT NOT NULL,
                    path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    metrics_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT,
                    detail_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS quality_reports (
                    id TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL,
                    dataset_version TEXT NOT NULL,
                    gate_version TEXT NOT NULL,
                    passed INTEGER NOT NULL,
                    report_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(dataset_id, dataset_version, gate_version)
                );
                CREATE TABLE IF NOT EXISTS workflow_runs (
                    id TEXT PRIMARY KEY,
                    experiment_id TEXT NOT NULL UNIQUE,
                    qlib_experiment_id TEXT NOT NULL,
                    recorder_id TEXT NOT NULL UNIQUE,
                    dataset_version TEXT NOT NULL,
                    quality_report_id TEXT NOT NULL,
                    handler TEXT NOT NULL,
                    model_type TEXT NOT NULL,
                    seed INTEGER NOT NULL,
                    config_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    recorded_path TEXT NOT NULL DEFAULT '',
                    artifacts_json TEXT NOT NULL DEFAULT '{}',
                    metrics_json TEXT NOT NULL DEFAULT '{}',
                    gate_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS backtest_results (
                    id TEXT PRIMARY KEY,
                    workflow_run_id TEXT NOT NULL,
                    engine TEXT NOT NULL,
                    signal_hash TEXT NOT NULL,
                    metrics_json TEXT NOT NULL DEFAULT '{}',
                    config_json TEXT NOT NULL DEFAULT '{}',
                    artifact_path TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(workflow_run_id, engine)
                );
                """
            )

        with self.connect() as conn:
            self._ensure_column(
                conn,
                "jobs",
                "stage",
                "TEXT NOT NULL DEFAULT 'queued'",
            )
            self._ensure_column(conn, "jobs", "heartbeat_at", "TEXT")
            self._ensure_column(
                conn,
                "jobs",
                "run_token",
                "TEXT NOT NULL DEFAULT ''",
            )

    @staticmethod
    def _ensure_column(
        conn: sqlite3.Connection,
        table: str,
        column: str,
        declaration: str,
    ) -> None:
        existing = {
            str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    def table_names(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        return [str(row["name"]) for row in rows]

    def insert_job(self, row: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    id, kind, status, heavy, progress, pid, message,
                    params_json, result_json, created_at, updated_at,
                    started_at, finished_at, stage, heartbeat_at, run_token
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["kind"],
                    row["status"],
                    int(bool(row.get("heavy", True))),
                    float(row.get("progress", 0)),
                    row.get("pid"),
                    str(row.get("message", "")),
                    json.dumps(row.get("params", {}), ensure_ascii=False),
                    json.dumps(row.get("result", {}), ensure_ascii=False),
                    row["created_at"],
                    row["updated_at"],
                    row.get("started_at"),
                    row.get("finished_at"),
                    str(row.get("stage") or "queued"),
                    row.get("heartbeat_at"),
                    str(row.get("run_token") or ""),
                ),
            )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._job_dict(row) if row else None

    def list_jobs(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (max(1, min(int(limit), 500)),),
            ).fetchall()
        return [self._job_dict(row) for row in rows]

    def active_heavy_job(self) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM jobs
                WHERE heavy=1 AND status IN ('queued','running','cancelling')
                ORDER BY created_at LIMIT 1
                """
            ).fetchone()
        return self._job_dict(row) if row else None

    def update_job(self, job_id: str, **changes: Any) -> dict[str, Any]:
        allowed = {
            "status",
            "progress",
            "pid",
            "message",
            "result_json",
            "updated_at",
            "started_at",
            "finished_at",
            "stage",
            "heartbeat_at",
            "run_token",
        }
        values = {key: value for key, value in changes.items() if key in allowed}
        if not values:
            current = self.get_job(job_id)
            if current is None:
                raise KeyError(job_id)
            return current
        fields = ", ".join(f"{key}=?" for key in values)
        with self.connect() as conn:
            conn.execute(
                f"UPDATE jobs SET {fields} WHERE id=?",
                (*values.values(), job_id),
            )
        current = self.get_job(job_id)
        if current is None:
            raise KeyError(job_id)
        return current

    def upsert_dataset(self, row: dict[str, Any]) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO datasets (
                    id, kind, status, start_date, end_date, latest_date,
                    instruments, rows, coverage, path, metadata_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    kind=excluded.kind,
                    status=excluded.status,
                    start_date=excluded.start_date,
                    end_date=excluded.end_date,
                    latest_date=excluded.latest_date,
                    instruments=excluded.instruments,
                    rows=excluded.rows,
                    coverage=excluded.coverage,
                    path=excluded.path,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    row["id"],
                    row["kind"],
                    row["status"],
                    row.get("start_date"),
                    row.get("end_date"),
                    row.get("latest_date"),
                    int(row.get("instruments", 0)),
                    int(row.get("rows", 0)),
                    float(row.get("coverage", 0)),
                    row.get("path"),
                    json.dumps(row.get("metadata", {}), ensure_ascii=False),
                    row.get("created_at", now),
                    row.get("updated_at", now),
                ),
            )

    def list_datasets(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._list_records("datasets", limit, {"metadata_json": "metadata"})

    def upsert_quality_report(self, row: dict[str, Any]) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO quality_reports (
                    id, dataset_id, dataset_version, gate_version, passed,
                    report_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dataset_id, dataset_version, gate_version) DO UPDATE SET
                    id=excluded.id,
                    passed=excluded.passed,
                    report_json=excluded.report_json,
                    created_at=excluded.created_at
                """,
                (
                    row["id"],
                    row["dataset_id"],
                    row["dataset_version"],
                    row["gate_version"],
                    int(bool(row.get("passed"))),
                    json.dumps(row.get("report", {}), ensure_ascii=False),
                    row.get("created_at", now),
                ),
            )

    def list_quality_reports(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM quality_reports ORDER BY created_at DESC LIMIT ?",
                (max(1, min(int(limit), 500)),),
            ).fetchall()
        result = []
        for row in rows:
            item = self._decode_record(dict(row), {"report_json": "report"})
            item["passed"] = bool(item["passed"])
            result.append(item)
        return result

    def upsert_experiment(self, row: dict[str, Any]) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO experiments (
                    id, dataset_id, job_id, status, model_type,
                    metrics_json, config_json, path, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    dataset_id=excluded.dataset_id,
                    job_id=excluded.job_id,
                    status=excluded.status,
                    model_type=excluded.model_type,
                    metrics_json=excluded.metrics_json,
                    config_json=excluded.config_json,
                    path=excluded.path,
                    updated_at=excluded.updated_at
                """,
                (
                    row["id"],
                    row.get("dataset_id"),
                    row.get("job_id"),
                    row["status"],
                    row["model_type"],
                    json.dumps(row.get("metrics", {}), ensure_ascii=False),
                    json.dumps(row.get("config", {}), ensure_ascii=False),
                    row.get("path"),
                    row.get("created_at", now),
                    row.get("updated_at", now),
                ),
            )

    def list_experiments(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._list_records(
            "experiments",
            limit,
            {"metrics_json": "metrics", "config_json": "config"},
        )

    def get_experiment(self, experiment_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM experiments WHERE id=?",
                (experiment_id,),
            ).fetchone()
        if row is None:
            return None
        return self._decode_record(
            dict(row),
            {"metrics_json": "metrics", "config_json": "config"},
        )

    def upsert_model(self, row: dict[str, Any]) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO models (
                    id, experiment_id, status, model_type, path, sha256,
                    metrics_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    experiment_id=excluded.experiment_id,
                    status=excluded.status,
                    model_type=excluded.model_type,
                    path=excluded.path,
                    sha256=excluded.sha256,
                    metrics_json=excluded.metrics_json,
                    updated_at=excluded.updated_at
                """,
                (
                    row["id"],
                    row["experiment_id"],
                    row["status"],
                    row["model_type"],
                    row["path"],
                    row["sha256"],
                    json.dumps(row.get("metrics", {}), ensure_ascii=False),
                    row.get("created_at", now),
                    row.get("updated_at", now),
                ),
            )

    def list_models(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._list_records("models", limit, {"metrics_json": "metrics"})

    def upsert_workflow_run(self, row: dict[str, Any]) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO workflow_runs (
                    id, experiment_id, qlib_experiment_id, recorder_id,
                    dataset_version, quality_report_id, handler, model_type,
                    seed, config_hash, status, recorded_path, artifacts_json,
                    metrics_json, gate_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(recorder_id) DO UPDATE SET
                    id=excluded.id,
                    experiment_id=excluded.experiment_id,
                    qlib_experiment_id=excluded.qlib_experiment_id,
                    dataset_version=excluded.dataset_version,
                    quality_report_id=excluded.quality_report_id,
                    handler=excluded.handler,
                    model_type=excluded.model_type,
                    seed=excluded.seed,
                    config_hash=excluded.config_hash,
                    status=excluded.status,
                    recorded_path=excluded.recorded_path,
                    artifacts_json=excluded.artifacts_json,
                    metrics_json=excluded.metrics_json,
                    gate_json=excluded.gate_json,
                    updated_at=excluded.updated_at
                """,
                (
                    row["id"],
                    row["experiment_id"],
                    row["qlib_experiment_id"],
                    row["recorder_id"],
                    row["dataset_version"],
                    row["quality_report_id"],
                    row["handler"],
                    row["model_type"],
                    int(row["seed"]),
                    row["config_hash"],
                    row["status"],
                    str(row.get("recorded_path") or ""),
                    json.dumps(row.get("artifacts", {}), ensure_ascii=False),
                    json.dumps(row.get("metrics", {}), ensure_ascii=False),
                    json.dumps(row.get("gate", {}), ensure_ascii=False),
                    row.get("created_at", now),
                    row.get("updated_at", now),
                ),
            )

    def list_workflow_runs(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM workflow_runs ORDER BY created_at DESC LIMIT ?",
                (max(1, min(int(limit), 500)),),
            ).fetchall()
        return [self._workflow_dict(row) for row in rows]

    def get_workflow_run(self, workflow_run_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_runs WHERE id=?",
                (workflow_run_id,),
            ).fetchone()
        return self._workflow_dict(row) if row else None

    def update_workflow_gate(
        self,
        workflow_run_id: str,
        gate: dict[str, Any],
    ) -> dict[str, Any]:
        with self.connect() as conn:
            conn.execute(
                "UPDATE workflow_runs SET gate_json=?, updated_at=? WHERE id=?",
                (
                    json.dumps(gate, ensure_ascii=False),
                    utc_now(),
                    workflow_run_id,
                ),
            )
        updated = self.get_workflow_run(workflow_run_id)
        if updated is None:
            raise KeyError(workflow_run_id)
        return updated

    def upsert_backtest_result(self, row: dict[str, Any]) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO backtest_results (
                    id, workflow_run_id, engine, signal_hash, metrics_json,
                    config_json, artifact_path, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workflow_run_id, engine) DO UPDATE SET
                    id=excluded.id,
                    signal_hash=excluded.signal_hash,
                    metrics_json=excluded.metrics_json,
                    config_json=excluded.config_json,
                    artifact_path=excluded.artifact_path,
                    updated_at=excluded.updated_at
                """,
                (
                    row["id"],
                    row["workflow_run_id"],
                    row["engine"],
                    row["signal_hash"],
                    json.dumps(row.get("metrics", {}), ensure_ascii=False),
                    json.dumps(row.get("config", {}), ensure_ascii=False),
                    str(row.get("artifact_path") or ""),
                    row.get("created_at", now),
                    row.get("updated_at", now),
                ),
            )

    def list_backtest_results(
        self,
        workflow_run_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 500))
        with self.connect() as conn:
            if workflow_run_id:
                rows = conn.execute(
                    """
                    SELECT * FROM backtest_results
                    WHERE workflow_run_id=?
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (workflow_run_id, bounded),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM backtest_results ORDER BY created_at DESC LIMIT ?",
                    (bounded,),
                ).fetchall()
        return [
            self._decode_record(
                dict(row),
                {"metrics_json": "metrics", "config_json": "config"},
            )
            for row in rows
        ]

    def get_model(self, model_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM models WHERE id=?",
                (model_id,),
            ).fetchone()
        if row is None:
            return None
        return self._decode_record(dict(row), {"metrics_json": "metrics"})

    def read_research_snapshot_records(self, dataset_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            conn.execute("BEGIN")
            dataset_row = conn.execute(
                "SELECT * FROM datasets WHERE id=?",
                (dataset_id,),
            ).fetchone()
            experiment_rows = conn.execute(
                """
                SELECT * FROM experiments
                WHERE dataset_id=?
                ORDER BY created_at DESC
                """,
                (dataset_id,),
            ).fetchall()
            model_rows = conn.execute(
                """
                SELECT models.* FROM models
                JOIN experiments ON experiments.id=models.experiment_id
                WHERE experiments.dataset_id=?
                ORDER BY models.created_at DESC
                """,
                (dataset_id,),
            ).fetchall()
        dataset = None
        if dataset_row is not None:
            dataset = self._decode_record(
                dict(dataset_row),
                {"metadata_json": "metadata"},
            )
        experiments = [
            self._decode_record(
                dict(row),
                {"metrics_json": "metrics", "config_json": "config"},
            )
            for row in experiment_rows
        ]
        models = [
            self._decode_record(dict(row), {"metrics_json": "metrics"})
            for row in model_rows
        ]
        return {
            "dataset": dataset,
            "experiments": experiments,
            "models": models,
        }

    def update_model_status(self, model_id: str, status: str) -> dict[str, Any]:
        with self.connect() as conn:
            conn.execute(
                "UPDATE models SET status=?, updated_at=? WHERE id=?",
                (status, utc_now(), model_id),
            )
            row = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
        if row is None:
            raise KeyError(model_id)
        return self._decode_record(dict(row), {"metrics_json": "metrics"})

    def audit(
        self,
        event_type: str,
        entity_type: str,
        entity_id: str | None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_events (
                    event_type, entity_type, entity_id, detail_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event_type,
                    entity_type,
                    entity_id,
                    json.dumps(detail or {}, ensure_ascii=False),
                    utc_now(),
                ),
            )

    def list_audit_events(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._list_records(
            "audit_events",
            limit,
            {"detail_json": "detail"},
            order_column="id",
        )

    def _list_records(
        self,
        table: str,
        limit: int,
        json_fields: dict[str, str],
        *,
        order_column: str = "created_at",
    ) -> list[dict[str, Any]]:
        allowed = {"datasets", "experiments", "models", "audit_events"}
        if table not in allowed:
            raise ValueError(f"unsupported registry table: {table}")
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM {table} ORDER BY {order_column} DESC LIMIT ?",
                (max(1, min(int(limit), 500)),),
            ).fetchall()
        return [self._decode_record(dict(row), json_fields) for row in rows]

    @staticmethod
    def _decode_record(
        item: dict[str, Any],
        json_fields: dict[str, str],
    ) -> dict[str, Any]:
        for source, target in json_fields.items():
            item[target] = json.loads(item.pop(source, "") or "{}")
        return item

    @staticmethod
    def _workflow_dict(row: sqlite3.Row) -> dict[str, Any]:
        item = Registry._decode_record(
            dict(row),
            {
                "artifacts_json": "artifacts",
                "metrics_json": "metrics",
                "gate_json": "gate",
            },
        )
        resolution = resolve_recorded_path(item.get("recorded_path"))
        item.update(
            {
                "resolved_path": resolution.resolved_path,
                "path_state": resolution.path_state,
                "resolution_reason": resolution.resolution_reason,
            }
        )
        return item

    @staticmethod
    def _job_dict(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["heavy"] = bool(item["heavy"])
        item["params"] = json.loads(item.pop("params_json") or "{}")
        item["result"] = json.loads(item.pop("result_json") or "{}")
        return item

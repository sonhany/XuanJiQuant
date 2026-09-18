import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest

from quant.qlib.registry import utc_now


def _seed_research_bundle(registry, tmp_path, dataset_id, suffix):
    now = utc_now()
    experiment_id = f"exp-{suffix}"
    model_id = f"model-{suffix}"
    registry.upsert_dataset(
        {
            "id": dataset_id,
            "kind": "research",
            "status": "ready",
            "latest_date": "2026-07-20",
            "created_at": now,
            "updated_at": now,
        }
    )
    registry.upsert_experiment(
        {
            "id": experiment_id,
            "dataset_id": dataset_id,
            "status": "succeeded",
            "model_type": "LightGBM",
            "metrics": {"rank_ic": 0.01},
            "created_at": now,
            "updated_at": now,
        }
    )
    registry.upsert_model(
        {
            "id": model_id,
            "experiment_id": experiment_id,
            "status": "candidate",
            "model_type": "LightGBM",
            "path": str(tmp_path / f"{model_id}.txt"),
            "sha256": suffix[0] * 64,
            "created_at": now,
            "updated_at": now,
        }
    )
    return experiment_id, model_id


def test_default_root_is_project_managed_data(monkeypatch):
    monkeypatch.delenv("QLIB_DATA_ROOT", raising=False)

    from quant.qlib.paths import data_root

    project_root = Path(__file__).resolve().parents[1]
    assert data_root() == project_root / "data" / "qlib"


def test_resolve_data_path_rejects_escape(tmp_path, monkeypatch):
    monkeypatch.setenv("QLIB_DATA_ROOT", str(tmp_path / "warehouse"))

    from quant.qlib.paths import resolve_data_path

    try:
        resolve_data_path("..", "outside")
    except ValueError as exc:
        assert "outside Qlib data root" in str(exc)
    else:
        raise AssertionError("path traversal should be rejected")


def test_registry_creates_required_tables(tmp_path):
    from quant.qlib.registry import Registry

    registry = Registry(tmp_path / "qlib_meta.db")

    assert {
        "datasets",
        "jobs",
        "experiments",
        "models",
        "audit_events",
        "quality_reports",
        "workflow_runs",
        "backtest_results",
    } <= set(registry.table_names())


def test_quality_report_upsert_is_idempotent(tmp_path):
    from quant.qlib.registry import Registry

    registry = Registry(tmp_path / "qlib_meta.db")
    row = {
        "id": "quality-1",
        "dataset_id": "a_share_6y_daily",
        "dataset_version": "daily-pit-v1",
        "gate_version": "qlib_phase1_gate_v1",
        "passed": False,
        "report": {"reason_codes": ["coverage_below_98pct"]},
    }
    registry.upsert_quality_report(row)
    registry.upsert_quality_report(
        {**row, "passed": True, "report": {"reason_codes": []}}
    )

    items = registry.list_quality_reports()
    assert len(items) == 1
    assert items[0]["passed"] is True
    assert items[0]["report"] == {"reason_codes": []}


def test_workflow_run_upsert_is_idempotent_and_resolves_legacy_path(
    tmp_path,
    monkeypatch,
):
    from quant.qlib.registry import Registry

    active = tmp_path / "qlib"
    artifact = active / "mlruns" / "7" / "rec-1"
    artifact.mkdir(parents=True)
    monkeypatch.setenv("QLIB_DATA_ROOT", str(active))
    registry = Registry(tmp_path / "qlib_meta.db")
    row = {
        "id": "wf-1",
        "experiment_id": "local-1",
        "qlib_experiment_id": "7",
        "recorder_id": "rec-1",
        "dataset_version": "daily-pit-v1",
        "quality_report_id": "quality-1",
        "handler": "Alpha158",
        "model_type": "LightGBM",
        "seed": 42,
        "config_hash": "a" * 64,
        "status": "succeeded",
        "recorded_path": r"C:\AlphaCouncil-QlibData\mlruns\7\rec-1",
        "artifacts": {"pred.pkl": "b" * 64},
        "metrics": {"rank_ic": 0.03},
        "gate": {"passed": False},
    }
    registry.upsert_workflow_run(row)
    registry.upsert_workflow_run(
        {**row, "metrics": {"rank_ic": 0.04}}
    )

    items = registry.list_workflow_runs()
    assert len(items) == 1
    assert items[0]["metrics"]["rank_ic"] == 0.04
    assert items[0]["recorded_path"] == row["recorded_path"]
    assert items[0]["resolved_path"] == str(artifact.resolve())
    assert items[0]["path_state"] == "mapped_legacy"
    assert registry.get_workflow_run("wf-1")["recorder_id"] == "rec-1"


def test_backtest_result_is_unique_per_workflow_and_engine(tmp_path):
    from quant.qlib.registry import Registry

    registry = Registry(tmp_path / "qlib_meta.db")
    first = {
        "id": "bt-1",
        "workflow_run_id": "wf-1",
        "engine": "qlib_official",
        "signal_hash": "c" * 64,
        "metrics": {"sharpe": 1.0},
        "config": {"gate_version": "qlib_phase1_gate_v1"},
        "artifact_path": "report.pkl",
    }
    registry.upsert_backtest_result(first)
    registry.upsert_backtest_result(
        {**first, "id": "bt-2", "metrics": {"sharpe": 1.1}}
    )

    items = registry.list_backtest_results("wf-1")
    assert len(items) == 1
    assert items[0]["id"] == "bt-2"
    assert items[0]["metrics"]["sharpe"] == 1.1


def test_registry_lists_jobs_and_upserts_research_records(tmp_path):
    from quant.qlib.registry import Registry

    registry = Registry(tmp_path / "qlib_meta.db")
    now = utc_now()
    registry.insert_job(
        {
            "id": "job-1",
            "kind": "train_smoke",
            "status": "queued",
            "created_at": now,
            "updated_at": now,
        }
    )
    registry.upsert_dataset(
        {
            "id": "demo",
            "kind": "official_demo",
            "status": "ready",
            "rows": 100,
            "created_at": now,
            "updated_at": now,
        }
    )
    registry.upsert_experiment(
        {
            "id": "exp-1",
            "job_id": "job-1",
            "status": "succeeded",
            "model_type": "LightGBM",
            "metrics": {"rank_ic": 0.03},
            "created_at": now,
            "updated_at": now,
        }
    )
    registry.upsert_model(
        {
            "id": "model-1",
            "experiment_id": "exp-1",
            "status": "candidate",
            "model_type": "LightGBM",
            "path": str(tmp_path / "model.txt"),
            "sha256": "a" * 64,
            "metrics": {"rank_ic": 0.03},
            "created_at": now,
            "updated_at": now,
        }
    )
    registry.audit("job_submitted", "job", "job-1", {"kind": "train_smoke"})

    assert registry.list_jobs()[0]["id"] == "job-1"
    assert registry.list_datasets()[0]["metadata"] == {}
    assert registry.list_experiments()[0]["metrics"]["rank_ic"] == 0.03
    assert registry.list_models()[0]["sha256"] == "a" * 64
    assert registry.list_audit_events()[0]["event_type"] == "job_submitted"

    assert registry.get_experiment("exp-1")["metrics"] == {"rank_ic": 0.03}
    assert registry.get_experiment("exp-1")["config"] == {}
    assert registry.get_model("model-1")["metrics"] == {"rank_ic": 0.03}
    assert registry.get_experiment("missing") is None
    assert registry.get_model("missing") is None


def test_readonly_registry_missing_path_creates_nothing(tmp_path):
    from quant.qlib.registry import Registry

    db_path = tmp_path / "missing-parent" / "qlib_meta.db"

    with pytest.raises(FileNotFoundError, match="qlib_meta.db"):
        Registry(db_path, read_only=True)

    assert not db_path.parent.exists()
    assert not db_path.exists()
    assert not Path(f"{db_path}-wal").exists()
    assert not Path(f"{db_path}-shm").exists()


def test_readonly_registry_reads_without_application_writes(tmp_path):
    from quant.qlib.registry import Registry

    db_path = tmp_path / "qlib_meta.db"
    writable = Registry(db_path)
    now = utc_now()
    writable.upsert_dataset(
        {
            "id": "a_share_6y_daily",
            "kind": "research",
            "status": "ready",
            "latest_date": "2026-07-20",
            "created_at": now,
            "updated_at": now,
        }
    )
    writable.upsert_experiment(
        {
            "id": "exp-readonly",
            "dataset_id": "a_share_6y_daily",
            "status": "succeeded",
            "model_type": "LightGBM",
            "metrics": {"rank_ic": 0.04},
            "created_at": now,
            "updated_at": now,
        }
    )
    writable.upsert_model(
        {
            "id": "model-readonly",
            "experiment_id": "exp-readonly",
            "status": "candidate",
            "model_type": "LightGBM",
            "path": str(tmp_path / "model.txt"),
            "sha256": "c" * 64,
            "created_at": now,
            "updated_at": now,
        }
    )
    before_mtime = db_path.stat().st_mtime_ns

    readonly = Registry(db_path, read_only=True)

    assert readonly.list_datasets()[0]["id"] == "a_share_6y_daily"
    assert readonly.list_experiments()[0]["metrics"] == {"rank_ic": 0.04}
    assert readonly.list_models()[0]["id"] == "model-readonly"
    assert readonly.get_experiment("exp-readonly")["id"] == "exp-readonly"
    assert readonly.get_model("model-readonly")["id"] == "model-readonly"
    with readonly.connect() as conn:
        assert conn.execute("PRAGMA query_only").fetchone()[0] == 1
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        readonly.audit("forbidden", "test", None)

    assert db_path.stat().st_mtime_ns == before_mtime


def test_readonly_registry_sees_committed_rows_in_active_wal(tmp_path):
    from quant.qlib.registry import Registry

    db_path = tmp_path / "qlib_meta.db"
    Registry(db_path)
    now = utc_now()
    writer = sqlite3.connect(db_path)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute(
            """
            INSERT INTO datasets (
                id, kind, status, latest_date, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "a_share_6y_daily",
                "research",
                "ready",
                "2026-07-20",
                now,
                now,
            ),
        )
        writer.execute(
            """
            INSERT INTO experiments (
                id, dataset_id, status, model_type, metrics_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "exp-active-wal",
                "a_share_6y_daily",
                "succeeded",
                "LightGBM",
                '{"rank_ic":0.05}',
                now,
                now,
            ),
        )
        writer.execute(
            """
            INSERT INTO models (
                id, experiment_id, status, model_type, path, sha256,
                metrics_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "model-active-wal",
                "exp-active-wal",
                "candidate",
                "LightGBM",
                str(tmp_path / "active-wal-model.txt"),
                "e" * 64,
                '{"rank_ic":0.05}',
                now,
                now,
            ),
        )
        writer.commit()
        assert Path(f"{db_path}-wal").exists()

        readonly = Registry(db_path, read_only=True)

        assert readonly.list_datasets()[0]["id"] == "a_share_6y_daily"
        assert readonly.list_experiments()[0]["id"] == "exp-active-wal"
        assert readonly.list_models()[0]["id"] == "model-active-wal"
        assert readonly.get_experiment("exp-active-wal")["metrics"] == {
            "rank_ic": 0.05
        }
        assert readonly.get_model("model-active-wal")["metrics"] == {
            "rank_ic": 0.05
        }
        bundle = readonly.read_research_snapshot_records("a_share_6y_daily")
        assert bundle["dataset"]["id"] == "a_share_6y_daily"
        assert bundle["experiments"][0]["id"] == "exp-active-wal"
        assert bundle["models"][0]["id"] == "model-active-wal"
    finally:
        writer.close()


def test_research_snapshot_records_only_include_target_dataset(tmp_path):
    from quant.qlib.registry import Registry

    db_path = tmp_path / "qlib_meta.db"
    writable = Registry(db_path)
    target_experiment, target_model = _seed_research_bundle(
        writable,
        tmp_path,
        "a_share_6y_daily",
        "a",
    )
    _seed_research_bundle(writable, tmp_path, "other_dataset", "b")
    readonly = Registry(db_path, read_only=True)

    bundle = readonly.read_research_snapshot_records("a_share_6y_daily")

    assert bundle["dataset"]["id"] == "a_share_6y_daily"
    assert [row["id"] for row in bundle["experiments"]] == [target_experiment]
    assert [row["id"] for row in bundle["models"]] == [target_model]


def test_research_snapshot_records_use_one_connection_and_transaction(
    tmp_path,
    monkeypatch,
):
    from quant.qlib.registry import Registry

    db_path = tmp_path / "qlib_meta.db"
    writable = Registry(db_path)
    _seed_research_bundle(writable, tmp_path, "a_share_6y_daily", "c")
    readonly = Registry(db_path, read_only=True)
    original_connect = readonly.connect
    connection_count = 0
    statements = []

    @contextmanager
    def tracked_connect():
        nonlocal connection_count
        connection_count += 1
        with original_connect() as conn:
            conn.set_trace_callback(statements.append)
            yield conn

    monkeypatch.setattr(readonly, "connect", tracked_connect)

    readonly.read_research_snapshot_records("a_share_6y_daily")

    assert connection_count == 1
    assert any(statement.strip().upper() == "BEGIN" for statement in statements)

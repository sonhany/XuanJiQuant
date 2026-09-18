import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from scripts.qlib_path_migration import migrate


LEGACY = r"C:\XuanJiQuant-QlibData"


def test_path_migration_cli_bootstraps_project_imports():
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "scripts/qlib_path_migration.py", "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed(db_path):
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE datasets (
                id TEXT PRIMARY KEY, status TEXT NOT NULL, path TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE models (
                id TEXT PRIMARY KEY, status TEXT NOT NULL, path TEXT NOT NULL,
                metrics_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE workflow_runs (
                id TEXT PRIMARY KEY, status TEXT NOT NULL,
                recorded_path TEXT NOT NULL DEFAULT '',
                artifacts_json TEXT NOT NULL DEFAULT '{}',
                metrics_json TEXT NOT NULL DEFAULT '{}',
                gate_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY, status TEXT NOT NULL,
                params_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT,
                detail_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT INTO datasets VALUES (?, ?, ?, ?)",
            (
                "d1",
                "ready",
                LEGACY + r"\datasets\d1",
                json.dumps({"source_path": LEGACY + r"\datasets\d1\manifest.json"}),
            ),
        )
        conn.execute(
            "INSERT INTO models VALUES (?, ?, ?, ?)",
            ("m1", "candidate", LEGACY + r"\models\missing.pkl", "{}"),
        )
        conn.execute(
            "INSERT INTO workflow_runs VALUES (?, ?, ?, ?, ?, ?)",
            (
                "wf1",
                "succeeded",
                LEGACY + r"\workflows\missing",
                json.dumps({"prediction_path": LEGACY + r"\workflows\missing\pred.pkl"}),
                json.dumps({"traceback": "historical " + LEGACY + r"\do-not-rewrite"}),
                "{}",
            ),
        )
        conn.execute(
            "INSERT INTO jobs VALUES (?, ?, ?, ?)",
            (
                "j1",
                "failed",
                json.dumps({"artifact_path": LEGACY + r"\jobs\missing.json"}),
                json.dumps({"traceback": "historical " + LEGACY + r"\keep"}),
            ),
        )


def test_dry_run_never_mutates_and_reports_nested_paths(tmp_path):
    db_path = tmp_path / "qlib_meta.db"
    active_root = tmp_path / "active-qlib"
    (active_root / "datasets" / "d1").mkdir(parents=True)
    (active_root / "datasets" / "d1" / "manifest.json").write_text(
        "{}", encoding="utf-8"
    )
    _seed(db_path)
    before = _sha256(db_path)

    report = migrate(db_path=db_path, active_root=active_root, dry_run=True)

    assert report["obsolete_active_count"] == 6
    assert any(item["locator"] == "metadata_json.source_path" for item in report["items"])
    assert _sha256(db_path) == before
    assert report["backup_path"] == ""


def test_apply_maps_existing_invalidates_missing_and_preserves_history(tmp_path):
    db_path = tmp_path / "qlib_meta.db"
    active_root = tmp_path / "active-qlib"
    target = active_root / "datasets" / "d1"
    target.mkdir(parents=True)
    (target / "manifest.json").write_text("{}", encoding="utf-8")
    _seed(db_path)
    before = _sha256(db_path)

    report = migrate(db_path=db_path, active_root=active_root, dry_run=False)

    assert report["post_scan_obsolete_active_count"] == 0
    assert report["backup_sha256"] == before
    assert _sha256(report["backup_path"]) == before
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        dataset = conn.execute("SELECT * FROM datasets WHERE id='d1'").fetchone()
        model = conn.execute("SELECT * FROM models WHERE id='m1'").fetchone()
        workflow = conn.execute(
            "SELECT * FROM workflow_runs WHERE id='wf1'"
        ).fetchone()
        job = conn.execute("SELECT * FROM jobs WHERE id='j1'").fetchone()
        audit = conn.execute(
            "SELECT * FROM audit_events WHERE event_type='qlib_path_migration'"
        ).fetchone()

    assert dataset["path"] == str(target.resolve())
    assert json.loads(dataset["metadata_json"])["source_path"] == str(
        (target / "manifest.json").resolve()
    )
    assert model["path"] == ""
    assert model["status"] == "missing_historical"
    assert workflow["recorded_path"] == ""
    assert workflow["status"] == "succeeded"
    assert json.loads(workflow["metrics_json"])["traceback"].startswith("historical ")
    assert json.loads(workflow["artifacts_json"])["prediction_path_state"] == "missing_historical"
    assert json.loads(job["params_json"])["artifact_path"] == ""
    assert json.loads(job["result_json"])["traceback"].startswith("historical ")
    assert audit is not None


def test_apply_is_idempotent_after_active_obsolete_paths_are_zero(tmp_path):
    db_path = tmp_path / "qlib_meta.db"
    active_root = tmp_path / "active-qlib"
    _seed(db_path)
    first = migrate(db_path=db_path, active_root=active_root, dry_run=False)
    second = migrate(db_path=db_path, active_root=active_root, dry_run=False)

    assert first["post_scan_obsolete_active_count"] == 0
    assert second["obsolete_active_count"] == 0
    assert second["items"] == []

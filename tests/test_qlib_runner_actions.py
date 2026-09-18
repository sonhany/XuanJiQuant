from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from quant.qlib.jobs import JobManager
from quant.qlib.registry import Registry, utc_now


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts" / "qlib_runner.py"
WORKER_PATH = ROOT / "scripts" / "qlib_job_worker.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("qlib_runner_contract", RUNNER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_worker():
    spec = importlib.util.spec_from_file_location(
        "qlib_job_worker_regime_contract",
        WORKER_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runner_exposes_expected_read_and_control_actions():
    runner = load_runner()
    assert runner.READ_ONLY_ACTIONS == {
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
    assert runner.CONTROL_ACTIONS == {
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
    assert "train_regime" in runner.JOB_ACTIONS
    assert "workflow_baseline" in runner.JOB_ACTIONS
    assert "workflow_monthly_walk_forward" in runner.JOB_ACTIONS
    assert "workflow_quarterly_matrix" in runner.JOB_ACTIONS
    assert "backtest_ashare" in runner.JOB_ACTIONS
    assert runner.FIELDS_BY_ACTION["train_regime"] == runner.COMMON_FIELDS


def test_fixed_workflow_actions_reject_caller_model_configuration():
    runner = load_runner()

    for action in (
        "workflow_baseline",
        "workflow_monthly_walk_forward",
        "workflow_quarterly_matrix",
    ):
        with pytest.raises(ValueError, match="unsupported request field"):
            runner.validate_request(
                {"action": action, "handler": "Alpha999", "model": "custom"}
            )


def test_divergence_review_accepts_only_bounded_note():
    runner = load_runner()

    accepted = runner.validate_request(
        {
            "action": "resolve_backtest_divergence",
            "workflow_run_id": "wf_1",
            "review_note": "已核对成交费率差异",
        }
    )
    assert accepted["workflow_run_id"] == "wf_1"

    with pytest.raises(ValueError, match="review_note"):
        runner.validate_request(
            {
                "action": "resolve_backtest_divergence",
                "workflow_run_id": "wf_1",
                "review_note": "x" * 1001,
            }
        )


@pytest.mark.parametrize("field", ["command", "python", "path", "package", "expression"])
def test_control_actions_reject_arbitrary_execution_fields(field):
    runner = load_runner()
    with pytest.raises(ValueError, match="unsupported request field"):
        runner.validate_request({"action": "train_smoke", field: "malicious"})


@pytest.mark.parametrize(
    "field",
    [
        "path",
        "output_path",
        "metadata_path",
        "feature_names",
        "n_components",
        "random_state",
        "command",
        "shell",
    ],
)
def test_train_regime_rejects_all_caller_configuration(field):
    runner = load_runner()

    with pytest.raises(ValueError, match="unsupported request field"):
        runner.validate_request({"action": "train_regime", field: "malicious"})


def test_worker_dispatches_train_regime_without_caller_params(monkeypatch):
    worker = load_worker()
    calls = []
    monkeypatch.setattr(
        worker,
        "_require_six_year_quality",
        lambda: {"passed": True},
    )
    monkeypatch.setattr(
        worker,
        "_train_regime",
        lambda progress: calls.append(progress) or {"artifact_sha256": "a" * 64},
        raising=False,
    )
    progress = lambda *_: None

    result = worker.dispatch_job("train_regime", {}, progress)

    assert result["artifact_sha256"] == "a" * 64
    assert calls == [progress]


def test_worker_command_uses_isolated_python_and_fixed_script(tmp_path, monkeypatch):
    runner = load_runner()
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    command = runner.worker_command("job_123")
    assert command[0] == str(tmp_path / ".venv-qlib" / "Scripts" / "python.exe")
    assert command[1] == str(tmp_path / "scripts" / "qlib_job_worker.py")
    assert command[2:] == ["--job-id", "job_123"]


def test_read_only_status_does_not_import_trading_cache():
    source = RUNNER_PATH.read_text(encoding="utf-8")
    assert "create_cache" not in source
    assert "quant.data.cache" not in source


def test_schedule_status_returns_complete_cycle_counters(tmp_path, monkeypatch):
    runner = load_runner()
    store = Registry(tmp_path / "qlib_meta.db")
    store.audit(
        "schedule_cycle_succeeded",
        "qlib_schedule",
        "weekly",
        {"mode": "weekly", "status": "succeeded", "no_op": False},
    )
    monkeypatch.setattr(runner, "registry", lambda: store)

    result = runner.handle({"action": "schedule_status"})["data"]

    assert result["modes"]["weekly"]["consecutive_successes"] == 1
    assert result["modes"]["monthly"]["consecutive_successes"] == 0


def test_venv_status_reuses_recent_successful_probe(tmp_path, monkeypatch):
    runner = load_runner()
    python_path = tmp_path / ".venv-qlib" / "Scripts" / "python.exe"
    python_path.parent.mkdir(parents=True)
    python_path.touch()
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        payload = {
            "python": "3.11.9",
            "qlib": "0.9.7",
            "lightgbm": "4.6.0",
            "hmmlearn": "0.3.3",
        }
        return SimpleNamespace(stdout=json.dumps(payload))

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    first = runner._venv_status()
    second = runner._venv_status()

    assert first == second
    assert first["ready"] is True
    assert first["python_version"] == "3.11.9"
    assert first["hmmlearn_version"] == "0.3.3"
    assert len(calls) == 1
    probe = calls[0][0][0][2]
    assert "importlib.metadata" in probe
    assert "import qlib,lightgbm" not in probe


def test_venv_status_keeps_last_success_when_refresh_probe_fails(tmp_path, monkeypatch):
    runner = load_runner()
    python_path = tmp_path / ".venv-qlib" / "Scripts" / "python.exe"
    python_path.parent.mkdir(parents=True)
    python_path.touch()
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    clock = iter((100.0, 500.0))
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(clock))
    attempts = 0

    def fake_run(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            payload = {
                "python": "3.11.9",
                "qlib": "0.9.7",
                "lightgbm": "4.6.0",
                "hmmlearn": "0.3.3",
            }
            return SimpleNamespace(stdout=json.dumps(payload))
        raise runner.subprocess.TimeoutExpired(cmd="python", timeout=20)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    first = runner._venv_status()
    fallback = runner._venv_status()

    assert first["error"] == ""
    assert fallback["ready"] is True
    assert fallback["python_version"] == "3.11.9"
    assert "cached after probe failure" in fallback["error"]
    assert attempts == 2


def test_venv_status_is_not_ready_when_hmmlearn_probe_is_missing(
    tmp_path,
    monkeypatch,
):
    runner = load_runner()
    python_path = tmp_path / ".venv-qlib" / "Scripts" / "python.exe"
    python_path.parent.mkdir(parents=True)
    python_path.touch()
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    payload = {
        "python": "3.11.9",
        "qlib": "0.9.7",
        "lightgbm": "4.6.0",
    }
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps(payload)),
    )

    result = runner._venv_status()

    assert result["ready"] is False
    assert result["hmmlearn_version"] == ""
    assert "hmmlearn" in result["error"].lower()


def _insert_running_job(store: Registry, *, job_id: str = "qlib_orphan") -> None:
    now = utc_now()
    store.insert_job(
        {
            "id": job_id,
            "kind": "train_smoke",
            "status": "running",
            "heavy": True,
            "progress": 0.25,
            "pid": 999999,
            "message": "started",
            "params": {},
            "result": {},
            "created_at": now,
            "updated_at": now,
            "started_at": now,
        }
    )


def test_status_hides_dead_worker_without_mutating_registry(tmp_path, monkeypatch):
    runner = load_runner()
    monkeypatch.setenv("QLIB_DATA_ROOT", str(tmp_path))
    store = Registry(tmp_path / "qlib_meta.db")
    _insert_running_job(store)
    monkeypatch.setattr(runner, "registry", lambda: store)
    monkeypatch.setattr(runner, "job_is_orphaned", lambda job: job["status"] == "running")
    monkeypatch.setattr(runner, "_venv_status", lambda: {"ready": True})
    monkeypatch.setattr(runner, "_six_year_quality", lambda: None)

    result = runner.handle({"action": "status"})["data"]

    assert result["active_job"] is None
    assert result["latest_job"]["status"] == "interrupted"
    assert result["latest_job"]["stale_persisted_status"] is True
    assert store.get_job("qlib_orphan")["status"] == "running"


def test_new_heavy_job_reconciles_dead_worker_before_create(tmp_path, monkeypatch):
    import quant.qlib.jobs as jobs_module

    store = Registry(tmp_path / "qlib_meta.db")
    _insert_running_job(store)
    monkeypatch.setattr(jobs_module, "pid_alive", lambda _pid: False)

    created = JobManager(store).create("train_one_year", heavy=True)

    assert store.get_job("qlib_orphan")["status"] == "interrupted"
    assert store.get_job("qlib_orphan")["message"] == "worker process is no longer running"
    assert created["status"] == "queued"


def test_promote_shadow_rechecks_gate_and_artifact_hashes(tmp_path, monkeypatch):
    import hashlib

    import pandas as pd

    runner = load_runner()
    monkeypatch.setenv("QLIB_DATA_ROOT", str(tmp_path))
    store = Registry(tmp_path / "qlib_meta.db")
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    params = artifact_root / "params.pkl"
    params.write_bytes(b"model")
    index = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2026-08-03"), "SH600000"),
            (pd.Timestamp("2026-08-03"), "SZ000001"),
        ],
        names=["datetime", "instrument"],
    )
    prediction = pd.Series([0.8, 0.7], index=index, name="score")
    prediction.to_pickle(artifact_root / "pred.pkl")

    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    store.upsert_model(
        {
            "id": "model_1",
            "experiment_id": "local_1",
            "status": "candidate",
            "model_type": "LightGBM",
            "path": str(params),
            "sha256": digest(params),
            "metrics": {},
        }
    )
    store.upsert_workflow_run(
        {
            "id": "wf_1",
            "experiment_id": "local_1",
            "qlib_experiment_id": "exp_1",
            "recorder_id": "rec_1",
            "dataset_version": "daily-pit-v1",
            "quality_report_id": "quality_1",
            "handler": "Alpha158",
            "model_type": "LightGBM",
            "seed": 42,
            "config_hash": "b" * 64,
            "status": "succeeded",
            "recorded_path": str(artifact_root),
            "artifacts": {
                "params.pkl": digest(params),
                "pred.pkl": digest(artifact_root / "pred.pkl"),
            },
            "metrics": {},
            "gate": {
                "gate_version": "qlib_phase1_gate_v1",
                "status": "candidate",
                "signal_hash": "a" * 64,
            },
        }
    )
    monkeypatch.setattr(
        runner,
        "resolve_data_path",
        lambda *parts: tmp_path.joinpath(*parts),
    )

    result = runner._promote_shadow_model(store, "model_1")

    assert result["model"]["status"] == "shadow"
    assert result["workflow_run_id"] == "wf_1"
    assert result["signal"]["path"].exists()


def test_promote_shadow_rejects_tampered_prediction(tmp_path, monkeypatch):
    import hashlib

    import pandas as pd

    runner = load_runner()
    monkeypatch.setenv("QLIB_DATA_ROOT", str(tmp_path))
    store = Registry(tmp_path / "qlib_meta.db")
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    params = artifact_root / "params.pkl"
    prediction_path = artifact_root / "pred.pkl"
    params.write_bytes(b"model")
    pd.Series(
        [0.8],
        index=pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2026-08-03"), "SH600000")],
            names=["datetime", "instrument"],
        ),
    ).to_pickle(prediction_path)
    original_prediction_hash = hashlib.sha256(prediction_path.read_bytes()).hexdigest()
    store.upsert_model(
        {
            "id": "model_1",
            "experiment_id": "local_1",
            "status": "candidate",
            "model_type": "LightGBM",
            "path": str(params),
            "sha256": hashlib.sha256(params.read_bytes()).hexdigest(),
            "metrics": {},
        }
    )
    store.upsert_workflow_run(
        {
            "id": "wf_1",
            "experiment_id": "local_1",
            "qlib_experiment_id": "exp_1",
            "recorder_id": "rec_1",
            "dataset_version": "daily-pit-v1",
            "quality_report_id": "quality_1",
            "handler": "Alpha158",
            "model_type": "LightGBM",
            "seed": 42,
            "config_hash": "b" * 64,
            "status": "succeeded",
            "recorded_path": str(artifact_root),
            "artifacts": {
                "params.pkl": hashlib.sha256(params.read_bytes()).hexdigest(),
                "pred.pkl": original_prediction_hash,
            },
            "metrics": {},
            "gate": {
                "gate_version": "qlib_phase1_gate_v1",
                "status": "candidate",
                "signal_hash": "a" * 64,
            },
        }
    )
    prediction_path.write_bytes(prediction_path.read_bytes() + b"tampered")
    monkeypatch.setattr(
        runner,
        "resolve_data_path",
        lambda *parts: tmp_path.joinpath(*parts),
    )

    with pytest.raises(ValueError, match="artifact hash mismatch"):
        runner._promote_shadow_model(store, "model_1")

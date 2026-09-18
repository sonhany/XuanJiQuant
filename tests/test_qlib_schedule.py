from datetime import datetime
import importlib.util
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEDULE_PATH = ROOT / "scripts" / "qlib_schedule.py"


def load_schedule():
    spec = importlib.util.spec_from_file_location("qlib_schedule_contract", SCHEDULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_dispatcher(calls):
    def dispatch(kind, params, progress):
        calls.append(kind)
        if kind.startswith("quality_"):
            return {
                "passed": True,
                "report_id": "quality_1",
                "dataset_version": "daily-pit-v1",
            }
        if kind == "build_f4_references":
            return {"status": "passed", "dataset_version": "daily-pit-v1"}
        if kind.startswith("workflow_"):
            return {
                "status": "succeeded",
                "workflow_run_ids": ["wf_1"],
                "artifacts_complete": True,
            }
        if kind == "backtest_ashare":
            return {
                "status": "succeeded",
                "engines": ["qlib_official", "xuanji_ashare"],
                "gate_status": "candidate",
            }
        return {"status": "succeeded", "dataset_version": "daily-pit-v1"}

    return dispatch


def test_weekly_runs_quality_before_workflow():
    schedule = load_schedule()
    calls = []

    result = schedule.run_weekly(
        force=True,
        now=datetime(2026, 8, 8, 18, 30),
        dispatcher=fake_dispatcher(calls),
    )

    assert calls == [
        "collect_six_years",
        "quality_six_years",
        "build_f4_references",
        "export_six_years",
        "workflow_baseline",
        "backtest_ashare",
    ]
    assert result["status"] == "succeeded"


def test_monthly_and_quarterly_use_fixed_pipelines():
    schedule = load_schedule()
    monthly = []
    schedule.run_six_year_cycle(
        mode="monthly",
        force=True,
        now=datetime(2026, 9, 5, 18, 30),
        dispatcher=fake_dispatcher(monthly),
    )
    assert monthly == [
        "collect_six_years",
        "quality_six_years",
        "build_f4_references",
        "export_six_years",
        "workflow_monthly_walk_forward",
        "backtest_ashare",
    ]

    quarterly = []
    schedule.run_six_year_cycle(
        mode="quarterly",
        force=True,
        now=datetime(2026, 10, 3, 18, 30),
        dispatcher=fake_dispatcher(quarterly),
    )
    assert "workflow_quarterly_matrix" in quarterly
    assert quarterly[-1] == "backtest_ashare"


def test_no_new_trading_day_is_successful_no_op():
    schedule = load_schedule()
    calls = []

    def dispatcher(kind, params, progress):
        calls.append(kind)
        return {"status": "succeeded", "no_op": True}

    result = schedule.run_weekly(
        force=True,
        now=datetime(2026, 8, 8, 18, 30),
        dispatcher=dispatcher,
    )

    assert result["status"] == "succeeded"
    assert result["no_op"] is True
    assert calls == ["collect_six_years"]


def test_incomplete_workflow_cycle_is_failed():
    schedule = load_schedule()

    def dispatcher(kind, params, progress):
        if kind == "quality_six_years":
            return {"passed": True, "dataset_version": "v1"}
        if kind == "build_f4_references":
            return {"status": "passed", "dataset_version": "v1"}
        if kind.startswith("workflow_"):
            return {
                "status": "succeeded",
                "workflow_run_ids": ["wf_1"],
                "artifacts_complete": False,
            }
        return {"status": "succeeded"}

    result = schedule.run_weekly(
        force=True,
        now=datetime(2026, 8, 8, 18, 30),
        dispatcher=dispatcher,
    )

    assert result["status"] == "failed"
    assert "recorder_artifacts_incomplete" in result["reason_codes"]


def test_reference_failure_stops_export_and_training():
    schedule = load_schedule()
    calls = []

    def dispatcher(kind, params, progress):
        calls.append(kind)
        if kind == "quality_six_years":
            return {"passed": True, "dataset_version": "v1"}
        if kind == "build_f4_references":
            return {"status": "failed", "reason_code": "f4_reference_build_failed"}
        return {"status": "succeeded"}

    result = schedule.run_weekly(
        force=True,
        now=datetime(2026, 8, 8, 18, 30),
        dispatcher=dispatcher,
    )

    assert calls == [
        "collect_six_years",
        "quality_six_years",
        "build_f4_references",
    ]
    assert result["status"] == "failed"
    assert result["reason_codes"] == ["f4_reference_build_failed"]


def test_schedule_status_counts_only_consecutive_complete_cycles():
    schedule = load_schedule()

    class Store:
        def list_audit_events(self, limit):
            assert limit == 500
            return [
                {
                    "event_type": "schedule_cycle_no_op",
                    "detail": {"mode": "weekly", "status": "succeeded", "no_op": True},
                },
                {
                    "event_type": "schedule_cycle_succeeded",
                    "detail": {"mode": "weekly", "status": "succeeded", "no_op": False},
                },
                {
                    "event_type": "schedule_cycle_succeeded",
                    "detail": {"mode": "monthly", "status": "succeeded", "no_op": False},
                },
                {
                    "event_type": "schedule_cycle_succeeded",
                    "detail": {"mode": "weekly", "status": "succeeded", "no_op": False},
                },
                {
                    "event_type": "schedule_cycle_failed",
                    "detail": {"mode": "weekly", "status": "failed"},
                },
                {
                    "event_type": "schedule_cycle_succeeded",
                    "detail": {"mode": "weekly", "status": "succeeded", "no_op": False},
                },
            ]

    result = schedule.schedule_status(Store(), "weekly")
    assert result["consecutive_successes"] == 2


def test_registered_schedule_cycle_is_visible_as_active_job(tmp_path):
    schedule = load_schedule()
    store = schedule.Registry(tmp_path / "qlib_meta.db")
    observed = []

    def dispatcher(kind, params, progress):
        active = store.active_heavy_job()
        observed.append(
            {
                "kind": kind,
                "active_kind": active["kind"] if active else None,
                "active_status": active["status"] if active else None,
            }
        )
        progress(0.5, f"{kind} halfway")
        return fake_dispatcher([])(kind, params, progress)

    result = schedule.run_registered_cycle(
        mode="weekly",
        force=True,
        now=datetime(2026, 8, 8, 18, 30),
        dispatcher=dispatcher,
        store=store,
        pid=os.getpid(),
    )

    latest = store.list_jobs(1)[0]
    assert observed
    assert all(item["active_kind"] == "schedule_weekly" for item in observed)
    assert all(item["active_status"] == "running" for item in observed)
    assert result["status"] == "succeeded"
    assert result["schedule_job_id"] == latest["id"]
    assert latest["kind"] == "schedule_weekly"
    assert latest["status"] == "succeeded"
    assert latest["progress"] == 1.0


def test_auto_mode_prioritizes_quarterly_monthly_then_weekly():
    schedule = load_schedule()

    assert schedule.select_mode(datetime(2026, 10, 3, 18, 30)) == "quarterly"
    assert schedule.select_mode(datetime(2026, 9, 5, 18, 30)) == "monthly"
    assert schedule.select_mode(datetime(2026, 8, 8, 18, 30)) == "weekly"


def test_registered_cycle_returns_explicit_skip_when_live_heavy_job_exists(tmp_path):
    schedule = load_schedule()
    store = schedule.Registry(tmp_path / "qlib_meta.db")
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    store.insert_job(
        {
            "id": "active-heavy",
            "kind": "collect_six_years",
            "status": "running",
            "heavy": True,
            "pid": os.getpid(),
            "run_token": "live-token",
            "created_at": now,
            "updated_at": now,
            "started_at": now,
            "heartbeat_at": now,
        }
    )

    result = schedule.run_registered_cycle(
        mode="auto",
        now=datetime(2026, 8, 8, 18, 30),
        store=store,
    )

    assert result["status"] == "skipped"
    assert result["reason_code"] == "heavy_job_active"
    assert result["active_job_id"] == "active-heavy"

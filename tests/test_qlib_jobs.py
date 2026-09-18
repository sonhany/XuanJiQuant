import pytest


def test_only_one_heavy_job_can_be_active(tmp_path):
    from quant.qlib.jobs import ActiveJobError, JobManager
    from quant.qlib.registry import Registry

    jobs = JobManager(Registry(tmp_path / "qlib_meta.db"))
    first = jobs.create("train_one_year", heavy=True)

    with pytest.raises(ActiveJobError):
        jobs.create("collect_six_years", heavy=True)

    jobs.transition(first["id"], "running")
    jobs.transition(first["id"], "succeeded")
    second = jobs.create("collect_six_years", heavy=True)
    assert second["status"] == "queued"


def test_invalid_job_transition_is_rejected(tmp_path):
    from quant.qlib.jobs import InvalidTransitionError, JobManager
    from quant.qlib.registry import Registry

    jobs = JobManager(Registry(tmp_path / "qlib_meta.db"))
    job = jobs.create("train_smoke", heavy=True)

    with pytest.raises(InvalidTransitionError):
        jobs.transition(job["id"], "succeeded")


def test_dead_worker_is_persisted_as_interrupted(tmp_path):
    from quant.qlib.jobs import JobManager
    from quant.qlib.registry import Registry

    store = Registry(tmp_path / "meta.db")
    manager = JobManager(store)
    job = manager.create("workflow_baseline", heavy=True)
    manager.transition(
        job["id"],
        "running",
        pid=999999,
        stage="train",
        run_token="run_1",
    )

    recovered = manager.recover_stale_jobs(process_alive=lambda _: False)
    saved = store.get_job(job["id"])

    assert recovered == [job["id"]]
    assert saved["status"] == "interrupted"
    assert saved["stage"] == "train"
    assert saved["run_token"] == "run_1"


def test_progress_persists_stage_heartbeat_and_run_token(tmp_path):
    from quant.qlib.jobs import JobManager, job_progress_callback
    from quant.qlib.registry import Registry

    store = Registry(tmp_path / "meta.db")
    manager = JobManager(store)
    job = manager.create("workflow_baseline", heavy=True)
    manager.transition(job["id"], "running", pid=123, run_token="run_2")
    progress = job_progress_callback(store, job["id"], "run_2")

    progress(0.5, "train", "正在训练 LightGBM")
    saved = store.get_job(job["id"])

    assert saved["progress"] == 0.5
    assert saved["stage"] == "train"
    assert saved["heartbeat_at"]
    assert saved["run_token"] == "run_2"
    assert saved["message"] == "正在训练 LightGBM"


def test_progress_rejects_stale_run_token(tmp_path):
    from quant.qlib.jobs import JobManager, job_progress_callback
    from quant.qlib.registry import Registry

    store = Registry(tmp_path / "meta.db")
    manager = JobManager(store)
    job = manager.create("workflow_baseline", heavy=True)
    manager.transition(job["id"], "running", pid=123, run_token="current")

    with pytest.raises(RuntimeError, match="run token mismatch"):
        job_progress_callback(store, job["id"], "stale")(
            0.5, "train", "stale update"
        )

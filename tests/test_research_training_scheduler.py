from datetime import date, datetime, timedelta, timezone

from quant.research.job_store import ResearchJobStore
from quant.data.cache import MemoryCache
from quant.data.snapshot import DataSnapshot, publish_snapshot
from scripts.research_training_scheduler import (
    _factor_handler,
    _load_runtime_inputs,
    _once_exit_code,
    run_due_once,
)
from quant.research.training_schedule import ScheduledResearchJob
import scripts.research_training_scheduler as scheduler


SUNDAY_1000 = datetime(2026, 8, 9, 10, 0)
FRIDAY_1620 = datetime(2026, 8, 7, 16, 20)
CALENDAR = {date(2026, 8, 7)}


def _snapshot():
    return {
        "sync_complete": True,
        "complete_market_date": "2026-08-07",
        "factor_input_fresh": True,
        "data_version": "pit-v1",
    }


def test_once_exit_code_retries_blocked_prerequisites_but_accepts_idempotent_work():
    assert _once_exit_code([]) == 0
    assert _once_exit_code(
        [{"status": "skipped", "reason_code": "idempotent_terminal"}]
    ) == 0
    assert _once_exit_code(
        [{"status": "blocked", "reason_code": "qlib_prerequisite_missing"}]
    ) == 1
    assert _once_exit_code(
        [{"status": "skipped", "reason_code": "retry_backoff"}]
    ) == 1


def test_strategy_handler_runs_f4_validator_and_returns_projection(monkeypatch, tmp_path):
    calls = []
    latest = tmp_path / "latest.json"
    latest.write_text(
        '{"status":"f4_rejected","reasons":["sharpe_below_0_80"],'
        '"promotion_state":"research_only","execution_authority":false}',
        encoding="utf-8",
    )

    def fake_run(script_name, *arguments, timeout_seconds):
        calls.append((script_name, arguments, timeout_seconds))
        return {"success": True, "script": script_name}

    monkeypatch.setattr(scheduler, "_run_deterministic_research_script", fake_run)
    monkeypatch.setattr(scheduler, "F4_LATEST_PATH", latest)
    monkeypatch.setattr(
        scheduler,
        "resolve_complete_generation",
        lambda _root: {"pointer": {"generation_id": "generation-v1"}},
    )
    job = ScheduledResearchJob(
        kind="strategy_weekly",
        idempotency_key="strategy-weekly-1",
        market_date="2026-08-14",
        data_version="data-v1",
        factory_version="strategy-v1",
    )
    stages = []
    result = scheduler._strategy_handler(job, lambda stage, progress: stages.append(stage))
    assert calls == [
        ("validate_strategy_portfolios.py", ("--once",), 43200),
        (
            "generate_experimental_portfolio.py",
            ("--generation-id", "generation-v1"),
            3600,
        ),
    ]
    assert result["status"] == "f4_rejected"
    assert result["execution_authority"] is False
    assert stages == ["f4_validation", "f4_gate_complete", "experimental_selection_rebound"]


def test_selection_handler_runs_deterministic_generator_and_validates_projection(
    monkeypatch, tmp_path
):
    calls = []
    latest = tmp_path / "latest.json"
    latest.write_text(
        '{"portfolio_id":"portfolio-v1","selection_date":"20260818",'
        '"generated_from_snapshot_id":"daily-v1","snapshot_data_version":"data-v1",'
        '"position_count":2,"positions":[{"code":"000001"}],'
        '"promotion_state":"research_only","execution_authority":false,'
        '"not_a_trade_signal":true}',
        encoding="utf-8",
    )

    def fake_run(script_name, *arguments, timeout_seconds):
        calls.append((script_name, arguments, timeout_seconds))
        return {"success": True, "script": script_name}

    monkeypatch.setattr(scheduler, "_run_deterministic_research_script", fake_run)
    monkeypatch.setattr(scheduler, "SELECTION_LATEST_PATH", latest)
    job = ScheduledResearchJob(
        kind="research_selection_daily",
        idempotency_key="selection-v1",
        market_date="2026-08-18",
        data_version="data-v1",
        factory_version="factor-v1:f4-v1:portfolio-v1",
    )
    stages = []

    result = scheduler._selection_handler(
        job, lambda stage, progress: stages.append(stage)
    )

    assert calls == [("generate_research_portfolio.py", ("--once",), 3600)]
    assert result["portfolio_id"] == "portfolio-v1"
    assert result["execution_authority"] is False
    assert stages == ["research_selection", "selection_gate_complete"]


def test_selection_handler_validates_generation_staging_when_environment_is_set(
    monkeypatch, tmp_path
):
    generation = tmp_path / "generation"
    generation.mkdir()
    (generation / "selection.json").write_text(
        '{"portfolio_id":"portfolio-v1","selection_date":"20260818",'
        '"generated_from_snapshot_id":"daily-v1","snapshot_data_version":"data-v1",'
        '"position_count":1,"positions":[{"code":"000001"}],'
        '"promotion_state":"research_only","execution_authority":false,'
        '"not_a_trade_signal":true}',
        encoding="utf-8",
    )
    monkeypatch.setenv("XUANJI_RESEARCH_GENERATION_DIR", str(generation))
    monkeypatch.setattr(
        scheduler,
        "_run_deterministic_research_script",
        lambda *_args, **_kwargs: {"success": True},
    )
    job = ScheduledResearchJob(
        kind="research_selection_daily",
        idempotency_key="selection-v1",
        market_date="2026-08-18",
        data_version="data-v1",
        factory_version="factor-v1:f4-v1:portfolio-v1",
    )

    result = scheduler._selection_handler(job, lambda *_args: None)

    assert result["portfolio_id"] == "portfolio-v1"


def test_factor_handler_reuses_only_generation_staging_artifact(monkeypatch, tmp_path):
    generation = tmp_path / "generation"
    generation.mkdir()
    (generation / "factor_evaluation.json").write_text(
        '{"data_version":"pit-v1","data_end_date":"20260807",'
        '"factors":[{"factor":"ret_5"}],"promotion_state":"research_only",'
        '"execution_authority":false}',
        encoding="utf-8",
    )
    monkeypatch.setenv("XUANJI_RESEARCH_GENERATION_DIR", str(generation))
    monkeypatch.setattr(
        scheduler,
        "_run_deterministic_research_script",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("must reuse staging artifact")
        ),
    )
    job = ScheduledResearchJob(
        kind="factor_daily",
        idempotency_key="factor-v1",
        market_date="2026-08-07",
        data_version="pit-v1",
        factory_version="factor-v1",
    )

    result = scheduler._factor_handler(job, lambda *_args: None)

    assert result["reason_code"] == "factor_version_already_evaluated"


def test_generation_attempt_uses_local_job_store_so_failed_attempt_can_retry(
    monkeypatch, tmp_path
):
    generation = tmp_path / "generation-attempt"
    monkeypatch.setenv("XUANJI_RESEARCH_GENERATION_DIR", str(generation))

    path = scheduler._research_job_store_path()

    assert path == generation.resolve() / "research_jobs.db"


def test_factor_job_runs_once_and_records_shadow_result(tmp_path):
    store = ResearchJobStore(tmp_path / "research_jobs.db")
    calls = []

    result = run_due_once(
        now=FRIDAY_1620,
        trading_days=CALENDAR,
        data_snapshot=_snapshot(),
        store=store,
        factor_version="factor-v1",
        strategy_version="strategy-v1",
        qlib_version="qlib-v1",
        handlers={
            "factor_daily": lambda job, heartbeat: calls.append(job.kind)
            or {"success": True, "promotion_state": "shadow"}
        },
    )
    repeated = run_due_once(
        now=FRIDAY_1620,
        trading_days=CALENDAR,
        data_snapshot=_snapshot(),
        store=store,
        factor_version="factor-v1",
        strategy_version="strategy-v1",
        qlib_version="qlib-v1",
        handlers={},
    )

    assert calls == ["factor_daily"]
    assert result[0]["status"] == "succeeded"
    assert repeated[0]["status"] == "skipped"
    assert repeated[0]["reason_code"] == "idempotent_terminal"


def test_daily_selection_runs_only_after_same_version_factor_success(tmp_path):
    store = ResearchJobStore(tmp_path / "research_jobs.db")
    calls = []
    snapshot = {
        **_snapshot(),
        "f4_validation_id": "f4-v1",
        "portfolio_policy_version": "portfolio-v1",
    }

    result = run_due_once(
        now=FRIDAY_1620,
        trading_days=CALENDAR,
        data_snapshot=snapshot,
        store=store,
        factor_version="factor-v1",
        strategy_version="strategy-v1",
        qlib_version="qlib-v1",
        handlers={
            "factor_daily": lambda *_args: calls.append("factor_daily")
            or {"success": True, "dataset_version": "pit-v1"},
            "research_selection_daily": lambda *_args: calls.append(
                "research_selection_daily"
            )
            or {"success": True, "dataset_version": "pit-v1"},
        },
    )

    assert calls == ["factor_daily", "research_selection_daily"]
    assert [item["status"] for item in result] == ["succeeded", "succeeded"]


def test_qlib_lane_does_not_claim_overdue_daily_jobs(tmp_path):
    store = ResearchJobStore(tmp_path / "research_jobs.db")
    calls = []
    snapshot = {
        **_snapshot(),
        "qlib_sync_complete": True,
        "qlib_market_date": "2026-08-07",
        "qlib_data_version": "qlib-data-v1",
    }

    result = run_due_once(
        now=datetime(2026, 8, 8, 18, 30),
        trading_days=CALENDAR,
        data_snapshot=snapshot,
        store=store,
        factor_version="factor-v1",
        strategy_version="strategy-v1",
        qlib_version="qlib-v1",
        lane="qlib",
        handlers={"qlib_weekly": lambda job, *_args: calls.append(job.kind) or {"success": True}},
    )

    assert calls == ["qlib_weekly"]
    assert [item["kind"] for item in result] == ["qlib_weekly"]
    assert [item["kind"] for item in store.list_jobs(10)] == ["qlib_weekly"]


def test_qlib_weekly_refresh_accepts_complete_but_stale_input_dataset(tmp_path):
    store = ResearchJobStore(tmp_path / "research_jobs.db")
    calls = []
    snapshot = {
        **_snapshot(),
        "complete_market_date": "2026-08-28",
        "qlib_sync_complete": True,
        "qlib_market_date": "2026-08-21",
        "qlib_data_version": "qlib-data-20260821",
    }

    result = run_due_once(
        now=datetime(2026, 8, 29, 18, 30),
        trading_days={date(2026, 8, 28)},
        data_snapshot=snapshot,
        store=store,
        factor_version="factor-v1",
        strategy_version="strategy-v1",
        qlib_version="qlib-v1",
        lane="qlib",
        handlers={
            "qlib_weekly": lambda job, *_args: calls.append(job.kind)
            or {"success": True, "dataset_version": "qlib-data-20260828"}
        },
    )

    assert calls == ["qlib_weekly"]
    assert result[0]["status"] == "succeeded"


def test_qlib_weekly_retry_resumes_incomplete_checkpoint(tmp_path):
    store = ResearchJobStore(tmp_path / "research_jobs.db")
    calls = []
    snapshot = {
        **_snapshot(),
        "complete_market_date": "2026-08-28",
        "qlib_sync_complete": False,
        "qlib_market_date": "",
        "qlib_data_version": "daily-pit-2020-08-16-2026-08-30",
    }

    result = run_due_once(
        now=datetime(2026, 8, 29, 19, 0),
        trading_days={date(2026, 8, 28)},
        data_snapshot=snapshot,
        store=store,
        factor_version="factor-v1",
        strategy_version="strategy-v1",
        qlib_version="qlib-v1",
        lane="qlib",
        handlers={
            "qlib_weekly": lambda job, *_args: calls.append(job.kind)
            or {"success": True, "dataset_version": job.data_version}
        },
    )

    assert calls == ["qlib_weekly"]
    assert result[0]["status"] == "succeeded"


def test_qlib_lane_retries_same_week_interrupted_job_after_saturday(tmp_path):
    store = ResearchJobStore(tmp_path / "research_jobs.db", retry_delay_seconds=60)
    identity = "qlib_weekly:2026-W35:qlib-checkpoint:qlib-v1"
    claim = store.claim(
        identity,
        kind="qlib_weekly",
        heavy=True,
        owner_pid=1,
        now=datetime(2026, 8, 29, 18, 30),
        params={
            "market_date": "2026-08-28",
            "data_version": "qlib-checkpoint",
            "factory_version": "qlib-v1",
        },
    )
    store.finish(
        claim.job_id,
        run_token=claim.run_token,
        status="interrupted",
        result={"reason_code": "owner_lost"},
        now=datetime(2026, 8, 29, 18, 31),
    )
    calls = []

    result = run_due_once(
        now=datetime(2026, 8, 30, 16, 0),
        trading_days={date(2026, 8, 28)},
        data_snapshot={
            **_snapshot(),
            "complete_market_date": "2026-08-28",
            "qlib_sync_complete": False,
            "qlib_market_date": "",
            "qlib_data_version": "qlib-checkpoint",
        },
        store=store,
        factor_version="factor-v1",
        strategy_version="strategy-v1",
        qlib_version="qlib-v1",
        lane="qlib",
        handlers={
            "qlib_weekly": lambda job, *_args: calls.append(job.idempotency_key)
            or {"success": True, "dataset_version": "qlib-complete"}
        },
    )

    assert calls == [identity]
    assert result[0]["status"] == "succeeded"
    assert store.find(identity)["attempt"] == 2


def test_claimed_qlib_job_forces_inner_cycle_so_safe_retry_is_not_skipped(
    monkeypatch,
):
    calls = []
    monkeypatch.setattr(
        "scripts.qlib_schedule.run_registered_cycle",
        lambda **kwargs: calls.append(kwargs) or {"status": "succeeded"},
    )
    job = ScheduledResearchJob(
        kind="qlib_weekly",
        idempotency_key="qlib_weekly:2026-W35:qlib-old:qlib-v1",
        market_date="2026-08-28",
        data_version="qlib-old",
        factory_version="qlib-v1",
        heavy=True,
    )

    result = scheduler._qlib_handler(job, lambda *_args: None)

    assert result["status"] == "succeeded"
    assert calls[0]["mode"] == "weekly"
    assert calls[0]["force"] is True


def test_strategy_lane_does_not_claim_overdue_daily_jobs(tmp_path):
    store = ResearchJobStore(tmp_path / "research_jobs.db")

    result = run_due_once(
        now=SUNDAY_1000,
        trading_days=CALENDAR,
        data_snapshot=_snapshot(),
        store=store,
        factor_version="factor-v1",
        strategy_version="strategy-v1",
        qlib_version="qlib-v1",
        lane="strategy",
        handlers={"strategy_weekly": lambda *_args: {"success": True}},
    )

    assert [item["kind"] for item in result] == ["strategy_weekly"]
    assert [item["kind"] for item in store.list_jobs(10)] == ["strategy_weekly"]


def test_pit_completion_event_triggers_same_week_strategy_once(tmp_path):
    store = ResearchJobStore(tmp_path / "research_jobs.db")
    calls = []
    snapshot = {
        **_snapshot(),
        "complete_market_date": "2026-08-28",
        "data_version": "daily-v1",
        "factor_publication_complete": True,
        "factor_publication_market_date": "20260828",
        "factor_publication_data_version": "daily-v1",
        "f4_trigger_required": True,
    }

    first = run_due_once(
        now=datetime(2026, 8, 29, 22, 0),
        trading_days={date(2026, 8, 28)},
        data_snapshot=snapshot,
        store=store,
        factor_version="factor-v1",
        strategy_version="strategy-v1",
        qlib_version="qlib-v1",
        lane="strategy",
        event_trigger=True,
        handlers={
            "strategy_weekly": lambda job, *_args: calls.append(job.idempotency_key)
            or {"success": True}
        },
    )
    repeated = run_due_once(
        now=datetime(2026, 8, 30, 10, 0),
        trading_days={date(2026, 8, 28)},
        data_snapshot=snapshot,
        store=store,
        factor_version="factor-v1",
        strategy_version="strategy-v1",
        qlib_version="qlib-v1",
        lane="strategy",
        handlers={"strategy_weekly": lambda *_args: {"success": True}},
    )

    assert first[0]["status"] == "succeeded"
    assert repeated[0]["status"] == "skipped"
    assert repeated[0]["reason_code"] == "idempotent_terminal"
    assert calls == ["strategy_weekly:2026-W35:daily-v1:strategy-v1"]


def test_scheduler_recovers_dead_owner_then_retries_after_safe_backoff(tmp_path):
    started = datetime(2026, 8, 7, 8, 20, tzinfo=timezone.utc)
    store = ResearchJobStore(
        tmp_path / "research_jobs.db",
        lease_seconds=30,
        retry_delay_seconds=30,
    )
    identity = "factor_daily:2026-08-07:pit-v1:factor-v1"
    abandoned = store.claim(
        identity,
        kind="factor_daily",
        heavy=False,
        owner_pid=999_999,
        now=started,
    )

    cooling_down = run_due_once(
        now=FRIDAY_1620 + timedelta(seconds=31),
        trading_days=CALENDAR,
        data_snapshot=_snapshot(),
        store=store,
        factor_version="factor-v1",
        strategy_version="strategy-v1",
        qlib_version="qlib-v1",
        handlers={},
        process_alive=lambda _pid: False,
    )
    completed = run_due_once(
        now=FRIDAY_1620 + timedelta(seconds=61),
        trading_days=CALENDAR,
        data_snapshot=_snapshot(),
        store=store,
        factor_version="factor-v1",
        strategy_version="strategy-v1",
        qlib_version="qlib-v1",
        handlers={"factor_daily": lambda *_args: {"success": True}},
        process_alive=lambda _pid: False,
    )

    assert abandoned.claimed is True
    assert cooling_down[0]["status"] == "skipped"
    assert cooling_down[0]["reason_code"] == "retry_backoff"
    assert completed[0]["status"] == "succeeded"
    assert store.find(identity)["attempt"] == 2


def test_scheduler_blocks_strategy_without_matching_factor_success(tmp_path):
    store = ResearchJobStore(tmp_path / "research_jobs.db")

    result = run_due_once(
        now=SUNDAY_1000,
        trading_days=CALENDAR,
        data_snapshot=_snapshot(),
        store=store,
        factor_version="factor-v1",
        strategy_version="strategy-v1",
        qlib_version="qlib-v1",
        handlers={"strategy_weekly": lambda _job, _heartbeat: {"success": True}},
    )

    strategy = next(item for item in result if item["kind"] == "strategy_weekly")
    assert strategy["status"] == "blocked"
    assert strategy["reason_code"] == "factor_prerequisite_missing"


def test_scheduler_accepts_verified_daily_factor_publication_from_separate_store(
    tmp_path,
):
    store = ResearchJobStore(tmp_path / "research_jobs.db")
    snapshot = {
        **_snapshot(),
        "factor_publication_complete": True,
        "factor_publication_market_date": "20260807",
        "factor_publication_data_version": "pit-v1",
        "qlib_sync_complete": True,
        "qlib_market_date": "2026-08-07",
        "qlib_data_version": "qlib-data-v1",
    }
    qlib = store.claim(
        "qlib_weekly:2026-W32:qlib-data-v1:qlib-v1",
        kind="qlib_weekly",
        heavy=True,
        owner_pid=1,
        now=datetime(2026, 8, 8, 18, 30),
        params={
            "market_date": "2026-08-07",
            "data_version": "qlib-data-v1",
            "factory_version": "qlib-v1",
        },
    )
    store.finish(
        qlib.job_id,
        run_token=qlib.run_token,
        status="succeeded",
        result={"dataset_version": "qlib-data-v1"},
    )

    result = run_due_once(
        now=SUNDAY_1000,
        trading_days=CALENDAR,
        data_snapshot=snapshot,
        store=store,
        factor_version="factor-v1",
        strategy_version="strategy-v1",
        qlib_version="qlib-v1",
        lane="strategy",
        handlers={"strategy_weekly": lambda *_args: {"success": True}},
    )

    assert result[0]["status"] == "succeeded"


def test_strategy_weekly_does_not_require_qlib_weekly_task(tmp_path):
    store = ResearchJobStore(tmp_path / "research_jobs.db")
    calls = []
    snapshot = {
        **_snapshot(),
        "factor_publication_complete": True,
        "factor_publication_market_date": "20260807",
        "factor_publication_data_version": "pit-v1",
        "qlib_sync_complete": False,
        "qlib_market_date": "",
        "qlib_data_version": "qlib-independent-failure",
    }

    result = run_due_once(
        now=SUNDAY_1000,
        trading_days=CALENDAR,
        data_snapshot=snapshot,
        store=store,
        factor_version="factor-v1",
        strategy_version="strategy-v1",
        qlib_version="qlib-v1",
        lane="strategy",
        handlers={
            "strategy_weekly": lambda job, *_args: calls.append(job.kind)
            or {"success": True}
        },
    )

    assert calls == ["strategy_weekly"]
    assert result[0]["status"] == "succeeded"


def test_strategy_is_independent_from_qlib_dataset_version_changes(
    tmp_path,
):
    store = ResearchJobStore(tmp_path / "research_jobs.db")
    before_refresh = {
        **_snapshot(),
        "complete_market_date": "2026-08-28",
        "qlib_sync_complete": True,
        "qlib_market_date": "2026-08-21",
        "qlib_data_version": "qlib-data-20260821",
    }
    qlib_result = run_due_once(
        now=datetime(2026, 8, 29, 18, 30),
        trading_days={date(2026, 8, 28)},
        data_snapshot=before_refresh,
        store=store,
        factor_version="factor-v1",
        strategy_version="strategy-v1",
        qlib_version="qlib-v1",
        lane="qlib",
        handlers={
            "qlib_weekly": lambda *_args: {
                "success": True,
                "dataset_version": "qlib-data-20260828",
            }
        },
    )
    assert qlib_result[0]["status"] == "succeeded"

    after_refresh = {
        **before_refresh,
        "factor_publication_complete": True,
        "factor_publication_market_date": "2026-08-28",
        "factor_publication_data_version": "pit-v1",
        "qlib_market_date": "2026-08-28",
        "qlib_data_version": "qlib-data-20260828",
    }
    strategy_result = run_due_once(
        now=datetime(2026, 8, 30, 10, 0),
        trading_days={date(2026, 8, 28)},
        data_snapshot=after_refresh,
        store=store,
        factor_version="factor-v1",
        strategy_version="strategy-v1",
        qlib_version="qlib-v1",
        lane="strategy",
        handlers={"strategy_weekly": lambda *_args: {"success": True}},
    )

    assert strategy_result[0]["status"] == "succeeded"


def test_scheduler_ignores_failed_current_week_qlib_task(tmp_path):
    store = ResearchJobStore(tmp_path / "research_jobs.db")
    snapshot = {
        **_snapshot(),
        "factor_publication_complete": True,
        "factor_publication_market_date": "20260807",
        "factor_publication_data_version": "pit-v1",
        "qlib_sync_complete": True,
        "qlib_market_date": "2026-08-07",
        "qlib_data_version": "qlib-data-v1",
    }
    claim = store.claim(
        "qlib_weekly:2026-W32:qlib-data-v1:qlib-v1",
        kind="qlib_weekly",
        heavy=True,
        owner_pid=1,
        now=datetime(2026, 8, 8, 18, 30),
        params={
            "market_date": "2026-08-07",
            "data_version": "qlib-data-v1",
            "factory_version": "qlib-v1",
        },
    )
    store.finish(
        claim.job_id,
        run_token=claim.run_token,
        status="failed",
        result={"reason_code": "qlib_independent_failure"},
    )

    completed = run_due_once(
        now=SUNDAY_1000,
        trading_days=CALENDAR,
        data_snapshot=snapshot,
        store=store,
        factor_version="factor-v1",
        strategy_version="strategy-v1",
        qlib_version="qlib-v1",
        handlers={"strategy_weekly": lambda *_args: {"success": True}},
    )

    strategy = next(item for item in completed if item["kind"] == "strategy_weekly")
    assert strategy["status"] == "succeeded"


def test_scheduler_runs_strategy_when_qlib_weekly_also_succeeded(tmp_path):
    store = ResearchJobStore(tmp_path / "research_jobs.db")
    snapshot = {
        **_snapshot(),
        "factor_publication_complete": True,
        "factor_publication_market_date": "20260807",
        "factor_publication_data_version": "pit-v1",
        "qlib_sync_complete": True,
        "qlib_market_date": "2026-08-07",
        "qlib_data_version": "qlib-data-v1",
    }
    run_due_once(
        now=FRIDAY_1620,
        trading_days=CALENDAR,
        data_snapshot=snapshot,
        store=store,
        factor_version="factor-v1",
        strategy_version="strategy-v1",
        qlib_version="qlib-v1",
        handlers={"factor_daily": lambda *_args: {"success": True}},
    )
    saturday = datetime(2026, 8, 8, 18, 30)
    run_due_once(
        now=saturday,
        trading_days=CALENDAR,
        data_snapshot=snapshot,
        store=store,
        factor_version="factor-v1",
        strategy_version="strategy-v1",
        qlib_version="qlib-v1",
        handlers={"qlib_weekly": lambda *_args: {"success": True}},
    )

    completed = run_due_once(
        now=SUNDAY_1000,
        trading_days=CALENDAR,
        data_snapshot=snapshot,
        store=store,
        factor_version="factor-v1",
        strategy_version="strategy-v1",
        qlib_version="qlib-v1",
        handlers={"strategy_weekly": lambda *_args: {"success": True}},
    )

    strategy = next(item for item in completed if item["kind"] == "strategy_weekly")
    assert strategy["status"] == "succeeded"


def test_stale_or_incomplete_data_blocks_factor_before_handler(tmp_path):
    store = ResearchJobStore(tmp_path / "research_jobs.db")
    called = []
    snapshot = _snapshot()
    snapshot["factor_input_fresh"] = False

    result = run_due_once(
        now=FRIDAY_1620,
        trading_days=CALENDAR,
        data_snapshot=snapshot,
        store=store,
        factor_version="factor-v1",
        strategy_version="strategy-v1",
        qlib_version="qlib-v1",
        handlers={"factor_daily": lambda *_args: called.append(True)},
    )

    assert called == []
    assert result[0]["status"] == "blocked"
    assert result[0]["reason_code"] == "factor_input_stale"


def test_handler_failure_is_audited_as_failed_not_success(tmp_path):
    store = ResearchJobStore(tmp_path / "research_jobs.db")

    result = run_due_once(
        now=FRIDAY_1620,
        trading_days=CALENDAR,
        data_snapshot=_snapshot(),
        store=store,
        factor_version="factor-v1",
        strategy_version="strategy-v1",
        qlib_version="qlib-v1",
        handlers={
            "factor_daily": lambda *_args: {
                "success": False,
                "error": "upstream unavailable",
            }
        },
    )

    assert result[0]["status"] == "failed"
    assert store.list_jobs(1)[0]["status"] == "failed"


def test_successful_research_result_cannot_claim_promotion_or_execution(tmp_path):
    store = ResearchJobStore(tmp_path / "research_jobs.db")

    result = run_due_once(
        now=FRIDAY_1620,
        trading_days=CALENDAR,
        data_snapshot=_snapshot(),
        store=store,
        factor_version="factor-v1",
        strategy_version="strategy-v1",
        qlib_version="qlib-v1",
        handlers={
            "factor_daily": lambda *_args: {
                "success": True,
                "promotion_state": "production_candidate",
                "execution_authority": True,
            }
        },
    )

    assert result[0]["status"] == "succeeded"
    payload = store.list_jobs(1)[0]["result"]
    assert payload["promotion_state"] == "research_only"
    assert payload["execution_authority"] is False


def test_runtime_inputs_separate_daily_factor_snapshot_from_qlib_manifest(tmp_path, monkeypatch):
    manifest = tmp_path / "datasets" / "a_share_6y_daily" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        '{"status":"complete","dataset_version":"pit-v2","end_date":"2026-08-07"}',
        encoding="utf-8",
    )
    calendar = tmp_path / "provider" / "calendars" / "day.txt"
    calendar.parent.mkdir(parents=True)
    calendar.write_text("2026-08-06\n2026-08-07\n", encoding="utf-8")
    f4_latest = tmp_path / "research" / "f4" / "latest.json"
    f4_latest.parent.mkdir(parents=True)
    f4_latest.write_text(
        '{"validation_id":"f4-v2","portfolio_policy_version":"portfolio-v2",'
        '"promotion_state":"research_only","execution_authority":false}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "scripts.research_training_scheduler.resolve_data_path",
        lambda *parts: tmp_path.joinpath(*parts),
    )
    cache = MemoryCache()
    publish_snapshot(
        cache,
        DataSnapshot(
            snapshot_id="daily-20260813",
            dataset="a_share_daily",
            as_of="2026-08-13",
            published_at="2026-08-14T13:00:00+08:00",
            universe_version="u" * 64,
            expected_count=5203,
            available_count=5201,
            source_chain=("tdx_quant",),
            content_hash="d" * 64,
            quality_status="passed",
            freshness_status="fresh",
        ),
    )
    monkeypatch.setattr(
        "scripts.research_training_scheduler.create_cache",
        lambda: cache,
        raising=False,
    )
    monkeypatch.setattr(scheduler, "F4_LATEST_PATH", f4_latest)
    monkeypatch.setattr(
        scheduler,
        "DAILY_RESEARCH_ROOT",
        tmp_path / "research" / "daily",
    )
    monkeypatch.setattr(
        scheduler,
        "build_f4_readiness",
        lambda _root: {
            "status": "blocked",
            "reason_code": "factor_prerequisite_missing",
            "trigger_required": False,
        },
    )

    trading_days, snapshot = _load_runtime_inputs()

    assert trading_days == ["2026-08-06", "2026-08-07", "2026-08-13"]
    assert snapshot == {
        "sync_complete": True,
        "complete_market_date": "2026-08-13",
        "factor_input_fresh": True,
        "data_version": "d" * 64,
        "factor_publication_complete": False,
        "factor_publication_market_date": "",
        "factor_publication_data_version": "",
        "qlib_sync_complete": True,
        "qlib_market_date": "2026-08-07",
        "qlib_data_version": "pit-v2",
        "f4_validation_id": "f4-v2",
            "portfolio_policy_version": "portfolio-v2",
            "f4_readiness_status": "blocked",
            "f4_readiness_reason": "factor_prerequisite_missing",
            "f4_trigger_required": False,
        }


def test_runtime_inputs_use_actual_qlib_market_date_not_weekend_collection_date(
    tmp_path, monkeypatch
):
    manifest = tmp_path / "datasets" / "a_share_6y_daily" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        '{"status":"complete","dataset_version":"pit-v2","end_date":"2026-08-22"}',
        encoding="utf-8",
    )
    quality = manifest.parent / "quality_report.json"
    quality.write_text(
        '{"status":"passed","data_latest_date":"2026-08-21","expected_latest_date":"2026-08-21"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "scripts.research_training_scheduler.resolve_data_path",
        lambda *parts: tmp_path.joinpath(*parts),
    )
    cache = MemoryCache()
    publish_snapshot(
        cache,
        DataSnapshot(
            snapshot_id="daily-20260821",
            dataset="a_share_daily",
            as_of="2026-08-21",
            published_at="2026-08-21T16:20:00+08:00",
            universe_version="u" * 64,
            expected_count=5203,
            available_count=5201,
            source_chain=("tdx_quant",),
            content_hash="d" * 64,
            quality_status="passed",
            freshness_status="fresh",
        ),
    )
    monkeypatch.setattr(scheduler, "create_cache", lambda: cache)

    trading_days, snapshot = _load_runtime_inputs()

    assert trading_days == ["2026-08-21"]
    assert snapshot["qlib_market_date"] == "2026-08-21"


def test_incomplete_qlib_dataset_does_not_block_daily_factor(tmp_path):
    store = ResearchJobStore(tmp_path / "research_jobs.db")
    calls = []
    snapshot = {
        **_snapshot(),
        "qlib_sync_complete": False,
        "qlib_market_date": "",
        "qlib_data_version": "qlib-incomplete",
    }

    result = run_due_once(
        now=FRIDAY_1620,
        trading_days=CALENDAR,
        data_snapshot=snapshot,
        store=store,
        factor_version="factor-v1",
        strategy_version="strategy-v1",
        qlib_version="qlib-v1",
        handlers={
            "factor_daily": lambda job, _heartbeat: calls.append(job.kind)
            or {"success": True}
        },
    )

    assert calls == ["factor_daily"]
    assert result[0]["status"] == "succeeded"


def test_factor_handler_adopts_only_exact_existing_research_artifact(tmp_path, monkeypatch):
    artifact = tmp_path / "factor_evaluation.json"
    artifact.write_text(
        '{"data_version":"pit-v1","data_end_date":"20260807",'
        '"factors":[{"factor":"ret_5"}],"promotion_state":"research_only",'
        '"execution_authority":false}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "scripts.research_training_scheduler.FACTOR_EVALUATION_PATH",
        artifact,
        raising=False,
    )
    monkeypatch.setattr(
        "scripts.research_training_scheduler._run_deterministic_research_script",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not recompute")),
    )
    heartbeats = []
    job = ScheduledResearchJob(
        kind="factor_daily",
        idempotency_key="factor_daily:2026-08-07:pit-v1:factor-v1",
        market_date="2026-08-07",
        data_version="pit-v1",
        factory_version="factor-v1",
    )

    result = _factor_handler(job, lambda stage, progress: heartbeats.append((stage, progress)))

    assert result["success"] is True
    assert result["no_op"] is True
    assert result["reason_code"] == "factor_version_already_evaluated"
    assert result["dataset_version"] == "pit-v1"
    assert heartbeats[-1] == ("factor_artifact_verified", 1.0)

from datetime import datetime, timedelta, timezone

import pytest

from quant.research.job_store import ResearchJobStore


def test_idempotency_and_heavy_lease_are_atomic(tmp_path):
    store = ResearchJobStore(tmp_path / "research_jobs.db")
    first = store.claim(
        "qlib_weekly:2026-W32:v1:q1",
        kind="qlib_weekly",
        heavy=True,
        owner_pid=123,
    )

    assert first.claimed is True
    assert (
        store.claim(
            "qlib_weekly:2026-W32:v1:q1",
            kind="qlib_weekly",
            heavy=True,
            owner_pid=124,
        ).claimed
        is False
    )
    blocked = store.claim(
        "qlib_monthly:2026-08:v1:q1",
        kind="qlib_monthly",
        heavy=True,
        owner_pid=125,
    )
    assert blocked.claimed is False
    assert blocked.reason == "heavy_job_active"


def test_heartbeat_and_success_preserve_terminal_evidence(tmp_path):
    store = ResearchJobStore(tmp_path / "research_jobs.db")
    claim = store.claim(
        "factor_daily:2026-08-07:v1:f1",
        kind="factor_daily",
        heavy=False,
        owner_pid=123,
    )

    running = store.heartbeat(
        claim.job_id,
        run_token=claim.run_token,
        stage="ic_validation",
        progress=0.6,
    )
    finished = store.finish(
        claim.job_id,
        run_token=claim.run_token,
        status="succeeded",
        result={"dataset_version": "v1", "promotion_state": "shadow"},
    )

    assert running["stage"] == "ic_validation"
    assert running["progress"] == 0.6
    assert finished["status"] == "succeeded"
    assert finished["result"]["promotion_state"] == "shadow"
    assert finished["finished_at"]


def test_expired_owner_becomes_interrupted_before_retry(tmp_path):
    store = ResearchJobStore(tmp_path / "research_jobs.db", lease_seconds=60)
    claim = store.claim(
        "factor_daily:2026-08-07:v1:f1",
        kind="factor_daily",
        heavy=False,
        owner_pid=123,
    )

    recovered = store.recover_expired(
        now=datetime.now(timezone.utc) + timedelta(minutes=10),
        process_alive=lambda _pid: False,
    )

    assert recovered == [claim.job_id]
    assert store.get(claim.job_id)["status"] == "interrupted"


def test_failed_job_retries_same_identity_only_after_safe_backoff(tmp_path):
    started = datetime(2026, 8, 9, 3, 0, tzinfo=timezone.utc)
    store = ResearchJobStore(
        tmp_path / "research_jobs.db",
        retry_delay_seconds=900,
        max_attempts=3,
    )
    claim = store.claim(
        "factor_daily:2026-08-08:v1:f1",
        kind="factor_daily",
        heavy=False,
        owner_pid=123,
        now=started,
    )
    store.finish(
        claim.job_id,
        run_token=claim.run_token,
        status="failed",
        result={"reason_code": "source_unavailable"},
        error_code="source_unavailable",
        now=started,
    )

    cooling_down = store.claim(
        "factor_daily:2026-08-08:v1:f1",
        kind="factor_daily",
        heavy=False,
        owner_pid=124,
        now=started + timedelta(minutes=14),
    )
    retried = store.claim(
        "factor_daily:2026-08-08:v1:f1",
        kind="factor_daily",
        heavy=False,
        owner_pid=124,
        now=started + timedelta(minutes=15),
    )

    assert cooling_down.claimed is False
    assert cooling_down.reason == "retry_backoff"
    assert retried.claimed is True
    assert retried.job_id == claim.job_id
    assert retried.run_token != claim.run_token
    assert store.get(claim.job_id)["attempt"] == 2


def test_success_and_retry_exhaustion_remain_terminal(tmp_path):
    started = datetime(2026, 8, 9, 3, 0, tzinfo=timezone.utc)
    store = ResearchJobStore(
        tmp_path / "research_jobs.db",
        retry_delay_seconds=30,
        max_attempts=2,
    )
    claim = store.claim(
        "strategy_weekly:2026-W32:v1:s1",
        kind="strategy_weekly",
        heavy=False,
        owner_pid=123,
        now=started,
    )
    store.finish(
        claim.job_id,
        run_token=claim.run_token,
        status="failed",
        now=started,
    )
    retry = store.claim(
        "strategy_weekly:2026-W32:v1:s1",
        kind="strategy_weekly",
        heavy=False,
        owner_pid=124,
        now=started + timedelta(seconds=30),
    )
    store.finish(
        retry.job_id,
        run_token=retry.run_token,
        status="failed",
        now=started + timedelta(seconds=30),
    )

    exhausted = store.claim(
        "strategy_weekly:2026-W32:v1:s1",
        kind="strategy_weekly",
        heavy=False,
        owner_pid=125,
        now=started + timedelta(minutes=10),
    )

    assert exhausted.claimed is False
    assert exhausted.reason == "retry_exhausted"


def test_live_process_is_not_recovered_when_heartbeat_is_old(tmp_path):
    store = ResearchJobStore(tmp_path / "research_jobs.db", lease_seconds=60)
    claim = store.claim(
        "factor_daily:2026-08-07:v1:f1",
        kind="factor_daily",
        heavy=False,
        owner_pid=123,
    )

    recovered = store.recover_expired(
        now=datetime.now(timezone.utc) + timedelta(minutes=10),
        process_alive=lambda _pid: True,
    )

    assert recovered == []
    assert store.get(claim.job_id)["status"] == "running"


@pytest.mark.parametrize(
    "state", ["paper_active", "production_candidate", "approved", "live"]
)
def test_scheduler_ledger_rejects_production_promotion_states(tmp_path, state):
    store = ResearchJobStore(tmp_path / "research_jobs.db")
    claim = store.claim(
        "strategy_weekly:2026-W32:v1:s1",
        kind="strategy_weekly",
        heavy=False,
        owner_pid=123,
    )

    with pytest.raises(ValueError, match="promotion state"):
        store.finish(
            claim.job_id,
            run_token=claim.run_token,
            status="succeeded",
            result={"promotion_state": state},
        )

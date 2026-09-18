from datetime import date, datetime

from quant.research.training_schedule import due_research_jobs


TRADING_DAYS = {
    date(2026, 8, 7),
    date(2026, 9, 4),
    date(2026, 10, 2),
}


def _due(now: datetime):
    return due_research_jobs(
        now=now,
        trading_days=TRADING_DAYS,
        data_version="pit-v1",
        factor_version="factor-v1",
        strategy_version="strategy-v1",
        qlib_version="qlib-v1",
        f4_validation_id="f4-v1",
        portfolio_policy_version="portfolio-v1",
    )


def test_factor_is_due_after_1620_on_trading_day():
    jobs = _due(datetime(2026, 8, 7, 16, 20))

    assert [job.kind for job in jobs] == [
        "factor_daily",
        "research_selection_daily",
    ]
    assert jobs[0].market_date == "2026-08-07"
    assert (
        jobs[0].idempotency_key
        == "factor_daily:2026-08-07:pit-v1:factor-v1"
    )
    assert jobs[1].idempotency_key == (
        "research_selection_daily:2026-08-07:pit-v1:factor-v1:"
        "f4-v1:portfolio-v1"
    )


def test_factor_waits_for_cutoff_but_missed_trading_day_remains_due():
    assert _due(datetime(2026, 8, 7, 16, 19)) == []
    saturday_jobs = _due(datetime(2026, 8, 8, 16, 20))
    assert [job.kind for job in saturday_jobs] == [
        "factor_daily",
        "research_selection_daily",
    ]
    assert saturday_jobs[0].market_date == "2026-08-07"


def test_factor_missed_after_close_is_due_on_next_morning():
    jobs = _due(datetime(2026, 8, 8, 8, 30))

    assert [job.kind for job in jobs] == [
        "factor_daily",
        "research_selection_daily",
    ]
    assert jobs[0].market_date == "2026-08-07"


def test_strategy_is_due_sunday_after_1000_with_stable_iso_week_key():
    jobs = _due(datetime(2026, 8, 9, 10, 0))

    assert [job.kind for job in jobs] == [
        "factor_daily",
        "research_selection_daily",
        "strategy_weekly",
    ]
    assert jobs[2].market_date == "2026-08-07"
    assert (
        jobs[2].idempotency_key
        == "strategy_weekly:2026-W32:pit-v1:strategy-v1"
    )
    assert jobs[2].heavy is True


def test_strategy_is_not_due_before_sunday_cutoff():
    assert "strategy_weekly" not in [
        job.kind for job in _due(datetime(2026, 8, 8, 18, 30))
    ]
    assert "strategy_weekly" not in [
        job.kind for job in _due(datetime(2026, 8, 9, 9, 59))
    ]


def test_monthly_qlib_replaces_weekly_on_first_eligible_saturday():
    jobs = _due(datetime(2026, 9, 5, 18, 30))

    assert [job.kind for job in jobs if job.kind.startswith("qlib_")] == [
        "qlib_monthly"
    ]
    assert jobs[-1].idempotency_key == "qlib_monthly:2026-09:pit-v1:qlib-v1"


def test_quarterly_qlib_replaces_monthly_and_weekly():
    jobs = _due(datetime(2026, 10, 3, 18, 30))

    assert [job.kind for job in jobs if job.kind.startswith("qlib_")] == [
        "qlib_quarterly"
    ]
    assert jobs[-1].idempotency_key == "qlib_quarterly:2026-Q3:pit-v1:qlib-v1"


def test_weekly_qlib_runs_on_non_monthly_saturday():
    jobs = _due(datetime(2026, 8, 8, 18, 30))

    assert [job.kind for job in jobs] == [
        "factor_daily",
        "research_selection_daily",
        "qlib_weekly",
    ]
    assert jobs[-1].idempotency_key == "qlib_weekly:2026-W32:pit-v1:qlib-v1"

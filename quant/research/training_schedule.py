from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Iterable


FACTOR_CUTOFF = time(16, 20)
STRATEGY_CUTOFF = time(10, 0)
QLIB_CUTOFF = time(18, 30)
STRATEGY_WEEKDAY = 6
QLIB_WEEKDAY = 5


@dataclass(frozen=True, slots=True)
class ScheduledResearchJob:
    kind: str
    idempotency_key: str
    market_date: str
    data_version: str
    factory_version: str
    heavy: bool = False


def _calendar_days(values: Iterable[date | datetime | str]) -> tuple[date, ...]:
    days: set[date] = set()
    for value in values:
        if isinstance(value, datetime):
            days.add(value.date())
        elif isinstance(value, date):
            days.add(value)
        else:
            days.add(date.fromisoformat(str(value)[:10]))
    return tuple(sorted(days))


def _latest_market_date(now: datetime, trading_days: tuple[date, ...]) -> date | None:
    eligible = [day for day in trading_days if day <= now.date()]
    return eligible[-1] if eligible else None


def _is_first_saturday_of_month(day: date) -> bool:
    return day.weekday() == 5 and day.day <= 7


def _completed_quarter(day: date) -> tuple[int, int]:
    if day.month == 1:
        return day.year - 1, 4
    return day.year, (day.month - 1) // 3


def due_research_jobs(
    *,
    now: datetime,
    trading_days: Iterable[date | datetime | str],
    data_version: str,
    factor_version: str,
    strategy_version: str,
    qlib_version: str = "qlib-v1",
    qlib_data_version: str | None = None,
    f4_validation_id: str = "",
    portfolio_policy_version: str = "",
) -> list[ScheduledResearchJob]:
    """Return deterministic work due by ``now`` without inspecting mutable state."""

    calendar = _calendar_days(trading_days)
    market_day = _latest_market_date(now, calendar)
    if market_day is None:
        return []
    market_date = market_day.isoformat()
    jobs: list[ScheduledResearchJob] = []

    # A missed post-close run must remain due on later days. The job store's
    # idempotency key prevents duplicate evaluation after a successful run.
    factor_window_open = (
        market_day < now.date()
        or (market_day == now.date() and now.time() >= FACTOR_CUTOFF)
    )
    if factor_window_open:
        jobs.append(
            ScheduledResearchJob(
                kind="factor_daily",
                idempotency_key=(
                    f"factor_daily:{market_date}:{data_version}:{factor_version}"
                ),
                market_date=market_date,
                data_version=str(data_version),
                factory_version=str(factor_version),
            )
        )
        if str(f4_validation_id).strip() and str(portfolio_policy_version).strip():
            jobs.append(
                ScheduledResearchJob(
                    kind="research_selection_daily",
                    idempotency_key=(
                        f"research_selection_daily:{market_date}:{data_version}:"
                        f"{factor_version}:{f4_validation_id}:"
                        f"{portfolio_policy_version}"
                    ),
                    market_date=market_date,
                    data_version=str(data_version),
                    factory_version=(
                        f"{factor_version}:{f4_validation_id}:"
                        f"{portfolio_policy_version}"
                    ),
                )
            )

    iso_year, iso_week, _ = now.date().isocalendar()
    if now.weekday() == STRATEGY_WEEKDAY and now.time() >= STRATEGY_CUTOFF:
        jobs.append(
            ScheduledResearchJob(
                kind="strategy_weekly",
                idempotency_key=(
                    f"strategy_weekly:{iso_year}-W{iso_week:02d}:"
                    f"{data_version}:{strategy_version}"
                ),
                market_date=market_date,
                data_version=str(data_version),
                factory_version=str(strategy_version),
                heavy=True,
            )
        )

    if now.weekday() != QLIB_WEEKDAY or now.time() < QLIB_CUTOFF:
        return jobs

    if _is_first_saturday_of_month(now.date()) and now.month in (1, 4, 7, 10):
        quarter_year, quarter = _completed_quarter(now.date())
        kind = "qlib_quarterly"
        period = f"{quarter_year}-Q{quarter}"
    elif _is_first_saturday_of_month(now.date()):
        kind = "qlib_monthly"
        period = f"{now.year}-{now.month:02d}"
    else:
        kind = "qlib_weekly"
        period = f"{iso_year}-W{iso_week:02d}"
    qlib_input_version = str(qlib_data_version or data_version)
    jobs.append(
        ScheduledResearchJob(
            kind=kind,
            idempotency_key=f"{kind}:{period}:{qlib_input_version}:{qlib_version}",
            market_date=market_date,
            data_version=qlib_input_version,
            factory_version=str(qlib_version),
            heavy=True,
        )
    )
    return jobs

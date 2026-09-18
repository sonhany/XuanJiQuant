"""Point-in-time financial filtering and trailing-twelve-month metrics."""
from __future__ import annotations

from statistics import median
from typing import Any

from .contracts import safe_number


DATE_FIELDS = ("ann_date", "f_ann_date", "data_date", "update_date")
PERIOD_FIELDS = ("report_period", "report_date", "end_date")
TTM_FIELDS = (
    "revenue",
    "net_profit",
    "operating_cash_flow",
    "enterprise_fcf_per_share",
    "shareholder_fcf_per_share",
    "pre_tax_profit",
    "income_tax",
)


def _date(value: Any) -> str:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    return digits[:14]


def _period(row: dict) -> str:
    for field in PERIOD_FIELDS:
        value = _date(row.get(field))
        if len(value) >= 8:
            return value[:8]
    return ""


def _announcement(row: dict) -> str:
    values = [_date(row.get(field)) for field in DATE_FIELDS]
    return max((value for value in values if len(value) >= 8), default="")


def filter_point_in_time_records(
    records: list[dict],
    valuation_as_of: Any,
) -> dict:
    """Exclude financial statements not yet public at the valuation timestamp."""
    cutoff = _date(valuation_as_of)
    cutoff_day = cutoff[:8] if len(cutoff) >= 8 else "99999999"
    selected: list[dict] = []
    announcement_dates: list[str] = []
    missing_announcement = 0
    excluded = 0
    for item in records:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        announcement = _announcement(row)
        if announcement and announcement[:8] > cutoff_day:
            excluded += 1
            continue
        if announcement:
            announcement_dates.append(announcement)
        else:
            missing_announcement += 1
        selected.append(row)
    selected.sort(key=_period)

    if selected and not missing_announcement:
        quality, quality_score = "announcement_date", 1.0
    elif selected and announcement_dates:
        quality, quality_score = "mixed_date_basis", 0.85
    elif selected:
        quality, quality_score = "report_period_only", 0.75
    else:
        quality, quality_score = "unavailable", 0.0

    warnings: list[str] = []
    if excluded:
        warnings.append(f"excluded {excluded} financial records not public as of valuation")
    if quality == "mixed_date_basis":
        warnings.append("some financial records lack announcement dates")
    elif quality == "report_period_only":
        warnings.append("financial point-in-time check uses report periods only")
    return {
        "records": selected,
        "financial_as_of": max(announcement_dates, default=None),
        "quality": quality,
        "quality_score": quality_score,
        "excluded_count": excluded,
        "warnings": warnings,
    }


def annual_records(records: list[dict]) -> list[dict]:
    """Return chronologically sorted annual financial records."""
    rows = [
        dict(row)
        for row in records
        if isinstance(row, dict) and _period(row).endswith("1231")
    ]
    rows.sort(key=_period)
    return rows


def _copy_metrics(row: dict) -> dict[str, float]:
    result: dict[str, float] = {}
    for field in TTM_FIELDS:
        value = safe_number(row.get(field))
        if value is not None:
            result[field] = value
    return result


def build_ttm_metrics(records: list[dict]) -> dict:
    """Build TTM values using annual + current YTD - prior-year YTD."""
    rows = [dict(row) for row in records if isinstance(row, dict) and _period(row)]
    rows.sort(key=_period)
    if not rows:
        return {"period": None, "formula": "unavailable"}
    latest = rows[-1]
    latest_period = _period(latest)
    if latest_period.endswith("1231"):
        return {
            "period": latest_period,
            "formula": "latest_annual",
            **_copy_metrics(latest),
        }

    latest_year = int(latest_period[:4])
    annual = next(
        (
            row
            for row in reversed(rows)
            if _period(row).endswith("1231")
            and int(_period(row)[:4]) < latest_year
        ),
        None,
    )
    prior_period = f"{latest_year - 1}{latest_period[4:8]}"
    prior_ytd = next((row for row in rows if _period(row) == prior_period), None)
    if annual is None or prior_ytd is None:
        return {
            "period": latest_period,
            "formula": "latest_ytd_incomplete",
            **_copy_metrics(latest),
        }

    values: dict[str, float] = {}
    for field in TTM_FIELDS:
        annual_value = safe_number(annual.get(field))
        current_value = safe_number(latest.get(field))
        prior_value = safe_number(prior_ytd.get(field))
        if None not in (annual_value, current_value, prior_value):
            values[field] = annual_value + current_value - prior_value
    return {
        "period": latest_period,
        "formula": "latest_annual+current_ytd-prior_ytd",
        **values,
    }


def derive_earnings_growth(records: list[dict]) -> float | None:
    """Derive robust profit growth from annual statements."""
    annual_profit: list[tuple[str, float]] = []
    reported_growth: list[tuple[str, float]] = []
    for row in records:
        if not isinstance(row, dict):
            continue
        period = _period(row)
        profit = safe_number(row.get("net_profit"))
        growth = safe_number(
            row.get("profit_growth")
            if row.get("profit_growth") is not None
            else row.get("net_profit_growth")
        )
        if period.endswith("1231") and profit is not None and profit > 0:
            annual_profit.append((period, profit))
        if period and growth is not None:
            reported_growth.append((period, growth))
    annual_profit.sort(key=lambda item: item[0])
    year_over_year = [
        current / previous - 1
        for (_, previous), (_, current) in zip(annual_profit, annual_profit[1:])
        if previous > 0 and current > 0
    ]
    if year_over_year:
        return median(year_over_year[-5:])
    reported_growth.sort(key=lambda item: item[0])
    recent = [value for _, value in reported_growth[-5:]]
    if not recent:
        return None
    percent_units = any(abs(value) > 1 for value in recent)
    return median(value / 100.0 if percent_units else value for value in recent)

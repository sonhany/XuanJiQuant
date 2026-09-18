from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable


def _iso_date(value: Any) -> str:
    text = str(value or "")[:10]
    digits = text.replace("-", "")
    if len(digits) >= 8 and digits[:8].isdigit():
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return ""


def _is_st_name(value: Any) -> bool:
    name = str(value or "").upper().replace(" ", "")
    return "ST" in name or "退" in name


def build_st_intervals(
    instrument: str,
    changes: Iterable[dict[str, Any]],
) -> list[dict[str, str]]:
    ordered = sorted(
        (
            {
                "date": _iso_date(row.get("date") or row.get("变更日期")),
                "before": str(row.get("before") or row.get("变更前简称") or ""),
                "after": str(row.get("after") or row.get("变更后简称") or ""),
            }
            for row in changes or []
        ),
        key=lambda row: row["date"],
    )
    intervals: list[dict[str, str]] = []
    open_start = ""
    for change in ordered:
        if not change["date"]:
            continue
        before_st = _is_st_name(change["before"])
        after_st = _is_st_name(change["after"])
        if after_st and not before_st and not open_start:
            open_start = change["date"]
        elif before_st and not after_st and open_start:
            end = date.fromisoformat(change["date"]) - timedelta(days=1)
            intervals.append(
                {
                    "instrument": instrument,
                    "start_date": open_start,
                    "end_date": end.isoformat(),
                    "status": "st",
                }
            )
            open_start = ""
    if open_start:
        intervals.append(
            {
                "instrument": instrument,
                "start_date": open_start,
                "end_date": "",
                "status": "st",
            }
        )
    return intervals


def _inside_interval(trade_date: str, interval: dict[str, Any]) -> bool:
    start = _iso_date(interval.get("start_date"))
    end = _iso_date(interval.get("end_date"))
    return bool(start and trade_date >= start and (not end or trade_date <= end))


def build_daily_mask(
    instrument: str,
    trade_date: str,
    *,
    listing_date: str,
    delisting_date: str,
    st_intervals: Iterable[dict[str, Any]],
    historical_st_uncertain: bool,
    volume: float,
    limit_up: bool = False,
    limit_down: bool = False,
) -> dict[str, Any]:
    current = _iso_date(trade_date)
    listed_on = _iso_date(listing_date)
    delisted_on = _iso_date(delisting_date)
    listed = not listed_on or current >= listed_on
    delisted = bool(delisted_on and current > delisted_on)
    is_st = any(_inside_interval(current, interval) for interval in st_intervals or [])
    if is_st:
        st_status = "st"
    elif historical_st_uncertain:
        st_status = "unknown"
    else:
        st_status = "normal"
    paused = float(volume or 0) <= 0
    tradable = (
        listed
        and not delisted
        and st_status == "normal"
        and not paused
        and not limit_up
        and not limit_down
    )
    sources = ["price_volume"]
    if listed_on or delisted_on:
        sources.append("listing_interval")
    if st_intervals:
        sources.append("name_changes")
    if historical_st_uncertain:
        sources.append("historical_st_unknown")
    return {
        "instrument": instrument,
        "datetime": current,
        "listed": listed,
        "delisted": delisted,
        "is_st": is_st,
        "st_status": st_status,
        "paused": paused,
        "limit_up": bool(limit_up),
        "limit_down": bool(limit_down),
        "tradable": tradable,
        "status_sources": sources,
    }

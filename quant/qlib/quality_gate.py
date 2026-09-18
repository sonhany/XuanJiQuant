from __future__ import annotations

import hashlib
import json
from typing import Any


GATE_VERSION = "qlib_phase1_gate_v1"
THRESHOLDS = {
    "coverage": 0.98,
    "recent_coverage": 0.99,
    "trading_days": 1200,
    "duplicate_rows": 0,
    "invalid_ohlc": 0,
    "non_positive_factors": 0,
    "unknown_st_samples": 0,
    "invalid_lifecycle_samples": 0,
}


def calculate_lifecycle_coverage(
    *,
    trading_days: list[str],
    symbols: list[dict[str, Any]],
) -> dict[str, Any]:
    """Measure PIT coverage only inside each instrument's listed lifecycle."""

    calendar = sorted({str(value)[:10] for value in trading_days if str(value)[:10]})
    expected_samples = 0
    observed_samples = 0
    for row in symbols:
        listing = str(row.get("listing_date") or "")[:10]
        delisting = str(row.get("delisting_date") or "")[:10]
        eligible = {
            day
            for day in calendar
            if (not listing or day >= listing) and (not delisting or day <= delisting)
        }
        observed = {
            str(day)[:10]
            for day in (row.get("observed_dates") or [])
            if str(day)[:10] in eligible
        }
        expected_samples += len(eligible)
        observed_samples += len(observed)
    coverage = observed_samples / expected_samples if expected_samples else 0.0
    return {
        "expected_samples": expected_samples,
        "observed_samples": observed_samples,
        "coverage": coverage,
    }


def _report_id(dataset_version: str) -> str:
    identity = json.dumps(
        {
            "dataset_version": dataset_version,
            "gate_version": GATE_VERSION,
            "thresholds": THRESHOLDS,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"quality_{hashlib.sha256(identity).hexdigest()[:20]}"


def check_dataset_quality(
    *,
    requested: int,
    completed: int,
    recent_coverage: float,
    trading_days: int,
    latest_date_matches: bool,
    duplicate_rows: int,
    invalid_ohlc: int,
    non_positive_factors: int,
    unknown_st_samples: int,
    invalid_lifecycle_samples: int,
    dataset_version: str,
    coverage_override: float | None = None,
) -> dict[str, Any]:
    coverage = (
        float(coverage_override)
        if coverage_override is not None
        else (completed / requested if requested else 0.0)
    )
    reasons = []
    if coverage < 0.98:
        reasons.append("coverage_below_98pct")
    if float(recent_coverage) < 0.99:
        reasons.append("recent_coverage_below_99pct")
    if int(trading_days) < 1200:
        reasons.append("trading_days_below_1200")
    if not latest_date_matches:
        reasons.append("latest_date_mismatch")
    if int(duplicate_rows) > 0:
        reasons.append("duplicate_rows")
    if int(invalid_ohlc) > 0:
        reasons.append("invalid_ohlc")
    if int(non_positive_factors) > 0:
        reasons.append("non_positive_factor")
    if int(unknown_st_samples) > 0:
        reasons.append("unknown_st_in_training")
    if int(invalid_lifecycle_samples) > 0:
        reasons.append("invalid_lifecycle_sample")
    return {
        "report_id": _report_id(dataset_version),
        "dataset_version": str(dataset_version),
        "gate_version": GATE_VERSION,
        "thresholds": dict(THRESHOLDS),
        "passed": not reasons,
        "status": "passed" if not reasons else "failed",
        "reason_codes": reasons,
        "metrics": {
            "requested": int(requested),
            "completed": int(completed),
            "coverage": coverage,
            "recent_coverage": float(recent_coverage),
            "trading_days": int(trading_days),
            "latest_date_matches": bool(latest_date_matches),
            "duplicate_rows": int(duplicate_rows),
            "invalid_ohlc": int(invalid_ohlc),
            "non_positive_factors": int(non_positive_factors),
            "unknown_st_samples": int(unknown_st_samples),
            "invalid_lifecycle_samples": int(invalid_lifecycle_samples),
        },
    }

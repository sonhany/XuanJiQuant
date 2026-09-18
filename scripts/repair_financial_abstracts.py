"""Audit and repair missing profit and cash-flow fields in financial abstracts."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Callable, Iterable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant.data.akshare_source import fetch_core_financials
from quant.data.cache import create_cache
from quant.data.financial_quality import (
    REQUIRED_FINANCIAL_FIELDS,
    analyze_financial_history,
)

REQUIRED_CASHFLOW_FIELDS = REQUIRED_FINANCIAL_FIELDS


def _has_value(value: Any) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, float) and math.isnan(value):
        return False
    return True


def _records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(row) for row in value if isinstance(row, dict)]


def _period(row: dict[str, Any]) -> str:
    return str(
        row.get("report_date")
        or row.get("period")
        or row.get("end_date")
        or ""
    ).replace("-", "")


def missing_required_fields(records: Any) -> list[str]:
    rows = _records(records)
    return [
        field
        for field in REQUIRED_CASHFLOW_FIELDS
        if not any(_has_value(row.get(field)) for row in rows)
    ]


def latest_missing_required_fields(records: Any) -> list[str]:
    rows = _records(records)
    latest = max(rows, key=_period) if rows else {}
    return [
        field
        for field in REQUIRED_CASHFLOW_FIELDS
        if not _has_value(latest.get(field))
    ]


def _first_value(source: Any, keys: Iterable[str]) -> Any:
    if not isinstance(source, dict):
        return None
    for key in keys:
        value = source.get(key)
        if _has_value(value):
            return value
    return None


def extract_crosscheck_record(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    merged = value.get("merged") if isinstance(value.get("merged"), dict) else {}
    tables = merged.get("tables") if isinstance(merged.get("tables"), dict) else {}
    income = tables.get("income") if isinstance(tables.get("income"), dict) else {}
    performance = (
        tables.get("performance")
        if isinstance(tables.get("performance"), dict)
        else {}
    )
    cashflow = (
        tables.get("cashflow")
        if isinstance(tables.get("cashflow"), dict)
        else {}
    )

    candidates: list[dict[str, Any]] = []
    records = _records(value.get("akshare_records"))
    if records:
        candidates.append(max(records, key=_period))
    latest = merged.get("latest_akshare_report")
    if isinstance(latest, dict):
        candidates.append(latest)
    candidates.extend([merged, income, performance, cashflow])

    def pick(*keys: str) -> Any:
        for source in candidates:
            found = _first_value(source, keys)
            if _has_value(found):
                return found
        return None

    record = {
        "code": str(merged.get("code") or value.get("code") or ""),
        "report_date": str(
            merged.get("period")
            or pick("report_date", "period", "end_date")
            or ""
        ).replace("-", ""),
        "revenue": pick(
            "revenue",
            "营业总收入",
            "营业收入",
            "营业总收入-营业总收入",
        ),
        "net_profit": pick(
            "net_profit",
            "归母净利润",
            "净利润",
            "净利润-净利润",
        ),
        "operating_cash_flow": pick(
            "operating_cash_flow",
            "经营现金流量净额",
            "经营活动产生的现金流量净额",
            "经营性现金流-现金流量净额",
        ),
    }
    if not record["report_date"] or missing_required_fields([record]):
        return None
    return record


def backfill_from_crosschecks(
    codes: Iterable[str],
    cache,
) -> dict[str, Any]:
    selected_codes = list(
        dict.fromkeys(
            str(code).strip()
            for code in codes
            if str(code).strip()
        )
    )
    result: dict[str, Any] = {
        "total": len(selected_codes),
        "backfilled": 0,
        "failed": 0,
        "backfilled_codes": [],
        "failures": {},
    }
    for code in selected_codes:
        record = extract_crosscheck_record(
            cache.get(f"fin:crosscheck:{code}")
        )
        if record is None:
            result["failed"] += 1
            result["failures"][code] = "complete crosscheck record unavailable"
            continue
        key = f"fin:abstract:{code}"
        merged = merge_financial_records(cache.get(key), [record])
        if latest_missing_required_fields(merged):
            result["failed"] += 1
            result["failures"][code] = "crosscheck merge remains incomplete"
            continue
        cache.set(key, merged)
        result["backfilled"] += 1
        result["backfilled_codes"].append(code)

    result["backfilled_codes"].sort()
    result["failures"] = dict(sorted(result["failures"].items()))
    return result


def _table_records(value: Any) -> list[dict[str, Any]]:
    if hasattr(value, "to_dict"):
        if getattr(value, "empty", False):
            return []
        value = value.to_dict(orient="records")
    return _records(value)


def _normalized_code(value: Any) -> str:
    code = str(value or "").strip()
    if code.endswith(".0") and code[:-2].isdigit():
        code = code[:-2]
    return code.zfill(6) if code.isdigit() else code


def _records_by_code(value: Any) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in _table_records(value):
        code = _normalized_code(
            _first_value(row, ("股票代码", "代码", "code"))
        )
        if code:
            indexed[code] = row
    return indexed


def backfill_from_bulk_periods(
    codes: Iterable[str],
    cache,
    *,
    income_fetcher: Callable[[str], Any] | None = None,
    cashflow_fetcher: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    if income_fetcher is None or cashflow_fetcher is None:
        import akshare as ak

        income_fetcher = income_fetcher or (
            lambda period: ak.stock_lrb_em(date=period)
        )
        cashflow_fetcher = cashflow_fetcher or (
            lambda period: ak.stock_xjll_em(date=period)
        )

    grouped: dict[str, list[tuple[str, list[str]]]] = {}
    for code in dict.fromkeys(
        str(item).strip()
        for item in codes
        if str(item).strip()
    ):
        rows = _records(cache.get(f"fin:abstract:{code}"))
        period = _period(max(rows, key=_period)) if rows else ""
        missing = latest_missing_required_fields(rows)
        if period and missing:
            grouped.setdefault(period, []).append((code, missing))

    result: dict[str, Any] = {
        "total": sum(len(items) for items in grouped.values()),
        "backfilled": 0,
        "failed": 0,
        "backfilled_codes": [],
        "failures": {},
    }
    for period, items in sorted(grouped.items()):
        needs_income = any(
            "revenue" in missing or "net_profit" in missing
            for _, missing in items
        )
        needs_cashflow = any(
            "operating_cash_flow" in missing
            for _, missing in items
        )
        income_rows: dict[str, dict[str, Any]] = {}
        cashflow_rows: dict[str, dict[str, Any]] = {}
        income_error = cashflow_error = ""
        if needs_income:
            try:
                income_rows = _records_by_code(income_fetcher(period))
            except Exception as exc:
                income_error = f"{type(exc).__name__}: {str(exc)[:160]}"
        if needs_cashflow:
            try:
                cashflow_rows = _records_by_code(cashflow_fetcher(period))
            except Exception as exc:
                cashflow_error = f"{type(exc).__name__}: {str(exc)[:160]}"

        for code, missing in items:
            income = income_rows.get(code, {})
            cashflow = cashflow_rows.get(code, {})
            record = {
                "code": code,
                "report_date": period,
                "revenue": _first_value(
                    income,
                    ("营业总收入", "营业收入"),
                ),
                "net_profit": _first_value(
                    income,
                    ("净利润", "归属母公司股东的净利润"),
                ),
                "operating_cash_flow": _first_value(
                    cashflow,
                    (
                        "经营性现金流-现金流量净额",
                        "经营活动产生的现金流量净额",
                    ),
                ),
            }
            key = f"fin:abstract:{code}"
            merged = merge_financial_records(cache.get(key), [record])
            remaining = latest_missing_required_fields(merged)
            if remaining:
                reasons = []
                if income_error and any(
                    field in missing
                    for field in ("revenue", "net_profit")
                ):
                    reasons.append(f"income source failed: {income_error}")
                if cashflow_error and "operating_cash_flow" in missing:
                    reasons.append(
                        f"cashflow source failed: {cashflow_error}"
                    )
                reasons.append(f"still missing: {','.join(remaining)}")
                result["failed"] += 1
                result["failures"][code] = "; ".join(reasons)
                continue
            cache.set(key, merged)
            result["backfilled"] += 1
            result["backfilled_codes"].append(code)

    result["backfilled_codes"].sort()
    result["failures"] = dict(sorted(result["failures"].items()))
    return result


def backfill_historical_periods(
    codes: Iterable[str],
    cache,
    *,
    start_period: str,
    periods: Iterable[str] | None = None,
    income_fetcher: Callable[[str], Any] | None = None,
    cashflow_fetcher: Callable[[str], Any] | None = None,
    workers: int = 4,
    source_retries: int = 2,
    retry_delay_seconds: float = 1.5,
    progress: Callable[[int, int, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if income_fetcher is None or cashflow_fetcher is None:
        import akshare as ak

        income_fetcher = income_fetcher or (
            lambda period: ak.stock_lrb_em(date=period)
        )
        cashflow_fetcher = cashflow_fetcher or (
            lambda period: ak.stock_xjll_em(date=period)
        )

    selected_codes = list(
        dict.fromkeys(
            str(code).strip()
            for code in codes
            if str(code).strip()
        )
    )
    selected_periods = {
        str(period).replace("-", "")
        for period in (periods or [])
        if str(period).strip()
    }
    targets: dict[str, dict[str, list[str]]] = defaultdict(dict)
    for code in selected_codes:
        for row in _records(cache.get(f"fin:abstract:{code}")):
            period = _period(row)
            if not period or period < str(start_period):
                continue
            if selected_periods and period not in selected_periods:
                continue
            missing = [
                field
                for field in REQUIRED_CASHFLOW_FIELDS
                if not _has_value(row.get(field))
            ]
            if missing:
                targets[period][code] = missing

    target_pairs = {
        (code, period)
        for period, items in targets.items()
        for code in items
    }
    result: dict[str, Any] = {
        "target_periods": len(targets),
        "target_records": len(target_pairs),
        "updated_records": 0,
        "completed_records": 0,
        "remaining_records": len(target_pairs),
        "source_failures": {},
    }
    if not targets:
        return result

    def fetch_with_retry(
        source_name: str,
        fetcher: Callable[[str], Any],
        period: str,
    ) -> tuple[dict[str, dict[str, Any]], str]:
        attempts = max(1, int(source_retries) + 1)
        for attempt in range(attempts):
            try:
                return _records_by_code(fetcher(period)), ""
            except Exception as exc:
                if attempt + 1 >= attempts:
                    return {}, (
                        f"{source_name} {type(exc).__name__}: "
                        f"{str(exc)[:160]} after {attempts} attempts"
                    )
                delay = max(0.0, float(retry_delay_seconds)) * (attempt + 1)
                if delay:
                    time.sleep(delay)
        return {}, f"{source_name} source retry exhausted"

    def fetch_period(period: str):
        items = targets[period]
        needs_income = any(
            "revenue" in missing or "net_profit" in missing
            for missing in items.values()
        )
        needs_cashflow = any(
            "operating_cash_flow" in missing
            for missing in items.values()
        )
        income_rows: dict[str, dict[str, Any]] = {}
        cashflow_rows: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        if needs_income:
            income_rows, income_error = fetch_with_retry(
                "income",
                income_fetcher,
                period,
            )
            if income_error:
                errors.append(income_error)
        if needs_cashflow:
            cashflow_rows, cashflow_error = fetch_with_retry(
                "cashflow",
                cashflow_fetcher,
                period,
            )
            if cashflow_error:
                errors.append(cashflow_error)
        return period, income_rows, cashflow_rows, errors

    updates_by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    completed_periods = 0
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
        futures = {
            pool.submit(fetch_period, period): period
            for period in sorted(targets)
        }
        for future in as_completed(futures):
            period, income_rows, cashflow_rows, errors = future.result()
            if errors:
                result["source_failures"][period] = errors
            for code in targets[period]:
                income = income_rows.get(code, {})
                cashflow = cashflow_rows.get(code, {})
                update = {
                    "report_date": period,
                    "code": code,
                    "revenue": _first_value(
                        income,
                        ("营业总收入", "营业收入"),
                    ),
                    "net_profit": _first_value(
                        income,
                        ("净利润", "归属母公司股东的净利润"),
                    ),
                    "operating_cash_flow": _first_value(
                        cashflow,
                        (
                            "经营性现金流-现金流量净额",
                            "经营活动产生的现金流量净额",
                        ),
                    ),
                }
                if any(
                    _has_value(update.get(field))
                    for field in REQUIRED_CASHFLOW_FIELDS
                ):
                    updates_by_code[code].append(update)
                    result["updated_records"] += 1
            completed_periods += 1
            if progress is not None:
                progress(completed_periods, len(targets), result)

    merged_by_code: dict[str, list[dict[str, Any]]] = {}
    for code, updates in updates_by_code.items():
        merged = merge_financial_records(
            cache.get(f"fin:abstract:{code}"),
            updates,
        )
        merged_by_code[code] = merged
        cache.set(f"fin:abstract:{code}", merged)

    remaining = 0
    for code, period in target_pairs:
        rows = merged_by_code.get(code)
        if rows is None:
            rows = _records(cache.get(f"fin:abstract:{code}"))
        row = next((item for item in rows if _period(item) == period), {})
        if any(
            not _has_value(row.get(field))
            for field in REQUIRED_CASHFLOW_FIELDS
        ):
            remaining += 1

    result["completed_records"] = len(target_pairs) - remaining
    result["remaining_records"] = remaining
    result["source_failures"] = dict(
        sorted(result["source_failures"].items())
    )
    return result


def audit_financial_abstracts(
    cache,
    codes: Iterable[str] | None = None,
) -> dict[str, Any]:
    if codes is None:
        selected_codes = sorted(
            key.rsplit(":", 1)[-1]
            for key in cache.keys("fin:abstract:*")
        )
    else:
        selected_codes = sorted(
            {
                str(code).strip()
                for code in codes
                if str(code).strip()
            }
        )

    missing_codes: list[str] = []
    missing_by_field = {field: 0 for field in REQUIRED_CASHFLOW_FIELDS}
    details: dict[str, list[str]] = {}
    for code in selected_codes:
        fields = latest_missing_required_fields(
            cache.get(f"fin:abstract:{code}")
        )
        if not fields:
            continue
        missing_codes.append(code)
        details[code] = fields
        for field in fields:
            missing_by_field[field] += 1

    return {
        "total": len(selected_codes),
        "complete": len(selected_codes) - len(missing_codes),
        "missing": len(missing_codes),
        "missing_codes": missing_codes,
        "missing_by_field": missing_by_field,
        "details": details,
    }


def audit_financial_history(
    cache,
    codes: Iterable[str] | None = None,
    *,
    as_of_date: str | None = None,
    start_period: str = "",
) -> dict[str, Any]:
    if codes is None:
        selected_codes = sorted(
            key.rsplit(":", 1)[-1]
            for key in cache.keys("fin:abstract:*")
        )
    else:
        selected_codes = sorted(
            {
                str(code).strip()
                for code in codes
                if str(code).strip()
            }
        )

    total_periods = complete_periods = latest_complete_codes = 0
    freshness = {"current": 0, "stale": 0, "unknown": 0}
    stale_codes: list[str] = []
    missing_by_field = {field: 0 for field in REQUIRED_CASHFLOW_FIELDS}
    coverage_starts: list[str] = []
    coverage_ends: list[str] = []

    for code in selected_codes:
        rows = [
            row
            for row in _records(cache.get(f"fin:abstract:{code}"))
            if not start_period or _period(row) >= str(start_period)
        ]
        quality = analyze_financial_history(
            rows,
            as_of_date=as_of_date,
        )
        completeness = quality["completeness"]
        code_freshness = quality["freshness"]
        total_periods += completeness["total_periods"]
        complete_periods += completeness["complete_periods"]
        latest_complete_codes += int(completeness["latest_complete"])
        for field, count in completeness["missing_by_field"].items():
            missing_by_field[field] += count
        status = code_freshness["status"]
        freshness[status] = freshness.get(status, 0) + 1
        if status == "stale":
            stale_codes.append(code)
        start = quality["coverage"]["start_period"]
        end = quality["coverage"]["end_period"]
        if start:
            coverage_starts.append(start)
        if end:
            coverage_ends.append(end)

    return {
        "total_codes": len(selected_codes),
        "total_periods": total_periods,
        "complete_periods": complete_periods,
        "incomplete_periods": total_periods - complete_periods,
        "completeness_ratio": round(
            complete_periods / total_periods,
            6,
        ) if total_periods else 0,
        "latest_complete_codes": latest_complete_codes,
        "missing_by_field": missing_by_field,
        "freshness": freshness,
        "stale_codes": stale_codes,
        "coverage": {
            "start_period": min(coverage_starts, default=""),
            "end_period": max(coverage_ends, default=""),
        },
        "start_period_filter": str(start_period or ""),
    }


def merge_financial_records(
    existing: Any,
    fresh: Any,
) -> list[dict[str, Any]]:
    merged_by_period: dict[str, dict[str, Any]] = {}
    undated: list[dict[str, Any]] = []

    for row in _records(existing):
        period = _period(row)
        if period:
            merged_by_period[period] = row
        else:
            undated.append(row)

    for row in _records(fresh):
        period = _period(row)
        if not period:
            if row not in undated:
                undated.append(row)
            continue
        combined = dict(merged_by_period.get(period, {}))
        for key, value in row.items():
            if _has_value(value):
                combined[key] = value
        merged_by_period[period] = combined

    dated = [
        merged_by_period[period]
        for period in sorted(merged_by_period, reverse=True)
    ]
    return dated + undated


def _fetch_records(
    code: str,
    fetcher: Callable[[str], Any],
) -> tuple[str, list[dict[str, Any]] | None, str]:
    try:
        value = fetcher(code)
        if hasattr(value, "to_dict"):
            if getattr(value, "empty", False):
                return code, None, "source returned empty"
            value = value.to_dict(orient="records")
        rows = _records(value)
        if not rows:
            return code, None, "source returned empty"
        missing = latest_missing_required_fields(rows)
        if missing:
            return code, None, f"source missing fields: {','.join(missing)}"
        return code, rows, ""
    except Exception as exc:
        return code, None, f"{type(exc).__name__}: {str(exc)[:200]}"


def repair_financial_abstracts(
    codes: Iterable[str],
    cache,
    *,
    fetcher: Callable[[str], Any] = fetch_core_financials,
    workers: int = 6,
    progress: Callable[[int, int, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    selected_codes = list(
        dict.fromkeys(
            str(code).strip()
            for code in codes
            if str(code).strip()
        )
    )
    result: dict[str, Any] = {
        "total": len(selected_codes),
        "repaired": 0,
        "failed": 0,
        "repaired_codes": [],
        "failures": {},
    }
    if not selected_codes:
        return result

    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
        futures = {
            pool.submit(_fetch_records, code, fetcher): code
            for code in selected_codes
        }
        for index, future in enumerate(as_completed(futures), 1):
            code, fresh, error = future.result()
            if fresh is None:
                result["failed"] += 1
                result["failures"][code] = error
            else:
                key = f"fin:abstract:{code}"
                merged = merge_financial_records(cache.get(key), fresh)
                if latest_missing_required_fields(merged):
                    result["failed"] += 1
                    result["failures"][code] = "merged result remains incomplete"
                else:
                    cache.set(key, merged)
                    result["repaired"] += 1
                    result["repaired_codes"].append(code)
            if progress is not None:
                progress(index, len(selected_codes), result)

    result["repaired_codes"].sort()
    result["failures"] = dict(sorted(result["failures"].items()))
    return result


def _parse_codes(raw: str) -> list[str]:
    return [
        item.strip()
        for item in str(raw or "").split(",")
        if item.strip()
    ]


def resolve_history_start(
    *,
    as_of_date: str,
    history_years: int,
    explicit_start: str,
) -> str:
    explicit = str(explicit_start or "").replace("-", "")
    if explicit:
        if len(explicit) != 8 or not explicit.isdigit():
            raise ValueError("history start must use YYYYMMDD")
        return explicit
    as_of = str(as_of_date or "").replace("-", "")
    if len(as_of) != 8 or not as_of.isdigit():
        raise ValueError("as-of date must use YYYYMMDD")
    return f"{int(as_of[:4]) - max(1, int(history_years))}0101"


def _write_report(path: str, payload: dict[str, Any]) -> None:
    report_path = os.path.abspath(path)
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit and repair fin:abstract profit and cash-flow fields."
    )
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--codes", default="", help="Comma-separated stock codes.")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--history-only",
        action="store_true",
        help="Backfill missing historical periods using period-batched tables.",
    )
    parser.add_argument("--history-years", type=int, default=10)
    parser.add_argument("--history-start", default="")
    parser.add_argument(
        "--history-periods",
        default="",
        help="Comma-separated YYYYMMDD report periods for targeted retries.",
    )
    parser.add_argument("--source-retries", type=int, default=2)
    parser.add_argument("--retry-delay-seconds", type=float, default=1.5)
    parser.add_argument(
        "--as-of",
        default=datetime.now().strftime("%Y%m%d"),
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Use cached crosschecks only; do not call external sources.",
    )
    parser.add_argument(
        "--report",
        default=os.path.join("logs", "financial_abstract_repair.json"),
    )
    args = parser.parse_args()

    cache = create_cache()
    requested_codes = _parse_codes(args.codes)
    if args.history_only:
        selected_codes = requested_codes or sorted(
            key.rsplit(":", 1)[-1]
            for key in cache.keys("fin:abstract:*")
        )
        if args.limit > 0:
            selected_codes = selected_codes[: args.limit]
        history_start = resolve_history_start(
            as_of_date=args.as_of,
            history_years=args.history_years,
            explicit_start=args.history_start,
        )
        before_history = audit_financial_history(
            cache,
            selected_codes,
            as_of_date=args.as_of,
            start_period=history_start,
        )
        history_payload: dict[str, Any] = {
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "mode": "historical_period_batch",
            "as_of_date": args.as_of,
            "history_start": history_start,
            "required_fields": list(REQUIRED_CASHFLOW_FIELDS),
            "before": before_history,
            "repair": None,
            "after": None,
        }
        print(
            f"History audit: codes={before_history['total_codes']} "
            f"periods={before_history['total_periods']} "
            f"complete={before_history['complete_periods']} "
            f"ratio={before_history['completeness_ratio']:.2%}",
            flush=True,
        )
        history_started = time.time()

        def history_progress(
            index: int,
            total: int,
            current: dict[str, Any],
        ) -> None:
            elapsed = max(time.time() - history_started, 1e-6)
            rate = index / elapsed
            eta = (total - index) / rate if rate else 0
            print(
                f"History [{index}/{total}] "
                f"updates={current['updated_records']} "
                f"rate={rate:.2f} periods/s ETA={eta:.0f}s",
                flush=True,
            )

        history_repair = backfill_historical_periods(
            selected_codes,
            cache,
            start_period=history_start,
            periods=_parse_codes(args.history_periods),
            workers=args.workers,
            source_retries=args.source_retries,
            retry_delay_seconds=args.retry_delay_seconds,
            progress=history_progress,
        )
        history_payload["repair"] = history_repair
        history_payload["after"] = audit_financial_history(
            cache,
            selected_codes,
            as_of_date=args.as_of,
            start_period=history_start,
        )
        history_payload["finished_at"] = datetime.now().isoformat(
            timespec="seconds"
        )
        _write_report(args.report, history_payload)
        print(
            f"History result: completed={history_repair['completed_records']} "
            f"remaining={history_repair['remaining_records']} "
            f"ratio={history_payload['after']['completeness_ratio']:.2%}",
            flush=True,
        )
        print(f"Report: {os.path.abspath(args.report)}", flush=True)
        return 0 if not history_repair["remaining_records"] else 1

    before = audit_financial_abstracts(cache, requested_codes or None)
    repair_codes = list(before["missing_codes"])
    if args.limit > 0:
        repair_codes = repair_codes[: args.limit]

    payload: dict[str, Any] = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "required_fields": list(REQUIRED_CASHFLOW_FIELDS),
        "before": before,
        "crosscheck_backfill": None,
        "repair": None,
        "bulk_backfill": None,
        "after": None,
    }
    print(
        f"Audit: total={before['total']} complete={before['complete']} "
        f"missing={before['missing']}",
        flush=True,
    )

    if not args.audit_only:
        crosscheck_backfill = backfill_from_crosschecks(repair_codes, cache)
        payload["crosscheck_backfill"] = crosscheck_backfill
        after_crosscheck = audit_financial_abstracts(
            cache,
            requested_codes or None,
        )
        print(
            f"Crosscheck: backfilled={crosscheck_backfill['backfilled']} "
            f"failed={crosscheck_backfill['failed']} "
            f"remaining={after_crosscheck['missing']}",
            flush=True,
        )
        repair_codes = list(after_crosscheck["missing_codes"])
        if args.limit > 0:
            repair_codes = repair_codes[: args.limit]

        started = time.time()

        def report_progress(index: int, total: int, current: dict[str, Any]) -> None:
            if index % 50 == 0 or index == total:
                elapsed = max(time.time() - started, 1e-6)
                rate = index / elapsed
                eta = (total - index) / rate if rate else 0
                print(
                    f"Repair [{index}/{total}] repaired={current['repaired']} "
                    f"failed={current['failed']} rate={rate:.2f}/s ETA={eta:.0f}s",
                    flush=True,
                )

        repair = (
            repair_financial_abstracts(
                repair_codes,
                cache,
                workers=args.workers,
                progress=report_progress,
            )
            if not args.local_only
            else {
                "total": len(repair_codes),
                "repaired": 0,
                "failed": len(repair_codes),
                "repaired_codes": [],
                "failures": {
                    code: "external repair skipped by --local-only"
                    for code in repair_codes
                },
            }
        )
        payload["repair"] = repair
        after_external = audit_financial_abstracts(
            cache,
            requested_codes or None,
        )
        bulk_backfill = (
            backfill_from_bulk_periods(
                after_external["missing_codes"],
                cache,
            )
            if not args.local_only and after_external["missing_codes"]
            else {
                "total": len(after_external["missing_codes"]),
                "backfilled": 0,
                "failed": len(after_external["missing_codes"]),
                "backfilled_codes": [],
                "failures": {
                    code: "bulk fallback skipped"
                    for code in after_external["missing_codes"]
                },
            }
        )
        payload["bulk_backfill"] = bulk_backfill
        payload["after"] = audit_financial_abstracts(
            cache,
            requested_codes or None,
        )
        print(
            f"Result: repaired={repair['repaired']} failed={repair['failed']} "
            f"bulk={bulk_backfill['backfilled']} "
            f"remaining={payload['after']['missing']}",
            flush=True,
        )

    payload["finished_at"] = datetime.now().isoformat(timespec="seconds")
    _write_report(args.report, payload)
    print(f"Report: {os.path.abspath(args.report)}", flush=True)
    return 0 if args.audit_only or not payload["after"]["missing"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

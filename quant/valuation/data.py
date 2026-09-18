"""TdxQuant-first normalized data inputs for stock valuation.

This module owns source priority, field provenance, freshness classification,
bounded concurrency and cache policy. Valuation formulas consume its stable
JSON-safe dictionaries and never need to infer units or missing-data meaning.
"""
from __future__ import annotations

import inspect
import io
import math
import numbers
import threading
import time
from contextlib import redirect_stdout
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError, as_completed
from datetime import date, datetime
from typing import Any, Callable, Iterable

from .contracts import derive_growth_rate, normalize_code, safe_number
from .financials import (
    annual_records,
    build_ttm_metrics,
    derive_earnings_growth,
    filter_point_in_time_records,
)


TDX_UNIT_10K = 10_000.0
FUNDAMENTAL_SUCCESS_TTL = 24 * 60 * 60
PARTIAL_TTL = 15 * 60
UNAVAILABLE_TTL = 60
QUOTE_LIVE_TTL = 5
QUOTE_DEGRADED_TTL = 15
PEER_MEMBER_TTL = 30 * 60
PEER_RESULT_TTL = 5
FETCHED_HISTORY_TTL = 30 * 60
MARKET_TTL = 30
DEFAULT_PEER_LIMIT = 24
DEFAULT_MAX_WORKERS = 4
DEFAULT_MAX_PENDING_TASKS = 8
DEFAULT_MAX_PEER_SCAN = 96

_TDX_SCALED_FIELDS = {
    "revenue": ("J_yysy", "10k_cny"),
    "net_profit": ("J_jly", "10k_cny"),
    "operating_cash_flow": ("J_jyxjl", "10k_cny"),
    "total_shares": ("J_zgb", "10k_shares"),
    "total_assets": ("J_zzc", "10k_cny"),
    "long_term_debt": ("J_cqfz", "10k_cny"),
}
_FUNDAMENTAL_FIELDS = (
    "eps",
    "bvps",
    "revenue",
    "net_profit",
    "operating_cash_flow",
    "total_shares",
    "total_assets",
    "long_term_debt",
)


def _date_text(value: Any) -> str:
    raw = str(value or "").strip()
    digits = "".join(char for char in raw if char.isdigit())
    return digits[:14] if len(digits) >= 8 else ""


def _first(raw: dict, names: Iterable[str], default: Any = None) -> Any:
    for name in names:
        value = raw.get(name)
        if value not in (None, ""):
            return value
    return default


def _decode_name(value: Any) -> str:
    if isinstance(value, bytes):
        for encoding in ("utf-8", "gb18030"):
            try:
                return value.decode(encoding).strip()
            except UnicodeDecodeError:
                continue
        return ""
    return str(value or "").strip()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, numbers.Real):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    try:
        if value != value:
            return None
    except Exception:
        pass
    return str(value)


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, numbers.Real):
        return float(value) == 1.0
    text = str(value or "").strip().upper()
    return text in {"1", "TRUE", "YES", "Y", "ST", "*ST"}


def _status_ttl(
    status: str,
    *,
    success: int = FUNDAMENTAL_SUCCESS_TTL,
    partial: int = PARTIAL_TTL,
    unavailable: int = UNAVAILABLE_TTL,
) -> int:
    if status == "success":
        return int(success)
    if status == "partial":
        return int(partial)
    return int(unavailable)


def _scaled_tdx_value(value: Any) -> float | None:
    number = safe_number(value)
    return number * TDX_UNIT_10K if number is not None else None


def normalize_tdx_fundamentals(code: object, raw: dict | None) -> dict:
    """Normalize documented TdxQuant fields with explicit unit metadata."""
    normalized = normalize_code(code)
    if not normalized:
        raise ValueError("invalid stock code")
    payload = raw if isinstance(raw, dict) else {}
    values = {
        "eps": safe_number(payload.get("J_mgsy")),
        "bvps": safe_number(payload.get("J_mgjzc")),
    }
    units = {
        "J_mgsy": {"input": "cny_per_share", "scale": 1.0},
        "J_mgjzc": {"input": "cny_per_share", "scale": 1.0},
    }
    source_fields = {"eps": "J_mgsy", "bvps": "J_mgjzc"}
    for output, (field, input_unit) in _TDX_SCALED_FIELDS.items():
        values[output] = _scaled_tdx_value(payload.get(field))
        units[field] = {"input": input_unit, "scale": TDX_UNIT_10K}
        source_fields[output] = field

    warnings = [
        f"missing or invalid TdxQuant field {source_fields[field]}"
        for field in _FUNDAMENTAL_FIELDS
        if values.get(field) is None
    ]
    report_period = _date_text(
        _first(payload, ("J_bgrq", "ReportDate", "report_date", "end_date"))
    )
    data_date = _date_text(
        _first(
            payload,
            ("UpdateTime", "DataDate", "data_date", "ann_date", "f_ann_date"),
        )
    )
    if not report_period:
        warnings.append("missing TdxQuant financial report period")
    if not data_date:
        warnings.append("missing TdxQuant financial data date")
    field_sources = {
        field: "tdx_quant_stock_info"
        for field in _FUNDAMENTAL_FIELDS
        if values.get(field) is not None
    }
    return {
        "code": normalized,
        "name": _decode_name(payload.get("Name")) or normalized,
        **values,
        "industry_code": str(payload.get("rs_hycode_sim") or "").strip(),
        "industry_name": _decode_name(
            _first(
                payload,
                (
                    "rs_hyname_sim",
                    "IndustryName",
                    "industry_name",
                    "HYName",
                ),
            )
        ),
        "is_st": _parse_bool(payload.get("IsSTGP")),
        "report_period": report_period or None,
        "data_date": data_date or None,
        "units": units,
        "field_sources": field_sources,
        "source": "tdx_quant_stock_info",
        "status": "success" if not warnings else "partial",
        "warnings": warnings,
    }


_ALIASES = {
    "eps": ("eps", "basic_eps", "每股收益"),
    "bvps": ("bvps", "bps", "每股净资产"),
    "revenue": ("revenue", "total_revenue", "营业总收入"),
    "net_profit": ("net_profit", "n_income", "归母净利润"),
    "operating_cash_flow": (
        "operating_cash_flow",
        "n_cashflow_act",
        "经营活动现金流量净额",
    ),
    "total_shares": ("total_shares", "total_capital", "总股本"),
    "total_assets": ("total_assets", "assets", "资产总计"),
    "long_term_debt": ("long_term_debt", "lt_borr", "长期借款"),
}


def _normalize_record(code: str, record: dict, source: str) -> dict:
    payload = _json_safe(record if isinstance(record, dict) else {})
    values = {
        field: safe_number(_first(payload, aliases))
        for field, aliases in _ALIASES.items()
    }
    name = _decode_name(_first(payload, ("name", "Name", "股票简称"))) or code
    return {
        "code": code,
        "name": name,
        **values,
        "industry_code": str(
            _first(payload, ("industry_code", "rs_hycode_sim"), "")
        ).strip(),
        "industry_name": _decode_name(
            _first(payload, ("industry_name", "rs_hyname_sim"))
        ),
        "is_st": _parse_bool(payload.get("is_st"))
        or name.upper().startswith(("ST", "*ST")),
        "report_period": _date_text(
            _first(payload, ("report_date", "end_date", "report_period"))
        )
        or None,
        "data_date": _date_text(
            _first(
                payload,
                ("ann_date", "f_ann_date", "data_date", "update_date"),
            )
        )
        or None,
        "source": source,
    }


def _latest_record(records: list[dict]) -> dict:
    return max(
        (row for row in records if isinstance(row, dict)),
        key=lambda row: _date_text(
            _first(row, ("report_date", "end_date", "report_period"))
        ),
        default={},
    )


def _load_baostock_industries(cache: Any) -> int:
    import baostock as bs

    from scripts.download_industry import _industry_category

    captured = io.StringIO()
    with redirect_stdout(captured):
        login = bs.login()
        if str(login.error_code) != "0":
            raise RuntimeError(f"baostock login failed: {login.error_msg}")
        written = 0
        try:
            result = bs.query_stock_industry()
            if str(result.error_code) != "0":
                raise RuntimeError(
                    f"baostock industry query failed: {result.error_msg}"
                )
            while result.next():
                row = result.get_row_data()
                if len(row) < 4 or "." not in str(row[1]):
                    continue
                code = str(row[1]).split(".", 1)[1]
                industry = str(row[3] or "").strip()
                if not normalize_code(code) or not industry:
                    continue
                cache.set(f"stock:industry:{code}", _industry_category(industry))
                cache.set(f"stock:industry_raw:{code}", industry)
                written += 1
        finally:
            bs.logout()
    return written


class ValuationDataProvider:
    """Build source-labelled valuation inputs with bounded external work."""

    def __init__(
        self,
        *,
        cache: Any,
        tdx_source: Any = None,
        quote_fallback: Callable[[list[str]], Any] | None = None,
        financial_fetcher: Callable[..., dict] | None = None,
        industry_loader: Callable[[Any], int] | None = None,
        max_workers: int = DEFAULT_MAX_WORKERS,
        max_pending_tasks: int = DEFAULT_MAX_PENDING_TASKS,
        max_peer_scan: int = DEFAULT_MAX_PEER_SCAN,
        industry_timeout: float = 8.0,
        peer_timeout: float = 15.0,
        source_timeout: float = 15.0,
        now_fn: Callable[[], datetime] | None = None,
    ):
        if cache is None:
            raise TypeError("cache is required")
        if tdx_source is None:
            from quant.data import tdx_quant_source

            tdx_source = tdx_quant_source
        self.cache = cache
        self.tdx_source = tdx_source
        self.quote_fallback = quote_fallback
        self.financial_fetcher = financial_fetcher
        self.industry_loader = industry_loader or _load_baostock_industries
        self.max_workers = max(1, min(int(max_workers), 16))
        self.max_pending_tasks = max(0, int(max_pending_tasks))
        self.max_peer_scan = max(1, int(max_peer_scan))
        self.industry_timeout = max(0.001, float(industry_timeout))
        self.peer_timeout = max(0.01, float(peer_timeout))
        self.source_timeout = max(0.01, float(source_timeout))
        self._now_fn = now_fn or datetime.now

        self._executor = ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="valuation-data",
        )
        self._task_slots = threading.BoundedSemaphore(
            self.max_workers + self.max_pending_tasks
        )
        self._metrics_lock = threading.Lock()
        self._outstanding = 0
        self._rejected = 0
        self._closed = False
        self._industry_refresh_lock = threading.Lock()
        self._industry_refresh_attempted = False
        self._fundamental_locks_guard = threading.Lock()
        self._fundamental_locks: dict[str, threading.Lock] = {}
        self._tdx_info_locks_guard = threading.Lock()
        self._tdx_info_locks: dict[str, threading.Lock] = {}

    @staticmethod
    def _code(value: object) -> str:
        normalized = normalize_code(value)
        if not normalized:
            raise ValueError("invalid stock code")
        return normalized

    def _fundamental_lock(self, code: str) -> threading.Lock:
        with self._fundamental_locks_guard:
            return self._fundamental_locks.setdefault(code, threading.Lock())

    def _tdx_info_lock(self, code: str) -> threading.Lock:
        with self._tdx_info_locks_guard:
            return self._tdx_info_locks.setdefault(code, threading.Lock())

    def _submit_bounded(self, fn: Callable, *args, **kwargs) -> Future | None:
        if self._closed or not self._task_slots.acquire(blocking=False):
            with self._metrics_lock:
                self._rejected += 1
            return None
        with self._metrics_lock:
            self._outstanding += 1
        try:
            future = self._executor.submit(fn, *args, **kwargs)
        except Exception:
            self._task_slots.release()
            with self._metrics_lock:
                self._outstanding -= 1
            raise

        def release(_future: Future) -> None:
            self._task_slots.release()
            with self._metrics_lock:
                self._outstanding -= 1

        future.add_done_callback(release)
        return future

    def executor_metrics(self) -> dict:
        with self._metrics_lock:
            return {
                "max_workers": self.max_workers,
                "max_pending_tasks": self.max_pending_tasks,
                "capacity": self.max_workers + self.max_pending_tasks,
                "outstanding": self._outstanding,
                "rejected": self._rejected,
            }

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _call_source(self, method_name: str, *args, **kwargs):
        method = getattr(self.tdx_source, method_name)
        try:
            signature = inspect.signature(method)
            accepts_kwargs = any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in signature.parameters.values()
            )
            if "timeout" in signature.parameters or accepts_kwargs:
                kwargs.setdefault("timeout", self.source_timeout)
        except (TypeError, ValueError):
            pass
        return method(*args, **kwargs)

    def _daily_summary(self, code: str) -> dict | None:
        cached = self.cache.get(f"valuation:daily_summary:{code}")
        if isinstance(cached, dict):
            return _json_safe(cached)
        conn = getattr(self.cache, "_conn", None)
        lock = getattr(self.cache, "_lock", None)
        if conn is None or lock is None:
            return None
        try:
            with lock:
                row = conn.execute(
                    """
                    SELECT code, name, latest_date, close, prev_close,
                           change_pct, volume, amount, updated_at
                    FROM stock_daily_summary WHERE code = ? LIMIT 1
                    """,
                    (code,),
                ).fetchone()
        except Exception:
            return None
        if not row:
            return None
        return {
            "code": str(row[0]),
            "name": str(row[1] or row[0]),
            "latest_date": str(row[2] or ""),
            "close": safe_number(row[3]),
            "prev_close": safe_number(row[4]),
            "change_pct": safe_number(row[5]),
            "volume": safe_number(row[6]),
            "amount": safe_number(row[7]),
            "updated_at": str(row[8] or ""),
        }

    def _market_summaries(self) -> list[dict]:
        cached = self.cache.get("valuation:market_summaries")
        if isinstance(cached, list):
            return [_json_safe(row) for row in cached if isinstance(row, dict)]
        conn = getattr(self.cache, "_conn", None)
        lock = getattr(self.cache, "_lock", None)
        if conn is None or lock is None:
            return []
        try:
            with lock:
                latest = conn.execute(
                    "SELECT MAX(latest_date) FROM stock_daily_summary"
                ).fetchone()
                latest_date = str(latest[0] or "") if latest else ""
                rows = conn.execute(
                    """
                    SELECT code, name, latest_date, close, prev_close,
                           change_pct, volume, amount
                    FROM stock_daily_summary WHERE latest_date = ?
                    """,
                    (latest_date,),
                ).fetchall()
        except Exception:
            return []
        return [
            {
                "code": str(row[0]),
                "name": str(row[1] or row[0]),
                "latest_date": str(row[2] or ""),
                "close": safe_number(row[3]),
                "prev_close": safe_number(row[4]),
                "change_pct": safe_number(row[5]),
                "volume": safe_number(row[6]),
                "amount": safe_number(row[7]),
            }
            for row in rows
        ]

    def _fetch_financial_records(self, code: str) -> dict:
        key = f"valuation:financial_fetch:v2:{code}"
        cached = self.cache.get(key)
        if isinstance(cached, dict):
            return _json_safe(cached)
        warnings: list[str] = []
        records: list[dict] = []
        try:
            fetcher = self.financial_fetcher
            if fetcher is None:
                from quant.data.financial_reconciler import (
                    fetch_financial_crosscheck,
                )

                fetcher = fetch_financial_crosscheck
            fetched = fetcher(code, include_tushare=False)
            if isinstance(fetched, dict):
                records = [
                    _json_safe(row)
                    for row in (fetched.get("akshare_records") or [])
                    if isinstance(row, dict)
                ]
                warnings.extend(str(item) for item in fetched.get("warnings") or [])
        except Exception as exc:
            warnings.append(
                f"selected-stock financial fallback failed: {str(exc)[:160]}"
            )
        result = {
            "records": records,
            "status": "success" if records else "unavailable",
            "source": "akshare_selected_stock" if records else "unavailable",
            "warnings": warnings,
        }
        self.cache.set(
            key,
            result,
            ttl=_status_ttl(
                result["status"],
                success=FETCHED_HISTORY_TTL,
                partial=5 * 60,
            ),
        )
        return result

    def _get_tdx_stock_info(self, code: str) -> dict:
        key = f"valuation:tdx_stock_info:{code}"
        cached = self.cache.get(key)
        if isinstance(cached, dict):
            return _json_safe(cached)
        with self._tdx_info_lock(code):
            cached = self.cache.get(key)
            if isinstance(cached, dict):
                return _json_safe(cached)
            warnings: list[str] = []
            raw: dict = {}
            try:
                fetched = self._call_source(
                    "fetch_stock_info", code, field_list=[]
                )
                if isinstance(fetched, dict):
                    raw = _json_safe(fetched)
                if not raw:
                    warnings.append("TdxQuant stock_info returned empty")
            except Exception as exc:
                warnings.append(
                    f"TdxQuant stock_info failed: {str(exc)[:160]}"
                )
            result = {
                "raw": raw,
                "status": "success" if raw else "unavailable",
                "warnings": warnings,
            }
            self.cache.set(
                key,
                result,
                ttl=_status_ttl(
                    result["status"],
                    success=PARTIAL_TTL,
                    partial=5 * 60,
                ),
            )
            return result

    def get_fundamentals(
        self, code: object, *, allow_external: bool = True
    ) -> dict:
        normalized = self._code(code)
        full_cache_key = f"valuation:fundamental:{normalized}"
        cache_key = (
            full_cache_key
            if allow_external
            else f"valuation:peer_fundamental:{normalized}"
        )
        if not allow_external:
            complete = self.cache.get(full_cache_key)
            if isinstance(complete, dict):
                return _json_safe(complete)
        cached = self.cache.get(cache_key)
        if isinstance(cached, dict):
            return _json_safe(cached)

        lock_key = normalized if allow_external else f"{normalized}:peer"
        with self._fundamental_lock(lock_key):
            if not allow_external:
                complete = self.cache.get(full_cache_key)
                if isinstance(complete, dict):
                    return _json_safe(complete)
            cached = self.cache.get(cache_key)
            if isinstance(cached, dict):
                return _json_safe(cached)

            warnings: list[str] = []
            candidates: list[tuple[str, dict]] = []
            tdx_info = self._get_tdx_stock_info(normalized)
            raw = tdx_info.get("raw")
            if isinstance(raw, dict) and raw:
                candidates.append(
                    (
                        "tdx_quant_stock_info",
                        normalize_tdx_fundamentals(normalized, raw),
                    )
                )
            warnings.extend(tdx_info.get("warnings") or [])

            cached_records = self.cache.get(f"fin:abstract:{normalized}")
            cached_records = (
                cached_records if isinstance(cached_records, list) else []
            )
            if cached_records:
                candidates.append(
                    (
                        "fin_abstract_cache",
                        _normalize_record(
                            normalized,
                            _latest_record(cached_records),
                            "fin_abstract_cache",
                        ),
                    )
                )

            current_values = {
                field: next(
                    (
                        candidate.get(field)
                        for _source, candidate in candidates
                        if candidate.get(field) is not None
                    ),
                    None,
                )
                for field in _FUNDAMENTAL_FIELDS
            }
            if allow_external and any(
                value is None for value in current_values.values()
            ):
                external = self._fetch_financial_records(normalized)
                external_records = external.get("records") or []
                if external_records:
                    candidates.append(
                        (
                            "akshare_selected_stock",
                            _normalize_record(
                                normalized,
                                _latest_record(external_records),
                                "akshare_selected_stock",
                            ),
                        )
                    )
                warnings.extend(external.get("warnings") or [])

            field_sources: dict[str, str] = {}
            values: dict[str, float | None] = {}
            for field in _FUNDAMENTAL_FIELDS:
                values[field] = None
                for source_name, candidate in candidates:
                    value = safe_number(candidate.get(field))
                    if value is not None:
                        values[field] = value
                        field_sources[field] = source_name
                        if source_name != "tdx_quant_stock_info":
                            warnings.append(
                                f"filled {field} from {source_name}"
                            )
                        break

            primary = candidates[0][1] if candidates else {}
            name = next(
                (
                    str(candidate.get("name"))
                    for _source, candidate in candidates
                    if candidate.get("name")
                    and str(candidate.get("name")) != normalized
                ),
                str(self.cache.get(f"stock:name:{normalized}") or normalized),
            )
            industry_code = next(
                (
                    str(candidate.get("industry_code"))
                    for _source, candidate in candidates
                    if candidate.get("industry_code")
                ),
                "",
            )
            industry_name = next(
                (
                    str(candidate.get("industry_name"))
                    for _source, candidate in candidates
                    if candidate.get("industry_name")
                ),
                "",
            )
            report_period = max(
                (
                    _date_text(candidate.get("report_period"))
                    for _source, candidate in candidates
                ),
                default="",
            )
            data_date = max(
                (
                    _date_text(candidate.get("data_date"))
                    for _source, candidate in candidates
                ),
                default="",
            )
            is_st = any(
                bool(candidate.get("is_st")) for _source, candidate in candidates
            ) or name.upper().startswith(("ST", "*ST"))
            present = sum(value is not None for value in values.values())
            if present == 0:
                status = "unavailable"
            elif present == len(_FUNDAMENTAL_FIELDS) and not any(
                source != "tdx_quant_stock_info"
                for source in field_sources.values()
            ):
                status = "success"
            else:
                status = "partial"
            missing = [
                field for field, value in values.items() if value is None
            ]
            warnings.extend(
                f"fundamental field unavailable: {field}" for field in missing
            )
            sources = list(dict.fromkeys(field_sources.values()))
            result = {
                "code": normalized,
                "name": name,
                **values,
                "industry_code": industry_code,
                "industry_name": industry_name,
                "is_st": is_st,
                "report_period": report_period or None,
                "data_date": data_date or None,
                "units": primary.get("units") or {},
                "field_sources": field_sources,
                "source": "+".join(sources) if sources else "unavailable",
                "status": status,
                "warnings": list(dict.fromkeys(warnings)),
            }
            result = _json_safe(result)
            self.cache.set(cache_key, result, ttl=_status_ttl(status))
            return result

    def _external_quote_fallback(self, code: str) -> dict | None:
        fetcher = self.quote_fallback
        if fetcher is None:
            try:
                from quant.data.tencent_source import fetch_quotes

                fetcher = fetch_quotes
            except Exception:
                return None
        try:
            payload = fetcher([code])
        except Exception:
            return None
        row = payload.get(code) if isinstance(payload, dict) else None
        return row if isinstance(row, dict) else None

    def _snapshot_freshness(self, snapshot: dict) -> tuple[str, str | None]:
        timestamp = _date_text(
            _first(snapshot, ("timestamp", "as_of", "data_date"))
        )
        as_of = timestamp or None
        price = safe_number(snapshot.get("price"))
        prev_close = safe_number(snapshot.get("prev_close"))
        volume = safe_number(snapshot.get("volume")) or 0.0
        amount = safe_number(snapshot.get("amount")) or 0.0
        raw = snapshot.get("raw") if isinstance(snapshot.get("raw"), dict) else {}
        raw_now = safe_number(raw.get("Now"))
        equals_previous = (
            price is not None
            and prev_close is not None
            and abs(price - prev_close) < 1e-9
        )
        if raw_now == 0 and equals_previous and volume <= 0 and amount <= 0:
            return "preopen", as_of
        today = self._now_fn().strftime("%Y%m%d")
        if timestamp and timestamp[:8] < today:
            return "stale", as_of
        if timestamp and equals_previous and volume <= 0 and amount <= 0:
            return "suspended", as_of
        if not timestamp:
            if equals_previous and volume <= 0 and amount <= 0:
                return "preopen", None
            now = self._now_fn()
            intraday = (
                now.weekday() < 5
                and (
                    (now.hour == 9 and now.minute >= 15)
                    or now.hour == 10
                    or (now.hour == 11 and now.minute <= 30)
                    or now.hour in (13, 14)
                    or (now.hour == 15 and now.minute <= 10)
                )
            )
            if intraday and (volume > 0 or amount > 0):
                return "live", now.strftime("%Y%m%d%H%M%S")
            return "stale", None
        if volume > 0 or amount > 0:
            return "live", as_of
        if equals_previous:
            return "previous_close", as_of
        return "stale", as_of

    def get_quote(self, code: object) -> dict:
        normalized = self._code(code)
        cache_key = f"valuation:quote:{normalized}"
        cached = self.cache.get(cache_key)
        if isinstance(cached, dict):
            return _json_safe(cached)

        warnings: list[str] = []
        try:
            snapshot = self._call_source("fetch_snapshot", normalized)
            snapshot = snapshot if isinstance(snapshot, dict) else {}
            price = safe_number(snapshot.get("price"))
            if price is not None and price > 0:
                freshness, as_of = self._snapshot_freshness(snapshot)
                status = "success" if freshness == "live" else "partial"
                if freshness != "live":
                    warnings.append(
                        f"TdxQuant snapshot classified as {freshness}"
                    )
                result = {
                    "code": normalized,
                    "name": str(
                        self.cache.get(f"stock:name:{normalized}") or normalized
                    ),
                    "price": price,
                    "open": safe_number(snapshot.get("open")),
                    "high": safe_number(snapshot.get("high")),
                    "low": safe_number(snapshot.get("low")),
                    "prev_close": safe_number(snapshot.get("prev_close")),
                    "change_pct": safe_number(snapshot.get("chg_pct")),
                    "volume": safe_number(snapshot.get("volume")),
                    "amount": safe_number(snapshot.get("amount")),
                    "source": str(snapshot.get("source") or "tdx_quant"),
                    "as_of": as_of,
                    "freshness": freshness,
                    "status": status,
                    "warnings": warnings,
                }
                self.cache.set(
                    cache_key,
                    result,
                    ttl=(
                        QUOTE_LIVE_TTL
                        if freshness == "live"
                        else QUOTE_DEGRADED_TTL
                    ),
                )
                return result
            warnings.append("TdxQuant snapshot returned no valid price")
        except Exception as exc:
            warnings.append(f"TdxQuant snapshot failed: {str(exc)[:160]}")

        summary = self._daily_summary(normalized)
        summary_price = safe_number((summary or {}).get("close"))
        if summary and summary_price is not None and summary_price > 0:
            result = {
                "code": normalized,
                "name": str(summary.get("name") or normalized),
                "price": summary_price,
                "open": None,
                "high": None,
                "low": None,
                "prev_close": safe_number(summary.get("prev_close")),
                "change_pct": safe_number(summary.get("change_pct")),
                "volume": safe_number(summary.get("volume")),
                "amount": safe_number(summary.get("amount")),
                "source": "stock_daily_summary",
                "as_of": _date_text(summary.get("latest_date")) or None,
                "freshness": "previous_close",
                "status": "partial",
                "warnings": warnings
                + ["using latest persisted daily summary instead of live quote"],
            }
            self.cache.set(cache_key, result, ttl=QUOTE_DEGRADED_TTL)
            return result

        fallback = self._external_quote_fallback(normalized)
        fallback_price = safe_number((fallback or {}).get("price"))
        if fallback and fallback_price is not None and fallback_price > 0:
            timestamp = _date_text(
                _first(fallback, ("timestamp", "date_time", "as_of"))
            )
            freshness = (
                "live"
                if timestamp
                and timestamp[:8] >= self._now_fn().strftime("%Y%m%d")
                else "stale"
            )
            result = {
                "code": normalized,
                "name": str(fallback.get("name") or normalized),
                "price": fallback_price,
                "open": safe_number(fallback.get("open")),
                "high": safe_number(fallback.get("high")),
                "low": safe_number(fallback.get("low")),
                "prev_close": safe_number(fallback.get("prev_close")),
                "change_pct": safe_number(
                    _first(fallback, ("chg_pct", "change_pct"))
                ),
                "volume": safe_number(fallback.get("volume")),
                "amount": safe_number(fallback.get("amount")),
                "source": str(fallback.get("source") or "tencent_fallback"),
                "as_of": timestamp or None,
                "freshness": freshness,
                "status": "partial",
                "warnings": warnings + ["using realtime fallback quote"],
            }
            self.cache.set(cache_key, result, ttl=QUOTE_DEGRADED_TTL)
            return result

        result = {
            "code": normalized,
            "name": str(self.cache.get(f"stock:name:{normalized}") or normalized),
            "price": None,
            "open": None,
            "high": None,
            "low": None,
            "prev_close": None,
            "change_pct": None,
            "volume": None,
            "amount": None,
            "source": "unavailable",
            "as_of": None,
            "freshness": "missing",
            "status": "unavailable",
            "warnings": warnings + ["no valid quote source available"],
        }
        self.cache.set(cache_key, result, ttl=UNAVAILABLE_TTL)
        return result

    def get_financial_history(self, code: object) -> dict:
        normalized = self._code(code)
        key = f"valuation:financial_history:{normalized}"
        cached = self.cache.get(key)
        if isinstance(cached, dict):
            cached_records = cached.get("records")
            cached_records = (
                cached_records if isinstance(cached_records, list) else []
            )
            enrichment_fields = {
                "revenue",
                "net_profit",
                "operating_cash_flow",
                "enterprise_fcf_per_share",
                "shareholder_fcf_per_share",
            }
            cache_is_current = (
                cached.get("date_basis") is not None
                and cached.get("retrieved_at") is not None
                and cached.get("valuation_as_of") is not None
                and cached.get("point_in_time_quality") is not None
                and isinstance(cached.get("ttm"), dict)
                and any(
                    any(row.get(field) is not None for field in enrichment_fields)
                    for row in cached_records
                    if isinstance(row, dict)
                )
            )
            if cache_is_current or self.financial_fetcher is None:
                return _json_safe(cached)
        raw = self.cache.get(f"fin:abstract:{normalized}")
        records = raw if isinstance(raw, list) else []
        source = "fin_abstract_cache"
        warnings: list[str] = []
        enrichment_fields = {
            "revenue",
            "net_profit",
            "operating_cash_flow",
            "enterprise_fcf_per_share",
            "shareholder_fcf_per_share",
        }
        lacks_enrichment = not any(
            any(row.get(field) is not None for field in enrichment_fields)
            for row in records
            if isinstance(row, dict)
        )
        needs_enrichment = not records or (
            self.financial_fetcher is not None and lacks_enrichment
        )
        if needs_enrichment:
            external = self._fetch_financial_records(normalized)
            external_records = external.get("records") or []
            if external_records:
                merged: dict[str, dict] = {}
                for row in records:
                    if not isinstance(row, dict):
                        continue
                    period = _date_text(
                        _first(row, ("report_date", "end_date", "report_period"))
                    )
                    if period:
                        merged[period] = dict(row)
                for row in external_records:
                    if not isinstance(row, dict):
                        continue
                    period = _date_text(
                        _first(row, ("report_date", "end_date", "report_period"))
                    )
                    if period:
                        merged[period] = {**merged.get(period, {}), **row}
                records = list(merged.values())
                source = (
                    "fin_abstract_cache+akshare_selected_stock"
                    if raw
                    else external.get("source") or "akshare_selected_stock"
                )
                self.cache.set(f"fin:abstract:{normalized}", records)
            warnings.extend(external.get("warnings") or [])
        clean_all = [_json_safe(row) for row in records if isinstance(row, dict)]
        clean_all.sort(
            key=lambda row: _date_text(
                _first(row, ("report_date", "end_date", "report_period"))
            )
        )
        valuation_as_of = self._now_fn().strftime("%Y%m%d%H%M%S")
        point_in_time = filter_point_in_time_records(
            clean_all,
            valuation_as_of,
        )
        clean = point_in_time["records"]
        warnings.extend(
            warning
            for warning in point_in_time["warnings"]
            if point_in_time["quality"] != "report_period_only"
        )
        report_period = max(
            (
                _date_text(
                    _first(row, ("report_date", "end_date", "report_period"))
                )
                for row in clean
            ),
            default="",
        )
        data_date = max(
            (
                _date_text(
                    _first(
                        row,
                        ("ann_date", "f_ann_date", "data_date", "update_date"),
                    )
                )
                for row in clean
            ),
            default="",
        )
        if not clean:
            warnings.append("financial history unavailable")
        if clean and not report_period:
            warnings.append("financial history lacks report period")
        status = (
            "unavailable"
            if not clean
            else ("partial" if warnings else "success")
        )
        retrieved_at = valuation_as_of
        result = {
            "code": normalized,
            "records": clean,
            "annual_records": annual_records(clean),
            "ttm": build_ttm_metrics(clean),
            "sample_length": len(clean),
            "report_period": report_period or None,
            "data_date": data_date or None,
            "date_basis": "announcement_date" if data_date else "report_period",
            "valuation_as_of": valuation_as_of,
            "financial_as_of": point_in_time["financial_as_of"],
            "point_in_time_quality": point_in_time["quality"],
            "point_in_time_quality_score": point_in_time["quality_score"],
            "retrieved_at": retrieved_at,
            "source": source if clean else "unavailable",
            "status": status,
            "warnings": warnings,
        }
        self.cache.set(
            key,
            result,
            ttl=_status_ttl(
                status,
                success=FETCHED_HISTORY_TTL,
                partial=5 * 60,
            ),
        )
        return result

    def _refresh_industry_once(self) -> tuple[bool, str]:
        with self._industry_refresh_lock:
            if self._industry_refresh_attempted:
                return False, "industry refresh already attempted"
            self._industry_refresh_attempted = True
        future = self._submit_bounded(self.industry_loader, self.cache)
        if future is None:
            return False, "industry refresh rejected by bounded executor"
        try:
            future.result(timeout=self.industry_timeout)
            return True, ""
        except TimeoutError:
            future.cancel()
            return False, "Baostock industry refresh timeout"
        except Exception as exc:
            return False, f"Baostock industry refresh failed: {str(exc)[:160]}"

    def get_industry(self, code: object) -> dict:
        normalized = self._code(code)
        fundamentals = self.cache.get(f"valuation:fundamental:{normalized}")
        if not isinstance(fundamentals, dict):
            tdx_info = self._get_tdx_stock_info(normalized)
            raw = tdx_info.get("raw")
            fundamentals = (
                normalize_tdx_fundamentals(normalized, raw)
                if isinstance(raw, dict) and raw
                else {}
            )
        industry_code = str(fundamentals.get("industry_code") or "").strip()
        industry_name = str(fundamentals.get("industry_name") or "").strip()
        if industry_code or industry_name:
            peer_filter_label = None
            warnings: list[str] = []
            if industry_code and not industry_name:
                key = f"stock:industry:{normalized}"
                cached_label = self.cache.get(key)
                if not cached_label:
                    _refreshed, warning = self._refresh_industry_once()
                    cached_label = self.cache.get(key)
                    if warning:
                        warnings.append(warning)
                if cached_label:
                    peer_filter_label = str(cached_label)
            return {
                "code": normalized,
                "industry": industry_name or peer_filter_label or industry_code,
                "industry_code": industry_code or None,
                "industry_name": industry_name or None,
                "peer_filter_label": peer_filter_label,
                "source": (
                    "tdx_quant_stock_info+baostock_peer_filter"
                    if peer_filter_label
                    else "tdx_quant_stock_info"
                ),
                "status": "partial" if warnings else "success",
                "warnings": warnings,
            }

        key = f"stock:industry:{normalized}"
        industry = self.cache.get(key)
        if industry:
            return {
                "code": normalized,
                "industry": str(industry),
                "industry_code": None,
                "industry_name": str(industry),
                "source": "baostock_cache",
                "status": "partial",
                "warnings": ["TdxQuant industry unavailable; using Baostock"],
            }
        refreshed, warning = self._refresh_industry_once()
        industry = self.cache.get(key)
        if industry:
            return {
                "code": normalized,
                "industry": str(industry),
                "industry_code": None,
                "industry_name": str(industry),
                "source": "baostock_refresh" if refreshed else "baostock_cache",
                "status": "partial",
                "warnings": [
                    item
                    for item in (
                        "TdxQuant industry unavailable; using Baostock",
                        warning,
                    )
                    if item
                ],
            }
        return {
            "code": normalized,
            "industry": None,
            "industry_code": None,
            "industry_name": None,
            "source": "unavailable",
            "status": "partial",
            "warnings": [warning or "industry unavailable"],
        }

    def get_daily_history(
        self, code: object, *, count: int = 900, min_samples: int = 720
    ) -> dict:
        normalized = self._code(code)
        key = f"valuation:kline:{normalized}:{max(1, int(count))}"
        cached = self.cache.get(key)
        if isinstance(cached, dict):
            return _json_safe(cached)
        raw = self.cache.get(f"kline:{normalized}:d")
        bars = raw if isinstance(raw, list) else []
        source = "kline_cache"
        warnings: list[str] = []
        requested = max(1, int(count))
        if len(bars) < requested:
            try:
                fetched = self._call_source(
                    "fetch_klines",
                    normalized,
                    count=requested,
                    period="1d",
                )
            except Exception as exc:
                allow_method = getattr(
                    self.tdx_source, "fetch_klines_allow_price_jumps", None
                )
                if allow_method is None:
                    warnings.append(
                        f"TdxQuant daily history failed: {str(exc)[:160]}"
                    )
                    fetched = []
                else:
                    try:
                        fetched = self._call_source(
                            "fetch_klines_allow_price_jumps",
                            normalized,
                            count=requested,
                            period="1d",
                        )
                        warnings.append(
                            "TdxQuant corporate-action price jump accepted with factor"
                        )
                    except Exception as fallback_exc:
                        warnings.append(
                            "TdxQuant daily history failed: "
                            f"{str(fallback_exc)[:160]}"
                        )
                        fetched = []
            if fetched:
                merged = {
                    _date_text(row.get("date")): dict(row)
                    for row in bars
                    if isinstance(row, dict) and _date_text(row.get("date"))
                }
                for row in fetched:
                    if isinstance(row, dict) and _date_text(row.get("date")):
                        merged[_date_text(row.get("date"))] = dict(row)
                bars = sorted(
                    merged.values(),
                    key=lambda row: _date_text(row.get("date")),
                )
                source = (
                    "kline_cache+tdx_quant" if raw else "tdx_quant"
                )
                if len(bars) > len(raw if isinstance(raw, list) else []):
                    self.cache.set(f"kline:{normalized}:d", bars)
        clean = [_json_safe(row) for row in bars if isinstance(row, dict)]
        for row in clean:
            close = safe_number(row.get("close"))
            factor = safe_number(row.get("factor"))
            if close is not None and factor is not None and factor > 0:
                row["adjusted_close"] = close * factor
        clean.sort(key=lambda row: _date_text(row.get("date")))
        actual = len(clean)
        required = max(1, int(min_samples))
        complete = actual >= required
        if not clean:
            warnings.append("daily history unavailable")
        elif not complete:
            warnings.append(f"daily history coverage {actual}/{required}")
        status = (
            "unavailable"
            if not clean
            else ("success" if complete else "partial")
        )
        result = {
            "code": normalized,
            "bars": clean,
            "sample_length": actual,
            "start_date": _date_text(clean[0].get("date")) if clean else None,
            "latest_date": _date_text(clean[-1].get("date")) if clean else None,
            "coverage": {
                "required_samples": required,
                "actual_samples": actual,
                "complete": complete,
            },
            "source": source if clean else "unavailable",
            "status": status,
            "warnings": warnings,
        }
        self.cache.set(
            key,
            result,
            ttl=_status_ttl(
                status,
                success=FETCHED_HISTORY_TTL,
                partial=5 * 60,
            ),
        )
        return result

    @staticmethod
    def _has_valuation_basis(fundamentals: dict) -> bool:
        shares = safe_number(fundamentals.get("total_shares"))
        basis = (
            safe_number(fundamentals.get("eps")),
            safe_number(fundamentals.get("bvps")),
            safe_number(fundamentals.get("revenue")),
        )
        return bool(
            shares
            and shares > 0
            and any(value is not None and value > 0 for value in basis)
        )

    @staticmethod
    def _matches_industry(
        fundamentals: dict, target_code: str, target_label: str, cached_label: str
    ) -> bool:
        candidate_code = str(fundamentals.get("industry_code") or "").strip()
        if target_code:
            return bool(candidate_code and candidate_code == target_code)
        return bool(target_label and cached_label == target_label)

    def _candidate_codes(self, target: str) -> list[str]:
        seen: set[str] = set()
        output: list[str] = []
        raw_universe = self.cache.get("stock:universe") or []
        for raw in raw_universe:
            code = normalize_code(raw)
            if code and code != target and code not in seen:
                seen.add(code)
                output.append(code)
        for key in self.cache.keys("stock:industry:*"):
            code = normalize_code(str(key).rsplit(":", 1)[-1])
            if code and code != target and code not in seen:
                seen.add(code)
                output.append(code)
        return output

    def _candidate_rank(self, code: str) -> tuple[int, float, str]:
        availability = 0
        if isinstance(
            self.cache.get(f"valuation:fundamental:{code}"), dict
        ):
            availability += 4
        if self.cache.get(f"fin:abstract:{code}"):
            availability += 2
        if self.cache.get(f"kline:{code}:d"):
            availability += 1
        summary = self._daily_summary(code) or {}
        if safe_number(summary.get("close")):
            availability += 1
        amount = safe_number(summary.get("amount")) or 0.0
        return (-availability, -amount, code)

    def _build_peer_members(
        self,
        target: str,
        industry: dict,
        limit: int,
    ) -> dict:
        target_code = str(industry.get("industry_code") or "")
        target_label = str(industry.get("industry") or "")
        candidates = self._candidate_codes(target)
        peer_filter_label = str(industry.get("peer_filter_label") or "")
        if peer_filter_label:
            candidates = [
                code
                for code in candidates
                if str(self.cache.get(f"stock:industry:{code}") or "")
                == peer_filter_label
            ]
        elif not target_code:
            candidates = [
                code
                for code in candidates
                if str(self.cache.get(f"stock:industry:{code}") or "")
                == target_label
            ]
        candidates.sort(key=self._candidate_rank)
        candidates = candidates[: self.max_peer_scan]
        candidate_order = {
            code: index for index, code in enumerate(candidates)
        }
        members: list[str] = []
        warnings: list[str] = []
        submitted_count = 0
        batch_size = max(1, min(self.max_workers * 2, self.max_peer_scan))

        for offset in range(0, len(candidates), batch_size):
            if len(members) >= limit:
                break
            batch = candidates[offset : offset + batch_size]
            futures: dict[Future, str] = {}
            for candidate in batch:
                future = self._submit_bounded(
                    self.get_fundamentals,
                    candidate,
                    allow_external=False,
                )
                if future is None:
                    warnings.append(
                        "peer fundamental task rejected by bounded executor"
                    )
                    continue
                futures[future] = candidate
                submitted_count += 1
            if not futures:
                continue
            try:
                for future in as_completed(
                    futures, timeout=self.peer_timeout
                ):
                    candidate = futures[future]
                    try:
                        fundamental = future.result()
                    except Exception as exc:
                        warnings.append(
                            f"peer {candidate} fundamental failed: {str(exc)[:120]}"
                        )
                        continue
                    name = str(fundamental.get("name") or candidate)
                    cached_label = str(
                        self.cache.get(f"stock:industry:{candidate}") or ""
                    )
                    if (
                        fundamental.get("is_st")
                        or name.upper().startswith(("ST", "*ST"))
                        or not self._has_valuation_basis(fundamental)
                        or not self._matches_industry(
                            fundamental,
                            target_code,
                            target_label,
                            cached_label,
                        )
                    ):
                        continue
                    members.append(candidate)
                members.sort(
                    key=lambda code: candidate_order.get(code, len(candidates))
                )
            except TimeoutError:
                warnings.append("peer fundamental collection timeout")
                for future in futures:
                    future.cancel()
                break
        return {
            "members": members[:limit],
            "candidate_fetch_count": submitted_count,
            "warnings": warnings,
        }

    def _peer_record(self, code: str) -> dict | None:
        fundamentals = self.get_fundamentals(
            code, allow_external=False
        )
        quote = self.get_quote(code)
        price = safe_number(quote.get("price"))
        if price is None or price <= 0:
            return None
        shares = safe_number(fundamentals.get("total_shares"))
        revenue = safe_number(fundamentals.get("revenue"))
        eps = safe_number(fundamentals.get("eps"))
        bvps = safe_number(fundamentals.get("bvps"))
        market_cap = price * shares if shares else None
        financial_history = self.cache.get(f"fin:abstract:{code}")
        financial_records = (
            financial_history if isinstance(financial_history, list) else []
        )
        growth_rate = derive_growth_rate(financial_records)
        earnings_growth_rate = derive_earnings_growth(financial_records)
        latest_financial = max(
            (row for row in financial_records if isinstance(row, dict)),
            key=lambda row: _date_text(
                _first(row, ("report_date", "end_date", "report_period"))
            ),
            default={},
        )
        return {
            "code": code,
            "name": str(fundamentals.get("name") or code),
            "price": price,
            "amount": safe_number(quote.get("amount")),
            "market_cap": market_cap,
            "eps": eps,
            "bvps": bvps,
            "revenue": revenue,
            "total_shares": shares,
            "pe": price / eps if eps and eps > 0 else None,
            "pb": price / bvps if bvps and bvps > 0 else None,
            "ps": (
                market_cap / revenue
                if market_cap and revenue and revenue > 0
                else None
            ),
            "growth_rate": growth_rate,
            "earnings_growth_rate": earnings_growth_rate,
            "roe": safe_number(latest_financial.get("roe")),
            "net_margin": safe_number(latest_financial.get("net_margin")),
            "quote_source": quote.get("source"),
            "fundamental_source": fundamentals.get("source"),
            "report_period": fundamentals.get("report_period"),
        }

    def get_peers(
        self,
        code: object,
        *,
        industry: str | None = None,
        limit: int = DEFAULT_PEER_LIMIT,
    ) -> dict:
        normalized = self._code(code)
        capped_limit = max(1, min(int(limit), DEFAULT_PEER_LIMIT))
        industry_result = (
            {
                "industry": industry,
                "industry_code": None,
                "industry_name": industry,
                "status": "partial",
                "warnings": [],
            }
            if industry
            else self.get_industry(normalized)
        )
        industry_label = str(industry_result.get("industry") or "")
        industry_code = str(industry_result.get("industry_code") or "")
        if not industry_label and not industry_code:
            return {
                "code": normalized,
                "industry": None,
                "peers": [],
                "candidate_fetch_count": 0,
                "excluded_count": 0,
                "source": "unavailable",
                "status": "unavailable",
                "warnings": list(industry_result.get("warnings") or []),
            }
        identity = industry_code or industry_label
        result_key = (
            f"valuation:peer_result:{normalized}:{identity}:{capped_limit}"
        )
        cached_result = self.cache.get(result_key)
        if isinstance(cached_result, dict):
            return _json_safe(cached_result)
        member_key = (
            f"valuation:peer_members:{normalized}:{identity}:{capped_limit}"
        )
        membership = self.cache.get(member_key)
        if not isinstance(membership, dict):
            membership = self._build_peer_members(
                normalized, industry_result, capped_limit
            )
            self.cache.set(member_key, membership, ttl=PEER_MEMBER_TTL)

        members = list(membership.get("members") or [])
        peers: list[dict] = []
        warnings = list(industry_result.get("warnings") or [])
        warnings.extend(membership.get("warnings") or [])
        deadline = time.monotonic() + self.peer_timeout
        batch_size = max(1, self.max_workers)
        for offset in range(0, len(members), batch_size):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                warnings.append("peer quote collection timeout")
                break
            futures: dict[Future, str] = {}
            for member in members[offset : offset + batch_size]:
                future = self._submit_bounded(self._peer_record, member)
                if future is None:
                    warnings.append("peer quote task rejected by bounded executor")
                    continue
                futures[future] = member
            try:
                for future in as_completed(futures, timeout=remaining):
                    member = futures[future]
                    try:
                        row = future.result()
                        if row:
                            peers.append(row)
                    except Exception as exc:
                        warnings.append(
                            f"peer {member} quote failed: {str(exc)[:120]}"
                        )
            except TimeoutError:
                warnings.append("peer quote collection timeout")
                for future in futures:
                    future.cancel()
                break
        order = {member: index for index, member in enumerate(members)}
        peers.sort(key=lambda row: order.get(str(row.get("code")), 10**9))
        result = {
            "code": normalized,
            "industry": industry_label or industry_code,
            "industry_code": industry_code or None,
            "peers": peers[:capped_limit],
            "candidate_fetch_count": int(
                membership.get("candidate_fetch_count") or 0
            ),
            "excluded_count": max(
                0,
                int(membership.get("candidate_fetch_count") or 0) - len(peers),
            ),
            "source": "tdx_industry+bounded_peers"
            if industry_code
            else "baostock_industry+bounded_peers",
            "status": (
                "unavailable"
                if not peers
                else ("partial" if warnings or len(peers) < capped_limit else "success")
            ),
            "warnings": list(dict.fromkeys(warnings)),
        }
        result = _json_safe(result)
        self.cache.set(result_key, result, ttl=PEER_RESULT_TTL)
        return result

    def get_market_inputs(self) -> dict:
        cached = self.cache.get("valuation:market_inputs")
        if isinstance(cached, dict):
            return _json_safe(cached)
        warnings: list[str] = []
        summaries = self._market_summaries()
        changes = [
            safe_number(row.get("change_pct")) for row in summaries
        ]
        changes = [value for value in changes if value is not None]
        advances = sum(1 for value in changes if value > 0)
        total_amount = (
            sum(safe_number(row.get("amount")) or 0.0 for row in summaries)
            if summaries
            else None
        )
        latest_date = max(
            (_date_text(row.get("latest_date")) for row in summaries),
            default="",
        )
        if not summaries:
            warnings.append(
                "market breadth and liquidity summaries unavailable"
            )
        index_bars: list[dict] = []
        try:
            raw = self._call_source(
                "fetch_klines", "SH000300", count=260, period="1d"
            )
            index_bars = [
                _json_safe(row) for row in raw if isinstance(row, dict)
            ]
        except Exception as exc:
            warnings.append(f"index history unavailable: {str(exc)[:160]}")
        index_bars.sort(key=lambda row: _date_text(row.get("date")))
        index_closes: list[float] = []
        for row in index_bars:
            close = safe_number(row.get("close"))
            factor = safe_number(row.get("factor"))
            adjusted = (
                close * factor
                if close is not None and factor is not None and factor > 0
                else close
            )
            if adjusted is not None and adjusted > 0:
                row["adjusted_close"] = adjusted
                index_closes.append(adjusted)
        index_percentile = None
        index_regime = None
        if index_closes:
            latest_close = index_closes[-1]
            below = sum(1 for value in index_closes if value < latest_close)
            equal = sum(1 for value in index_closes if value == latest_close)
            index_percentile = (below + 0.5 * equal) / len(index_closes)
            ma20 = sum(index_closes[-20:]) / min(20, len(index_closes))
            ma60 = sum(index_closes[-60:]) / min(60, len(index_closes))
            if latest_close > ma20 > ma60:
                index_regime = "bull"
            elif latest_close < ma20 < ma60:
                index_regime = "bear"
            else:
                index_regime = "neutral"
        if not index_bars and not any(
            "index" in warning.lower() for warning in warnings
        ):
            warnings.append("index history unavailable")
        result = {
            "breadth": {
                "advance_ratio": (
                    advances / len(changes) if changes else None
                ),
                "advancing_count": advances if changes else None,
                "observed_count": len(changes),
                "as_of": latest_date or None,
                "source": (
                    "stock_daily_summary" if summaries else "unavailable"
                ),
            },
            "liquidity": {
                "total_amount": total_amount,
                "active_count": len(summaries),
                "as_of": latest_date or None,
                "source": (
                    "stock_daily_summary" if summaries else "unavailable"
                ),
            },
            "index": {
                "code": "SH000300",
                "bars": index_bars,
                "sample_length": len(index_bars),
                "latest_date": (
                    _date_text(index_bars[-1].get("date"))
                    if index_bars
                    else None
                ),
                "source": "tdx_quant" if index_bars else "unavailable",
                "percentile": index_percentile,
                "regime": index_regime,
                "status": "success" if index_bars else "unavailable",
            },
            "status": "success" if not warnings else "partial",
            "warnings": warnings,
        }
        result = _json_safe(result)
        self.cache.set(
            "valuation:market_inputs",
            result,
            ttl=_status_ttl(
                result["status"],
                success=MARKET_TTL,
                partial=MARKET_TTL,
            ),
        )
        return result

    @staticmethod
    def _section_error(name: str, exc: Exception) -> dict:
        return {
            "status": "error",
            "source": "unavailable",
            "warnings": [f"{name} failed: {str(exc)[:160]}"],
        }

    def get_valuation_inputs(
        self, code: object, *, include_peers: bool = True
    ) -> dict:
        normalized = self._code(code)
        tasks = {
            "quote": (self.get_quote, (normalized,)),
            "fundamentals": (self.get_fundamentals, (normalized,)),
            "financial_history": (self.get_financial_history, (normalized,)),
            "industry": (self.get_industry, (normalized,)),
            "daily_history": (self.get_daily_history, (normalized,)),
            "market": (self.get_market_inputs, ()),
        }
        futures: dict[str, Future] = {}
        results: dict[str, dict] = {}
        for name, (fn, args) in tasks.items():
            future = self._submit_bounded(fn, *args)
            if future is None:
                try:
                    results[name] = fn(*args)
                except Exception as exc:
                    results[name] = self._section_error(name, exc)
            else:
                futures[name] = future
        for name, future in futures.items():
            try:
                results[name] = future.result(timeout=max(30.0, self.source_timeout * 2))
            except Exception as exc:
                results[name] = self._section_error(name, exc)

        quote = results["quote"]
        fundamentals = results["fundamentals"]
        financial_history = results["financial_history"]
        industry = results["industry"]
        daily_history = results["daily_history"]
        market = results["market"]
        peers = (
            self.get_peers(normalized, limit=DEFAULT_PEER_LIMIT)
            if include_peers
            else {
                "code": normalized,
                "industry": industry.get("industry"),
                "peers": [],
                "candidate_fetch_count": 0,
                "excluded_count": 0,
                "source": "not_requested",
                "status": "unavailable",
                "warnings": ["peer collection not requested"],
            }
        )
        sections = (
            quote,
            fundamentals,
            financial_history,
            industry,
            daily_history,
            peers,
            market,
        )
        warnings = [
            str(warning)
            for section in sections
            for warning in section.get("warnings") or []
        ]
        statuses = {str(section.get("status") or "") for section in sections}
        status = (
            "unavailable"
            if quote.get("price") is None
            and fundamentals.get("status") == "unavailable"
            else ("success" if statuses == {"success"} else "partial")
        )
        name = str(
            fundamentals.get("name")
            or quote.get("name")
            or self.cache.get(f"stock:name:{normalized}")
            or normalized
        )
        source_values = {
            str(section.get("source"))
            for section in sections
            if section.get("source")
        }
        source_values.update(
            {
                str(market.get("breadth", {}).get("source") or ""),
                str(market.get("liquidity", {}).get("source") or ""),
                str(market.get("index", {}).get("source") or ""),
            }
        )
        return {
            "code": normalized,
            "name": name,
            "status": status,
            "quote": quote,
            "fundamentals": fundamentals,
            "financial_history": financial_history,
            "industry": industry,
            "daily_history": daily_history,
            "peers": peers,
            "market": market,
            "data_date": quote.get("as_of")
            or daily_history.get("latest_date"),
            "report_period": financial_history.get("report_period")
            or fundamentals.get("report_period"),
            "sources": sorted(source_values - {"", "None"}),
            "warnings": warnings,
        }

    load = get_valuation_inputs

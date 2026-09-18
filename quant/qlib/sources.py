from __future__ import annotations

from datetime import date, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from threading import Lock
import time
from typing import Any

from .corporate_actions import reconcile_adjustment_rows


AKSHARE_DAILY_FIELDS = {
    "date": ("\u65e5\u671f", "date"),
    "open": ("\u5f00\u76d8", "open"),
    "high": ("\u6700\u9ad8", "high"),
    "low": ("\u6700\u4f4e", "low"),
    "close": ("\u6536\u76d8", "close"),
    "volume": ("\u6210\u4ea4\u91cf", "volume"),
    "amount": ("\u6210\u4ea4\u989d", "amount"),
}


_SOURCE_EXECUTOR = ThreadPoolExecutor(max_workers=16, thread_name_prefix="qlib-source")


class SourceCircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        cooldown_seconds: float = 60.0,
        clock=time.monotonic,
    ):
        self.failure_threshold = max(1, int(failure_threshold))
        self.cooldown_seconds = max(1.0, float(cooldown_seconds))
        self.clock = clock
        self._states: dict[str, dict[str, float | int]] = {}
        self._lock = Lock()

    def allow(self, source: str) -> bool:
        with self._lock:
            state = self._states.get(str(source)) or {}
            opened_until = float(state.get("opened_until") or 0.0)
            return opened_until <= float(self.clock())

    def success(self, source: str) -> None:
        with self._lock:
            self._states[str(source)] = {
                "consecutive_failures": 0,
                "opened_until": 0.0,
            }

    def seconds_until_recovery(self, source: str) -> float:
        with self._lock:
            state = self._states.get(str(source)) or {}
            opened_until = float(state.get("opened_until") or 0.0)
        return max(0.0, opened_until - float(self.clock()))

    def failure(self, source: str) -> None:
        with self._lock:
            key = str(source)
            state = dict(self._states.get(key) or {})
            failures = int(state.get("consecutive_failures") or 0) + 1
            opened_until = float(state.get("opened_until") or 0.0)
            if failures >= self.failure_threshold:
                opened_until = float(self.clock()) + self.cooldown_seconds
            self._states[key] = {
                "consecutive_failures": failures,
                "opened_until": opened_until,
            }

    def snapshot(self, source: str) -> dict[str, float | int | bool]:
        with self._lock:
            state = dict(self._states.get(str(source)) or {})
        return {
            "consecutive_failures": int(state.get("consecutive_failures") or 0),
            "opened_until": float(state.get("opened_until") or 0.0),
            "open": not self.allow(source),
        }


SOURCE_CIRCUIT = SourceCircuitBreaker()


def guarded_source_call(
    source: str,
    operation,
    *,
    timeout_seconds: float,
    circuit: SourceCircuitBreaker = SOURCE_CIRCUIT,
    wait_for_recovery: bool = False,
    sleep=time.sleep,
):
    if not circuit.allow(source):
        if wait_for_recovery:
            sleep(circuit.seconds_until_recovery(source))
        if not circuit.allow(source):
            raise RuntimeError(f"source circuit open: {source}")
    future = _SOURCE_EXECUTOR.submit(operation)
    try:
        value = future.result(timeout=max(0.001, float(timeout_seconds)))
    except FutureTimeoutError as exc:
        future.cancel()
        circuit.failure(source)
        raise TimeoutError(f"source timeout: {source}") from exc
    except Exception:
        circuit.failure(source)
        raise
    circuit.success(source)
    return value


def _validate_akshare_daily_columns(frame: Any) -> None:
    columns = {str(column) for column in getattr(frame, "columns", [])}
    missing = [
        field
        for field, aliases in AKSHARE_DAILY_FIELDS.items()
        if not any(alias in columns for alias in aliases)
    ]
    if missing:
        raise ValueError(f"missing columns: {', '.join(missing)}")


def normalize_instrument(code: str) -> str:
    text = str(code or "").upper().strip()
    for prefix in ("SH", "SZ", "BJ"):
        if text.startswith(prefix):
            text = text[2:]
    text = text.split(".")[0].zfill(6)[:6]
    if text.startswith(("5", "6", "9")) and not text.startswith("92"):
        return f"SH{text}"
    if text.startswith(("4", "8", "92")):
        return f"BJ{text}"
    return f"SZ{text}"


def pure_code(instrument: str) -> str:
    return normalize_instrument(instrument)[2:]


def _iso_trade_date(value: Any) -> str:
    text = str(value or "").strip()[:10]
    digits = text.replace("-", "")
    if len(digits) >= 8 and digits[:8].isdigit():
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return ""


def _normalize_rows(
    instrument: str,
    rows: list[dict[str, Any]],
    source: str,
) -> list[dict[str, Any]]:
    fetched_at = datetime.now().astimezone().isoformat(timespec="seconds")
    normalized = []
    for row in rows or []:
        trade_date = _iso_trade_date(row.get("date") or row.get("datetime"))
        if not trade_date:
            continue
        normalized.append(
            {
                "instrument": normalize_instrument(instrument),
                "datetime": trade_date,
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "volume": row.get("volume", 0),
                "amount": row.get("amount", 0),
                "factor": row.get("factor", 1.0),
                "source": source,
                "fetched_at": fetched_at,
            }
        )
    return normalized


def _merge_by_date(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for group in groups:
        for row in group or []:
            trade_date = _iso_trade_date(row.get("datetime") or row.get("date"))
            if trade_date:
                merged[trade_date] = row
    return [merged[key] for key in sorted(merged)]


def _fetch_akshare_daily_tracks(
    instrument: str,
    start_date: str,
    end_date: str,
) -> dict[str, list[dict[str, Any]]]:
    import akshare as ak

    code = pure_code(instrument)

    def load(adjust: str, source: str) -> list[dict[str, Any]]:
        frame = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
            adjust=adjust,
        )
        _validate_akshare_daily_columns(frame)
        rows = []
        for item in frame.to_dict(orient="records"):
            rows.append(
                {
                    "date": _pick(item, "日期", "date"),
                    "open": _pick(item, "开盘", "open"),
                    "high": _pick(item, "最高", "high"),
                    "low": _pick(item, "最低", "low"),
                    "close": _pick(item, "收盘", "close"),
                    "volume": float(_pick(item, "成交量", "volume") or 0) * 100,
                    "amount": _pick(item, "成交额", "amount"),
                    "source": source,
                }
            )
        return _normalize_rows(instrument, rows, source)

    return {
        "raw": load("", "akshare_unadjusted"),
        "front": load("qfq", "akshare_front"),
    }


def fetch_daily_history(
    instrument: str,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    code = pure_code(instrument)
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    count = max(300, int((end - start).days * 0.75) + 40)

    tdx_error = ""
    try:
        from quant.data.tdx_quant_source import fetch_klines_allow_price_jumps

        rows = fetch_klines_allow_price_jumps(
            code,
            count=count,
            period="1d",
            dividend_type="none",
        )
        rows = [
            row
            for row in rows
            if start_date <= _iso_trade_date(row.get("date")) <= end_date
        ]
        if rows:
            return _normalize_rows(instrument, rows, "tdxquant_unadjusted")
    except Exception as exc:
        tdx_error = str(exc)[:240]

    try:
        from quant.data.baostock_source import fetch_klines_range

        rows = fetch_klines_range(code, start_date, end_date, adjustflag="3")
        if rows:
            return _normalize_rows(instrument, rows, "baostock_unadjusted")
    except Exception:
        pass

    try:
        from quant.data.tencent_source import fetch_klines

        rows = fetch_klines(code, count=count)
        rows = [
            row
            for row in rows
            if start_date <= _iso_trade_date(row.get("date")) <= end_date
        ]
        if rows:
            return _normalize_rows(instrument, rows, "tencent_qfq_fallback")
    except Exception as exc:
        raise RuntimeError(
            f"all Qlib daily sources failed for {code}: "
            f"tdx={tdx_error or 'empty'}; fallback={str(exc)[:240]}"
        ) from exc
    return []


def fetch_daily_history_tracks(
    instrument: str,
    start_date: str,
    end_date: str,
    *,
    listing_date: str = "",
) -> dict[str, Any]:
    code = pure_code(instrument)
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    count = max(300, int((end - start).days * 0.75) + 40)
    health = {"passed": False, "sources": [], "errors": []}

    try:
        from quant.data.tdx_quant_source import fetch_klines_allow_price_jumps

        raw_rows, front_rows = guarded_source_call(
            "tdxquant",
            lambda: (
                fetch_klines_allow_price_jumps(
                    code,
                    count=count,
                    period="1d",
                    dividend_type="none",
                ),
                fetch_klines_allow_price_jumps(
                    code,
                    count=count,
                    period="1d",
                    dividend_type="front",
                ),
            ),
            timeout_seconds=45,
            wait_for_recovery=True,
        )
        raw = _normalize_rows(
            instrument,
            [
                row
                for row in raw_rows
                if start_date <= _iso_trade_date(row.get("date")) <= end_date
            ],
            "tdxquant_unadjusted",
        )
        front = _normalize_rows(
            instrument,
            [
                row
                for row in front_rows
                if start_date <= _iso_trade_date(row.get("date")) <= end_date
            ],
            "tdxquant_front",
        )
        if raw and front:
            earliest = min(row["datetime"] for row in raw)
            eligible_start = start
            try:
                listed_on = date.fromisoformat(str(listing_date)[:10])
                if start <= listed_on <= end:
                    eligible_start = listed_on
            except ValueError:
                pass
            missing_days = (date.fromisoformat(earliest) - eligible_start).days
            sources = ["tdxquant"]
            if missing_days > 14:
                supplement_end = (
                    date.fromisoformat(earliest) - timedelta(days=1)
                ).isoformat()
                try:
                    supplement = guarded_source_call(
                        "akshare",
                        lambda: _fetch_akshare_daily_tracks(
                            instrument,
                            start_date,
                            supplement_end,
                        ),
                        timeout_seconds=60,
                        wait_for_recovery=True,
                    )
                    if supplement["raw"] and supplement["front"]:
                        raw = _merge_by_date(supplement["raw"], raw)
                        front = _merge_by_date(supplement["front"], front)
                        sources.insert(0, "akshare")
                    else:
                        raise RuntimeError("AkShare supplement returned empty rows")
                except Exception as akshare_exc:
                    try:
                        from quant.data.baostock_source import fetch_klines_range

                        prefix_raw_rows, prefix_front_rows = guarded_source_call(
                            "baostock",
                            lambda: (
                                fetch_klines_range(
                                    code,
                                    start_date,
                                    supplement_end,
                                    adjustflag="3",
                                    allow_price_jumps=True,
                                ),
                                fetch_klines_range(
                                    code,
                                    start_date,
                                    supplement_end,
                                    adjustflag="2",
                                    allow_price_jumps=True,
                                ),
                            ),
                            timeout_seconds=60,
                            wait_for_recovery=True,
                        )
                        prefix_raw = _normalize_rows(
                            instrument, prefix_raw_rows, "baostock_unadjusted"
                        )
                        prefix_front = _normalize_rows(
                            instrument, prefix_front_rows, "baostock_front"
                        )
                        if not prefix_raw or not prefix_front:
                            raise RuntimeError("BaoStock prefix returned empty rows")
                        raw = _merge_by_date(prefix_raw, raw)
                        front = _merge_by_date(prefix_front, front)
                        sources.insert(0, "baostock")
                    except Exception as baostock_exc:
                        raise RuntimeError(
                            f"TdxQuant history begins at {earliest}; "
                            "missing prefix supplement failed: "
                            f"akshare={str(akshare_exc)[:160]}; "
                            f"baostock={str(baostock_exc)[:160]}"
                        ) from baostock_exc
            health.update({"passed": True, "sources": ["tdxquant"]})
            health["sources"] = sources
            return {
                "raw": reconcile_adjustment_rows(raw, front, []),
                "front": front,
                "source_health": health,
            }
        health["errors"].append("tdxquant raw/front track returned empty rows")
    except Exception as exc:
        health["errors"].append(f"tdxquant: {str(exc)[:240]}")

    try:
        from quant.data.baostock_source import fetch_klines_range

        raw_rows, front_rows = guarded_source_call(
            "baostock",
            lambda: (
                fetch_klines_range(
                    code,
                    start_date,
                    end_date,
                    adjustflag="3",
                    allow_price_jumps=True,
                ),
                fetch_klines_range(
                    code,
                    start_date,
                    end_date,
                    adjustflag="2",
                    allow_price_jumps=True,
                ),
            ),
            timeout_seconds=60,
            wait_for_recovery=True,
        )
        raw = _normalize_rows(instrument, raw_rows, "baostock_unadjusted")
        front = _normalize_rows(instrument, front_rows, "baostock_front")
        if raw and front:
            return {
                "raw": reconcile_adjustment_rows(raw, front, []),
                "front": front,
                "source_health": {
                    "passed": True,
                    "sources": ["baostock"],
                    "errors": health["errors"],
                },
            }
        health["errors"].append("baostock raw/front track returned empty rows")
    except Exception as exc:
        health["errors"].append(f"baostock: {str(exc)[:240]}")

    try:
        tracks = guarded_source_call(
            "akshare",
            lambda: _fetch_akshare_daily_tracks(instrument, start_date, end_date),
            timeout_seconds=60,
            wait_for_recovery=True,
        )
        raw = tracks["raw"]
        front = tracks["front"]
        if raw and front:
            return {
                "raw": reconcile_adjustment_rows(raw, front, []),
                "front": front,
                "source_health": {
                    "passed": True,
                    "sources": ["akshare"],
                    "errors": health["errors"],
                },
            }
        health["errors"].append("akshare raw/front track returned empty rows")
    except Exception as exc:
        health["errors"].append(f"akshare: {str(exc)[:240]}")

    raw = fetch_daily_history(instrument, start_date, end_date)
    if not raw:
        raise RuntimeError(
            f"Qlib dual-track source failed for {code}: {'; '.join(health['errors'])}"
        )
    health["sources"] = sorted({str(row.get("source") or "fallback") for row in raw})
    health["errors"].append("front-adjusted validation track unavailable")
    raise RuntimeError(
        f"Qlib dual-track source failed for {code}: {'; '.join(health['errors'])}"
    )


def fetch_daily_history_tracks_batch(
    instruments: list[str],
    start_date: str,
    end_date: str,
    *,
    batch_size: int = 100,
) -> dict[str, dict[str, Any]]:
    """Best-effort TdxQuant bulk prefetch; absent symbols keep the normal fallback chain."""
    from quant.data.tdx_quant_source import (
        fetch_klines_batch_allow_price_jumps,
        health_check,
        tdx_symbol,
    )

    health = health_check()
    if health.get("available") is not True:
        raise RuntimeError(
            "tdxquant_batch_unavailable: "
            + str(health.get("error") or "health check failed")[:240]
        )

    requested = list(dict.fromkeys(normalize_instrument(item) for item in instruments))
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    count = max(30, int((end - start).days * 0.75) + 10)
    output: dict[str, dict[str, Any]] = {}
    bounded_batch = max(1, min(int(batch_size), 200))
    for offset in range(0, len(requested), bounded_batch):
        chunk = requested[offset : offset + bounded_batch]
        raw_batches = fetch_klines_batch_allow_price_jumps(
            chunk,
            count=count,
            period="1d",
            dividend_type="none",
            batch_size=bounded_batch,
        )
        front_batches = fetch_klines_batch_allow_price_jumps(
            chunk,
            count=count,
            period="1d",
            dividend_type="front",
            batch_size=bounded_batch,
        )
        for instrument in chunk:
            symbol = tdx_symbol(instrument)
            raw = _normalize_rows(
                instrument,
                list(raw_batches.get(symbol, [])),
                "tdxquant_batch_unadjusted",
            )
            front = _normalize_rows(
                instrument,
                list(front_batches.get(symbol, [])),
                "tdxquant_batch_front",
            )
            if not raw or not front:
                continue
            try:
                output[instrument] = {
                    "raw": reconcile_adjustment_rows(raw, front, []),
                    "front": front,
                    "source_health": {
                        "passed": True,
                        "sources": ["tdxquant_batch"],
                        "errors": [],
                    },
                }
            except Exception:
                continue
    return output


def _pick(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return value
    return ""


def _records(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    return frame.to_dict(orient="records")


def _load_records_with_retry(loader, *, attempts: int = 3) -> list[dict[str, Any]]:
    last_error: Exception | None = None
    for attempt in range(max(1, int(attempts))):
        try:
            return _records(loader())
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    assert last_error is not None
    raise last_error


def fetch_akshare_reference_data() -> dict[str, Any]:
    import akshare as ak

    errors: list[str] = []
    current_universe: list[dict[str, str]] = []
    name_changes: list[dict[str, str]] = []
    delistings: list[dict[str, str]] = []
    current_by_symbol: dict[str, dict[str, str]] = {}

    listing_specs = (
        (
            "akshare_sse_main_listed",
            lambda: ak.stock_info_sh_name_code(symbol="主板A股"),
            ("证券代码", "代码"),
            ("证券简称", "名称"),
            ("上市日期", "上市时间"),
        ),
        (
            "akshare_sse_star_listed",
            lambda: ak.stock_info_sh_name_code(symbol="科创板"),
            ("证券代码", "代码"),
            ("证券简称", "名称"),
            ("上市日期", "上市时间"),
        ),
        (
            "akshare_szse_listed",
            lambda: ak.stock_info_sz_name_code(symbol="A股列表"),
            ("A股代码", "证券代码", "代码"),
            ("A股简称", "证券简称", "名称"),
            ("A股上市日期", "上市日期", "上市时间"),
        ),
    )
    for source, loader, code_keys, name_keys, date_keys in listing_specs:
        try:
            for row in _load_records_with_retry(loader):
                code = str(_pick(row, *code_keys)).zfill(6)
                listed = _iso_trade_date(_pick(row, *date_keys))
                if len(code) == 6 and code.isdigit() and not code.startswith("920"):
                    symbol = normalize_instrument(code)
                    current_by_symbol[symbol] = {
                        "instrument": symbol,
                        "name": str(_pick(row, *name_keys) or code),
                        "listing_date": listed,
                        "source": source,
                    }
        except Exception as exc:
            errors.append(f"{source}: {str(exc)[:240]}")

    current_universe = [current_by_symbol[key] for key in sorted(current_by_symbol)]
    listing_date_coverage = (
        sum(bool(row.get("listing_date")) for row in current_universe)
        / len(current_universe)
        if current_universe
        else 0.0
    )
    if current_universe and listing_date_coverage < 0.99:
        errors.append(f"listing_date_coverage: {listing_date_coverage:.6f}")

    try:
        for row in _load_records_with_retry(
            lambda: ak.stock_info_sz_change_name(symbol="简称变更")
        ):
            code = str(_pick(row, "证券代码", "代码")).zfill(6)
            trade_date = _iso_trade_date(_pick(row, "变更日期", "变更时间", "日期"))
            if len(code) == 6 and code.isdigit() and trade_date:
                name_changes.append(
                    {
                        "instrument": normalize_instrument(code),
                        "date": trade_date,
                        "before": str(_pick(row, "变更前简称", "变更前证券简称")),
                        "after": str(_pick(row, "变更后简称", "变更后证券简称")),
                        "source": "akshare_szse_name_change",
                    }
                )
    except Exception as exc:
        errors.append(f"name_changes: {str(exc)[:240]}")

    delist_specs = (
        (
            "akshare_sse_delist",
            lambda: ak.stock_info_sh_delist(symbol="全部"),
            ("公司代码", "证券代码", "代码"),
        ),
        (
            "akshare_szse_delist",
            lambda: ak.stock_info_sz_delist(symbol="终止上市公司"),
            ("证券代码", "公司代码", "代码"),
        ),
    )
    for source, loader, code_keys in delist_specs:
        try:
            for row in _load_records_with_retry(loader):
                code = str(_pick(row, *code_keys)).zfill(6)
                if len(code) != 6 or not code.isdigit() or code.startswith("920"):
                    continue
                delistings.append(
                    {
                        "instrument": normalize_instrument(code),
                        "listing_date": _iso_trade_date(
                            _pick(row, "上市日期", "上市时间")
                        ),
                        "delisting_date": _iso_trade_date(
                            _pick(
                                row,
                                "终止上市日期",
                                "暂停上市日期",
                                "摘牌日期",
                                "退市日期",
                            )
                        ),
                        "source": source,
                    }
                )
        except Exception as exc:
            errors.append(f"{source}: {str(exc)[:240]}")

    return {
        "current_universe": current_universe,
        "name_changes": name_changes,
        "delistings": delistings,
        "source_health": {
            "passed": not errors,
            "errors": errors,
            "listing_date_coverage": listing_date_coverage,
            "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
    }


def load_universe(trade_date: str = "") -> list[dict[str, str]]:
    tdx_error = ""
    try:
        from quant.data.tdx_quant_source import fetch_stock_universe

        rows = []
        for item in fetch_stock_universe():
            code = str(item.get("code") or "")
            if len(code) != 6 or not code.isdigit() or code.startswith("920"):
                continue
            rows.append(
                {
                    "instrument": normalize_instrument(f"{item.get('market', '')}{code}"),
                    "name": str(item.get("name") or code),
                    "trade_status": "1",
                }
            )
        if rows:
            return rows
    except Exception as exc:
        tdx_error = str(exc)[:240]

    import baostock as bs

    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(
            f"all Qlib universe sources failed: "
            f"tdx={tdx_error or 'empty'}; baostock={login.error_msg}"
        )
    try:
        query_date = trade_date or date.today().isoformat()
        result = bs.query_all_stock(day=query_date)
        rows = []
        while result.error_code == "0" and result.next():
            item = dict(zip(result.fields, result.get_row_data()))
            code = str(item.get("code") or "")
            pure = code.split(".")[-1]
            if len(pure) != 6 or pure.startswith("920"):
                continue
            rows.append(
                {
                    "instrument": normalize_instrument(pure),
                    "name": str(item.get("code_name") or pure),
                    "trade_status": str(item.get("tradeStatus") or ""),
                }
            )
        return rows
    finally:
        bs.logout()

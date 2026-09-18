#!/usr/bin/env python
"""Build read-only F4 PIT industry and CSI 300 benchmark references."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant.qlib.f4_references import (  # noqa: E402
    build_benchmark_payload,
    build_industry_payload,
    normalize_industry_records,
)
from quant.qlib.sources import normalize_instrument  # noqa: E402


DEFAULT_DATASET_ROOT = PROJECT_ROOT / "data" / "qlib" / "datasets" / "a_share_6y_daily"
DEFAULT_INDUSTRY_PATH = PROJECT_ROOT / "data" / "research" / "industry" / "pit_industry.json"
DEFAULT_BENCHMARK_PATH = PROJECT_ROOT / "data" / "research" / "benchmarks" / "000300.json"


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    temp.replace(path)


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def load_eligible_dates(raw_dir: Path) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for path in sorted(raw_dir.glob("*.json")):
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(rows, list):
            continue
        symbol = normalize_instrument(path.stem)
        dates = sorted(
            {
                str(row.get("datetime") or row.get("date") or "")[:10]
                for row in rows
                if isinstance(row, dict)
                and str(row.get("datetime") or row.get("date") or "")[:10]
            }
        )
        if dates:
            result[symbol] = dates
    return result


class BoundedCninfoIndustryClient:
    """Small p_stock2110 client with an explicit transport deadline.

    AkShare 1.18.60 calls ``requests.post`` without a timeout.  A stalled
    CNINFO connection therefore blocks every worker and prevents the weekly
    research job from ever reaching a terminal state.  This adapter preserves
    AkShare's response shape while making the network boundary finite.
    """

    URL = "https://webapi.cninfo.com.cn/api/stock/p_stock2110"
    _COLUMN_MAP = {
        "SECCODE": "证券代码",
        "VARYDATE": "变更日期",
        "F001V": "分类标准编码",
        "F003V": "行业编码",
        "F006V": "行业大类",
    }

    def __init__(
        self,
        *,
        post: Callable[..., Any],
        accept_enckey: str,
        timeout: tuple[float, float] = (5.0, 15.0),
    ) -> None:
        if not str(accept_enckey or "").strip():
            raise RuntimeError("cninfo_accept_enckey_missing")
        self._post = post
        self._accept_enckey = str(accept_enckey)
        self._timeout = (float(timeout[0]), float(timeout[1]))

    @staticmethod
    def _date(value: str) -> str:
        digits = "".join(char for char in str(value or "") if char.isdigit())[:8]
        if len(digits) != 8:
            raise ValueError("cninfo_industry_date_invalid")
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"

    def stock_industry_change_cninfo(
        self, *, symbol: str, start_date: str, end_date: str
    ):
        import pandas as pd

        response = self._post(
            self.URL,
            params={
                "scode": str(symbol),
                "sdate": self._date(start_date),
                "edate": self._date(end_date),
            },
            headers={
                "Accept": "*/*",
                "Accept-Encoding": "gzip, deflate",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Cache-Control": "no-cache",
                "Content-Length": "0",
                "Host": "webapi.cninfo.com.cn",
                "Accept-Enckey": self._accept_enckey,
                "Origin": "https://webapi.cninfo.com.cn",
                "Pragma": "no-cache",
                "Referer": "https://webapi.cninfo.com.cn/",
                "User-Agent": "XuanJiQuant-CNINFO-Industry/1.0",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload = response.json()
        records = payload.get("records") if isinstance(payload, dict) else None
        if not isinstance(records, list):
            raise RuntimeError("cninfo_industry_payload_invalid")
        normalized = []
        for raw in records:
            if not isinstance(raw, dict):
                continue
            normalized.append(
                {
                    target: raw.get(source)
                    for source, target in self._COLUMN_MAP.items()
                }
            )
        return pd.DataFrame(normalized, columns=list(self._COLUMN_MAP.values()))


def _load_akshare() -> BoundedCninfoIndustryClient:
    """Create the bounded client and initialize MiniRacer on the main thread."""
    import akshare as ak

    function_globals = ak.stock_industry_change_cninfo.__globals__
    js_runtime = function_globals["py_mini_racer"].MiniRacer()
    js_runtime.eval(function_globals["_get_file_content_ths"]("cninfo.js"))
    accept_enckey = js_runtime.call("getResCode1")
    return BoundedCninfoIndustryClient(
        post=function_globals["requests"].post,
        accept_enckey=str(accept_enckey),
    )


def _required_f4_validation_through(
    eligible_dates: Mapping[str, Sequence[str]], end_date: str
) -> str:
    """Return the last date consumed by the final complete F4 OOS window.

    A daily market tail that cannot form another complete purged walk-forward
    window is not read by F4 and must not force 5,000+ per-symbol industry
    requests.  Short fixtures and genuinely insufficient calendars retain the
    conservative market-end requirement.
    """
    from quant.strategy.f4_contracts import F4Blocked
    from quant.strategy.walk_forward import build_f4_windows

    calendar = sorted(
        {
            str(value)[:10]
            for values in eligible_dates.values()
            for value in values
            if str(value)[:10]
        }
    )
    try:
        windows = build_f4_windows(calendar)
    except F4Blocked:
        return str(end_date)[:10]
    return str(windows[-1].test_end.date())


def _fetch_industry(
    client: Any, symbol: str, start_date: str, end_date: str
) -> list[dict[str, str]]:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            frame = client.stock_industry_change_cninfo(
                symbol=symbol[2:],
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
            )
            return normalize_industry_records(frame.to_dict(orient="records"))
        except KeyError as exc:
            # AkShare 1.18.60 indexes the date column even when CNINFO returns
            # a successful records=[] payload.  That is a valid empty history,
            # not a transport failure and not an industry backfill licence.
            if exc.args and exc.args[0] == "变更日期":
                return []
            last_error = exc
        except Exception as exc:
            last_error = exc
        if attempt < 2:
            time.sleep(2**attempt)
    assert last_error is not None
    raise last_error


def build_industry_reference(
    *,
    dataset_root: Path,
    output_path: Path,
    workers: int = 4,
) -> dict[str, Any]:
    manifest = _read_object(dataset_root / "manifest.json")
    eligible_dates = load_eligible_dates(dataset_root / "raw")
    completed_symbols = manifest.get("completed_symbols")
    if isinstance(completed_symbols, list) and completed_symbols:
        completed = {normalize_instrument(str(symbol)) for symbol in completed_symbols}
        eligible_dates = {
            symbol: dates for symbol, dates in eligible_dates.items() if symbol in completed
        }
    start_date = str(manifest.get("start_date") or "2020-01-01")
    end_date = str(manifest.get("end_date") or datetime.now().date().isoformat())
    required_validation_through = _required_f4_validation_through(
        eligible_dates, end_date
    )
    checkpoint_path = output_path.with_suffix(".progress.json")
    checkpoint = _read_object(checkpoint_path)
    records_by_symbol = {
        str(key): list(value)
        for key, value in dict(checkpoint.get("records_by_symbol") or {}).items()
        if isinstance(value, list)
    }
    failures = dict(checkpoint.get("failed_symbols") or {})
    validated_through_by_symbol = {
        str(key): str(value)[:10]
        for key, value in dict(checkpoint.get("validated_through_by_symbol") or {}).items()
        if str(value)[:10]
    }
    active_symbols = set(eligible_dates)
    records_by_symbol = {
        symbol: rows for symbol, rows in records_by_symbol.items() if symbol in active_symbols
    }
    failures = {
        symbol: detail for symbol, detail in failures.items() if symbol in active_symbols
    }
    validated_through_by_symbol = {
        symbol: value
        for symbol, value in validated_through_by_symbol.items()
        if symbol in active_symbols
    }
    checkpoint_end = str(checkpoint.get("validated_through") or "")[:10]
    if not checkpoint_end:
        match = re.search(r"(\d{4}-\d{2}-\d{2})$", str(checkpoint.get("dataset_version") or ""))
        checkpoint_end = match.group(1) if match else ""
    if checkpoint_end:
        for symbol in records_by_symbol:
            validated_through_by_symbol.setdefault(symbol, checkpoint_end)
    symbols = sorted(eligible_dates)
    required_symbols = {
        symbol
        for symbol, dates in eligible_dates.items()
        if any(str(value)[:10] <= required_validation_through for value in dates)
    }
    failures = {
        symbol: detail for symbol, detail in failures.items() if symbol in required_symbols
    }
    pending: list[tuple[str, str]] = []
    for symbol in sorted(required_symbols):
        validated_through = validated_through_by_symbol.get(symbol, "")
        if symbol not in records_by_symbol or not validated_through:
            pending.append((symbol, "1990-01-01"))
        elif validated_through < required_validation_through:
            next_date = (
                datetime.strptime(validated_through, "%Y-%m-%d").date()
                + timedelta(days=1)
            ).isoformat()
            pending.append((symbol, next_date))
    completed_since_write = 0
    # AkShare imports py_mini_racer on this platform.  Its native V8 runtime
    # must be initialized once on the main thread before worker threads start;
    # concurrent first imports can terminate the whole Python process.
    client = _load_akshare() if pending else None

    def actual_validated_through() -> str:
        values = [
            validated_through_by_symbol.get(symbol, "")
            for symbol in sorted(required_symbols)
        ]
        return min(values) if values and all(values) else ""

    def persist() -> None:
        _write_json_atomic(
            checkpoint_path,
            {
                "dataset_version": manifest.get("dataset_version"),
                "validated_through": actual_validated_through(),
                "required_validation_through": required_validation_through,
                "validated_through_by_symbol": validated_through_by_symbol,
                "records_by_symbol": records_by_symbol,
                "failed_symbols": failures,
                "completed": len(records_by_symbol),
                "requested": len(symbols),
                "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            },
        )

    if pending:
        assert client is not None
        with ThreadPoolExecutor(max_workers=max(1, min(8, int(workers)))) as executor:
            future_map = {
                executor.submit(
                    _fetch_industry,
                    client,
                    symbol,
                    fetch_start,
                    required_validation_through,
                ): symbol
                for symbol, fetch_start in pending
            }
            for future in as_completed(future_map):
                symbol = future_map[future]
                try:
                    records_by_symbol[symbol] = normalize_industry_records(
                        [*records_by_symbol.get(symbol, []), *future.result()]
                    )
                    validated_through_by_symbol[symbol] = required_validation_through
                    failures.pop(symbol, None)
                except Exception as exc:
                    failures[symbol] = {
                        "error": str(exc)[:300],
                        "failed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    }
                completed_since_write += 1
                if completed_since_write >= 25:
                    persist()
                    completed_since_write = 0
                    print(
                        f"industry {len(records_by_symbol)}/{len(symbols)}; failed={len(failures)}",
                        flush=True,
                    )
    persist()
    records = [row for symbol in sorted(records_by_symbol) for row in records_by_symbol[symbol]]
    validation_eligible_dates = {
        symbol: [
            value
            for value in eligible_dates.get(symbol, [])
            if str(value)[:10] <= required_validation_through
        ]
        for symbol in sorted(required_symbols)
    }
    payload = build_industry_payload(records, validation_eligible_dates)
    payload.update(
        {
            "dataset_version": manifest.get("dataset_version"),
            "requested_symbols": len(symbols),
            "market_tail_eligible_symbols": len(eligible_dates),
            "source_completed_symbols": len(records_by_symbol),
            "validated_through_symbols": sum(
                1
                for symbol in required_symbols
                if validated_through_by_symbol.get(symbol, "")
                >= required_validation_through
            ),
            "required_symbols": len(required_symbols),
            "required_validation_through": required_validation_through,
            "validated_through": actual_validated_through(),
            "dataset_end_date": end_date,
            "deferred_tail_symbols": sorted(set(symbols) - required_symbols),
            "failed_symbols": failures,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "research_only": True,
            "execution_authority": False,
        }
    )
    if failures or any(
        validated_through_by_symbol.get(symbol, "") < required_validation_through
        for symbol in required_symbols
    ):
        payload["status"] = "failed"
    _write_json_atomic(output_path, payload)
    return payload


def _fetch_benchmark(
    start_date: str,
    end_date: str,
    *,
    get: Callable[..., Any] | None = None,
    timeout: tuple[float, float] = (5.0, 15.0),
):
    import pandas as pd
    import requests

    transport = get or requests.get
    params = {
        "secid": "1.000300",
        "fields1": "f1,f2,f3,f4,f5",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "klt": "101",
        "fqt": "0",
        "beg": start_date.replace("-", ""),
        "end": end_date.replace("-", ""),
    }
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = transport(
                "https://push2his.eastmoney.com/api/qt/stock/kline/get",
                params=params,
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            klines = data.get("klines") if isinstance(data, dict) else None
            if not isinstance(klines, list) or not klines:
                raise RuntimeError("eastmoney_benchmark_payload_invalid")
            frame = pd.DataFrame([str(item).split(",") for item in klines])
            if frame.shape[1] < 7:
                raise RuntimeError("eastmoney_benchmark_row_invalid")
            frame = frame.iloc[:, :7]
            frame.columns = [
                "date",
                "open",
                "close",
                "high",
                "low",
                "volume",
                "amount",
            ]
            for column in ("open", "close", "high", "low", "volume", "amount"):
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
            if frame[["date", "close"]].isna().any().any():
                raise RuntimeError("eastmoney_benchmark_row_invalid")
            return frame
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2**attempt)
    assert last_error is not None
    raise last_error


def _fetch_benchmark_tdx(start_date: str, end_date: str) -> list[dict[str, Any]]:
    """Fetch the governed local CSI 300 tail; caller merges it with prior history."""
    from quant.data.tdx_quant_source import fetch_klines_allow_price_jumps

    rows = fetch_klines_allow_price_jumps("sh000300", count=2000)
    start = str(start_date).replace("-", "")[:8]
    end = str(end_date).replace("-", "")[:8]
    return [
        dict(row)
        for row in rows
        if start <= str(row.get("date") or "").replace("-", "")[:8] <= end
    ]


def build_benchmark_reference(*, dataset_root: Path, output_path: Path) -> dict[str, Any]:
    eligible_dates = load_eligible_dates(dataset_root / "raw")
    manifest = _read_object(dataset_root / "manifest.json")
    completed_symbols = manifest.get("completed_symbols")
    if isinstance(completed_symbols, list) and completed_symbols:
        completed = {normalize_instrument(str(symbol)) for symbol in completed_symbols}
        eligible_dates = {
            symbol: dates for symbol, dates in eligible_dates.items() if symbol in completed
        }
    expected_dates = sorted({item for values in eligible_dates.values() for item in values})
    if not expected_dates:
        raise RuntimeError("six-year PIT raw data has no eligible trading dates")
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    prior = _read_object(output_path)
    fetch_error = ""
    try:
        frame = _fetch_benchmark(expected_dates[0], expected_dates[-1])
        rows = frame.to_dict(orient="records")
        source_fetch_status = "fresh"
        source_fetched_at = generated_at
    except Exception as exc:
        fetch_error = str(exc)[:300]
        cached_rows = prior.get("bars") if isinstance(prior.get("bars"), list) else []
        try:
            tdx_rows = _fetch_benchmark_tdx(expected_dates[0], expected_dates[-1])
        except Exception as tdx_exc:
            rows = cached_rows
            if not rows:
                raise exc
            source_fetch_status = "cache_revalidated"
            source_fetched_at = str(
                prior.get("source_fetched_at") or prior.get("generated_at") or ""
            )
            fetch_error = f"primary={fetch_error}; tdx={str(tdx_exc)[:180]}"[:300]
        else:
            merged = {
                str(row.get("date") or row.get("datetime") or "")[:10]: dict(row)
                for row in cached_rows
                if isinstance(row, dict)
            }
            for row in tdx_rows:
                merged[str(row.get("date") or "")[:10]] = dict(row)
            rows = [merged[key] for key in sorted(merged) if key]
            source_fetch_status = "tdx_quant_incremental"
            source_fetched_at = generated_at
    payload = build_benchmark_payload(
        rows, expected_dates=expected_dates, code="000300"
    )
    if source_fetch_status == "tdx_quant_incremental":
        payload["source"] = "akshare_index_zh_a_hist+tdx_quant"
    if source_fetch_status == "cache_revalidated" and payload.get("status") != "passed":
        raise RuntimeError(
            "benchmark source unavailable and cached bars fail current calendar coverage"
        )
    payload.update(
        {
            "dataset_version": manifest.get("dataset_version"),
            "generated_at": generated_at,
            "source_fetch_status": source_fetch_status,
            "source_fetched_at": source_fetched_at,
            "research_only": True,
            "execution_authority": False,
        }
    )
    if fetch_error:
        payload["source_fetch_error"] = fetch_error
    _write_json_atomic(output_path, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=("industry", "benchmark", "all"))
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--industry-output", type=Path, default=DEFAULT_INDUSTRY_PATH)
    parser.add_argument("--benchmark-output", type=Path, default=DEFAULT_BENCHMARK_PATH)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    statuses: list[str] = []
    if args.target in {"industry", "all"}:
        statuses.append(
            str(
                build_industry_reference(
                    dataset_root=args.dataset_root,
                    output_path=args.industry_output,
                    workers=args.workers,
                ).get("status")
            )
        )
    if args.target in {"benchmark", "all"}:
        statuses.append(
            str(
                build_benchmark_reference(
                    dataset_root=args.dataset_root, output_path=args.benchmark_output
                ).get("status")
            )
        )
    print(json.dumps({"statuses": statuses}, ensure_ascii=False))
    return 0 if statuses and all(status == "passed" for status in statuses) else 2


if __name__ == "__main__":
    raise SystemExit(main())

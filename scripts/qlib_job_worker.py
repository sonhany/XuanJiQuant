"""Detached Qlib job worker running inside .venv-qlib."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import traceback
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quant.qlib.jobs import JobManager, job_progress_callback
from quant.qlib.paths import resolve_data_path
from quant.qlib.registry import Registry, utc_now
from quant.data.cache import create_cache
from quant.data.snapshot import read_latest_passed_snapshot


Progress = Callable[[float, str], None]
SIX_YEAR_DATASET_ID = "a_share_6y_daily"
BENCHMARK_REFERENCE_PATH = ROOT / "data" / "research" / "benchmarks" / "000300.json"
INDUSTRY_REFERENCE_PATH = ROOT / "data" / "research" / "industry" / "pit_industry.json"
STAGES = (
    "collect",
    "quality",
    "export",
    "dataset",
    "train",
    "signal_record",
    "signal_analysis",
    "portfolio_analysis",
    "local_backtest",
    "register",
    "gate",
    "report",
)


def _collection_end_date(snapshot: dict[str, Any] | None) -> date:
    value = snapshot or {}
    if (
        value.get("quality_status") != "passed"
        or value.get("freshness_status") != "fresh"
    ):
        raise RuntimeError("daily_snapshot_not_ready_for_pit_collection")
    try:
        return date.fromisoformat(str(value.get("as_of") or "")[:10])
    except ValueError as exc:
        raise RuntimeError("daily_snapshot_date_invalid") from exc


def _initial_stage(kind: str) -> str:
    if kind.startswith("collect") or kind == "build_point_in_time":
        return "collect"
    if kind.startswith("quality"):
        return "quality"
    if kind.startswith("export"):
        return "export"
    if kind == "backtest_ashare":
        return "local_backtest"
    return "dataset"


def _raw_file_binding(path: Path, content: bytes) -> dict[str, Any]:
    return {
        "name": path.name,
        "sha256": hashlib.sha256(content).hexdigest(),
        "size": len(content),
    }


def _dataset_sha256(raw_files: list[dict[str, Any]]) -> str:
    encoded = json.dumps(
        raw_files,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _current_raw_file_bindings(raw_dir: Path) -> list[dict[str, Any]]:
    return [
        _raw_file_binding(path, path.read_bytes())
        for path in sorted(raw_dir.glob("*.json"))
    ]


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _ensure_directories() -> dict[str, Any]:
    names = [
        "raw",
        "raw/qlib_demo",
        "datasets",
        "qlib_bin",
        "models",
        "reports",
        "jobs",
        "cache",
    ]
    paths = []
    for name in names:
        path = resolve_data_path(*name.split("/"))
        path.mkdir(parents=True, exist_ok=True)
        paths.append(str(path))
    return {"status": "ready", "paths": paths}


def _recent_universe() -> list[str]:
    from quant.qlib.sources import load_universe

    cursor = date.today()
    for _ in range(20):
        if cursor.weekday() < 5:
            rows = load_universe(cursor.isoformat())
            instruments = [
                item["instrument"]
                for item in rows
                if item.get("trade_status", "1") != "0"
                and not item["instrument"][2:].startswith("920")
            ]
            if instruments:
                return instruments
        cursor -= timedelta(days=1)
    raise RuntimeError("unable to load a recent A-share universe")


def _register_collected_dataset(
    store: Registry,
    *,
    dataset_id: str,
    output: Path,
    start_date: str,
    end_date: str,
    requested: int,
    completed: int,
    failed: int,
) -> dict[str, Any]:
    row_count = 0
    latest_date = ""
    for path in sorted(Path(output).glob("*.json")):
        if path.name == "manifest.json":
            continue
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(rows, list):
            continue
        row_count += len(rows)
        for item in rows:
            value = str((item or {}).get("datetime") or "")[:10]
            if value > latest_date:
                latest_date = value
    coverage = completed / requested if requested else 0.0
    row = {
        "id": dataset_id,
        "kind": "tdxquant_daily",
        "status": "ready" if failed == 0 and completed == requested else "incomplete",
        "start_date": start_date,
        "end_date": end_date,
        "latest_date": latest_date,
        "instruments": completed,
        "rows": row_count,
        "coverage": coverage,
        "path": str(output),
        "metadata": {
            "requested": requested,
            "failed": failed,
            "primary_source": "tdxquant_unadjusted",
            "excluded_prefixes": ["920"],
        },
    }
    store.upsert_dataset(row)
    store.audit(
        "dataset_registered",
        "dataset",
        dataset_id,
        {
            "status": row["status"],
            "instruments": completed,
            "rows": row_count,
            "coverage": coverage,
        },
    )
    return row


def _collection_progress_message(processed: int, total: int) -> str:
    return f"已处理 {processed}/{total} 只股票"


def _bounded_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _bounded_float_env(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _six_year_collection_options() -> dict[str, int | float]:
    """为长时间可恢复采集提供有界运行参数。"""
    return {
        "workers": _bounded_int_env("XUANJI_QLIB_SIX_YEAR_WORKERS", 8, 1, 8),
        "failure_abort_after": _bounded_int_env("XUANJI_QLIB_FAILURE_ABORT_AFTER", 100, 1, 100_000),
        "failure_abort_ratio": _bounded_float_env("XUANJI_QLIB_FAILURE_ABORT_RATIO", 0.9, 0.0, 1.0),
    }


def _collect(years: int, progress: Progress) -> dict[str, Any]:
    from quant.qlib.collector import collect_daily_dataset, collect_six_year_dataset
    from quant.qlib.sources import fetch_daily_history_tracks_batch

    end = _collection_end_date(
        read_latest_passed_snapshot(create_cache(), "a_share_daily")
    )
    start = end - timedelta(days=365 * years + 15)
    dataset_id = f"a_share_{years}y_daily"
    dataset_root = resolve_data_path("datasets", dataset_id)
    if years == 6:
        manifest_path = dataset_root / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            symbol_starts = [
                str(row.get("start_date") or "")[:10]
                for row in (manifest.get("symbols") or {}).values()
                if isinstance(row, dict)
                and row.get("status") == "complete"
                and str(row.get("start_date") or "")[:10]
            ]
            stable_start = (
                max(symbol_starts)
                if symbol_starts
                else str(manifest.get("start_date") or "")[:10]
            )
            prior_start = date.fromisoformat(stable_start)
            if prior_start <= end:
                start = prior_start
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
    output = dataset_root / "raw"
    progress(0.03, "正在加载全市场股票列表")
    instruments = _recent_universe()
    progress(0.08, f"开始采集 {len(instruments)} 只股票")
    callback = lambda processed, total: progress(
            0.08 + 0.88 * processed / max(total, 1),
            _collection_progress_message(processed, total),
        )
    if years == 6:
        result = collect_six_year_dataset(
            instruments,
            start.isoformat(),
            end.isoformat(),
            dataset_root,
            track_prefetcher=fetch_daily_history_tracks_batch,
            checkpoint_every=25,
            progress_callback=callback,
            **_six_year_collection_options(),
        )
    else:
        result = collect_daily_dataset(
            instruments,
            start.isoformat(),
            end.isoformat(),
            output,
            data_version=dataset_id,
            checkpoint_every=25,
            progress_callback=callback,
        )
    dataset = _register_collected_dataset(
        Registry(resolve_data_path("qlib_meta.db")),
        dataset_id=dataset_id,
        output=output,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        requested=int(result.get("requested") or 0),
        completed=int(result.get("completed") or 0),
        failed=int(result.get("failed") or 0),
    )
    result["dataset_id"] = dataset_id
    result["path"] = str(output)
    result["dataset"] = dataset
    return result


def _export(dataset_id: str, progress: Progress) -> dict[str, Any]:
    from quant.qlib.exporter import (
        benchmark_reference_rows,
        write_qlib_bin_from_json_files,
    )

    raw_dir = resolve_data_path("datasets", dataset_id, "raw")
    if dataset_id == SIX_YEAR_DATASET_ID:
        manifest_path = raw_dir.parent / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeError("six-year completed-symbol manifest is unavailable") from exc
        completed_symbols = manifest.get("completed_symbols")
        if not isinstance(completed_symbols, list) or not completed_symbols:
            raise RuntimeError("six-year completed-symbol manifest is empty")
        files = [raw_dir / f"{str(symbol)}.json" for symbol in completed_symbols]
        missing = [path.name for path in files if not path.is_file()]
        if missing:
            raise RuntimeError(
                f"six-year completed-symbol files are missing: {', '.join(missing[:5])}"
            )
        files.sort()
    else:
        files = sorted(
            path for path in raw_dir.glob("*.json")
            if path.name != "manifest.json"
        )
    if not files:
        raise RuntimeError(f"dataset has no collected symbols: {dataset_id}")
    benchmark = ""
    if dataset_id == SIX_YEAR_DATASET_ID:
        quality_path = resolve_data_path("datasets", dataset_id, "quality_report.json")
        try:
            quality = json.loads(quality_path.read_text(encoding="utf-8"))
            reference = json.loads(BENCHMARK_REFERENCE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeError("six-year benchmark reference is unavailable") from exc
        benchmark_rows = benchmark_reference_rows(
            reference,
            expected_dataset_version=str(quality.get("dataset_version") or ""),
        )
        benchmark_path = resolve_data_path(
            "datasets", dataset_id, "references", "SH000300.json"
        )
        _atomic_write_json(benchmark_path, benchmark_rows)
        files.append(benchmark_path)
        benchmark = "SH000300"
    progress(0.1, f"正在流式校验 {len(files)} 个股票文件")
    target = resolve_data_path("qlib_bin", dataset_id)
    result = write_qlib_bin_from_json_files(
        files,
        target,
        universe_exclusions={benchmark} if benchmark else None,
        progress=lambda index, total: (
            progress(0.4 + 0.5 * index / max(total, 1), f"已导出 {index}/{total}")
            if index % 100 == 0 or index == total
            else None
        ),
    )
    result["dataset_id"] = dataset_id
    result["benchmark"] = benchmark
    return result


def _build_f4_references(progress: Progress) -> dict[str, Any]:
    from scripts.build_f4_market_references import (
        build_benchmark_reference,
        build_industry_reference,
    )

    dataset_root = resolve_data_path("datasets", SIX_YEAR_DATASET_ID)
    try:
        manifest = json.loads(
            (dataset_root / "manifest.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError("six-year reference manifest is unavailable") from exc
    dataset_version = str(manifest.get("dataset_version") or "")
    if not dataset_version:
        raise RuntimeError("six-year reference manifest has no dataset version")
    progress(0.05, "开始更新历史行业归属")
    industry = build_industry_reference(
        dataset_root=dataset_root,
        output_path=INDUSTRY_REFERENCE_PATH,
        workers=max(1, min(8, int(os.environ.get("XUANJI_F4_REFERENCE_WORKERS", "4")))),
    )
    progress(0.80, "开始更新沪深300基准")
    benchmark = build_benchmark_reference(
        dataset_root=dataset_root,
        output_path=BENCHMARK_REFERENCE_PATH,
    )
    complete = all(
        item.get("status") == "passed"
        and str(item.get("dataset_version") or "") == dataset_version
        and item.get("research_only") is True
        and item.get("execution_authority") is False
        for item in (industry, benchmark)
    )
    progress(1.0, "历史行业与基准参考检查完成")
    return {
        "status": "passed" if complete else "failed",
        "reason_code": "" if complete else "f4_reference_build_failed",
        "dataset_version": dataset_version,
        "industry": industry,
        "benchmark": benchmark,
        "research_only": True,
        "execution_authority": False,
    }


def _require_six_year_quality() -> dict[str, Any]:
    from quant.qlib.quality_gate import GATE_VERSION

    path = resolve_data_path(
        "datasets",
        SIX_YEAR_DATASET_ID,
        "quality_report.json",
    )
    if not path.exists():
        raise RuntimeError("dataset quality gate failed: quality report missing")
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("gate_version") != GATE_VERSION:
        raise RuntimeError("dataset quality gate failed: gate version mismatch")
    if not report.get("passed"):
        reasons = ", ".join(report.get("reason_codes") or ["unknown"])
        raise RuntimeError(f"dataset quality gate failed: {reasons}")
    manifest_path = path.parent / "manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists()
        else {}
    )
    manifest_version = str(manifest.get("dataset_version") or "")
    if not manifest_version:
        manifest_version = (
            f"daily-pit-{manifest.get('start_date')}-{manifest.get('end_date')}"
        )
    if report.get("dataset_version") != manifest_version:
        raise RuntimeError("dataset quality gate failed: dataset version mismatch")
    if (
        not manifest_path.exists()
        or hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        != report.get("manifest_hash")
    ):
        raise RuntimeError("dataset quality gate failed: manifest hash mismatch")
    raw_files = _current_raw_file_bindings(path.parent / "raw")
    if (
        raw_files != report.get("raw_files")
        or _dataset_sha256(raw_files) != report.get("dataset_sha256")
    ):
        raise RuntimeError("dataset quality gate failed: raw dataset binding mismatch")
    records = Registry(resolve_data_path("qlib_meta.db")).list_quality_reports()
    registered = next(
        (
            item
            for item in records
            if item.get("id") == report.get("report_id")
            and item.get("dataset_id") == SIX_YEAR_DATASET_ID
            and item.get("dataset_version") == report.get("dataset_version")
            and item.get("gate_version") == report.get("gate_version")
        ),
        None,
    )
    if (
        registered is None
        or not registered.get("passed")
        or registered.get("report") != report
    ):
        raise RuntimeError("dataset quality gate failed: registry record mismatch")
    return report


def _quality_six_years(progress: Progress) -> dict[str, Any]:
    from quant.qlib.quality_gate import (
        calculate_lifecycle_coverage,
        check_dataset_quality,
    )

    root = resolve_data_path("datasets", SIX_YEAR_DATASET_ID)
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        raise RuntimeError("six-year dataset manifest is missing")
    manifest_bytes = manifest_path.read_bytes()
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    files = sorted((root / "raw").glob("*.json"))
    dates: set[str] = set()
    latest_by_symbol: dict[str, str] = {}
    observed_by_symbol: dict[str, set[str]] = {}
    duplicate_rows = 0
    invalid_ohlc = 0
    non_positive_factors = 0
    unknown_st_samples = 0
    invalid_lifecycle_samples = 0
    raw_files: list[dict[str, Any]] = []
    for index, path in enumerate(files, start=1):
        content = path.read_bytes()
        raw_files.append(_raw_file_binding(path, content))
        rows = json.loads(content.decode("utf-8"))
        observed_by_symbol[path.stem] = set()
        seen: set[str] = set()
        for row in rows:
            trade_date = str(row.get("datetime") or "")[:10]
            if trade_date in seen:
                duplicate_rows += 1
            seen.add(trade_date)
            observed_by_symbol[path.stem].add(trade_date)
            dates.add(trade_date)
            latest_by_symbol[path.stem] = max(
                latest_by_symbol.get(path.stem, ""),
                trade_date,
            )
            try:
                open_, high, low, close = (
                    float(row.get("open") or 0),
                    float(row.get("high") or 0),
                    float(row.get("low") or 0),
                    float(row.get("close") or 0),
                )
                if (
                    min(open_, high, low, close) <= 0
                    or high < max(open_, close, low)
                    or low > min(open_, close, high)
                ):
                    invalid_ohlc += 1
                if float(row.get("factor") or 0) <= 0:
                    non_positive_factors += 1
            except (TypeError, ValueError):
                invalid_ohlc += 1
            if int(row.get("st_unknown") or 0) and int(row.get("tradable") or 0):
                unknown_st_samples += 1
            if (
                (not int(row.get("listed", 1)) or int(row.get("delisted") or 0))
                and int(row.get("tradable") or 0)
            ):
                invalid_lifecycle_samples += 1
        if index % 250 == 0:
            progress(
                0.1 + 0.8 * index / max(len(files), 1),
                f"已检查 {index}/{len(files)}",
            )
    latest = max(dates) if dates else ""
    lifecycle_by_symbol: dict[str, dict[str, str]] = {}
    manifest_symbols = manifest.get("symbols") or {}
    if isinstance(manifest_symbols, dict):
        for symbol, detail in manifest_symbols.items():
            if isinstance(detail, dict):
                lifecycle_by_symbol[str(symbol)] = {
                    "listing_date": str(detail.get("listing_date") or "")[:10],
                    "delisting_date": str(detail.get("delisting_date") or "")[:10],
                }
    reference_path = root / "point_in_time" / "reference_data.json"
    if reference_path.is_file():
        reference_payload = json.loads(reference_path.read_text(encoding="utf-8"))
        for detail in reference_payload.get("delistings") or []:
            symbol = str(detail.get("instrument") or "")
            if symbol:
                lifecycle_by_symbol[symbol] = {
                    "listing_date": str(detail.get("listing_date") or "")[:10],
                    "delisting_date": str(detail.get("delisting_date") or "")[:10],
                }
    calendar_path = resolve_data_path("provider", "calendars", "day.txt")
    if calendar_path.is_file():
        start_bound = str(manifest.get("start_date") or "")[:10]
        end_bound = str(manifest.get("end_date") or "")[:10]
        coverage_calendar = [
            line.strip()[:10]
            for line in calendar_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
            and (not start_bound or line.strip()[:10] >= start_bound)
            and (not end_bound or line.strip()[:10] <= end_bound)
        ]
    else:
        coverage_calendar = sorted(dates)
    lifecycle_coverage = calculate_lifecycle_coverage(
        trading_days=coverage_calendar,
        symbols=[
            {
                "instrument": symbol,
                **lifecycle_by_symbol.get(symbol, {}),
                "observed_dates": sorted(observed_dates),
            }
            for symbol, observed_dates in observed_by_symbol.items()
        ],
    )
    reference_candidates = ("SH600000", "SZ000001", "SZ300750")
    reference_symbols = [
        symbol for symbol in reference_candidates if symbol in latest_by_symbol
    ]
    expected_latest_date = max(
        (latest_by_symbol[symbol] for symbol in reference_symbols),
        default="",
    )
    recent_symbols = [
        symbol
        for symbol in latest_by_symbol
        if (
            not lifecycle_by_symbol.get(symbol, {}).get("listing_date")
            or lifecycle_by_symbol[symbol]["listing_date"] <= latest
        )
        and (
            not lifecycle_by_symbol.get(symbol, {}).get("delisting_date")
            or lifecycle_by_symbol[symbol]["delisting_date"] >= latest
        )
    ]
    recent_coverage = (
        sum(latest_by_symbol[symbol] == latest for symbol in recent_symbols)
        / len(recent_symbols)
        if recent_symbols
        else 0.0
    )
    end_date = str(manifest.get("end_date") or "")
    dataset_version = str(manifest.get("dataset_version") or "")
    if not dataset_version:
        dataset_version = (
            f"daily-pit-{manifest.get('start_date')}-{manifest.get('end_date')}"
        )
    latest_matches = bool(
        expected_latest_date
        and end_date
        and 0
        <= (
            date.fromisoformat(end_date) - date.fromisoformat(expected_latest_date)
        ).days
        <= 7
    )
    report = check_dataset_quality(
        requested=int(manifest.get("requested") or 0),
        completed=len(latest_by_symbol),
        recent_coverage=recent_coverage,
        trading_days=len(dates),
        latest_date_matches=latest_matches,
        duplicate_rows=duplicate_rows,
        invalid_ohlc=invalid_ohlc,
        non_positive_factors=non_positive_factors,
        unknown_st_samples=unknown_st_samples,
        invalid_lifecycle_samples=invalid_lifecycle_samples,
        dataset_version=dataset_version,
        coverage_override=min(
            float(lifecycle_coverage["coverage"]),
            len(latest_by_symbol) / max(int(manifest.get("requested") or 0), 1),
        ),
    )
    if not reference_symbols:
        report["passed"] = False
        report.setdefault("reason_codes", []).append("reference_symbols_missing")
    report.update(
        {
            "dataset_id": SIX_YEAR_DATASET_ID,
            "start_date": manifest.get("start_date"),
            "end_date": end_date,
            "data_latest_date": latest,
            "expected_latest_date": expected_latest_date,
            "reference_symbols": reference_symbols,
            "recent_eligible_symbols": len(recent_symbols),
            "checked_at": date.today().isoformat(),
            "manifest_hash": manifest_hash,
            "raw_files": raw_files,
            "lifecycle_coverage": lifecycle_coverage,
            "dataset_sha256": _dataset_sha256(raw_files),
        }
    )
    path = root / "quality_report.json"
    _atomic_write_json(path, report)
    Registry(resolve_data_path("qlib_meta.db")).upsert_quality_report(
        {
            "id": report["report_id"],
            "dataset_id": SIX_YEAR_DATASET_ID,
            "dataset_version": report["dataset_version"],
            "gate_version": report["gate_version"],
            "passed": report["passed"],
            "report": report,
        }
    )
    progress(1.0, "六年数据质量门禁检查完成")
    return {**report, "path": str(path)}


def _train_regime(progress: Progress) -> dict[str, Any]:
    from scripts.adaptive_regime import train_latest_regime

    return train_latest_regime(progress)


def dispatch_job(kind: str, params: dict[str, Any], progress: Progress) -> dict[str, Any]:
    if kind == "setup":
        return _ensure_directories()
    if kind == "collect_one_year":
        return _collect(1, progress)
    if kind == "collect_six_years":
        return _collect(6, progress)
    if kind == "build_point_in_time":
        return _collect(6, progress)
    if kind == "quality_six_years":
        return _quality_six_years(progress)
    if kind == "build_f4_references":
        _require_six_year_quality()
        return _build_f4_references(progress)
    if kind == "export_six_years":
        _require_six_year_quality()
        return _export(SIX_YEAR_DATASET_ID, progress)
    if kind == "export":
        return _export(str(params.get("dataset_id") or "a_share_1y_daily"), progress)
    if kind in {"train_smoke", "train_one_year"}:
        from qlib_train import run_preset

        preset = "official-demo" if kind == "train_smoke" else "one-year"
        return run_preset(preset, dataset_id=params.get("dataset_id"), progress=progress)
    if kind == "train_walk_forward":
        _require_six_year_quality()
        from qlib_train import run_preset

        return run_preset(
            "six-year-walk-forward",
            dataset_id=SIX_YEAR_DATASET_ID,
            progress=progress,
        )
    if kind == "train_regime":
        _require_six_year_quality()
        return _train_regime(progress)
    if kind == "workflow_baseline":
        _require_six_year_quality()
        from qlib_train import run_preset

        return run_preset(
            "one-year",
            dataset_id=SIX_YEAR_DATASET_ID,
            progress=progress,
        )
    if kind == "workflow_monthly_walk_forward":
        _require_six_year_quality()
        from qlib_train import run_preset

        return run_preset(
            "six-year-walk-forward",
            dataset_id=SIX_YEAR_DATASET_ID,
            progress=progress,
        )
    if kind == "workflow_quarterly_matrix":
        _require_six_year_quality()
        from qlib_train import run_quarterly_matrix

        return run_quarterly_matrix(progress=progress)
    if kind == "backtest_ashare":
        from qlib_train import run_ashare_for_workflow

        return run_ashare_for_workflow(
            str(params.get("workflow_run_id") or ""),
            progress=progress,
        )
    raise ValueError(f"unsupported Qlib job kind: {kind}")


def run_job(job_id: str) -> dict[str, Any]:
    store = Registry(resolve_data_path("qlib_meta.db"))
    manager = JobManager(store)
    job = store.get_job(job_id)
    if job is None:
        raise KeyError(job_id)
    manager.transition(job_id, "running", message="任务已启动", pid=os.getpid())

    run_token = f"run_{uuid.uuid4().hex}"
    initial_stage = _initial_stage(str(job["kind"]))
    store.update_job(
        job_id,
        stage=initial_stage,
        heartbeat_at=utc_now(),
        run_token=run_token,
        updated_at=utc_now(),
    )
    persist_progress = job_progress_callback(store, job_id, run_token)

    def progress(
        value: float,
        stage_or_message: str,
        message: str | None = None,
    ) -> None:
        if message is None:
            current = store.get_job(job_id) or {}
            resolved_stage = str(current.get("stage") or initial_stage)
            resolved_message = str(stage_or_message)
        else:
            resolved_stage = str(stage_or_message)
            resolved_message = str(message)
        if resolved_stage not in STAGES:
            raise ValueError(f"unsupported Qlib job stage: {resolved_stage}")
        persist_progress(value, resolved_stage, resolved_message)
        print(f"[{value:.1%}] [{resolved_stage}] {resolved_message}", flush=True)

    try:
        result = dispatch_job(job["kind"], job.get("params") or {}, progress)
        manager.transition(job_id, "succeeded", message="任务完成", result=result)
        store.update_job(
            job_id,
            stage="report",
            heartbeat_at=utc_now(),
            run_token=run_token,
            updated_at=utc_now(),
        )
        store.audit("job_succeeded", "job", job_id, {"kind": job["kind"]})
        return result
    except Exception as exc:
        detail = {"error": str(exc), "traceback": traceback.format_exc()[-8000:]}
        manager.transition(job_id, "failed", message=str(exc)[:500], result=detail)
        store.update_job(
            job_id,
            heartbeat_at=utc_now(),
            run_token=run_token,
            updated_at=utc_now(),
        )
        store.audit("job_failed", "job", job_id, {"kind": job["kind"], "error": str(exc)[:500]})
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()
    result = run_job(args.job_id)
    print(json.dumps(result, ensure_ascii=False, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

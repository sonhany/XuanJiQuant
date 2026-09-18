from __future__ import annotations

import json
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable

from .failures import classify_failure
from .normalizer import normalize_daily_bars
from .point_in_time import build_daily_mask
from .sources import (
    fetch_akshare_reference_data,
    fetch_daily_history,
    fetch_daily_history_tracks,
    normalize_instrument,
)


Fetcher = Callable[[str, str, str], list[dict]]
ProgressCallback = Callable[[int, int], None]
TrackFetcher = Callable[[str, str, str], dict[str, Any]]
TrackPrefetcher = Callable[
    [list[str], str, str], dict[str, dict[str, Any]]
]
Sleep = Callable[[float], None]

SIX_YEAR_SOURCE_SCHEMA_VERSION = "qlib_source_v1"
SIX_YEAR_ADJUSTMENT_SCHEMA_VERSION = "qlib_adjustment_v1"
SIX_YEAR_MIN_SYMBOL_COVERAGE = 0.98


def _is_supported_a_share(instrument: str) -> bool:
    code = normalize_instrument(instrument)[2:]
    return bool(
        len(code) == 6
        and code.isdigit()
        and not code.startswith(("200", "900", "920"))
    )


def _read_manifest(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json_atomic(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    temp.replace(path)


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return payload if isinstance(payload, list) else []


def _merge_records_by_datetime(
    old_rows: list[dict[str, Any]],
    new_rows: list[dict[str, Any]],
    *,
    data_version: str = "",
    minimum_date: str = "",
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in [*old_rows, *new_rows]:
        trade_date = str(row.get("datetime") or "")[:10]
        if not trade_date:
            continue
        merged[trade_date] = dict(row)
    result = [
        merged[key]
        for key in sorted(merged)
        if not minimum_date or key >= minimum_date
    ]
    if data_version:
        for row in result:
            row["data_version"] = data_version
    return result


def _failure_payload(exc: BaseException, attempts: int) -> dict[str, Any]:
    detail = classify_failure(exc)
    return {
        **detail.as_dict(),
        "attempts": attempts,
        "last_failed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def _run_with_retry(
    operation: Callable[[], Any],
    *,
    sleep: Sleep,
    max_attempts: int = 3,
) -> tuple[bool, Any, dict[str, Any] | None]:
    attempts_limit = max(1, int(max_attempts))
    for attempts in range(1, attempts_limit + 1):
        try:
            return True, operation(), None
        except Exception as exc:
            detail = classify_failure(exc)
            if not detail.retryable or attempts >= attempts_limit:
                return False, None, _failure_payload(exc, attempts)
            sleep(2 ** (attempts - 1))
    raise AssertionError("retry loop exhausted unexpectedly")


def _frame_records(frame) -> list[dict[str, Any]]:
    copy = frame.copy()
    copy["datetime"] = copy["datetime"].dt.strftime("%Y-%m-%d")
    return copy.to_dict(orient="records")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _symbol_artifact_paths(output_dir: Path, instrument: str) -> dict[str, Path]:
    root = Path(output_dir)
    symbol = normalize_instrument(instrument)
    return {
        "raw": root / "raw" / f"{symbol}.json",
        "adjusted": root / "adjusted" / f"{symbol}.json",
        "daily_mask": root
        / "point_in_time"
        / "daily_masks"
        / f"{symbol}.json",
    }


def _symbol_artifact_hashes(output_dir: Path, instrument: str) -> dict[str, str]:
    return {
        name: _sha256_file(path)
        for name, path in _symbol_artifact_paths(output_dir, instrument).items()
    }


def _artifact_bundle_hash(hashes: dict[str, str]) -> str:
    encoded = json.dumps(
        hashes,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _last_passed_raw_bindings(
    output_dir: Path,
) -> tuple[dict[str, dict[str, Any]], str, str]:
    path = Path(output_dir) / "quality_report.json"
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}, "", ""
    if report.get("passed") is not True:
        return {}, "", ""
    version = str(report.get("dataset_version") or "")
    prior_start = str(report.get("start_date") or "")[:10]
    prior_end = str(report.get("end_date") or "")[:10]
    if version.startswith("daily-pit-") and len(version) >= 31:
        prior_start = prior_start or version[10:20]
        prior_end = prior_end or version[21:31]
    bindings = {}
    for item in report.get("raw_files") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        sha256 = str(item.get("sha256") or "").lower()
        if name.endswith(".json") and len(sha256) == 64:
            bindings[Path(name).stem] = {
                "sha256": sha256,
                "size": int(item.get("size") or 0),
            }
    return bindings, prior_start, prior_end


def _raw_binding_matches(
    output_dir: Path,
    instrument: str,
    binding: dict[str, Any] | None,
) -> bool:
    if not binding:
        return False
    path = _symbol_artifact_paths(Path(output_dir), instrument)["raw"]
    try:
        return (
            path.stat().st_size == int(binding.get("size") or -1)
            and _sha256_file(path) == str(binding.get("sha256") or "")
        )
    except OSError:
        return False


def _retarget_terminal_symbol_artifacts(
    output_dir: Path,
    instrument: str,
    *,
    entry: dict[str, Any],
    start_date: str,
    end_date: str,
    data_version: str,
    lifecycle: dict[str, Any],
) -> dict[str, Any]:
    """Rebind verified post-delisting history without requesting impossible bars."""
    root = Path(output_dir)
    symbol = normalize_instrument(instrument)
    paths = _symbol_artifact_paths(root, symbol)
    payloads: dict[str, list[dict[str, Any]]] = {}
    date_sets: dict[str, set[str]] = {}
    for name, path in paths.items():
        rows = _read_json_list(path)
        filtered = []
        for row in rows:
            trade_date = str(row.get("datetime") or "")[:10]
            if trade_date and start_date <= trade_date <= end_date:
                item = dict(row)
                if name in {"raw", "adjusted"}:
                    item["data_version"] = data_version
                filtered.append(item)
        payloads[name] = filtered
        date_sets[name] = {
            str(row.get("datetime") or "")[:10] for row in filtered
        }
    if not payloads["raw"] or len(set(map(frozenset, date_sets.values()))) != 1:
        raise ValueError("terminal symbol artifacts are incomplete or misaligned")

    staged: list[tuple[Path, Path]] = []
    try:
        for name, target in paths.items():
            pending = target.with_suffix(target.suffix + ".pending")
            pending.write_text(
                json.dumps(payloads[name], ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            staged.append((pending, target))
        for pending, target in staged:
            pending.replace(target)
    finally:
        for pending, _ in staged:
            if pending.exists():
                pending.unlink()

    artifact_hashes = _symbol_artifact_hashes(root, symbol)
    result = dict(entry)
    result.update(
        {
            "status": "complete",
            "symbol": symbol,
            "raw_rows": len(payloads["raw"]),
            "adjusted_rows": len(payloads["adjusted"]),
            "mask_rows": len(payloads["daily_mask"]),
            "artifact_hashes": artifact_hashes,
            "artifact_sha256": _artifact_bundle_hash(artifact_hashes),
            "source_schema_version": SIX_YEAR_SOURCE_SCHEMA_VERSION,
            "adjustment_schema_version": SIX_YEAR_ADJUSTMENT_SCHEMA_VERSION,
            "start_date": start_date,
            "end_date": end_date,
            "listing_date": str(lifecycle.get("listing_date") or ""),
            "delisting_date": str(lifecycle.get("delisting_date") or ""),
            "terminal_history_reused": True,
            "completed_at": datetime.now()
            .astimezone()
            .isoformat(timespec="seconds"),
        }
    )
    return result


def _recover_orphaned_target_artifacts(
    output_dir: Path,
    instrument: str,
    *,
    entry: dict[str, Any],
    start_date: str,
    end_date: str,
    data_version: str,
    lifecycle: dict[str, Any],
) -> dict[str, Any] | None:
    """Recover a fully written target bundle whose manifest checkpoint lagged."""
    root = Path(output_dir)
    symbol = normalize_instrument(instrument)
    paths = _symbol_artifact_paths(root, symbol)
    if any(path.with_suffix(path.suffix + ".pending").exists() for path in paths.values()):
        return None
    payloads = {name: _read_json_list(path) for name, path in paths.items()}
    if not all(payloads.values()):
        return None
    date_sets = {
        name: {str(row.get("datetime") or "")[:10] for row in rows}
        for name, rows in payloads.items()
    }
    if len(set(map(frozenset, date_sets.values()))) != 1:
        return None
    dates = date_sets["raw"]
    if not dates or min(dates) < start_date or max(dates) > end_date:
        return None
    for name in ("raw", "adjusted"):
        if any(str(row.get("data_version") or "") != data_version for row in payloads[name]):
            return None
    try:
        artifact_hashes = _symbol_artifact_hashes(root, symbol)
    except OSError:
        return None
    result = dict(entry)
    result.update(
        {
            "status": "complete",
            "symbol": symbol,
            "raw_rows": len(payloads["raw"]),
            "adjusted_rows": len(payloads["adjusted"]),
            "mask_rows": len(payloads["daily_mask"]),
            "artifact_hashes": artifact_hashes,
            "artifact_sha256": _artifact_bundle_hash(artifact_hashes),
            "source_schema_version": SIX_YEAR_SOURCE_SCHEMA_VERSION,
            "adjustment_schema_version": SIX_YEAR_ADJUSTMENT_SCHEMA_VERSION,
            "start_date": start_date,
            "end_date": end_date,
            "listing_date": str(lifecycle.get("listing_date") or ""),
            "delisting_date": str(lifecycle.get("delisting_date") or ""),
            "orphaned_target_recovered": True,
            "completed_at": datetime.now()
            .astimezone()
            .isoformat(timespec="seconds"),
        }
    )
    return result


def symbol_artifacts_complete(
    output_dir: Path,
    instrument: str,
    expected: dict[str, Any] | None = None,
) -> bool:
    paths = _symbol_artifact_paths(output_dir, instrument)
    if not all(path.is_file() for path in paths.values()):
        return False
    if not expected:
        return True
    expected_hashes = expected.get("artifact_hashes")
    expected_bundle = str(expected.get("artifact_sha256") or "")
    if not isinstance(expected_hashes, dict) or len(expected_bundle) != 64:
        return False
    try:
        actual_hashes = _symbol_artifact_hashes(output_dir, instrument)
    except OSError:
        return False
    return (
        actual_hashes == expected_hashes
        and _artifact_bundle_hash(actual_hashes) == expected_bundle
    )


def collect_six_year_symbol(
    instrument: str,
    start_date: str,
    end_date: str,
    output_dir: Path,
    *,
    track_fetcher: TrackFetcher = fetch_daily_history_tracks,
    metadata: dict[str, Any] | None = None,
    data_version: str = "",
    merge_existing: bool = False,
    dataset_start_date: str = "",
) -> dict[str, Any]:
    symbol = normalize_instrument(instrument)
    root = Path(output_dir)
    status = dict(metadata or {})
    window_start_date = str(dataset_start_date or start_date)
    if track_fetcher is fetch_daily_history_tracks:
        tracks = track_fetcher(
            symbol,
            start_date,
            end_date,
            listing_date=str(status.get("listing_date") or ""),
        )
    else:
        tracks = track_fetcher(symbol, start_date, end_date)
    version = data_version or f"daily-pit-{start_date}-{end_date}"
    raw_frame = normalize_daily_bars(tracks.get("raw") or [], data_version=version)
    front_frame = normalize_daily_bars(tracks.get("front") or [], data_version=version)

    masks = []
    for row in raw_frame.to_dict(orient="records"):
        mask = build_daily_mask(
            symbol,
            row["datetime"].strftime("%Y-%m-%d"),
            listing_date=str(status.get("listing_date") or ""),
            delisting_date=str(status.get("delisting_date") or ""),
            st_intervals=status.get("st_intervals") or [],
            historical_st_uncertain=bool(status.get("historical_st_uncertain", True)),
            volume=float(row.get("volume") or 0),
            limit_up=bool(row.get("limit_up")),
            limit_down=bool(row.get("limit_down")),
        )
        masks.append(mask)

    mask_by_date = {row["datetime"]: row for row in masks}
    raw_records = _frame_records(raw_frame)
    for row in raw_records:
        mask = mask_by_date[row["datetime"]]
        row.update(
            {
                "tradable": int(mask["tradable"]),
                "is_st": int(mask["is_st"]),
                "st_unknown": int(mask["st_status"] == "unknown"),
                "listed": int(mask["listed"]),
                "delisted": int(mask["delisted"]),
                "paused": int(mask["paused"]),
                "limit_up": int(mask["limit_up"]),
                "limit_down": int(mask["limit_down"]),
            }
        )
    front_records = _frame_records(front_frame)

    if merge_existing:
        raw_records = _merge_records_by_datetime(
            _read_json_list(root / "raw" / f"{symbol}.json"),
            raw_records,
            data_version=version,
            minimum_date=window_start_date,
        )
        front_records = _merge_records_by_datetime(
            _read_json_list(root / "adjusted" / f"{symbol}.json"),
            front_records,
            data_version=version,
            minimum_date=window_start_date,
        )
        masks = _merge_records_by_datetime(
            _read_json_list(
                root / "point_in_time" / "daily_masks" / f"{symbol}.json"
            ),
            masks,
            minimum_date=window_start_date,
        )

    targets = {
        root / "raw" / f"{symbol}.json": raw_records,
        root / "adjusted" / f"{symbol}.json": front_records,
        root / "point_in_time" / "daily_masks" / f"{symbol}.json": masks,
    }
    staged: list[tuple[Path, Path]] = []
    try:
        for target, payload in targets.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            pending = target.with_suffix(target.suffix + ".pending")
            pending.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            staged.append((pending, target))
        for pending, target in staged:
            pending.replace(target)
    finally:
        for pending, _ in staged:
            if pending.exists():
                pending.unlink()

    factor_anomalies = sum(
        1 for row in raw_records if not bool(row.get("front_price_valid", True))
    )
    artifact_hashes = _symbol_artifact_hashes(root, symbol)
    return {
        "status": "complete",
        "symbol": symbol,
        "raw_rows": len(raw_records),
        "adjusted_rows": len(front_records),
        "mask_rows": len(masks),
        "sources": tracks.get("source_health", {}).get("sources", []),
        "factor_anomalies": factor_anomalies,
        "artifact_hashes": artifact_hashes,
        "artifact_sha256": _artifact_bundle_hash(artifact_hashes),
        "source_schema_version": SIX_YEAR_SOURCE_SCHEMA_VERSION,
        "adjustment_schema_version": SIX_YEAR_ADJUSTMENT_SCHEMA_VERSION,
        "start_date": window_start_date,
        "end_date": end_date,
        "listing_date": str(status.get("listing_date") or ""),
        "delisting_date": str(status.get("delisting_date") or ""),
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def collect_six_year_dataset(
    instruments: Iterable[str],
    start_date: str,
    end_date: str,
    output_dir: Path,
    *,
    track_fetcher: TrackFetcher = fetch_daily_history_tracks,
    track_prefetcher: TrackPrefetcher | None = None,
    reference_data: dict[str, Any] | None = None,
    refresh: bool = False,
    checkpoint_every: int = 25,
    progress_callback: ProgressCallback | None = None,
    failure_abort_after: int = 100,
    failure_abort_ratio: float = 0.9,
    workers: int = 4,
    sleep: Sleep = time.sleep,
) -> dict[str, Any]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    reference = reference_data if reference_data is not None else fetch_akshare_reference_data()
    _write_json_atomic(root / "point_in_time" / "reference_data.json", reference)

    current_listing_dates = {
        normalize_instrument(row.get("instrument") or ""): str(
            row.get("listing_date") or ""
        )[:10]
        for row in reference.get("current_universe") or []
    }
    requested = {
        normalize_instrument(code)
        for code in instruments
        if _is_supported_a_share(normalize_instrument(code))
        and (
            not current_listing_dates.get(normalize_instrument(code))
            or current_listing_dates[normalize_instrument(code)] <= end_date
        )
    }
    for row in reference.get("delistings") or []:
        symbol = normalize_instrument(row.get("instrument") or "")
        delisted = str(row.get("delisting_date") or "")
        listed = str(row.get("listing_date") or "")
        if (
            symbol[2:].isdigit()
            and _is_supported_a_share(symbol)
            and bool(delisted)
            and delisted >= start_date
            and (not listed or listed <= end_date)
        ):
            requested.add(symbol)
    symbols = sorted(requested)

    changes_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in reference.get("name_changes") or []:
        symbol = normalize_instrument(row.get("instrument") or "")
        changes_by_symbol.setdefault(symbol, []).append(row)
    lifecycle_by_symbol: dict[str, dict[str, Any]] = {}
    for row in reference.get("current_universe") or []:
        symbol = normalize_instrument(row.get("instrument") or "")
        if symbol[2:].isdigit():
            lifecycle_by_symbol[symbol] = {
                "listing_date": str(row.get("listing_date") or ""),
                "delisting_date": "",
            }
    for row in reference.get("delistings") or []:
        symbol = normalize_instrument(row.get("instrument") or "")
        existing = lifecycle_by_symbol.setdefault(symbol, {})
        if row.get("listing_date"):
            existing["listing_date"] = str(row.get("listing_date"))
        if row.get("delisting_date"):
            existing["delisting_date"] = str(row.get("delisting_date"))
    from .point_in_time import build_st_intervals

    manifest_path = root / "manifest.json"
    manifest = _read_manifest(manifest_path)
    entries = dict(manifest.get("symbols") or {})
    failed = dict(manifest.get("failed_symbols") or {})
    historical_failed = dict(manifest.get("historical_failed_symbols") or {})
    for symbol in list(failed):
        if symbol not in requested:
            historical_failed[symbol] = failed.pop(symbol)
    batch_statistics = list(manifest.get("batch_statistics") or [])
    written = 0
    skipped = 0
    terminal_history_reused = 0
    orphaned_target_recovered = 0
    batch_prefetch_requested = 0
    batch_prefetch_available = 0
    batch_prefetch_error = ""
    processed = 0
    attempted_this_run = 0
    failed_this_run = 0
    verified_complete: set[str] = set()
    aborted_early = False
    abort_reason = ""
    checkpoint_size = max(1, int(checkpoint_every))
    abort_after = max(1, int(failure_abort_after))
    abort_ratio = max(0.0, min(float(failure_abort_ratio), 1.0))
    worker_count = max(1, min(int(workers), 8))
    dataset_version = f"daily-pit-{start_date}-{end_date}"
    prior_identity_current = bool(
        not refresh
        and str(manifest.get("dataset_version") or "") == dataset_version
        and int(manifest.get("requested") or 0) == len(symbols)
        and set(entries) >= set(symbols)
    )
    passed_raw_bindings, passed_start_date, passed_end_date = (
        _last_passed_raw_bindings(root)
    )
    def entry_is_current(entry: dict[str, Any], artifacts_complete: bool) -> bool:
        return bool(
            entry.get("status") == "complete"
            and artifacts_complete
            and str(entry.get("start_date") or "") == start_date
            and str(entry.get("end_date") or "") == end_date
            and entry.get("source_schema_version") == SIX_YEAR_SOURCE_SCHEMA_VERSION
            and entry.get("adjustment_schema_version")
            == SIX_YEAR_ADJUSTMENT_SCHEMA_VERSION
        )

    current_entry_cache: dict[str, bool] = {}
    if prior_identity_current:
        for symbol in symbols:
            entry = dict(entries.get(symbol) or {})
            reusable = entry_is_current(
                entry,
                symbol_artifacts_complete(root, symbol, entry),
            )
            current_entry_cache[symbol] = reusable
            if reusable:
                verified_complete.add(symbol)

    def entry_can_increment(entry: dict[str, Any], artifacts_complete: bool) -> bool:
        prior_start = str(entry.get("start_date") or "")
        prior_end = str(entry.get("end_date") or "")
        return bool(
            not refresh
            and entry.get("status") == "complete"
            and artifacts_complete
            and prior_start
            and prior_start <= start_date
            and prior_end
            and prior_end <= end_date
            and (prior_start != start_date or prior_end != end_date)
            and entry.get("source_schema_version") == SIX_YEAR_SOURCE_SCHEMA_VERSION
            and entry.get("adjustment_schema_version")
            == SIX_YEAR_ADJUSTMENT_SCHEMA_VERSION
        )

    prefetched_tracks: dict[str, dict[str, Any]] = {}
    prefetch_attempted_symbols: set[str] = set()
    if track_prefetcher is not None and entries:
        prefetch_symbols = []
        failed_prefetch_symbols = []
        for symbol in symbols:
            entry = dict(entries.get(symbol) or {})
            lifecycle = lifecycle_by_symbol.get(symbol) or {}
            delisting_date = str(lifecycle.get("delisting_date") or "")[:10]
            prior_start = str(entry.get("start_date") or "")[:10]
            prior_end = str(entry.get("end_date") or "")[:10]
            if (
                entry.get("status") == "complete"
                and prior_start
                and prior_start <= start_date
                and prior_end
                and prior_end < end_date
                and (not delisting_date or delisting_date >= end_date)
                and entry.get("source_schema_version")
                == SIX_YEAR_SOURCE_SCHEMA_VERSION
                and entry.get("adjustment_schema_version")
                == SIX_YEAR_ADJUSTMENT_SCHEMA_VERSION
            ):
                prefetch_symbols.append(symbol)
            elif (
                (entry.get("status") == "failed" or symbol in failed)
                and (not delisting_date or delisting_date >= end_date)
            ):
                failed_prefetch_symbols.append(symbol)
        batch_prefetch_requested = len(prefetch_symbols) + len(
            failed_prefetch_symbols
        )
        prefetch_attempted_symbols.update(prefetch_symbols)
        prefetch_attempted_symbols.update(failed_prefetch_symbols)
        if prefetch_symbols:
            prefetch_start = (
                date.fromisoformat(end_date) - timedelta(days=30)
            ).isoformat()
            try:
                prefetched_tracks = dict(
                    track_prefetcher(
                        prefetch_symbols,
                        prefetch_start,
                        end_date,
                    )
                    or {}
                )
                batch_prefetch_available = sum(
                    1 for symbol in prefetch_symbols if symbol in prefetched_tracks
                )
            except Exception as exc:
                batch_prefetch_error = str(exc)[:240]
                prefetched_tracks = {}
        if failed_prefetch_symbols:
            try:
                recovered_tracks = dict(
                    track_prefetcher(
                        failed_prefetch_symbols,
                        start_date,
                        end_date,
                    )
                    or {}
                )
                prefetched_tracks.update(recovered_tracks)
                batch_prefetch_available += sum(
                    1
                    for symbol in failed_prefetch_symbols
                    if symbol in recovered_tracks
                )
            except Exception as exc:
                detail = str(exc)[:240]
                batch_prefetch_error = "; ".join(
                    value for value in (batch_prefetch_error, detail) if value
                )[:240]

    def write_checkpoint() -> None:
        completed_symbols = sorted(verified_complete)
        symbol_coverage = len(completed_symbols) / len(symbols) if symbols else 0.0
        prior_universe_accounted = bool(
            prior_identity_current
            and set(symbols).issubset(verified_complete | set(failed))
        )
        collection_exhausted = bool(
            not aborted_early
            and (processed >= len(symbols) or prior_universe_accounted)
        )
        payload = {
                "dataset_version": dataset_version,
                "source_schema_version": SIX_YEAR_SOURCE_SCHEMA_VERSION,
                "adjustment_schema_version": SIX_YEAR_ADJUSTMENT_SCHEMA_VERSION,
                "start_date": start_date,
                "end_date": end_date,
                "requested": len(symbols),
                "processed": processed,
                "completed_symbols": completed_symbols,
                "failed_symbols": failed,
                "historical_failed_symbols": historical_failed,
                "symbols": entries,
                "batch_statistics": batch_statistics,
                "source_health": reference.get("source_health") or {},
                "aborted_early": aborted_early,
                "abort_reason": abort_reason,
                "current_run_attempted": attempted_this_run,
                "current_run_failed": failed_this_run,
                "terminal_history_reused": terminal_history_reused,
                "orphaned_target_recovered": orphaned_target_recovered,
                "batch_prefetch_requested": batch_prefetch_requested,
                "batch_prefetch_available": batch_prefetch_available,
                "batch_prefetch_error": batch_prefetch_error,
                "worker_count": worker_count,
                "collection_exhausted": collection_exhausted,
                "symbol_coverage": symbol_coverage,
                "status": (
                    "complete"
                    if collection_exhausted
                    and symbol_coverage >= SIX_YEAR_MIN_SYMBOL_COVERAGE
                    else "incomplete"
                ),
                "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        payload["manifest_content_sha256"] = hashlib.sha256(canonical).hexdigest()
        _write_json_atomic(manifest_path, payload)

    def prepare_symbol(symbol: str) -> Callable[[], tuple[bool, Any, dict[str, Any] | None]]:
            entry = dict(entries.get(symbol) or {})
            artifacts_complete = symbol_artifacts_complete(
                root,
                symbol,
                entry,
            )
            lifecycle = lifecycle_by_symbol.get(symbol) or {}
            changes = changes_by_symbol.get(symbol) or []
            delisting_date = str(lifecycle.get("delisting_date") or "")[:10]
            passed_raw_binding = passed_raw_bindings.get(symbol)
            recovered_from_passed_gate = _raw_binding_matches(
                root,
                symbol,
                passed_raw_binding,
            )
            prior_start = str(entry.get("start_date") or passed_start_date)[:10]
            prior_end = str(entry.get("end_date") or passed_end_date)[:10]
            orphaned_result = None
            if (
                entry.get("status") == "complete"
                and prior_start
                and prior_start <= start_date
                and prior_end
                and prior_end < end_date
                and entry.get("source_schema_version")
                == SIX_YEAR_SOURCE_SCHEMA_VERSION
                and entry.get("adjustment_schema_version")
                == SIX_YEAR_ADJUSTMENT_SCHEMA_VERSION
            ):
                orphaned_result = _recover_orphaned_target_artifacts(
                    root,
                    symbol,
                    entry=entry,
                    start_date=start_date,
                    end_date=end_date,
                    data_version=dataset_version,
                    lifecycle=lifecycle,
                )
            terminal_retarget = bool(
                (
                    (entry.get("status") == "complete" and artifacts_complete)
                    or recovered_from_passed_gate
                )
                and prior_start
                and prior_start <= start_date
                and prior_end
                and delisting_date
                and prior_end >= delisting_date
                and delisting_date < end_date
                and (
                    recovered_from_passed_gate
                    or (
                        entry.get("source_schema_version")
                        == SIX_YEAR_SOURCE_SCHEMA_VERSION
                        and entry.get("adjustment_schema_version")
                        == SIX_YEAR_ADJUSTMENT_SCHEMA_VERSION
                    )
                )
            )
            incremental = entry_can_increment(entry, artifacts_complete)
            prefetched = prefetched_tracks.get(symbol)
            known_failure = dict(failed.get(symbol) or entry.get("failure") or {})
            if (
                known_failure
                and not prefetched
                and orphaned_result is None
                and not terminal_retarget
            ):
                preserved = {
                    **known_failure,
                    "deferred_retry": True,
                    "deferred_reason": "full_window_batch_prefetch_unavailable",
                }
                return lambda: (False, None, preserved)
            if (
                incremental
                and symbol in prefetch_attempted_symbols
                and not prefetched
                and orphaned_result is None
                and not terminal_retarget
            ):
                deferred = {
                    "reason_code": "source_batch_prefetch_unavailable",
                    "retryable": True,
                    "message": "incremental batch prefetch returned no usable dual-track data",
                    "exception_type": "BatchPrefetchUnavailable",
                    "attempts": 0,
                    "last_failed_at": datetime.now()
                    .astimezone()
                    .isoformat(timespec="seconds"),
                    "deferred_retry": True,
                    "deferred_reason": "incremental_batch_prefetch_unavailable",
                }
                return lambda: (False, None, deferred)
            collect_start = start_date
            if incremental:
                existing_raw = _read_json_list(root / "raw" / f"{symbol}.json")
                latest = max(
                    (str(row.get("datetime") or "")[:10] for row in existing_raw),
                    default="",
                )
                if latest:
                    collect_start = max(
                        date.fromisoformat(start_date),
                        date.fromisoformat(latest) - timedelta(days=15),
                    ).isoformat()

            def collect_symbol() -> dict[str, Any]:
                if orphaned_result is not None:
                    return orphaned_result
                if terminal_retarget:
                    return _retarget_terminal_symbol_artifacts(
                        root,
                        symbol,
                        entry=entry,
                        start_date=start_date,
                        end_date=end_date,
                        data_version=dataset_version,
                        lifecycle=lifecycle,
                    )
                selected_fetcher = track_fetcher
                if prefetched:
                    def cached_fetcher(
                        _instrument: str,
                        requested_start: str,
                        requested_end: str,
                    ) -> dict[str, Any]:
                        sliced = {}
                        for key in ("raw", "front"):
                            sliced[key] = [
                                dict(row)
                                for row in prefetched.get(key) or []
                                if requested_start
                                <= str(row.get("datetime") or row.get("date") or "")[:10]
                                <= requested_end
                            ]
                        if not sliced["raw"] or not sliced["front"]:
                            sliced = {
                                key: [dict(row) for row in prefetched.get(key) or []]
                                for key in ("raw", "front")
                            }
                        sliced["source_health"] = dict(
                            prefetched.get("source_health") or {}
                        )
                        return sliced

                    selected_fetcher = cached_fetcher
                return collect_six_year_symbol(
                    symbol,
                    collect_start,
                    end_date,
                    root,
                    track_fetcher=selected_fetcher,
                    metadata={
                        "listing_date": lifecycle.get("listing_date") or "",
                        "delisting_date": lifecycle.get("delisting_date") or "",
                        "st_intervals": build_st_intervals(symbol, changes),
                        "historical_st_uncertain": bool(
                            (reference.get("source_health") or {}).get("errors")
                        ),
                    },
                    data_version=dataset_version,
                    merge_existing=incremental,
                    dataset_start_date=start_date,
                )

            return lambda: _run_with_retry(collect_symbol, sleep=sleep)

    cursor = 0
    while cursor < len(symbols):
        until_checkpoint = checkpoint_size - (processed % checkpoint_size)
        batch_size = min(worker_count, until_checkpoint, len(symbols) - cursor)
        batch = symbols[cursor : cursor + batch_size]
        cursor += batch_size
        pending: list[tuple[str, Callable[[], tuple[bool, Any, dict[str, Any] | None]]]] = []
        for symbol in batch:
            entry = dict(entries.get(symbol) or {})
            reusable = current_entry_cache.get(symbol)
            if reusable is None:
                reusable = entry_is_current(
                    entry,
                    symbol_artifacts_complete(root, symbol, entry),
                )
            if reusable:
                skipped += 1
                verified_complete.add(symbol)
            else:
                attempted_this_run += 1
                pending.append((symbol, prepare_symbol(symbol)))

        batch_results: dict[str, tuple[bool, Any, dict[str, Any] | None]] = {}
        if pending:
            with ThreadPoolExecutor(max_workers=min(worker_count, len(pending))) as pool:
                futures = {symbol: pool.submit(operation) for symbol, operation in pending}
                for symbol, _operation in pending:
                    batch_results[symbol] = futures[symbol].result()
        for symbol in batch:
            if symbol in batch_results:
                ok, result, failure = batch_results[symbol]
                if ok:
                    entries[symbol] = result
                    failed.pop(symbol, None)
                    verified_complete.add(symbol)
                    written += 1
                    if result.get("terminal_history_reused") is True:
                        terminal_history_reused += 1
                    if result.get("orphaned_target_recovered") is True:
                        orphaned_target_recovered += 1
                else:
                    verified_complete.discard(symbol)
                    failed_this_run += 1
                    failed[symbol] = failure
                    entries[symbol] = {"status": "failed", "failure": failure}
            processed += 1

        if processed % 250 == 0:
            batch_statistics.append(
                {
                    "processed": processed,
                    "requested": len(symbols),
                    "written": written,
                    "skipped": skipped,
                    "failed": len(failed),
                    "recorded_at": datetime.now()
                    .astimezone()
                    .isoformat(timespec="seconds"),
                }
            )
        if processed % checkpoint_size == 0 or processed == len(symbols):
            if (
                attempted_this_run >= abort_after
                and failed_this_run / attempted_this_run >= abort_ratio
            ):
                aborted_early = True
                abort_reason = "source_failure_ratio"
            write_checkpoint()
            if progress_callback:
                progress_callback(processed, len(symbols))
            if aborted_early:
                break

    completed = len(verified_complete)
    write_checkpoint()
    symbol_coverage = completed / len(symbols) if symbols else 0.0
    collection_exhausted = processed >= len(symbols) and not aborted_early
    return {
        "status": (
            "complete"
            if collection_exhausted
            and symbol_coverage >= SIX_YEAR_MIN_SYMBOL_COVERAGE
            else "incomplete"
        ),
        "requested": len(symbols),
        "processed": processed,
        "completed": completed,
        "written": written,
        "skipped": skipped,
        "terminal_history_reused": terminal_history_reused,
        "orphaned_target_recovered": orphaned_target_recovered,
        "batch_prefetch_requested": batch_prefetch_requested,
        "batch_prefetch_available": batch_prefetch_available,
        "batch_prefetch_error": batch_prefetch_error,
        "failed": len(failed),
        "aborted_early": aborted_early,
        "abort_reason": abort_reason,
        "manifest": str(manifest_path),
        "worker_count": worker_count,
        "collection_exhausted": collection_exhausted,
        "symbol_coverage": symbol_coverage,
    }


def collect_daily_dataset(
    instruments: Iterable[str],
    start_date: str,
    end_date: str,
    output_dir: Path,
    *,
    fetcher: Fetcher = fetch_daily_history,
    refresh: bool = False,
    data_version: str = "",
    checkpoint_every: int = 25,
    progress_callback: ProgressCallback | None = None,
    sleep: Sleep = time.sleep,
) -> dict:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    manifest = _read_manifest(manifest_path)
    version = data_version or f"daily-{start_date}-{end_date}"
    same_dataset_version = manifest.get("dataset_version") == version
    completed = (
        set(manifest.get("completed_symbols") or []) if same_dataset_version else set()
    )
    failed: dict[str, Any] = (
        dict(manifest.get("failed_symbols") or {}) if same_dataset_version else {}
    )
    requested = list(dict.fromkeys(normalize_instrument(code) for code in instruments))
    written = 0
    skipped = 0
    checkpoint_size = max(1, int(checkpoint_every))

    def write_checkpoint() -> None:
        state = {
            "dataset_version": version,
            "start_date": start_date,
            "end_date": end_date,
            "requested": len(requested),
            "completed_symbols": sorted(completed),
            "failed_symbols": failed,
            "status": "complete"
            if len(completed) == len(requested) and not failed
            else "incomplete",
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        _write_json_atomic(manifest_path, state)

    for index, instrument in enumerate(requested, start=1):
        target = output_dir / f"{instrument}.json"
        if not refresh and instrument in completed and target.exists():
            skipped += 1
        else:
            def collect_symbol() -> None:
                rows = fetcher(instrument, start_date, end_date)
                frame = normalize_daily_bars(rows, data_version=version)
                _write_json_atomic(
                    target,
                    frame.assign(datetime=frame["datetime"].dt.strftime("%Y-%m-%d")).to_dict(
                        orient="records"
                    ),
                )

            ok, _, failure = _run_with_retry(collect_symbol, sleep=sleep)
            if ok:
                completed.add(instrument)
                failed.pop(instrument, None)
                written += 1
            else:
                failed[instrument] = failure

        if index % checkpoint_size == 0 or index == len(requested):
            write_checkpoint()
            if progress_callback is not None:
                progress_callback(index, len(requested))

    return {
        "status": "complete"
        if len(completed) == len(requested) and not failed
        else "incomplete",
        "requested": len(requested),
        "completed": len(completed),
        "written": written,
        "skipped": skipped,
        "failed": len(failed),
        "manifest": str(manifest_path),
    }

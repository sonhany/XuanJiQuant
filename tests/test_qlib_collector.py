import hashlib
import json


def _daily_row(instrument, trade_date, close=10.0, source="unit"):
    return {
        "instrument": instrument,
        "datetime": trade_date,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 100,
        "amount": close * 100,
        "factor": 1.0,
        "source": source,
    }


def test_collector_resumes_completed_symbols(tmp_path):
    from quant.qlib.collector import collect_daily_dataset

    calls = []

    def fetcher(code, start_date, end_date):
        calls.append(code)
        return [
            {
                "instrument": code,
                "datetime": start_date,
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10,
                "volume": 100,
                "amount": 1000,
                "source": "unit",
            }
        ]

    first = collect_daily_dataset(
        ["SH600000", "SZ000001"],
        "2026-01-02",
        "2026-01-02",
        tmp_path,
        fetcher=fetcher,
    )
    second = collect_daily_dataset(
        ["SH600000", "SZ000001"],
        "2026-01-02",
        "2026-01-02",
        tmp_path,
        fetcher=fetcher,
    )

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert first["completed"] == 2
    assert second["skipped"] == 2
    assert calls == ["SH600000", "SZ000001"]
    assert manifest["status"] == "complete"


def test_collector_reports_progress_and_writes_final_checkpoint(tmp_path):
    from quant.qlib.collector import collect_daily_dataset

    progress = []

    def fetcher(code, start_date, end_date):
        return [
            {
                "instrument": code,
                "datetime": start_date,
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10,
                "volume": 100,
                "amount": 1000,
                "source": "unit",
            }
        ]

    result = collect_daily_dataset(
        ["SH600000", "SZ000001", "SZ300750"],
        "2026-01-02",
        "2026-01-02",
        tmp_path,
        fetcher=fetcher,
        checkpoint_every=2,
        progress_callback=lambda completed, total: progress.append((completed, total)),
    )

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert result["completed"] == 3
    assert progress == [(2, 3), (3, 3)]
    assert manifest["completed_symbols"] == ["SH600000", "SZ000001", "SZ300750"]


def test_collector_writes_raw_adjusted_and_pit_files(tmp_path):
    from quant.qlib.collector import collect_six_year_symbol

    def fake_tracks(instrument, start_date, end_date):
        raw = {
            "instrument": instrument,
            "datetime": start_date,
            "open": 10,
            "high": 11,
            "low": 9,
            "close": 10,
            "volume": 100,
            "amount": 1000,
            "factor": 0.8,
            "source": "unit_raw",
        }
        adjusted = dict(raw, open=8, high=8.8, low=7.2, close=8, source="unit_front")
        return {
            "raw": [raw],
            "front": [adjusted],
            "source_health": {"passed": True, "sources": ["unit"]},
        }

    metadata = {
        "listing_date": "2000-01-01",
        "delisting_date": "",
        "st_intervals": [],
        "historical_st_uncertain": False,
    }
    result = collect_six_year_symbol(
        "SH600000",
        "2026-01-02",
        "2026-01-02",
        tmp_path,
        track_fetcher=fake_tracks,
        metadata=metadata,
    )

    assert (tmp_path / "raw" / "SH600000.json").exists()
    assert (tmp_path / "adjusted" / "SH600000.json").exists()
    assert (
        tmp_path / "point_in_time" / "daily_masks" / "SH600000.json"
    ).exists()
    assert result["status"] == "complete"
    assert result["raw_rows"] == 1
    assert result["adjusted_rows"] == 1
    assert result["mask_rows"] == 1


def test_resume_requires_all_symbol_artifacts(tmp_path):
    from quant.qlib.collector import symbol_artifacts_complete

    raw = tmp_path / "raw"
    raw.mkdir(parents=True)
    (raw / "SH600000.json").write_text("[]", encoding="utf-8")

    assert symbol_artifacts_complete(tmp_path, "SH600000") is False


def test_collector_retries_network_failure_and_succeeds_on_third_attempt(tmp_path):
    from quant.qlib.collector import collect_daily_dataset

    attempts = []
    delays = []

    def fetcher(code, start_date, end_date):
        attempts.append(code)
        if len(attempts) < 3:
            raise TimeoutError("source timed out")
        return [_daily_row(code, start_date)]

    result = collect_daily_dataset(
        ["SH600000"],
        "2026-01-02",
        "2026-01-02",
        tmp_path,
        fetcher=fetcher,
        sleep=delays.append,
    )

    assert result["status"] == "complete"
    assert attempts == ["SH600000", "SH600000", "SH600000"]
    assert delays == [1, 2]


def test_collector_records_structured_nonretryable_failure(tmp_path):
    from quant.qlib.collector import collect_daily_dataset

    attempts = []

    def fetcher(code, start_date, end_date):
        attempts.append(code)
        raise ValueError("missing columns: volume")

    result = collect_daily_dataset(
        ["SH600000"],
        "2026-01-02",
        "2026-01-02",
        tmp_path,
        fetcher=fetcher,
        sleep=lambda _: None,
    )
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    failure = manifest["failed_symbols"]["SH600000"]

    assert result["status"] == "incomplete"
    assert attempts == ["SH600000"]
    assert failure["reason_code"] == "missing_columns"
    assert failure["retryable"] is False
    assert failure["attempts"] == 1
    assert failure["exception_type"] == "ValueError"
    assert failure["message"] == "missing columns: volume"
    assert failure["last_failed_at"]


def test_six_year_collector_skips_same_version_and_merges_trailing_update(tmp_path):
    from quant.qlib.collector import collect_six_year_dataset

    calls = []

    def track_fetcher(instrument, start_date, end_date):
        calls.append((instrument, start_date, end_date))
        raw = [
            _daily_row(instrument, start_date, source="unit_raw"),
            _daily_row(instrument, end_date, source="unit_raw"),
        ]
        front = [dict(row, source="unit_front") for row in raw]
        return {
            "raw": raw,
            "front": front,
            "source_health": {"passed": True, "sources": ["unit"]},
        }

    reference = {
        "name_changes": [],
        "delistings": [],
        "source_health": {"passed": True, "errors": []},
    }
    first = collect_six_year_dataset(
        ["SH600000"],
        "2026-01-01",
        "2026-01-20",
        tmp_path,
        track_fetcher=track_fetcher,
        reference_data=reference,
    )
    same = collect_six_year_dataset(
        ["SH600000"],
        "2026-01-01",
        "2026-01-20",
        tmp_path,
        track_fetcher=track_fetcher,
        reference_data=reference,
    )
    advanced = collect_six_year_dataset(
        ["SH600000"],
        "2026-01-01",
        "2026-02-01",
        tmp_path,
        track_fetcher=track_fetcher,
        reference_data=reference,
    )
    raw = json.loads(
        (tmp_path / "raw" / "SH600000.json").read_text(encoding="utf-8")
    )

    assert first["written"] == 1
    assert same["skipped"] == 1
    assert advanced["written"] == 1
    assert calls == [
        ("SH600000", "2026-01-01", "2026-01-20"),
        ("SH600000", "2026-01-05", "2026-02-01"),
    ]
    assert [row["datetime"] for row in raw] == [
        "2026-01-01",
        "2026-01-05",
        "2026-01-20",
        "2026-02-01",
    ]


def test_six_year_collector_incrementally_advances_a_sliding_window(tmp_path):
    from quant.qlib.collector import collect_six_year_dataset

    calls = []

    def track_fetcher(instrument, start_date, end_date):
        calls.append((instrument, start_date, end_date))
        raw = [
            _daily_row(instrument, start_date, source="unit_raw"),
            _daily_row(instrument, end_date, source="unit_raw"),
        ]
        return {
            "raw": raw,
            "front": [dict(row, source="unit_front") for row in raw],
            "source_health": {"passed": True, "sources": ["unit"]},
        }

    reference = {
        "name_changes": [],
        "delistings": [],
        "source_health": {"passed": True, "errors": []},
    }
    collect_six_year_dataset(
        ["SH600000"], "2026-01-01", "2026-01-20", tmp_path,
        track_fetcher=track_fetcher, reference_data=reference,
    )
    advanced = collect_six_year_dataset(
        ["SH600000"], "2026-01-05", "2026-02-01", tmp_path,
        track_fetcher=track_fetcher, reference_data=reference,
    )
    raw = json.loads((tmp_path / "raw" / "SH600000.json").read_text(encoding="utf-8"))

    assert advanced["written"] == 1
    assert calls[-1] == ("SH600000", "2026-01-05", "2026-02-01")
    assert [row["datetime"] for row in raw] == [
        "2026-01-05",
        "2026-01-20",
        "2026-02-01",
    ]


def test_six_year_collector_retargets_verified_terminal_history_without_fetching(tmp_path):
    from quant.qlib.collector import collect_six_year_dataset

    calls = []

    def track_fetcher(instrument, start_date, end_date):
        calls.append((instrument, start_date, end_date))
        raw = [
            _daily_row(instrument, "2026-01-01", source="unit_raw"),
            _daily_row(instrument, "2026-01-09", source="unit_raw"),
        ]
        return {
            "raw": raw,
            "front": [dict(row, source="unit_front") for row in raw],
            "source_health": {"passed": True, "sources": ["unit"]},
        }

    reference = {
        "name_changes": [],
        "delistings": [
            {
                "instrument": "SH600001",
                "listing_date": "2000-01-01",
                "delisting_date": "2026-01-10",
            }
        ],
        "source_health": {"passed": True, "errors": []},
    }
    first = collect_six_year_dataset(
        ["SH600001"],
        "2026-01-01",
        "2026-01-20",
        tmp_path,
        track_fetcher=track_fetcher,
        reference_data=reference,
    )
    advanced = collect_six_year_dataset(
        ["SH600001"],
        "2026-01-05",
        "2026-02-01",
        tmp_path,
        track_fetcher=track_fetcher,
        reference_data=reference,
    )
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    raw = json.loads(
        (tmp_path / "raw" / "SH600001.json").read_text(encoding="utf-8")
    )

    assert first["written"] == 1
    assert advanced["written"] == 1
    assert advanced["completed"] == 1
    assert advanced["failed"] == 0
    assert calls == [("SH600001", "2026-01-01", "2026-01-20")]
    assert [row["datetime"] for row in raw] == ["2026-01-09"]
    assert {row["data_version"] for row in raw} == {
        "daily-pit-2026-01-05-2026-02-01"
    }
    entry = manifest["symbols"]["SH600001"]
    assert entry["start_date"] == "2026-01-05"
    assert entry["end_date"] == "2026-02-01"
    assert entry["delisting_date"] == "2026-01-10"
    assert entry["terminal_history_reused"] is True
    assert len(entry["artifact_sha256"]) == 64


def test_six_year_collector_uses_bulk_prefetch_only_for_verified_incremental_entries(
    tmp_path,
):
    from quant.qlib.collector import collect_six_year_dataset

    individual_calls = []
    batch_calls = []

    def individual_fetcher(instrument, start_date, end_date):
        individual_calls.append((instrument, start_date, end_date))
        raw = [_daily_row(instrument, end_date, source="unit_initial")]
        return {
            "raw": raw,
            "front": [dict(row, source="unit_initial_front") for row in raw],
            "source_health": {"passed": True, "sources": ["unit"]},
        }

    reference = {
        "name_changes": [],
        "delistings": [],
        "source_health": {"passed": True, "errors": []},
    }
    instruments = ["SH600000", "SZ000001"]
    collect_six_year_dataset(
        instruments,
        "2026-01-01",
        "2026-01-20",
        tmp_path,
        track_fetcher=individual_fetcher,
        reference_data=reference,
    )

    def batch_prefetcher(requested, start_date, end_date):
        batch_calls.append((tuple(requested), start_date, end_date))
        return {
            instrument: {
                "raw": [_daily_row(instrument, end_date, source="unit_batch")],
                "front": [
                    _daily_row(instrument, end_date, source="unit_batch_front")
                ],
                "source_health": {
                    "passed": True,
                    "sources": ["unit_batch"],
                },
            }
            for instrument in requested
        }

    advanced = collect_six_year_dataset(
        instruments,
        "2026-01-01",
        "2026-02-01",
        tmp_path,
        track_fetcher=individual_fetcher,
        track_prefetcher=batch_prefetcher,
        reference_data=reference,
    )

    assert len(batch_calls) == 1
    assert batch_calls[0][0] == tuple(sorted(instruments))
    assert individual_calls == [
        ("SH600000", "2026-01-01", "2026-01-20"),
        ("SZ000001", "2026-01-01", "2026-01-20"),
    ]
    assert advanced["written"] == 2
    assert advanced["batch_prefetch_available"] == 2


def test_known_failed_symbol_uses_full_window_prefetch_and_never_blocks_on_individual_fallback(
    tmp_path,
):
    from quant.qlib.collector import collect_six_year_dataset

    instruments = ["SH600000", "SH601123"]

    def initial_fetcher(instrument, start_date, _end_date):
        if instrument == "SH601123":
            raise RuntimeError("known source failure")
        raw = [_daily_row(instrument, start_date, source="unit_initial")]
        return {
            "raw": raw,
            "front": [dict(row, source="unit_initial_front") for row in raw],
            "source_health": {"passed": True, "sources": ["unit"]},
        }

    reference = {
        "name_changes": [],
        "delistings": [],
        "source_health": {"passed": True, "errors": []},
    }
    first = collect_six_year_dataset(
        instruments,
        "2026-01-01",
        "2026-01-20",
        tmp_path,
        track_fetcher=initial_fetcher,
        reference_data=reference,
        sleep=lambda _: None,
    )
    assert first["failed"] == 1

    batch_calls = []
    individual_calls = []

    def batch_prefetcher(requested, start_date, end_date):
        batch_calls.append((tuple(requested), start_date, end_date))
        if tuple(requested) == ("SH600000",):
            raw = [_daily_row("SH600000", end_date, source="unit_batch")]
            return {
                "SH600000": {
                    "raw": raw,
                    "front": [dict(row, source="unit_batch_front") for row in raw],
                    "source_health": {"passed": True, "sources": ["unit_batch"]},
                }
            }
        return {}

    resumed = collect_six_year_dataset(
        instruments,
        "2026-01-01",
        "2026-02-01",
        tmp_path,
        track_fetcher=lambda *args: individual_calls.append(args)
        or (_ for _ in ()).throw(AssertionError("individual fallback must not run")),
        track_prefetcher=batch_prefetcher,
        reference_data=reference,
        sleep=lambda _: None,
    )

    assert batch_calls == [
        (("SH600000",), "2026-01-02", "2026-02-01"),
        (("SH601123",), "2026-01-01", "2026-02-01"),
    ]
    assert individual_calls == []
    assert resumed["completed"] == 1
    assert resumed["failed"] == 1


def test_incremental_symbol_without_batch_prefetch_never_uses_individual_fallback(
    tmp_path,
):
    from quant.qlib.collector import collect_six_year_dataset

    individual_calls = []

    def initial_fetcher(instrument, start_date, _end_date):
        individual_calls.append((instrument, start_date))
        raw = [_daily_row(instrument, start_date, source="unit_initial")]
        return {
            "raw": raw,
            "front": [dict(row, source="unit_initial_front") for row in raw],
            "source_health": {"passed": True, "sources": ["unit"]},
        }

    reference = {
        "name_changes": [],
        "delistings": [],
        "source_health": {"passed": True, "errors": []},
    }
    collect_six_year_dataset(
        ["SH600000"],
        "2026-01-01",
        "2026-01-20",
        tmp_path,
        track_fetcher=initial_fetcher,
        reference_data=reference,
    )
    individual_calls.clear()
    batch_calls = []

    def empty_batch_prefetch(requested, start_date, end_date):
        batch_calls.append((tuple(requested), start_date, end_date))
        return {}

    resumed = collect_six_year_dataset(
        ["SH600000"],
        "2026-01-01",
        "2026-02-01",
        tmp_path,
        track_fetcher=lambda *args: individual_calls.append(args)
        or (_ for _ in ()).throw(AssertionError("individual fallback must not run")),
        track_prefetcher=empty_batch_prefetch,
        reference_data=reference,
        sleep=lambda _: None,
    )

    assert batch_calls == [(('SH600000',), '2026-01-02', '2026-02-01')]
    assert individual_calls == []
    assert resumed["processed"] == 1
    assert resumed["completed"] == 0
    assert resumed["failed"] == 1
    failure = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))[
        "failed_symbols"
    ]["SH600000"]
    assert failure["reason_code"] == "source_batch_prefetch_unavailable"
    assert failure["deferred_retry"] is True


def test_same_version_checkpoint_keeps_previously_verified_completion_on_cancel(
    tmp_path,
):
    from quant.qlib.collector import collect_six_year_dataset

    def track_fetcher(instrument, start_date, end_date):
        raw = [_daily_row(instrument, end_date, source="unit")]
        return {
            "raw": raw,
            "front": [dict(row, source="unit_front") for row in raw],
            "source_health": {"passed": True, "sources": ["unit"]},
        }

    reference = {
        "name_changes": [],
        "delistings": [],
        "source_health": {"passed": True, "errors": []},
    }
    instruments = ["SH600000", "SZ000001"]
    collect_six_year_dataset(
        instruments,
        "2026-01-01",
        "2026-01-20",
        tmp_path,
        track_fetcher=track_fetcher,
        reference_data=reference,
        checkpoint_every=1,
        workers=1,
    )

    def cancel_after_first(processed, _total):
        if processed == 1:
            raise RuntimeError("cancelled")

    try:
        collect_six_year_dataset(
            instruments,
            "2026-01-01",
            "2026-01-20",
            tmp_path,
            track_fetcher=lambda *_args: (_ for _ in ()).throw(
                AssertionError("same-version artifacts must be reused")
            ),
            reference_data=reference,
            checkpoint_every=1,
            progress_callback=cancel_after_first,
            workers=1,
        )
    except RuntimeError as exc:
        assert str(exc) == "cancelled"
    else:
        raise AssertionError("progress callback must cancel the second collection")

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "complete"
    assert manifest["collection_exhausted"] is True
    assert manifest["completed_symbols"] == sorted(instruments)


def test_six_year_collector_recovers_aligned_target_version_after_checkpoint_crash(
    tmp_path,
):
    from quant.qlib.collector import (
        collect_six_year_dataset,
        collect_six_year_symbol,
    )

    calls = []

    def track_fetcher(instrument, start_date, end_date):
        calls.append((instrument, start_date, end_date))
        raw = [_daily_row(instrument, end_date, source="unit")]
        return {
            "raw": raw,
            "front": [dict(row, source="unit_front") for row in raw],
            "source_health": {"passed": True, "sources": ["unit"]},
        }

    reference = {
        "name_changes": [],
        "delistings": [],
        "source_health": {"passed": True, "errors": []},
    }
    collect_six_year_dataset(
        ["SH600000"],
        "2026-01-01",
        "2026-01-20",
        tmp_path,
        track_fetcher=track_fetcher,
        reference_data=reference,
    )
    collect_six_year_symbol(
        "SH600000",
        "2026-01-05",
        "2026-02-01",
        tmp_path,
        track_fetcher=track_fetcher,
        metadata={
            "listing_date": "2000-01-01",
            "delisting_date": "",
            "st_intervals": [],
            "historical_st_uncertain": False,
        },
        data_version="daily-pit-2026-01-05-2026-02-01",
        merge_existing=True,
        dataset_start_date="2026-01-05",
    )

    recovered = collect_six_year_dataset(
        ["SH600000"],
        "2026-01-05",
        "2026-02-01",
        tmp_path,
        track_fetcher=track_fetcher,
        reference_data=reference,
    )

    assert recovered["completed"] == 1
    assert recovered["orphaned_target_recovered"] == 1
    assert calls == [
        ("SH600000", "2026-01-01", "2026-01-20"),
        ("SH600000", "2026-01-05", "2026-02-01"),
    ]


def test_six_year_collector_recovers_terminal_history_from_last_passed_raw_binding(tmp_path):
    from quant.qlib.collector import collect_six_year_dataset

    calls = []

    def track_fetcher(instrument, start_date, end_date):
        calls.append((instrument, start_date, end_date))
        raw = [_daily_row(instrument, "2026-01-09", source="unit_raw")]
        return {
            "raw": raw,
            "front": [dict(row, source="unit_front") for row in raw],
            "source_health": {"passed": True, "sources": ["unit"]},
        }

    reference = {
        "name_changes": [],
        "delistings": [
            {
                "instrument": "SH600001",
                "listing_date": "2000-01-01",
                "delisting_date": "2026-01-10",
            }
        ],
        "source_health": {"passed": True, "errors": []},
    }
    collect_six_year_dataset(
        ["SH600001"],
        "2026-01-01",
        "2026-01-20",
        tmp_path,
        track_fetcher=track_fetcher,
        reference_data=reference,
    )
    raw_path = tmp_path / "raw" / "SH600001.json"
    (tmp_path / "quality_report.json").write_text(
        json.dumps(
            {
                "passed": True,
                "dataset_version": "daily-pit-2026-01-01-2026-01-20",
                "raw_files": [
                    {
                        "name": raw_path.name,
                        "size": raw_path.stat().st_size,
                        "sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.json"
    interrupted = json.loads(manifest_path.read_text(encoding="utf-8"))
    interrupted["symbols"]["SH600001"] = {
        "status": "failed",
        "failure": {"reason_code": "source_unavailable"},
    }
    manifest_path.write_text(json.dumps(interrupted), encoding="utf-8")

    advanced = collect_six_year_dataset(
        ["SH600001"],
        "2026-01-05",
        "2026-02-01",
        tmp_path,
        track_fetcher=track_fetcher,
        reference_data=reference,
    )

    assert advanced["completed"] == 1
    assert advanced["terminal_history_reused"] == 1
    assert calls == [("SH600001", "2026-01-01", "2026-01-20")]


def test_six_year_collector_resumes_mixed_checkpoint_by_entry_identity(tmp_path):
    from quant.qlib.collector import collect_six_year_dataset

    calls = []

    def track_fetcher(instrument, start_date, end_date):
        calls.append((instrument, start_date, end_date))
        raw = [
            _daily_row(instrument, start_date, source="unit_raw"),
            _daily_row(instrument, end_date, source="unit_raw"),
        ]
        return {
            "raw": raw,
            "front": [dict(row, source="unit_front") for row in raw],
            "source_health": {"passed": True, "sources": ["unit"]},
        }

    reference = {
        "name_changes": [],
        "delistings": [],
        "source_health": {"passed": True, "errors": []},
    }
    collect_six_year_dataset(
        ["SH600000"], "2026-01-01", "2026-01-20", tmp_path,
        track_fetcher=track_fetcher, reference_data=reference,
    )
    manifest_path = tmp_path / "manifest.json"
    interrupted = json.loads(manifest_path.read_text(encoding="utf-8"))
    interrupted.update(
        {
            "dataset_version": "daily-pit-2026-01-05-2026-02-01",
            "start_date": "2026-01-05",
            "end_date": "2026-02-01",
            "status": "incomplete",
        }
    )
    manifest_path.write_text(json.dumps(interrupted), encoding="utf-8")

    resumed = collect_six_year_dataset(
        ["SH600000"], "2026-01-05", "2026-02-01", tmp_path,
        track_fetcher=track_fetcher, reference_data=reference,
    )

    assert resumed["written"] == 1
    assert resumed["skipped"] == 0
    assert calls[-1] == ("SH600000", "2026-01-05", "2026-02-01")


def test_six_year_collector_aborts_when_current_run_is_failure_dominated(tmp_path):
    from quant.qlib.collector import collect_six_year_dataset

    calls = []

    def failing_track_fetcher(instrument, start_date, end_date):
        calls.append(instrument)
        raise ValueError("missing columns: front-adjusted track")

    reference = {
        "name_changes": [],
        "delistings": [],
        "source_health": {"passed": True, "errors": []},
    }
    instruments = [f"SH{600000 + index:06d}" for index in range(40)]

    result = collect_six_year_dataset(
        instruments,
        "2020-01-01",
        "2026-01-01",
        tmp_path,
        track_fetcher=failing_track_fetcher,
        reference_data=reference,
        checkpoint_every=5,
        failure_abort_after=10,
        failure_abort_ratio=0.8,
        sleep=lambda _: None,
    )
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

    assert 10 <= len(calls) <= 13
    assert result["status"] == "incomplete"
    assert result["processed"] == 10
    assert result["aborted_early"] is True
    assert result["abort_reason"] == "source_failure_ratio"
    assert manifest["aborted_early"] is True
    assert manifest["abort_reason"] == "source_failure_ratio"


def test_six_year_collector_bounds_workers_and_hashes_symbol_artifacts(tmp_path):
    from quant.qlib.collector import collect_six_year_dataset

    def track_fetcher(instrument, start_date, end_date):
        raw = [_daily_row(instrument, start_date, source="unit_raw")]
        return {
            "raw": raw,
            "front": [dict(row, source="unit_front") for row in raw],
            "source_health": {"passed": True, "sources": ["unit"]},
        }

    reference = {
        "name_changes": [],
        "delistings": [],
        "source_health": {"passed": True, "errors": []},
    }
    result = collect_six_year_dataset(
        ["SH600000", "SZ000001"],
        "2026-01-02",
        "2026-01-02",
        tmp_path,
        track_fetcher=track_fetcher,
        reference_data=reference,
        workers=99,
    )
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

    assert result["worker_count"] == 8
    assert manifest["worker_count"] == 8
    assert len(manifest["manifest_content_sha256"]) == 64
    for item in manifest["symbols"].values():
        assert len(item["artifact_sha256"]) == 64
        assert set(item["artifact_hashes"]) == {"raw", "adjusted", "daily_mask"}


def test_tampered_symbol_artifact_is_not_reused(tmp_path):
    from quant.qlib.collector import collect_six_year_dataset

    calls = []

    def track_fetcher(instrument, start_date, end_date):
        calls.append(instrument)
        raw = [_daily_row(instrument, start_date, source="unit_raw")]
        return {
            "raw": raw,
            "front": [dict(row, source="unit_front") for row in raw],
            "source_health": {"passed": True, "sources": ["unit"]},
        }

    reference = {
        "name_changes": [],
        "delistings": [],
        "source_health": {"passed": True, "errors": []},
    }
    kwargs = dict(
        instruments=["SH600000"],
        start_date="2026-01-02",
        end_date="2026-01-02",
        output_dir=tmp_path,
        track_fetcher=track_fetcher,
        reference_data=reference,
    )
    collect_six_year_dataset(**kwargs)
    (tmp_path / "raw" / "SH600000.json").write_text("[]", encoding="utf-8")
    repeated = collect_six_year_dataset(**kwargs)

    assert calls == ["SH600000", "SH600000"]
    assert repeated["written"] == 1


def test_resume_hashes_each_reusable_symbol_only_once_per_run(tmp_path, monkeypatch):
    import quant.qlib.collector as collector

    instruments = ["SH600000", "SH600001", "SZ000001", "SZ000002"]

    def track_fetcher(instrument, start_date, end_date):
        raw = [_daily_row(instrument, start_date, source="unit_raw")]
        return {
            "raw": raw,
            "front": [dict(row, source="unit_front") for row in raw],
            "source_health": {"passed": True, "sources": ["unit"]},
        }

    kwargs = dict(
        instruments=instruments,
        start_date="2026-01-02",
        end_date="2026-01-02",
        output_dir=tmp_path,
        track_fetcher=track_fetcher,
        reference_data={
            "name_changes": [],
            "delistings": [],
            "source_health": {"passed": True, "errors": []},
        },
        checkpoint_every=1,
    )
    collector.collect_six_year_dataset(**kwargs)
    original = collector.symbol_artifacts_complete
    calls = []

    def counted(*args, **kwargs):
        calls.append(args[1])
        return original(*args, **kwargs)

    monkeypatch.setattr(collector, "symbol_artifacts_complete", counted)
    repeated = collector.collect_six_year_dataset(**kwargs)

    assert repeated["skipped"] == len(instruments)
    assert calls == sorted(instruments)


def test_six_year_collector_does_not_add_unknown_date_delisting(tmp_path):
    from quant.qlib.collector import collect_six_year_dataset

    calls = []

    def track_fetcher(instrument, start_date, end_date):
        calls.append(instrument)
        raw = [_daily_row(instrument, start_date, source="unit_raw")]
        return {
            "raw": raw,
            "front": [dict(row, source="unit_front") for row in raw],
            "source_health": {"passed": True, "sources": ["unit"]},
        }

    reference = {
        "name_changes": [],
        "delistings": [
            {"instrument": "SH600001", "delisting_date": ""},
            {"instrument": "SH600002", "delisting_date": "2024-01-05"},
            {"instrument": "SZ200054", "delisting_date": "2020-08-28"},
        ],
        "source_health": {"passed": True, "errors": []},
    }
    result = collect_six_year_dataset(
        ["SH600000"],
        "2020-08-01",
        "2026-08-15",
        tmp_path,
        track_fetcher=track_fetcher,
        reference_data=reference,
    )

    assert result["requested"] == 2
    assert calls == ["SH600000", "SH600002"]


def test_six_year_collector_preserves_current_instrument_listing_date(tmp_path):
    from quant.qlib.collector import collect_six_year_dataset

    def track_fetcher(instrument, start_date, end_date):
        raw = [_daily_row(instrument, "2026-04-01", source="unit_raw")]
        return {
            "raw": raw,
            "front": [dict(row, source="unit_front") for row in raw],
            "source_health": {"passed": True, "sources": ["unit"]},
        }

    collect_six_year_dataset(
        ["SZ301707"],
        "2020-08-01",
        "2026-08-14",
        tmp_path,
        track_fetcher=track_fetcher,
        reference_data={
            "current_universe": [
                {"instrument": "SZ301707", "listing_date": "2026-04-01"}
            ],
            "name_changes": [],
            "delistings": [],
            "source_health": {"passed": True, "errors": []},
        },
    )
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["symbols"]["SZ301707"]["listing_date"] == "2026-04-01"


def test_six_year_collector_excludes_current_symbols_listed_after_cutoff(tmp_path):
    from quant.qlib.collector import collect_six_year_dataset

    calls = []

    def track_fetcher(instrument, start_date, end_date):
        calls.append(instrument)
        raw = [_daily_row(instrument, end_date, source="unit_raw")]
        return {
            "raw": raw,
            "front": [dict(row, source="unit_front") for row in raw],
            "source_health": {"passed": True, "sources": ["unit"]},
        }

    result = collect_six_year_dataset(
        ["SH600000", "SZ301999"],
        "2020-08-01",
        "2026-08-14",
        tmp_path,
        track_fetcher=track_fetcher,
        reference_data={
            "current_universe": [
                {"instrument": "SH600000", "listing_date": "1999-11-10"},
                {"instrument": "SZ301999", "listing_date": "2026-08-17"},
            ],
            "name_changes": [],
            "delistings": [],
            "source_health": {"passed": True, "errors": []},
        },
    )

    assert result["requested"] == 1
    assert calls == ["SH600000"]


def test_six_year_manifest_finalizes_after_exhaustive_98pct_collection(tmp_path):
    from quant.qlib.collector import collect_six_year_dataset

    instruments = [f"SH{600000 + index:06d}" for index in range(100)]

    def track_fetcher(instrument, start_date, end_date):
        if instrument == instruments[-1]:
            raise RuntimeError("permanent unit failure")
        raw = [_daily_row(instrument, start_date, source="unit_raw")]
        return {
            "raw": raw,
            "front": [dict(row, source="unit_front") for row in raw],
            "source_health": {"passed": True, "sources": ["unit"]},
        }

    result = collect_six_year_dataset(
        instruments,
        "2020-08-01",
        "2026-08-15",
        tmp_path,
        track_fetcher=track_fetcher,
        reference_data={
            "name_changes": [],
            "delistings": [],
            "source_health": {"passed": True, "errors": []},
        },
        checkpoint_every=25,
        failure_abort_after=1000,
        sleep=lambda _: None,
    )
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

    assert result["processed"] == 100
    assert result["completed"] == 99
    assert result["status"] == "complete"
    assert manifest["status"] == "complete"
    assert manifest["collection_exhausted"] is True
    assert len(manifest["failed_symbols"]) == 1


def test_six_year_manifest_separates_failures_outside_current_request(tmp_path):
    from quant.qlib.collector import collect_six_year_dataset

    def track_fetcher(instrument, start_date, end_date):
        if instrument == "SH600001":
            raise RuntimeError("historical unit failure")
        raw = [_daily_row(instrument, start_date, source="unit_raw")]
        return {
            "raw": raw,
            "front": [dict(row, source="unit_front") for row in raw],
            "source_health": {"passed": True, "sources": ["unit"]},
        }

    common = dict(
        start_date="2020-08-01",
        end_date="2026-08-14",
        output_dir=tmp_path,
        track_fetcher=track_fetcher,
        reference_data={
            "name_changes": [],
            "delistings": [],
            "source_health": {"passed": True, "errors": []},
        },
        failure_abort_after=100,
        sleep=lambda _: None,
    )
    collect_six_year_dataset(instruments=["SH600000", "SH600001"], **common)
    collect_six_year_dataset(instruments=["SH600000"], **common)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["failed_symbols"] == {}
    assert "SH600001" in manifest["historical_failed_symbols"]

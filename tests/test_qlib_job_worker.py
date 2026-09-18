from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "scripts" / "qlib_job_worker.py"


def _passed_quality(**kwargs):
    return {
        "passed": True,
        "reason_codes": [],
        "metrics": {},
        "report_id": "quality_unit_test",
        "dataset_version": kwargs["dataset_version"],
        "gate_version": "qlib_phase1_gate_v1",
        "thresholds": {},
    }


def load_worker():
    spec = importlib.util.spec_from_file_location("qlib_job_worker_contract", WORKER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_quality_dataset(root: Path) -> tuple[Path, Path]:
    dataset = root / "datasets" / "a_share_6y_daily"
    raw = dataset / "raw"
    raw.mkdir(parents=True)
    manifest = dataset / "manifest.json"
    manifest.write_bytes(
        b'{\n  "requested": 2, "start_date": "2020-07-20", '
        b'"end_date": "2026-07-20", '
        b'"dataset_version": "daily-pit-2020-07-20-2026-07-20"\n}\n'
    )
    for symbol, close in (("SH600000", 10.5), ("SZ000001", 12.5)):
        (raw / f"{symbol}.json").write_text(
            json.dumps(
                [
                    {
                        "datetime": "2026-07-20",
                        "open": close - 0.5,
                        "high": close + 0.5,
                        "low": close - 1,
                        "close": close,
                        "factor": 1,
                        "tradable": 1,
                        "listed": 1,
                    }
                ],
                sort_keys=True,
            ),
            encoding="utf-8",
        )
    return dataset, raw


def test_worker_rejects_unknown_job_kind():
    worker = load_worker()
    with pytest.raises(ValueError, match="unsupported Qlib job kind"):
        worker.dispatch_job("arbitrary_command", {}, lambda *_: None)


def test_collection_progress_message_does_not_claim_processed_symbols_were_collected():
    worker = load_worker()

    message = worker._collection_progress_message(450, 5500)

    assert message == "已处理 450/5500 只股票"
    assert "已采集" not in message


def test_setup_job_only_creates_fixed_warehouse_directories(tmp_path, monkeypatch):
    worker = load_worker()
    monkeypatch.setenv("QLIB_DATA_ROOT", str(tmp_path))
    result = worker.dispatch_job("setup", {}, lambda *_: None)
    assert result["status"] == "ready"
    assert (tmp_path / "raw").is_dir()
    assert (tmp_path / "models").is_dir()
    assert (tmp_path / "reports").is_dir()


def test_collected_dataset_is_registered_with_real_row_counts(tmp_path):
    from quant.qlib.registry import Registry

    worker = load_worker()
    raw = tmp_path / "datasets" / "a_share_1y_daily" / "raw"
    raw.mkdir(parents=True)
    (raw / "SH600000.json").write_text(
        json.dumps(
            [
                {"datetime": "2026-07-09"},
                {"datetime": "2026-07-10"},
            ]
        ),
        encoding="utf-8",
    )
    (raw / "SZ000001.json").write_text(
        json.dumps([{"datetime": "2026-07-10"}]),
        encoding="utf-8",
    )
    store = Registry(tmp_path / "qlib_meta.db")

    row = worker._register_collected_dataset(
        store,
        dataset_id="a_share_1y_daily",
        output=raw,
        start_date="2025-07-01",
        end_date="2026-07-12",
        requested=3,
        completed=2,
        failed=1,
    )

    assert row["rows"] == 3
    assert row["latest_date"] == "2026-07-10"
    assert row["coverage"] == pytest.approx(2 / 3)
    assert store.list_datasets()[0]["status"] == "incomplete"


def test_export_ignores_dataset_manifest(tmp_path, monkeypatch):
    from quant.qlib import exporter

    worker = load_worker()
    raw = tmp_path / "datasets" / "a_share_1y_daily" / "raw"
    raw.mkdir(parents=True)
    (raw / "manifest.json").write_text(
        json.dumps({"requested": 1, "completed_symbols": ["SH600000"]}),
        encoding="utf-8",
    )
    (raw / "SH600000.json").write_text(
        json.dumps(
            [
                {
                    "instrument": "SH600000",
                    "datetime": "2026-07-10",
                    "open": 9,
                    "high": 10,
                    "low": 8,
                    "close": 9.5,
                    "volume": 100,
                    "amount": 950,
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        worker,
        "resolve_data_path",
        lambda *parts: tmp_path.joinpath(*parts),
    )
    captured = {}

    def fake_write(files, target, *, progress=None, universe_exclusions=None):
        captured["files"] = [path.name for path in files]
        captured["target"] = target
        captured["universe_exclusions"] = universe_exclusions
        return {"instruments": 1}

    monkeypatch.setattr(exporter, "write_qlib_bin_from_json_files", fake_write)

    result = worker._export("a_share_1y_daily", lambda *_: None)

    assert captured["files"] == ["SH600000.json"]
    assert captured["universe_exclusions"] is None
    assert result["dataset_id"] == "a_share_1y_daily"


def test_six_year_export_requires_passed_quality_report(tmp_path, monkeypatch):
    worker = load_worker()
    monkeypatch.setattr(
        worker,
        "resolve_data_path",
        lambda *parts: tmp_path.joinpath(*parts),
    )

    with pytest.raises(RuntimeError, match="quality gate"):
        worker.dispatch_job("export_six_years", {}, lambda *_: None)


def test_six_year_export_includes_version_matched_csi300_reference(tmp_path, monkeypatch):
    from quant.qlib import exporter

    worker = load_worker()
    monkeypatch.setattr(worker, "resolve_data_path", lambda *parts: tmp_path.joinpath(*parts))
    raw = tmp_path / "datasets" / "a_share_6y_daily" / "raw"
    raw.mkdir(parents=True)
    (raw.parent / "manifest.json").write_text(
        json.dumps({"completed_symbols": ["SH600000"]}),
        encoding="utf-8",
    )
    (raw / "SH600000.json").write_text(
        json.dumps([{"instrument": "SH600000", "datetime": "2026-01-02", "close": 10}]),
        encoding="utf-8",
    )
    quality_path = tmp_path / "datasets" / "a_share_6y_daily" / "quality_report.json"
    quality_path.write_text(
        json.dumps({"status": "passed", "dataset_version": "daily-pit-v1"}),
        encoding="utf-8",
    )
    benchmark_path = tmp_path / "000300.json"
    benchmark_path.write_text(
        json.dumps(
            {
                "status": "passed",
                "code": "000300",
                "dataset_version": "daily-pit-v1",
                "research_only": True,
                "execution_authority": False,
                "bars": [
                    {
                        "date": "2026-01-02",
                        "open": 3990,
                        "high": 4050,
                        "low": 3980,
                        "close": 4000,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(worker, "BENCHMARK_REFERENCE_PATH", benchmark_path)
    captured = {}

    def fake_write(files, target, *, progress=None, universe_exclusions=None):
        captured["files"] = [path.name for path in files]
        captured["universe_exclusions"] = universe_exclusions
        return {"instruments": 2}

    monkeypatch.setattr(exporter, "write_qlib_bin_from_json_files", fake_write)

    result = worker._export("a_share_6y_daily", lambda *_: None)

    assert captured["files"] == ["SH600000.json", "SH000300.json"]
    assert captured["universe_exclusions"] == {"SH000300"}
    assert result["benchmark"] == "SH000300"


def test_six_year_export_uses_only_manifest_completed_symbols(tmp_path, monkeypatch):
    from quant.qlib import exporter

    worker = load_worker()
    monkeypatch.setattr(worker, "resolve_data_path", lambda *parts: tmp_path.joinpath(*parts))
    root = tmp_path / "datasets" / "a_share_6y_daily"
    raw = root / "raw"
    raw.mkdir(parents=True)
    (root / "manifest.json").write_text(
        json.dumps({"completed_symbols": ["SH600000"]}),
        encoding="utf-8",
    )
    for symbol in ("SH600000", "SZ300028"):
        (raw / f"{symbol}.json").write_text(
            json.dumps([{"instrument": symbol, "datetime": "2026-01-02", "close": 10}]),
            encoding="utf-8",
        )
    (root / "quality_report.json").write_text(
        json.dumps({"status": "passed", "dataset_version": "daily-pit-v1"}),
        encoding="utf-8",
    )
    benchmark_path = tmp_path / "000300.json"
    benchmark_path.write_text(
        json.dumps(
            {
                "status": "passed",
                "code": "000300",
                "dataset_version": "daily-pit-v1",
                "research_only": True,
                "execution_authority": False,
                    "bars": [{
                        "date": "2026-01-02",
                        "open": 3990,
                        "high": 4010,
                        "low": 3980,
                        "close": 4000,
                    }],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(worker, "BENCHMARK_REFERENCE_PATH", benchmark_path)
    captured = {}

    def fake_write(files, target, *, progress=None, universe_exclusions=None):
        captured["files"] = [path.name for path in files]
        return {"instruments": len(files)}

    monkeypatch.setattr(exporter, "write_qlib_bin_from_json_files", fake_write)

    worker._export("a_share_6y_daily", lambda *_: None)

    assert captured["files"] == ["SH600000.json", "SH000300.json"]


def test_reference_stage_requires_both_current_references(tmp_path, monkeypatch):
    from scripts import build_f4_market_references as reference_builder

    worker = load_worker()
    monkeypatch.setattr(worker, "resolve_data_path", lambda *parts: tmp_path.joinpath(*parts))
    root = tmp_path / "datasets" / "a_share_6y_daily"
    root.mkdir(parents=True)
    (root / "manifest.json").write_text(
        json.dumps({"dataset_version": "daily-pit-v1"}), encoding="utf-8"
    )
    monkeypatch.setattr(
        reference_builder,
        "build_industry_reference",
        lambda **_kwargs: {"status": "passed", "dataset_version": "daily-pit-v1"},
    )
    monkeypatch.setattr(
        reference_builder,
        "build_benchmark_reference",
        lambda **_kwargs: {"status": "passed", "dataset_version": "stale-v0"},
    )

    result = worker._build_f4_references(lambda *_: None)

    assert result["status"] == "failed"
    assert result["reason_code"] == "f4_reference_build_failed"
    assert result["research_only"] is True
    assert result["execution_authority"] is False


def test_six_year_quality_report_records_exact_manifest_file_hash(
    tmp_path,
    monkeypatch,
):
    from quant.qlib import quality_gate

    worker = load_worker()
    monkeypatch.setattr(
        worker,
        "resolve_data_path",
        lambda *parts: tmp_path.joinpath(*parts),
    )
    monkeypatch.setattr(
        quality_gate,
        "check_dataset_quality",
        _passed_quality,
    )
    root = tmp_path / "datasets" / "a_share_6y_daily"
    raw = root / "raw"
    raw.mkdir(parents=True)
    manifest_bytes = (
        b'{\n  "requested": 1, "start_date": "2020-07-20", '
        b'"end_date": "2026-07-20", '
        b'"dataset_version": "daily-pit-2020-07-20-2026-07-20"\n}\n'
    )
    manifest_path = root / "manifest.json"
    manifest_path.write_bytes(manifest_bytes)
    (raw / "SH600000.json").write_text(
        json.dumps(
            [
                {
                    "datetime": "2026-07-20",
                    "open": 10,
                    "high": 11,
                    "low": 9,
                    "close": 10.5,
                    "factor": 1,
                    "tradable": 1,
                    "listed": 1,
                }
            ]
        ),
        encoding="utf-8",
    )
    expected = hashlib.sha256(manifest_bytes).hexdigest()

    returned = worker._quality_six_years(lambda *_: None)
    persisted = json.loads((root / "quality_report.json").read_text(encoding="utf-8"))

    assert returned["manifest_hash"] == expected
    assert persisted["manifest_hash"] == expected
    assert len(expected) == 64


def test_six_year_quality_uses_requested_universe_not_only_observed_lifecycle(
    tmp_path,
    monkeypatch,
):
    worker = load_worker()
    monkeypatch.setattr(
        worker,
        "resolve_data_path",
        lambda *parts: tmp_path.joinpath(*parts),
    )
    root = tmp_path / "datasets" / "a_share_6y_daily"
    raw = root / "raw"
    raw.mkdir(parents=True)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "requested": 100,
                "status": "incomplete",
                "start_date": "2020-08-01",
                "end_date": "2026-08-15",
                "dataset_version": "daily-pit-test",
            }
        ),
        encoding="utf-8",
    )
    rows = [
        {
            "datetime": f"2026-01-{day:02d}",
            "open": 10,
            "high": 11,
            "low": 9,
            "close": 10,
            "factor": 1,
            "listed": 1,
            "tradable": 1,
        }
        for day in range(1, 29)
    ]
    (raw / "SH600000.json").write_text(json.dumps(rows), encoding="utf-8")

    report = worker._quality_six_years(lambda *_: None)

    assert report["metrics"]["coverage"] == 0.01
    assert "coverage_below_98pct" in report["reason_codes"]
    assert report["status"] == "failed"


def test_six_year_collection_options_are_environment_bounded(monkeypatch):
    worker = load_worker()
    monkeypatch.setenv("XUANJI_QLIB_SIX_YEAR_WORKERS", "99")
    monkeypatch.setenv("XUANJI_QLIB_FAILURE_ABORT_AFTER", "0")
    monkeypatch.setenv("XUANJI_QLIB_FAILURE_ABORT_RATIO", "2")

    assert worker._six_year_collection_options() == {
        "workers": 8,
        "failure_abort_after": 1,
        "failure_abort_ratio": 1.0,
    }


def test_six_year_worker_enables_tdxquant_bulk_prefetch(tmp_path, monkeypatch):
    from quant.qlib import collector, sources

    worker = load_worker()
    captured = {}
    monkeypatch.setattr(worker, "_recent_universe", lambda: ["SH600000"])
    monkeypatch.setattr(
        worker,
        "resolve_data_path",
        lambda *parts: tmp_path.joinpath(*parts),
    )
    monkeypatch.setattr(
        worker,
        "_register_collected_dataset",
        lambda *args, **kwargs: {"id": "unit"},
    )
    monkeypatch.setattr(
        worker,
        "read_latest_passed_snapshot",
        lambda *_args: {
            "as_of": "2026-08-28",
            "quality_status": "passed",
            "freshness_status": "fresh",
        },
    )

    def fake_collect(*args, **kwargs):
        captured.update(kwargs)
        return {
            "requested": 1,
            "completed": 1,
            "failed": 0,
            "status": "complete",
        }

    monkeypatch.setattr(collector, "collect_six_year_dataset", fake_collect)

    worker._collect(6, lambda *_: None)

    assert captured["track_prefetcher"] is sources.fetch_daily_history_tracks_batch


def test_collection_end_date_uses_latest_passed_daily_market_snapshot():
    worker = load_worker()

    result = worker._collection_end_date(
        {
            "as_of": "2026-08-28",
            "quality_status": "passed",
            "freshness_status": "fresh",
        }
    )

    assert result.isoformat() == "2026-08-28"


def test_six_year_collection_preserves_existing_pit_start_date(tmp_path, monkeypatch):
    from quant.qlib import collector

    worker = load_worker()
    dataset_root = tmp_path / "datasets" / "a_share_6y_daily"
    dataset_root.mkdir(parents=True)
    (dataset_root / "manifest.json").write_text(
        json.dumps(
            {
                "status": "incomplete",
                "start_date": "2020-08-14",
                "end_date": "2026-08-21",
                "dataset_version": "daily-pit-2020-08-14-2026-08-21",
                "symbols": {
                    "SH600000": {
                        "status": "complete",
                        "start_date": "2020-08-08",
                        "end_date": "2026-08-21",
                    },
                    "SH600001": {
                        "status": "complete",
                        "start_date": "2020-08-08",
                        "end_date": "2026-08-21",
                    },
                    "SH600002": {
                        "status": "complete",
                        "start_date": "2020-08-16",
                        "end_date": "2026-08-21",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    captured = {}
    monkeypatch.setattr(worker, "_recent_universe", lambda: ["SH600000"])
    monkeypatch.setattr(
        worker,
        "resolve_data_path",
        lambda *parts: tmp_path.joinpath(*parts),
    )
    monkeypatch.setattr(
        worker,
        "read_latest_passed_snapshot",
        lambda *_args: {
            "as_of": "2026-08-28",
            "quality_status": "passed",
            "freshness_status": "fresh",
        },
    )
    monkeypatch.setattr(worker, "_register_collected_dataset", lambda *args, **kwargs: {})

    def fake_collect(*args, **kwargs):
        captured["start_date"] = args[1]
        captured["end_date"] = args[2]
        return {"requested": 1, "completed": 1, "failed": 0, "status": "complete"}

    monkeypatch.setattr(collector, "collect_six_year_dataset", fake_collect)

    worker._collect(6, lambda *_args: None)

    assert captured == {"start_date": "2020-08-16", "end_date": "2026-08-28"}


def test_six_year_quality_report_binds_every_sorted_raw_file(
    tmp_path,
    monkeypatch,
):
    from quant.qlib import quality_gate

    worker = load_worker()
    dataset, raw = _seed_quality_dataset(tmp_path)
    monkeypatch.setattr(
        worker,
        "resolve_data_path",
        lambda *parts: tmp_path.joinpath(*parts),
    )
    monkeypatch.setattr(
        quality_gate,
        "check_dataset_quality",
        _passed_quality,
    )

    report = worker._quality_six_years(lambda *_: None)
    expected_files = [
        {
            "name": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": len(path.read_bytes()),
        }
        for path in sorted(raw.glob("*.json"))
    ]
    expected_dataset_hash = hashlib.sha256(
        json.dumps(
            expected_files,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    assert report["raw_files"] == expected_files
    assert report["dataset_sha256"] == expected_dataset_hash
    assert worker._require_six_year_quality()[
        "dataset_sha256"
    ] == expected_dataset_hash
    assert (dataset / "quality_report.json").exists()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda dataset, raw: (dataset / "manifest.json").write_bytes(
                (dataset / "manifest.json").read_bytes() + b" "
            ),
            "manifest hash mismatch",
        ),
        (
            lambda dataset, raw: (raw / "SH600000.json").write_bytes(
                (raw / "SH600000.json").read_bytes() + b" "
            ),
            "raw dataset binding mismatch",
        ),
        (
            lambda dataset, raw: (raw / "SZ300750.json").write_text(
                "[]",
                encoding="utf-8",
            ),
            "raw dataset binding mismatch",
        ),
        (
            lambda dataset, raw: (raw / "SZ000001.json").unlink(),
            "raw dataset binding mismatch",
        ),
    ],
)
def test_six_year_quality_gate_rejects_stale_or_changed_dataset_bytes(
    tmp_path,
    monkeypatch,
    mutation,
    message,
):
    from quant.qlib import quality_gate

    worker = load_worker()
    dataset, raw = _seed_quality_dataset(tmp_path)
    monkeypatch.setattr(
        worker,
        "resolve_data_path",
        lambda *parts: tmp_path.joinpath(*parts),
    )
    monkeypatch.setattr(
        quality_gate,
        "check_dataset_quality",
        _passed_quality,
    )
    worker._quality_six_years(lambda *_: None)
    mutation(dataset, raw)

    with pytest.raises(RuntimeError, match=message):
        worker._require_six_year_quality()


def test_quality_report_publication_uses_fsync_and_atomic_replace(
    tmp_path,
    monkeypatch,
):
    from quant.qlib import quality_gate

    worker = load_worker()
    dataset, _ = _seed_quality_dataset(tmp_path)
    monkeypatch.setattr(
        worker,
        "resolve_data_path",
        lambda *parts: tmp_path.joinpath(*parts),
    )
    monkeypatch.setattr(
        quality_gate,
        "check_dataset_quality",
        _passed_quality,
    )
    fsync_calls = []
    replace_destinations = []
    real_replace = worker.os.replace
    monkeypatch.setattr(
        worker.os,
        "fsync",
        lambda descriptor: fsync_calls.append(descriptor),
    )

    def capture_replace(source, destination):
        replace_destinations.append(Path(destination))
        return real_replace(source, destination)

    monkeypatch.setattr(worker.os, "replace", capture_replace)

    worker._quality_six_years(lambda *_: None)

    report_path = dataset / "quality_report.json"
    assert report_path in replace_destinations
    assert fsync_calls
    assert not list(dataset.glob(".quality_report.json.*.tmp"))


def test_six_year_quality_report_is_registered_and_uses_reference_symbols(
    tmp_path,
    monkeypatch,
):
    from quant.qlib import quality_gate
    from quant.qlib.registry import Registry

    worker = load_worker()
    _seed_quality_dataset(tmp_path)
    monkeypatch.setattr(
        worker,
        "resolve_data_path",
        lambda *parts: tmp_path.joinpath(*parts),
    )
    monkeypatch.setattr(quality_gate, "check_dataset_quality", _passed_quality)

    report = worker._quality_six_years(lambda *_: None)
    records = Registry(tmp_path / "qlib_meta.db").list_quality_reports()

    assert report["expected_latest_date"] == "2026-07-20"
    assert report["reference_symbols"] == ["SH600000", "SZ000001"]
    assert len(records) == 1
    assert records[0]["id"] == report["report_id"]
    assert records[0]["report"]["dataset_sha256"] == report["dataset_sha256"]


def test_six_year_recent_coverage_excludes_symbols_delisted_before_dataset_end(
    tmp_path,
    monkeypatch,
):
    from quant.qlib import quality_gate

    worker = load_worker()
    root = tmp_path / "datasets" / "a_share_6y_daily"
    raw = root / "raw"
    raw.mkdir(parents=True)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "requested": 2,
                "start_date": "2026-07-10",
                "end_date": "2026-07-20",
                "dataset_version": "daily-pit-lifecycle-test",
                "symbols": {
                    "SH600000": {"listing_date": "1999-11-10", "delisting_date": ""},
                    "SZ000005": {
                        "listing_date": "1990-12-10",
                        "delisting_date": "2026-07-10",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    common = {
        "open": 10,
        "high": 11,
        "low": 9,
        "close": 10,
        "factor": 1,
        "listed": 1,
        "tradable": 1,
    }
    (raw / "SH600000.json").write_text(
        json.dumps([{**common, "datetime": "2026-07-20"}]), encoding="utf-8"
    )
    (raw / "SZ000005.json").write_text(
        json.dumps([{**common, "datetime": "2026-07-10"}]), encoding="utf-8"
    )
    monkeypatch.setattr(
        worker,
        "resolve_data_path",
        lambda *parts: tmp_path.joinpath(*parts),
    )
    captured = {}

    def capture_quality(**kwargs):
        captured.update(kwargs)
        return _passed_quality(**kwargs)

    monkeypatch.setattr(quality_gate, "check_dataset_quality", capture_quality)

    worker._quality_six_years(lambda *_: None)

    assert captured["recent_coverage"] == 1.0


def test_six_year_quality_gate_fails_when_reference_symbols_are_missing(
    tmp_path,
    monkeypatch,
):
    from quant.qlib import quality_gate

    worker = load_worker()
    root = tmp_path / "datasets" / "a_share_6y_daily"
    raw = root / "raw"
    raw.mkdir(parents=True)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "requested": 1,
                "start_date": "2020-07-20",
                "end_date": "2026-07-20",
                "dataset_version": "daily-pit-test",
            }
        ),
        encoding="utf-8",
    )
    (raw / "SH601398.json").write_text(
        json.dumps(
            [
                {
                    "datetime": "2026-07-20",
                    "open": 5,
                    "high": 5,
                    "low": 5,
                    "close": 5,
                    "factor": 1,
                    "tradable": 1,
                    "listed": 1,
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        worker,
        "resolve_data_path",
        lambda *parts: tmp_path.joinpath(*parts),
    )
    monkeypatch.setattr(quality_gate, "check_dataset_quality", _passed_quality)

    report = worker._quality_six_years(lambda *_: None)

    assert report["passed"] is False
    assert "reference_symbols_missing" in report["reason_codes"]


def test_six_year_quality_gate_rejects_registry_report_mismatch(
    tmp_path,
    monkeypatch,
):
    from quant.qlib import quality_gate
    from quant.qlib.registry import Registry

    worker = load_worker()
    _seed_quality_dataset(tmp_path)
    monkeypatch.setattr(
        worker,
        "resolve_data_path",
        lambda *parts: tmp_path.joinpath(*parts),
    )
    monkeypatch.setattr(quality_gate, "check_dataset_quality", _passed_quality)
    report = worker._quality_six_years(lambda *_: None)
    Registry(tmp_path / "qlib_meta.db").upsert_quality_report(
        {
            "id": report["report_id"],
            "dataset_id": report["dataset_id"],
            "dataset_version": report["dataset_version"],
            "gate_version": report["gate_version"],
            "passed": True,
            "report": {**report, "dataset_sha256": "tampered"},
        }
    )

    with pytest.raises(RuntimeError, match="registry record mismatch"):
        worker._require_six_year_quality()

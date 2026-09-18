import hashlib
import importlib
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime

import pytest

from quant.adaptive.snapshot import load_research_snapshot, write_research_snapshot


_MISSING = object()


def _payload() -> dict:
    return {
        "schema_version": "adaptive-research.v1",
        "generated_at": "2026-07-20T18:30:00+08:00",
        "dataset": {
            "id": "a_share_6y_daily",
            "latest_date": "2026-07-20",
            "quality_passed": True,
            "manifest_hash": "a" * 64,
        },
        "models": [],
    }


def _write_raw_snapshot(path, payload):
    clean = deepcopy(payload)
    clean.pop("snapshot_sha256", None)
    encoded = json.dumps(
        clean,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    raw = deepcopy(clean)
    raw["snapshot_sha256"] = hashlib.sha256(encoded).hexdigest()
    path.write_text(
        json.dumps(
            raw,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ),
        encoding="utf-8",
    )


def _assert_write_and_load_reject(tmp_path, payload, match):
    target = tmp_path / "invalid-write.json"
    with pytest.raises(ValueError, match=match):
        write_research_snapshot(payload, target)
    assert not target.exists()

    raw_target = tmp_path / "invalid-load.json"
    _write_raw_snapshot(raw_target, payload)
    with pytest.raises(ValueError, match=match):
        load_research_snapshot(raw_target)


def test_snapshot_round_trip_uses_hash_and_schema(tmp_path):
    latest = tmp_path / "adaptive-research-latest.json"

    written = write_research_snapshot(_payload(), latest)
    loaded = load_research_snapshot(latest)

    assert loaded["snapshot_sha256"] == written["snapshot_sha256"]
    assert loaded["dataset"]["quality_passed"] is True


def test_snapshot_rejects_tampering(tmp_path):
    latest = tmp_path / "adaptive-research-latest.json"
    write_research_snapshot(_payload(), latest)
    raw = json.loads(latest.read_text(encoding="utf-8"))
    raw["generated_at"] = "2026-07-20T19:30:00+08:00"
    latest.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="snapshot hash mismatch"):
        load_research_snapshot(latest)


def test_snapshot_rejects_failed_quality_without_replacing_target(tmp_path):
    latest = tmp_path / "adaptive-research-latest.json"
    write_research_snapshot(_payload(), latest)
    previous = latest.read_bytes()
    failed = _payload()
    failed["dataset"]["quality_passed"] = False

    with pytest.raises(ValueError, match="quality_passed"):
        write_research_snapshot(failed, latest)

    assert latest.read_bytes() == previous


def test_snapshot_rejects_bad_schema(tmp_path):
    latest = tmp_path / "adaptive-research-latest.json"
    payload = _payload()
    payload["schema_version"] = "adaptive-research.v0"

    with pytest.raises(ValueError, match="invalid schema_version"):
        write_research_snapshot(payload, latest)

    assert not latest.exists()


def test_snapshot_atomically_replaces_and_cleans_temp_file(tmp_path):
    latest = tmp_path / "adaptive-research-latest.json"
    first = _payload()
    write_research_snapshot(first, latest)
    second = _payload()
    second["dataset"]["latest_date"] = "2026-07-21"

    write_research_snapshot(second, latest)

    assert load_research_snapshot(latest)["dataset"]["latest_date"] == "2026-07-21"
    assert list(tmp_path.glob("*.tmp")) == []


def test_snapshot_concurrent_writers_use_owned_temp_files(tmp_path, monkeypatch):
    import quant.adaptive.snapshot as snapshot

    latest = tmp_path / "adaptive-research-latest.json"
    payloads = [_payload(), _payload()]
    payloads[0]["dataset"]["latest_date"] = "2026-07-20"
    payloads[1]["dataset"]["latest_date"] = "2026-07-21"
    barrier = threading.Barrier(2)
    real_replace = snapshot.os.replace
    real_fsync = snapshot.os.fsync
    replace_sources = []
    sources_lock = threading.Lock()

    def synchronized_fsync(fd):
        real_fsync(fd)
        barrier.wait(timeout=5)

    def recorded_replace(source, target):
        with sources_lock:
            replace_sources.append(source)
        real_replace(source, target)

    monkeypatch.setattr(snapshot.os, "fsync", synchronized_fsync)
    monkeypatch.setattr(snapshot.os, "replace", recorded_replace)
    with ThreadPoolExecutor(max_workers=2) as executor:
        written = list(executor.map(lambda item: write_research_snapshot(item, latest), payloads))

    loaded = load_research_snapshot(latest)
    returned_hashes = {item["snapshot_sha256"] for item in written}
    assert len(written) == 2
    assert len({str(path) for path in replace_sources}) == 2
    assert loaded["snapshot_sha256"] in returned_hashes
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize(
    "missing_field",
    ["generated_at", "dataset", "models"],
)
def test_snapshot_rejects_incomplete_top_level_schema(tmp_path, missing_field):
    payload = _payload()
    payload.pop(missing_field)

    _assert_write_and_load_reject(tmp_path, payload, missing_field)


@pytest.mark.parametrize(
    ("path", "value", "match"),
    [
        (("generated_at",), "2026-07-20T18:30:00", "generated_at"),
        (("generated_at",), "not-a-timestamp", "generated_at"),
        (("dataset", "id"), "other", "dataset.id"),
        (("dataset", "latest_date"), "", "latest_date"),
        (("dataset", "latest_date"), "20-07-2026", "latest_date"),
        (("dataset", "quality_passed"), 1, "quality_passed"),
        (("dataset", "manifest_hash"), "xyz", "manifest_hash"),
        (("models",), {}, "models"),
    ],
)
def test_snapshot_rejects_invalid_metadata(tmp_path, path, value, match):
    payload = _payload()
    cursor = payload
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value

    _assert_write_and_load_reject(tmp_path, payload, match)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("id", _MISSING, "model.id"),
        ("id", "", "model.id"),
        ("experiment_id", _MISSING, "experiment_id"),
        ("experiment_id", "", "experiment_id"),
        ("sha256", _MISSING, "model.sha256"),
        ("sha256", "bad", "model.sha256"),
        ("status", _MISSING, "model.status"),
        ("status", "", "model.status"),
        ("model_type", _MISSING, "model.model_type"),
        ("model_type", "", "model.model_type"),
        ("path", _MISSING, "model.path"),
        ("path", "", "model.path"),
        ("metrics", _MISSING, "model.metrics"),
        ("metrics", [], "model.metrics"),
        ("walk_forward_metrics", _MISSING, "walk_forward_metrics"),
        ("walk_forward_metrics", [], "walk_forward_metrics"),
    ],
)
def test_snapshot_rejects_invalid_model_schema(tmp_path, field, value, match):
    payload = _payload()
    payload["models"] = [
        {
            "id": "model-1",
            "experiment_id": "exp-1",
            "status": "candidate",
            "model_type": "LightGBM",
            "path": "models/model-1.txt",
            "sha256": "f" * 64,
            "metrics": {"rank_ic": 0.02},
            "walk_forward_metrics": {},
        }
    ]
    if value is _MISSING:
        payload["models"][0].pop(field)
    else:
        payload["models"][0][field] = value

    _assert_write_and_load_reject(tmp_path, payload, match)


def test_snapshot_rejects_corrupt_json(tmp_path):
    target = tmp_path / "corrupt.json"
    target.write_text('{"schema_version":', encoding="utf-8")

    with pytest.raises(ValueError, match="invalid snapshot JSON"):
        load_research_snapshot(target)


def test_snapshot_rejects_non_finite_values_on_write_and_load(tmp_path):
    payload = _payload()
    payload["extra_metric"] = float("nan")

    with pytest.raises(ValueError, match="non-finite"):
        write_research_snapshot(payload, tmp_path / "nan-write.json")

    raw = deepcopy(payload)
    raw["snapshot_sha256"] = "0" * 64
    target = tmp_path / "nan-load.json"
    target.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="non-finite"):
        load_research_snapshot(target)


def test_build_snapshot_reads_registry_records_without_online_cache():
    sys.modules.pop("scripts.adaptive_snapshot", None)
    sys.modules.pop("quant.data.cache", None)
    module = importlib.import_module("scripts.adaptive_snapshot")

    assert "quant.data.cache" not in sys.modules

    class Store:
        def __init__(self):
            self.calls = []

        def read_research_snapshot_records(self, dataset_id):
            self.calls.append(("research_snapshot", dataset_id))
            return {
                "dataset": {
                    "id": "a_share_6y_daily",
                    "latest_date": "2026-07-20",
                    "status": "ready",
                },
                "models": [
                    {
                        "id": "model-1",
                        "experiment_id": "exp-1",
                        "status": "candidate",
                        "model_type": "LightGBM",
                        "path": "models/model-1.txt",
                        "sha256": "1" * 64,
                        "metrics": {"rank_ic": 0.02},
                    },
                    {
                        "id": "model-2",
                        "experiment_id": "exp-2",
                        "status": "candidate",
                        "model_type": "LightGBM",
                        "path": "models/model-2.txt",
                        "sha256": "2" * 64,
                        "metrics": {},
                    },
                ],
                "experiments": [
                    {"id": "exp-1", "metrics": {"rank_ic": 0.031}},
                    {"id": "exp-2", "metrics": {}},
                ],
            }

    store = Store()
    result = module.build_snapshot(
        store,
        {
            "dataset_id": "a_share_6y_daily",
            "data_latest_date": "2026-07-20",
            "passed": True,
            "manifest_hash": "b" * 64,
        },
    )

    generated_at = datetime.fromisoformat(result["generated_at"])
    assert result["schema_version"] == "adaptive-research.v1"
    assert generated_at.tzinfo is not None
    assert result["dataset"] == {
        "id": "a_share_6y_daily",
        "latest_date": "2026-07-20",
        "quality_passed": True,
        "manifest_hash": "b" * 64,
    }
    assert result["models"][0]["walk_forward_metrics"] == {"rank_ic": 0.031}
    assert result["models"][1]["walk_forward_metrics"] == {}
    assert result["models"][0]["model_type"] == "LightGBM"
    assert result["models"][0]["path"] == "models/model-1.txt"
    assert result["models"][0]["metrics"] == {"rank_ic": 0.02}
    assert store.calls == [("research_snapshot", "a_share_6y_daily")]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", _MISSING),
        ("model_type", 123),
        ("path", ""),
        ("metrics", []),
    ],
)
def test_build_snapshot_rejects_malformed_registry_model(field, value):
    module = importlib.import_module("scripts.adaptive_snapshot")
    model = {
        "id": "model-1",
        "experiment_id": "exp-1",
        "status": "candidate",
        "model_type": "LightGBM",
        "path": "models/model-1.txt",
        "sha256": "1" * 64,
        "metrics": {},
    }
    if value is _MISSING:
        model.pop(field)
    else:
        model[field] = value

    class Store:
        def read_research_snapshot_records(self, dataset_id):
            return {
                "dataset": {
                    "id": dataset_id,
                    "latest_date": "2026-07-20",
                },
                "models": [model],
                "experiments": [{"id": "exp-1", "metrics": {}}],
            }

    with pytest.raises(ValueError, match=field):
        module.build_snapshot(
            Store(),
            {
                "dataset_id": "a_share_6y_daily",
                "data_latest_date": "2026-07-20",
                "passed": True,
                "manifest_hash": "b" * 64,
            },
        )


def test_build_snapshot_rejects_missing_dataset_after_reading_registry():
    module = importlib.import_module("scripts.adaptive_snapshot")

    class Store:
        def __init__(self):
            self.calls = []

        def read_research_snapshot_records(self, dataset_id):
            self.calls.append(("research_snapshot", dataset_id))
            return {"dataset": None, "models": [], "experiments": []}

    store = Store()

    with pytest.raises(ValueError, match="a_share_6y_daily"):
        module.build_snapshot(
            store,
            {
                "dataset_id": "a_share_6y_daily",
                "data_latest_date": "2026-07-20",
                "passed": True,
                "manifest_hash": "b" * 64,
            },
        )

    assert store.calls == [("research_snapshot", "a_share_6y_daily")]


def _seed_main_prerequisites(
    root,
    *,
    registry=True,
    quality=True,
    manifest=True,
):
    if registry:
        from quant.qlib.registry import Registry, utc_now

        store = Registry(root / "qlib_meta.db")
        now = utc_now()
        store.upsert_dataset(
            {
                "id": "a_share_6y_daily",
                "kind": "research",
                "status": "ready",
                "latest_date": "2026-07-20",
                "created_at": now,
                "updated_at": now,
            }
        )
    dataset_root = root / "datasets" / "a_share_6y_daily"
    manifest_path = dataset_root / "manifest.json"
    quality_path = dataset_root / "quality_report.json"
    timestamp_ns = 1_700_000_000_000_000_000
    manifest_hash = "0" * 64
    if manifest:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "dataset_id": "a_share_6y_daily",
                    "start_date": "2020-07-20",
                    "end_date": "2026-07-20",
                    "requested": 5000,
                }
            ),
            encoding="utf-8",
        )
        os.utime(manifest_path, ns=(timestamp_ns, timestamp_ns))
        manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if quality:
        quality_path.parent.mkdir(parents=True, exist_ok=True)
        quality_path.write_text(
            json.dumps(
                {
                    "passed": True,
                    "dataset_id": "a_share_6y_daily",
                    "data_latest_date": "2026-07-20",
                    "checked_at": "2026-07-20",
                    "reason_codes": [],
                    "manifest_hash": manifest_hash,
                }
            ),
            encoding="utf-8",
        )
        os.utime(
            quality_path,
            ns=(timestamp_ns + 1_000_000_000, timestamp_ns + 1_000_000_000),
        )


def test_quality_provenance_requires_exact_manifest_file_hash(tmp_path):
    module = importlib.import_module("scripts.adaptive_snapshot")
    root = tmp_path / "external-qlib"
    _seed_main_prerequisites(root)
    manifest_path = root / "datasets" / "a_share_6y_daily" / "manifest.json"
    quality_path = root / "datasets" / "a_share_6y_daily" / "quality_report.json"
    expected_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    validated = module.load_quality_provenance(
        quality_path,
        manifest_path,
        "2026-07-20",
    )

    assert validated["passed"] is True
    assert validated["manifest_hash"] == expected_hash


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("passed", False, "passed"),
        ("passed", "false", "passed"),
        ("passed", 1, "passed"),
        ("dataset_id", "other", "dataset_id"),
        ("data_latest_date", "2026-07-19", "data_latest_date"),
        ("manifest_hash", "bad", "manifest_hash"),
        ("manifest_hash", "0" * 64, "manifest_hash"),
    ],
)
def test_quality_provenance_rejects_invalid_report(
    tmp_path,
    field,
    value,
    match,
):
    module = importlib.import_module("scripts.adaptive_snapshot")
    root = tmp_path / "external-qlib"
    _seed_main_prerequisites(root)
    manifest_path = root / "datasets" / "a_share_6y_daily" / "manifest.json"
    quality_path = root / "datasets" / "a_share_6y_daily" / "quality_report.json"
    report = json.loads(quality_path.read_text(encoding="utf-8"))
    report[field] = value
    quality_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ValueError, match=match):
        module.load_quality_provenance(
            quality_path,
            manifest_path,
            "2026-07-20",
        )


def test_quality_provenance_requires_object_and_valid_manifest(tmp_path):
    module = importlib.import_module("scripts.adaptive_snapshot")
    root = tmp_path / "external-qlib"
    _seed_main_prerequisites(root)
    manifest_path = root / "datasets" / "a_share_6y_daily" / "manifest.json"
    quality_path = root / "datasets" / "a_share_6y_daily" / "quality_report.json"
    quality_path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="quality report must be an object"):
        module.load_quality_provenance(
            quality_path,
            manifest_path,
            "2026-07-20",
        )

    quality_path.write_text(
        json.dumps(
            {
                "passed": True,
                "dataset_id": "a_share_6y_daily",
                "data_latest_date": "2026-07-20",
            }
        ),
        encoding="utf-8",
    )
    manifest_path.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid manifest JSON"):
        module.load_quality_provenance(
            quality_path,
            manifest_path,
            "2026-07-20",
        )


def test_main_opens_registry_readonly(tmp_path, monkeypatch):
    module = importlib.import_module("scripts.adaptive_snapshot")
    root = tmp_path / "external-qlib"
    _seed_main_prerequisites(root)
    monkeypatch.setenv("QLIB_DATA_ROOT", str(root))
    real_registry = module.Registry
    calls = []

    def registry_factory(path, *, read_only=False):
        calls.append((path, read_only))
        return real_registry(path, read_only=read_only)

    monkeypatch.setattr(module, "Registry", registry_factory)

    assert module.main() == 0

    output = root / "runtime_exports" / "adaptive-research-latest.json"
    assert calls == [(root / "qlib_meta.db", True)]
    assert load_research_snapshot(output)["dataset"]["latest_date"] == "2026-07-20"


@pytest.mark.parametrize(
    ("missing", "message"),
    [
        ("registry", "qlib_meta.db"),
        ("quality", "quality_report.json"),
        ("manifest", "manifest.json"),
    ],
)
def test_main_refuses_missing_prerequisites_without_snapshot(
    tmp_path,
    monkeypatch,
    missing,
    message,
):
    module = importlib.import_module("scripts.adaptive_snapshot")
    root = tmp_path / "external-qlib"
    _seed_main_prerequisites(
        root,
        registry=missing != "registry",
        quality=missing != "quality",
        manifest=missing != "manifest",
    )
    monkeypatch.setenv("QLIB_DATA_ROOT", str(root))

    with pytest.raises(FileNotFoundError, match=message):
        module.main()

    assert not (root / "runtime_exports" / "adaptive-research-latest.json").exists()
    if missing == "registry":
        assert not (root / "qlib_meta.db").exists()


def test_main_preserves_previous_snapshot_when_quality_is_stale(
    tmp_path,
    monkeypatch,
):
    module = importlib.import_module("scripts.adaptive_snapshot")
    root = tmp_path / "external-qlib"
    _seed_main_prerequisites(root)
    monkeypatch.setenv("QLIB_DATA_ROOT", str(root))
    assert module.main() == 0
    output = root / "runtime_exports" / "adaptive-research-latest.json"
    previous = output.read_bytes()
    quality_path = root / "datasets" / "a_share_6y_daily" / "quality_report.json"
    manifest_path = root / "datasets" / "a_share_6y_daily" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["requested"] = 5001
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    newer = quality_path.stat().st_mtime_ns + 1_000_000_000
    os.utime(manifest_path, ns=(newer, newer))

    with pytest.raises(ValueError, match="older than manifest"):
        module.main()

    assert output.read_bytes() == previous


def test_main_rejects_changed_manifest_even_with_backdated_mtime(
    tmp_path,
    monkeypatch,
):
    module = importlib.import_module("scripts.adaptive_snapshot")
    root = tmp_path / "external-qlib"
    _seed_main_prerequisites(root)
    monkeypatch.setenv("QLIB_DATA_ROOT", str(root))
    assert module.main() == 0
    output = root / "runtime_exports" / "adaptive-research-latest.json"
    previous = output.read_bytes()
    quality_path = root / "datasets" / "a_share_6y_daily" / "quality_report.json"
    manifest_path = root / "datasets" / "a_share_6y_daily" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["requested"] = 4999
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    older = quality_path.stat().st_mtime_ns - 1_000_000_000
    os.utime(manifest_path, ns=(older, older))

    with pytest.raises(ValueError, match="manifest_hash"):
        module.main()

    assert output.read_bytes() == previous

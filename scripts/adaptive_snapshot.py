"""Export a read-only Qlib research snapshot for the adaptive subsystem."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quant.adaptive.snapshot import write_research_snapshot
from quant.qlib.paths import resolve_data_path
from quant.qlib.registry import Registry


DATASET_ID = "a_share_6y_daily"
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


def _reject_non_finite(value: str):
    raise ValueError(f"non-finite value: {value}")


def _load_json(path: Path, label: str):
    if not path.is_file():
        raise FileNotFoundError(f"Qlib {label} not found: {path}")
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_non_finite,
        )
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"invalid {label} JSON") from exc


def load_quality_provenance(
    quality_path: Path,
    manifest_path: Path,
    registry_latest_date: str,
) -> dict:
    quality_report = _load_json(Path(quality_path), "quality report")
    manifest_path = Path(manifest_path)
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Qlib manifest not found: {manifest_path}")
    try:
        manifest_bytes = manifest_path.read_bytes()
        json.loads(
            manifest_bytes.decode("utf-8"),
            parse_constant=_reject_non_finite,
        )
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError("invalid manifest JSON") from exc
    if not isinstance(quality_report, dict):
        raise ValueError("quality report must be an object")
    if quality_report.get("passed") is not True:
        raise ValueError("quality report passed must be true")
    if quality_report.get("dataset_id") != DATASET_ID:
        raise ValueError(f"quality report dataset_id must be {DATASET_ID}")
    if quality_report.get("data_latest_date") != registry_latest_date:
        raise ValueError("quality report data_latest_date does not match registry")
    if quality_path.stat().st_mtime_ns < manifest_path.stat().st_mtime_ns:
        raise ValueError("quality report is older than manifest")
    recorded_hash = quality_report.get("manifest_hash")
    if not isinstance(recorded_hash, str) or not _SHA256_PATTERN.fullmatch(
        recorded_hash
    ):
        raise ValueError("quality report manifest_hash must be a 64-hex SHA-256")
    current_hash = hashlib.sha256(manifest_bytes).hexdigest()
    if recorded_hash != current_hash:
        raise ValueError("quality report manifest_hash mismatch")
    return dict(quality_report)


def _build_models(models, experiments: dict) -> list[dict]:
    if not isinstance(models, list):
        raise ValueError("registry models must be a list")
    built = []
    for index, model in enumerate(models):
        if not isinstance(model, dict):
            raise ValueError(f"registry model at index {index} must be an object")
        for field in ("id", "experiment_id", "status", "model_type", "path"):
            value = model.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"registry model {field} is required at index {index}")
        model_hash = model.get("sha256")
        if not isinstance(model_hash, str) or not _SHA256_PATTERN.fullmatch(model_hash):
            raise ValueError(f"registry model sha256 is invalid at index {index}")
        if not isinstance(model.get("metrics"), dict):
            raise ValueError(f"registry model metrics must be an object at index {index}")
        experiment = experiments.get(model["experiment_id"])
        if not isinstance(experiment, dict):
            raise ValueError(f"registry experiment is missing for model {model['id']}")
        walk_forward_metrics = experiment.get("metrics")
        if not isinstance(walk_forward_metrics, dict):
            raise ValueError(
                f"registry experiment metrics must be an object for model {model['id']}"
            )
        built.append({**model, "walk_forward_metrics": walk_forward_metrics})
    return built


def build_snapshot(
    store,
    quality_report: dict,
    *,
    records: dict | None = None,
) -> dict:
    record_bundle = (
        records
        if records is not None
        else store.read_research_snapshot_records(DATASET_ID)
    )
    dataset = record_bundle.get("dataset")
    if dataset is None:
        raise ValueError(f"Qlib registry dataset not found: {DATASET_ID}")
    experiment_rows = record_bundle.get("experiments") or []
    if not isinstance(experiment_rows, list) or not all(
        isinstance(row, dict) and isinstance(row.get("id"), str)
        for row in experiment_rows
    ):
        raise ValueError("registry experiments must be valid records")
    experiments = {row["id"]: row for row in experiment_rows}
    models = _build_models(record_bundle.get("models") or [], experiments)
    return {
        "schema_version": "adaptive-research.v1",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dataset": {
            "id": DATASET_ID,
            "latest_date": dataset.get("latest_date"),
            "quality_passed": quality_report.get("passed") is True,
            "manifest_hash": quality_report.get("manifest_hash", ""),
        },
        "models": models,
    }


def main() -> int:
    registry_path = resolve_data_path("qlib_meta.db")
    dataset_path = resolve_data_path("datasets", DATASET_ID)
    quality_path = dataset_path / "quality_report.json"
    manifest_path = dataset_path / "manifest.json"
    if not registry_path.is_file():
        raise FileNotFoundError(f"Qlib registry not found: {registry_path}")
    if not quality_path.is_file():
        raise FileNotFoundError(f"Qlib quality report not found: {quality_path}")
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Qlib manifest not found: {manifest_path}")
    store = Registry(registry_path, read_only=True)
    records = store.read_research_snapshot_records(DATASET_ID)
    dataset = records.get("dataset")
    if dataset is None:
        raise ValueError(f"Qlib registry dataset not found: {DATASET_ID}")
    quality_report = load_quality_provenance(
        quality_path,
        manifest_path,
        dataset.get("latest_date"),
    )
    output_path = resolve_data_path(
        "runtime_exports",
        "adaptive-research-latest.json",
    )
    written = write_research_snapshot(
        build_snapshot(store, quality_report, records=records),
        output_path,
    )
    print(
        json.dumps(
            {"path": str(output_path), "snapshot_sha256": written["snapshot_sha256"]},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

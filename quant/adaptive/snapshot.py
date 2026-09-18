from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from datetime import date, datetime
from pathlib import Path

from quant.adaptive.contracts import require_schema


SCHEMA_VERSION = "adaptive-research.v1"
DATASET_ID = "a_share_6y_daily"
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_REPLACE_LOCK = threading.Lock()


def _reject_non_finite(value: str):
    raise ValueError(f"snapshot contains non-finite value: {value}")


def _json_bytes(payload: object) -> bytes:
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except ValueError as exc:
        raise ValueError("snapshot contains non-finite values") from exc


def _canonical(payload: dict) -> bytes:
    clean = dict(payload)
    clean.pop("snapshot_sha256", None)
    return _json_bytes(clean)


def _validate_snapshot(payload: dict) -> dict:
    snapshot = require_schema(payload, SCHEMA_VERSION)
    generated_at = snapshot.get("generated_at")
    try:
        generated = datetime.fromisoformat(generated_at)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid generated_at") from exc
    if generated.tzinfo is None or generated.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")

    dataset = snapshot.get("dataset")
    if not isinstance(dataset, dict):
        raise ValueError("dataset must be an object")
    if dataset.get("id") != DATASET_ID:
        raise ValueError(f"dataset.id must be {DATASET_ID}")
    latest_date = dataset.get("latest_date")
    if not isinstance(latest_date, str) or not latest_date:
        raise ValueError("dataset.latest_date must be a non-empty ISO date")
    try:
        date.fromisoformat(latest_date)
    except ValueError as exc:
        raise ValueError("invalid dataset.latest_date") from exc
    if dataset.get("quality_passed") is not True:
        raise ValueError("dataset.quality_passed must be true")
    manifest_hash = dataset.get("manifest_hash")
    if not isinstance(manifest_hash, str) or not _SHA256_PATTERN.fullmatch(
        manifest_hash
    ):
        raise ValueError("dataset.manifest_hash must be a 64-hex SHA-256")

    models = snapshot.get("models")
    if not isinstance(models, list):
        raise ValueError("models must be a list")
    for index, model in enumerate(models):
        if not isinstance(model, dict):
            raise ValueError(f"models[{index}] must be an object")
        if not isinstance(model.get("id"), str) or not model["id"].strip():
            raise ValueError(f"model.id is required at index {index}")
        if (
            not isinstance(model.get("experiment_id"), str)
            or not model["experiment_id"].strip()
        ):
            raise ValueError(f"model.experiment_id is required at index {index}")
        model_hash = model.get("sha256")
        if not isinstance(model_hash, str) or not _SHA256_PATTERN.fullmatch(model_hash):
            raise ValueError(f"model.sha256 must be a 64-hex SHA-256 at index {index}")
        for field in ("status", "model_type", "path"):
            value = model.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"model.{field} is required at index {index}")
        if not isinstance(model.get("metrics"), dict):
            raise ValueError(f"model.metrics must be an object at index {index}")
        if not isinstance(model.get("walk_forward_metrics"), dict):
            raise ValueError(f"model.walk_forward_metrics must be an object at index {index}")
    return snapshot


def write_research_snapshot(payload: dict, path: str | Path) -> dict:
    snapshot = _validate_snapshot(payload)
    snapshot["snapshot_sha256"] = hashlib.sha256(_canonical(snapshot)).hexdigest()

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = _json_bytes(snapshot)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        with _REPLACE_LOCK:
            os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return snapshot


def load_research_snapshot(path: str | Path) -> dict:
    try:
        payload = json.loads(
            Path(path).read_text(encoding="utf-8"),
            parse_constant=_reject_non_finite,
        )
    except json.JSONDecodeError as exc:
        raise ValueError("invalid snapshot JSON") from exc
    snapshot = _validate_snapshot(payload)
    expected = hashlib.sha256(_canonical(snapshot)).hexdigest()
    if snapshot.get("snapshot_sha256") != expected:
        raise ValueError("snapshot hash mismatch")
    return snapshot

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import logging
import math
import os
import platform
import re
import shutil
import tempfile
import uuid
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM
from sklearn.exceptions import ConvergenceWarning
from sklearn.preprocessing import StandardScaler

from quant.qlib.paths import DEFAULT_DATA_ROOT


REGIME_FEATURES = ("ret_20", "realized_vol_20", "breadth")
REGIME_SEMANTICS = {"risk_on", "range", "stress"}
SCHEMA_VERSION = "adaptive-regime-model.v1"
MIN_TRAINING_ROWS = 252
MIN_STATE_ROWS = 20
REGIME_ROOT = DEFAULT_DATA_ROOT / "models" / "regime"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class _ConvergenceLogCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if "converg" in message.lower():
            self.messages.append(message)


def _finite_metric(
    metrics: dict[str, float],
    name: str,
    state: int,
) -> float:
    try:
        value = float(metrics[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"state {state} has invalid {name}") from exc
    if not math.isfinite(value):
        raise ValueError(f"state {state} has invalid {name}")
    return value


def map_hidden_states(
    state_means: dict[int, dict[str, float]],
) -> dict[int, str]:
    if not isinstance(state_means, dict) or len(state_means) != 3:
        raise ValueError("state mapping requires exactly three states")
    normalized: dict[int, dict[str, float]] = {}
    for raw_state, metrics in state_means.items():
        if isinstance(raw_state, bool):
            raise ValueError("state identifiers must be integers")
        try:
            state = int(raw_state)
        except (TypeError, ValueError) as exc:
            raise ValueError("state identifiers must be integers") from exc
        if state in normalized or not isinstance(metrics, dict):
            raise ValueError("state mapping contains invalid states")
        normalized[state] = {
            "ret_20": _finite_metric(metrics, "ret_20", state),
            "realized_vol_20": _finite_metric(
                metrics,
                "realized_vol_20",
                state,
            ),
        }

    states = sorted(normalized)
    risk_on = min(
        states,
        key=lambda state: (
            -normalized[state]["ret_20"],
            normalized[state]["realized_vol_20"],
            state,
        ),
    )
    remaining = [state for state in states if state != risk_on]
    stress = min(
        remaining,
        key=lambda state: (
            -normalized[state]["realized_vol_20"],
            normalized[state]["ret_20"],
            state,
        ),
    )
    range_state = next(
        state for state in remaining if state != stress
    )
    return {
        risk_on: "risk_on",
        stress: "stress",
        range_state: "range",
    }


def _validated_frame(
    frame: pd.DataFrame,
    feature_names: list[str],
) -> pd.DataFrame:
    if list(feature_names) != list(REGIME_FEATURES):
        raise ValueError(
            "regime model requires fixed feature order: "
            + ", ".join(REGIME_FEATURES)
        )
    if not isinstance(frame, pd.DataFrame):
        raise ValueError("regime training input must be a DataFrame")
    missing = [name for name in REGIME_FEATURES if name not in frame.columns]
    if missing:
        raise ValueError(f"regime training missing features: {', '.join(missing)}")
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError("regime training index must be a DatetimeIndex")
    if not frame.index.is_monotonic_increasing:
        raise ValueError("regime training rows must be time-ordered")
    if not frame.index.is_unique:
        raise ValueError("regime training timestamps must be unique")
    if len(frame) < MIN_TRAINING_ROWS:
        raise ValueError(
            f"regime training requires at least {MIN_TRAINING_ROWS} rows"
        )

    clean = frame.loc[:, list(REGIME_FEATURES)].copy()
    for name in REGIME_FEATURES:
        clean[name] = pd.to_numeric(clean[name], errors="coerce")
    if not np.isfinite(clean.to_numpy(dtype=float)).all():
        raise ValueError("regime training rows must contain finite features")
    return clean.astype(float)


def _dependency_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "numpy": importlib.metadata.version("numpy"),
        "pandas": importlib.metadata.version("pandas"),
        "scikit_learn": importlib.metadata.version("scikit-learn"),
        "hmmlearn": importlib.metadata.version("hmmlearn"),
        "joblib": importlib.metadata.version("joblib"),
    }


def _new_temp_path(target: Path) -> Path:
    handle = tempfile.NamedTemporaryFile(
        mode="wb",
        delete=False,
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    path = Path(handle.name)
    handle.close()
    return path


def _fsync_file(path: Path) -> None:
    with path.open("r+b") as handle:
        handle.flush()
        os.fsync(handle.fileno())


def _write_bytes_atomic(path: Path, content: bytes) -> None:
    temp = _new_temp_path(path)
    try:
        with temp.open("wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _canonical_metadata_sha256(metadata: dict[str, Any]) -> str:
    payload = dict(metadata)
    payload.pop("metadata_sha256", None)
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _validate_metadata(metadata: Any) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        raise ValueError("regime metadata must be an object")
    if metadata.get("metadata_sha256") != _canonical_metadata_sha256(metadata):
        raise ValueError("regime metadata hash mismatch")
    generation_id = metadata.get("generation_id")
    if type(generation_id) is not str or not _SHA256_PATTERN.fullmatch(generation_id):
        raise ValueError("regime generation_id is invalid")
    if metadata.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("regime metadata schema mismatch")
    artifact_hash = metadata.get("artifact_sha256")
    if type(artifact_hash) is not str or not _SHA256_PATTERN.fullmatch(artifact_hash):
        raise ValueError("regime artifact hash is invalid")
    if metadata.get("feature_names") != list(REGIME_FEATURES):
        raise ValueError("regime metadata feature order mismatch")
    rows = metadata.get("training_rows")
    if type(rows) is not int or rows < MIN_TRAINING_ROWS:
        raise ValueError("regime metadata training rows invalid")
    expected_states = {"0", "1", "2"}
    counts = metadata.get("state_counts")
    mapping = metadata.get("state_mapping")
    means = metadata.get("state_means")
    if not isinstance(counts, dict) or set(counts) != expected_states:
        raise ValueError("regime metadata state counts invalid")
    if any(type(value) is not int or value <= 0 for value in counts.values()):
        raise ValueError("regime metadata state counts invalid")
    if sum(counts.values()) != rows:
        raise ValueError("regime metadata state counts invalid")
    if (
        not isinstance(mapping, dict)
        or set(mapping) != expected_states
        or set(mapping.values()) != REGIME_SEMANTICS
    ):
        raise ValueError("regime metadata state mapping invalid")
    if not isinstance(means, dict) or set(means) != expected_states:
        raise ValueError("regime metadata state means invalid")
    for state in expected_states:
        metrics = means.get(state)
        if not isinstance(metrics, dict) or set(metrics) != set(REGIME_FEATURES):
            raise ValueError("regime metadata state means invalid")
        if any(
            type(metrics[name]) not in (int, float)
            or not math.isfinite(float(metrics[name]))
            for name in REGIME_FEATURES
        ):
            raise ValueError("regime metadata state means invalid")
    matrix = metadata.get("transition_matrix")
    try:
        transition = np.asarray(matrix, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("regime metadata transition matrix invalid") from exc
    if (
        transition.shape != (3, 3)
        or not np.isfinite(transition).all()
        or (transition < 0).any()
        or not np.allclose(transition.sum(axis=1), 1.0, atol=1e-6)
    ):
        raise ValueError("regime metadata transition matrix invalid")
    if metadata.get("converged") is not True:
        raise ValueError("regime metadata convergence state invalid")
    try:
        start = pd.Timestamp(metadata.get("training_start"))
        end = pd.Timestamp(metadata.get("training_end"))
    except (TypeError, ValueError) as exc:
        raise ValueError("regime metadata training range invalid") from exc
    if pd.isna(start) or pd.isna(end) or start >= end:
        raise ValueError("regime metadata training range invalid")
    if type(metadata.get("random_state")) is not int:
        raise ValueError("regime metadata random state invalid")
    if not isinstance(metadata.get("dependency_versions"), dict):
        raise ValueError("regime metadata dependency versions invalid")
    return metadata


def _validate_loaded_artifact(
    artifact: Any,
    *,
    expected_rows: int,
    validation_rows: np.ndarray,
) -> None:
    if not isinstance(artifact, dict):
        raise ValueError("artifact must be an object")
    if artifact.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("artifact schema mismatch")
    if artifact.get("feature_names") != list(REGIME_FEATURES):
        raise ValueError("artifact feature order mismatch")
    if int(artifact.get("training_rows") or 0) != expected_rows:
        raise ValueError("artifact training row count mismatch")
    mapping = artifact.get("state_mapping")
    if (
        not isinstance(mapping, dict)
        or set(mapping) != {0, 1, 2}
        or set(mapping.values()) != REGIME_SEMANTICS
    ):
        raise ValueError("artifact state keys mismatch")
    scaler = artifact.get("scaler")
    model = artifact.get("model")
    if not hasattr(scaler, "transform"):
        raise ValueError("artifact scaler is invalid")
    if not hasattr(model, "predict_proba"):
        raise ValueError("artifact model is invalid")
    transformed = np.asarray(scaler.transform(validation_rows), dtype=float)
    probabilities = np.asarray(model.predict_proba(transformed), dtype=float)
    if (
        transformed.shape != validation_rows.shape
        or not np.isfinite(transformed).all()
        or probabilities.shape != (len(validation_rows), 3)
        or not np.isfinite(probabilities).all()
        or (probabilities < 0).any()
        or not np.allclose(probabilities.sum(axis=1), 1.0, atol=1e-6)
    ):
        raise ValueError("artifact probability inference is invalid")
    monitor = getattr(model, "monitor_", None)
    if monitor is None or getattr(monitor, "converged", False) is not True:
        raise ValueError("artifact model is not converged")
    matrix = np.asarray(getattr(model, "transmat_", None), dtype=float)
    if (
        matrix.shape != (3, 3)
        or not np.isfinite(matrix).all()
        or not np.allclose(matrix.sum(axis=1), 1.0, atol=1e-6)
    ):
        raise ValueError("artifact transition matrix is invalid")


def load_current_regime_model() -> dict[str, Any]:
    root = Path(REGIME_ROOT).resolve()
    pointer_path = root / "regime-latest.json"
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError("regime pointer is unreadable") from exc
    metadata = _validate_metadata(pointer)
    generation_id = metadata["generation_id"]
    generation_root = (root / "generations").resolve()
    generation = (generation_root / generation_id).resolve()
    try:
        generation.relative_to(generation_root)
    except ValueError as exc:
        raise ValueError("regime generation_id escaped generation root") from exc
    artifact_path = generation / "regime.joblib"
    generation_metadata_path = generation / "metadata.json"
    try:
        generation_metadata = json.loads(
            generation_metadata_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError("regime generation metadata is unreadable") from exc
    if generation_metadata != metadata:
        raise ValueError("regime generation metadata mismatch")
    try:
        artifact_hash = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValueError("regime artifact is unreadable") from exc
    if artifact_hash != metadata["artifact_sha256"]:
        raise ValueError("regime artifact hash mismatch")
    try:
        artifact = joblib.load(artifact_path)
        _validate_loaded_artifact(
            artifact,
            expected_rows=metadata["training_rows"],
            validation_rows=np.zeros((1, len(REGIME_FEATURES)), dtype=float),
        )
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"regime artifact validation failed: {exc}") from exc
    return {
        "artifact": artifact,
        "artifact_path": artifact_path,
        "metadata": metadata,
    }


def _require_converged(model: Any) -> None:
    monitor = getattr(model, "monitor_", None)
    if monitor is None or getattr(monitor, "converged", False) is not True:
        raise RuntimeError("regime model did not converge")
    history = [float(value) for value in getattr(monitor, "history", ())]
    if len(history) < 2 or not np.isfinite(history).all():
        raise RuntimeError("regime model did not converge")
    delta = history[-1] - history[-2]
    precision = np.finfo(float).eps ** 0.5
    if delta < -precision:
        raise RuntimeError("regime model convergence warning")
    tolerance = float(getattr(monitor, "tol", getattr(model, "tol", 0.0)))
    if not math.isfinite(tolerance) or tolerance <= 0 or delta >= tolerance:
        raise RuntimeError("regime model did not converge")


def train_regime_model(
    frame: pd.DataFrame,
    *,
    feature_names: list[str],
    output_path: Path,
    random_state: int = 7,
) -> dict[str, Any]:
    clean = _validated_frame(frame, feature_names)
    scaler = StandardScaler()
    values = scaler.fit_transform(clean.to_numpy(dtype=float))
    model = GaussianHMM(
        n_components=3,
        covariance_type="diag",
        n_iter=300,
        tol=1e-4,
        random_state=int(random_state),
    )
    log_capture = _ConvergenceLogCapture()
    hmm_logger = logging.getLogger("hmmlearn.base")
    hmm_logger.addHandler(log_capture)
    try:
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            model.fit(values)
            states = np.asarray(model.predict(values), dtype=int)
    finally:
        hmm_logger.removeHandler(log_capture)
    convergence_warnings = [
        warning
        for warning in captured
        if issubclass(warning.category, ConvergenceWarning)
        or "converg" in str(warning.message).lower()
    ]
    if convergence_warnings or log_capture.messages:
        raise RuntimeError("regime model convergence warning")
    _require_converged(model)
    if states.shape != (len(clean),) or not np.isin(states, (0, 1, 2)).all():
        raise RuntimeError("regime model returned invalid hidden states")

    state_counts = {
        state: int(np.count_nonzero(states == state))
        for state in range(3)
    }
    required_support = max(
        MIN_STATE_ROWS,
        int(math.ceil(len(clean) * 0.05)),
    )
    if any(count < required_support for count in state_counts.values()):
        raise RuntimeError(
            "regime model has insufficient state support "
            f"(minimum {required_support} rows)"
        )
    state_means = {
        state: {
            name: float(clean.iloc[states == state][name].mean())
            for name in REGIME_FEATURES
        }
        for state in range(3)
    }
    state_mapping = map_hidden_states(state_means)
    transition_matrix = np.asarray(model.transmat_, dtype=float)
    if (
        transition_matrix.shape != (3, 3)
        or not np.isfinite(transition_matrix).all()
        or not np.allclose(transition_matrix.sum(axis=1), 1.0, atol=1e-6)
    ):
        raise RuntimeError("regime model transition matrix is invalid")

    artifact = {
        "schema_version": SCHEMA_VERSION,
        "feature_names": list(REGIME_FEATURES),
        "scaler": scaler,
        "model": model,
        "state_mapping": state_mapping,
        "state_means": state_means,
        "state_counts": state_counts,
        "training_rows": len(clean),
        "training_start": clean.index[0].isoformat(),
        "training_end": clean.index[-1].isoformat(),
        "random_state": int(random_state),
    }
    target = Path(output_path)
    metadata_path = target.with_suffix(".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    generations_root = target.parent / "generations"
    staging_dir = Path(
        tempfile.mkdtemp(prefix=".staging-", dir=target.parent)
    )
    staged_artifact = staging_dir / "regime.joblib"
    staged_metadata = staging_dir / "metadata.json"
    try:
        joblib.dump(artifact, staged_artifact)
        _fsync_file(staged_artifact)
        try:
            loaded = joblib.load(staged_artifact)
            _validate_loaded_artifact(
                loaded,
                expected_rows=len(clean),
                validation_rows=clean.iloc[:16].to_numpy(dtype=float),
            )
        except Exception as exc:
            raise RuntimeError(
                f"regime artifact reload validation failed: {exc}"
            ) from exc
        artifact_sha256 = hashlib.sha256(
            staged_artifact.read_bytes()
        ).hexdigest()
        generation_id = hashlib.sha256(
            f"{artifact_sha256}:{uuid.uuid4().hex}".encode("ascii")
        ).hexdigest()
        metadata = {
            "schema_version": SCHEMA_VERSION,
            "generation_id": generation_id,
            "generated_at": datetime.now().astimezone().isoformat(
                timespec="seconds"
            ),
            "path": str(
                target.parent
                / "generations"
                / generation_id
                / "regime.joblib"
            ),
            "artifact_sha256": artifact_sha256,
            "dependency_versions": _dependency_versions(),
            "training_rows": len(clean),
            "feature_names": list(REGIME_FEATURES),
            "state_counts": {
                str(state): count
                for state, count in sorted(state_counts.items())
            },
            "state_mapping": {
                str(state): semantic
                for state, semantic in sorted(state_mapping.items())
            },
            "state_means": {
                str(state): state_means[state]
                for state in sorted(state_means)
            },
            "transition_matrix": transition_matrix.tolist(),
            "converged": True,
            "training_start": clean.index[0].isoformat(),
            "training_end": clean.index[-1].isoformat(),
            "random_state": int(random_state),
        }
        metadata["metadata_sha256"] = _canonical_metadata_sha256(metadata)
        _validate_metadata(metadata)
        metadata_bytes = (
            json.dumps(
                metadata,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        with staged_metadata.open("wb") as handle:
            handle.write(metadata_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        generations_root.mkdir(parents=True, exist_ok=True)
        generation_dir = generations_root / generation_id
        os.replace(staging_dir, generation_dir)
        persisted_artifact = generation_dir / "regime.joblib"
        persisted_metadata = generation_dir / "metadata.json"
        if hashlib.sha256(persisted_artifact.read_bytes()).hexdigest() != artifact_sha256:
            raise RuntimeError("persisted regime artifact hash mismatch")
        if persisted_metadata.read_bytes() != metadata_bytes:
            raise RuntimeError("persisted regime metadata mismatch")
        # Compatibility mirror is non-authoritative. The pointer remains the
        # sole commit point and readers always resolve the immutable generation.
        _write_bytes_atomic(target, persisted_artifact.read_bytes())
        _write_bytes_atomic(metadata_path, metadata_bytes)
        return metadata
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)

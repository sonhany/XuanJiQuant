from __future__ import annotations

import hashlib
import json
import math
import os
import pickle
import re
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping
from urllib.parse import unquote, urlparse

import pandas as pd

from .workflow_config import (
    build_dataset_config,
    build_model_config,
    build_port_analysis_config,
    build_window_workflow_config,
    config_sha256,
)


@dataclass(frozen=True)
class WorkflowRequest:
    local_experiment_id: str
    dataset_id: str
    dataset_version: str
    quality_report_id: str
    provider_uri: Path
    recorder_uri: str
    experiment_name: str
    recorder_name: str
    handler: str
    model_type: str
    seed: int
    segments: dict[str, tuple[str, str]]
    instruments: str = "all"


@dataclass(frozen=True)
class WorkflowResult:
    local_experiment_id: str
    dataset_id: str
    dataset_version: str
    quality_report_id: str
    handler: str
    model_type: str
    seed: int
    qlib_experiment_id: str
    recorder_id: str
    status: str
    artifact_root: Path
    metrics: dict[str, Any]
    artifacts: list[str]
    config_hash: str


class WindowWorkflowError(ValueError):
    """Fail-closed error carrying a stable F4 Qlib reason code."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = str(reason_code)
        self.detail = str(detail)
        super().__init__(
            self.reason_code if not self.detail else f"{self.reason_code}: {self.detail}"
        )


@dataclass(frozen=True, slots=True)
class WindowWorkflowRequest:
    candidate_id: str
    window_id: str
    alpha_spec_hash: str
    provider_uri: Path
    artifact_root: Path
    handler: str
    model_type: str
    seed: int
    segments: dict[str, tuple[str, str]]
    minimum_coverage: float
    allowed_segment_dates: tuple[tuple[str, tuple[str, ...]], ...]
    allowed_segment_identities: tuple[
        tuple[str, tuple[tuple[str, str], ...]], ...
    ] = ()
    instruments: str = "all"


@dataclass(frozen=True, slots=True)
class WindowPredictionResult:
    candidate_id: str
    window_id: str
    segment: str
    alpha_spec_hash: str
    config_hash: str
    model_sha256: str
    prediction_path: Path
    prediction_sha256: str
    coverage: float
    lock_hash: str
    promotion_state: str = "research_only"
    execution_authority: bool = False


@dataclass(frozen=True, slots=True)
class WindowWorkflowResult:
    candidate_id: str
    window_id: str
    alpha_spec_hash: str
    handler: str
    model_type: str
    seed: int
    recorder_id: str
    recorder_identity: str
    config_hash: str
    model_path: Path
    model_sha256: str
    validation_prediction_path: Path
    validation_prediction_sha256: str
    validation_coverage: float
    artifact_root: Path
    provider_uri: Path
    instruments: str
    segments: tuple[tuple[str, tuple[str, str]], ...]
    minimum_coverage: float
    allowed_segment_dates: tuple[tuple[str, tuple[str, ...]], ...]
    allowed_segment_identities: tuple[
        tuple[str, tuple[tuple[str, str], ...]], ...
    ]
    fit_manifest_path: Path
    promotion_state: str = "research_only"
    execution_authority: bool = False

    def predict_test(
        self,
        *,
        lock: Mapping[str, Any],
        runtime: Any | None = None,
    ) -> WindowPredictionResult:
        return predict_locked_test(self, lock, runtime=runtime)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for name in (
            "model_path",
            "validation_prediction_path",
            "artifact_root",
            "provider_uri",
            "fit_manifest_path",
        ):
            payload[name] = str(payload[name])
        payload["segments"] = {
            name: list(bounds) for name, bounds in self.segments
        }
        payload["allowed_segment_dates"] = {
            name: list(dates) for name, dates in self.allowed_segment_dates
        }
        payload["allowed_segment_identities"] = {
            name: [list(identity) for identity in identities]
            for name, identities in self.allowed_segment_identities
        }
        return payload


@dataclass(frozen=True, slots=True)
class _WindowRecorderBinding:
    id: str
    identity: str
    native: Any = None


class QlibRuntime:
    def __init__(self) -> None:
        self.recorder: Any = None
        self.config_hash = ""

    def init(self, request: WorkflowRequest) -> None:
        import qlib
        import mlflow
        from qlib.constant import REG_CN

        if request.recorder_uri.startswith("sqlite:///"):
            database_path = Path(request.recorder_uri.removeprefix("sqlite:///"))
            artifact_root = (
                database_path.parent
                / "mlruns"
                / re.sub(r"[^A-Za-z0-9_.-]+", "-", request.experiment_name)
            )
            artifact_root.mkdir(parents=True, exist_ok=True)
            client = mlflow.tracking.MlflowClient(
                tracking_uri=request.recorder_uri
            )
            if client.get_experiment_by_name(request.experiment_name) is None:
                client.create_experiment(
                    request.experiment_name,
                    artifact_location=artifact_root.resolve().as_uri(),
                )

        qlib.init(
            provider_uri=str(request.provider_uri),
            region=REG_CN,
            expression_cache=None,
            dataset_cache=None,
            exp_manager={
                "class": "MLflowExpManager",
                "module_path": "qlib.workflow.expm",
                "kwargs": {
                    "uri": request.recorder_uri,
                    "default_exp_name": request.experiment_name,
                },
            },
        )

    def build_dataset(self, config: dict[str, Any]) -> Any:
        from qlib.utils import init_instance_by_config

        return init_instance_by_config(config)

    def build_model(self, config: dict[str, Any]) -> Any:
        from qlib.utils import init_instance_by_config

        official = dict(config)
        official.pop("xuanji_metadata", None)
        return init_instance_by_config(official)

    @contextmanager
    def start(self, request: WorkflowRequest) -> Iterator[Any]:
        from qlib.workflow import R

        with R.start(
            experiment_name=request.experiment_name,
            recorder_name=request.recorder_name,
            uri=request.recorder_uri,
        ):
            self.recorder = R.get_recorder()
            R.log_params(
                local_experiment_id=request.local_experiment_id,
                dataset_id=request.dataset_id,
                dataset_version=request.dataset_version,
                quality_report_id=request.quality_report_id,
                handler=request.handler,
                model_type=request.model_type,
                seed=request.seed,
                config_hash=self.config_hash,
            )
            yield self.recorder

    def save_model(self, model: Any) -> None:
        from qlib.workflow import R

        R.save_objects(**{"params.pkl": model})

    def generate_signal(self, model: Any, dataset: Any, recorder: Any) -> None:
        from qlib.workflow.record_temp import SignalRecord

        SignalRecord(model, dataset, recorder).generate()

    def generate_signal_analysis(self, recorder: Any) -> None:
        from qlib.workflow.record_temp import SigAnaRecord

        SigAnaRecord(recorder, ana_long_short=True).generate()

    def generate_portfolio_analysis(
        self,
        recorder: Any,
        config: dict[str, Any],
    ) -> None:
        from qlib.workflow.record_temp import PortAnaRecord

        PortAnaRecord(
            recorder,
            config=config,
            risk_analysis_freq="day",
            indicator_analysis_freq="day",
        ).generate()

    def finish(self) -> dict[str, Any]:
        if self.recorder is None:
            raise RuntimeError("Qlib recorder was not started")
        artifact_uri = str(self.recorder.get_artifact_uri())
        parsed = urlparse(artifact_uri)
        if parsed.scheme == "file":
            local = unquote(parsed.path)
            if re.match(r"^/[A-Za-z]:", local):
                local = local[1:]
            artifact_root = Path(local)
        else:
            artifact_root = Path(self.recorder.get_local_dir()) / "artifacts"
        artifacts = (
            [
                path.relative_to(artifact_root).as_posix()
                for path in sorted(artifact_root.rglob("*"))
                if path.is_file()
            ]
            if artifact_root.exists()
            else []
        )
        return {
            "artifact_root": artifact_root,
            "metrics": dict(self.recorder.list_metrics() or {}),
            "artifacts": artifacts,
        }

    def init_window(self, request: WindowWorkflowRequest) -> None:
        import qlib
        import mlflow
        from qlib.constant import REG_CN

        experiment_name = "xuanji-f4-window-v2"
        database_path = (
            Path(request.provider_uri).resolve().parent.parent / "mlflow.db"
        )
        database_path.parent.mkdir(parents=True, exist_ok=True)
        recorder_uri = f"sqlite:///{database_path.as_posix()}"
        artifact_root = (
            database_path.parent / "mlruns" / experiment_name
        ).resolve()
        artifact_root.mkdir(parents=True, exist_ok=True)
        client = mlflow.tracking.MlflowClient(tracking_uri=recorder_uri)
        if client.get_experiment_by_name(experiment_name) is None:
            client.create_experiment(
                experiment_name,
                artifact_location=artifact_root.as_uri(),
            )
        qlib.init(
            provider_uri=str(request.provider_uri),
            region=REG_CN,
            expression_cache=None,
            dataset_cache=None,
            exp_manager={
                "class": "MLflowExpManager",
                "module_path": "qlib.workflow.expm",
                "kwargs": {
                    "uri": recorder_uri,
                    "default_exp_name": experiment_name,
                },
            },
        )

    @contextmanager
    def start_window_recorder(
        self,
        request: WindowWorkflowRequest,
        *,
        recorder_identity: str,
    ) -> Iterator[_WindowRecorderBinding]:
        from qlib.workflow import R

        experiment_name = "xuanji-f4-window-v2"
        with R.start(
            experiment_name=experiment_name,
            recorder_name=recorder_identity,
        ):
            recorder = R.get_recorder()
            yield _WindowRecorderBinding(
                id=str(recorder.id),
                identity=str(recorder_identity),
                native=recorder,
            )

    @contextmanager
    def resume_window_recorder(
        self,
        request: WindowWorkflowRequest,
        *,
        recorder_id: str,
        recorder_identity: str,
    ) -> Iterator[_WindowRecorderBinding]:
        del request
        from qlib.workflow import R

        recorder = R.get_recorder(
            recorder_id=recorder_id,
            experiment_name="xuanji-f4-window-v2",
        )
        yield _WindowRecorderBinding(
            id=str(recorder_id),
            identity=str(recorder_identity),
            native=recorder,
        )

    def fit_model(self, model: Any, dataset: Any, *, segment: str) -> None:
        if segment != "train":
            raise ValueError("window model may only fit the train segment")
        model.fit(dataset)

    def save_window_model(self, model: Any, path: Path) -> None:
        with Path(path).open("wb") as handle:
            pickle.dump(model, handle, protocol=pickle.HIGHEST_PROTOCOL)
            handle.flush()
            os.fsync(handle.fileno())

    def load_window_model(self, path: Path, config: dict[str, Any]) -> Any:
        del config
        with Path(path).open("rb") as handle:
            return pickle.load(handle)

    def predict_segment(self, model: Any, dataset: Any, *, segment: str) -> Any:
        if segment not in {"valid", "test"}:
            raise ValueError("window prediction segment is invalid")
        return model.predict(dataset, segment=segment)

    def expected_prediction_identities(
        self,
        dataset: Any,
        *,
        segment: str,
    ) -> tuple[tuple[Any, Any], ...]:
        prepared = dataset.prepare(segment, col_set="feature", data_key="infer")
        index = prepared.index
        if not isinstance(index, pd.MultiIndex) or index.nlevels < 2:
            raise ValueError("Qlib prediction eligibility index is invalid")
        return tuple((item[0], item[1]) for item in index.tolist())


_WINDOW_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    try:
        encoded = json.dumps(
            dict(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=str,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise WindowWorkflowError("qlib_artifact_nonfinite", str(exc)) from exc
    _atomic_bytes(path, encoded)


def _atomic_model(runtime: Any, model: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        runtime.save_window_model(model, temporary)
        if not temporary.is_file():
            raise WindowWorkflowError("qlib_model_artifact_missing")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _resolved_child(root: Path, *components: str) -> Path:
    resolved_root = Path(root).resolve()
    if resolved_root.exists() and not resolved_root.is_dir():
        raise WindowWorkflowError("qlib_artifact_path_invalid")
    if any(not _WINDOW_COMPONENT.fullmatch(str(component)) for component in components):
        raise WindowWorkflowError("qlib_artifact_path_invalid")
    target = resolved_root.joinpath(*components).resolve()
    if not target.is_relative_to(resolved_root):
        raise WindowWorkflowError("qlib_artifact_path_invalid")
    return target


def _artifact_target(root: Path, parent: Path, name: str) -> Path:
    """Reject lexical, parent-symlink and pre-existing target-symlink escapes."""

    resolved_root = Path(root).resolve()
    lexical = Path(os.path.abspath(parent / name))
    try:
        lexical.relative_to(resolved_root)
    except ValueError as exc:
        raise WindowWorkflowError("qlib_artifact_path_invalid") from exc
    resolved = lexical.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise WindowWorkflowError("qlib_artifact_path_invalid")
    return lexical


def _verify_artifact_target(root: Path, path: Path) -> None:
    resolved_root = Path(root).resolve()
    lexical = Path(os.path.abspath(path))
    try:
        lexical.relative_to(resolved_root)
    except ValueError as exc:
        raise WindowWorkflowError("qlib_artifact_path_invalid") from exc
    if not lexical.resolve().is_relative_to(resolved_root):
        raise WindowWorkflowError("qlib_artifact_path_invalid")


def _normalize_identity(date: Any, instrument: Any) -> tuple[str, str]:
    try:
        normalized_date = pd.Timestamp(date).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OverflowError) as exc:
        raise WindowWorkflowError("qlib_prediction_identity_invalid") from exc
    normalized_instrument = str(instrument).strip().upper()
    if not normalized_instrument:
        raise WindowWorkflowError("qlib_prediction_identity_invalid")
    return normalized_date, normalized_instrument


def _prediction_frame(value: Any) -> pd.DataFrame:
    if isinstance(value, pd.Series):
        if (
            not isinstance(value.index, pd.MultiIndex)
            or list(value.index.names) != ["datetime", "instrument"]
        ):
            raise WindowWorkflowError("qlib_prediction_payload_invalid")
        frame = value.rename("score").reset_index()
        frame.rename(columns={"datetime": "date"}, inplace=True)
    elif isinstance(value, pd.DataFrame):
        frame = value.copy()
        if {"date", "instrument"}.issubset(frame.columns):
            value_columns = [
                column
                for column in frame.columns
                if column not in {"date", "instrument"}
            ]
            if len(value_columns) != 1:
                raise WindowWorkflowError("qlib_prediction_payload_invalid")
            frame.rename(columns={value_columns[0]: "score"}, inplace=True)
        elif (
            isinstance(frame.index, pd.MultiIndex)
            and list(frame.index.names) == ["datetime", "instrument"]
            and len(frame.columns) == 1
        ):
            frame.rename(columns={frame.columns[0]: "score"}, inplace=True)
            frame = frame.reset_index()
            frame.rename(columns={"datetime": "date"}, inplace=True)
        else:
            raise WindowWorkflowError("qlib_prediction_payload_invalid")
    else:
        raise WindowWorkflowError("qlib_prediction_payload_invalid")
    if not {"date", "instrument", "score"}.issubset(frame.columns):
        raise WindowWorkflowError("qlib_prediction_payload_invalid")
    frame = frame.loc[:, ["date", "instrument", "score"]].copy()
    identities = [
        _normalize_identity(date, instrument)
        for date, instrument in zip(
            frame["date"], frame["instrument"], strict=True
        )
    ]
    frame["date"] = [identity[0] for identity in identities]
    frame["instrument"] = [identity[1] for identity in identities]
    frame["score"] = pd.to_numeric(frame["score"], errors="coerce")
    if frame.duplicated(["date", "instrument"]).any():
        raise WindowWorkflowError("qlib_prediction_identity_duplicate")
    if any(not math.isfinite(float(score)) for score in frame["score"]):
        raise WindowWorkflowError("qlib_prediction_nonfinite")
    frame.sort_values(["date", "instrument"], kind="mergesort", inplace=True)
    frame.reset_index(drop=True, inplace=True)
    return frame


def _validate_prediction(
    value: Any,
    expected_identities: Iterable[tuple[Any, Any]],
    *,
    minimum_coverage: float,
    segment: str,
    allowed_dates: Iterable[str],
) -> tuple[pd.DataFrame, float]:
    frame = _prediction_frame(value)
    normalized_expected = _normalize_expected_identities(
        expected_identities,
        segment=segment,
        allowed_dates=allowed_dates,
    )
    expected = set(normalized_expected)
    actual = set(zip(frame["date"], frame["instrument"], strict=True))
    if any(date not in {str(value) for value in allowed_dates} for date, _ in actual):
        raise WindowWorkflowError("qlib_prediction_segment_identity_invalid")
    if not actual.issubset(expected):
        raise WindowWorkflowError("qlib_prediction_identity_invalid")
    coverage = len(actual) / len(expected)
    if coverage < float(minimum_coverage):
        raise WindowWorkflowError(
            "qlib_prediction_coverage_insufficient",
            f"actual={coverage:.6f} required={float(minimum_coverage):.6f}",
        )
    return frame, float(coverage)


def _normalize_expected_identities(
    expected_identities: Iterable[tuple[Any, Any]],
    *,
    segment: str,
    allowed_dates: Iterable[str],
) -> tuple[tuple[str, str], ...]:
    allowed = {
        _normalize_identity(date, "__DATE_BOUND__")[0]
        for date in allowed_dates
    }
    if not allowed:
        raise WindowWorkflowError("qlib_prediction_segment_identity_invalid")
    normalized_expected = tuple(
        _normalize_identity(date, instrument)
        for date, instrument in expected_identities
    )
    expected = set(normalized_expected)
    if not expected:
        raise WindowWorkflowError("qlib_prediction_coverage_denominator_invalid")
    if len(expected) != len(normalized_expected):
        raise WindowWorkflowError("qlib_prediction_identity_duplicate")
    if (
        segment not in {"valid", "test"}
        or any(date not in allowed for date, _instrument in expected)
    ):
        raise WindowWorkflowError("qlib_prediction_segment_identity_invalid")
    return tuple(sorted(expected))


def _write_prediction(path: Path, frame: pd.DataFrame) -> str:
    if any(not math.isfinite(float(score)) for score in frame["score"]):
        raise WindowWorkflowError("qlib_prediction_nonfinite")
    encoded = frame.to_csv(
        index=False,
        lineterminator="\n",
        float_format="%.17g",
    ).encode("utf-8")
    _atomic_bytes(path, encoded)
    return _sha256_file(path)


def _window_config(
    request: WindowWorkflowRequest,
    *,
    recorder_identity: str,
) -> dict[str, Any]:
    try:
        return build_window_workflow_config(
            candidate_id=request.candidate_id,
            window_id=request.window_id,
            alpha_spec_hash=request.alpha_spec_hash,
            handler=request.handler,
            model_type=request.model_type,
            seed=request.seed,
            instruments=request.instruments,
            segments=dict(request.segments),
            minimum_coverage=request.minimum_coverage,
            allowed_segment_dates=dict(request.allowed_segment_dates),
            allowed_segment_identities=dict(request.allowed_segment_identities),
            recorder_identity=recorder_identity,
        )
    except (TypeError, ValueError) as exc:
        raise WindowWorkflowError("qlib_config_invalid", str(exc)) from exc


def fit_window_workflow(
    request: WindowWorkflowRequest,
    *,
    runtime: Any | None = None,
) -> WindowWorkflowResult:
    """Fit on train and write validation predictions; never touch test."""

    run_root = _resolved_child(
        request.artifact_root,
        str(request.window_id),
        str(request.candidate_id),
    )
    run_root.mkdir(parents=True, exist_ok=True)
    resolved_root = Path(request.artifact_root).resolve()
    if not run_root.resolve().is_relative_to(resolved_root):
        raise WindowWorkflowError("qlib_artifact_path_invalid")
    active_runtime = runtime or QlibRuntime()
    try:
        active_runtime.init_window(request)
    except (ImportError, ModuleNotFoundError) as exc:
        raise WindowWorkflowError("qlib_dependency_unavailable", str(exc)) from exc
    requested_recorder_identity = (
        f"f4v2-{request.window_id}-{request.candidate_id[:16]}-"
        f"{request.alpha_spec_hash[:12]}"
    )
    stage = "recorder"
    try:
        with active_runtime.start_window_recorder(
            request,
            recorder_identity=requested_recorder_identity,
        ) as recorder:
            recorder_id = str(getattr(recorder, "id", "") or "")
            recorder_identity = str(getattr(recorder, "identity", "") or "")
            if (
                not recorder_id
                or recorder_identity != requested_recorder_identity
            ):
                raise WindowWorkflowError("qlib_recorder_identity_invalid")
            provisional_config = _window_config(
                request,
                recorder_identity=recorder_identity,
            )
            stage = "identity_binding"
            dataset = active_runtime.build_dataset(provisional_config["dataset"])
            dates_by_segment = dict(request.allowed_segment_dates)
            # Test eligibility is intentionally not inspected before a verified
            # winner lock.  Only validation identities enter the fit identity.
            bound_identities = tuple(
                (
                    segment,
                    _normalize_expected_identities(
                        active_runtime.expected_prediction_identities(
                            dataset, segment=segment
                        ),
                        segment=segment,
                        allowed_dates=dates_by_segment[segment],
                    ),
                )
                for segment in ("valid",)
            )
            bound_request = replace(
                request,
                allowed_segment_identities=bound_identities,
            )
            config = _window_config(
                bound_request,
                recorder_identity=recorder_identity,
            )
            config_hash = config_sha256(config)
            stage = "training"
            model = active_runtime.build_model(config["model"])
            active_runtime.fit_model(model, dataset, segment="train")

            stage = "model_write"
            model_path = _artifact_target(resolved_root, run_root, "model.pkl")
            _atomic_model(active_runtime, model, model_path)
            _verify_artifact_target(resolved_root, model_path)
            model_sha256 = _sha256_file(model_path)

            stage = "prediction"
            raw_prediction = active_runtime.predict_segment(
                model, dataset, segment="valid"
            )
            expected = dict(bound_identities)["valid"]
            frame, coverage = _validate_prediction(
                raw_prediction,
                expected,
                minimum_coverage=request.minimum_coverage,
                segment="valid",
                allowed_dates=dict(request.allowed_segment_dates)["valid"],
            )
            prediction_path = _artifact_target(
                resolved_root, run_root, "validation_predictions.csv"
            )
            prediction_sha256 = _write_prediction(prediction_path, frame)
            _verify_artifact_target(resolved_root, prediction_path)

            stage = "manifest_write"
            manifest_path = _artifact_target(
                resolved_root, run_root, "fit_manifest.json"
            )
            manifest = {
                "candidate_id": request.candidate_id,
                "window_id": request.window_id,
                "alpha_spec_hash": request.alpha_spec_hash,
                "handler": request.handler,
                "model_type": request.model_type,
                "seed": int(request.seed),
                "recorder_id": recorder_id,
                "recorder_identity": recorder_identity,
                "config_hash": config_hash,
                "model_path": model_path.name,
                "model_sha256": model_sha256,
                "validation_prediction_path": prediction_path.name,
                "validation_prediction_sha256": prediction_sha256,
                "validation_coverage": coverage,
                "allowed_segment_dates": {
                    name: list(dates)
                    for name, dates in request.allowed_segment_dates
                },
                "allowed_segment_identities": {
                    name: [list(identity) for identity in identities]
                    for name, identities in bound_identities
                },
                "promotion_state": "research_only",
                "execution_authority": False,
            }
            _atomic_json(manifest_path, manifest)
            _verify_artifact_target(resolved_root, manifest_path)
    except (ImportError, ModuleNotFoundError) as exc:
        raise WindowWorkflowError("qlib_dependency_unavailable", str(exc)) from exc
    except WindowWorkflowError:
        raise
    except Exception as exc:
        reason_code = {
            "prediction": "qlib_prediction_failed",
            "model_write": "qlib_model_artifact_write_failed",
            "manifest_write": "qlib_artifact_write_failed",
        }.get(stage, "qlib_training_failed")
        raise WindowWorkflowError(reason_code, str(exc)) from exc
    return WindowWorkflowResult(
        candidate_id=request.candidate_id,
        window_id=request.window_id,
        alpha_spec_hash=request.alpha_spec_hash,
        handler=request.handler,
        model_type=request.model_type,
        seed=int(request.seed),
        recorder_id=recorder_id,
        recorder_identity=recorder_identity,
        config_hash=config_hash,
        model_path=model_path,
        model_sha256=model_sha256,
        validation_prediction_path=prediction_path,
        validation_prediction_sha256=prediction_sha256,
        validation_coverage=coverage,
        artifact_root=resolved_root,
        provider_uri=Path(request.provider_uri).resolve(),
        instruments=request.instruments,
        segments=tuple(
            (name, tuple(bounds)) for name, bounds in sorted(request.segments.items())
        ),
        minimum_coverage=float(request.minimum_coverage),
        allowed_segment_dates=tuple(
            (name, tuple(dates))
            for name, dates in sorted(request.allowed_segment_dates)
        ),
        allowed_segment_identities=bound_identities,
        fit_manifest_path=manifest_path,
    )


def _verify_lock(result: WindowWorkflowResult, lock: Mapping[str, Any]) -> str:
    lock_payload = dict(lock)
    lock_hash = str(lock_payload.get("lock_hash") or "")
    lock_core = {
        key: value
        for key, value in lock_payload.items()
        if key not in {"lock_hash", "promotion_state", "execution_authority"}
    }
    required = {
        "candidate_id": result.candidate_id,
        "window_id": result.window_id,
        "alpha_spec_hash": result.alpha_spec_hash,
        "alpha_fit_hash": result.config_hash,
        "model_artifact_hash": result.model_sha256,
        "selection_scope": "current_window_validation_only",
        "test_scope": "locked_winner_only",
    }
    required_identity_fields = (
        "factory_run_id",
        "portfolio_policy_hash",
        "validation_leaderboard_hash",
    )
    if (
        any(lock_core.get(key) != value for key, value in required.items())
        or any(
            not isinstance(lock_core.get(key), str)
            or not str(lock_core.get(key)).strip()
            for key in required_identity_fields
        )
        or lock_payload.get("promotion_state") != "research_only"
        or lock_payload.get("execution_authority") is not False
        or lock_hash != config_sha256(lock_core)
    ):
        raise WindowWorkflowError("qlib_test_lock_invalid")
    return lock_hash


def _verify_fit_result(result: WindowWorkflowResult) -> None:
    root = result.artifact_root.resolve()
    model_path = result.model_path.resolve()
    validation_path = result.validation_prediction_path.resolve()
    manifest_path = result.fit_manifest_path.resolve()
    if any(
        not path.is_relative_to(root)
        for path in (model_path, validation_path, manifest_path)
    ):
        raise WindowWorkflowError("qlib_artifact_path_invalid")
    if not model_path.is_file():
        raise WindowWorkflowError("qlib_model_artifact_missing")
    if _sha256_file(model_path) != result.model_sha256:
        raise WindowWorkflowError("qlib_model_hash_mismatch")
    if (
        not validation_path.is_file()
        or _sha256_file(validation_path) != result.validation_prediction_sha256
    ):
        raise WindowWorkflowError("qlib_validation_prediction_hash_mismatch")
    if result.promotion_state != "research_only" or result.execution_authority:
        raise WindowWorkflowError("qlib_artifact_authority_invalid")
    if not result.recorder_id or not result.recorder_identity:
        raise WindowWorkflowError("qlib_recorder_identity_invalid")


def predict_locked_test(
    result: WindowWorkflowResult,
    lock: Mapping[str, Any],
    *,
    runtime: Any | None = None,
) -> WindowPredictionResult:
    """Verify the immutable winner lock, then predict only the test segment."""

    _verify_fit_result(result)
    lock_hash = _verify_lock(result, lock)
    request = WindowWorkflowRequest(
        candidate_id=result.candidate_id,
        window_id=result.window_id,
        alpha_spec_hash=result.alpha_spec_hash,
        provider_uri=result.provider_uri,
        artifact_root=result.artifact_root,
        handler=result.handler,
        model_type=result.model_type,
        seed=result.seed,
        segments=dict(result.segments),
        minimum_coverage=result.minimum_coverage,
        allowed_segment_dates=result.allowed_segment_dates,
        allowed_segment_identities=result.allowed_segment_identities,
        instruments=result.instruments,
    )
    config = _window_config(
        request,
        recorder_identity=result.recorder_identity,
    )
    if config_sha256(config) != result.config_hash:
        raise WindowWorkflowError("qlib_config_hash_mismatch")
    active_runtime = runtime or QlibRuntime()
    try:
        active_runtime.init_window(request)
    except (ImportError, ModuleNotFoundError) as exc:
        raise WindowWorkflowError("qlib_dependency_unavailable", str(exc)) from exc
    try:
        with active_runtime.resume_window_recorder(
            request,
            recorder_id=result.recorder_id,
            recorder_identity=result.recorder_identity,
        ):
            dataset = active_runtime.build_dataset(config["dataset"])
            model = active_runtime.load_window_model(
                result.model_path, config["model"]
            )
            raw_prediction = active_runtime.predict_segment(
                model, dataset, segment="test"
            )
            expected = active_runtime.expected_prediction_identities(
                dataset, segment="test"
            )
            normalized_expected = _normalize_expected_identities(
                expected,
                segment="test",
                allowed_dates=dict(result.allowed_segment_dates)["test"],
            )
            frame, coverage = _validate_prediction(
                raw_prediction,
                normalized_expected,
                minimum_coverage=result.minimum_coverage,
                segment="test",
                allowed_dates=dict(result.allowed_segment_dates)["test"],
            )
    except (ImportError, ModuleNotFoundError) as exc:
        raise WindowWorkflowError("qlib_dependency_unavailable", str(exc)) from exc
    except WindowWorkflowError:
        raise
    except Exception as exc:
        raise WindowWorkflowError("qlib_prediction_failed", str(exc)) from exc
    prediction_path = _artifact_target(
        result.artifact_root, result.model_path.parent, "test_predictions.csv"
    )
    prediction_sha256 = _write_prediction(prediction_path, frame)
    _verify_artifact_target(result.artifact_root, prediction_path)
    return WindowPredictionResult(
        candidate_id=result.candidate_id,
        window_id=result.window_id,
        segment="test",
        alpha_spec_hash=result.alpha_spec_hash,
        config_hash=result.config_hash,
        model_sha256=result.model_sha256,
        prediction_path=prediction_path,
        prediction_sha256=prediction_sha256,
        coverage=coverage,
        lock_hash=lock_hash,
    )


def run_workflow(
    request: WorkflowRequest,
    *,
    runtime: Any | None = None,
) -> WorkflowResult:
    dataset_config = build_dataset_config(
        handler=request.handler,
        instruments=request.instruments,
        segments=request.segments,
    )
    model_config = build_model_config(request.model_type, request.seed)
    port_config = build_port_analysis_config(*request.segments["test"])
    combined_config = {
        "dataset": dataset_config,
        "model": model_config,
        "portfolio_analysis": port_config,
    }
    config_hash = config_sha256(combined_config)
    active_runtime = runtime or QlibRuntime()
    setattr(active_runtime, "config_hash", config_hash)
    active_runtime.init(request)
    dataset = active_runtime.build_dataset(dataset_config)
    model = active_runtime.build_model(model_config)
    recorder = None
    with active_runtime.start(request) as recorder:
        model.fit(dataset)
        active_runtime.save_model(model)
        active_runtime.generate_signal(model, dataset, recorder)
        active_runtime.generate_signal_analysis(recorder)
        active_runtime.generate_portfolio_analysis(recorder, port_config)
    finished = active_runtime.finish()
    return WorkflowResult(
        local_experiment_id=request.local_experiment_id,
        dataset_id=request.dataset_id,
        dataset_version=request.dataset_version,
        quality_report_id=request.quality_report_id,
        handler=request.handler,
        model_type=request.model_type,
        seed=int(request.seed),
        qlib_experiment_id=str(recorder.experiment_id),
        recorder_id=str(recorder.id),
        status="succeeded",
        artifact_root=Path(finished["artifact_root"]),
        metrics=dict(finished.get("metrics") or {}),
        artifacts=list(finished.get("artifacts") or []),
        config_hash=config_hash,
    )

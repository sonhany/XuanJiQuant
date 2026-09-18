"""Qlib Alpha158 + LightGBM training entry."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Callable

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quant.qlib.evaluator import evaluate_cross_section, promotion_status
from quant.qlib.artifact_importer import (
    ArtifactValidationError,
    import_workflow_result,
)
from quant.qlib.paths import resolve_data_path
from quant.qlib.registry import Registry, utc_now
from quant.qlib.workflow_bridge import WorkflowRequest, WorkflowResult, run_workflow


Progress = Callable[[float, str], None]


def _calendar_from_provider(provider_uri: Path) -> pd.DatetimeIndex:
    path = Path(provider_uri) / "calendars" / "day.txt"
    if not path.exists():
        raise RuntimeError(f"Qlib calendar is not ready: {path}")
    values = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    calendar = pd.DatetimeIndex(pd.to_datetime([value for value in values if value]))
    if calendar.empty:
        raise RuntimeError(f"Qlib calendar is empty: {path}")
    return calendar


def _dataset_identity(dataset_id: str, preset: str) -> tuple[str, str]:
    if preset == "official-demo":
        return "qlib-official-demo-simple-v1", "quality_not_required_demo"
    root = resolve_data_path("datasets", dataset_id)
    manifest_path = root / "manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists()
        else {}
    )
    dataset_version = str(manifest.get("dataset_version") or "")
    if not dataset_version:
        dataset_version = f"qlib-bin-{dataset_id}"
    quality_path = root / "quality_report.json"
    quality_report_id = "quality_not_required_one_year"
    if quality_path.exists():
        quality = json.loads(quality_path.read_text(encoding="utf-8"))
        quality_report_id = str(quality.get("report_id") or "quality_report_unidentified")
    return dataset_version, quality_report_id


def _recorder_uri() -> str:
    path = resolve_data_path("mlflow.db").resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path.as_posix()}"


def chronological_segments(calendar: pd.DatetimeIndex) -> dict[str, tuple[str, str]]:
    values = pd.DatetimeIndex(calendar).drop_duplicates().sort_values()
    if len(values) < 61:
        raise ValueError(
            "Qlib training requires at least 60 trading days plus one execution boundary"
        )
    research_values = values[:-1]
    train_end = max(1, int(len(research_values) * 0.6)) - 1
    valid_end = max(train_end + 2, int(len(research_values) * 0.8)) - 1
    valid_end = min(valid_end, len(research_values) - 2)
    return {
        "train": (
            research_values[0].strftime("%Y-%m-%d"),
            research_values[train_end].strftime("%Y-%m-%d"),
        ),
        "valid": (
            research_values[train_end + 1].strftime("%Y-%m-%d"),
            research_values[valid_end].strftime("%Y-%m-%d"),
        ),
        "test": (
            research_values[valid_end + 1].strftime("%Y-%m-%d"),
            research_values[-1].strftime("%Y-%m-%d"),
        ),
    }


def validate_artifact_bundle(artifact_dir: Path, experiment_id: str) -> None:
    artifact_dir = Path(artifact_dir)
    required = ["model.txt", "metrics.json", "predictions.parquet", "report.json"]
    missing = [name for name in required if not (artifact_dir / name).exists()]
    if missing:
        raise ValueError(f"missing training artifacts: {', '.join(missing)}")
    for name in ("metrics.json", "report.json"):
        payload = json.loads((artifact_dir / name).read_text(encoding="utf-8"))
        if payload.get("experiment_id") != experiment_id:
            raise ValueError(f"experiment ID mismatch in {name}")


def _ensure_demo_data(progress: Progress) -> Path:
    target = resolve_data_path("raw", "qlib_demo")
    if (target / "calendars" / "day.txt").exists():
        return target
    progress(0.04, "正在下载 Qlib 官方简化示例数据")
    from qlib.tests.data import GetData

    GetData(delete_zip_file=True).qlib_data(
        name="qlib_data_simple",
        target_dir=target,
        region="cn",
        interval="1d",
        delete_old=False,
        exists_skip=True,
    )
    if not (target / "calendars" / "day.txt").exists():
        raise RuntimeError("Qlib official demo download did not produce a calendar")
    return target


def _segment_consistency(prediction: pd.Series, label: pd.Series) -> bool:
    frame = pd.concat([prediction.rename("score"), label.rename("label")], axis=1).dropna()
    if frame.empty or "datetime" not in frame.index.names:
        return False
    dates = pd.DatetimeIndex(frame.index.get_level_values("datetime").unique()).sort_values()
    if len(dates) < 4:
        return False
    halves = [dates[: len(dates) // 2], dates[len(dates) // 2 :]]
    signs = []
    for values in halves:
        part = frame[frame.index.get_level_values("datetime").isin(values)]
        daily = part.groupby(level="datetime").apply(
            lambda group: group["score"].corr(group["label"], method="spearman")
        ).dropna()
        signs.append(float(daily.mean()) if len(daily) else 0.0)
    return signs[0] != 0 and signs[1] != 0 and signs[0] * signs[1] > 0


def _load_qlib_dataset(
    provider_uri: Path,
    *,
    instruments: str,
    progress: Progress,
    segments_override: dict[str, tuple[str, str]] | None = None,
) -> tuple[Any, dict[str, tuple[str, str]]]:
    import qlib
    from qlib.constant import REG_CN
    from qlib.contrib.data.handler import Alpha158
    from qlib.data import D
    from qlib.data.dataset import DatasetH

    qlib.init(
        provider_uri=str(provider_uri),
        region=REG_CN,
        expression_cache=None,
        dataset_cache=None,
    )
    calendar = pd.DatetimeIndex(D.calendar(freq="day"))
    segments = segments_override or chronological_segments(calendar)
    progress(0.18, f"Qlib 日历已加载，共 {len(calendar)} 个交易日")
    handler = Alpha158(
        instruments=instruments,
        start_time=segments["train"][0],
        end_time=segments["test"][1],
        fit_start_time=segments["train"][0],
        fit_end_time=segments["train"][1],
        label=(["Ref($close, -6) / Ref($close, -1) - 1"], ["LABEL0"]),
    )
    return DatasetH(handler=handler, segments=segments), segments


def _run_walk_forward_preset(
    provider_uri: Path,
    dataset_id: str,
    progress: Progress,
) -> dict[str, Any]:
    import qlib
    from qlib.constant import REG_CN
    from qlib.data import D

    from quant.qlib.walk_forward import (
        aggregate_promotion_status,
        aggregate_walk_forward_metrics,
        build_walk_forward_windows,
    )

    quality_path = resolve_data_path("datasets", dataset_id, "quality_report.json")
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    qlib.init(
        provider_uri=str(provider_uri),
        region=REG_CN,
        expression_cache=None,
        dataset_cache=None,
    )
    windows = build_walk_forward_windows(pd.DatetimeIndex(D.calendar(freq="day")))
    if len(windows) < 4:
        raise RuntimeError("walk-forward requires at least four complete windows")
    experiment_id = f"qlib_six_year_walk_forward_{uuid.uuid4().hex[:12]}"
    store = Registry(resolve_data_path("qlib_meta.db"))
    now = utc_now()
    store.upsert_experiment(
        {
            "id": experiment_id,
            "dataset_id": dataset_id,
            "status": "running",
            "model_type": "LightGBM-WalkForward",
            "config": {"preset": "six-year-walk-forward", "windows": windows},
            "created_at": now,
            "updated_at": now,
        }
    )
    window_metrics = []
    for index, window in enumerate(windows, start=1):
        progress(0.05 + 0.85 * (index - 1) / len(windows), f"训练窗口 {index}/{len(windows)}")
        segments = {
            key: tuple(value)
            for key, value in (
                ("train", window["train"]),
                ("valid", window["valid"]),
                ("test", window["test"]),
            )
        }
        dataset, _ = _load_qlib_dataset(
            provider_uri,
            instruments="market",
            progress=lambda *_: None,
            segments_override=segments,
        )
        training, test_label = _prepare_frames(dataset, lambda *_: None)
        window_experiment_id = f"{experiment_id}_{window['id']}"
        trained = train_lightgbm(
            training,
            output_dir=resolve_data_path("models"),
            seed=42 + index,
            experiment_id=window_experiment_id,
        )
        prediction = pd.Series(
            trained["test_predictions"],
            index=test_label.index,
            name="score",
        )
        metrics = evaluate_cross_section(prediction, test_label, cost_bps=20)
        metrics["segment_sign_consistent"] = _segment_consistency(prediction, test_label)
        metrics["window_id"] = window["id"]
        metrics["segments"] = segments
        artifact_dir = Path(trained["artifact_dir"])
        prediction.to_frame().assign(label=test_label).to_parquet(
            artifact_dir / "predictions.parquet"
        )
        (artifact_dir / "metrics.json").write_text(
            json.dumps(
                {"experiment_id": window_experiment_id, **metrics},
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        (artifact_dir / "report.json").write_text(
            json.dumps(
                {
                    "experiment_id": window_experiment_id,
                    "parent_experiment_id": experiment_id,
                    "dataset_id": dataset_id,
                    "status": promotion_status(metrics),
                    "metrics": metrics,
                    "sha256": trained["sha256"],
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        validate_artifact_bundle(artifact_dir, window_experiment_id)
        window_metrics.append(metrics)

    aggregate = aggregate_walk_forward_metrics(window_metrics)
    status = aggregate_promotion_status(window_metrics, bool(quality.get("passed")))
    report = {
        "experiment_id": experiment_id,
        "dataset_id": dataset_id,
        "preset": "six-year-walk-forward",
        "status": status,
        "quality_passed": bool(quality.get("passed")),
        "windows": window_metrics,
        "aggregate_metrics": aggregate,
        "safety_boundary": "offline_research_only",
        "created_at": utc_now(),
    }
    report_path = resolve_data_path("reports", f"{experiment_id}.json")
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    store.upsert_experiment(
        {
            "id": experiment_id,
            "dataset_id": dataset_id,
            "status": "succeeded",
            "model_type": "LightGBM-WalkForward",
            "metrics": aggregate,
            "config": {"preset": "six-year-walk-forward", "windows": windows},
            "path": str(report_path),
            "created_at": now,
            "updated_at": utc_now(),
        }
    )
    store.audit("walk_forward_succeeded", "experiment", experiment_id, report)
    progress(1.0, "Walk-Forward 六年基线完成")
    return {
        "experiment_id": experiment_id,
        "dataset_id": dataset_id,
        "status": status,
        "report": str(report_path),
        "metrics": aggregate,
        "windows": len(window_metrics),
    }


def _prepare_frames(dataset: Any, progress: Progress) -> tuple[dict[str, Any], pd.Series]:
    prepared = {}
    for index, segment in enumerate(("train", "valid", "test"), start=1):
        frame = dataset.prepare(
            segment,
            col_set=["feature", "label"],
            data_key="learn",
        )
        frame = frame.loc[frame["label"].notna().all(axis=1)]
        if frame.empty:
            raise RuntimeError(f"Qlib Alpha158 produced an empty {segment} segment")
        prepared[segment] = frame
        progress(0.22 + index * 0.13, f"Alpha158 {segment} 样本：{len(frame)}")
    feature_names = [
        str(name)
        for name in prepared["train"]["feature"].columns
    ]
    training = {
        "train_x": prepared["train"]["feature"],
        "train_y": prepared["train"]["label"].iloc[:, 0],
        "valid_x": prepared["valid"]["feature"],
        "valid_y": prepared["valid"]["label"].iloc[:, 0],
        "test_x": prepared["test"]["feature"],
        "test_y": prepared["test"]["label"].iloc[:, 0],
        "feature_names": feature_names,
    }
    raw_test = dataset.prepare(
        "test",
        col_set=["label"],
        data_key="infer",
    )
    raw_label = (
        raw_test["label"].iloc[:, 0]
        if isinstance(raw_test.columns, pd.MultiIndex) and "label" in raw_test.columns.get_level_values(0)
        else raw_test.iloc[:, 0]
    )
    return training, raw_label.reindex(prepared["test"].index)


def _model_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dataset_registry_row(
    *,
    existing: dict[str, Any] | None,
    dataset_id: str,
    preset: str,
    provider_uri: Path,
    segments: dict[str, tuple[str, str]],
    now: str,
) -> dict[str, Any]:
    current = dict(existing or {})
    metadata = dict(current.get("metadata") or {})
    metadata.update(
        {
            "preset": preset,
            "source": "qlib_official_demo"
            if preset == "official-demo"
            else "independent_collector",
            "provider_uri": str(provider_uri),
        }
    )
    return {
        "id": dataset_id,
        "kind": current.get("kind")
        or ("official_demo" if preset == "official-demo" else "a_share_daily"),
        "status": current.get("status")
        if preset == "one-year" and current
        else "ready",
        "start_date": segments["train"][0],
        "end_date": segments["test"][1],
        "latest_date": segments["test"][1],
        "instruments": int(current.get("instruments") or 0),
        "rows": int(current.get("rows") or 0),
        "coverage": float(current.get("coverage") or 0),
        "path": str(provider_uri),
        "metadata": metadata,
        "created_at": current.get("created_at") or now,
        "updated_at": utc_now(),
    }


def _research_instruments(dataset_id: str) -> str:
    """Keep provider lookup and the six-year stock research universe separate."""
    return "market" if str(dataset_id) == "a_share_6y_daily" else "all"


def run_preset(
    preset: str,
    *,
    dataset_id: str | None = None,
    progress: Progress | None = None,
) -> dict[str, Any]:
    report_progress = progress or (lambda value, message: print(f"[{value:.1%}] {message}", flush=True))
    if preset == "official-demo":
        provider_uri = _ensure_demo_data(report_progress)
        resolved_dataset_id = "official_demo_smoke"
        instruments = "csi300"
        model_status_override = "official_demo_smoke"
    elif preset == "one-year":
        resolved_dataset_id = dataset_id or "a_share_1y_daily"
        provider_uri = resolve_data_path("qlib_bin", resolved_dataset_id)
        if not (provider_uri / "calendars" / "day.txt").exists():
            raise RuntimeError(f"Qlib bin dataset is not ready: {resolved_dataset_id}")
        instruments = _research_instruments(resolved_dataset_id)
        model_status_override = ""
    elif preset == "six-year-walk-forward":
        resolved_dataset_id = dataset_id or "a_share_6y_daily"
        provider_uri = resolve_data_path("qlib_bin", resolved_dataset_id)
        if not (provider_uri / "calendars" / "day.txt").exists():
            raise RuntimeError(f"Qlib bin dataset is not ready: {resolved_dataset_id}")
        return _run_walk_forward_preset(
            provider_uri,
            resolved_dataset_id,
            report_progress,
        )
    else:
        raise ValueError(f"unsupported training preset: {preset}")

    experiment_id = f"qlib_{preset.replace('-', '_')}_{uuid.uuid4().hex[:12]}"
    store = Registry(resolve_data_path("qlib_meta.db"))
    existing_dataset = next(
        (
            item
            for item in store.list_datasets(500)
            if item.get("id") == resolved_dataset_id
        ),
        None,
    )
    now = utc_now()
    store.upsert_experiment(
        {
            "id": experiment_id,
            "dataset_id": resolved_dataset_id,
            "status": "running",
            "model_type": "LightGBM",
            "config": {"preset": preset, "features": "Alpha158", "label": "future_5d_return"},
            "created_at": now,
            "updated_at": now,
        }
    )
    try:
        dataset, segments = _load_qlib_dataset(
            provider_uri,
            instruments=instruments,
            progress=report_progress,
        )
        training, test_label = _prepare_frames(dataset, report_progress)
        report_progress(0.66, "正在训练 LightGBM")
        trained = train_lightgbm(
            training,
            output_dir=resolve_data_path("models"),
            seed=42,
            experiment_id=experiment_id,
        )
        prediction = pd.Series(trained["test_predictions"], index=test_label.index, name="score")
        metrics = evaluate_cross_section(prediction, test_label, cost_bps=20)
        metrics["segment_sign_consistent"] = _segment_consistency(prediction, test_label)
        status = model_status_override or promotion_status(metrics)
        artifact_dir = Path(trained["artifact_dir"])
        prediction.to_frame().assign(label=test_label).to_parquet(
            artifact_dir / "predictions.parquet"
        )
        metrics_payload = {"experiment_id": experiment_id, **metrics}
        report_payload = {
            "experiment_id": experiment_id,
            "dataset_id": resolved_dataset_id,
            "preset": preset,
            "status": status,
            "feature_set": "Alpha158",
            "target": "future_5d_return",
            "segments": segments,
            "metrics": metrics,
            "safety_boundary": "offline_research_only",
            "created_at": utc_now(),
        }
        (artifact_dir / "metrics.json").write_text(
            json.dumps(metrics_payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        (artifact_dir / "report.json").write_text(
            json.dumps(report_payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        report_path = resolve_data_path("reports", f"{experiment_id}.json")
        report_path.write_text(
            json.dumps(report_payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        validate_artifact_bundle(artifact_dir, experiment_id)
        checksum = _model_checksum(artifact_dir / "model.txt")
        store.upsert_dataset(
            _dataset_registry_row(
                existing=existing_dataset,
                dataset_id=resolved_dataset_id,
                preset=preset,
                provider_uri=provider_uri,
                segments=segments,
                now=now,
            )
        )
        store.upsert_experiment(
            {
                "id": experiment_id,
                "dataset_id": resolved_dataset_id,
                "status": "succeeded",
                "model_type": "LightGBM",
                "metrics": metrics,
                "config": {"preset": preset, "features": "Alpha158", "label": "future_5d_return"},
                "path": str(artifact_dir),
                "created_at": now,
                "updated_at": utc_now(),
            }
        )
        store.upsert_model(
            {
                "id": experiment_id,
                "experiment_id": experiment_id,
                "status": status,
                "model_type": "LightGBM",
                "path": str(artifact_dir / "model.txt"),
                "sha256": checksum,
                "metrics": metrics,
                "created_at": now,
                "updated_at": utc_now(),
            }
        )
        store.audit("training_succeeded", "experiment", experiment_id, report_payload)
        report_progress(1.0, "训练与产物校验完成")
        return {
            "experiment_id": experiment_id,
            "dataset_id": resolved_dataset_id,
            "status": status,
            "artifact_dir": str(artifact_dir),
            "report": str(report_path),
            "metrics": metrics,
        }
    except Exception as exc:
        store.upsert_experiment(
            {
                "id": experiment_id,
                "dataset_id": resolved_dataset_id,
                "status": "failed",
                "model_type": "LightGBM",
                "config": {"preset": preset, "features": "Alpha158", "label": "future_5d_return"},
                "metrics": {},
                "created_at": now,
                "updated_at": utc_now(),
            }
        )
        store.audit("training_failed", "experiment", experiment_id, {"error": str(exc)[:1000]})
        raise


def _run_walk_forward_workflow(
    provider_uri: Path,
    dataset_id: str,
    progress: Progress,
) -> dict[str, Any]:
    from quant.qlib.walk_forward import (
        aggregate_promotion_status,
        aggregate_walk_forward_metrics,
        build_walk_forward_windows,
    )

    quality_path = resolve_data_path("datasets", dataset_id, "quality_report.json")
    if not quality_path.exists():
        raise RuntimeError("walk-forward quality report is missing")
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    dataset_version = str(quality.get("dataset_version") or "")
    quality_report_id = str(quality.get("report_id") or "")
    if not dataset_version or not quality_report_id:
        raise RuntimeError("walk-forward quality report identity is incomplete")
    windows = build_walk_forward_windows(_calendar_from_provider(provider_uri))
    if len(windows) < 4:
        raise RuntimeError("walk-forward requires at least four complete windows")

    parent_id = f"qlib_six_year_walk_forward_{uuid.uuid4().hex[:12]}"
    store = Registry(resolve_data_path("qlib_meta.db"))
    created_at = utc_now()
    store.upsert_experiment(
        {
            "id": parent_id,
            "dataset_id": dataset_id,
            "status": "running",
            "model_type": "LightGBM-WalkForward",
            "config": {"preset": "six-year-walk-forward", "windows": windows},
            "created_at": created_at,
            "updated_at": created_at,
        }
    )
    window_metrics = []
    for index, window in enumerate(windows, start=1):
        progress(
            0.05 + 0.85 * (index - 1) / len(windows),
            f"正在运行 Qlib 滚动窗口 {index}/{len(windows)}",
        )
        segments = {
            "train": tuple(window["train"]),
            "valid": tuple(window["valid"]),
            "test": tuple(window["test"]),
        }
        local_id = f"{parent_id}_{window['id']}"
        result = run_workflow(
            WorkflowRequest(
                local_experiment_id=local_id,
                dataset_id=dataset_id,
                dataset_version=dataset_version,
                quality_report_id=quality_report_id,
                provider_uri=provider_uri,
                recorder_uri=_recorder_uri(),
                experiment_name="xuanji-qlib-walk-forward",
                recorder_name=local_id,
                handler="Alpha158",
                model_type="LightGBM",
                seed=42 + index,
                segments=segments,
                instruments="market",
            )
        )
        imported = import_workflow_result(result, store)
        metrics = {
            **imported["metrics"],
            "window_id": window["id"],
            "segments": segments,
            "recorder_id": result.recorder_id,
            "qlib_experiment_id": result.qlib_experiment_id,
            "config_hash": result.config_hash,
            "workflow_run_id": imported["id"],
        }
        window_metrics.append(metrics)
        store.upsert_experiment(
            {
                "id": local_id,
                "dataset_id": dataset_id,
                "status": "succeeded",
                "model_type": "LightGBM",
                "metrics": result.metrics,
                "config": {
                    "preset": "six-year-walk-forward",
                    "handler": "Alpha158",
                    "window": window,
                    "recorder_id": result.recorder_id,
                },
                "path": str(result.artifact_root),
                "created_at": created_at,
                "updated_at": utc_now(),
            }
        )

    aggregate = aggregate_walk_forward_metrics(window_metrics)
    status = aggregate_promotion_status(window_metrics, bool(quality.get("passed")))
    report = {
        "experiment_id": parent_id,
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "quality_report_id": quality_report_id,
        "preset": "six-year-walk-forward",
        "status": status,
        "quality_passed": bool(quality.get("passed")),
        "windows": window_metrics,
        "aggregate_metrics": aggregate,
        "safety_boundary": "offline_research_only",
        "created_at": utc_now(),
    }
    report_path = resolve_data_path("reports", f"{parent_id}.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    store.upsert_experiment(
        {
            "id": parent_id,
            "dataset_id": dataset_id,
            "status": "succeeded",
            "model_type": "LightGBM-WalkForward",
            "metrics": aggregate,
            "config": {"preset": "six-year-walk-forward", "windows": windows},
            "path": str(report_path),
            "created_at": created_at,
            "updated_at": utc_now(),
        }
    )
    store.audit("walk_forward_succeeded", "experiment", parent_id, report)
    progress(1.0, "Qlib Walk-Forward 六年基线完成")
    return {
        "experiment_id": parent_id,
        "dataset_id": dataset_id,
        "status": status,
        "report": str(report_path),
        "metrics": aggregate,
        "windows": len(window_metrics),
    }


def _run_preset_workflow(
    preset: str,
    *,
    dataset_id: str | None = None,
    progress: Progress | None = None,
) -> dict[str, Any]:
    report_progress = progress or (
        lambda value, message: print(f"[{value:.1%}] {message}", flush=True)
    )
    if preset == "official-demo":
        provider_uri = _ensure_demo_data(report_progress)
        resolved_dataset_id = "official_demo_smoke"
        instruments = "csi300"
        status_override = "official_demo_smoke"
    elif preset in {"one-year", "six-year-walk-forward"}:
        resolved_dataset_id = dataset_id or (
            "a_share_6y_daily"
            if preset == "six-year-walk-forward"
            else "a_share_1y_daily"
        )
        provider_uri = resolve_data_path("qlib_bin", resolved_dataset_id)
        if not (provider_uri / "calendars" / "day.txt").exists():
            raise RuntimeError(f"Qlib bin dataset is not ready: {resolved_dataset_id}")
        if preset == "six-year-walk-forward":
            return _run_walk_forward_workflow(
                provider_uri,
                resolved_dataset_id,
                report_progress,
            )
        instruments = _research_instruments(resolved_dataset_id)
        status_override = ""
    else:
        raise ValueError(f"unsupported training preset: {preset}")

    segments = chronological_segments(_calendar_from_provider(provider_uri))
    local_id = f"qlib_{preset.replace('-', '_')}_{uuid.uuid4().hex[:12]}"
    dataset_version, quality_report_id = _dataset_identity(
        resolved_dataset_id,
        preset,
    )
    store = Registry(resolve_data_path("qlib_meta.db"))
    created_at = utc_now()
    store.upsert_experiment(
        {
            "id": local_id,
            "dataset_id": resolved_dataset_id,
            "status": "running",
            "model_type": "LightGBM",
            "config": {"preset": preset, "features": "Alpha158"},
            "created_at": created_at,
            "updated_at": created_at,
        }
    )
    try:
        report_progress(0.15, "正在运行 Qlib 官方 Workflow 与三类 Record")
        result: WorkflowResult = run_workflow(
            WorkflowRequest(
                local_experiment_id=local_id,
                dataset_id=resolved_dataset_id,
                dataset_version=dataset_version,
                quality_report_id=quality_report_id,
                provider_uri=provider_uri,
                recorder_uri=_recorder_uri(),
                experiment_name="xuanji-qlib-daily",
                recorder_name=local_id,
                handler="Alpha158",
                model_type="LightGBM",
                seed=42,
                segments=segments,
                instruments=instruments,
            )
        )
        imported = import_workflow_result(result, store)
        params_path = Path(result.artifact_root) / "params.pkl"
        store.upsert_model(
            {
                "id": local_id,
                "experiment_id": local_id,
                "status": "official_demo_smoke"
                if preset == "official-demo"
                else "research",
                "model_type": "LightGBM",
                "path": str(params_path),
                "sha256": _model_checksum(params_path),
                "metrics": imported["metrics"],
                "created_at": created_at,
                "updated_at": utc_now(),
            }
        )
        status = status_override or promotion_status(imported["metrics"])
        report_payload = {
            "experiment_id": local_id,
            "dataset_id": resolved_dataset_id,
            "dataset_version": dataset_version,
            "quality_report_id": quality_report_id,
            "preset": preset,
            "status": status,
            "feature_set": "Alpha158",
            "target": "future_5d_return",
            "segments": segments,
            "metrics": result.metrics,
            "normalized_metrics": imported["metrics"],
            "workflow_run_id": imported["id"],
            "qlib_experiment_id": result.qlib_experiment_id,
            "recorder_id": result.recorder_id,
            "config_hash": result.config_hash,
            "artifacts": result.artifacts,
            "safety_boundary": "offline_research_only",
            "created_at": utc_now(),
        }
        report_path = resolve_data_path("reports", f"{local_id}.json")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report_payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        existing_dataset = next(
            (
                item
                for item in store.list_datasets(500)
                if item.get("id") == resolved_dataset_id
            ),
            None,
        )
        store.upsert_dataset(
            _dataset_registry_row(
                existing=existing_dataset,
                dataset_id=resolved_dataset_id,
                preset=preset,
                provider_uri=provider_uri,
                segments=segments,
                now=created_at,
            )
        )
        store.upsert_experiment(
            {
                "id": local_id,
                "dataset_id": resolved_dataset_id,
                "status": "succeeded",
                "model_type": "LightGBM",
                "metrics": result.metrics,
                "config": {
                    "preset": preset,
                    "features": "Alpha158",
                    "recorder_id": result.recorder_id,
                },
                "path": str(result.artifact_root),
                "created_at": created_at,
                "updated_at": utc_now(),
            }
        )
        store.audit("training_succeeded", "experiment", local_id, report_payload)
        report_progress(1.0, "Qlib Workflow 与三类 Record 已完成")
        return {
            "experiment_id": local_id,
            "dataset_id": resolved_dataset_id,
            "status": status,
            "workflow_run_id": imported["id"],
            "workflow_run_ids": [imported["id"]],
            "artifacts_complete": True,
            "artifact_dir": str(result.artifact_root),
            "report": str(report_path),
            "metrics": result.metrics,
            "recorder_id": result.recorder_id,
            "qlib_experiment_id": result.qlib_experiment_id,
        }
    except Exception as exc:
        failure_status = (
            "incomplete" if isinstance(exc, ArtifactValidationError) else "failed"
        )
        store.upsert_experiment(
            {
                "id": local_id,
                "dataset_id": resolved_dataset_id,
                "status": failure_status,
                "model_type": "LightGBM",
                "config": {"preset": preset, "features": "Alpha158"},
                "metrics": {},
                "created_at": created_at,
                "updated_at": utc_now(),
            }
        )
        store.audit(
            "training_failed",
            "experiment",
            local_id,
            {"error": str(exc)[:1000]},
        )
        raise


# Public training entry: all supported presets use the official Qlib Workflow bridge.
run_preset = _run_preset_workflow


def run_quarterly_matrix(
    *,
    progress: Progress | None = None,
) -> dict[str, Any]:
    from quant.qlib.artifact_importer import import_workflow_result
    from quant.qlib.workflow_config import MODEL_MATRIX

    report_progress = progress or (lambda *_: None)
    dataset_id = "a_share_6y_daily"
    provider_uri = resolve_data_path("qlib_bin", dataset_id)
    if not (provider_uri / "calendars" / "day.txt").exists():
        raise RuntimeError(f"Qlib bin dataset is not ready: {dataset_id}")
    dataset_version, quality_report_id = _dataset_identity(dataset_id, "quarterly")
    if quality_report_id.startswith("quality_not_required"):
        raise RuntimeError("quarterly matrix requires an identified quality report")
    segments = chronological_segments(_calendar_from_provider(provider_uri))
    store = Registry(resolve_data_path("qlib_meta.db"))
    workflow_run_ids = []
    failures = []
    for index, (handler, model_type) in enumerate(MODEL_MATRIX, start=1):
        local_id = (
            f"qlib_quarterly_{handler.lower()}_{model_type.lower()}_"
            f"{uuid.uuid4().hex[:10]}"
        )
        report_progress(
            0.05 + 0.85 * (index - 1) / len(MODEL_MATRIX),
            "train",
            f"季度固定矩阵 {index}/{len(MODEL_MATRIX)}：{handler} + {model_type}",
        )
        try:
            result = run_workflow(
                WorkflowRequest(
                    local_experiment_id=local_id,
                    dataset_id=dataset_id,
                    dataset_version=dataset_version,
                    quality_report_id=quality_report_id,
                    provider_uri=provider_uri,
                    recorder_uri=_recorder_uri(),
                    experiment_name="xuanji-qlib-quarterly",
                    recorder_name=local_id,
                    handler=handler,
                    model_type=model_type,
                    seed=42 + index,
                    segments=segments,
                    instruments="market",
                )
            )
            imported = import_workflow_result(result, store)
            params = Path(result.artifact_root) / "params.pkl"
            store.upsert_model(
                {
                    "id": local_id,
                    "experiment_id": local_id,
                    "status": "research",
                    "model_type": model_type,
                    "path": str(params),
                    "sha256": _model_checksum(params),
                    "metrics": imported["metrics"],
                }
            )
            workflow_run_ids.append(imported["id"])
        except Exception as exc:
            failures.append(
                {"handler": handler, "model_type": model_type, "error": str(exc)[:500]}
            )
    status = "succeeded" if not failures else "partial_failed"
    report_progress(1.0, "report", f"季度固定矩阵完成：{status}")
    return {
        "status": status,
        "dataset_version": dataset_version,
        "quality_report_id": quality_report_id,
        "workflow_run_ids": workflow_run_ids,
        "artifacts_complete": len(workflow_run_ids) == len(MODEL_MATRIX),
        "failures": failures,
    }


def run_ashare_for_workflow(
    workflow_run_id: str,
    *,
    progress: Progress | None = None,
) -> dict[str, Any]:
    import pandas as pd

    from quant.qlib.ashare_backtest import build_signal_bundle, run_ashare_backtest
    from quant.qlib.promotion_gate import evaluate_promotion_gate

    if not workflow_run_id:
        raise ValueError("workflow_run_id is required for A-share backtest")
    report_progress = progress or (lambda *_: None)
    store = Registry(resolve_data_path("qlib_meta.db"))
    workflow = store.get_workflow_run(workflow_run_id)
    if workflow is None:
        raise KeyError(workflow_run_id)
    experiment = store.get_experiment(workflow["experiment_id"])
    if experiment is None or not experiment.get("dataset_id"):
        raise RuntimeError("workflow experiment has no dataset binding")
    dataset_id = str(experiment["dataset_id"])
    artifact_root = Path(workflow["resolved_path"])
    prediction_payload = pd.read_pickle(artifact_root / "pred.pkl")
    prediction = (
        prediction_payload["score"]
        if isinstance(prediction_payload, pd.DataFrame)
        and "score" in prediction_payload.columns
        else prediction_payload.iloc[:, 0]
        if isinstance(prediction_payload, pd.DataFrame)
        and len(prediction_payload.columns) == 1
        else prediction_payload
    )
    if not isinstance(prediction, pd.Series):
        raise RuntimeError("workflow prediction artifact is not a Series")
    bundle = build_signal_bundle(
        prediction,
        workflow_run_id,
        workflow["dataset_version"],
        topk=50,
        n_drop=5,
        excluded_instruments={"SH000300"},
    )
    report_progress(0.25, "local_backtest", "正在加载 A 股时点行情与交易约束")
    raw_root = resolve_data_path("datasets", dataset_id, "raw")
    klines = {}
    for code in bundle["signals"]:
        matches = sorted(raw_root.glob(f"*{code}.json"))
        if not matches:
            raise RuntimeError(f"A-share backtest raw bars missing: {code}")
        frame = pd.DataFrame(json.loads(matches[0].read_text(encoding="utf-8")))
        if "datetime" in frame.columns and "date" not in frame.columns:
            frame = frame.rename(columns={"datetime": "date"})
        klines[code] = frame
    backtest = run_ashare_backtest(signal_bundle=bundle, klines=klines)
    metrics = dict(backtest.get("metrics") or {})
    trading_days = max(1, int(metrics.get("trading_days") or 0))
    ashare_metrics = {
        "after_cost_return": float(metrics.get("total_return_pct") or 0) / 100,
        "annual_return": float(metrics.get("annual_return_pct") or 0) / 100,
        "sharpe": float(metrics.get("sharpe_ratio") or 0),
        "max_drawdown": -abs(float(metrics.get("max_drawdown_pct") or 0) / 100),
        "annual_turnover": float(metrics.get("fill_count") or 0)
        / trading_days
        * 252,
    }
    canonical = dict(workflow.get("metrics") or {})
    official_metrics = {
        "after_cost_return": float(canonical.get("official_annualized_return") or 0),
        "annual_return": float(canonical.get("official_annualized_return") or 0),
        "sharpe": float(canonical.get("official_information_ratio") or 0),
        "max_drawdown": float(canonical.get("official_max_drawdown") or 0),
        "annual_turnover": float(canonical.get("official_annual_turnover") or 0),
    }
    quality = next(
        (
            item
            for item in store.list_quality_reports(500)
            if item.get("id") == workflow.get("quality_report_id")
        ),
        None,
    )
    signal_metrics = {
        "window_count": 1,
        "median_rank_ic": float(canonical.get("rank_ic") or 0),
        "median_icir": float(canonical.get("rank_icir") or 0),
        "positive_rank_ic_ratio": 1.0 if float(canonical.get("rank_ic") or 0) > 0 else 0.0,
        "aggregate_after_cost_long_short": float(
            canonical.get("long_short_annual_return") or 0
        ),
        "aggregate_sharpe": float(canonical.get("long_short_annual_sharpe") or 0),
        "max_drawdown": float(canonical.get("official_max_drawdown") or 0),
        "worst_rank_ic": float(canonical.get("rank_ic") or 0),
    }
    gate = evaluate_promotion_gate(
        quality_passed=bool(quality and quality.get("passed")),
        signal_metrics=signal_metrics,
        official_backtest=official_metrics,
        ashare_backtest=ashare_metrics,
        divergence_reviewed=False,
    )
    gate["signal_hash"] = bundle["signal_hash"]
    store.update_workflow_gate(workflow_run_id, gate)
    now = utc_now()
    for engine, engine_metrics, config in (
        ("qlib_official", official_metrics, {"source": "PortAnaRecord"}),
        ("xuanji_ashare", ashare_metrics, {"version": backtest["config_version"]}),
    ):
        store.upsert_backtest_result(
            {
                "id": f"backtest_{workflow_run_id}_{engine}",
                "workflow_run_id": workflow_run_id,
                "engine": engine,
                "signal_hash": bundle["signal_hash"],
                "metrics": engine_metrics,
                "config": config,
                "artifact_path": str(artifact_root),
                "created_at": now,
                "updated_at": now,
            }
        )
    model = next(
        (
            item
            for item in store.list_models(500)
            if item.get("experiment_id") == workflow["experiment_id"]
        ),
        None,
    )
    if model is not None:
        store.update_model_status(model["id"], gate["status"])
    report_progress(1.0, "report", f"双回测与统一门禁完成：{gate['status']}")
    return {
        "status": "succeeded",
        "workflow_run_id": workflow_run_id,
        "engines": ["qlib_official", "xuanji_ashare"],
        "gate_status": gate["status"],
        "gate": gate,
        "signal_hash": bundle["signal_hash"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--preset",
        choices=["official-demo", "one-year", "six-year-walk-forward"],
        required=True,
    )
    parser.add_argument("--dataset-id")
    args = parser.parse_args()
    result = run_preset(args.preset, dataset_id=args.dataset_id)
    print(json.dumps(result, ensure_ascii=False, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

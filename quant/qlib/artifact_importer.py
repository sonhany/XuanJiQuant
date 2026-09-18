from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .registry import Registry, utc_now
from .workflow_bridge import WorkflowResult


REQUIRED_ARTIFACTS = (
    "params.pkl",
    "pred.pkl",
    "label.pkl",
    "sig_analysis/ic.pkl",
    "sig_analysis/ric.pkl",
    "portfolio_analysis/report_normal_1day.pkl",
    "portfolio_analysis/positions_normal_1day.pkl",
    "portfolio_analysis/port_analysis_1day.pkl",
)


class ArtifactValidationError(RuntimeError):
    pass


def _safe_artifact_path(root: Path, relative_name: str) -> Path:
    relative = Path(str(relative_name).replace("\\", "/"))
    if relative.is_absolute():
        raise ArtifactValidationError(f"artifact path traversal rejected: {relative_name}")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ArtifactValidationError(
            f"artifact path traversal rejected: {relative_name}"
        ) from exc
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    def number(name: str) -> float:
        try:
            return float(metrics.get(name) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    return {
        "rank_ic": number("Rank IC"),
        "rank_icir": number("Rank ICIR"),
        "icir": number("Rank ICIR"),
        "long_short_annual_return": number("Long-Short Ann Return"),
        "long_short_annual_sharpe": number("Long-Short Ann Sharpe"),
        "sharpe": number("1day.excess_return_with_cost.information_ratio"),
        "official_annualized_return": number(
            "1day.excess_return_with_cost.annualized_return"
        ),
        "official_information_ratio": number(
            "1day.excess_return_with_cost.information_ratio"
        ),
        "official_max_drawdown": number(
            "1day.excess_return_with_cost.max_drawdown"
        ),
        "max_drawdown": number("1day.excess_return_with_cost.max_drawdown"),
        "after_cost_long_short": number(
            "1day.excess_return_with_cost.annualized_return"
        ),
        "official_metrics": dict(metrics),
    }


def import_workflow_result(
    result: WorkflowResult,
    store: Registry,
) -> dict[str, Any]:
    if result.status != "succeeded":
        raise ArtifactValidationError(
            f"Qlib recorder result is not succeeded: {result.status}"
        )
    root = Path(result.artifact_root).resolve()
    for name in result.artifacts:
        _safe_artifact_path(root, name)
    artifacts: dict[str, str] = {}
    for name in REQUIRED_ARTIFACTS:
        path = _safe_artifact_path(root, name)
        if not path.is_file():
            raise ArtifactValidationError(f"required Qlib artifact is missing: {name}")
        artifacts[name] = _sha256(path)

    metrics = _canonical_metrics(result.metrics)
    workflow_id = "workflow_" + hashlib.sha256(
        result.recorder_id.encode("utf-8")
    ).hexdigest()[:20]
    now = utc_now()
    store.upsert_experiment(
        {
            "id": result.local_experiment_id,
            "dataset_id": result.dataset_id,
            "status": "succeeded",
            "model_type": result.model_type,
            "metrics": metrics,
            "config": {
                "handler": result.handler,
                "seed": result.seed,
                "dataset_version": result.dataset_version,
                "quality_report_id": result.quality_report_id,
                "qlib_experiment_id": result.qlib_experiment_id,
                "recorder_id": result.recorder_id,
                "config_hash": result.config_hash,
            },
            "path": str(root),
            "updated_at": now,
        }
    )
    store.upsert_workflow_run(
        {
            "id": workflow_id,
            "experiment_id": result.local_experiment_id,
            "qlib_experiment_id": result.qlib_experiment_id,
            "recorder_id": result.recorder_id,
            "dataset_version": result.dataset_version,
            "quality_report_id": result.quality_report_id,
            "handler": result.handler,
            "model_type": result.model_type,
            "seed": result.seed,
            "config_hash": result.config_hash,
            "status": "succeeded",
            "recorded_path": str(root),
            "artifacts": artifacts,
            "metrics": metrics,
            "gate": {},
            "updated_at": now,
        }
    )
    imported = store.get_workflow_run(workflow_id)
    if imported is None:
        raise RuntimeError(f"workflow import disappeared: {workflow_id}")
    return imported

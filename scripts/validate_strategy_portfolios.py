"""Deterministic F4 strategy and portfolio validation entrypoint."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant.strategy.f4_contracts import F4Blocked, F4ValidationIdentity, authority_fields
from quant.strategy.f4_dataset import validate_f4_dataset_values
from quant.strategy.f4_gate import GATE_VERSION, evaluate_f4_gate
from quant.strategy.f4_metrics import aggregate_v2_window_metrics, aggregate_window_metrics
from quant.strategy.f4_real_pipeline import (
    CANDIDATE_SPEC_VERSION,
    F4_PIPELINE_VERSION,
    run_real_f4_pipeline,
)
from quant.strategy.f4_v2_publication import (
    F4V2PublicationError,
    resolve_committed_v2_generation,
    write_v2_compatibility_projection,
)
from quant.research.publication import PublicationError, resolve_complete_artifact


@dataclass(frozen=True, slots=True)
class EvidencePaths:
    report: Path
    latest: Path
    no_op: bool
    authoritative_v2_committed: bool = False
    compatibility_projection_state: str = "completed"
    compatibility_projection_error: str | None = None


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_v2_authoritative_pointer(
    evidence_root: Path, factory_run_id: str
) -> dict[str, Any]:
    project_root = evidence_root.resolve().parents[2]
    try:
        return resolve_committed_v2_generation(
            project_root,
            expected_factory_run_id=factory_run_id,
        )
    except F4V2PublicationError as exc:
        raise RuntimeError(f"f4_v2_authoritative_pointer_invalid:{exc}") from exc


def _evidence_payloads(result: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    validation_id = str(result.get("validation_id") or "")
    authority = authority_fields()
    identity_keys = (
        "validation_id", "market_date", "factor_snapshot_id", "factor_data_version",
        "factor_universe_version", "pit_dataset_version", "pit_manifest_hash",
        "pit_quality_report_id", "industry_version", "benchmark_version",
        "pipeline_version",
        "candidate_spec_version", "portfolio_policy_version", "cost_model_version",
        "gate_version",
    )
    identity = {key: result.get(key) for key in identity_keys}
    gate_result = {
        "validation_id": validation_id,
        "status": result.get("status"),
        "reasons": list(result.get("reasons") or []),
        "reason_code": result.get("reason_code"),
        "gate_version": result.get("gate_version"),
        "metrics": dict(result.get("metrics") or {}),
        **authority,
    }
    return {
        "identity.json": {**identity, **authority},
        "window_definitions.json": {
            "validation_id": validation_id,
            "windows": list(result.get("window_definitions") or []),
            **authority,
        },
        "candidate_spec.json": {
            "validation_id": validation_id,
            **dict(result.get("candidate_spec") or {}),
            **authority,
        },
        "portfolio_policy.json": {
            "validation_id": validation_id,
            **dict(result.get("portfolio_policy") or {}),
            **authority,
        },
        "cost_model.json": {
            "validation_id": validation_id,
            **dict(result.get("cost_model") or {}),
            **authority,
        },
        "window_metrics.json": {
            "validation_id": validation_id,
            "validation_metrics": list(result.get("validation_metrics") or []),
            "window_metrics": list(result.get("window_metrics") or []),
            "stress_metrics": dict(result.get("stress_metrics") or {}),
            **authority,
        },
        "aggregate_metrics.json": {
            "validation_id": validation_id,
            "metrics": dict(result.get("metrics") or {}),
            **authority,
        },
        "gate_result.json": gate_result,
    }


def _validate_existing_evidence(target_dir: Path, validation_id: str) -> dict[str, Any]:
    required = set(_evidence_payloads({"validation_id": validation_id})) | {
        "validation_report.json"
    }
    actual = {path.name for path in target_dir.iterdir() if path.is_file()}
    if actual != required:
        raise RuntimeError("artifact_integrity_failed: evidence file set invalid")
    report = _json_object(target_dir / "validation_report.json")
    if (
        report.get("validation_id") != validation_id
        or report.get("promotion_state") != "research_only"
        or report.get("execution_authority") is not False
        or not report.get("status")
    ):
        raise RuntimeError("artifact_integrity_failed: immutable report invalid")
    hashes = report.get("artifact_hashes")
    if not isinstance(hashes, dict) or set(hashes) != required - {"validation_report.json"}:
        raise RuntimeError("artifact_integrity_failed: artifact hashes missing")
    for name, expected in hashes.items():
        path = target_dir / name
        payload = _json_object(path)
        if (
            payload.get("validation_id") != validation_id
            or payload.get("promotion_state") != "research_only"
            or payload.get("execution_authority") is not False
            or _sha256(path) != expected
        ):
            raise RuntimeError(f"artifact_integrity_failed: {name} invalid")
    return report


def _recovery_evidence_dir(
    evidence_root: Path,
    validation_id: str,
    payload: Mapping[str, Any],
) -> Path:
    stable_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"artifact_hashes", "generated_at", "no_op"}
    }
    recovery_id = hashlib.sha256(
        json.dumps(
            stable_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    return evidence_root / "recoveries" / validation_id / recovery_id


def _validated_latest_recovery(
    evidence_root: Path,
    validation_id: str,
) -> dict[str, Any] | None:
    latest = _json_object(evidence_root / "latest.json")
    if (
        latest.get("validation_id") != validation_id
        or latest.get("status") == "f4_blocked"
    ):
        return None
    artifact_value = latest.get("artifact_path")
    if type(artifact_value) is not str or not artifact_value:
        raise RuntimeError("artifact_integrity_failed: recovery artifact path missing")
    report = Path(artifact_value).resolve()
    root = evidence_root.resolve()
    try:
        report.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(
            "artifact_integrity_failed: recovery artifact path escaped"
        ) from exc
    if report.name != "validation_report.json" or not report.is_file():
        raise RuntimeError("artifact_integrity_failed: recovery report missing")
    recovered = _validate_existing_evidence(report.parent, validation_id)
    if recovered.get("status") == "f4_blocked":
        return None
    return recovered


def _latest_projection(payload: Mapping[str, Any], report: Path) -> dict[str, Any]:
    excluded_top_level = {
        "artifact_hashes",
        "validation_metrics",
    }
    projection = {
        key: value
        for key, value in payload.items()
        if key not in excluded_top_level
        and key not in {"window_metrics", "stress_metrics", "candidate_spec"}
    }
    projection["window_metrics"] = [
        {
            key: value
            for key, value in dict(row).items()
            if key not in {"equity_curve", "factor_fit"}
        }
        for row in payload.get("window_metrics") or []
    ]
    projection["stress_metrics"] = {
        str(multiplier): {
            key: value
            for key, value in dict(summary).items()
            if key != "window_metrics"
        }
        for multiplier, summary in dict(payload.get("stress_metrics") or {}).items()
    }
    candidate = dict(payload.get("candidate_spec") or {})
    projection["candidate_spec"] = {
        key: value for key, value in candidate.items() if key != "factor_fits"
    }
    projection["artifact_path"] = str(report.resolve())
    projection.update(authority_fields())
    return projection


def _enrich_v2_compatibility_projection(
    projection: Mapping[str, Any],
    resolved_generation: Mapping[str, Any],
) -> dict[str, Any]:
    """Attach UI metadata only from an already validated authoritative v2 generation."""

    report = resolved_generation.get("factory_report")
    generation_value = resolved_generation.get("generation_dir")
    if not isinstance(report, dict) or type(generation_value) is not str or not generation_value:
        raise RuntimeError("f4_v2_authoritative_projection_invalid")
    diagnostics_payload = _json_object(Path(generation_value) / "family_diagnostics.json")
    families = diagnostics_payload.get("families")
    if not isinstance(families, dict):
        raise RuntimeError("f4_v2_authoritative_projection_invalid")
    return {
        **dict(projection),
        "factory_version": report.get("factory_version"),
        "candidate_count": report.get("candidate_count"),
        "family_diagnostics": families,
    }


def write_validation_evidence(
    project_root: Path | str,
    result: Mapping[str, Any],
    *,
    compatibility_writer: Callable[[Path, Mapping[str, Any]], None] | None = None,
) -> EvidencePaths:
    root = Path(project_root)
    validation_id = str(result.get("validation_id") or "")
    if not validation_id:
        raise RuntimeError("artifact_integrity_failed: validation_id missing")
    evidence_root = root / "data" / "research" / "f4"
    factory_run_id = str(result.get("factory_run_id") or "")
    authoritative_v2_committed = False
    authoritative_v2_pointer: dict[str, Any] = {}
    if factory_run_id:
        authoritative_v2_pointer = _validate_v2_authoritative_pointer(
            evidence_root, factory_run_id
        )
        authoritative_v2_committed = True
    target_dir = evidence_root / validation_id
    latest = evidence_root / "latest.json"
    no_op = False
    payload = dict(result)
    if target_dir.exists():
        existing = _validate_existing_evidence(target_dir, validation_id)
        if (
            existing.get("status") == "f4_blocked"
            and payload.get("status") != "f4_blocked"
        ):
            target_dir = _recovery_evidence_dir(
                evidence_root, validation_id, payload
            )
        else:
            payload = existing
            no_op = True
    if not no_op and target_dir.exists():
        payload = _validate_existing_evidence(target_dir, validation_id)
        no_op = True
    report = target_dir / "validation_report.json"
    if not no_op:
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        temporary_dir = target_dir.parent / f".{target_dir.name}.{os.getpid()}.tmp"
        temporary_dir.mkdir(parents=False, exist_ok=False)
        try:
            evidence_payloads = _evidence_payloads(payload)
            for name, artifact in evidence_payloads.items():
                _atomic_json(temporary_dir / name, artifact)
            payload["artifact_hashes"] = {
                name: _sha256(temporary_dir / name) for name in evidence_payloads
            }
            _atomic_json(temporary_dir / "validation_report.json", payload)
            os.replace(temporary_dir, target_dir)
        except Exception:
            if temporary_dir.exists() and temporary_dir.parent == target_dir.parent:
                shutil.rmtree(temporary_dir)
            raise
    projection = _latest_projection(payload, report)
    if authoritative_v2_committed:
        projection = _enrich_v2_compatibility_projection(
            projection, authoritative_v2_pointer
        )
        compatibility_result = write_v2_compatibility_projection(
            root,
            expected_factory_run_id=factory_run_id,
            expected_factory_report_sha256=str(
                authoritative_v2_pointer.get("factory_report_sha256") or ""
            ),
            projection=projection,
            writer=compatibility_writer,
        )
        state = str(
            compatibility_result.get("compatibility_projection_state")
            or "failed"
        )
        return EvidencePaths(
            report=report,
            latest=latest,
            no_op=no_op,
            authoritative_v2_committed=True,
            compatibility_projection_state=state,
            compatibility_projection_error=compatibility_result.get(
                "compatibility_projection_error"
            ),
        )
    writer = compatibility_writer or _atomic_json
    try:
        writer(latest, projection)
    except Exception as exc:
        if not authoritative_v2_committed:
            raise
        return EvidencePaths(
            report=report,
            latest=latest,
            no_op=no_op,
            authoritative_v2_committed=True,
            compatibility_projection_state="failed",
            compatibility_projection_error=str(exc),
        )
    return EvidencePaths(
        report=report,
        latest=latest,
        no_op=no_op,
        authoritative_v2_committed=authoritative_v2_committed,
    )


def _identity(
    *,
    manifest: Mapping[str, Any],
    quality: Mapping[str, Any],
    industry: Mapping[str, Any],
    benchmark: Mapping[str, Any],
    factor: Mapping[str, Any],
) -> F4ValidationIdentity:
    return F4ValidationIdentity(
        market_date=str(manifest.get("end_date") or factor.get("data_end_date") or "missing")[:10],
        factor_snapshot_id=str(factor.get("snapshot_id") or "missing"),
        factor_data_version=str(factor.get("data_version") or "missing"),
        factor_universe_version=str(factor.get("universe_version") or "missing"),
        pit_dataset_version=str(manifest.get("dataset_version") or "missing"),
        pit_manifest_hash=str(
            manifest.get("manifest_content_sha256") or "missing"
        ),
        pit_quality_report_id=str(quality.get("report_id") or "missing"),
        industry_version=str(industry.get("version") or "missing"),
        benchmark_version=str(benchmark.get("version") or "missing"),
        pipeline_version=F4_PIPELINE_VERSION,
        candidate_spec_version=CANDIDATE_SPEC_VERSION,
        portfolio_policy_version="nested-window-policy-v1",
        cost_model_version="cost-model-v1",
        gate_version=GATE_VERSION,
    )


def run_validation(
    *,
    project_root: Path | str = PROJECT_ROOT,
    manifest: Mapping[str, Any] | None = None,
    quality: Mapping[str, Any] | None = None,
    industry: Mapping[str, Any] | None = None,
    benchmark: Mapping[str, Any] | None = None,
    window_metrics: Iterable[Mapping[str, object]] | None = None,
    double_cost_excess_return: float = 0.0,
) -> dict[str, Any]:
    root = Path(project_root)
    manifest_path = root / "data" / "qlib" / "datasets" / "a_share_6y_daily" / "manifest.json"
    quality_path = root / "data" / "qlib" / "datasets" / "a_share_6y_daily" / "quality_report.json"
    factor_path = root / "data" / "factor_evaluation.json"
    industry_path = root / "data" / "research" / "industry" / "pit_industry.json"
    benchmark_path = root / "data" / "research" / "benchmarks" / "000300.json"
    manifest_value = dict(manifest) if manifest is not None else _json_object(manifest_path)
    quality_value = dict(quality) if quality is not None else _json_object(quality_path)
    industry_value = dict(industry) if industry is not None else _json_object(industry_path)
    benchmark_value = dict(benchmark) if benchmark is not None else _json_object(benchmark_path)
    publication_root = root / "data" / "research" / "daily"
    if (publication_root / "latest.json").is_file():
        try:
            factor = _json_object(
                resolve_complete_artifact(publication_root, "factor_evaluation.json")
            )
        except PublicationError:
            factor = {}
    else:
        factor = _json_object(factor_path)
    identity = _identity(
        manifest=manifest_value,
        quality=quality_value,
        industry=industry_value,
        benchmark=benchmark_value,
        factor=factor,
    )

    blocked: list[str] = []
    try:
        validate_f4_dataset_values(
            manifest_value,
            quality_value,
            industry_value,
            benchmark_value,
        )
    except F4Blocked as exc:
        blocked.append(exc.reason_code)
    if not blocked and not factor:
        blocked.append("f3_evidence_missing")
    elif not blocked and (factor.get("promotion_state") != "research_only" or factor.get("execution_authority") is not False):
        blocked.append("f3_authority_invalid")
    elif not blocked and (
        str(factor.get("data_end_date") or "").replace("-", "")[:8]
        != str(manifest_value.get("end_date") or "").replace("-", "")[:8]
    ):
        blocked.append("f3_pit_date_mismatch")

    if not blocked and window_metrics is None:
        existing_dir = root / "data" / "research" / "f4" / identity.validation_id
        if existing_dir.is_dir():
            existing = _validate_existing_evidence(existing_dir, identity.validation_id)
            if existing.get("status") != "f4_blocked":
                return {**existing, "no_op": True}
            recovered = _validated_latest_recovery(
                existing_dir.parent, identity.validation_id
            )
            if recovered is not None:
                return {**recovered, "no_op": True}

    metrics: dict[str, object] = {}
    pipeline: dict[str, Any] = {}
    if not blocked:
        if window_metrics is not None:
            rows = list(window_metrics)
            metrics = aggregate_window_metrics(
                rows,
                double_cost_excess_return=double_cost_excess_return,
            )
        else:
            try:
                pipeline = run_real_f4_pipeline(
                    project_root=root,
                    manifest=manifest_value,
                    industry=industry_value,
                    benchmark=benchmark_value,
                )
                rows = list(pipeline.get("window_metrics") or [])
                double_cost = dict(pipeline.get("stress_metrics") or {}).get("2.0") or {}
                aggregate = (
                    aggregate_v2_window_metrics
                    if (pipeline.get("candidate_spec") or {}).get("version")
                    == "f4-multi-alpha-candidate-factory-v2"
                    else aggregate_window_metrics
                )
                aggregate_arguments = {
                    "double_cost_excess_return": float(double_cost.get("excess_return") or 0.0),
                    "constraint_violation_count": sum(
                        int(row.get("constraint_violation_count") or 0) for row in rows
                    ),
                    "future_data_violation_count": sum(
                        int(row.get("future_data_violation_count") or 0) for row in rows
                    ),
                }
                metrics = (
                    aggregate(
                        locked_tests=rows,
                        validation_rows=list(pipeline.get("validation_metrics") or []),
                        **aggregate_arguments,
                    )
                    if aggregate is aggregate_v2_window_metrics
                    else aggregate(rows, **aggregate_arguments)
                )
            except F4Blocked as exc:
                blocked.append(exc.reason_code)
    gate = evaluate_f4_gate(metrics, blocked)
    if (
        gate.get("status") == "f4_rejected"
        and pipeline.get("factory_run_id")
    ):
        pipeline["candidate_factory_status"] = "exhausted"
        candidate_factory = dict(pipeline.get("candidate_factory") or {})
        candidate_factory["candidate_factory_status"] = "exhausted"
        pipeline["candidate_factory"] = candidate_factory
        gate = {**gate, "display_status": "f4_rejected_exhausted"}
    metric_projection = dict(gate.get("metrics") or {})
    if metric_projection:
        metric_projection.update(
            {
                "after_cost_excess_return_pct": float(metric_projection.get("after_cost_excess_return") or 0.0) * 100,
                "double_cost_excess_return_pct": float(metric_projection.get("double_cost_excess_return") or 0.0) * 100,
                "max_drawdown_pct": float(metric_projection.get("max_drawdown") or 0.0) * 100,
            }
        )
        gate = {**gate, "metrics": metric_projection}
    projected_windows = []
    for row in list(pipeline.get("window_metrics") or []):
        projected_windows.append(
            {
                **row,
                "excess_return_pct": float(row.get("excess_return") or 0.0) * 100,
                "max_drawdown_pct": float(row.get("max_drawdown") or 0.0) * 100,
            }
        )
    return {
        "success": True,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        **identity.to_dict(),
        **gate,
        **pipeline,
        "window_metrics": projected_windows or list(pipeline.get("window_metrics") or []),
        "aggregate_metrics": metric_projection,
        "window_count": int(metric_projection.get("window_count") or 0),
        "reason_code": (gate.get("reasons") or [""])[0],
        "input_status": {
            "pit_manifest": str(manifest_value.get("status") or "missing"),
            "pit_quality": str(quality_value.get("status") or "missing"),
            "pit_industry": "present" if industry_value else "missing",
            "benchmark": "present" if benchmark_value else "missing",
            "f3_evidence": "present" if factor else "missing",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="F4 strategy portfolio validation")
    parser.add_argument("--once", action="store_true")
    parser.parse_args()
    result = run_validation(project_root=PROJECT_ROOT)
    paths = write_validation_evidence(PROJECT_ROOT, result)
    summary = {
        "success": result.get("success"),
        "generated_at": result.get("generated_at"),
        "validation_id": result.get("validation_id"),
        "status": result.get("status"),
        "reasons": result.get("reasons"),
        "metrics": result.get("metrics"),
        "panel": result.get("panel"),
        "window_count": result.get("window_count"),
        "promotion_state": result.get("promotion_state"),
        "execution_authority": result.get("execution_authority"),
        "artifact_path": str(paths.report),
        "no_op": paths.no_op,
        "authoritative_v2_committed": paths.authoritative_v2_committed,
        "publication_committed": paths.authoritative_v2_committed,
        "compatibility_projection_state": paths.compatibility_projection_state,
        "compatibility_projection_error": paths.compatibility_projection_error,
    }
    print(json.dumps(summary, ensure_ascii=False))
    if (
        result.get("success") is not True
        or result.get("status") == "f4_blocked"
        or paths.compatibility_projection_state != "completed"
    ):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

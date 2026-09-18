"""Generate one immutable, research-only daily portfolio projection."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from quant.strategy.research_selection import build_research_selection
from quant.strategy.f4_candidate_factory import FACTORY_VERSION_V2
from quant.strategy.f4_v2_publication import resolve_committed_v2_generation
from quant.data.sync_policy import load_sync_policy


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        raise RuntimeError(f"research_selection_input_missing:{path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"research_selection_input_invalid:{path}")
    return value


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(
                dict(payload),
                handle,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _generation_dir_from_env() -> Path | None:
    value = str(os.environ.get("XUANJI_RESEARCH_GENERATION_DIR") or "").strip()
    return Path(value).resolve() if value else None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_v2_candidate_spec(
    project_root: Path,
    f4_latest: Mapping[str, Any],
) -> dict[str, Any]:
    factory_run_id = str(f4_latest.get("factory_run_id") or "")
    validation_id = str(f4_latest.get("validation_id") or "")
    if (
        not factory_run_id
        or not validation_id
        or f4_latest.get("factory_version") != FACTORY_VERSION_V2
        or f4_latest.get("candidate_spec_version") != FACTORY_VERSION_V2
    ):
        raise RuntimeError("f4_v2_selection_identity_invalid")
    resolved = resolve_committed_v2_generation(
        project_root,
        expected_factory_run_id=factory_run_id,
    )
    report = resolved.get("factory_report")
    pipeline = report.get("pipeline_result") if isinstance(report, dict) else None
    source = pipeline.get("candidate_spec") if isinstance(pipeline, dict) else None
    if (
        not isinstance(source, dict)
        or source.get("version") != FACTORY_VERSION_V2
        or source.get("factory_run_id") != factory_run_id
        or source.get("promotion_state") != "research_only"
        or source.get("execution_authority") is not False
    ):
        raise RuntimeError("f4_v2_candidate_spec_invalid")
    generation_dir = Path(str(resolved.get("generation_dir") or "")).resolve()
    model_payload = _read_object(generation_dir / "model_artifacts.json")
    if (
        model_payload.get("factory_run_id") != factory_run_id
        or model_payload.get("promotion_state") != "research_only"
        or model_payload.get("execution_authority") is not False
        or not isinstance(model_payload.get("models"), list)
    ):
        raise RuntimeError("f4_v2_model_artifacts_invalid")
    candidate_spec = dict(source)
    fits = [dict(item) for item in source.get("factor_fits") or []]
    if not fits:
        raise RuntimeError("f4_factor_fit_missing")
    fit = fits[-1]
    fit_path_value = fit.get("alpha_fit_path")
    fit_hash = str(fit.get("alpha_fit_artifact_hash") or "")
    if type(fit_path_value) is not str or not fit_path_value or not fit_hash:
        raise RuntimeError("f4_alpha_fit_artifact_missing")
    fit_path = Path(fit_path_value).resolve()
    if not fit_path.is_file() or _sha256_file(fit_path) != fit_hash:
        raise RuntimeError("f4_alpha_fit_artifact_invalid")
    fit_payload = _read_object(fit_path)
    selected_signals = fit_payload.get("selected_signals")
    if not isinstance(selected_signals, list) or not selected_signals:
        raise RuntimeError("f4_qlib_daily_inference_unavailable")
    if (
        fit_payload.get("window_id") != fit.get("window_id")
        or fit_payload.get("candidate_id") != fit.get("candidate_id")
        or fit_payload.get("artifact_hash") != fit.get("alpha_fit_hash")
    ):
        raise RuntimeError("f4_alpha_fit_identity_mismatch")
    fit.update(
        {
            "fit_end": fit_payload.get("fit_end"),
            "factors": list(selected_signals),
            "directions": dict(fit_payload.get("directions") or {}),
            "weights": dict(fit_payload.get("weights") or {}),
            "median_rank_ic": dict(fit_payload.get("median_rank_ic") or {}),
            "direction_consistency": dict(
                fit_payload.get("direction_consistency") or {}
            ),
        }
    )
    fits[-1] = fit
    candidate_spec["factor_fits"] = fits
    candidate_spec["model_artifacts"] = list(model_payload["models"])
    candidate_spec["validation_id"] = validation_id
    return candidate_spec


def _load_candidate_spec(
    project_root: Path,
    f4_latest: Mapping[str, Any],
) -> dict[str, Any]:
    if (
        f4_latest.get("factory_version") == FACTORY_VERSION_V2
        or f4_latest.get("candidate_spec_version") == FACTORY_VERSION_V2
    ):
        return _load_v2_candidate_spec(project_root, f4_latest)
    validation_id = str(f4_latest.get("validation_id") or "")
    return _read_object(
        project_root
        / "data"
        / "research"
        / "f4"
        / validation_id
        / "candidate_spec.json"
    )


def _load_reusable_f4_evidence(
    project_root: Path,
    f4_latest: Mapping[str, Any],
    *,
    target_date: str,
) -> dict[str, Any]:
    """Keep a selection-bound committed F4 when a newer retry is only blocked."""

    current = dict(f4_latest)
    if (
        current.get("status") == "f4_rejected"
        and current.get("candidate_spec_version") == FACTORY_VERSION_V2
        and current.get("factory_run_id")
        and current.get("validation_id")
    ):
        return current
    try:
        prior_selection = _read_object(
            project_root
            / "data"
            / "research"
            / "experimental_selections"
            / "latest.json"
        )
    except RuntimeError:
        return current
    validation_id = str(prior_selection.get("f4_validation_id") or "")
    factory_run_id = str(prior_selection.get("f4_factory_run_id") or "")
    if (
        prior_selection.get("selection_status") != "experimental_research_portfolio"
        or prior_selection.get("promotion_state") != "research_only"
        or prior_selection.get("execution_authority") is not False
        or not validation_id
        or not factory_run_id
    ):
        return current
    try:
        report = _read_object(
            project_root
            / "data"
            / "research"
            / "f4"
            / validation_id
            / "validation_report.json"
        )
    except RuntimeError:
        return current
    if (
        report.get("status") != "f4_rejected"
        or report.get("validation_id") != validation_id
        or report.get("factory_run_id") != factory_run_id
        or report.get("candidate_spec_version") != FACTORY_VERSION_V2
        or report.get("promotion_state") != "research_only"
        or report.get("execution_authority") is not False
    ):
        return current
    try:
        target = datetime.strptime(str(target_date).replace("-", "")[:8], "%Y%m%d")
        validated = datetime.strptime(
            str(report.get("market_date") or "").replace("-", "")[:8], "%Y%m%d"
        )
        maximum_age_days = load_sync_policy()["f4_strategy"].stale_after_ms / 86_400_000
    except (KeyError, TypeError, ValueError):
        return current
    age_days = (target - validated).days
    if age_days < 0 or age_days > maximum_age_days:
        return current
    return {
        **report,
        "factory_version": FACTORY_VERSION_V2,
        "evidence_source": "prior_selection_bound_committed_f4",
    }


def generate_once(
    *,
    root: str | Path = PROJECT_ROOT,
    generated_at: str | None = None,
    factor_snapshot_path: str | Path | None = None,
    factor_evaluation_path: str | Path | None = None,
    selection_output_path: str | Path | None = None,
) -> dict[str, Any]:
    project_root = Path(root).resolve()
    generation_dir = _generation_dir_from_env()
    factor_snapshot_source = (
        Path(factor_snapshot_path).resolve()
        if factor_snapshot_path is not None
        else generation_dir / "factor_snapshot_latest.json"
        if generation_dir is not None
        else project_root / "data" / "factor_snapshot_latest.json"
    )
    factor_evaluation_source = (
        Path(factor_evaluation_path).resolve()
        if factor_evaluation_path is not None
        else generation_dir / "factor_evaluation.json"
        if generation_dir is not None
        else project_root / "data" / "factor_evaluation.json"
    )
    explicit_selection_output = (
        Path(selection_output_path).resolve()
        if selection_output_path is not None
        else generation_dir / "selection.json"
        if generation_dir is not None
        else None
    )
    factor_snapshot = _read_object(factor_snapshot_source)
    factor_evaluation = _read_object(factor_evaluation_source)
    f4_latest = _load_reusable_f4_evidence(
        project_root,
        _read_object(project_root / "data" / "research" / "f4" / "latest.json"),
        target_date=str(
            factor_snapshot.get("as_of") or factor_snapshot.get("latest_kline_date") or ""
        ),
    )
    candidate_spec = _load_candidate_spec(project_root, f4_latest)
    industry = _read_object(
        project_root / "data" / "research" / "industry" / "pit_industry.json"
    )
    timestamp = generated_at or datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(
        timespec="seconds"
    )
    candidate = build_research_selection(
        factor_snapshot=factor_snapshot,
        factor_evaluation=factor_evaluation,
        f4_latest=f4_latest,
        candidate_spec=candidate_spec,
        industry_records=industry.get("records") or [],
        generated_at=timestamp,
    )
    if explicit_selection_output is not None:
        payload = candidate
        _atomic_json(explicit_selection_output, payload)
    else:
        selection_root = project_root / "data" / "research" / "selections"
        versioned = selection_root / candidate["portfolio_id"] / "portfolio.json"
        if versioned.is_file():
            payload = _read_object(versioned)
            if payload.get("portfolio_id") != candidate["portfolio_id"]:
                raise RuntimeError("research_selection_identity_collision")
        else:
            payload = candidate
            _atomic_json(versioned, payload)
        _atomic_json(selection_root / "latest.json", payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="确定性每日研究选股组合")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--factor-snapshot-path")
    parser.add_argument("--factor-evaluation-path")
    parser.add_argument("--selection-output-path")
    args = parser.parse_args()
    try:
        result = generate_once(
            factor_snapshot_path=args.factor_snapshot_path,
            factor_evaluation_path=args.factor_evaluation_path,
            selection_output_path=args.selection_output_path,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "reason_code": getattr(exc, "reason_code", type(exc).__name__),
                    "error": str(exc),
                    "promotion_state": "research_only",
                    "execution_authority": False,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return 1
    print(
        json.dumps(
            {
                "success": True,
                "portfolio_id": result["portfolio_id"],
                "selection_date": result["selection_date"],
                "position_count": result["position_count"],
                "selection_status": result["selection_status"],
                "promotion_state": "research_only",
                "execution_authority": False,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

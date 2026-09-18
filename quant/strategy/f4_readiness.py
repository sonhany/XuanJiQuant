"""Lightweight, read-only readiness projection for the next F4 validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from quant.research.publication import PublicationError, resolve_complete_generation
from quant.strategy.f4_contracts import F4Blocked
from quant.strategy.f4_dataset import validate_f4_dataset_values


def _date(value: object) -> str:
    compact = str(value or "").replace("-", "")[:8]
    return (
        f"{compact[:4]}-{compact[4:6]}-{compact[6:8]}"
        if len(compact) == 8 and compact.isdigit()
        else ""
    )


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def evaluate_f4_readiness(
    *,
    manifest: Mapping[str, Any],
    quality: Mapping[str, Any],
    industry: Mapping[str, Any],
    benchmark: Mapping[str, Any],
    factor_publication: Mapping[str, Any],
    f4_projection: Mapping[str, Any],
) -> dict[str, Any]:
    """Separate current prerequisites from the latest immutable F4 evidence."""

    daily_date = _date(factor_publication.get("target_date"))
    manifest_version = str(manifest.get("dataset_version") or "")
    quality_matches = bool(
        manifest_version
        and str(quality.get("dataset_version") or "") == manifest_version
    )
    pit_market_date = (
        _date(
            quality.get("data_latest_date")
            or quality.get("expected_latest_date")
            or manifest.get("end_date")
        )
        if quality_matches
        else ""
    )
    evidence_date = _date(f4_projection.get("market_date"))
    base = {
        "schema_version": "f4-readiness-v1",
        "daily_market_date": daily_date,
        "pit_market_date": pit_market_date,
        "pit_target_date": _date(manifest.get("end_date")),
        "f4_evidence_market_date": evidence_date,
        "f4_generated_at": str(f4_projection.get("generated_at") or ""),
        "pit_dataset_version": manifest_version,
        "pit_manifest_status": str(manifest.get("status") or "missing"),
        "pit_progress": {
            "processed": int(manifest.get("processed") or 0),
            "requested": int(manifest.get("requested") or 0),
        },
        "promotion_state": "research_only",
        "execution_authority": False,
    }
    try:
        validate_f4_dataset_values(manifest, quality, industry, benchmark)
    except F4Blocked as exc:
        return {
            **base,
            "status": "blocked",
            "reason_code": exc.reason_code,
            "trigger_required": False,
        }
    if (
        factor_publication.get("promotion_state") != "research_only"
        or factor_publication.get("execution_authority") is not False
        or not daily_date
    ):
        return {
            **base,
            "status": "blocked",
            "reason_code": "factor_prerequisite_missing",
            "trigger_required": False,
        }
    if not pit_market_date or daily_date != pit_market_date:
        return {
            **base,
            "status": "blocked",
            "reason_code": "f3_pit_date_mismatch",
            "trigger_required": False,
        }
    if evidence_date == pit_market_date:
        return {
            **base,
            "status": "current",
            "reason_code": "",
            "trigger_required": False,
        }
    return {
        **base,
        "status": "ready",
        "reason_code": "f4_revalidation_due",
        "trigger_required": True,
    }


def build_f4_readiness(project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root)
    dataset = root / "data" / "qlib" / "datasets" / "a_share_6y_daily"
    publication_root = root / "data" / "research" / "daily"
    try:
        factor_publication = resolve_complete_generation(publication_root)["pointer"]
    except (PublicationError, OSError, KeyError, TypeError, ValueError):
        factor_publication = {}
    return evaluate_f4_readiness(
        manifest=_json(dataset / "manifest.json"),
        quality=_json(dataset / "quality_report.json"),
        industry=_json(root / "data" / "research" / "industry" / "pit_industry.json"),
        benchmark=_json(root / "data" / "research" / "benchmarks" / "000300.json"),
        factor_publication=factor_publication,
        f4_projection=_json(root / "data" / "research" / "f4" / "latest.json"),
    )

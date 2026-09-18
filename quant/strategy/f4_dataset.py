"""Point-in-time dataset gates for F4 strategy research."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from quant.factor.fundamental import FUNDAMENTAL_FACTORS

from .f4_contracts import F4Blocked


@dataclass(frozen=True, slots=True)
class F4DatasetRefs:
    pit_dataset_version: str
    adjustment_schema_version: str
    industry_version: str
    benchmark_code: str
    benchmark_version: str


def _read_json(path: Path | str | None, reason_code: str) -> dict:
    if path is None:
        raise F4Blocked(reason_code)
    target = Path(path)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise F4Blocked(reason_code, str(exc)) from exc
    if not isinstance(value, dict):
        raise F4Blocked(reason_code, "expected JSON object")
    return value


def load_f4_dataset_refs(
    manifest_path: Path | str,
    quality_path: Path | str,
    industry_path: Path | str | None,
    benchmark_path: Path | str | None,
) -> F4DatasetRefs:
    manifest = _read_json(manifest_path, "pit_manifest_missing")
    if manifest.get("status") != "complete":
        raise F4Blocked(
            "pit_manifest_incomplete", f"status={manifest.get('status') or 'missing'}"
        )
    if not manifest.get("dataset_version"):
        raise F4Blocked("pit_dataset_version_missing")
    if not manifest.get("adjustment_schema_version"):
        raise F4Blocked("corporate_action_schema_mismatch", "version missing")
    quality = _read_json(quality_path, "pit_quality_missing")
    if quality.get("status") != "passed":
        raise F4Blocked(
            "pit_quality_failed", f"status={quality.get('status') or 'missing'}"
        )
    if str(quality.get("dataset_version") or "") != str(
        manifest.get("dataset_version") or ""
    ):
        raise F4Blocked("pit_quality_version_mismatch")
    industry = _read_json(industry_path, "pit_industry_missing")
    benchmark = _read_json(benchmark_path, "benchmark_missing")
    return validate_f4_dataset_values(manifest, quality, industry, benchmark)


def validate_f4_dataset_values(
    manifest: Mapping[str, object],
    quality: Mapping[str, object],
    industry: Mapping[str, object],
    benchmark: Mapping[str, object],
) -> F4DatasetRefs:
    """Validate already-loaded F4 references without weakening the file gate."""
    if manifest.get("status") != "complete":
        raise F4Blocked(
            "pit_manifest_incomplete", f"status={manifest.get('status') or 'missing'}"
        )
    dataset_version = str(manifest.get("dataset_version") or "")
    if not dataset_version:
        raise F4Blocked("pit_dataset_version_missing")
    adjustment = str(manifest.get("adjustment_schema_version") or "")
    if not adjustment:
        raise F4Blocked("corporate_action_schema_mismatch", "version missing")

    if quality.get("status") != "passed":
        raise F4Blocked(
            "pit_quality_failed", f"status={quality.get('status') or 'missing'}"
        )
    if str(quality.get("dataset_version") or "") != dataset_version:
        raise F4Blocked("pit_quality_version_mismatch")

    if industry.get("effective_dated") is not True:
        raise F4Blocked("pit_industry_missing", "effective dates required")
    if float(industry.get("coverage") or 0.0) < 0.95:
        raise F4Blocked("pit_industry_missing", "coverage below 0.95")
    industry_version = str(industry.get("version") or "")
    if not industry_version:
        raise F4Blocked("pit_industry_missing", "version missing")

    if float(benchmark.get("coverage") or 0.0) < 0.99:
        if not benchmark:
            raise F4Blocked("benchmark_missing")
        raise F4Blocked("benchmark_coverage_failed")
    benchmark_code = str(benchmark.get("code") or "")
    benchmark_version = str(benchmark.get("version") or "")
    if not benchmark_code or not benchmark_version:
        raise F4Blocked("benchmark_missing", "code/version missing")

    return F4DatasetRefs(
        pit_dataset_version=dataset_version,
        adjustment_schema_version=adjustment,
        industry_version=industry_version,
        benchmark_code=benchmark_code,
        benchmark_version=benchmark_version,
    )


def eligible_factor_names(
    names: Iterable[str], *, financial_pit_passed: bool
) -> tuple[list[str], dict[str, str]]:
    fundamentals = set(FUNDAMENTAL_FACTORS)
    eligible: list[str] = []
    excluded: dict[str, str] = {}
    for raw in names:
        name = str(raw)
        if name in fundamentals and not financial_pit_passed:
            excluded[name] = "financial_pit_missing"
        else:
            eligible.append(name)
    return eligible, excluded

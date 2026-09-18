import json

import pytest

from quant.strategy.f4_contracts import F4Blocked
from quant.strategy.f4_dataset import eligible_factor_names, load_f4_dataset_refs


def _write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_incomplete_manifest_blocks_real_validation(tmp_path):
    manifest = _write(
        tmp_path / "manifest.json",
        {"status": "incomplete", "dataset_version": "pit-v1"},
    )
    quality = _write(
        tmp_path / "quality.json",
        {"status": "passed", "dataset_version": "pit-v1"},
    )
    with pytest.raises(F4Blocked, match="pit_manifest_incomplete"):
        load_f4_dataset_refs(manifest, quality, None, None)


def test_dataset_quality_and_versions_must_match(tmp_path):
    manifest = _write(
        tmp_path / "manifest.json",
        {
            "status": "complete",
            "dataset_version": "pit-v1",
            "adjustment_schema_version": "adj-v1",
        },
    )
    quality = _write(
        tmp_path / "quality.json",
        {"status": "passed", "dataset_version": "pit-v2"},
    )
    with pytest.raises(F4Blocked, match="pit_quality_version_mismatch"):
        load_f4_dataset_refs(manifest, quality, None, None)


def test_complete_dataset_requires_effective_industry_and_benchmark(tmp_path):
    manifest = _write(
        tmp_path / "manifest.json",
        {
            "status": "complete",
            "dataset_version": "pit-v1",
            "adjustment_schema_version": "adj-v1",
        },
    )
    quality = _write(
        tmp_path / "quality.json",
        {"status": "passed", "dataset_version": "pit-v1"},
    )
    industry = _write(
        tmp_path / "industry.json",
        {
            "version": "industry-v1",
            "coverage": 0.96,
            "effective_dated": True,
        },
    )
    benchmark = _write(
        tmp_path / "benchmark.json",
        {"code": "000300", "version": "csi300-v1", "coverage": 1.0},
    )
    refs = load_f4_dataset_refs(manifest, quality, industry, benchmark)
    assert refs.pit_dataset_version == "pit-v1"
    assert refs.industry_version == "industry-v1"
    assert refs.benchmark_version == "csi300-v1"


def test_fundamental_factors_require_announcement_date_pit():
    factors, excluded = eligible_factor_names(
        ["ret_20", "roe"], financial_pit_passed=False
    )
    assert factors == ["ret_20"]
    assert excluded == {"roe": "financial_pit_missing"}

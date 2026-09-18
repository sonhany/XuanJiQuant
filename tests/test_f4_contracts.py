from quant.strategy.f4_contracts import (
    F4Blocked,
    F4ValidationIdentity,
    authority_fields,
)


def _identity(**overrides):
    values = {
        "market_date": "2026-08-14",
        "factor_snapshot_id": "snap-1",
        "factor_data_version": "factor-v1",
        "factor_universe_version": "universe-v1",
        "pit_dataset_version": "pit-v1",
        "pit_manifest_hash": "manifest-hash-v1",
        "pit_quality_report_id": "quality-report-v1",
        "industry_version": "industry-v1",
        "benchmark_version": "benchmark-v1",
        "pipeline_version": "pipeline-v1",
        "candidate_spec_version": "candidate-v1",
        "portfolio_policy_version": "portfolio-v1",
        "cost_model_version": "cost-v1",
        "gate_version": "f4-gate-v1",
    }
    values.update(overrides)
    return F4ValidationIdentity(**values)


def test_identity_changes_when_any_governance_version_changes():
    first = _identity()
    variants = [
        _identity(pit_manifest_hash="manifest-hash-v2"),
        _identity(pit_quality_report_id="quality-report-v2"),
        _identity(industry_version="industry-v2"),
        _identity(benchmark_version="benchmark-v2"),
        _identity(pipeline_version="pipeline-v2"),
    ]
    assert all(first.validation_id != variant.validation_id for variant in variants)
    assert first.to_dict()["validation_id"] == first.validation_id


def test_authority_is_always_research_only():
    assert authority_fields() == {
        "promotion_state": "research_only",
        "execution_authority": False,
    }


def test_blocked_error_has_stable_reason_code():
    error = F4Blocked("pit_manifest_incomplete", "status=incomplete")
    assert error.reason_code == "pit_manifest_incomplete"
    assert str(error) == "pit_manifest_incomplete: status=incomplete"

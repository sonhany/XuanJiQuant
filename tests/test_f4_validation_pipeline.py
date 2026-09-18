import json
from pathlib import Path

import pytest

import scripts.validate_strategy_portfolios as validator
from quant.strategy.f4_contracts import F4Blocked
from quant.strategy.f4_v2_publication import publish_v2_generation
from scripts.validate_strategy_portfolios import (
    run_validation,
    write_validation_evidence,
)
from tests.test_f4_v2_publication import _complete_staging, _factory_id


def _complete_factor_evidence(root):
    data_dir = root / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "factor_evaluation.json").write_text(
        json.dumps(
            {
                "snapshot_id": "factor-snapshot",
                "data_version": "data-v1",
                "universe_version": "universe-v1",
                "data_end_date": "2026-08-14",
                "promotion_state": "research_only",
                "execution_authority": False,
            }
        ),
        encoding="utf-8",
    )


def _complete_inputs():
    return {
        "manifest": {
            "status": "complete",
            "dataset_version": "pit-v1",
            "end_date": "2026-08-14",
            "adjustment_schema_version": "adj-v1",
            "manifest_content_sha256": "manifest-hash-v1",
        },
        "quality": {
            "status": "passed",
            "dataset_version": "pit-v1",
            "report_id": "quality-report-v1",
        },
        "industry": {
            "effective_dated": True,
            "coverage": 0.99,
            "version": "industry-v1",
        },
        "benchmark": {
            "coverage": 1.0,
            "code": "000300",
            "version": "benchmark-v1",
        },
    }


def _fake_real_pipeline(**_kwargs):
    windows = [
        {
            "window_id": f"wf-{index:02d}",
            "after_cost_return": 0.04,
            "benchmark_return": 0.01,
            "excess_return": 0.03,
            "sharpe": 1.1,
            "max_drawdown": -0.08,
            "constraint_violation_count": 0,
            "future_data_violation_count": 0,
        }
        for index in range(1, 5)
    ]
    return {
        "panel": {"panel_id": "panel-v1", "row_count": 1000},
        "window_definitions": [{"window_id": row["window_id"]} for row in windows],
        "candidate_spec": {"version": "ic-weighted-top20-v1"},
        "portfolio_policy": {"version": "portfolio-policy-v1"},
        "cost_model": {"version": "cost-model-v1"},
        "window_metrics": windows,
        "stress_metrics": {
            "1.0": {"window_metrics": windows, "excess_return": 0.12},
            "1.5": {"window_metrics": windows, "excess_return": 0.10},
            "2.0": {"window_metrics": windows, "excess_return": 0.08},
        },
    }


def test_current_incomplete_manifest_returns_blocked(tmp_path):
    result = run_validation(
        project_root=tmp_path,
        manifest={"status": "incomplete", "dataset_version": "pit-v1"},
        quality={},
    )
    assert result["status"] == "f4_blocked"
    assert result["reasons"] == ["pit_manifest_incomplete"]
    assert result["execution_authority"] is False


def test_evidence_is_immutable_and_latest_is_a_projection(tmp_path):
    result = {
        "validation_id": "abc",
        "status": "f4_blocked",
        "reasons": ["pit_manifest_incomplete"],
        "promotion_state": "research_only",
        "execution_authority": False,
    }
    paths = write_validation_evidence(tmp_path, result)
    assert json.loads(paths.report.read_text())["validation_id"] == "abc"
    assert json.loads(paths.latest.read_text())["validation_id"] == "abc"
    assert paths.report != paths.latest
    assert {path.name for path in paths.report.parent.iterdir()} == {
        "identity.json",
        "window_definitions.json",
        "candidate_spec.json",
        "portfolio_policy.json",
        "cost_model.json",
        "window_metrics.json",
        "aggregate_metrics.json",
        "gate_result.json",
        "validation_report.json",
    }


def test_existing_identity_is_validated_before_no_op(tmp_path):
    result = {
        "validation_id": "abc",
        "status": "f4_blocked",
        "reasons": ["pit_manifest_incomplete"],
        "promotion_state": "research_only",
        "execution_authority": False,
    }
    first = write_validation_evidence(tmp_path, result)
    second = write_validation_evidence(tmp_path, result)
    assert second.no_op is True
    first.report.write_text("{}", encoding="utf-8")
    try:
        write_validation_evidence(tmp_path, result)
    except RuntimeError as exc:
        assert "artifact_integrity_failed" in str(exc)
    else:
        raise AssertionError("corrupt immutable report was accepted")


def test_successful_retry_preserves_blocked_history_and_publishes_recovery(tmp_path):
    blocked = {
        "validation_id": "abc-recovery",
        "status": "f4_blocked",
        "reasons": ["candidate_score_contract_invalid"],
        "promotion_state": "research_only",
        "execution_authority": False,
    }
    recovered = {
        **blocked,
        "status": "f4_rejected",
        "reasons": ["sharpe_below_0_80"],
        "reason_code": "sharpe_below_0_80",
    }

    first = write_validation_evidence(tmp_path, blocked)
    second = write_validation_evidence(tmp_path, recovered)

    assert second.no_op is False
    assert second.report.parent != first.report.parent
    assert json.loads(first.report.read_text(encoding="utf-8"))["status"] == "f4_blocked"
    assert json.loads(second.report.read_text(encoding="utf-8"))["status"] == "f4_rejected"
    latest = json.loads(second.latest.read_text(encoding="utf-8"))
    assert latest["status"] == "f4_rejected"
    assert Path(latest["artifact_path"]).resolve() == second.report.resolve()

    third = write_validation_evidence(tmp_path, recovered)
    assert third.no_op is True
    assert third.report == second.report


def test_latest_projection_omits_heavy_curves_but_keeps_window_and_stress_summary(tmp_path):
    result = {
        "validation_id": "summary-test",
        "status": "f4_rejected",
        "reasons": ["sharpe_below_0_80"],
        "metrics": {"window_count": 1, "sharpe": 0.2},
        "window_metrics": [
            {
                "window_id": "wf-01",
                "excess_return": -0.1,
                "equity_curve": [{"date": "2024-01-01", "equity": 1.0}],
                "factor_fit": {"factors": ["ret_5"]},
            }
        ],
        "stress_metrics": {
            "2.0": {
                "excess_return": -0.2,
                "window_metrics": [{"window_id": "wf-01", "equity_curve": [1, 2]}],
            }
        },
        "promotion_state": "research_only",
        "execution_authority": False,
    }

    paths = write_validation_evidence(tmp_path, result)
    latest = json.loads(paths.latest.read_text(encoding="utf-8"))

    assert latest["window_metrics"][0]["window_id"] == "wf-01"
    assert "equity_curve" not in latest["window_metrics"][0]
    assert "factor_fit" not in latest["window_metrics"][0]
    assert latest["stress_metrics"]["2.0"]["excess_return"] == -0.2
    assert "window_metrics" not in latest["stress_metrics"]["2.0"]
    assert latest["artifact_path"].endswith("validation_report.json")


def test_complete_pit_cannot_bypass_missing_benchmark(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "factor_evaluation.json").write_text(
        json.dumps(
            {
                "snapshot_id": "factor-snapshot",
                "data_version": "data-v1",
                "universe_version": "universe-v1",
                "promotion_state": "research_only",
                "execution_authority": False,
            }
        ),
        encoding="utf-8",
    )
    result = run_validation(
        project_root=tmp_path,
        manifest={
            "status": "complete",
            "dataset_version": "pit-v1",
            "adjustment_schema_version": "adj-v1",
            "manifest_content_sha256": "manifest-hash-v1",
        },
        quality={
            "status": "passed",
            "dataset_version": "pit-v1",
            "report_id": "quality-report-v1",
        },
        industry={"effective_dated": True, "coverage": 0.99, "version": "industry-v1"},
        benchmark={},
        window_metrics=[
            {
                "after_cost_return": 0.10,
                "benchmark_return": 0.02,
                "excess_return": 0.08,
                "sharpe": 1.0,
                "max_drawdown": -0.10,
                "constraint_violations": 0,
            }
        ] * 4,
        double_cost_excess_return=0.01,
    )
    assert result["status"] == "f4_blocked"
    assert result["reasons"] == ["benchmark_missing"]
    assert result["pit_manifest_hash"] == "manifest-hash-v1"
    assert result["pit_quality_report_id"] == "quality-report-v1"
    assert result["industry_version"] == "industry-v1"


def test_complete_inputs_run_real_windows_without_injected_metrics(tmp_path, monkeypatch):
    _complete_factor_evidence(tmp_path)
    monkeypatch.setattr(validator, "run_real_f4_pipeline", _fake_real_pipeline)

    result = run_validation(project_root=tmp_path, **_complete_inputs())

    assert result["status"] == "f4_research_candidate"
    assert result["metrics"]["window_count"] == 4
    assert result["window_count"] == 4
    assert result["stress_metrics"]["2.0"]["excess_return"] == 0.08
    assert result["promotion_state"] == "research_only"
    assert result["execution_authority"] is False


def test_factor_evidence_date_must_match_pit_dataset_end_date(tmp_path, monkeypatch):
    _complete_factor_evidence(tmp_path)
    factor_path = tmp_path / "data" / "factor_evaluation.json"
    factor = json.loads(factor_path.read_text(encoding="utf-8"))
    factor["data_end_date"] = "2026-08-19"
    factor_path.write_text(json.dumps(factor), encoding="utf-8")
    monkeypatch.setattr(
        validator,
        "run_real_f4_pipeline",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("mismatched dates ran F4")),
    )

    result = run_validation(project_root=tmp_path, **_complete_inputs())

    assert result["status"] == "f4_blocked"
    assert result["reason_code"] == "f3_pit_date_mismatch"


def test_same_identity_validates_evidence_before_skipping_real_pipeline(tmp_path, monkeypatch):
    _complete_factor_evidence(tmp_path)
    monkeypatch.setattr(validator, "run_real_f4_pipeline", _fake_real_pipeline)
    first = run_validation(project_root=tmp_path, **_complete_inputs())
    write_validation_evidence(tmp_path, first)

    def unexpected_pipeline(**_kwargs):
        raise AssertionError("same validated identity reran the expensive pipeline")

    monkeypatch.setattr(validator, "run_real_f4_pipeline", unexpected_pipeline)
    second = run_validation(project_root=tmp_path, **_complete_inputs())

    assert second["validation_id"] == first["validation_id"]
    assert second["status"] == "f4_research_candidate"
    assert second["no_op"] is True


def test_same_identity_retries_prior_blocked_pipeline_evidence(tmp_path, monkeypatch):
    _complete_factor_evidence(tmp_path)
    monkeypatch.setattr(
        validator,
        "run_real_f4_pipeline",
        lambda **_kwargs: (_ for _ in ()).throw(F4Blocked("pit_panel_version_mismatch")),
    )
    first = run_validation(project_root=tmp_path, **_complete_inputs())
    write_validation_evidence(tmp_path, first)
    assert first["status"] == "f4_blocked"

    monkeypatch.setattr(validator, "run_real_f4_pipeline", _fake_real_pipeline)
    second = run_validation(project_root=tmp_path, **_complete_inputs())

    assert second["status"] == "f4_research_candidate"
    assert second.get("no_op") is not True
    write_validation_evidence(tmp_path, second)

    monkeypatch.setattr(
        validator,
        "run_real_f4_pipeline",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("recovered validation evidence reran the expensive pipeline")
        ),
    )
    third = run_validation(project_root=tmp_path, **_complete_inputs())
    assert third["status"] == "f4_research_candidate"
    assert third["no_op"] is True


def test_v2_compatibility_projection_requires_matching_authoritative_pointer(tmp_path):
    result = {
        "validation_id": "v2-validation",
        "factory_run_id": "a" * 64,
        "status": "f4_rejected",
        "reasons": ["sharpe_below_0_80"],
        "promotion_state": "research_only",
        "execution_authority": False,
    }

    try:
        write_validation_evidence(tmp_path, result)
    except RuntimeError as exc:
        assert "f4_v2_authoritative_pointer_invalid" in str(exc)
    else:
        raise AssertionError("v2 compatibility projection bypassed authoritative pointer")
    assert not (tmp_path / "data" / "research" / "f4" / "latest.json").exists()


def test_v2_compatibility_failure_is_reported_after_pointer_commit(tmp_path):
    factory_run_id = _factory_id("validation-compatibility-failure")
    handle = _complete_staging(tmp_path, factory_run_id=factory_run_id)
    publish_v2_generation(handle)
    pointer_path = handle.factory_root / "latest.json"
    result = {
        "validation_id": "v2-validation",
        "factory_run_id": factory_run_id,
        "status": "f4_rejected",
        "reasons": ["sharpe_below_0_80"],
        "promotion_state": "research_only",
        "execution_authority": False,
    }

    def fail_compatibility(_path, _payload):
        raise OSError("compatibility latest locked")

    paths = write_validation_evidence(
        tmp_path, result, compatibility_writer=fail_compatibility
    )

    assert paths.authoritative_v2_committed is True
    assert paths.compatibility_projection_state == "failed"
    assert "compatibility latest locked" in paths.compatibility_projection_error
    assert json.loads(pointer_path.read_text())["factory_run_id"] == factory_run_id
    assert paths.report.is_file()


def test_v2_compatibility_projection_carries_authoritative_factory_metadata(tmp_path):
    factory_run_id = _factory_id("validation-projection-metadata")
    handle = _complete_staging(tmp_path, factory_run_id=factory_run_id)
    publish_v2_generation(handle)

    paths = write_validation_evidence(
        tmp_path,
        {
            "validation_id": "v2-validation",
            "factory_run_id": factory_run_id,
            "candidate_spec_version": "f4-multi-alpha-candidate-factory-v2",
            "candidate_spec": {
                "version": "f4-multi-alpha-candidate-factory-v2",
                "selection_locks": [{"window_id": "wf-01"}],
            },
            "candidate_count": 24,
            "status": "f4_rejected",
            "reasons": ["sharpe_below_0_80"],
            "promotion_state": "research_only",
            "execution_authority": False,
        },
    )

    latest = json.loads(paths.latest.read_text(encoding="utf-8"))
    assert latest["factory_version"] == "f4-multi-alpha-candidate-factory-v2"
    assert set(latest["family_diagnostics"]) == {
        "momentum",
        "reversal",
        "defensive",
        "liquidity",
        "ensemble",
        "qlib",
    }


@pytest.mark.parametrize("mutation", ["missing_artifact", "forged_report"])
def test_validation_entrypoint_revalidates_complete_v2_generation(tmp_path, mutation):
    factory_run_id = _factory_id(f"validation-{mutation}")
    handle = _complete_staging(tmp_path, factory_run_id=factory_run_id)
    publish_v2_generation(handle)
    if mutation == "missing_artifact":
        (handle.final_dir / "family_diagnostics.json").unlink()
    else:
        report_path = handle.final_dir / "factory_report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["candidate_count"] = 999
        report_path.write_text(json.dumps(report), encoding="utf-8")
    result = {
        "validation_id": "v2-validation",
        "factory_run_id": factory_run_id,
        "status": "f4_rejected",
        "reasons": ["sharpe_below_0_80"],
        "promotion_state": "research_only",
        "execution_authority": False,
    }

    with pytest.raises(RuntimeError, match="f4_v2_authoritative_pointer_invalid"):
        write_validation_evidence(tmp_path, result)
    assert not (tmp_path / "data" / "research" / "f4" / "latest.json").exists()


def test_main_returns_nonzero_when_only_compatibility_projection_fails(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(
        validator,
        "run_validation",
        lambda **_kwargs: {
            "success": True,
            "factory_run_id": "c" * 64,
            "status": "f4_rejected",
            "promotion_state": "research_only",
            "execution_authority": False,
        },
    )
    monkeypatch.setattr(
        validator,
        "write_validation_evidence",
        lambda *_args, **_kwargs: validator.EvidencePaths(
            report=tmp_path / "factory_report.json",
            latest=tmp_path / "latest.json",
            no_op=False,
            authoritative_v2_committed=True,
            compatibility_projection_state="failed",
            compatibility_projection_error="compatibility latest locked",
        ),
    )
    monkeypatch.setattr(validator.sys, "argv", ["validate_strategy_portfolios.py", "--once"])

    exit_code = validator.main()
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert output["publication_committed"] is True
    assert output["compatibility_projection_state"] == "failed"
    assert output["compatibility_projection_error"] == "compatibility latest locked"


def test_main_returns_nonzero_when_f4_is_infrastructure_blocked(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(
        validator,
        "run_validation",
        lambda **_kwargs: {
            "success": True,
            "validation_id": "blocked-validation",
            "status": "f4_blocked",
            "reasons": ["candidate_score_contract_invalid"],
            "promotion_state": "research_only",
            "execution_authority": False,
        },
    )
    monkeypatch.setattr(
        validator,
        "write_validation_evidence",
        lambda *_args, **_kwargs: validator.EvidencePaths(
            report=tmp_path / "validation_report.json",
            latest=tmp_path / "latest.json",
            no_op=False,
            authoritative_v2_committed=False,
            compatibility_projection_state="completed",
            compatibility_projection_error=None,
        ),
    )
    monkeypatch.setattr(
        validator.sys,
        "argv",
        ["validate_strategy_portfolios.py", "--once"],
    )

    exit_code = validator.main()
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert output["status"] == "f4_blocked"
    assert output["publication_committed"] is False


def test_validation_entrypoint_uses_shared_compatibility_pointer_cas(
    tmp_path, monkeypatch
):
    factory_run_id = _factory_id("validation-cas")
    handle = _complete_staging(tmp_path, factory_run_id=factory_run_id)
    publish_v2_generation(handle)
    calls = []

    def conflict(*args, **kwargs):
        calls.append((args, kwargs))
        return {
            "compatibility_projection_state": "projection_conflict",
            "compatibility_projection_error": "f4_v2_pointer_conflict",
        }

    monkeypatch.setattr(validator, "write_v2_compatibility_projection", conflict)
    paths = write_validation_evidence(
        tmp_path,
        {
            "validation_id": "v2-validation",
            "factory_run_id": factory_run_id,
            "status": "f4_rejected",
            "promotion_state": "research_only",
            "execution_authority": False,
        },
    )

    assert len(calls) == 1
    assert paths.compatibility_projection_state == "projection_conflict"
    assert paths.authoritative_v2_committed is True
    assert not (tmp_path / "data" / "research" / "f4" / "latest.json").exists()

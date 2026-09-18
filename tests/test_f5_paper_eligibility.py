import pytest

from dataclasses import replace

from quant.paper_execution.eligibility import evaluate_eligibility
from quant.paper_execution.policy import ExperimentalPaperPolicy, PaperExecutionPolicy
from quant.risk.config import load_paper_execution_risk_config
from quant.strategy.f4_candidate_factory import (
    FACTORY_VERSION_V1,
    FACTORY_VERSION_V2,
    canonical_payload_hash,
)


def _selection(count=10):
    positions = [
        {"code": f"{600000 + index:06d}", "target_weight": 0.09, "industry": "测试"}
        for index in range(count)
    ]
    return {
        "portfolio_id": "portfolio-v1",
        "selection_status": "f4_research_portfolio",
        "selection_date": "20260818",
        "generated_from_snapshot_id": "snapshot-v1",
        "snapshot_data_version": "data-v1",
        "f4_validation_id": "validation-v1",
        "f4_gate_status": "f4_research_candidate",
        "position_count": count,
        "positions": positions,
        "invested_weight": round(sum(item["target_weight"] for item in positions), 8),
        "cash_weight": round(1 - sum(item["target_weight"] for item in positions), 8),
        "portfolio_policy": {"version": "portfolio-policy-v1", "top_k": count, "lot_size": 100},
        "promotion_state": "research_only",
        "execution_authority": False,
        "not_a_trade_signal": True,
    }


def _f4(status="f4_research_candidate"):
    return {
        "status": status,
        "validation_id": "validation-v1",
        "portfolio_policy_version": "portfolio-policy-v1",
        "cost_model_version": "cost-model-v1",
        "promotion_state": "research_only",
        "execution_authority": False,
    }


def _factor():
    return {"snapshot_id": "snapshot-v1", "data_version": "data-v1", "as_of": "20260818", "quality_passed": True}


def _evaluate(
    selection=None,
    f4=None,
    factor=None,
    policy=None,
    risk=None,
    existing_run=None,
    expected_selection_date="20260818",
):
    return evaluate_eligibility(
        selection=selection or _selection(),
        f4_latest=f4 or _f4(),
        factor_evidence=factor or _factor(),
        policy=policy or PaperExecutionPolicy(enabled=True),
        risk=risk or load_paper_execution_risk_config(hard_limits={"max_position_count": 10}),
        intended_session="20260819",
        expected_selection_date=expected_selection_date,
        existing_run=existing_run,
    )


def test_candidate_with_matching_identity_is_eligible():
    result = _evaluate()
    assert result.eligible is True
    assert result.reason_code == "eligible"
    assert result.evidence["paper_execution_authority"] is True
    assert result.evidence["live_execution_authority"] is False


def test_f4_rejected_and_diagnostic_selection_are_blocked():
    rejected = _selection()
    rejected["f4_gate_status"] = "f4_rejected"
    rejected["selection_status"] = "diagnostic_research_portfolio"
    assert _evaluate(selection=rejected, f4=_f4("f4_rejected")).reason_code == "blocked_by_f4"


def test_stale_and_identity_mismatches_fail_closed():
    assert _evaluate(expected_selection_date="20260818").eligible is True
    stale = _selection()
    stale["selection_date"] = "20260817"
    assert _evaluate(selection=stale).reason_code == "selection_stale"
    wrong_validation = _selection()
    wrong_validation["f4_validation_id"] = "other"
    assert _evaluate(selection=wrong_validation).reason_code == "validation_identity_mismatch"
    wrong_data = _selection()
    wrong_data["snapshot_data_version"] = "other"
    assert _evaluate(selection=wrong_data).reason_code == "data_identity_mismatch"


def test_disabled_kill_switch_duplicate_and_top20_are_blocked():
    assert _evaluate(policy=PaperExecutionPolicy(enabled=False)).reason_code == "paper_execution_disabled"
    assert _evaluate(policy=PaperExecutionPolicy(enabled=True, kill_switch=True)).reason_code == "kill_switch_active"
    assert _evaluate(existing_run={"status": "prepared"}).reason_code == "duplicate_run"
    assert _evaluate(selection=_selection(20)).reason_code == "portfolio_policy_incompatible"


def test_f5_risk_loader_uses_only_explicit_policy_and_hard_limits():
    class TrapCache:
        def get(self, key):
            raise AssertionError(f"F5 must not read cache key {key}")

    risk = load_paper_execution_risk_config(
        cache=TrapCache(),
        policy_risk={"max_position_count": 8, "max_position_pct": 0.15},
        hard_limits={"max_position_count": 10, "max_position_pct": 0.2},
    )
    assert risk["max_position_count"] == 8
    assert risk["max_position_pct"] == 0.15
    assert risk["_config_source"] == "f5_policy_plus_hard_limits"


def test_nested_candidate_policy_identity_must_match_f4_winner_exactly():
    selection = _selection()
    governed_policy = {
        "top_k": 10,
        "rebalance_bars": 10,
        "max_name_weight": 0.095,
        "max_industry_weight": 0.25,
        "lot_size": 100,
        "adv_participation": 0.10,
        "target_gross_exposure": 0.95,
        "version": "nested-window-policy-v1",
    }
    selection.update(
        {
            "portfolio_policy": governed_policy,
            "portfolio_policy_hash": canonical_payload_hash(governed_policy),
            "factor_fit_window": "wf-01",
            "f4_factory_version": FACTORY_VERSION_V1,
            "f4_factory_run_id": "factory-v1",
            "f4_candidate_id": "candidate-v1",
            "f4_candidate_lock_hash": "lock-v1",
        }
    )
    f4 = _f4()
    f4["portfolio_policy_version"] = "nested-window-policy-v1"
    f4["candidate_spec_version"] = FACTORY_VERSION_V1
    f4["candidate_spec"] = {
        "version": FACTORY_VERSION_V1,
        "factory_run_id": "factory-v1",
        "selected_policies": [
            {
                "window_id": "wf-01",
                "candidate_id": "candidate-v1",
                **governed_policy,
                "policy_hash": canonical_payload_hash(governed_policy),
            }
        ],
        "selection_locks": [
            {
                "window_id": "wf-01",
                "candidate_id": "candidate-v1",
                "lock_hash": "lock-v1",
            }
        ],
    }

    assert _evaluate(selection=selection, f4=f4).eligible is True
    selection["portfolio_policy"] = {**governed_policy, "rebalance_bars": 20}
    selection["portfolio_policy_hash"] = canonical_payload_hash(selection["portfolio_policy"])
    result = _evaluate(selection=selection, f4=f4)
    assert result.eligible is False
    assert result.reason_code == "f4_candidate_policy_identity_mismatch"


def test_new_factory_contract_without_factory_identity_is_never_eligible():
    f4 = _f4()
    f4["candidate_spec_version"] = FACTORY_VERSION_V1
    f4["candidate_spec"] = {
        "version": FACTORY_VERSION_V1,
        "selected_policies": [],
        "selection_locks": [],
    }

    result = _evaluate(f4=f4)

    assert result.eligible is False
    assert result.reason_code == "f4_candidate_factory_version_unsupported"


def test_experimental_policy_is_explicit_and_never_grants_live_authority():
    policy = PaperExecutionPolicy(
        enabled=True,
        experimental_paper=ExperimentalPaperPolicy(enabled=True),
    )

    assert policy.experimental_paper.enabled is True
    assert policy.experimental_paper.allowed_f4_statuses == ("f4_rejected",)
    assert policy.live_execution_authority is False


def test_experimental_policy_rejects_f4_blocked():
    with pytest.raises(ValueError, match="experimental_f4_status_forbidden"):
        ExperimentalPaperPolicy(
            enabled=True,
            allowed_f4_statuses=("f4_blocked",),
        )


def _experimental_pair():
    selection = _selection()
    governed_policy = {
        "top_k": 10,
        "rebalance_bars": 10,
        "max_name_weight": 0.095,
        "max_industry_weight": 0.25,
        "lot_size": 100,
        "adv_participation": 0.10,
        "target_gross_exposure": 0.95,
        "version": "nested-window-policy-v1",
    }
    selection.update(
        {
            "selection_status": "experimental_research_portfolio",
            "f4_gate_status": "f4_rejected",
            "research_generation_id": "generation-v1",
            "experimental_policy_version": "f5-experimental-paper-v1",
            "portfolio_policy": governed_policy,
            "portfolio_policy_hash": canonical_payload_hash(governed_policy),
            "factor_fit_window": "wf-01",
            "f4_factory_version": FACTORY_VERSION_V1,
            "f4_factory_run_id": "factory-v1",
            "f4_candidate_id": "candidate-v1",
            "f4_candidate_lock_hash": "lock-v1",
        }
    )
    f4 = _f4("f4_rejected")
    f4.update(
        {
            "candidate_factory_status": "exhausted",
            "portfolio_policy_version": "nested-window-policy-v1",
            "candidate_spec_version": FACTORY_VERSION_V1,
            "reasons": ["sharpe_below_0_80"],
            "metrics": {
                "constraint_violation_count": 0,
                "future_data_violation_count": 0,
            },
            "input_status": {
                "benchmark": "present",
                "f3_evidence": "present",
                "pit_industry": "present",
                "pit_manifest": "complete",
                "pit_quality": "passed",
            },
            "candidate_spec": {
                "version": FACTORY_VERSION_V1,
                "factory_run_id": "factory-v1",
                "selected_policies": [
                    {
                        "window_id": "wf-01",
                        "candidate_id": "candidate-v1",
                        **governed_policy,
                        "policy_hash": canonical_payload_hash(governed_policy),
                    }
                ],
                "selection_locks": [
                    {
                        "window_id": "wf-01",
                        "candidate_id": "candidate-v1",
                        "lock_hash": "lock-v1",
                    }
                ],
            },
        }
    )
    return selection, f4


def _v2_pair(*, model_artifact_hash="model-v2"):
    selection = _selection()
    governed_policy = {
        "top_k": 10,
        "rebalance_bars": 10,
        "max_name_weight": 0.095,
        "max_industry_weight": 0.25,
        "lot_size": 100,
        "adv_participation": 0.10,
        "target_gross_exposure": 0.95,
        "version": "f4-standard-top10-policy-v2",
    }
    policy_hash = canonical_payload_hash(governed_policy)
    lock_core = {
        "factory_run_id": "factory-v2",
        "window_id": "wf-01",
        "candidate_id": "candidate-v2",
        "alpha_spec_hash": "alpha-spec-v2",
        "alpha_fit_hash": "alpha-fit-v2",
        "model_artifact_hash": model_artifact_hash,
        "portfolio_policy_hash": policy_hash,
    }
    lock_hash = canonical_payload_hash(lock_core)
    selection.update(
        {
            "portfolio_policy": governed_policy,
            "portfolio_policy_hash": policy_hash,
            "factor_fit_window": "wf-01",
            "f4_factory_version": FACTORY_VERSION_V2,
            "f4_factory_run_id": "factory-v2",
            "f4_candidate_id": "candidate-v2",
            "f4_alpha_spec_hash": "alpha-spec-v2",
            "f4_alpha_fit_hash": "alpha-fit-v2",
            "f4_model_artifact_hash": model_artifact_hash,
            "f4_candidate_lock_hash": lock_hash,
        }
    )
    f4 = _f4()
    f4.update(
        {
            "portfolio_policy_version": "f4-standard-top10-policy-v2",
            "candidate_spec_version": FACTORY_VERSION_V2,
            "candidate_spec": {
                "version": FACTORY_VERSION_V2,
                "factory_run_id": "factory-v2",
                "factor_fits": [
                    {
                        "window_id": "wf-01",
                        "candidate_id": "candidate-v2",
                        "alpha_spec_hash": "alpha-spec-v2",
                        "alpha_fit_hash": "alpha-fit-v2",
                    }
                ],
                "model_artifacts": [
                    {
                        "window_id": "wf-01",
                        "candidate_id": "candidate-v2",
                        "model_artifact_hash": model_artifact_hash,
                    }
                ],
                "selected_policies": [
                    {
                        "window_id": "wf-01",
                        "candidate_id": "candidate-v2",
                        **governed_policy,
                        "policy_hash": policy_hash,
                        "lock_hash": lock_hash,
                    }
                ],
                "selection_locks": [
                    {
                        **lock_core,
                        "lock_hash": lock_hash,
                        "promotion_state": "research_only",
                        "execution_authority": False,
                    }
                ],
            },
        }
    )
    return selection, f4


def test_v2_selection_with_exact_f4_identity_is_eligible():
    selection, f4 = _v2_pair()

    result = _evaluate(selection=selection, f4=f4)

    assert result.eligible is True
    assert result.reason_code == "eligible"
    assert result.evidence["live_execution_authority"] is False


def test_v2_uses_locked_policy_hash_not_legacy_outer_policy_label():
    selection, f4 = _v2_pair(model_artifact_hash=None)
    f4["portfolio_policy_version"] = "nested-window-policy-v1"
    f4["candidate_spec"]["model_artifacts"] = []

    result = _evaluate(selection=selection, f4=f4)

    assert result.eligible is True
    assert result.reason_code == "eligible"


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("f4_alpha_spec_hash", "f4_candidate_alpha_identity_mismatch"),
        ("f4_alpha_fit_hash", "f4_candidate_alpha_fit_identity_mismatch"),
        ("f4_model_artifact_hash", "f4_candidate_model_identity_mismatch"),
    ],
)
def test_f5_v2_binding_rejects_alpha_or_model_hash_drift(field, reason):
    selection, f4 = _v2_pair()
    selection[field] = "forged"

    result = _evaluate(selection=selection, f4=f4)

    assert result.eligible is False
    assert result.reason_code == reason


def test_f5_unknown_factory_version_fails_closed():
    selection, f4 = _v2_pair()
    f4["candidate_spec_version"] = "f4-unknown-v99"
    f4["candidate_spec"]["version"] = "f4-unknown-v99"

    result = _evaluate(selection=selection, f4=f4)

    assert result.eligible is False
    assert result.reason_code == "f4_candidate_factory_version_unsupported"


@pytest.mark.parametrize("selection_version", [None, "f4-unknown-v99"])
def test_f5_v1_selection_version_missing_or_unknown_fails_closed(selection_version):
    selection, f4 = _experimental_pair()
    if selection_version is None:
        selection.pop("f4_factory_version")
    else:
        selection["f4_factory_version"] = selection_version

    result = _evaluate(
        selection=selection,
        f4=f4,
        policy=_experimental_policy(),
    )

    assert result.eligible is False
    assert result.reason_code == "f4_candidate_factory_version_unsupported"


@pytest.mark.parametrize(
    ("location", "version"),
    [
        ("outer", None),
        ("inner", None),
        ("outer", FACTORY_VERSION_V1),
        ("inner", FACTORY_VERSION_V1),
        ("selection", FACTORY_VERSION_V1),
        ("selection", 2),
    ],
)
def test_f5_v2_version_triplet_missing_non_string_or_mismatch_fails_closed(
    location, version
):
    selection, f4 = _v2_pair()
    if location == "outer":
        if version is None:
            f4.pop("candidate_spec_version")
        else:
            f4["candidate_spec_version"] = version
    elif location == "inner":
        if version is None:
            f4["candidate_spec"].pop("version")
        else:
            f4["candidate_spec"]["version"] = version
    else:
        selection["f4_factory_version"] = version

    result = _evaluate(selection=selection, f4=f4)

    assert result.eligible is False
    assert result.reason_code == "f4_candidate_factory_version_unsupported"


def _experimental_policy(enabled=True):
    return PaperExecutionPolicy(
        enabled=True,
        experimental_paper=ExperimentalPaperPolicy(enabled=enabled),
    )


def test_performance_rejected_strategy_is_experimentally_eligible():
    selection, f4 = _experimental_pair()

    result = _evaluate(
        selection=selection,
        f4=f4,
        policy=_experimental_policy(),
    )

    assert result.eligible is True
    assert result.reason_code == "eligible_experimental"
    assert result.evidence["execution_lane"] == "experimental_paper"
    assert result.evidence["strategy_quality_status"] == "unqualified"
    assert result.evidence["live_execution_authority"] is False


def test_experimental_lane_requires_explicit_policy_enablement():
    selection, f4 = _experimental_pair()

    result = _evaluate(
        selection=selection,
        f4=f4,
        policy=_experimental_policy(enabled=False),
    )

    assert result.eligible is False
    assert result.reason_code == "blocked_by_f4"


def test_blocked_or_unsafe_f4_never_enters_experimental_lane():
    selection, f4 = _experimental_pair()
    blocked = {**f4, "status": "f4_blocked"}
    assert (
        _evaluate(selection=selection, f4=blocked, policy=_experimental_policy()).reason_code
        == "blocked_by_f4"
    )

    unsafe = {**f4, "metrics": {**f4["metrics"], "future_data_violation_count": 1}}
    assert (
        _evaluate(selection=selection, f4=unsafe, policy=_experimental_policy()).reason_code
        == "future_data_detected"
    )

    wrong_reason = {**f4, "reasons": ["window_count_below_4"]}
    assert (
        _evaluate(
            selection=selection,
            f4=wrong_reason,
            policy=_experimental_policy(),
        ).reason_code
        == "experimental_f4_reason_forbidden"
    )

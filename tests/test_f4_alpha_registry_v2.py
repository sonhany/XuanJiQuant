from __future__ import annotations

import math
from collections import Counter
from dataclasses import replace

import pytest

from quant.strategy.f4_alpha_contracts import (
    FACTORY_VERSION_V1,
    FACTORY_VERSION_V2,
    FORBIDDEN_FUNDAMENTAL_FEATURES,
    SUPPORTED_FACTORY_VERSIONS,
    AlphaSpec,
    F4CandidateV2,
    build_v2_candidate_registry,
    validate_v2_candidate_registry,
)


EXPECTED_ALPHA_FORMULAS = {
    "M1": (("ret_20", 0.60), ("ret_60", 0.40)),
    "M2": (("ret_5", 0.40), ("ret_10", 0.35), ("roc_10", 0.25)),
    "M3": (
        ("ret_20_over_volatility_20", 0.60),
        ("ret_60_over_volatility_60", 0.40),
    ),
    "M4": (
        ("trend_strength", 0.35),
        ("ema_gap_12", 0.25),
        ("macd_hist_norm", 0.20),
        ("ret_20", 0.20),
    ),
    "R1": (("reversal_3", 1.0),),
    "R2": (("reversal_5", 1.0),),
    "R3": (("reversal_10", 1.0),),
    "R4": (("-overnight_ret", 0.40), ("-intraday_ret", 0.35), ("-bias_20", 0.25)),
    "D1": (("-volatility_5", 0.40), ("-volatility_20", 0.60)),
    "D2": (
        ("-volatility_20", 0.60),
        ("-volatility_60", 0.25),
        ("-range_pct", 0.15),
    ),
    "D3": (("-atr_14_norm", 0.45), ("-range_pct", 0.30), ("-boll_width", 0.25)),
    "D4": (("-volatility_20", 0.60), ("trend_strength", 0.25), ("ret_20", 0.15)),
    "L1": (("vol_ratio_5", 0.55), ("turnover_5_over_20", 0.45)),
    "L2": (("amt_ratio_5", 0.50), ("vol_ratio_5", 0.30), ("pvcorr_5", 0.20)),
    "L3": (("obv_slope_10", 0.50), ("ad_slope_10", 0.50)),
    "L4": (
        ("mfi_14", 0.35),
        ("vwap_dev_20", 0.30),
        ("pvcorr_10", 0.20),
        ("pvbeta_20", 0.15),
    ),
}

EXPECTED_BASE_RULE_ALPHA_IDS = (
    "M1",
    "M2",
    "M3",
    "M4",
    "R1",
    "R2",
    "R3",
    "R4",
    "D1",
    "D2",
    "D3",
    "D4",
    "L1",
    "L2",
    "L3",
    "L4",
)

EXPECTED_REBALANCE = {
    "M1": 20,
    "M2": 10,
    "M3": 20,
    "M4": 10,
    "R1": 5,
    "R2": 5,
    "R3": 10,
    "R4": 5,
    "D1": 10,
    "D2": 20,
    "D3": 10,
    "D4": 20,
    "L1": 5,
    "L2": 5,
    "L3": 10,
    "L4": 10,
    "E1": 10,
    "E2": 10,
    "E3": 10,
    "E4": 20,
    "Q1": 5,
    "Q2": 5,
    "Q3": 5,
    "Q4": 5,
}


def test_v2_registry_is_stable_complete_and_versioned():
    first = build_v2_candidate_registry()
    second = build_v2_candidate_registry()

    assert first == second
    assert len(first) == 24
    assert Counter(candidate.family for candidate in first) == {
        "momentum": 4,
        "reversal": 4,
        "defensive": 4,
        "liquidity": 4,
        "ensemble": 4,
        "qlib": 4,
    }
    assert {candidate.alpha_spec.alpha_id for candidate in first} == set(EXPECTED_REBALANCE)
    assert len({candidate.candidate_id for candidate in first}) == 24
    assert all(candidate.version == FACTORY_VERSION_V2 for candidate in first)
    assert FACTORY_VERSION_V1 == "f4-nested-candidate-factory-v1"
    assert FACTORY_VERSION_V2 == "f4-multi-alpha-candidate-factory-v2"
    assert SUPPORTED_FACTORY_VERSIONS == frozenset({FACTORY_VERSION_V1, FACTORY_VERSION_V2})


def test_v2_registry_has_the_required_rule_formulas_models_and_rebalance():
    by_alpha = {
        candidate.alpha_spec.alpha_id: candidate for candidate in build_v2_candidate_registry()
    }

    for alpha_id, formula in EXPECTED_ALPHA_FORMULAS.items():
        assert by_alpha[alpha_id].alpha_spec.formula == formula
        assert by_alpha[alpha_id].alpha_spec.input_features == tuple(
            feature for feature, _weight in formula
        )
    assert {alpha_id: item.portfolio_policy.rebalance_bars for alpha_id, item in by_alpha.items()} == EXPECTED_REBALANCE
    assert {
        alpha_id: (item.alpha_spec.handler, item.alpha_spec.model_type)
        for alpha_id, item in by_alpha.items()
        if item.family == "qlib"
    } == {
        "Q1": ("Alpha158", "LightGBM"),
        "Q2": ("Alpha360", "LightGBM"),
        "Q3": ("Alpha158", "XGBoost"),
        "Q4": ("Alpha158", "Linear"),
    }
    assert {
        alpha_id: item.alpha_spec.fit_method
        for alpha_id, item in by_alpha.items()
        if item.family == "ensemble"
    } == {
        "E1": "equal_family_sleeves",
        "E2": "train_rank_ic_shrinkage",
        "E3": "train_correlation_cluster",
        "E4": "train_subperiod_stability",
    }
    assert all(
        by_alpha[alpha_id].alpha_spec.formula == ()
        for alpha_id in (*"E1 E2 E3 E4".split(), *"Q1 Q2 Q3 Q4".split())
    )
    assert all(
        by_alpha[alpha_id].alpha_spec.input_features == EXPECTED_BASE_RULE_ALPHA_IDS
        for alpha_id in "E1 E2 E3 E4".split()
    )
    assert all(
        item.portfolio_policy.version == "f4-standard-top10-policy-v2"
        for item in by_alpha.values()
    )


def test_candidate_identity_covers_complete_alpha_and_portfolio_policy():
    candidate = build_v2_candidate_registry()[0]
    changed_formula = replace(
        candidate,
        alpha_spec=replace(
            candidate.alpha_spec,
            formula=(("ret_20", 0.59), ("ret_60", 0.41)),
        ),
    )
    changed_input = replace(
        candidate,
        alpha_spec=replace(
            candidate.alpha_spec,
            input_features=("ret_20", "ret_120"),
        ),
    )
    changed_policy = replace(
        candidate,
        portfolio_policy=replace(candidate.portfolio_policy, rebalance_bars=21),
    )

    assert len({candidate.candidate_id, changed_formula.candidate_id, changed_input.candidate_id, changed_policy.candidate_id}) == 4
    assert candidate.candidate_id == build_v2_candidate_registry()[0].candidate_id
    with pytest.raises(ValueError, match="candidate_alpha_spec_unregistered"):
        changed_formula.validate()
    with pytest.raises(ValueError, match="rule_alpha_contract_invalid"):
        changed_input.validate()
    with pytest.raises(ValueError, match="candidate_policy_unregistered"):
        changed_policy.validate()


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("formula", (("ret_20", 0.59), ("ret_60", 0.41)), "candidate_alpha_spec_unregistered"),
        ("input_features", ("ret_20", "ret_120"), "rule_alpha_contract_invalid"),
        ("preprocessing", "rank_only", "candidate_alpha_spec_unregistered"),
        ("label_horizon_bars", 10, "candidate_alpha_spec_unregistered"),
        ("minimum_coverage", 0.96, "candidate_alpha_spec_unregistered"),
        ("seed", 1, "candidate_alpha_spec_unregistered"),
    ],
)
def test_preregistered_m1_alpha_spec_tampering_is_rejected(field, value, reason):
    m1 = next(item for item in build_v2_candidate_registry() if item.alpha_spec.alpha_id == "M1")
    tampered = replace(m1, alpha_spec=replace(m1.alpha_spec, **{field: value}))

    with pytest.raises(ValueError, match=reason):
        tampered.validate()


def test_preregistered_m1_rebalance_tampering_is_rejected():
    m1 = next(item for item in build_v2_candidate_registry() if item.alpha_spec.alpha_id == "M1")
    tampered = replace(m1, portfolio_policy=replace(m1.portfolio_policy, rebalance_bars=21))

    with pytest.raises(ValueError, match="candidate_policy_unregistered"):
        tampered.validate()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("handler", "Alpha360"),
        ("model_type", "XGBoost"),
        ("formula", (("ret_5", 1.0),)),
    ],
)
def test_preregistered_q1_contract_tampering_is_rejected(field, value):
    q1 = next(item for item in build_v2_candidate_registry() if item.alpha_spec.alpha_id == "Q1")
    tampered = replace(q1, alpha_spec=replace(q1.alpha_spec, **{field: value}))

    with pytest.raises(ValueError, match="qlib_contract_invalid"):
        tampered.validate()


def test_preregistered_e1_input_contract_tampering_is_rejected():
    e1 = next(item for item in build_v2_candidate_registry() if item.alpha_spec.alpha_id == "E1")
    tampered = replace(
        e1,
        alpha_spec=replace(e1.alpha_spec, input_features=EXPECTED_BASE_RULE_ALPHA_IDS[:-1]),
    )

    with pytest.raises(ValueError, match="ensemble_contract_invalid"):
        tampered.validate()


def test_preregistered_policy_version_tampering_is_rejected():
    m1 = next(item for item in build_v2_candidate_registry() if item.alpha_spec.alpha_id == "M1")
    tampered = replace(
        m1,
        portfolio_policy=replace(m1.portfolio_policy, version="f4-policy-tampered"),
    )

    with pytest.raises(ValueError, match="candidate_policy_version_invalid"):
        tampered.validate()


def test_fundamental_features_are_absent_and_rejected():
    registry = build_v2_candidate_registry()
    used_features = {
        feature.lower()
        for candidate in registry
        for feature in candidate.alpha_spec.input_features
    }
    assert used_features.isdisjoint(FORBIDDEN_FUNDAMENTAL_FEATURES)

    candidate = registry[0]
    bad = replace(
        candidate,
        alpha_spec=replace(
            candidate.alpha_spec,
            input_features=(*candidate.alpha_spec.input_features, "roe"),
            formula=(*candidate.alpha_spec.formula, ("roe", 0.01)),
        ),
    )
    with pytest.raises(ValueError, match="fundamental_feature_forbidden"):
        bad.validate()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("target_gross_exposure", 0.96),
        ("max_name_weight", 0.10),
        ("max_industry_weight", 0.30),
        ("top_k", 11),
        ("lot_size", 1),
        ("adv_participation", 0.11),
    ],
)
def test_unsafe_candidate_policy_is_rejected(field, value):
    candidate = build_v2_candidate_registry()[0]
    unsafe = replace(
        candidate,
        portfolio_policy=replace(candidate.portfolio_policy, **{field: value}),
    )

    with pytest.raises(ValueError, match="candidate_policy_unsafe"):
        unsafe.validate()


def test_nonfinite_formula_weight_is_rejected():
    candidate = build_v2_candidate_registry()[0]
    bad = replace(
        candidate,
        alpha_spec=replace(candidate.alpha_spec, formula=(("ret_20", math.nan),)),
    )

    with pytest.raises(ValueError, match="alpha_formula_weight_nonfinite"):
        bad.validate()


def test_wrong_qlib_contract_is_rejected():
    q1 = next(item for item in build_v2_candidate_registry() if item.alpha_spec.alpha_id == "Q1")
    bad = replace(q1, alpha_spec=replace(q1.alpha_spec, model_type="XGBoost"))

    with pytest.raises(ValueError, match="qlib_contract_invalid"):
        bad.validate()


def test_duplicate_alpha_id_and_invalid_family_are_rejected():
    registry = build_v2_candidate_registry()
    duplicate = replace(
        registry[1],
        alpha_spec=replace(registry[1].alpha_spec, alpha_id=registry[0].alpha_spec.alpha_id),
    )
    with pytest.raises(ValueError, match="alpha_id_duplicate"):
        validate_v2_candidate_registry((registry[0], duplicate))

    invalid = F4CandidateV2(
        family="unknown",
        alpha_spec=AlphaSpec(
            alpha_id="Z1",
            family="unknown",
            input_features=("ret_5",),
            formula=(("ret_5", 1.0),),
            preprocessing="cross_sectional_winsorize_zscore",
            fit_method="fixed_weighted_sum",
        ),
        portfolio_policy=registry[0].portfolio_policy,
    )
    with pytest.raises(ValueError, match="candidate_family_invalid"):
        invalid.validate()


def test_every_serialized_candidate_is_research_only_without_execution_authority():
    rows = [candidate.to_dict() for candidate in build_v2_candidate_registry()]

    assert all(row["promotion_state"] == "research_only" for row in rows)
    assert all(row["execution_authority"] is False for row in rows)

import pytest

from quant.strategy.portfolio import PortfolioPolicy
from quant.strategy.research_selection import (
    ResearchSelectionBlocked,
    build_research_selection,
)
from quant.strategy.f4_candidate_factory import (
    FACTORY_VERSION_V1,
    FACTORY_VERSION_V2,
    canonical_payload_hash,
)


def _factor_snapshot():
    rows = []
    for index, code in enumerate(("000001", "000002", "000003", "000004"), 1):
        rows.append(
            {
                "code": code,
                "name": f"股票{index}",
                "date": "20260818",
                "close": 10.0 + index,
                "factors": {
                    "range_pct": float(index),
                    "volatility_5": float(index),
                },
            }
        )
    return {
        "as_of": "20260818",
        "latest_kline_date": "20260818",
        "snapshot_id": "daily-20260818",
        "data_version": "data-v1",
        "active_count": 4,
        "data_count": 4,
        "eligible_count": 4,
        "data_coverage": 1.0,
        "excluded_reasons": {},
        "promotion_state": "research_only",
        "execution_authority": False,
        "rows": rows,
    }


def _factor_evaluation(**overrides):
    value = {
        "data_end_date": "20260818",
        "latest_kline_date": "20260818",
        "snapshot_id": "daily-20260818",
        "data_version": "data-v1",
        "factors": [{"factor": "range_pct"}, {"factor": "volatility_5"}],
        "promotion_state": "research_only",
        "execution_authority": False,
    }
    value.update(overrides)
    return value


def _f4_latest(status="f4_rejected"):
    return {
        "validation_id": "f4-v1",
        "status": status,
        "promotion_state": "research_only",
        "execution_authority": False,
    }


def _candidate_spec():
    return {
        "validation_id": "f4-v1",
        "promotion_state": "research_only",
        "execution_authority": False,
        "factor_fits": [
            {
                "window_id": "wf-01",
                "fit_end": "2026-06-01",
                "factors": ["range_pct", "volatility_5"],
                "directions": {"range_pct": -1, "volatility_5": -1},
                "weights": {"range_pct": 0.6, "volatility_5": 0.4},
                "median_rank_ic": {"range_pct": -0.1, "volatility_5": -0.08},
                "direction_consistency": {"range_pct": 0.7, "volatility_5": 0.6},
            }
        ],
    }


def _v2_candidate_spec(*, model_artifact_hash=None):
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
    lock_core = {
        "factory_run_id": "factory-v2",
        "window_id": "wf-01",
        "candidate_id": "candidate-v2",
        "alpha_spec_hash": "alpha-spec-v2",
        "alpha_fit_hash": "alpha-fit-v2",
        "model_artifact_hash": model_artifact_hash,
        "portfolio_policy_hash": canonical_payload_hash(governed_policy),
    }
    lock_hash = canonical_payload_hash(lock_core)
    value = {
        "version": FACTORY_VERSION_V2,
        "factory_run_id": "factory-v2",
        "validation_id": "f4-v1",
        "promotion_state": "research_only",
        "execution_authority": False,
        "factor_fits": [
            {
                "window_id": "wf-01",
                "fit_end": "2026-06-01",
                "candidate_id": "candidate-v2",
                "alpha_spec_hash": "alpha-spec-v2",
                "alpha_fit_hash": "alpha-fit-v2",
                "factors": ["range_pct", "volatility_5"],
                "directions": {"range_pct": -1, "volatility_5": -1},
                "weights": {"range_pct": 0.6, "volatility_5": 0.4},
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
        "selected_policies": [
            {
                "window_id": "wf-01",
                "candidate_id": "candidate-v2",
                **governed_policy,
                "lock_hash": lock_hash,
                "policy_hash": canonical_payload_hash(governed_policy),
            }
        ],
        "model_artifacts": [],
    }
    if model_artifact_hash is not None:
        value["model_artifacts"] = [
            {
                "window_id": "wf-01",
                "candidate_id": "candidate-v2",
                "model_artifact_hash": model_artifact_hash,
            }
        ]
    return value


def _remove_v2_identity(candidate, missing):
    if missing == "factory_run_id":
        candidate.pop("factory_run_id")
    elif missing == "candidate_id":
        candidate["factor_fits"][0].pop("candidate_id")
    elif missing in {"alpha_spec_hash", "alpha_fit_hash"}:
        candidate["factor_fits"][0].pop(missing)
    elif missing == "portfolio_policy_hash":
        candidate["selection_locks"][0].pop("portfolio_policy_hash")
    else:
        candidate["selection_locks"][0].pop("lock_hash")


def _industries():
    return [
        {
            "instrument": f"SZ{code}",
            "effective_from": "2020-01-01",
            "industry_code": "I1" if code != "000004" else "I2",
            "industry_name": "行业一" if code != "000004" else "行业二",
        }
        for code in ("000001", "000002", "000003", "000004")
    ]


def _build(**overrides):
    arguments = {
        "factor_snapshot": _factor_snapshot(),
        "factor_evaluation": _factor_evaluation(),
        "f4_latest": _f4_latest(),
        "candidate_spec": _candidate_spec(),
        "industry_records": _industries(),
        "generated_at": "2026-08-19T17:00:00+08:00",
        "policy": PortfolioPolicy(
            top_k=4,
            max_name_weight=0.25,
            max_industry_weight=0.50,
        ),
    }
    arguments.update(overrides)
    return build_research_selection(**arguments)


def test_rejected_f4_builds_diagnostic_research_only_portfolio():
    result = _build()

    assert result["selection_status"] == "diagnostic_research_portfolio"
    assert result["source_validation_rejected"] is True
    assert result["promotion_state"] == "research_only"
    assert result["execution_authority"] is False
    assert result["not_a_trade_signal"] is True
    assert result["selection_date"] == "20260818"
    assert result["generated_from_snapshot_id"] == "daily-20260818"
    assert result["snapshot_data_version"] == "data-v1"
    assert result["positions"][0]["code"] == "000001"
    assert abs(
        sum(row["target_weight"] for row in result["positions"])
        + result["cash_weight"]
        - 1.0
    ) < 1e-12


def test_industry_cap_is_enforced_without_backfilling_outside_top_k():
    result = _build()

    assert result["industry_weights"]["行业一"] == 0.5
    assert result["position_count"] == 3
    assert result["cash_weight"] == 0.25
    assert result["exclusions"] == {"industry_cap": 1}


def test_portfolio_id_excludes_generated_timestamp():
    first = _build(generated_at="2026-08-19T17:00:00+08:00")
    second = _build(generated_at="2026-08-19T17:05:00+08:00")

    assert first["portfolio_id"] == second["portfolio_id"]


def test_version_mismatch_fails_closed():
    with pytest.raises(ResearchSelectionBlocked) as exc_info:
        _build(factor_evaluation=_factor_evaluation(data_version="old-data"))

    assert exc_info.value.reason_code == "factor_evaluation_version_mismatch"


def test_missing_frozen_factor_fit_fails_closed():
    candidate = _candidate_spec()
    candidate["factor_fits"] = []

    with pytest.raises(ResearchSelectionBlocked) as exc_info:
        _build(candidate_spec=candidate)

    assert exc_info.value.reason_code == "f4_factor_fit_missing"


def test_stale_factor_rows_are_not_selected():
    snapshot = _factor_snapshot()
    snapshot["rows"][0]["date"] = "20260817"

    result = _build(factor_snapshot=snapshot)

    assert "000001" not in {row["code"] for row in result["positions"]}
    assert result["universe"]["scored_count"] == 3


def test_f4_selected_candidate_policy_is_used_when_no_override_is_supplied():
    candidate = _candidate_spec()
    candidate["version"] = FACTORY_VERSION_V1
    candidate["factor_fits"][0]["candidate_id"] = "candidate-v1"
    candidate["factory_run_id"] = "factory-v1"
    lock_core = {
        "factory_run_id": "factory-v1",
        "window_id": "wf-01",
        "candidate_id": "candidate-v1",
        "selection_scope": "current_window_validation_only",
        "validation_leaderboard": [{"candidate_id": "candidate-v1", "selected": True}],
    }
    candidate["selection_locks"] = [
        {
            **lock_core,
            "lock_hash": canonical_payload_hash(lock_core),
            "promotion_state": "research_only",
            "execution_authority": False,
        }
    ]
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
    candidate["selected_policies"] = [
        {
            "window_id": "wf-01",
            "candidate_id": "candidate-v1",
            **governed_policy,
            "lock_hash": canonical_payload_hash(lock_core),
            "policy_hash": canonical_payload_hash(governed_policy),
        }
    ]

    result = _build(candidate_spec=candidate, policy=None)

    assert result["portfolio_policy"]["version"] == "nested-window-policy-v1"
    assert result["portfolio_policy"]["top_k"] == 10
    assert result["invested_weight"] <= 0.95
    assert all(position["target_weight"] <= 0.095 for position in result["positions"])
    assert result["f4_candidate_id"] == "candidate-v1"
    assert result["f4_candidate_lock_hash"] == canonical_payload_hash(lock_core)
    assert result["portfolio_policy_hash"] == canonical_payload_hash(governed_policy)


@pytest.mark.parametrize("drift", ["missing_policy", "candidate_mismatch", "unsafe"])
def test_factory_candidate_policy_missing_mismatched_or_unsafe_fails_closed(drift):
    candidate = _candidate_spec()
    candidate["version"] = FACTORY_VERSION_V1
    candidate["factory_run_id"] = "factory-v1"
    candidate["factor_fits"][0]["candidate_id"] = "candidate-v1"
    lock_core = {
        "factory_run_id": "factory-v1",
        "window_id": "wf-01",
        "candidate_id": "candidate-v1",
        "selection_scope": "current_window_validation_only",
        "validation_leaderboard": [{"candidate_id": "candidate-v1", "selected": True}],
    }
    candidate["selection_locks"] = [{**lock_core, "lock_hash": canonical_payload_hash(lock_core), "promotion_state": "research_only", "execution_authority": False}]
    policy = {
        "window_id": "wf-01",
        "candidate_id": "candidate-v1",
        "top_k": 10,
        "rebalance_bars": 10,
        "max_name_weight": 0.095,
        "max_industry_weight": 0.25,
        "lot_size": 100,
        "adv_participation": 0.10,
        "target_gross_exposure": 0.95,
        "version": "nested-window-policy-v1",
    }
    governed = {key: value for key, value in policy.items() if key not in {"window_id", "candidate_id"}}
    policy["policy_hash"] = canonical_payload_hash(governed)
    policy["lock_hash"] = canonical_payload_hash(lock_core)
    candidate["selected_policies"] = [] if drift == "missing_policy" else [policy]
    if drift == "candidate_mismatch":
        candidate["selected_policies"][0]["candidate_id"] = "other"
    if drift == "unsafe":
        candidate["selected_policies"][0]["top_k"] = 20

    with pytest.raises(ResearchSelectionBlocked):
        _build(candidate_spec=candidate, policy=None)


def test_new_factory_contract_without_factory_identity_fails_closed():
    candidate = _candidate_spec()
    candidate["version"] = FACTORY_VERSION_V1
    candidate["factor_fits"][0]["candidate_id"] = "candidate-v1"

    with pytest.raises(ResearchSelectionBlocked) as exc_info:
        _build(candidate_spec=candidate, policy=None)

    assert exc_info.value.reason_code == "f4_candidate_factory_identity_missing"


def test_research_selection_accepts_verified_v2_winner_identity():
    result = _build(candidate_spec=_v2_candidate_spec(), policy=None)

    assert result["f4_factory_version"] == FACTORY_VERSION_V2
    assert result["f4_factory_run_id"] == "factory-v2"
    assert result["f4_candidate_id"] == "candidate-v2"
    assert result["f4_alpha_spec_hash"] == "alpha-spec-v2"
    assert result["f4_alpha_fit_hash"] == "alpha-fit-v2"
    assert result["f4_model_artifact_hash"] is None
    assert result["f4_candidate_lock_hash"]


def test_v2_selection_reuses_signed_industry_rank_semantics():
    candidate = _v2_candidate_spec()
    candidate["factor_fits"][0].update(
        {
            "factors": ["-volatility_5"],
            "directions": {"-volatility_5": 1},
            "weights": {"-volatility_5": 1.0},
        }
    )

    result = _build(candidate_spec=candidate, policy=None)

    assert result["positions"][0]["code"] == "000001"
    assert result["positions"][0]["score"] > result["positions"][1]["score"]


@pytest.mark.parametrize(
    "missing",
    [
        "factory_run_id",
        "candidate_id",
        "alpha_spec_hash",
        "alpha_fit_hash",
        "portfolio_policy_hash",
        "lock_hash",
    ],
)
def test_v2_selection_missing_identity_fails_closed(missing):
    candidate = _v2_candidate_spec()
    _remove_v2_identity(candidate, missing)

    with pytest.raises(ResearchSelectionBlocked):
        _build(candidate_spec=candidate, policy=None)


def test_unknown_candidate_factory_version_fails_closed():
    candidate = _v2_candidate_spec()
    candidate["version"] = "f4-unknown-v99"

    with pytest.raises(ResearchSelectionBlocked) as exc_info:
        _build(candidate_spec=candidate, policy=None)

    assert exc_info.value.reason_code == "f4_candidate_factory_version_unsupported"

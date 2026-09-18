import pytest

from quant.strategy.experimental_selection import build_experimental_selection
from quant.strategy.f4_candidate_factory import FACTORY_VERSION_V1, canonical_payload_hash
from quant.strategy.research_selection import ResearchSelectionBlocked


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


def _factor_evaluation():
    return {
        "data_end_date": "20260818",
        "latest_kline_date": "20260818",
        "snapshot_id": "daily-20260818",
        "data_version": "data-v1",
        "factors": [{"factor": "range_pct"}, {"factor": "volatility_5"}],
        "promotion_state": "research_only",
        "execution_authority": False,
    }


def _candidate_spec():
    lock_core = {
        "factory_run_id": "factory-v1",
        "window_id": "wf-01",
        "candidate_id": "candidate-v1",
        "selection_scope": "current_window_validation_only",
        "validation_leaderboard": [{"candidate_id": "candidate-v1", "selected": True}],
    }
    lock_hash = canonical_payload_hash(lock_core)
    policy = {
        "top_k": 10,
        "rebalance_bars": 10,
        "max_name_weight": 0.095,
        "max_industry_weight": 0.25,
        "lot_size": 100,
        "adv_participation": 0.10,
        "target_gross_exposure": 0.95,
        "version": "nested-window-policy-v1",
    }
    return {
        "version": FACTORY_VERSION_V1,
        "validation_id": "f4-v1",
        "factory_run_id": "factory-v1",
        "promotion_state": "research_only",
        "execution_authority": False,
        "factor_fits": [
            {
                "window_id": "wf-01",
                "fit_end": "2026-06-01",
                "candidate_id": "candidate-v1",
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
                "candidate_id": "candidate-v1",
                **policy,
                "lock_hash": lock_hash,
                "policy_hash": canonical_payload_hash(policy),
            }
        ],
    }


def _f4(**overrides):
    value = {
        "validation_id": "f4-v1",
        "status": "f4_rejected",
        "candidate_factory_status": "exhausted",
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
        "promotion_state": "research_only",
        "execution_authority": False,
    }
    value.update(overrides)
    return value


def _industries():
    return [
        {
            "instrument": f"SZ{code}",
            "effective_from": "2020-01-01",
            "industry_code": "I1",
            "industry_name": "行业一",
        }
        for code in ("000001", "000002", "000003", "000004")
    ]


def _build(**overrides):
    arguments = {
        "factor_snapshot": _factor_snapshot(),
        "factor_evaluation": _factor_evaluation(),
        "f4_latest": _f4(),
        "candidate_spec": _candidate_spec(),
        "industry_records": _industries(),
        "research_generation_id": "generation-v1",
        "generated_at": "2026-08-20T16:20:00+08:00",
    }
    arguments.update(overrides)
    return build_experimental_selection(**arguments)


def test_rejected_factory_builds_bound_experimental_portfolio():
    result = _build()

    assert result["selection_status"] == "experimental_research_portfolio"
    assert result["research_generation_id"] == "generation-v1"
    assert result["f4_validation_id"] == "f4-v1"
    assert result["f4_candidate_id"] == "candidate-v1"
    assert result["f4_candidate_lock_hash"]
    assert result["portfolio_policy_hash"]
    assert result["experimental_policy_version"] == "f5-experimental-paper-v1"
    assert result["promotion_state"] == "research_only"
    assert result["execution_authority"] is False
    assert result["not_a_trade_signal"] is True


def test_experimental_portfolio_identity_ignores_generated_timestamp():
    first = _build(generated_at="2026-08-20T16:20:00+08:00")
    second = _build(generated_at="2026-08-20T16:25:00+08:00")

    assert first["portfolio_id"] == second["portfolio_id"]


@pytest.mark.parametrize(
    "reason",
    ["future_data_detected", "portfolio_constraint_failed", "window_count_below_4"],
)
def test_non_performance_f4_reason_cannot_build_experimental_portfolio(reason):
    with pytest.raises(ResearchSelectionBlocked) as exc_info:
        _build(f4_latest=_f4(reasons=[reason]))

    assert exc_info.value.reason_code == "experimental_f4_reason_forbidden"


def test_f4_blocked_or_nonzero_integrity_violation_fails_closed():
    with pytest.raises(ResearchSelectionBlocked) as exc_info:
        _build(f4_latest=_f4(status="f4_blocked"))
    assert exc_info.value.reason_code == "experimental_f4_status_forbidden"

    with pytest.raises(ResearchSelectionBlocked) as exc_info:
        _build(
            f4_latest=_f4(
                metrics={
                    "constraint_violation_count": 0,
                    "future_data_violation_count": 1,
                }
            )
        )
    assert exc_info.value.reason_code == "future_data_detected"

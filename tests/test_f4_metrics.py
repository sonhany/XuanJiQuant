import pytest

from quant.strategy.f4_alpha_contracts import build_v2_candidate_registry
from quant.strategy.f4_metrics import (
    aggregate_v2_window_metrics,
    build_family_diagnostics,
)


def _window(window_id, candidate_id, excess):
    return {
        "window_id": window_id,
        "candidate_id": candidate_id,
        "excess_return": excess,
        "sharpe": 1.0 if excess > 0 else -0.2,
        "max_drawdown": -0.1 if excess > 0 else -0.15,
    }


def test_v2_aggregate_uses_locked_test_winners_only():
    metrics = aggregate_v2_window_metrics(
        locked_tests=[
            _window("wf-01", "M1", 0.02),
            _window("wf-02", "Q1", -0.01),
        ],
        validation_rows=[_window("wf-01", "R1", 99.0)],
        double_cost_excess_return=0.001,
    )
    assert metrics["window_count"] == 2
    assert metrics["positive_excess_window_ratio"] == 0.5
    assert metrics["after_cost_excess_return"] == pytest.approx(0.01)


def test_v2_aggregate_rejects_two_winners_for_one_window():
    with pytest.raises(ValueError, match="f4_v2_locked_test_identity_invalid"):
        aggregate_v2_window_metrics(
            locked_tests=[
                _window("wf-01", "M1", 0.02),
                _window("wf-01", "Q1", 0.01),
            ],
            double_cost_excess_return=0.01,
        )


@pytest.mark.parametrize("field", ["excess_return", "sharpe", "max_drawdown"])
def test_v2_aggregate_rejects_non_finite_gate_inputs(field):
    row = _window("wf-01", "M1", 0.02)
    row[field] = float("nan")
    with pytest.raises(ValueError, match="f4_v2_metric_non_finite"):
        aggregate_v2_window_metrics(
            locked_tests=[row], double_cost_excess_return=0.01
        )


def test_v2_aggregate_rejects_non_finite_double_cost():
    with pytest.raises(ValueError, match="f4_v2_metric_non_finite"):
        aggregate_v2_window_metrics(
            locked_tests=[_window("wf-01", "M1", 0.02)],
            double_cost_excess_return=float("inf"),
        )


def test_family_diagnostics_cover_all_six_registered_families():
    registry = build_v2_candidate_registry()
    by_alpha = {item.alpha_spec.alpha_id: item for item in registry}
    statuses = [
        {
            "candidate_id": item.candidate_id,
            "family": item.family,
            "available": item.alpha_spec.alpha_id != "Q1",
            "reason_code": "qlib_dependency_unavailable"
            if item.alpha_spec.alpha_id == "Q1"
            else "",
        }
        for item in registry
    ]
    diagnostics = build_family_diagnostics(
        registry,
        statuses,
        [
            {"window_id": "wf-01", "candidate_id": by_alpha["M1"].candidate_id, "family": "momentum"},
            {"window_id": "wf-02", "candidate_id": by_alpha["Q2"].candidate_id, "family": "qlib"},
        ],
    )
    assert set(diagnostics) == {
        "momentum", "reversal", "defensive", "liquidity", "ensemble", "qlib"
    }
    assert all(row["registered"] == 4 for row in diagnostics.values())
    assert diagnostics["qlib"] == {
        "registered": 4,
        "available": 3,
        "unavailable": 1,
        "validation_wins": 1,
        "reason_counts": {"qlib_dependency_unavailable": 1},
    }


def test_family_diagnostics_reject_duplicate_candidate_or_window_lock():
    registry = build_v2_candidate_registry()
    candidate = registry[0]
    status = {
        "candidate_id": candidate.candidate_id,
        "family": candidate.family,
        "available": True,
        "reason_code": "",
    }
    with pytest.raises(ValueError, match="f4_v2_family_status_identity_invalid"):
        build_family_diagnostics(registry, [status, status], [])
    lock = {"window_id": "wf-01", "candidate_id": candidate.candidate_id}
    with pytest.raises(ValueError, match="f4_v2_family_lock_identity_invalid"):
        build_family_diagnostics(registry, [status], [lock, lock])

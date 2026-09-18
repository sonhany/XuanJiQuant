import inspect

import pytest

from quant.strategy.f4_gate import evaluate_f4_gate
from quant.strategy.f4_metrics import calculate_return_metrics


def passing_metrics():
    return {
        "window_count": 5,
        "positive_excess_window_ratio": 0.60,
        "after_cost_excess_return": 0.08,
        "sharpe": 0.90,
        "max_drawdown": -0.15,
        "double_cost_excess_return": 0.01,
        "constraint_violation_count": 0,
        "future_data_violation_count": 0,
    }


def test_all_hard_metrics_produce_research_candidate_without_authority():
    result = evaluate_f4_gate(passing_metrics(), blocked_reasons=[])
    assert result["status"] == "f4_research_candidate"
    assert result["promotion_state"] == "research_only"
    assert result["execution_authority"] is False


def test_f4_v4_threshold_boundaries_are_unchanged_for_v2():
    result = evaluate_f4_gate(
        {
            "window_count": 4,
            "positive_excess_window_ratio": 0.60,
            "after_cost_excess_return": 0.0001,
            "sharpe": 0.80,
            "max_drawdown": -0.20,
            "double_cost_excess_return": 0.0001,
            "constraint_violation_count": 0,
            "future_data_violation_count": 0,
        },
        [],
    )
    assert result["status"] == "f4_research_candidate"
    assert result["gate_version"] == "f4-gate-v4"
    assert result["promotion_state"] == "research_only"
    assert result["execution_authority"] is False


def test_f4_v4_source_contract_locks_all_eight_comparisons_and_ignores_bypass():
    source = inspect.getsource(evaluate_f4_gate)
    for expression in (
        'int(metrics.get("window_count") or 0) < 4',
        'float(metrics.get("positive_excess_window_ratio") or 0.0) < 0.60',
        'float(metrics.get("after_cost_excess_return") or 0.0) <= 0',
        'float(metrics.get("sharpe") or 0.0) < 0.80',
        'float(metrics.get("max_drawdown") or 0.0) < -0.20',
        'float(metrics.get("double_cost_excess_return") or 0.0) <= 0',
        'int(metrics.get("constraint_violation_count") or 0) != 0',
        'int(metrics.get("future_data_violation_count") or 0) != 0',
    ):
        assert expression in source
    weak = {**passing_metrics(), "sharpe": 0.0, "bypass": True, "force_pass": True}
    assert evaluate_f4_gate(weak, [])["status"] == "f4_rejected"


def test_data_failure_is_blocked_and_metric_failure_is_rejected():
    assert (
        evaluate_f4_gate(
            passing_metrics(), ["pit_manifest_incomplete"]
        )["status"]
        == "f4_blocked"
    )
    weak = {**passing_metrics(), "sharpe": 0.79}
    result = evaluate_f4_gate(weak, [])
    assert result["status"] == "f4_rejected"
    assert "sharpe_below_0_80" in result["reasons"]


def test_return_metrics_include_benchmark_excess_and_drawdown():
    result = calculate_return_metrics(
        [0.02, -0.01, 0.03, -0.02],
        [0.01, -0.01, 0.01, -0.01],
        periods_per_year=4,
    )
    assert result["total_return"] == pytest.approx(0.01929212, abs=1e-8)
    assert result["benchmark_return"] == pytest.approx(-0.00019999, abs=1e-8)
    assert result["excess_return"] > 0
    assert result["max_drawdown"] < 0

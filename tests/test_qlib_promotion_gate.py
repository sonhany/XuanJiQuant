from quant.qlib.promotion_gate import GATE_VERSION, evaluate_promotion_gate


def passing_payload():
    return {
        "quality_passed": True,
        "signal_metrics": {
            "window_count": 4,
            "median_rank_ic": 0.03,
            "median_icir": 0.40,
            "positive_rank_ic_ratio": 0.75,
            "aggregate_after_cost_long_short": 0.05,
            "aggregate_sharpe": 1.00,
            "max_drawdown": -0.10,
            "worst_rank_ic": -0.01,
        },
        "official_backtest": {
            "after_cost_return": 0.08,
            "annual_return": 0.12,
            "sharpe": 1.10,
            "max_drawdown": -0.12,
            "annual_turnover": 2.0,
        },
        "ashare_backtest": {
            "after_cost_return": 0.06,
            "annual_return": 0.10,
            "sharpe": 1.00,
            "max_drawdown": -0.14,
            "annual_turnover": 2.2,
        },
        "divergence_reviewed": False,
    }


def test_candidate_requires_both_backtests():
    result = evaluate_promotion_gate(**passing_payload())

    assert result["status"] == "candidate"
    assert result["gate_version"] == GATE_VERSION == "qlib_phase1_gate_v1"


def test_official_backtest_failure_is_rejected():
    payload = passing_payload()
    payload["official_backtest"]["sharpe"] = 0.79

    result = evaluate_promotion_gate(**payload)

    assert result["status"] == "rejected"
    assert "official_sharpe_below_0_80" in result["reason_codes"]


def test_divergence_requires_review_but_review_cannot_override_hard_failure():
    payload = passing_payload()
    payload["official_backtest"]["annual_return"] = 0.18
    payload["ashare_backtest"]["annual_return"] = 0.10

    assert evaluate_promotion_gate(**payload)["status"] == "review_required"

    payload["official_backtest"]["sharpe"] = 0.20
    payload["divergence_reviewed"] = True
    assert evaluate_promotion_gate(**payload)["status"] == "rejected"


def test_missing_quality_and_ashare_failure_are_both_reported():
    payload = passing_payload()
    payload["quality_passed"] = False
    payload["ashare_backtest"]["after_cost_return"] = -0.01

    result = evaluate_promotion_gate(**payload)

    assert result["status"] == "rejected"
    assert "dataset_quality_failed" in result["reason_codes"]
    assert "ashare_after_cost_return_not_positive" in result["reason_codes"]

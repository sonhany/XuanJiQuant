def test_failed_metrics_are_rejected():
    from quant.qlib.evaluator import promotion_status

    assert (
        promotion_status(
            {
                "rank_ic": 0.01,
                "icir": 0.5,
                "sharpe": 1.0,
                "max_drawdown": -0.1,
                "after_cost_long_short": 0.1,
                "segment_sign_consistent": True,
            }
        )
        == "rejected"
    )


def test_metrics_at_all_thresholds_are_candidate():
    from quant.qlib.evaluator import promotion_status

    assert (
        promotion_status(
            {
                "rank_ic": 0.02,
                "icir": 0.30,
                "sharpe": 0.80,
                "max_drawdown": -0.20,
                "after_cost_long_short": 0.01,
                "segment_sign_consistent": True,
            }
        )
        == "candidate"
    )

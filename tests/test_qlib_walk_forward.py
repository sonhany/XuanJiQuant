import pandas as pd


def _passing_window():
    return {
        "rank_ic": 0.04,
        "icir": 0.5,
        "after_cost_long_short": 0.08,
        "sharpe": 1.1,
        "max_drawdown": -0.12,
    }


def _allowed_failure():
    return {
        "rank_ic": -0.02,
        "icir": 0.1,
        "after_cost_long_short": -0.01,
        "sharpe": 0.2,
        "max_drawdown": -0.18,
    }


def test_walk_forward_windows_are_ordered_and_non_overlapping():
    from quant.qlib.walk_forward import build_walk_forward_windows

    calendar = pd.date_range("2020-01-01", "2026-07-01", freq="B")
    windows = build_walk_forward_windows(
        calendar,
        train_months=36,
        valid_months=6,
        test_months=6,
        step_months=3,
    )

    assert len(windows) >= 4
    for window in windows:
        assert window["train"][1] < window["valid"][0]
        assert window["valid"][1] < window["test"][0]


def test_walk_forward_candidate_requires_all_hard_metrics():
    from quant.qlib.walk_forward import aggregate_promotion_status

    status = aggregate_promotion_status(
        [_passing_window()] * 7 + [_allowed_failure()] * 3,
        quality_passed=True,
    )

    assert status == "candidate"


def test_walk_forward_is_rejected_on_quality_failure():
    from quant.qlib.walk_forward import aggregate_promotion_status

    assert aggregate_promotion_status([_passing_window()] * 8, False) == "rejected"

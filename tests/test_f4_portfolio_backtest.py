import pytest

from quant.strategy.portfolio_backtest import CostModel, simulate_rebalance


def test_rebalance_applies_lot_and_adv_capacity():
    result = simulate_rebalance(
        cash=1_000_000,
        positions={},
        target_weights={"600000": 0.10},
        market={
            "600000": {
                "price": 10.0,
                "adv20_shares": 5000,
                "tradable": True,
            }
        },
        cost=CostModel(),
    )
    assert result.fills[0].quantity == 500
    assert result.capacity_rejected_notional == 95_000
    assert result.fills[0].quantity % 100 == 0


def test_limit_up_and_suspension_reject_buys():
    result = simulate_rebalance(
        cash=100_000,
        positions={},
        target_weights={"600000": 0.10, "600001": 0.10},
        market={
            "600000": {
                "price": 10,
                "adv20_shares": 100000,
                "tradable": True,
                "limit_up": True,
            },
            "600001": {
                "price": 10,
                "adv20_shares": 100000,
                "tradable": False,
            },
        },
        cost=CostModel(),
    )
    assert result.fills == ()
    assert result.reject_counts == {"limit_up": 1, "suspended": 1}


def test_t1_locked_position_cannot_be_sold():
    result = simulate_rebalance(
        cash=0,
        positions={"600000": 1000},
        target_weights={"600000": 0.0},
        market={
            "600000": {
                "price": 10,
                "adv20_shares": 100000,
                "tradable": True,
                "sellable_shares": 0,
            }
        },
        cost=CostModel(),
    )
    assert result.fills == ()
    assert result.reject_counts == {"t1_locked": 1}
    assert result.positions["600000"] == 1000


@pytest.mark.parametrize("adv", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_adv_is_rejected_as_missing_capacity_data(adv):
    result = simulate_rebalance(
        cash=100_000,
        positions={},
        target_weights={"600000": 0.10},
        market={
            "600000": {
                "price": 10.0,
                "adv20_shares": adv,
                "tradable": True,
            }
        },
        cost=CostModel(),
    )

    assert result.fills == ()
    assert result.reject_counts == {"capacity_data_missing": 1}
    assert result.capacity_rejected_notional == 0.0


def test_f4_pipeline_identity_versions_tradable_score_and_finite_adv_semantics():
    from quant.strategy.f4_real_pipeline import F4_PIPELINE_VERSION

    assert (
        F4_PIPELINE_VERSION
        == "f4-real-pipeline-v7-pit-tradable-finite-adv-qlib-sqlite-market"
    )

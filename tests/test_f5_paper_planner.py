import pytest

from quant.paper_execution.planner import build_order_intents
from quant.paper_execution.policy import PaperExecutionPolicy


def _risk(**patch):
    return {
        "max_position_count": 10,
        "max_position_pct": 0.2,
        "max_gross_exposure_pct": 95,
        "min_cash_buffer_pct": 2,
        "max_orders_per_run": 20,
        "max_daily_turnover_pct": 100,
    } | patch


def test_planner_sells_first_buys_lots_and_clears_odd_lot_exit():
    selection = {
        "portfolio_id": "p1",
        "positions": [
            {"code": "000001", "target_weight": 0.2},
            {"code": "000002", "target_weight": 0.2},
        ],
    }
    account = {
        "cash": 10_000,
        "total_equity": 100_000,
        "positions": {
            "000001": {"quantity": 3000, "available_qty": 3000},
            "000003": {"quantity": 55, "available_qty": 55},
        },
    }
    orders = build_order_intents(selection, account, _risk(), {"000001": 10, "000002": 10, "000003": 10})
    assert [order["direction"] for order in orders[:2]] == ["sell", "sell"]
    exit_order = next(order for order in orders if order["code"] == "000003")
    assert exit_order["quantity"] == 55
    buy = next(order for order in orders if order["code"] == "000002")
    assert buy["quantity"] % 100 == 0
    assert all(order["client_order_id"].startswith("paper_order_") for order in orders)


def test_planner_omits_unchanged_targets_and_scales_buys_to_cash():
    selection = {"portfolio_id": "p1", "positions": [{"code": "000001", "target_weight": 0.5}]}
    account = {"cash": 1_000, "total_equity": 10_000, "positions": {}}
    orders = build_order_intents(selection, account, _risk(min_cash_buffer_pct=0), {"000001": 10})
    assert orders[0]["quantity"] == 100
    unchanged = {"cash": 5_000, "total_equity": 10_000, "positions": {"000001": {"quantity": 500, "available_qty": 500}}}
    assert build_order_intents(selection, unchanged, _risk(), {"000001": 10}) == []


def test_planner_never_silently_truncates_incompatible_portfolio():
    selection = {"portfolio_id": "p1", "positions": [{"code": f"{index:06d}", "target_weight": 0.05} for index in range(11)]}
    with pytest.raises(ValueError, match="portfolio_policy_incompatible"):
        build_order_intents(selection, {"cash": 100_000, "total_equity": 100_000, "positions": {}}, _risk(), {f"{index:06d}": 10 for index in range(11)})


def test_planner_caps_large_rebalance_sell_first_with_explicit_deferred_count():
    selection = {
        "portfolio_id": "p-staged",
        "positions": [
            {"code": f"2{index:05d}", "target_weight": 0.095}
            for index in range(10)
        ],
    }
    account = {
        "cash": 1_000,
        "total_equity": 1_000_000,
        "positions": {
            f"1{index:05d}": {"quantity": 10_000, "available_qty": 10_000}
            for index in range(16)
        },
    }
    prices = {
        **{f"1{index:05d}": 10.0 for index in range(16)},
        **{f"2{index:05d}": 10.0 for index in range(10)},
    }

    orders = build_order_intents(selection, account, _risk(), prices)

    assert len(orders) == 20
    assert [order["direction"] for order in orders[:16]] == ["sell"] * 16
    assert [order["direction"] for order in orders[16:]] == ["buy"] * 4
    assert all(order["partial_rebalance"] is True for order in orders)
    assert all(order["planned_order_count"] == 26 for order in orders)
    assert all(order["deferred_order_count"] == 6 for order in orders)


def test_staged_rebalance_changes_policy_identity():
    assert PaperExecutionPolicy().version == "f5-paper-policy-v2-staged-rebalance"

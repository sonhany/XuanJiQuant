import pytest

from quant.risk.gateway import check_order


BASE_PORTFOLIO = {
    "cash": 100_000,
    "market_value": 0,
    "total_equity": 100_000,
    "positions": {},
}
BASE_CONFIG = {
    "risk": {
        "kill_switch": False,
        "max_position_pct": 1.0,
        "max_gross_exposure_pct": 100,
        "max_position_count": 99,
        "max_orders_per_run": 99,
        "min_cash_buffer_pct": 0,
        "max_daily_turnover_pct": 0,
        "capital_cap": 0,
        "max_daily_loss_pct": 0,
        "allow_buy_st": False,
        "allow_buy_limit_up": False,
        "allow_sell_limit_down": False,
    }
}


def intent(**patch):
    base = {"code": "600519", "direction": "buy", "quantity": 100, "price": 10}
    base.update(patch)
    return base


def cfg(**risk_patch):
    risk = dict(BASE_CONFIG["risk"])
    risk.update(risk_patch)
    return {"risk": risk}


@pytest.mark.parametrize(
    "order,portfolio,market,config,reason",
    [
        (intent(), BASE_PORTFOLIO, {}, cfg(kill_switch=True), "kill_switch_active"),
        (intent(code=""), BASE_PORTFOLIO, {}, BASE_CONFIG, "missing_code"),
        (intent(direction="short"), BASE_PORTFOLIO, {}, BASE_CONFIG, "invalid_direction"),
        (intent(quantity=0), BASE_PORTFOLIO, {}, BASE_CONFIG, "invalid_quantity"),
        (intent(quantity=50), BASE_PORTFOLIO, {}, BASE_CONFIG, "not_board_lot"),
        (intent(price=0), BASE_PORTFOLIO, {}, BASE_CONFIG, "invalid_price_or_equity"),
        (intent(), BASE_PORTFOLIO, {"is_st": True}, BASE_CONFIG, "st_buy_blocked"),
        (intent(), BASE_PORTFOLIO, {"suspended": True}, BASE_CONFIG, "suspended"),
        (intent(), BASE_PORTFOLIO, {"limit_state": "up"}, BASE_CONFIG, "limit_up_blocked"),
        (intent(direction="sell"), {"cash": 0, "total_equity": 100_000, "positions": {"600519": {"quantity": 100, "available_qty": 100, "avg_price": 10}}}, {"limit_state": "down"}, BASE_CONFIG, "limit_down_blocked"),
        (intent(), {"cash": 100_000, "total_equity": 200_000, "positions": {}}, {}, cfg(capital_cap=100_000), "capital_cap_exceeded"),
        (intent(), {"cash": 100_000, "total_equity": 100_000, "daily_pnl": -6_000, "positions": {}}, {}, cfg(max_daily_loss_pct=5), "daily_loss_fuse"),
        (intent(), {"cash": 100_000, "total_equity": 100_000, "drawdown_pct": -13, "positions": {}}, {}, cfg(max_drawdown_pct=12), "max_drawdown_fuse"),
        (intent(attempted_orders=3), BASE_PORTFOLIO, {}, cfg(max_orders_per_run=3), "max_orders_per_run"),
        (intent(quantity=3000), BASE_PORTFOLIO, {}, cfg(max_position_pct=0.2), "max_position_pct"),
        (intent(code="000001"), {"cash": 100_000, "total_equity": 100_000, "positions": {"600519": {"quantity": 100, "avg_price": 10}}}, {}, cfg(max_position_count=1), "max_position_count"),
        (intent(quantity=9600), {"cash": 100_000, "total_equity": 100_000, "positions": {}}, {}, cfg(max_gross_exposure_pct=95), "max_gross_exposure_pct"),
        (intent(quantity=9900), BASE_PORTFOLIO, {}, cfg(min_cash_buffer_pct=2), "min_cash_buffer_pct"),
        (intent(direction="sell", quantity=200), {"cash": 0, "total_equity": 100_000, "positions": {"600519": {"quantity": 200, "available_qty": 100, "avg_price": 10}}}, {}, BASE_CONFIG, "t1_available_qty"),
        (intent(current_turnover_notional=35_000), BASE_PORTFOLIO, {}, cfg(max_daily_turnover_pct=35), "max_daily_turnover_pct"),
        (intent(decision={"trade_policy": "no_new_position"}), BASE_PORTFOLIO, {}, BASE_CONFIG, "decision_policy_blocks_buy"),
        (intent(decision={"objective": {"enforce_objective_risk_gate": True, "risk_mode": "no_new_position"}}), BASE_PORTFOLIO, {}, BASE_CONFIG, "objective_risk_mode_blocks_buy"),
    ],
)
def test_check_order_rejects_all_money_gate_reason_branches(order, portfolio, market, config, reason):
    result = check_order(order, portfolio, market, config)
    assert result["approved"] is False
    assert reason in result["reasons"]


def test_check_order_approves_clean_buy():
    result = check_order(intent(), BASE_PORTFOLIO, {}, BASE_CONFIG)
    assert result["approved"] is True
    assert result["reason"] == "ok"

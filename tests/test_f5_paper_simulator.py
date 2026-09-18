from quant.paper_execution.policy import PaperExecutionPolicy
from quant.paper_execution.simulator import simulate_order


def _intent(direction="buy", quantity=1000):
    return {"order_id": "o1", "client_order_id": "c1", "code": "600519", "direction": direction, "quantity": quantity}


def _bar(**patch):
    return {"date": "20260819", "open": 10.0, "close": 10.5, "volume": 10_000, "suspended": False, "limit_up": False, "limit_down": False} | patch


def test_simulator_fills_at_governed_open_with_costs_and_t1():
    result = simulate_order(_intent(), _bar(), {"cash": 100_000, "positions": {}}, PaperExecutionPolicy(enabled=True))
    assert result.order["status"] == "filled"
    assert result.fill["price"] > 10.0
    assert result.fill["commission"] >= 5.0
    assert result.position_delta["available_delta"] == 0
    assert result.cash_delta < -10_000


def test_simulator_rejects_suspension_limits_missing_price_and_t1_sell():
    policy = PaperExecutionPolicy(enabled=True)
    assert simulate_order(_intent(), _bar(suspended=True), {"cash": 100_000, "positions": {}}, policy).order["status"] == "rejected"
    assert simulate_order(_intent(), _bar(limit_up=True), {"cash": 100_000, "positions": {}}, policy).order["reject_reason"] == "buy_limit_up"
    assert simulate_order(_intent("sell"), _bar(limit_down=True), {"cash": 0, "positions": {"600519": {"quantity": 1000, "available_qty": 1000}}}, policy).order["reject_reason"] == "sell_limit_down"
    assert simulate_order(_intent(), _bar(open=None), {"cash": 100_000, "positions": {}}, policy).order["reject_reason"] == "missing_open_price"
    assert simulate_order(_intent("sell"), _bar(), {"cash": 0, "positions": {"600519": {"quantity": 1000, "available_qty": 0}}}, policy).order["reject_reason"] == "t1_unavailable"


def test_volume_cap_has_explicit_partial_fill_terminal_remainder():
    policy = PaperExecutionPolicy(enabled=True, participation_cap=0.1)
    result = simulate_order(_intent(quantity=1000), _bar(volume=5_000), {"cash": 100_000, "positions": {}}, policy)
    assert result.order["status"] == "partially_filled_cancelled"
    assert result.order["filled_qty"] == 500
    assert result.order["cancelled_qty"] == 500
    assert result.order["filled_qty"] + result.order["cancelled_qty"] == result.order["quantity"]


def test_intraday_simulator_uses_realtime_price_not_daily_open():
    from quant.paper_execution.simulator import simulate_intraday_order

    quote = _bar(open=1.0, price=10.5, quote_timestamp="20260820105400", date="20260820")
    result = simulate_intraday_order(
        _intent(), quote, {"cash": 100_000, "positions": {}}, PaperExecutionPolicy(enabled=True)
    )

    assert result.order["status"] == "filled"
    assert result.fill["price"] > 10.5
    assert result.fill["market_fact_type"] == "realtime_quote"
    assert result.fill["quote_timestamp"] == "20260820105400"


def test_intraday_simulator_keeps_limits_suspension_and_capacity_rules():
    from quant.paper_execution.simulator import simulate_intraday_order

    policy = PaperExecutionPolicy(enabled=True, participation_cap=0.1)
    account = {"cash": 100_000, "positions": {}}
    assert simulate_intraday_order(_intent(), _bar(price=10, suspended=True), account, policy).order["reject_reason"] == "suspended"
    assert simulate_intraday_order(_intent(), _bar(price=10, limit_up=True), account, policy).order["reject_reason"] == "buy_limit_up"
    partial = simulate_intraday_order(_intent( quantity=1000), _bar(price=10, volume=5_000), account, policy)
    assert partial.order["status"] == "partially_filled_cancelled"
    assert partial.order["filled_qty"] == 500

from quant.paper_execution.reconciler import reconcile_run


def _fixture():
    run = {"run_id": "r1", "portfolio_id": "p1", "validation_id": "v1", "policy_hash": "h1"}
    orders = [{"run_id": "r1", "order_id": "o1", "code": "600519", "direction": "buy", "quantity": 100, "filled_qty": 100, "cancelled_qty": 0, "status": "filled"}]
    fills = [{"run_id": "r1", "fill_id": "f1", "order_id": "o1", "code": "600519", "direction": "buy", "quantity": 100, "price": 10.0, "commission": 5.0, "stamp_tax": 0.0}]
    cash = [{"run_id": "r1", "entry_id": "c1", "entry_type": "buy", "amount": -1005.0, "balance_after": 8995.0}]
    initial = {"cash": 10_000.0, "positions": {}}
    final = {"cash": 8995.0, "positions": {"600519": {"quantity": 100, "available_qty": 0, "today_buy_qty": 100, "current_price": 10.5}}}
    equity = {"run_id": "r1", "cash": 8995.0, "market_value": 1050.0, "total_equity": 10045.0}
    return run, initial, final, orders, fills, cash, equity


def test_reconciliation_passes_all_invariants_for_balanced_run():
    result = reconcile_run(*_fixture())
    assert result.passed is True
    assert len(result.checks) == 10
    assert all(check["passed"] for check in result.checks)


def test_reconciliation_catches_duplicate_fill_negative_cash_and_bad_t1():
    run, initial, final, orders, fills, cash, equity = _fixture()
    fills.append(dict(fills[0]))
    final["cash"] = -1
    final["positions"]["600519"]["available_qty"] = 100
    result = reconcile_run(run, initial, final, orders, fills, cash, equity)
    failed = {check["check_name"] for check in result.checks if not check["passed"]}
    assert "order_fill_quantities" in failed
    assert "non_negative_balances" in failed
    assert "t1_availability" in failed
    assert "idempotent_side_effects" in failed


def test_reconciliation_rejects_nonterminal_order_and_identity_mismatch():
    run, initial, final, orders, fills, cash, equity = _fixture()
    orders[0]["status"] = "executing"
    fills[0]["run_id"] = "other"
    result = reconcile_run(run, initial, final, orders, fills, cash, equity)
    failed = {check["check_name"] for check in result.checks if not check["passed"]}
    assert "terminal_orders" in failed
    assert "run_identity_binding" in failed

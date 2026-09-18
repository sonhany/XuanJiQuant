"""F5 paper account reconciliation invariants."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .contracts import TERMINAL_ORDER_STATES


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    passed: bool
    checks: tuple[dict[str, Any], ...]


def _mapping_positions(account: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    value = account.get("positions") or {}
    if isinstance(value, Mapping):
        return {str(code): row for code, row in value.items()}
    return {str(row.get("code")): row for row in value}


def _check(name: str, passed: bool, expected: Any, actual: Any) -> dict[str, Any]:
    return {"check_name": name, "passed": bool(passed), "expected": expected, "actual": actual}


def reconcile_run(
    run: Mapping[str, Any],
    initial_account: Mapping[str, Any],
    final_account: Mapping[str, Any],
    orders: Iterable[Mapping[str, Any]],
    fills: Iterable[Mapping[str, Any]],
    cash_entries: Iterable[Mapping[str, Any]],
    equity_snapshot: Mapping[str, Any],
) -> ReconciliationResult:
    """Evaluate ten non-negotiable deterministic ledger invariants."""

    order_rows = list(orders)
    fill_rows = list(fills)
    cash_rows = list(cash_entries)
    fills_by_order: dict[str, int] = {}
    for fill in fill_rows:
        fills_by_order[str(fill.get("order_id"))] = fills_by_order.get(str(fill.get("order_id")), 0) + int(fill.get("quantity") or 0)
    quantities_ok = all(
        fills_by_order.get(str(order.get("order_id")), 0) == int(order.get("filled_qty") or 0)
        and int(order.get("filled_qty") or 0) <= int(order.get("quantity") or 0)
        and int(order.get("filled_qty") or 0) + int(order.get("cancelled_qty") or 0) == int(order.get("quantity") or 0)
        for order in order_rows
    )

    terminal_ok = all(str(order.get("status")) in TERMINAL_ORDER_STATES for order in order_rows)
    initial_cash = float(initial_account.get("cash") or 0)
    expected_cash = initial_cash + sum(float(entry.get("amount") or 0) for entry in cash_rows)
    final_cash = float(final_account.get("cash") or 0)
    cash_ok = math.isclose(expected_cash, final_cash, abs_tol=1e-6)

    initial_positions = _mapping_positions(initial_account)
    final_positions = _mapping_positions(final_account)
    expected_quantities = {code: int(row.get("quantity") or 0) for code, row in initial_positions.items()}
    for fill in fill_rows:
        code = str(fill.get("code") or "")
        sign = 1 if fill.get("direction") == "buy" else -1
        expected_quantities[code] = expected_quantities.get(code, 0) + sign * int(fill.get("quantity") or 0)
    actual_quantities = {code: int(row.get("quantity") or 0) for code, row in final_positions.items()}
    all_codes = set(expected_quantities) | set(actual_quantities)
    positions_ok = all(expected_quantities.get(code, 0) == actual_quantities.get(code, 0) for code in all_codes)

    non_negative = final_cash >= -1e-8 and all(
        int(row.get("quantity") or 0) >= 0 and int(row.get("available_qty") or 0) >= 0
        for row in final_positions.values()
    )
    bought_by_code: dict[str, int] = {}
    for fill in fill_rows:
        if fill.get("direction") == "buy":
            code = str(fill.get("code") or "")
            bought_by_code[code] = bought_by_code.get(code, 0) + int(fill.get("quantity") or 0)
    t1_ok = all(
        int(final_positions.get(code, {}).get("today_buy_qty") or 0) >= qty
        and int(final_positions.get(code, {}).get("available_qty") or 0)
        <= int(final_positions.get(code, {}).get("quantity") or 0) - qty
        for code, qty in bought_by_code.items()
    )

    market_value = sum(
        int(row.get("quantity") or 0) * float(row.get("current_price") or 0)
        for row in final_positions.values()
    )
    equity_ok = (
        math.isclose(float(equity_snapshot.get("cash") or 0), final_cash, abs_tol=1e-6)
        and math.isclose(float(equity_snapshot.get("market_value") or 0), market_value, abs_tol=1e-6)
        and math.isclose(float(equity_snapshot.get("total_equity") or 0), final_cash + market_value, abs_tol=1e-6)
    )
    run_id = str(run.get("run_id") or "")
    bound_rows = order_rows + fill_rows + cash_rows + [equity_snapshot]
    binding_ok = bool(run_id) and all(str(row.get("run_id") or "") == run_id for row in bound_rows)
    fill_ids = [str(row.get("fill_id") or "") for row in fill_rows]
    cash_ids = [str(row.get("entry_id") or "") for row in cash_rows]
    order_ids = [str(row.get("order_id") or "") for row in order_rows]
    idempotent = (
        len(fill_ids) == len(set(fill_ids))
        and len(cash_ids) == len(set(cash_ids))
        and len(order_ids) == len(set(order_ids))
        and all(fill_ids)
        and all(cash_ids)
        and all(order_ids)
    )
    identity_complete = all(str(run.get(key) or "") for key in ("portfolio_id", "validation_id", "policy_hash"))
    final_balances_match_entries = not cash_rows or math.isclose(
        float(cash_rows[-1].get("balance_after") or 0), final_cash, abs_tol=1e-6
    )

    checks = (
        _check("order_fill_quantities", quantities_ok, "fills=filled<=quantity and terminal remainder", fills_by_order),
        _check("terminal_orders", terminal_ok, sorted(TERMINAL_ORDER_STATES), [row.get("status") for row in order_rows]),
        _check("cash_balance", cash_ok, expected_cash, final_cash),
        _check("position_balance", positions_ok, expected_quantities, actual_quantities),
        _check("non_negative_balances", non_negative, ">=0", {"cash": final_cash, "positions": actual_quantities}),
        _check("t1_availability", t1_ok, "today buys unavailable", bought_by_code),
        _check("equity_identity", equity_ok, final_cash + market_value, equity_snapshot.get("total_equity")),
        _check("run_identity_binding", binding_ok, run_id, [row.get("run_id") for row in bound_rows]),
        _check("idempotent_side_effects", idempotent, "unique nonempty IDs", {"orders": order_ids, "fills": fill_ids, "cash": cash_ids}),
        _check("identity_and_cash_tail", identity_complete and final_balances_match_entries, "complete run identity and balanced tail", run),
    )
    return ReconciliationResult(passed=all(row["passed"] for row in checks), checks=checks)

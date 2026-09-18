"""Deterministic target-weight to paper-order planner."""

from __future__ import annotations

import math
from typing import Any, Mapping

from .contracts import stable_id


def _position_map(account: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    positions = account.get("positions") or {}
    if isinstance(positions, Mapping):
        return positions
    return {str(row.get("code")): row for row in positions}


def build_order_intents(
    selection: Mapping[str, Any],
    account: Mapping[str, Any],
    risk: Mapping[str, Any],
    prices: Mapping[str, float],
    *,
    run_id: str = "unclaimed",
    lot_size: int = 100,
    frozen_target_quantities: Mapping[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Build sell-first intents without silently altering the target universe."""

    targets = list(selection.get("positions") or [])
    if len(targets) > int(risk.get("max_position_count") or 0):
        raise ValueError("portfolio_policy_incompatible:max_position_count")
    if len(targets) + len(_position_map(account)) > int(risk.get("max_orders_per_run") or 0) * 2:
        raise ValueError("portfolio_policy_incompatible:max_orders_per_run")
    equity = float(account.get("total_equity") or 0)
    if equity <= 0:
        raise ValueError("account_equity_invalid")
    current = _position_map(account)
    target_by_code = {str(row.get("code") or "").zfill(6): row for row in targets}
    frozen_targets = {
        str(code).zfill(6): max(0, int(quantity))
        for code, quantity in (frozen_target_quantities or {}).items()
    }
    current_codes = {str(code).zfill(6) for code in current}
    codes = sorted(current_codes | set(target_by_code))
    sells: list[dict[str, Any]] = []
    buys: list[dict[str, Any]] = []
    cash = float(account.get("cash") or 0)
    cash_buffer = equity * float(risk.get("min_cash_buffer_pct") or 0) / 100.0

    planned: list[tuple[str, str, int, int, int, float]] = []
    for code in codes:
        price = float(prices.get(code) or 0)
        if not math.isfinite(price) or price <= 0:
            raise ValueError(f"price_unavailable:{code}")
        row = target_by_code.get(code)
        current_row = current.get(code) or current.get(code.lstrip("0")) or {}
        current_qty = int(current_row.get("quantity") or 0)
        target_weight = float((row or {}).get("target_weight") or 0)
        if code in frozen_targets:
            target_qty = frozen_targets[code]
        else:
            raw_target = max(0, math.floor((equity * target_weight) / price))
            target_qty = (raw_target // lot_size) * lot_size
        delta = target_qty - current_qty
        if delta < 0:
            available = int(current_row.get("available_qty", current_qty) or 0)
            quantity = min(-delta, available)
            if row is None:
                quantity = available  # a full exit may include an odd lot
            if quantity > 0:
                planned.append(("sell", code, quantity, target_qty, current_qty, price))
        elif delta > 0:
            quantity = (delta // lot_size) * lot_size
            if quantity > 0:
                planned.append(("buy", code, quantity, target_qty, current_qty, price))

    for direction, code, quantity, target_qty, current_qty, price in sorted(
        planned, key=lambda row: (0 if row[0] == "sell" else 1, row[1])
    ):
        if direction == "sell":
            cash += quantity * price
        else:
            affordable = max(0, math.floor((cash - cash_buffer) / price))
            affordable = (affordable // lot_size) * lot_size
            quantity = min(quantity, affordable)
            if quantity <= 0:
                continue
            cash -= quantity * price
        client_order_id = stable_id(
            "paper_order", run_id, selection.get("portfolio_id"), code, direction, quantity
        )
        intent = {
            "order_id": stable_id("paper_order_record", client_order_id),
            "client_order_id": client_order_id,
            "code": code,
            "direction": direction,
            "target_qty": target_qty,
            "current_qty": current_qty,
            "quantity": quantity,
            "filled_qty": 0,
            "cancelled_qty": 0,
            "status": "planned",
            "request_price": price,
        }
        (sells if direction == "sell" else buys).append(intent)
    orders = sells + buys
    max_orders = int(risk.get("max_orders_per_run") or 0)
    if len(orders) > max_orders:
        planned_order_count = len(orders)
        orders = orders[:max_orders]
        deferred_order_count = planned_order_count - len(orders)
        for order in orders:
            order["partial_rebalance"] = True
            order["planned_order_count"] = planned_order_count
            order["deferred_order_count"] = deferred_order_count
    return orders

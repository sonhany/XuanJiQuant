"""Deterministic next-session daily-bar fill simulation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from .contracts import stable_id
from .policy import PaperExecutionPolicy
from .slippage import ISlippageModel, FixedRateSlippage


@dataclass(frozen=True, slots=True)
class SimulationResult:
    order: dict[str, Any]
    fill: dict[str, Any] | None
    cash_delta: float
    position_delta: dict[str, int]


def _rejected(intent: Mapping[str, Any], reason: str) -> SimulationResult:
    order = dict(intent)
    order.update(status="rejected", reject_reason=reason, filled_qty=0, cancelled_qty=int(intent["quantity"]))
    return SimulationResult(order=order, fill=None, cash_delta=0.0, position_delta={"quantity_delta": 0, "available_delta": 0})


def simulate_order(
    intent: Mapping[str, Any],
    market_bar: Mapping[str, Any] | None,
    account: Mapping[str, Any],
    policy: PaperExecutionPolicy,
    slippage_model: ISlippageModel | None = None,
) -> SimulationResult:
    """Simulate exactly one order using governed daily opening facts.

    Args:
        slippage_model: 可插拔滑点模型。None 时使用 policy.slippage_rate 构建
                        FixedRateSlippage (向后兼容)。
    """

    if not market_bar:
        return _rejected(intent, "market_bar_missing")
    if bool(market_bar.get("suspended")) or float(market_bar.get("volume") or 0) <= 0:
        return _rejected(intent, "suspended")
    direction = str(intent.get("direction") or "")
    if direction == "buy" and bool(market_bar.get("limit_up")):
        return _rejected(intent, "buy_limit_up")
    if direction == "sell" and bool(market_bar.get("limit_down")):
        return _rejected(intent, "sell_limit_down")
    raw_open = market_bar.get("open")
    try:
        open_price = float(raw_open)
    except (TypeError, ValueError):
        return _rejected(intent, "missing_open_price")
    if not math.isfinite(open_price) or open_price <= 0:
        return _rejected(intent, "missing_open_price")
    quantity = int(intent.get("quantity") or 0)
    if quantity <= 0:
        return _rejected(intent, "quantity_invalid")
    positions = account.get("positions") or {}
    position = positions.get(intent["code"], {}) if isinstance(positions, Mapping) else {}
    if direction == "sell" and int(position.get("available_qty") or 0) < quantity:
        return _rejected(intent, "t1_unavailable")

    capacity = math.floor(float(market_bar.get("volume") or 0) * policy.participation_cap)
    if direction == "buy":
        capacity = (capacity // policy.lot_size) * policy.lot_size
    fill_qty = min(quantity, max(0, capacity))
    if fill_qty <= 0:
        return _rejected(intent, "capacity_unavailable")
    # 滑点: 优先使用注入的 slippage_model，否则回退到 policy.slippage_rate
    if slippage_model is None:
        slippage_model = FixedRateSlippage(rate=policy.slippage_rate)
    adv = int(market_bar.get("volume") or 0)
    execution_price, slippage_cost = slippage_model.compute(
        price=open_price, direction=direction, quantity=fill_qty, adv=adv,
    )
    if direction == "buy":
        affordable = int(float(account.get("cash") or 0) / execution_price)
        affordable = (affordable // policy.lot_size) * policy.lot_size
        fill_qty = min(fill_qty, affordable)
        if fill_qty <= 0:
            return _rejected(intent, "cash_insufficient")
    notional = execution_price * fill_qty
    commission = max(policy.minimum_commission, notional * policy.commission_rate)
    stamp_tax = notional * policy.stamp_tax_rate if direction == "sell" else 0.0
    transfer_fee = notional * policy.transfer_fee_rate
    fees = commission + stamp_tax + transfer_fee
    cash_delta = -(notional + fees) if direction == "buy" else notional - fees
    cancelled = quantity - fill_qty
    status = "filled" if cancelled == 0 else "partially_filled_cancelled"
    order = dict(intent)
    order.update(
        status=status,
        reject_reason=None,
        filled_qty=fill_qty,
        cancelled_qty=cancelled,
        filled_price=execution_price,
    )
    fill = {
        "fill_id": stable_id("paper_fill", intent["order_id"], market_bar.get("date"), fill_qty, execution_price),
        "order_id": intent["order_id"],
        "code": intent["code"],
        "direction": direction,
        "quantity": fill_qty,
        "price": execution_price,
        "commission": commission,
        "stamp_tax": stamp_tax,
        "transfer_fee": transfer_fee,
        "slippage": slippage_cost,
        "capacity_quantity": capacity,
        "market_date": market_bar.get("date"),
    }
    sign = 1 if direction == "buy" else -1
    return SimulationResult(
        order=order,
        fill=fill,
        cash_delta=cash_delta,
        position_delta={
            "quantity_delta": sign * fill_qty,
            "available_delta": 0 if direction == "buy" else -fill_qty,
            "today_buy_delta": fill_qty if direction == "buy" else 0,
        },
    )


def simulate_intraday_order(
    intent: Mapping[str, Any],
    realtime_quote: Mapping[str, Any] | None,
    account: Mapping[str, Any],
    policy: PaperExecutionPolicy,
    slippage_model: ISlippageModel | None = None,
) -> SimulationResult:
    """Simulate one order from an explicitly identified realtime quote."""

    if not realtime_quote:
        return _rejected(intent, "intraday_quote_missing")
    fact = dict(realtime_quote)
    fact["open"] = fact.get("price")
    result = simulate_order(intent, fact, account, policy, slippage_model=slippage_model)
    if result.fill is None:
        return result
    fill = {
        **result.fill,
        "market_fact_type": "realtime_quote",
        "quote_timestamp": fact.get("quote_timestamp") or fact.get("timestamp"),
        "quote_source": fact.get("source"),
    }
    return SimulationResult(
        order=result.order,
        fill=fill,
        cash_delta=result.cash_delta,
        position_delta=result.position_delta,
    )

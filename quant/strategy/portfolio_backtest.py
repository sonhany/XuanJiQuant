"""Research-only target-weight rebalance simulation for F4."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping

from quant.paper_execution.slippage import ISlippageModel, FixedRateSlippage, create_slippage_model


@dataclass(frozen=True, slots=True)
class CostModel:
    commission_rate: float = 0.0003
    min_commission: float = 5.0
    stamp_tax_rate: float = 0.0005
    transfer_fee_rate: float = 0.00001
    slippage_rate: float = 0.0001
    slippage_config: dict | None = None
    adv_participation: float = 0.10
    lot_size: int = 100
    version: str = "cost-model-v2"

    @property
    def slippage_model(self) -> ISlippageModel:
        """延迟构建滑点模型 (优先用 slippage_config, 否则回退到 slippage_rate)。"""
        if self.slippage_config:
            return create_slippage_model(self.slippage_config)
        return FixedRateSlippage(rate=self.slippage_rate)


@dataclass(frozen=True, slots=True)
class PortfolioFill:
    code: str
    direction: str
    quantity: int
    price: float
    commission: float
    stamp_tax: float
    transfer_fee: float
    slippage: float


@dataclass(frozen=True, slots=True)
class RebalanceResult:
    cash: float
    positions: dict[str, int]
    fills: tuple[PortfolioFill, ...]
    reject_counts: dict[str, int]
    capacity_rejected_notional: float


def _reject(counts: dict[str, int], reason: str) -> None:
    counts[reason] = counts.get(reason, 0) + 1


def _position_quantity(value: object) -> int:
    if isinstance(value, Mapping):
        value = value.get("quantity", 0)
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def simulate_rebalance(
    *,
    cash: float,
    positions: Mapping[str, object],
    target_weights: Mapping[str, float],
    market: Mapping[str, Mapping[str, object]],
    cost: CostModel,
) -> RebalanceResult:
    holdings = {str(code): _position_quantity(value) for code, value in positions.items()}
    available_cash = float(cash)
    equity = available_cash
    for code, quantity in holdings.items():
        try:
            equity += quantity * float((market.get(code) or {}).get("price") or 0.0)
        except (TypeError, ValueError):
            pass

    desired: dict[str, int] = {}
    for code in set(holdings) | {str(key) for key in target_weights}:
        row = market.get(code) or {}
        try:
            price = float(row.get("price") or 0.0)
            weight = max(0.0, float(target_weights.get(code, 0.0) or 0.0))
        except (TypeError, ValueError):
            price, weight = 0.0, 0.0
        desired[code] = int(equity * weight / price) if price > 0 else holdings.get(code, 0)

    deltas = {code: desired[code] - holdings.get(code, 0) for code in desired}
    ordered = sorted(deltas, key=lambda code: (deltas[code] >= 0, code))
    fills: list[PortfolioFill] = []
    rejects: dict[str, int] = {}
    capacity_rejected = 0.0

    for code in ordered:
        delta = deltas[code]
        if delta == 0:
            continue
        row = market.get(code) or {}
        try:
            price = float(row.get("price") or 0.0)
        except (TypeError, ValueError):
            price = 0.0
        if price <= 0:
            _reject(rejects, "price_missing")
            continue
        if row.get("tradable") is not True:
            _reject(rejects, "suspended")
            continue
        if row.get("pit_tradable", True) is not True:
            _reject(rejects, "pit_not_tradable")
            continue
        direction = "buy" if delta > 0 else "sell"
        if direction == "buy" and row.get("limit_up") is True:
            _reject(rejects, "limit_up")
            continue
        if direction == "sell" and row.get("limit_down") is True:
            _reject(rejects, "limit_down")
            continue
        try:
            adv = float(row.get("adv20_shares") or 0.0)
        except (TypeError, ValueError):
            adv = 0.0
        if not math.isfinite(adv) or adv <= 0:
            _reject(rejects, "capacity_data_missing")
            continue
        capacity = int(adv * cost.adv_participation)
        if direction == "buy":
            capacity = capacity // cost.lot_size * cost.lot_size
            requested = delta // cost.lot_size * cost.lot_size
        else:
            requested = -delta
            sellable = int(row.get("sellable_shares", holdings.get(code, 0)) or 0)
            if sellable <= 0:
                _reject(rejects, "t1_locked")
                continue
            requested = min(requested, sellable)
        quantity = min(requested, capacity)
        if quantity < requested:
            capacity_rejected += (requested - quantity) * price
        if quantity <= 0:
            _reject(rejects, "capacity_limit")
            continue

        fill_price, slippage = cost.slippage_model.compute(
            price=price, direction=direction, quantity=quantity, adv=int(adv),
        )
        notional = quantity * fill_price
        commission = max(notional * cost.commission_rate, cost.min_commission)
        stamp_tax = notional * cost.stamp_tax_rate if direction == "sell" else 0.0
        transfer_fee = notional * cost.transfer_fee_rate
        total_fee = commission + stamp_tax + transfer_fee
        if direction == "buy":
            total_cost = notional + total_fee
            if total_cost > available_cash:
                affordable = int(
                    available_cash
                    / (fill_price * (1 + cost.commission_rate + cost.transfer_fee_rate))
                )
                quantity = min(quantity, affordable // cost.lot_size * cost.lot_size)
                if quantity <= 0:
                    _reject(rejects, "cash_insufficient")
                    continue
                notional = quantity * fill_price
                commission = max(notional * cost.commission_rate, cost.min_commission)
                transfer_fee = notional * cost.transfer_fee_rate
                total_fee = commission + transfer_fee
                total_cost = notional + total_fee
            available_cash -= total_cost
            holdings[code] = holdings.get(code, 0) + quantity
        else:
            available_cash += notional - total_fee
            holdings[code] = max(0, holdings.get(code, 0) - quantity)
        fills.append(
            PortfolioFill(
                code=code,
                direction=direction,
                quantity=quantity,
                price=round(fill_price, 6),
                commission=round(commission, 6),
                stamp_tax=round(stamp_tax, 6),
                transfer_fee=round(transfer_fee, 6),
                slippage=round(slippage, 6),
            )
        )
    return RebalanceResult(
        cash=round(available_cash, 6),
        positions=holdings,
        fills=tuple(fills),
        reject_counts=rejects,
        capacity_rejected_notional=round(capacity_rejected, 6),
    )

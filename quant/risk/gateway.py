"""Independent pre-trade risk gateway.

All autonomous orders should be checked here before they reach the execution
runner. The gateway returns an explicit decision and never calls an LLM.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from quant.risk.config import normalize_risk_config


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _risk_cfg(config: dict | None) -> dict:
    return normalize_risk_config(config or {})


def _positions_map(portfolio: dict | None) -> dict:
    portfolio = portfolio or {}
    positions = portfolio.get("positions", {})
    if isinstance(positions, dict):
        return positions
    if isinstance(positions, list):
        return {str(p.get("code")): p for p in positions if isinstance(p, dict) and p.get("code")}
    return {}


def _portfolio_equity(portfolio: dict | None) -> float:
    portfolio = portfolio or {}
    if portfolio.get("total_equity") is not None:
        return _to_float(portfolio.get("total_equity"), 0.0)
    cash = _to_float(portfolio.get("cash"), 0.0)
    mv = _to_float(portfolio.get("market_value"), 0.0)
    if mv <= 0:
        for p in _positions_map(portfolio).values():
            mv += _to_int(p.get("quantity"), 0) * _to_float(p.get("current_price", p.get("avg_price")), 0.0)
    return cash + mv


def check_order(intent: dict, portfolio: dict | None, market: dict | None, config: dict | None) -> dict:
    """Check one order intent.

    Args:
        intent: {"code", "direction", "quantity", "price", "source", ...}
        portfolio: account snapshot with cash and positions
        market: optional live market facts, such as {"is_st": false}
        config: paper/autonomous risk config

    Returns:
        {"approved": bool, "decision": "approved|rejected|modified", ...}
    """
    risk = _risk_cfg(config)
    portfolio = portfolio or {}
    market = market or {}
    positions = _positions_map(portfolio)
    code = str(intent.get("code", "")).split(".")[0].strip()
    direction = str(intent.get("direction", "")).lower()
    qty = _to_int(intent.get("quantity"), 0)
    price = _to_float(intent.get("price"), 0.0)
    equity = _portfolio_equity(portfolio)
    cash = _to_float(portfolio.get("cash"), 0.0)
    pos = positions.get(code) or {}
    current_qty = _to_int(pos.get("quantity"), 0)
    risk_reducing = direction == "sell" and qty > 0 and current_qty > 0 and qty <= current_qty
    errors = []
    modified = dict(intent)

    if risk["kill_switch"] and not risk_reducing:
        errors.append("kill_switch_active")
    if not code:
        errors.append("missing_code")
    if direction not in {"buy", "sell"}:
        errors.append("invalid_direction")
    if qty <= 0:
        errors.append("invalid_quantity")
    if direction == "buy" and qty % 100 != 0:
        errors.append("not_board_lot")
    if price <= 0 or equity <= 0:
        errors.append("invalid_price_or_equity")
    if direction == "buy" and market.get("is_st") and not risk["allow_buy_st"]:
        errors.append("st_buy_blocked")
    if market.get("suspended"):
        errors.append("suspended")
    if direction == "buy" and market.get("limit_state") == "up" and not risk["allow_buy_limit_up"]:
        errors.append("limit_up_blocked")
    if direction == "sell" and market.get("limit_state") == "down" and not risk["allow_sell_limit_down"]:
        errors.append("limit_down_blocked")

    if not risk_reducing and risk["capital_cap"] > 0 and equity > risk["capital_cap"] + 1e-9:
        errors.append("capital_cap_exceeded")
    daily_pnl = _to_float(portfolio.get("daily_pnl"), 0.0)
    if not risk_reducing and risk["max_daily_loss_pct"] > 0 and equity > 0:
        if daily_pnl / equity * 100 < -risk["max_daily_loss_pct"] - 1e-9:
            errors.append("daily_loss_fuse")
    drawdown_pct = _to_float(portfolio.get("drawdown_pct"), 0.0)
    if not risk_reducing and risk["max_drawdown_pct"] > 0:
        if drawdown_pct < -risk["max_drawdown_pct"] - 1e-9:
            errors.append("max_drawdown_fuse")

    attempted_orders = _to_int(intent.get("attempted_orders"), 0)
    if not risk_reducing and risk["max_orders_per_run"] and attempted_orders >= risk["max_orders_per_run"]:
        errors.append("max_orders_per_run")

    current_mv = current_qty * _to_float(pos.get("current_price", pos.get("avg_price")), price)
    delta_mv = qty * price * (1 if direction == "buy" else -1)
    projected_mv = max(0.0, current_mv + delta_mv)
    if direction == "buy" and projected_mv / equity > risk["max_position_pct"] + 1e-9:
        errors.append("max_position_pct")

    active_codes = {c for c, p in positions.items() if _to_int((p or {}).get("quantity"), 0) > 0}
    projected_codes = set(active_codes)
    if direction == "buy":
        projected_codes.add(code)
    elif projected_mv <= 0:
        projected_codes.discard(code)
    if len(projected_codes) > risk["max_position_count"]:
        errors.append("max_position_count")

    total_mv = 0.0
    for c, p in positions.items():
        total_mv += _to_int(p.get("quantity"), 0) * _to_float(p.get("current_price", p.get("avg_price")), 0.0)
    projected_gross = max(0.0, total_mv + delta_mv)
    if direction == "buy" and projected_gross / equity * 100 > risk["max_gross_exposure_pct"] + 1e-9:
        errors.append("max_gross_exposure_pct")

    min_cash_pct = risk["min_cash_buffer_pct"]
    if direction == "buy" and (cash - qty * price) / equity * 100 < min_cash_pct - 1e-9:
        errors.append("min_cash_buffer_pct")
    if direction == "sell":
        available_qty = _to_int(pos.get("available_qty", current_qty), current_qty)
        if available_qty < qty:
            errors.append("t1_available_qty")

    daily_turnover = _to_float(intent.get("current_turnover_notional"), 0.0) + qty * price
    if (
        not risk_reducing
        and risk["max_daily_turnover_pct"] > 0
        and daily_turnover / equity * 100 > risk["max_daily_turnover_pct"] + 1e-9
    ):
        errors.append("max_daily_turnover_pct")

    decision = intent.get("decision") or {}
    if direction == "buy":
        if decision.get("trade_policy") in {"reduce_only", "no_new_position"}:
            errors.append("decision_policy_blocks_buy")
        objective = decision.get("objective") or {}
        objective_enforced = bool(objective.get("enforce_objective_risk_gate"))
        if objective_enforced and objective.get("risk_mode") in {"no_new_position", "de_risk"}:
            errors.append("objective_risk_mode_blocks_buy")

    if errors:
        return {
            "approved": False,
            "decision": "rejected",
            "reason": errors[0],
            "reasons": errors,
            "intent": intent,
            "risk_reducing": risk_reducing,
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    return {
        "approved": True,
        "decision": "modified" if modified != intent else "approved",
        "reason": "ok",
        "reasons": [],
        "intent": modified,
        "risk_reducing": risk_reducing,
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

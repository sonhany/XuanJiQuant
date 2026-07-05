"""Paper trading pre-trade risk checks."""
from __future__ import annotations

from quant.backtest.engine import is_limit_bar
from quant.data.audit import write_risk_event
from quant.risk.gateway import check_order


def build_portfolio_snapshot(pos_map: dict, status_data: dict, equity: float) -> dict:
    return {
        "cash": float(status_data.get("cash", 0) or 0),
        "market_value": float(status_data.get("market_value", 0) or 0),
        "total_equity": float(equity or status_data.get("total_equity", 0) or 0),
        "daily_pnl": float(status_data.get("daily_pnl", status_data.get("total_pnl", 0)) or 0),
        "positions": pos_map or {},
        "position_count": len([p for p in (pos_map or {}).values() if int(p.get("quantity", 0) or 0) > 0]),
    }


def _latest_bar(cache, code: str) -> dict:
    raw = cache.get(f"kline:{str(code).split('.')[0]}:d") or []
    if isinstance(raw, list) and raw:
        return raw[-1] or {}
    return {}


def build_market_snapshot(cache, code: str, direction: str, price: float) -> dict:
    code = str(code).split(".")[0].strip()
    name = str(cache.get(f"stock:name:{code}") or "")
    bar = _latest_bar(cache, code)
    market = {"code": code, "is_st": name.upper().startswith("ST") or "*ST" in name.upper()}
    try:
        prev_raw = cache.get(f"kline:{code}:d") or []
        prev = prev_raw[-2] if isinstance(prev_raw, list) and len(prev_raw) >= 2 else {}
        prev_close = float(prev.get("close") or prev.get("c") or 0)
        high = float(bar.get("high") or bar.get("h") or price or 0)
        low = float(bar.get("low") or bar.get("l") or price or 0)
        close = float(bar.get("close") or bar.get("c") or price or 0)
        amount = float(bar.get("amount") or bar.get("a") or 0)
        volume = float(bar.get("volume") or bar.get("v") or 0)
        if prev_close > 0:
            flag = is_limit_bar(code, prev_close, high, low, close, cache)
            if flag == 1:
                market["limit_state"] = "up"
            elif flag == -1:
                market["limit_state"] = "down"
        if close <= 0 or (amount == 0 and volume == 0 and bar):
            market["suspended"] = True
    except Exception:
        pass
    return market


def check_paper_order(cache, *, code: str, direction: str, qty: int, price: float,
                      equity: float, pos_map: dict, status_data: dict, cfg: dict,
                      summary: dict) -> tuple[bool, dict]:
    """Call the independent risk gateway and update the run summary."""
    attempted = len(summary.get("orders", [])) + len(summary.get("risk_rejections", []))
    turnover_notional = sum(
        float(o.get("qty", 0) or o.get("quantity", 0) or 0) * float(o.get("price", price) or price)
        for o in summary.get("orders", [])
        if o.get("success")
    )
    intent = {
        "code": code,
        "direction": direction,
        "quantity": int(qty),
        "price": float(price),
        "source": summary.get("trigger_source", "paper"),
        "attempted_orders": attempted,
        "current_turnover_notional": turnover_notional,
        "decision": summary.get("decision") or {},
        "run_id": summary.get("run_id"),
        "decision_id": (summary.get("decision") or {}).get("decision_id"),
    }
    portfolio = build_portfolio_snapshot(pos_map, status_data, equity)
    market = build_market_snapshot(cache, code, direction, price)
    result = check_order(intent, portfolio, market, cfg)
    result["run_id"] = summary.get("run_id")
    result["decision_id"] = intent.get("decision_id")
    result["market"] = market
    summary.setdefault("risk_checks", []).append(result)
    write_risk_event(cache, result, source="paper_pretrade")
    if result.get("approved"):
        return True, result
    item = {
        "code": code,
        "direction": direction,
        "qty": int(qty),
        "reason": result.get("reason"),
        "detail": ",".join(result.get("reasons") or []),
        "time": result.get("checked_at"),
        "run_id": summary.get("run_id"),
        "decision_id": intent.get("decision_id"),
    }
    summary.setdefault("risk_rejections", []).append(item)
    summary.setdefault("skipped_orders", []).append(item)
    return False, result

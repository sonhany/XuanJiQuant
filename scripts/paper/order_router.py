"""Route approved paper orders to the simulated execution runner."""
from __future__ import annotations

from quant.data.audit import write_order_event


def place_paper_order(cache, *, code: str, direction: str, qty: int, summary: dict,
                      action_place_order, decision_done, mark_decision, trade_date: str,
                      now_fn) -> bool:
    """Submit a paper order with idempotency and structured audit."""
    if qty <= 0:
        return False
    if decision_done(trade_date, code, direction):
        decision = summary.get("decision") or {}
        item = {"code": code, "direction": direction, "qty": int(qty),
                "reason": "idempotent_skip", "time": now_fn(),
                "run_id": summary.get("run_id"), "decision_id": decision.get("decision_id")}
        summary.setdefault("skipped_orders", []).append(item)
        summary.setdefault("orders", []).append({**item, "success": False, "error": "同日同股票同方向已处理，跳过重复下单"})
        write_order_event(cache, {**item, "status": "skipped", "success": False}, source="paper_router")
        return False
    try:
        decision = summary.get("decision") or {}
        result = action_place_order({
            "code": code,
            "direction": direction,
            "quantity": int(qty),
            "order_type": "market",
            "source": "paper",
            "run_id": summary.get("run_id"),
            "decision_id": decision.get("decision_id"),
        })
        ok = bool(result.get("success"))
        order_data = (result.get("data") or {}).get("order") if isinstance(result.get("data"), dict) else None
        rec = {
            "code": code,
            "direction": direction,
            "qty": int(qty),
            "success": ok,
            "error": result.get("error") if not ok else None,
            "reason": result.get("reason") if not ok else None,
            "order_id": order_data.get("id") if isinstance(order_data, dict) else None,
            "run_id": summary.get("run_id"),
            "decision_id": decision.get("decision_id"),
            "price_source": order_data.get("price_source") if isinstance(order_data, dict) else None,
            "time": now_fn(),
        }
        summary.setdefault("orders", []).append(rec)
        mark_decision(trade_date, code, direction, rec)
        write_order_event(cache, rec, source="paper_router")
        return ok
    except Exception as exc:
        rec = {"code": code, "direction": direction, "qty": int(qty), "success": False,
               "error": str(exc), "time": now_fn()}
        summary.setdefault("errors", []).append(f"{code} {direction} {qty} 下单异常: {exc}")
        summary.setdefault("orders", []).append(rec)
        write_order_event(cache, rec, source="paper_router")
        return False

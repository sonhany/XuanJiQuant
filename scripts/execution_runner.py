"""历史模拟交易账本只读投影。

自动执行、下单、撤单、止损触发和执行会话均已删除。该进程只读取
``execution:state`` 与历史权益快照，供驾驶舱、风险页和审计页展示。
"""
from __future__ import annotations

import copy
import json
import math
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant.data.cache import create_cache


cache = create_cache()
STATE_KEY = "execution:state"


def _sort_timestamp(value) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        try:
            return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            return 0.0


def _daily_equity_history(rows, limit=60, excluded_intervals=None):
    exclusions = []
    for interval in excluded_intervals or []:
        if not isinstance(interval, dict):
            continue
        start = _sort_timestamp(interval.get("start"))
        end = _sort_timestamp(interval.get("end"))
        if start > 0 and end > start:
            exclusions.append((start, end))

    latest_by_day = {}
    for raw in rows or []:
        if isinstance(raw, dict):
            row = raw
        elif hasattr(raw, "keys"):
            row = {key: raw[key] for key in raw.keys()}
        elif isinstance(raw, (list, tuple)) and len(raw) >= 5:
            row = dict(zip(("id", "total_equity", "cash", "position_count", "created_at"), raw[:5]))
        else:
            continue
        created_at = str(row.get("created_at") or "").strip()
        created_ts = _sort_timestamp(created_at)
        if created_ts > 0 and any(start <= created_ts < end for start, end in exclusions):
            continue
        try:
            equity = float(row.get("total_equity"))
        except (TypeError, ValueError):
            continue
        day = created_at[:10]
        if len(day) != 10 or equity <= 0 or not math.isfinite(equity):
            continue
        sort_key = (created_at, int(row.get("id") or 0))
        if latest_by_day.get(day, {}).get("_sort_key", ("", 0)) > sort_key:
            continue
        latest_by_day[day] = {
            "date": day,
            "equity": round(equity, 2),
            "cash": round(float(row.get("cash") or 0), 2),
            "position_count": int(row.get("position_count") or 0),
            "_sort_key": sort_key,
        }

    peak = 0.0
    history = []
    for day in sorted(latest_by_day):
        point = latest_by_day[day]
        peak = max(peak, point["equity"])
        drawdown = (point["equity"] - peak) / peak * 100 if peak > 0 else 0.0
        history.append({
            "date": point["date"], "equity": point["equity"], "cash": point["cash"],
            "position_count": point["position_count"], "drawdown_pct": round(drawdown, 4),
        })
    return history[-max(2, min(365, int(limit or 60))):]


def _load_state() -> dict:
    raw = cache.get(STATE_KEY) or {}
    positions = raw.get("positions") if isinstance(raw.get("positions"), dict) else {}
    orders = raw.get("orders") if isinstance(raw.get("orders"), list) else []
    trades = raw.get("trades") if isinstance(raw.get("trades"), list) else []
    return {
        **raw,
        "initial_capital": float(raw.get("initial_capital") or 1_000_000),
        "cash": float(raw.get("cash") or 0),
        "positions": positions,
        "orders": orders,
        "trades": trades,
    }


def current_priced_state(state: dict, *, cached_only: bool = True):
    """Return a detached snapshot enriched only from already-synced quotes."""
    priced = copy.deepcopy(state or {})
    current = 0
    for code, position in (priced.get("positions") or {}).items():
        normalized = str(code).split(".")[0].zfill(6)
        prefix = "sh" if normalized.startswith(("5", "6", "9")) else "sz"
        quote = cache.get(f"stock:realtime:{prefix}{normalized}") or {}
        try:
            price = float(quote.get("price") or 0)
        except (TypeError, ValueError):
            price = 0
        if price > 0 and isinstance(position, dict):
            position["current_price"] = price
            current += 1
    return priced, {"source": "sync_cache", "cached_only": True, "current_count": current}


def _position_rows(state: dict) -> list[dict]:
    rows = []
    for code, raw in state["positions"].items():
        position = raw if isinstance(raw, dict) else {}
        quantity = int(position.get("quantity") or 0)
        avg_price = float(position.get("avg_price") or 0)
        current_price = float(position.get("current_price") or avg_price)
        rows.append({
            "code": position.get("code") or code,
            "quantity": quantity,
            "available_qty": int(position.get("available_qty", quantity) or 0),
            "today_buy_qty": int(position.get("today_buy_qty") or 0),
            "avg_price": round(avg_price, 2),
            "current_price": round(current_price, 2),
            "market_value": round(quantity * current_price, 2),
            "cost": round(quantity * avg_price, 2),
            "pnl": round(quantity * (current_price - avg_price), 2),
            "pnl_pct": round((current_price / avg_price - 1) * 100, 2) if avg_price else 0,
            "entry_date": position.get("entry_date") or "--",
        })
    return rows


def _account(state: dict, positions: list[dict]) -> dict:
    market_value = sum(float(item["market_value"]) for item in positions)
    total_equity = state["cash"] + market_value
    initial = state["initial_capital"]
    pnl = total_equity - initial
    return {
        "initial_capital": round(initial, 2), "cash": round(state["cash"], 2),
        "market_value": round(market_value, 2), "total_equity": round(total_equity, 2),
        "total_pnl": round(pnl, 2), "total_pnl_pct": round(pnl / initial * 100, 2) if initial else 0,
        "daily_pnl": state.get("daily_pnl"), "drawdown_pct": state.get("drawdown_pct"),
        "price_updated_at": state.get("price_updated_at"), "prices_refreshed": False,
        "price_source": "historical_ledger", "position_count": len(positions),
        "order_count": len(state["orders"]), "trade_count": len(state["trades"]),
    }


def _equity_history() -> list[dict]:
    conn = getattr(cache, "_conn", None)
    rows = []
    if conn is not None:
        try:
            rows = conn.execute(
                "SELECT id,total_equity,cash,position_count,created_at FROM positions_snapshots "
                "WHERE total_equity IS NOT NULL ORDER BY created_at ASC,id ASC"
            ).fetchall()
        except Exception:
            rows = []
    return _daily_equity_history(rows, excluded_intervals=cache.get("execution:recovery:invalid_snapshot_intervals") or [])


def action_status(_request=None):
    state = _load_state()
    return {"success": True, "data": _account(state, _position_rows(state))}


def action_positions(_request=None):
    return {"success": True, "data": _position_rows(_load_state())}


def action_orders(request=None):
    request = request or {}
    orders = list(_load_state()["orders"])
    if request.get("status"):
        orders = [item for item in orders if item.get("status") == request["status"]]
    if request.get("code"):
        orders = [item for item in orders if item.get("code") == request["code"]]
    return {"success": True, "data": sorted(orders, key=lambda item: _sort_timestamp(item.get("created_at") or item.get("time")), reverse=True)[:int(request.get("limit") or 200)]}


def action_trades(request=None):
    request = request or {}
    trades = list(_load_state()["trades"])
    if request.get("code"):
        trades = [item for item in trades if item.get("code") == request["code"]]
    return {"success": True, "data": sorted(trades, key=lambda item: _sort_timestamp(item.get("timestamp") or item.get("created_at")), reverse=True)[:int(request.get("limit") or 200)]}


def action_all(_request=None):
    state = _load_state()
    positions = _position_rows(state)
    return {"success": True, "data": {
        "status": _account(state, positions), "account": _account(state, positions),
        "positions": positions,
        "orders": action_orders({"limit": 50})["data"],
        "trades": action_trades({"limit": 50})["data"],
        "equity_history": _equity_history(),
        "automatic_execution": {"enabled": False, "reason": "automatic_execution_disabled"},
    }}


ACTIONS = {"all": action_all, "status": action_status, "positions": action_positions, "orders": action_orders, "trades": action_trades}


if __name__ == "__main__":
    for line in sys.stdin:
        try:
            request = json.loads(line)
            request_id = request.get("__id")
            handler = ACTIONS.get(request.get("action", "status"))
            result = handler(request) if handler else {"success": False, "error": "automatic_execution_disabled", "reason": "automatic_execution_disabled"}
            if request_id:
                result["__id"] = request_id
            print(json.dumps(result, ensure_ascii=False), flush=True)
        except Exception as exc:
            print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False), flush=True)

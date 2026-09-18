"""Persistent read/control runner for the F5 simulation-only ledger."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant.paper_execution.reporting import status_projection
from quant.data.cache import create_cache
from quant.paper_execution.runtime import build_runtime_service, load_active_account_projection


service = build_runtime_service()
ledger = service.ledger
market_cache = create_cache()
HOT_SNAPSHOT_KEY = "market:hot:snapshot:latest"


def _ok(data):
    execution_mode = data.get("execution_mode") if isinstance(data, dict) else None
    return {
        "success": True,
        "data": data,
        "execution_mode": execution_mode or "paper_daily",
        "live_execution_authority": False,
    }


def _current_status():
    try:
        current = service.intraday_readiness(datetime.now())
    except Exception as exc:
        current = {
            "success": False,
            "paper_execution_ready": False,
            "paper_execution_authority": False,
            "live_execution_authority": False,
            "execution_lane": "blocked",
            "strategy_quality_status": "invalid",
            "reason_code": str(exc).split(":", 1)[0] or "readiness_unavailable",
        }
    return status_projection(ledger, current_readiness=current)


def handle(request):
    action = str(request.get("action") or "status")
    limit = min(1000, max(1, int(request.get("limit") or 200)))
    if action == "status":
        return _ok(_current_status())
    if action in {"account", "all"}:
        return _ok(load_active_account_projection(limit=limit))
    if action == "runs":
        return _ok(ledger.list_runs(limit=limit))
    if action == "orders":
        return _ok(ledger.list_orders(request.get("run_id"), limit))
    if action == "fills":
        return _ok(ledger.list_fills(request.get("run_id"), limit))
    if action == "trades":
        return _ok(ledger.list_fills(request.get("run_id"), limit))
    if action == "positions":
        return _ok(ledger.list_positions())
    if action == "equity":
        return _ok(ledger.list_equity(limit))
    if action == "reconciliations":
        return _ok(ledger.list_reconciliations(request.get("run_id"), limit))
    if action == "audit":
        return _ok(ledger.list_audit(limit))
    if action == "set_enabled":
        if set(request) - {"action", "enabled", "__id", "token"}:
            return {"success": False, "reason": "invalid_control_parameters"}
        ledger.set_setting("enabled", bool(request.get("enabled")))
        return _ok(_current_status())
    if action == "set_kill_switch":
        if set(request) - {"action", "enabled", "__id", "token"}:
            return {"success": False, "reason": "invalid_control_parameters"}
        ledger.set_setting("kill_switch", bool(request.get("enabled")))
        return _ok(_current_status())
    if action == "run_due":
        if set(request) - {"action", "__id", "token"}:
            return {"success": False, "reason": "arbitrary_execution_parameters_forbidden"}
        return _ok(service.run_due(datetime.now()))
    if action == "run_intraday":
        if set(request) - {"action", "__id", "token"}:
            return {"success": False, "reason": "arbitrary_execution_parameters_forbidden"}
        return _ok(service.run_intraday(datetime.now()))
    if action == "mark_to_market":
        if set(request) - {"action", "__id", "token"}:
            return {"success": False, "reason": "mark_to_market_parameters_forbidden"}
        snapshot = market_cache.get(HOT_SNAPSHOT_KEY)
        if not isinstance(snapshot, dict):
            return {"success": False, "reason": "market_snapshot_missing"}
        result = service.mark_to_market(snapshot, now=datetime.now())
        return _ok(result) if result.get("success") is True else {
            "success": False,
            "reason": result.get("reason_code") or "mark_to_market_failed",
            "data": result,
            "live_execution_authority": False,
        }
    return {"success": False, "reason": "arbitrary_order_action_forbidden", "live_execution_authority": False}


if __name__ == "__main__":
    for line in sys.stdin:
        try:
            request = json.loads(line)
            result = handle(request)
            if request.get("__id"):
                result["__id"] = request["__id"]
            print(json.dumps(result, ensure_ascii=False, default=str), flush=True)
        except Exception as exc:
            print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False), flush=True)

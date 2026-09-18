"""Lightweight persistent runner for the data-management control plane."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant.data.cache import create_cache
from quant.data.audit import write_audit_event
from quant.data.control_plane import get_control_plane_status, run_control_plane_health
from quant.data.sync_catalog import build_sync_catalog


cache = create_cache()


def handle(request: dict) -> dict:
    action = str(request.get("action") or "sync_status")
    if action == "sync_status":
        return {"success": True, "data": get_control_plane_status(cache)}
    if action == "sync_health":
        return run_control_plane_health(cache, force=bool(request.get("force")))
    if action == "sync_catalog":
        return {"success": True, "data": build_sync_catalog(cache)}
    if action == "write_update_status":
        state = request.get("state")
        if not isinstance(state, dict):
            return {"success": False, "error": "state must be an object"}
        cache.set("data:update:status", state)
        event_type = str(request.get("event_type") or "")[:80]
        if event_type:
            write_audit_event(cache, event_type, state, source="update_manager")
        return {"success": True}
    return {"success": False, "error": f"unknown action: {action}"}


if __name__ == "__main__":
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        request_id = None
        try:
            request = json.loads(line)
            request_id = request.get("__id")
            response = handle(request)
        except Exception as exc:
            response = {"success": False, "error": str(exc)[:500]}
        if request_id and isinstance(response, dict):
            response["__id"] = request_id
        print(json.dumps(response, ensure_ascii=False, default=str))
        sys.stdout.flush()

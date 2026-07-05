"""Shadow-only external signals.

News, macro, policy, and sentiment inputs are useful context, but they should
not directly trigger orders. This module keeps them in an explicit shadow lane.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def build_shadow_signals(cache, *, source: str = "data_agent") -> dict[str, Any]:
    global_ctx = cache.get("global:context:latest") or {}
    sector_flow = cache.get("market:sector_flow:latest") or []
    northbound = cache.get("market:northbound:latest") or {}
    signals = []
    for item in global_ctx.get("risk_signals") or []:
        signals.append({"type": "macro_market", "signal": item, "severity": "info"})
    if northbound:
        signals.append({
            "type": "northbound_flow",
            "signal": northbound.get("trend") or "unknown",
            "value": northbound.get("northFlow"),
            "severity": "info",
        })
    for row in (sector_flow or [])[:5]:
        if isinstance(row, dict):
            signals.append({
                "type": "sector_flow",
                "signal": row.get("name") or row.get("sector") or row.get("板块"),
                "value": row.get("netFlow") or row.get("amount") or row.get("主力净流入"),
                "severity": "info",
            })
    result = {
        "generated_at": _now(),
        "source": source,
        "mode": "shadow_only",
        "can_change_trade_policy": False,
        "can_trigger_order": False,
        "signals": signals,
    }
    try:
        cache.set("ai:shadow_signals:latest", result)
    except Exception:
        pass
    return result

"""Research-only external signals with no execution authority."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any


_REGIMES = {"extreme_fear", "fear", "neutral", "greed", "extreme_greed"}


def _bounded(value, default: float, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    number = float(value)
    return max(minimum, min(maximum, number)) if math.isfinite(number) else default


def _regime(score: float) -> str:
    if score <= 20: return "extreme_fear"
    if score <= 40: return "fear"
    if score < 60: return "neutral"
    if score < 80: return "greed"
    return "extreme_greed"


def _sentiment(value) -> dict[str, Any] | None:
    if not isinstance(value, dict) or not value:
        return None
    score = _bounded(value.get("sentiment_score"), 50.0, 0.0, 100.0)
    confidence = _bounded(value.get("confidence"), 0.0, 0.0, 1.0)
    raw_regime = value.get("sentiment_regime")
    sources = []
    for item in value.get("sources") if isinstance(value.get("sources"), list) else []:
        if isinstance(item, dict) and isinstance(item.get("source"), str) and isinstance(item.get("status"), str) and item.get("status") in {"live", "stale"}:
            sources.append(item["source"].strip()[:64])
    return {
        "type": "market_sentiment", "signal": raw_regime if isinstance(raw_regime, str) and raw_regime in _REGIMES else _regime(score),
        "value": score, "confidence": confidence, "sources": sources, "severity": "info",
    }


def build_shadow_signals(cache, *, source: str = "research_scheduler") -> dict[str, Any]:
    global_context = cache.get("global:context:latest")
    global_context = global_context if isinstance(global_context, dict) else {}
    northbound = cache.get("market:northbound:latest")
    northbound = northbound if isinstance(northbound, dict) else {}
    sector_flow = cache.get("market:sector_flow:latest")
    sector_flow = sector_flow if isinstance(sector_flow, list) else []
    signals = []
    for item in global_context.get("risk_signals") if isinstance(global_context.get("risk_signals"), list) else []:
        signals.append({"type": "macro_market", "signal": item, "severity": "info"})
    if northbound:
        signals.append({"type": "northbound_flow", "signal": northbound.get("trend") or "unknown", "value": northbound.get("northFlow"), "severity": "info"})
    for row in sector_flow[:5]:
        if isinstance(row, dict):
            signals.append({"type": "sector_flow", "signal": row.get("name") or row.get("sector") or row.get("板块"), "value": row.get("netFlow") or row.get("amount") or row.get("主力净流入"), "severity": "info"})
    sentiment = _sentiment(global_context.get("sentiment"))
    if sentiment:
        signals.append(sentiment)
    result = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "source": source,
        "mode": "shadow_only", "can_change_trade_policy": False, "can_trigger_order": False,
        "signals": signals,
    }
    return result

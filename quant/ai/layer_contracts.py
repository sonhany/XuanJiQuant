"""L0-L7 interface contracts for the autonomous quant pipeline.

These contracts document the minimum payload each layer should publish. They
are intentionally lightweight so existing agents can adopt them incrementally.
"""
from __future__ import annotations

from typing import Any


LAYER_CONTRACTS: dict[str, set[str]] = {
    "L0_infra": {"generated_at", "services", "storage", "runtime"},
    "L1_data": {"generated_at", "integrity", "data_stale", "trade_allowed"},
    "L2_factor": {"generated_at", "candidates", "approved", "promotion"},
    "L3_strategy": {"generated_at", "candidates", "approved", "promotion"},
    "L4_portfolio": {"generated_at", "target_weights", "rebalance_plan", "risk_budget"},
    "L5_execution": {"generated_at", "orders", "rejections", "review_lessons"},
    "L6_risk": {"generated_at", "pre_trade", "self_verification"},
    "L7_learning": {"generated_at", "lessons", "stats"},
}


def validate_layer_payload(layer: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    required = LAYER_CONTRACTS.get(layer)
    if required is None:
        raise ValueError(f"unknown layer contract: {layer}")
    payload = payload or {}
    missing = sorted(required - set(payload.keys()))
    return {
        "layer": layer,
        "valid": not missing,
        "missing": missing,
        "required": sorted(required),
    }


def contract_summary() -> dict[str, list[str]]:
    return {k: sorted(v) for k, v in LAYER_CONTRACTS.items()}

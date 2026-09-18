from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy

_AUTHORITY_KEYS = {"can_trigger_order", "can_change_trade_policy"}


def _sanitize_value(value: object) -> object:
    if isinstance(value, Mapping):
        out = {}
        for key, nested in value.items():
            out[key] = False if key in _AUTHORITY_KEYS else _sanitize_value(nested)
        return out
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    return deepcopy(value)


def sanitize_shadow_output(value: dict | None) -> dict:
    out = _sanitize_value(value) if isinstance(value, Mapping) else {}
    out["mode"] = "shadow_only"
    out["can_change_trade_policy"] = False
    out["can_trigger_order"] = False
    return out


def require_schema(payload: dict, expected: str) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    if payload.get("schema_version") != expected:
        raise ValueError(f"invalid schema_version: {payload.get('schema_version')}")
    return deepcopy(payload)

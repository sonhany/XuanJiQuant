from __future__ import annotations

from math import isfinite
from types import MappingProxyType

ACTIVATION_LEVELS = (
    "observe",
    "route_shadow",
    "size_shadow",
    "paper_guarded",
)

def _default_adaptive_config() -> dict:
    return {
        "enabled": True,
        "activation_level": "observe",
        "regime_states": 3,
        "kelly_fraction": 0.25,
        "allow_leverage": False,
        "allow_short": False,
        "min_regime_confidence": 0.65,
        "regime_confirmation_windows": 2,
        "drift_failure_windows": 3,
        "max_strategy_weight": 0.50,
        "max_adaptive_gross_exposure_pct": 80.0,
        "fallback_mode": "existing_policy",
        "human_approval_required": True,
    }


DEFAULT_ADAPTIVE_CONFIG = MappingProxyType(_default_adaptive_config())


def _finite_float(value: object, default: float) -> float:
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if isfinite(number) else default


def _bounded_float(value: object, default: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, _finite_float(value, default)))


def _positive_int(value: object, default: int) -> int:
    number = _finite_float(value, float(default))
    if not number.is_integer():
        return default
    return max(1, int(number))


def normalize_adaptive_config(value: dict | None) -> dict:
    out = dict(DEFAULT_ADAPTIVE_CONFIG)
    source = value if isinstance(value, dict) else {}
    for key in out:
        if key in source:
            out[key] = source[key]
    out["enabled"] = out["enabled"] if isinstance(out["enabled"], bool) else True
    if out["activation_level"] not in ACTIVATION_LEVELS:
        out["activation_level"] = "observe"
    out["regime_states"] = 3
    out["kelly_fraction"] = _bounded_float(out["kelly_fraction"], 0.25, 0.0, 0.25)
    out["min_regime_confidence"] = _bounded_float(
        out["min_regime_confidence"], 0.65, 0.0, 1.0
    )
    out["regime_confirmation_windows"] = _positive_int(
        out["regime_confirmation_windows"], 2
    )
    out["drift_failure_windows"] = _positive_int(out["drift_failure_windows"], 3)
    out["max_strategy_weight"] = _bounded_float(
        out["max_strategy_weight"], 0.50, 0.0, 1.0
    )
    out["max_adaptive_gross_exposure_pct"] = _bounded_float(
        out["max_adaptive_gross_exposure_pct"], 80.0, 0.0, 100.0
    )
    out["allow_leverage"] = False
    out["allow_short"] = False
    out["human_approval_required"] = True
    return out


def activation_permissions(level: str) -> dict:
    normalized = level if level in ACTIVATION_LEVELS else "observe"
    return {
        "publish_health": True,
        "publish_regime": True,
        "publish_route": normalized in {"route_shadow", "size_shadow", "paper_guarded"},
        "publish_sizing": normalized in {"size_shadow", "paper_guarded"},
        "apply_weight_cuts": normalized == "paper_guarded",
        "can_trigger_order": False,
        "can_change_trade_policy": False,
    }

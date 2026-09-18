from copy import deepcopy

import pytest

from quant.adaptive.activation import (
    ACTIVATION_LEVELS,
    DEFAULT_ADAPTIVE_CONFIG,
    activation_permissions,
    normalize_adaptive_config,
)
from quant.adaptive.contracts import require_schema, sanitize_shadow_output


def test_adaptive_defaults_are_observe_only():
    cfg = normalize_adaptive_config({})
    assert cfg == DEFAULT_ADAPTIVE_CONFIG
    assert cfg["activation_level"] == "observe"
    assert cfg["kelly_fraction"] == 0.25
    assert cfg["allow_leverage"] is False
    assert cfg["allow_short"] is False


def test_shadow_output_cannot_gain_execution_authority():
    out = sanitize_shadow_output({
        "mode": "paper_guarded",
        "can_change_trade_policy": True,
        "can_trigger_order": True,
    })
    assert out["mode"] == "shadow_only"
    assert out["can_change_trade_policy"] is False
    assert out["can_trigger_order"] is False


def test_only_paper_guarded_can_apply_weight_cuts():
    assert activation_permissions("observe")["apply_weight_cuts"] is False
    assert activation_permissions("route_shadow")["apply_weight_cuts"] is False
    assert activation_permissions("size_shadow")["apply_weight_cuts"] is False
    assert activation_permissions("paper_guarded")["apply_weight_cuts"] is True


def test_public_defaults_cannot_change_future_normalization():
    original = DEFAULT_ADAPTIVE_CONFIG["activation_level"]
    try:
        with pytest.raises(TypeError):
            DEFAULT_ADAPTIVE_CONFIG["activation_level"] = "paper_guarded"
    finally:
        if isinstance(DEFAULT_ADAPTIVE_CONFIG, dict):
            DEFAULT_ADAPTIVE_CONFIG["activation_level"] = original

    cfg = normalize_adaptive_config({})
    assert cfg == DEFAULT_ADAPTIVE_CONFIG
    assert isinstance(cfg, dict)
    assert cfg is not DEFAULT_ADAPTIVE_CONFIG


@pytest.mark.parametrize("kelly", ["invalid", float("nan"), float("inf"), -float("inf")])
def test_invalid_or_non_finite_kelly_uses_safe_default(kelly):
    assert normalize_adaptive_config({"kelly_fraction": kelly})["kelly_fraction"] == 0.25


def test_malformed_config_fails_closed_and_numeric_limits_are_clamped():
    cfg = normalize_adaptive_config({
        "enabled": "yes",
        "activation_level": "live",
        "regime_states": 99,
        "allow_leverage": True,
        "allow_short": True,
        "human_approval_required": False,
        "regime_confirmation_windows": 0,
        "drift_failure_windows": "invalid",
        "max_strategy_weight": 2.0,
        "max_adaptive_gross_exposure_pct": -10.0,
        "min_regime_confidence": float("nan"),
    })

    assert cfg["enabled"] is True
    assert cfg["activation_level"] == "observe"
    assert cfg["regime_states"] == 3
    assert cfg["allow_leverage"] is False
    assert cfg["allow_short"] is False
    assert cfg["human_approval_required"] is True
    assert cfg["regime_confirmation_windows"] == 1
    assert cfg["drift_failure_windows"] == 3
    assert cfg["max_strategy_weight"] == 1.0
    assert cfg["max_adaptive_gross_exposure_pct"] == 0.0
    assert cfg["min_regime_confidence"] == 0.65


def test_malformed_bounded_values_use_defaults():
    cfg = normalize_adaptive_config({
        "regime_confirmation_windows": None,
        "drift_failure_windows": [],
        "max_strategy_weight": "invalid",
        "max_adaptive_gross_exposure_pct": None,
        "min_regime_confidence": {},
    })

    assert cfg["regime_confirmation_windows"] == 2
    assert cfg["drift_failure_windows"] == 3
    assert cfg["max_strategy_weight"] == 0.50
    assert cfg["max_adaptive_gross_exposure_pct"] == 80.0
    assert cfg["min_regime_confidence"] == 0.65


def test_shadow_output_preserves_diagnostics_and_recursively_removes_authority():
    source = {
        "mode": "paper_guarded",
        "health": {"status": "ok", "can_trigger_order": True, "orders": ["buy"]},
        "regime": {"name": "trend", "confidence": 0.8},
        "routing": [{"strategy": "alpha", "trade_policy": "normal"}],
        "sizing": {
            "target_weights": {"alpha": 0.4},
            "shadow_weights": {"alpha": 0.3},
            "nested": {
                "can_change_trade_policy": True,
                "rebalance_instructions": ["execute"],
            },
        },
    }
    source_before = deepcopy(source)

    out = sanitize_shadow_output(source)

    assert out == {
        "mode": "shadow_only",
        "health": {"status": "ok", "can_trigger_order": False, "orders": ["buy"]},
        "regime": {"name": "trend", "confidence": 0.8},
        "routing": [{"strategy": "alpha", "trade_policy": "normal"}],
        "sizing": {
            "target_weights": {"alpha": 0.4},
            "shadow_weights": {"alpha": 0.3},
            "nested": {
                "can_change_trade_policy": False,
                "rebalance_instructions": ["execute"],
            },
        },
        "can_change_trade_policy": False,
        "can_trigger_order": False,
    }
    assert source == source_before


@pytest.mark.parametrize("level", [*ACTIVATION_LEVELS, "live", "", None, []])
def test_activation_permissions_never_grant_execution_authority(level):
    permissions = activation_permissions(level)
    assert permissions["can_trigger_order"] is False
    assert permissions["can_change_trade_policy"] is False


def test_require_schema_accepts_expected_version_with_defensive_copy():
    payload = {"schema_version": "adaptive.v1", "nested": {"status": "ok"}}
    validated = require_schema(payload, "adaptive.v1")

    assert validated == payload
    assert validated is not payload
    validated["nested"]["status"] = "changed"
    assert payload["nested"]["status"] == "ok"


def test_require_schema_rejects_missing_wrong_and_non_object_payloads():
    with pytest.raises(ValueError, match=r"^invalid schema_version: None$"):
        require_schema({}, "adaptive.v1")
    with pytest.raises(ValueError, match=r"^invalid schema_version: legacy$"):
        require_schema({"schema_version": "legacy"}, "adaptive.v1")
    with pytest.raises(ValueError, match=r"^payload must be an object$"):
        require_schema([], "adaptive.v1")

"""Single source of truth for risk limits used by trading gates."""
from __future__ import annotations

import json
import os
from typing import Any


DEFAULT_RISK_CONFIG: dict[str, Any] = {
    "kill_switch": False,
    "max_position_pct": 0.2,
    "max_gross_exposure_pct": 95.0,
    "max_position_count": 10,
    "max_orders_per_run": 20,
    "min_cash_buffer_pct": 2.0,
    "max_daily_turnover_pct": 35.0,
    "capital_cap": 0.0,
    "max_daily_loss_pct": 5.0,
    "max_position_loss_pct": 8.0,
    "max_drawdown_pct": 12.0,
    "allow_buy_st": False,
    "allow_buy_limit_up": False,
    "allow_sell_limit_down": False,
}

_MAX_LIMIT_KEYS = {
    "max_position_pct",
    "max_gross_exposure_pct",
    "max_position_count",
    "max_orders_per_run",
    "max_daily_turnover_pct",
    "max_daily_loss_pct",
    "max_position_loss_pct",
    "max_drawdown_pct",
}
_MIN_LIMIT_KEYS = {"min_cash_buffer_pct"}
_ALLOW_FLAG_KEYS = {"allow_buy_st", "allow_buy_limit_up", "allow_sell_limit_down"}


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _as_pct(value: Any, default: float) -> float:
    out = _to_float(value, default)
    if 0 < out <= 1:
        return out * 100
    return out


def _as_ratio(value: Any, default: float) -> float:
    out = _to_float(value, default)
    if 1 < out <= 100:
        return out / 100
    return out


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _deep_merge(base: dict, patch: dict | None) -> dict:
    out = dict(base or {})
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _manifest_metrics_from_file() -> dict:
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(root, "ai_manifest.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("metrics") or {}
    except Exception:
        return {}


def _hard_limits_from_file() -> dict:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hard_limits.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return dict(DEFAULT_RISK_CONFIG)
        return data.get("risk") if isinstance(data.get("risk"), dict) else data
    except Exception:
        return dict(DEFAULT_RISK_CONFIG)


def risk_from_manifest_metrics(metrics: dict | None) -> dict:
    metrics = metrics or {}
    out: dict[str, Any] = {}
    if "max_single_position_pct" in metrics:
        out["max_position_pct"] = _to_float(metrics.get("max_single_position_pct"), DEFAULT_RISK_CONFIG["max_position_pct"])
    if "max_daily_turnover" in metrics:
        out["max_daily_turnover_pct"] = _as_pct(metrics.get("max_daily_turnover"), DEFAULT_RISK_CONFIG["max_daily_turnover_pct"])
    if "max_drawdown_limit" in metrics:
        out["max_drawdown_pct"] = _as_pct(metrics.get("max_drawdown_limit"), DEFAULT_RISK_CONFIG["max_drawdown_pct"])
    return out


def normalize_risk_config(config: dict | None = None) -> dict:
    """Normalize legacy and current risk config fields into one schema."""
    config = config or {}
    risk = config.get("risk") if isinstance(config.get("risk"), dict) else {}
    merged = _deep_merge(DEFAULT_RISK_CONFIG, risk)

    if config.get("position_size_pct") is not None and "max_position_pct" not in risk:
        merged["max_position_pct"] = config.get("position_size_pct")
    if config.get("max_positions") is not None and "max_position_count" not in risk:
        merged["max_position_count"] = config.get("max_positions")
    if config.get("kill_switch") is not None:
        merged["kill_switch"] = bool(config.get("kill_switch"))

    merged["kill_switch"] = bool(merged.get("kill_switch", False))
    merged["max_position_pct"] = _clamp(_as_ratio(merged.get("max_position_pct"), DEFAULT_RISK_CONFIG["max_position_pct"]), 0.0, 1.0)
    merged["max_gross_exposure_pct"] = _clamp(_as_pct(merged.get("max_gross_exposure_pct"), DEFAULT_RISK_CONFIG["max_gross_exposure_pct"]), 0.0, 100.0)
    merged["max_position_count"] = max(0, _to_int(merged.get("max_position_count"), DEFAULT_RISK_CONFIG["max_position_count"]))
    merged["max_orders_per_run"] = max(0, _to_int(merged.get("max_orders_per_run"), DEFAULT_RISK_CONFIG["max_orders_per_run"]))
    merged["min_cash_buffer_pct"] = _clamp(_as_pct(merged.get("min_cash_buffer_pct"), DEFAULT_RISK_CONFIG["min_cash_buffer_pct"]), 0.0, 100.0)
    merged["max_daily_turnover_pct"] = _clamp(_as_pct(merged.get("max_daily_turnover_pct"), DEFAULT_RISK_CONFIG["max_daily_turnover_pct"]), 0.0, 100.0)
    merged["capital_cap"] = max(0.0, _to_float(merged.get("capital_cap"), DEFAULT_RISK_CONFIG["capital_cap"]))
    merged["max_daily_loss_pct"] = _clamp(_as_pct(merged.get("max_daily_loss_pct"), DEFAULT_RISK_CONFIG["max_daily_loss_pct"]), 0.0, 100.0)
    merged["max_position_loss_pct"] = _clamp(_as_pct(merged.get("max_position_loss_pct"), DEFAULT_RISK_CONFIG["max_position_loss_pct"]), 0.0, 100.0)
    merged["max_drawdown_pct"] = _clamp(_as_pct(merged.get("max_drawdown_pct"), DEFAULT_RISK_CONFIG["max_drawdown_pct"]), 0.0, 100.0)
    merged["allow_buy_st"] = bool(merged.get("allow_buy_st", False))
    merged["allow_buy_limit_up"] = bool(merged.get("allow_buy_limit_up", False))
    merged["allow_sell_limit_down"] = bool(merged.get("allow_sell_limit_down", False))
    return merged


def merge_restrictive_risk(base: dict, overlay: dict | None = None) -> dict:
    """Merge a downstream risk patch without allowing it to relax `base`."""
    out = normalize_risk_config({"risk": base or {}})
    raw = overlay if isinstance(overlay, dict) else {}
    candidate = normalize_risk_config({"risk": raw})
    for key in _MAX_LIMIT_KEYS:
        if key in raw:
            out[key] = min(out[key], candidate[key])
    for key in _MIN_LIMIT_KEYS:
        if key in raw:
            out[key] = max(out[key], candidate[key])
    if "capital_cap" in raw and candidate["capital_cap"] > 0:
        current = float(out.get("capital_cap") or 0)
        out["capital_cap"] = candidate["capital_cap"] if current <= 0 else min(current, candidate["capital_cap"])
    if "kill_switch" in raw:
        out["kill_switch"] = bool(out.get("kill_switch")) or bool(candidate["kill_switch"])
    for key in _ALLOW_FLAG_KEYS:
        if key in raw:
            out[key] = bool(out.get(key)) and bool(candidate[key])
    return out


def apply_hard_limits(config: dict, hard_limits: dict | None = None) -> dict:
    """Apply non-bypassable limits after all mutable configs are merged.

    KV configs may tighten these values, but cannot loosen them. The hard-limit
    file is the operator-controlled source for risk caps used by order gates.
    """
    out = normalize_risk_config({"risk": config or {}})
    hard = normalize_risk_config({"risk": hard_limits or _hard_limits_from_file()})
    for key in _MAX_LIMIT_KEYS:
        out[key] = min(out[key], hard[key])
    for key in _MIN_LIMIT_KEYS:
        out[key] = max(out[key], hard[key])
    if hard.get("capital_cap", 0) > 0:
        current_cap = float(out.get("capital_cap") or 0)
        out["capital_cap"] = hard["capital_cap"] if current_cap <= 0 else min(current_cap, hard["capital_cap"])
    out["kill_switch"] = bool(out.get("kill_switch")) or bool(hard.get("kill_switch"))
    for key in _ALLOW_FLAG_KEYS:
        out[key] = bool(out.get(key)) and bool(hard.get(key))
    out["_hard_limits_source"] = "quant/risk/hard_limits.json"
    return out


def load_risk_config(cache=None, explicit_config: dict | None = None) -> dict:
    """Load risk config using one precedence order.

    Precedence: defaults < manifest metrics < autonomous config < paper config
    < explicit config < hard-limit cap.

    Mutable configs can only tighten hard limits. They cannot raise max caps,
    lower mandatory cash buffers, disable a file-level kill switch, or enable
    restricted trading flags blocked by hard_limits.json.
    """
    if cache is None:
        try:
            from quant.data.cache import create_cache

            cache = create_cache()
        except Exception:
            cache = None

    manifest_metrics = _manifest_metrics_from_file()
    autonomous = {}
    paper = {}
    if cache is not None:
        try:
            manifest_metrics = _deep_merge(manifest_metrics, cache.get("ai:manifest:metrics") or {})
        except Exception:
            pass
        try:
            autonomous = cache.get("ai:autonomous:config") or {}
        except Exception:
            autonomous = {}
        try:
            paper = cache.get("paper:config") or {}
        except Exception:
            paper = {}

    merged = _deep_merge(DEFAULT_RISK_CONFIG, risk_from_manifest_metrics(manifest_metrics))
    merged = _deep_merge(merged, (autonomous.get("risk") if isinstance(autonomous, dict) else {}) or {})
    merged = merge_restrictive_risk(
        merged,
        (paper.get("risk") if isinstance(paper, dict) else {}) or {},
    )
    merged = merge_restrictive_risk(
        merged,
        (explicit_config.get("risk") if isinstance(explicit_config, dict) else {}) or {},
    )
    return apply_hard_limits(merged)


def load_paper_execution_risk_config(
    *,
    cache=None,
    policy_risk: dict | None = None,
    hard_limits: dict | None = None,
) -> dict:
    """Load F5 limits without consulting retired AI/Agent configuration.

    ``cache`` is accepted only for API compatibility and intentionally ignored.
    F5 can tighten the defaults, then the operator-owned hard-limit cap is
    applied last.  This keeps simulation policy independent of all historical
    autonomous-control keys.
    """

    del cache
    merged = merge_restrictive_risk(DEFAULT_RISK_CONFIG, policy_risk or {})
    result = apply_hard_limits(merged, hard_limits=hard_limits)
    result["_config_source"] = "f5_policy_plus_hard_limits"
    return result

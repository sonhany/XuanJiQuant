from copy import deepcopy
import math
import re

from quant.risk.config import DEFAULT_RISK_CONFIG, apply_hard_limits
from scripts.llm_registry import default_model, normalize_model, normalize_provider


_DEFAULT_PROVIDER = normalize_provider(None)


DEFAULT_CONFIG = {
    "strategy_name": "ma_cross",
    "strategy_params": {"fast": 5, "slow": 20},
    "universe": ["600519", "000858", "600036", "000333", "601318"],
    "position_size_pct": 0.2,
    "max_positions": 5,
    "trade_time": "15:05",
    "enabled": True,
    "skip_data_stale": True,
    "risk": dict(DEFAULT_RISK_CONFIG),
    "llm": {
        "enabled": True,
        "inherit_global": True,
        "provider": _DEFAULT_PROVIDER,
        "model": default_model(_DEFAULT_PROVIDER),
        "mode": "review",
        "timeout": 45,
        "max_new_positions": 3,
        "confidence_threshold": 0.6,
        "interpret_alerts": True,
    },
}


def default_paper_config() -> dict:
    return deepcopy(DEFAULT_CONFIG)


def _deep_merge(base: dict, patch: dict | None) -> dict:
    out = deepcopy(base or {})
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out


def _ratio(value, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    if 1 < number <= 100:
        number /= 100
    return number if 0 < number <= 1 else default


def normalize_paper_config(config: dict | None = None, *, base: dict | None = None) -> dict:
    """Canonicalize every persisted paper-strategy setting on the server."""
    merged = _deep_merge(default_paper_config(), base if isinstance(base, dict) else {})
    merged = _deep_merge(merged, config if isinstance(config, dict) else {})

    strategy_name = str(merged.get("strategy_name") or "").strip()
    merged["strategy_name"] = strategy_name or DEFAULT_CONFIG["strategy_name"]
    if not isinstance(merged.get("strategy_params"), dict):
        merged["strategy_params"] = deepcopy(DEFAULT_CONFIG["strategy_params"])

    raw_universe = merged.get("universe")
    if isinstance(raw_universe, str):
        raw_universe = raw_universe.split(",")
    codes = []
    for value in raw_universe if isinstance(raw_universe, list) else []:
        code = str(value or "").strip().split(".", 1)[0]
        if re.fullmatch(r"\d{6}", code) and code not in codes:
            codes.append(code)
    merged["universe"] = codes or deepcopy(DEFAULT_CONFIG["universe"])
    merged["position_size_pct"] = _ratio(
        merged.get("position_size_pct"),
        float(DEFAULT_CONFIG["position_size_pct"]),
    )
    try:
        max_positions = int(merged.get("max_positions"))
    except (TypeError, ValueError):
        max_positions = int(DEFAULT_CONFIG["max_positions"])
    merged["max_positions"] = max_positions if 1 <= max_positions <= 100 else int(DEFAULT_CONFIG["max_positions"])
    trade_time = str(merged.get("trade_time") or "").strip()
    merged["trade_time"] = trade_time if re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", trade_time) else DEFAULT_CONFIG["trade_time"]
    merged["enabled"] = bool(merged.get("enabled", True))
    merged["skip_data_stale"] = bool(merged.get("skip_data_stale", True))

    risk = apply_hard_limits(merged.get("risk") if isinstance(merged.get("risk"), dict) else {})
    risk.pop("_hard_limits_source", None)
    merged["risk"] = risk

    llm = _deep_merge(DEFAULT_CONFIG["llm"], merged.get("llm") if isinstance(merged.get("llm"), dict) else {})
    provider = normalize_provider(llm.get("provider"))
    llm["provider"] = provider
    llm["model"] = normalize_model(provider, llm.get("model"))
    llm["enabled"] = bool(llm.get("enabled", True))
    llm["inherit_global"] = bool(llm.get("inherit_global", True))
    llm["mode"] = llm.get("mode") if llm.get("mode") in {"off", "review", "decide"} else DEFAULT_CONFIG["llm"]["mode"]
    try:
        timeout = int(llm.get("timeout"))
    except (TypeError, ValueError):
        timeout = int(DEFAULT_CONFIG["llm"]["timeout"])
    llm["timeout"] = max(1, min(300, timeout))
    try:
        max_new_positions = int(llm.get("max_new_positions"))
    except (TypeError, ValueError):
        max_new_positions = int(DEFAULT_CONFIG["llm"]["max_new_positions"])
    llm["max_new_positions"] = max(0, min(100, max_new_positions))
    llm["confidence_threshold"] = _ratio(
        llm.get("confidence_threshold"),
        float(DEFAULT_CONFIG["llm"]["confidence_threshold"]),
    )
    llm["interpret_alerts"] = bool(llm.get("interpret_alerts", True))
    llm.pop("effective_source", None)
    llm.pop("registry_version", None)
    merged["llm"] = llm
    return merged

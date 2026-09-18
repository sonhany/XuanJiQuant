"""Confidence, data-quality and calibration weighted valuation consensus."""
from __future__ import annotations

from .contracts import safe_number


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def build_consensus(
    tracks: dict,
    *,
    data_quality: dict | None = None,
    calibration: dict | None = None,
    market_adjustment: float = 0.0,
) -> dict:
    """Combine intrinsic and peer valuation, then apply market state once."""
    data_quality = data_quality or {}
    calibration = calibration or {}
    raw_weights: dict[str, float] = {}
    usable: dict[str, dict] = {}
    for name in ("absolute", "relative"):
        track = tracks.get(name)
        if not isinstance(track, dict) or track.get("status") not in {"success", "partial"}:
            continue
        if any(safe_number(track.get(field)) is None for field in ("low", "mid", "high")):
            continue
        confidence = safe_number(track.get("confidence"))
        quality = safe_number(data_quality.get(name))
        reliability = safe_number((calibration.get(name) or {}).get("reliability"))
        raw = max(0.01, confidence if confidence is not None else 0.5)
        raw *= max(0.01, quality if quality is not None else 1.0)
        raw *= max(0.01, reliability if reliability is not None else 1.0)
        raw_weights[name] = raw
        usable[name] = track
    total = sum(raw_weights.values())
    if total <= 0:
        return {
            "status": "unavailable",
            "weights": {},
            "raw_weights": {},
            "market_applied_once": True,
        }
    weights = {name: value / total for name, value in raw_weights.items()}
    base = {
        field: sum(weights[name] * float(usable[name][field]) for name in usable)
        for field in ("low", "mid", "high")
    }
    adjustment = _clamp(float(market_adjustment or 0.0), -0.20, 0.20)
    final = {field: value * (1 + adjustment) for field, value in base.items()}
    return {
        "status": "success",
        "base_low": base["low"],
        "base_mid": base["mid"],
        "base_high": base["high"],
        "final_low": final["low"],
        "final_mid": final["mid"],
        "final_high": final["high"],
        "market_adjustment": adjustment,
        "market_applied_once": True,
        "weights": weights,
        "raw_weights": raw_weights,
        "data_quality": data_quality,
        "calibration": calibration,
    }

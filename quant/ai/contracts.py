"""Standard AI decision contract.

The LLM may propose portfolio targets and actions, but this module decides
whether the proposal is structurally usable. Invalid decisions are rejected
before they can reach the trading sandbox.
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta
from typing import Any


VALID_POLICIES = {"normal", "reduce_only", "no_new_position"}
VALID_REBALANCE_ACTIONS = {"buy", "sell", "hold"}
REQUIRED_FIELDS = {
    "target_weights",
    "rebalance_plan",
    "risk_budget",
    "confidence",
    "valid_until",
    "model_version",
    "prompt_version",
    "reason_codes",
}


class DecisionValidationError(ValueError):
    """Raised when an AI decision does not satisfy the contract."""


def _now() -> datetime:
    return datetime.now()


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(text.replace("Z", ""), fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _code(value: Any) -> str:
    return str(value or "").split(".")[0].strip()


def _decision_id(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def normalize_ai_decision(raw: dict | None, *, default_valid_minutes: int = 480) -> dict:
    """Return a normalized decision payload without relaxing hard validation.

    This function trims codes, clamps numeric values to safe ranges, and fills
    derived metadata. It does not silently invent the required contract fields;
    validate_ai_decision() still rejects missing fields.
    """
    src = copy.deepcopy(raw or {})
    src.setdefault("trade_policy", "no_new_position")
    src["trade_policy"] = src["trade_policy"] if src["trade_policy"] in VALID_POLICIES else "no_new_position"
    src["trade_allowed"] = bool(src.get("trade_allowed", False)) and src["trade_policy"] == "normal"

    weights = []
    seen = set()
    for row in src.get("target_weights") or []:
        if not isinstance(row, dict):
            continue
        code = _code(row.get("code"))
        if not code or code in seen:
            continue
        weight = max(0.0, min(1.0, _to_float(row.get("target_weight"))))
        confidence = max(0.0, min(1.0, _to_float(row.get("confidence"), src.get("confidence", 0.0))))
        weights.append({
            "code": code,
            "target_weight": round(weight, 6),
            "confidence": round(confidence, 6),
            "reason": str(row.get("reason") or "")[:240],
        })
        seen.add(code)
    src["target_weights"] = weights

    plan = []
    for row in src.get("rebalance_plan") or []:
        if not isinstance(row, dict):
            continue
        code = _code(row.get("code"))
        action = str(row.get("action", "hold")).lower()
        if not code or action not in VALID_REBALANCE_ACTIONS:
            continue
        plan.append({
            "code": code,
            "action": action,
            "target_weight": round(max(0.0, min(1.0, _to_float(row.get("target_weight")))), 6),
            "priority": str(row.get("priority") or "medium")[:24],
            "reason": str(row.get("reason") or "")[:240],
        })
    src["rebalance_plan"] = plan

    risk_budget = src.get("risk_budget") if isinstance(src.get("risk_budget"), dict) else {}
    src["risk_budget"] = {
        "max_position_pct": max(0.0, min(1.0, _to_float(risk_budget.get("max_position_pct"), 0.2))),
        "max_gross_exposure_pct": max(0.0, min(100.0, _to_float(risk_budget.get("max_gross_exposure_pct"), 95))),
        "max_position_count": max(0, int(_to_float(risk_budget.get("max_position_count"), 10))),
        "max_daily_turnover_pct": max(0.0, min(100.0, _to_float(risk_budget.get("max_daily_turnover_pct"), 35))),
    }
    src["confidence"] = round(max(0.0, min(1.0, _to_float(src.get("confidence"), 0.0))), 6)

    if not src.get("valid_until") and src.get("generated_at"):
        gen = _parse_dt(src.get("generated_at")) or _now()
        src["valid_until"] = (gen + timedelta(minutes=default_valid_minutes)).strftime("%Y-%m-%d %H:%M:%S")

    src["reason_codes"] = [str(x)[:80] for x in (src.get("reason_codes") or []) if str(x).strip()]
    src["model_version"] = str(src.get("model_version") or "")[:80]
    src["prompt_version"] = str(src.get("prompt_version") or "")[:80]
    src["schema_version"] = "ai_decision.v1"
    src["decision_id"] = src.get("decision_id") or _decision_id(src)
    return src


def validate_ai_decision(raw: dict | None, *, now: datetime | None = None) -> dict:
    """Validate and return a normalized AI decision.

    Raises DecisionValidationError on any contract violation. Callers should
    discard the decision and fail closed.
    """
    if not isinstance(raw, dict) or not raw:
        raise DecisionValidationError("missing decision payload")
    missing = sorted(REQUIRED_FIELDS - set(raw.keys()))
    if missing:
        raise DecisionValidationError(f"missing required fields: {', '.join(missing)}")

    decision = normalize_ai_decision(raw)
    errors = []
    if decision["trade_policy"] not in VALID_POLICIES:
        errors.append("invalid trade_policy")
    if decision["trade_allowed"] and decision["trade_policy"] != "normal":
        errors.append("trade_allowed requires trade_policy=normal")
    if not isinstance(decision["target_weights"], list):
        errors.append("target_weights must be list")
    if not isinstance(decision["rebalance_plan"], list):
        errors.append("rebalance_plan must be list")
    if not isinstance(decision["risk_budget"], dict):
        errors.append("risk_budget must be object")
    if not decision["model_version"]:
        errors.append("model_version is empty")
    if not decision["prompt_version"]:
        errors.append("prompt_version is empty")
    if not decision["reason_codes"]:
        errors.append("reason_codes is empty")
    if decision["confidence"] < 0 or decision["confidence"] > 1:
        errors.append("confidence out of range")

    total_weight = sum(float(row.get("target_weight", 0)) for row in decision["target_weights"])
    max_gross = float(decision["risk_budget"].get("max_gross_exposure_pct", 95)) / 100
    max_pos = float(decision["risk_budget"].get("max_position_pct", 0.2))
    max_count = int(decision["risk_budget"].get("max_position_count", 10))
    if total_weight > max_gross + 1e-9:
        errors.append("target total weight exceeds risk_budget.max_gross_exposure_pct")
    if len(decision["target_weights"]) > max_count:
        errors.append("target position count exceeds risk_budget.max_position_count")
    for row in decision["target_weights"]:
        if float(row.get("target_weight", 0)) > max_pos + 1e-9:
            errors.append(f"{row.get('code')} weight exceeds risk_budget.max_position_pct")

    valid_until = _parse_dt(decision.get("valid_until"))
    if valid_until is None:
        errors.append("valid_until is invalid")
    elif valid_until < (now or _now()):
        errors.append("decision expired")

    if decision["trade_policy"] != "normal":
        buys = [x for x in decision["rebalance_plan"] if x.get("action") == "buy"]
        if buys:
            errors.append("non-normal trade_policy cannot contain buy actions")

    if errors:
        raise DecisionValidationError("; ".join(errors))
    return decision


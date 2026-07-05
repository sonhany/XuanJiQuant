"""Read and validate the unified AI decision for paper trading."""
from __future__ import annotations

from datetime import datetime

from quant.ai.contracts import DecisionValidationError, validate_ai_decision
from quant.data.audit import write_ai_decision, write_audit_event


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def load_valid_decision(cache, *, require_verifier: bool = True) -> tuple[dict, list[str]]:
    """Load ai:decision:latest and fail closed when it is invalid.

    Returns:
        (decision, errors). When errors is non-empty the returned decision is a
        safe no-new-position decision.
    """
    raw = cache.get("ai:decision:latest") or {}
    errors = []
    try:
        decision = validate_ai_decision(raw)
    except DecisionValidationError as exc:
        errors.append(f"AI决策协议无效: {exc}")
        decision = {
            "trade_policy": "no_new_position",
            "trade_allowed": False,
            "date": _today(),
            "target_weights": [],
            "rebalance_plan": [],
            "risk_budget": {},
            "confidence": 0,
            "reason_codes": ["decision_contract_invalid"],
            "contract_error": str(exc),
        }
        write_audit_event(cache, "ai_decision_rejected", {"error": str(exc), "raw": raw}, source="decision_reader")
        return decision, errors

    verifier = cache.get("ai:verifier:latest") or {}
    decision["verifier_overall"] = verifier.get("overall")
    if require_verifier and decision.get("trade_allowed") and verifier.get("overall") != "pass":
        errors.append("AI验证器未通过, 禁止高风险交易")
        decision["trade_allowed"] = False
        decision["trade_policy"] = "no_new_position"
        decision.setdefault("reason_codes", []).append("verifier_not_pass")

    write_ai_decision(cache, decision, source="decision_reader")
    return decision, errors


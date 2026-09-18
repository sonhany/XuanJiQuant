"""Governed experimental portfolio derived from rejected F4 research evidence."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

from .research_selection import ResearchSelectionBlocked, build_research_selection


EXPERIMENTAL_POLICY_VERSION = "f5-experimental-paper-v1"
PERFORMANCE_REASONS = frozenset(
    {
        "positive_excess_window_ratio_below_0_60",
        "after_cost_excess_return_not_positive",
        "sharpe_below_0_80",
        "max_drawdown_below_minus_0_20",
        "double_cost_excess_return_not_positive",
    }
)
REQUIRED_INPUT_STATUS = {
    "benchmark": "present",
    "f3_evidence": "present",
    "pit_industry": "present",
    "pit_manifest": "complete",
    "pit_quality": "passed",
}


def canonical_selection_id(payload: Mapping[str, Any]) -> str:
    identity = dict(payload)
    identity.pop("portfolio_id", None)
    identity.pop("generated_at", None)
    encoded = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validated_experimental_f4(
    f4_latest: Mapping[str, Any], research_generation_id: str
) -> tuple[str, ...]:
    if str(f4_latest.get("status") or "") != "f4_rejected":
        raise ResearchSelectionBlocked("experimental_f4_status_forbidden")
    if str(f4_latest.get("candidate_factory_status") or "") != "exhausted":
        raise ResearchSelectionBlocked("experimental_candidate_factory_incomplete")
    reasons = tuple(
        str(value) for value in (f4_latest.get("reasons") or ()) if str(value)
    )
    if not reasons or not set(reasons).issubset(PERFORMANCE_REASONS):
        raise ResearchSelectionBlocked("experimental_f4_reason_forbidden")
    input_status = dict(f4_latest.get("input_status") or {})
    if any(
        input_status.get(key) != value
        for key, value in REQUIRED_INPUT_STATUS.items()
    ):
        raise ResearchSelectionBlocked("experimental_f4_input_unavailable")
    metrics = dict(f4_latest.get("metrics") or {})
    if int(metrics.get("constraint_violation_count") or 0) != 0:
        raise ResearchSelectionBlocked("portfolio_constraint_failed")
    if int(metrics.get("future_data_violation_count") or 0) != 0:
        raise ResearchSelectionBlocked("future_data_detected")
    if not str(research_generation_id).strip():
        raise ResearchSelectionBlocked("research_generation_identity_missing")
    return reasons


def build_experimental_selection_from_research(
    *,
    research_selection: Mapping[str, Any],
    f4_latest: Mapping[str, Any],
    research_generation_id: str,
    generated_at: str,
) -> dict[str, Any]:
    """Promote one verified daily research selection into the paper-only lane."""

    reasons = _validated_experimental_f4(f4_latest, research_generation_id)
    if (
        research_selection.get("promotion_state") != "research_only"
        or research_selection.get("execution_authority") is not False
        or research_selection.get("not_a_trade_signal") is not True
        or research_selection.get("selection_status")
        not in {"diagnostic_research_portfolio", "experimental_research_portfolio"}
        or research_selection.get("f4_gate_status") != "f4_rejected"
        or research_selection.get("f4_validation_id")
        != f4_latest.get("validation_id")
        or not isinstance(research_selection.get("positions"), list)
        or not research_selection.get("positions")
        or int(research_selection.get("position_count") or 0)
        != len(research_selection.get("positions") or [])
    ):
        raise ResearchSelectionBlocked("experimental_research_selection_invalid")
    expected_factory = str(f4_latest.get("factory_run_id") or "")
    selection_factory = str(research_selection.get("f4_factory_run_id") or "")
    if expected_factory and selection_factory != expected_factory:
        raise ResearchSelectionBlocked("experimental_factory_identity_mismatch")
    payload = dict(research_selection)
    payload.update(
        {
            "generated_at": str(generated_at),
            "selection_status": "experimental_research_portfolio",
            "research_generation_id": str(research_generation_id),
            "experimental_policy_version": EXPERIMENTAL_POLICY_VERSION,
            "f4_reasons": list(reasons),
            "warnings": [
                "F4未通过，仅允许实验模拟，不构成合格策略或实盘信号。"
            ],
            "promotion_state": "research_only",
            "execution_authority": False,
            "not_a_trade_signal": True,
        }
    )
    payload["portfolio_id"] = canonical_selection_id(payload)
    return payload


def build_experimental_selection(
    *,
    factor_snapshot: Mapping[str, Any],
    factor_evaluation: Mapping[str, Any],
    f4_latest: Mapping[str, Any],
    candidate_spec: Mapping[str, Any],
    industry_records: Iterable[Mapping[str, Any]],
    research_generation_id: str,
    generated_at: str,
) -> dict[str, Any]:
    """Build a simulation-only selection without changing the rejected F4 fact."""

    reasons = _validated_experimental_f4(f4_latest, research_generation_id)

    payload = build_research_selection(
        factor_snapshot=factor_snapshot,
        factor_evaluation=factor_evaluation,
        f4_latest=f4_latest,
        candidate_spec=candidate_spec,
        industry_records=industry_records,
        generated_at=generated_at,
    )
    payload.update(
        {
            "selection_status": "experimental_research_portfolio",
            "research_generation_id": str(research_generation_id),
            "experimental_policy_version": EXPERIMENTAL_POLICY_VERSION,
            "f4_reasons": list(reasons),
            "warnings": [
                "F4未通过，仅允许实验模拟，不构成合格策略或实盘信号。"
            ],
        }
    )
    payload["portfolio_id"] = canonical_selection_id(payload)
    return payload

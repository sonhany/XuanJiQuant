"""Fail-closed admission gate between F4 research and F5 simulation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .policy import PaperExecutionPolicy
from quant.strategy.f4_candidate_factory import (
    FACTORY_VERSION_V1,
    FACTORY_VERSION_V2,
    canonical_payload_hash,
)
from quant.strategy.experimental_selection import PERFORMANCE_REASONS, REQUIRED_INPUT_STATUS


@dataclass(frozen=True, slots=True)
class EligibilityResult:
    eligible: bool
    reason_code: str
    evidence: dict[str, Any] = field(default_factory=dict)


def _result(eligible: bool, reason: str, evidence: Mapping[str, Any] | None = None) -> EligibilityResult:
    return EligibilityResult(eligible=eligible, reason_code=reason, evidence=dict(evidence or {}))


def evaluate_eligibility(
    *,
    selection: Mapping[str, Any] | None,
    f4_latest: Mapping[str, Any] | None,
    factor_evidence: Mapping[str, Any] | None,
    policy: PaperExecutionPolicy,
    risk: Mapping[str, Any],
    intended_session: str,
    expected_selection_date: str,
    existing_run: Mapping[str, Any] | None = None,
) -> EligibilityResult:
    """Return the first stable gate result; never creates an order."""

    base = {
        "intended_session": intended_session,
        "expected_selection_date": expected_selection_date,
        "execution_mode": policy.execution_mode,
        "paper_execution_authority": policy.paper_execution_authority,
        "live_execution_authority": False,
        "policy_hash": policy.policy_hash,
    }
    if not policy.enabled:
        return _result(False, "paper_execution_disabled", base)
    if policy.kill_switch or bool(risk.get("kill_switch")):
        return _result(False, "kill_switch_active", base)
    if existing_run is not None:
        return _result(False, "duplicate_run", base | {"existing_status": existing_run.get("status")})
    if not selection:
        return _result(False, "selection_missing", base)
    if not f4_latest:
        return _result(False, "f4_evidence_missing", base)
    if not factor_evidence or factor_evidence.get("quality_passed") is not True:
        return _result(False, "factor_evidence_unavailable", base)

    selection_status = str(selection.get("selection_status") or "")
    selection_gate = str(selection.get("f4_gate_status") or "")
    f4_status = str(f4_latest.get("status") or "")
    validated_lane = (
        selection_status == "f4_research_portfolio"
        and selection_gate == "f4_research_candidate"
        and f4_status == "f4_research_candidate"
    )
    experimental_lane = bool(
        policy.experimental_paper.enabled
        and f4_status in policy.experimental_paper.allowed_f4_statuses
        and selection_status == "experimental_research_portfolio"
        and selection_gate == "f4_rejected"
    )
    if not validated_lane and not experimental_lane:
        return _result(False, "blocked_by_f4", base | {"f4_status": f4_status, "selection_status": selection_status})
    execution_lane = "validated_paper" if validated_lane else "experimental_paper"
    strategy_quality = "validated" if validated_lane else "unqualified"
    eligible_reason = "eligible" if validated_lane else "eligible_experimental"
    lane_evidence = {
        "execution_lane": execution_lane,
        "strategy_quality_status": strategy_quality,
        "f4_status": f4_status,
        "f4_reasons": list(f4_latest.get("reasons") or []),
    }
    if experimental_lane:
        if str(f4_latest.get("candidate_factory_status") or "") != "exhausted":
            return _result(False, "experimental_candidate_factory_incomplete", base | lane_evidence)
        reasons = {
            str(value) for value in (f4_latest.get("reasons") or []) if str(value)
        }
        if not reasons or not reasons.issubset(PERFORMANCE_REASONS):
            return _result(False, "experimental_f4_reason_forbidden", base | lane_evidence)
        input_status = dict(f4_latest.get("input_status") or {})
        if any(
            input_status.get(key) != value
            for key, value in REQUIRED_INPUT_STATUS.items()
        ):
            return _result(False, "experimental_f4_input_unavailable", base | lane_evidence)
        metrics = dict(f4_latest.get("metrics") or {})
        if (
            policy.experimental_paper.require_zero_constraint_violations
            and int(metrics.get("constraint_violation_count") or 0) != 0
        ):
            return _result(False, "portfolio_constraint_failed", base | lane_evidence)
        if (
            policy.experimental_paper.require_zero_future_data_violations
            and int(metrics.get("future_data_violation_count") or 0) != 0
        ):
            return _result(False, "future_data_detected", base | lane_evidence)
        if str(selection.get("experimental_policy_version") or "") != str(
            policy.experimental_paper.policy_version
        ):
            return _result(False, "experimental_policy_version_mismatch", base | lane_evidence)
    if (
        selection.get("promotion_state") != "research_only"
        or selection.get("execution_authority") is not False
        or selection.get("not_a_trade_signal") is not True
        or f4_latest.get("promotion_state") != "research_only"
        or f4_latest.get("execution_authority") is not False
    ):
        return _result(False, "research_authority_invalid", base)

    validation_id = str(selection.get("f4_validation_id") or "")
    if not validation_id or validation_id != str(f4_latest.get("validation_id") or ""):
        return _result(False, "validation_identity_mismatch", base | {"validation_id": validation_id})
    if str(selection.get("selection_date") or "").replace("-", "") != str(expected_selection_date).replace("-", ""):
        return _result(False, "selection_stale", base | {"selection_date": selection.get("selection_date")})
    if (
        str(selection.get("generated_from_snapshot_id") or "") != str(factor_evidence.get("snapshot_id") or "")
        or str(selection.get("snapshot_data_version") or "") != str(factor_evidence.get("data_version") or "")
        or str(factor_evidence.get("as_of") or "").replace("-", "") != str(expected_selection_date).replace("-", "")
    ):
        return _result(False, "data_identity_mismatch", base)

    positions = list(selection.get("positions") or [])
    declared_count = int(selection.get("position_count") or 0)
    max_count = int(risk.get("max_position_count") or 0)
    max_position = float(risk.get("max_position_pct") or 0)
    gross_cap = float(risk.get("max_gross_exposure_pct") or 0) / 100.0
    invested = float(selection.get("invested_weight") or 0)
    if declared_count != len(positions) or declared_count <= 0:
        return _result(False, "portfolio_integrity_failed", base)
    if declared_count > max_count:
        return _result(
            False,
            "portfolio_policy_incompatible",
            base | {"position_count": declared_count, "max_position_count": max_count},
        )
    if any(float(item.get("target_weight") or 0) > max_position + 1e-12 for item in positions):
        return _result(False, "portfolio_policy_incompatible", base | {"limit": "max_position_pct"})
    if invested > gross_cap + 1e-12:
        return _result(False, "portfolio_policy_incompatible", base | {"limit": "max_gross_exposure_pct"})
    portfolio_policy = dict(selection.get("portfolio_policy") or {})
    selection_factory_version = selection.get("f4_factory_version")
    if (
        selection_factory_version != FACTORY_VERSION_V2
        and str(portfolio_policy.get("version") or "")
        != str(f4_latest.get("portfolio_policy_version") or "")
    ):
        return _result(False, "portfolio_policy_version_mismatch", base)
    if int(portfolio_policy.get("lot_size") or policy.lot_size) != policy.lot_size:
        return _result(False, "portfolio_policy_incompatible", base | {"limit": "lot_size"})
    candidate_spec = dict(f4_latest.get("candidate_spec") or {})
    factory_run_id = str(candidate_spec.get("factory_run_id") or "")
    outer_factory_version = f4_latest.get("candidate_spec_version")
    inner_factory_version = candidate_spec.get("version")
    uses_candidate_factory = bool(
        candidate_spec
        or factory_run_id
        or outer_factory_version is not None
        or selection_factory_version is not None
    )
    factory_version = ""
    if uses_candidate_factory:
        version_triplet = (
            outer_factory_version,
            inner_factory_version,
            selection_factory_version,
        )
        if (
            any(type(value) is not str or not value.strip() for value in version_triplet)
            or len(set(version_triplet)) != 1
            or version_triplet[0]
            not in {FACTORY_VERSION_V1, FACTORY_VERSION_V2}
        ):
            return _result(False, "f4_candidate_factory_version_unsupported", base)
        factory_version = version_triplet[0]
    if uses_candidate_factory and not factory_run_id:
        return _result(False, "f4_candidate_policy_identity_mismatch", base)
    if uses_candidate_factory:
        candidate_id = str(selection.get("f4_candidate_id") or "")
        fit_window = str(selection.get("factor_fit_window") or "")
        governed = next(
            (
                dict(item)
                for item in candidate_spec.get("selected_policies") or []
                if str(item.get("candidate_id") or "") == candidate_id
                and str(item.get("window_id") or "") == fit_window
            ),
            {},
        )
        lock = next(
            (
                dict(item)
                for item in candidate_spec.get("selection_locks") or []
                if str(item.get("candidate_id") or "") == candidate_id
                and str(item.get("window_id") or "") == fit_window
            ),
            {},
        )
        fit = next(
            (
                dict(item)
                for item in candidate_spec.get("factor_fits") or []
                if str(item.get("candidate_id") or "") == candidate_id
                and str(item.get("window_id") or "") == fit_window
            ),
            {},
        )
        governed_policy = {
            key: value for key, value in governed.items() if key in portfolio_policy
        }
        common_identity_invalid = (
            str(selection.get("f4_factory_run_id") or "") != factory_run_id
            or not candidate_id
            or not governed
            or not lock
            or governed_policy != portfolio_policy
            or str(selection.get("f4_candidate_lock_hash") or "")
            != str(lock.get("lock_hash") or "")
            or str(selection.get("portfolio_policy_hash") or "")
            != canonical_payload_hash(portfolio_policy)
            or str(governed.get("policy_hash") or "")
            != canonical_payload_hash(portfolio_policy)
        )
        if common_identity_invalid:
            return _result(False, "f4_candidate_policy_identity_mismatch", base)
        if factory_version == FACTORY_VERSION_V2:
            lock_core = {
                key: value
                for key, value in lock.items()
                if key not in {"lock_hash", "promotion_state", "execution_authority"}
            }
            lock_hash = str(lock.get("lock_hash") or "")
            alpha_spec_hash = str(fit.get("alpha_spec_hash") or "")
            alpha_fit_hash = str(fit.get("alpha_fit_hash") or "")
            lock_alpha_spec_hash = str(lock.get("alpha_spec_hash") or "")
            lock_alpha_fit_hash = str(lock.get("alpha_fit_hash") or "")
            if (
                str(selection.get("f4_factory_version") or "") != FACTORY_VERSION_V2
                or lock.get("factory_run_id") != factory_run_id
                or not fit
                or not alpha_spec_hash
                or not alpha_fit_hash
                or not lock_hash
                or lock_hash != canonical_payload_hash(lock_core)
                or str(governed.get("lock_hash") or "") != lock_hash
                or str(lock.get("portfolio_policy_hash") or "")
                != canonical_payload_hash(portfolio_policy)
            ):
                return _result(False, "f4_candidate_policy_identity_mismatch", base)
            if (
                str(selection.get("f4_alpha_spec_hash") or "") != alpha_spec_hash
                or alpha_spec_hash != lock_alpha_spec_hash
            ):
                return _result(False, "f4_candidate_alpha_identity_mismatch", base)
            if (
                str(selection.get("f4_alpha_fit_hash") or "") != alpha_fit_hash
                or alpha_fit_hash != lock_alpha_fit_hash
            ):
                return _result(False, "f4_candidate_alpha_fit_identity_mismatch", base)
            model = next(
                (
                    dict(item)
                    for item in candidate_spec.get("model_artifacts") or []
                    if str(item.get("candidate_id") or "") == candidate_id
                    and str(item.get("window_id") or "") == fit_window
                ),
                {},
            )
            lock_model_hash = lock.get("model_artifact_hash")
            expected_model_hash = model.get("model_artifact_hash") if model else None
            if (
                lock_model_hash != expected_model_hash
                or selection.get("f4_model_artifact_hash") != expected_model_hash
            ):
                return _result(False, "f4_candidate_model_identity_mismatch", base)

    return _result(
        True,
        eligible_reason,
        base
        | lane_evidence
        | {
            "portfolio_id": selection.get("portfolio_id"),
            "validation_id": validation_id,
            "position_count": declared_count,
        },
    )

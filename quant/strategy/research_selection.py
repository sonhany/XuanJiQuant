"""Deterministic, research-only daily portfolio projection.

This module consumes versioned factor and F4 evidence.  It never creates an
order, promotes a candidate, or grants execution authority.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, fields
from typing import Any, Iterable, Mapping

import pandas as pd

from .portfolio import PortfolioPolicy, build_target_weights
from .f4_alpha_rules import derive_rule_features, preprocess_cross_section
from .f4_candidate_factory import (
    FACTORY_VERSION_V1,
    FACTORY_VERSION_V2,
    canonical_payload_hash,
)


SCHEMA_VERSION = "research-selection-v1"
FACTOR_LABELS = {
    "range_pct": "日内振幅",
    "volatility_60": "60日波动率",
    "volatility_20": "20日波动率",
    "atr_14": "14日真实波幅",
    "volatility_5": "5日波动率",
    "pvbeta_20": "20日量价贝塔",
    "boll_upper": "布林带上轨",
    "ema_12": "12日指数均线",
    "boll_mid": "布林带中轨",
    "ret_20": "20日收益率",
}


class ResearchSelectionBlocked(RuntimeError):
    def __init__(self, reason_code: str, detail: str = ""):
        self.reason_code = str(reason_code)
        self.detail = str(detail)
        super().__init__(f"{self.reason_code}: {self.detail}".rstrip(": "))


def _compact_date(value: object) -> str:
    return str(value or "").replace("-", "")[:8]


def _require_research_only(value: Mapping[str, Any], source: str) -> None:
    if (
        value.get("promotion_state") != "research_only"
        or value.get("execution_authority") is not False
    ):
        raise ResearchSelectionBlocked(
            f"{source}_authority_invalid",
            "research artifact must be research_only with no execution authority",
        )


def _latest_industries(
    records: Iterable[Mapping[str, Any]], *, as_of: str
) -> dict[str, tuple[str, str]]:
    cutoff = pd.Timestamp(as_of)
    latest: dict[str, tuple[pd.Timestamp, str, str]] = {}
    for row in records:
        instrument = str(row.get("instrument") or "")
        if not instrument:
            continue
        try:
            effective = pd.Timestamp(str(row.get("effective_from") or ""))
        except (TypeError, ValueError):
            continue
        if effective > cutoff:
            continue
        code = instrument[-6:]
        previous = latest.get(code)
        if previous is None or effective > previous[0]:
            latest[code] = (
                effective,
                str(row.get("industry_code") or "industry_unknown"),
                str(row.get("industry_name") or "行业未知"),
            )
    return {code: (value[1], value[2]) for code, value in latest.items()}


def _canonical_id(payload: Mapping[str, Any]) -> str:
    identity = dict(payload)
    identity.pop("generated_at", None)
    identity.pop("portfolio_id", None)
    encoded = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_research_selection(
    *,
    factor_snapshot: Mapping[str, Any],
    factor_evaluation: Mapping[str, Any],
    f4_latest: Mapping[str, Any],
    candidate_spec: Mapping[str, Any],
    industry_records: Iterable[Mapping[str, Any]],
    generated_at: str,
    policy: PortfolioPolicy | None = None,
) -> dict[str, Any]:
    """Build a version-bound portfolio projection from frozen research evidence."""

    _require_research_only(factor_snapshot, "factor_snapshot")
    _require_research_only(factor_evaluation, "factor_evaluation")
    _require_research_only(f4_latest, "f4")
    _require_research_only(candidate_spec, "candidate_spec")

    selection_date = _compact_date(
        factor_snapshot.get("as_of") or factor_snapshot.get("latest_kline_date")
    )
    snapshot_id = str(factor_snapshot.get("snapshot_id") or "")
    data_version = str(factor_snapshot.get("data_version") or "")
    if not selection_date or not snapshot_id or not data_version:
        raise ResearchSelectionBlocked(
            "factor_snapshot_identity_missing", "date, snapshot_id and data_version required"
        )
    if _compact_date(factor_evaluation.get("data_end_date")) != selection_date:
        raise ResearchSelectionBlocked(
            "factor_evaluation_date_mismatch", selection_date
        )
    if str(factor_evaluation.get("snapshot_id") or "") != snapshot_id:
        raise ResearchSelectionBlocked(
            "factor_evaluation_snapshot_mismatch", snapshot_id
        )
    if str(factor_evaluation.get("data_version") or "") != data_version:
        raise ResearchSelectionBlocked(
            "factor_evaluation_version_mismatch", data_version
        )

    validation_id = str(f4_latest.get("validation_id") or "")
    f4_status = str(f4_latest.get("status") or "")
    if f4_status not in {"f4_rejected", "f4_research_candidate"}:
        raise ResearchSelectionBlocked("f4_selection_unavailable", f4_status)
    if not validation_id or str(candidate_spec.get("validation_id") or "") != validation_id:
        raise ResearchSelectionBlocked("f4_validation_identity_mismatch", validation_id)
    factor_fits = list(candidate_spec.get("factor_fits") or [])
    if not factor_fits:
        raise ResearchSelectionBlocked("f4_factor_fit_missing")
    fit = dict(factor_fits[-1])
    factors = tuple(str(value) for value in (fit.get("factors") or []) if str(value))
    directions = dict(fit.get("directions") or {})
    weights = dict(fit.get("weights") or {})
    if not factors or any(name not in directions or name not in weights for name in factors):
        raise ResearchSelectionBlocked("f4_factor_fit_invalid")

    industries = _latest_industries(industry_records, as_of=selection_date)
    flattened: list[dict[str, Any]] = []
    for source in factor_snapshot.get("rows") or []:
        code = str(source.get("code") or "").zfill(6)
        if not code or _compact_date(source.get("date")) != selection_date:
            continue
        row = {
            "code": code,
            "name": str(source.get("name") or ""),
            "date": selection_date,
            "close": source.get("close"),
        }
        row.update(dict(source.get("factors") or {}))
        industry_code, industry_name = industries.get(
            code, ("industry_unknown", "行业未知")
        )
        row["industry"] = industry_code
        row["industry_name"] = industry_name
        flattened.append(row)
    if not flattened:
        raise ResearchSelectionBlocked("factor_snapshot_rows_missing")

    frame = pd.DataFrame(flattened)
    factory_version = str(candidate_spec.get("version") or "")
    if factory_version == FACTORY_VERSION_V2:
        try:
            frame = preprocess_cross_section(
                derive_rule_features(frame, factors), factors
            )
        except (TypeError, ValueError) as exc:
            raise ResearchSelectionBlocked(
                "f4_v2_factor_preprocessing_failed", str(exc)
            ) from exc
    score = pd.Series(0.0, index=frame.index, dtype=float)
    usable = pd.Series(True, index=frame.index, dtype=bool)
    contributions: dict[str, pd.Series] = {}
    for name in factors:
        if name not in frame.columns:
            raise ResearchSelectionBlocked("factor_column_missing", name)
        values = pd.to_numeric(frame[name], errors="coerce")
        usable &= values.notna() & values.map(math.isfinite)
        percentile = (
            values
            if factory_version == FACTORY_VERSION_V2
            else values.rank(method="average", pct=True)
        )
        contribution = (
            (percentile - 0.5)
            * int(directions[name])
            * float(weights[name])
        )
        contributions[name] = contribution
        score += contribution
    frame["score"] = score
    scored = frame.loc[usable].copy()
    if scored.empty:
        raise ResearchSelectionBlocked("factor_scores_missing")

    effective_policy = policy
    selected_candidate_id = str(fit.get("candidate_id") or "")
    selected_lock_hash = ""
    selected_policy_hash = ""
    selected_alpha_spec_hash = ""
    selected_alpha_fit_hash = ""
    selected_model_artifact_hash: str | None = None
    factory_run_id = str(candidate_spec.get("factory_run_id") or "")
    uses_candidate_factory = bool(factory_version or factory_run_id or selected_candidate_id)
    if uses_candidate_factory and factory_version not in {
        FACTORY_VERSION_V1,
        FACTORY_VERSION_V2,
    }:
        raise ResearchSelectionBlocked("f4_candidate_factory_version_unsupported")
    if uses_candidate_factory and not factory_run_id:
        reason = (
            "f4_candidate_v2_identity_missing"
            if factory_version == FACTORY_VERSION_V2
            else "f4_candidate_factory_identity_missing"
        )
        raise ResearchSelectionBlocked(reason)
    if uses_candidate_factory:
        selected_policies = list(candidate_spec.get("selected_policies") or [])
        selected_policy = next(
            (
                dict(item)
                for item in reversed(selected_policies)
                if str(item.get("candidate_id") or "") == selected_candidate_id
                and str(item.get("window_id") or "") == str(fit.get("window_id") or "")
            ),
            {},
        )
        selected_lock = next(
            (
                dict(item)
                for item in candidate_spec.get("selection_locks") or []
                if str(item.get("candidate_id") or "") == selected_candidate_id
                and str(item.get("window_id") or "") == str(fit.get("window_id") or "")
            ),
            {},
        )
        if not selected_candidate_id or not selected_policy or not selected_lock:
            raise ResearchSelectionBlocked("f4_candidate_policy_missing")
        lock_core = {
            key: value
            for key, value in selected_lock.items()
            if key not in {"lock_hash", "promotion_state", "execution_authority"}
        }
        selected_lock_hash = str(selected_lock.get("lock_hash") or "")
        if (
            selected_lock.get("factory_run_id") != factory_run_id
            or selected_lock_hash != canonical_payload_hash(lock_core)
        ):
            raise ResearchSelectionBlocked("f4_candidate_lock_invalid")
        allowed = {field.name for field in fields(PortfolioPolicy)}
        governed_policy = PortfolioPolicy(
            **{key: value for key, value in selected_policy.items() if key in allowed}
        )
        v1_policy_unsafe = factory_version == FACTORY_VERSION_V1 and (
            governed_policy.top_k > 10
            or governed_policy.target_gross_exposure > 0.95
            or governed_policy.max_name_weight > 0.20
            or governed_policy.top_k * governed_policy.max_name_weight
            > governed_policy.target_gross_exposure + 1e-12
            or governed_policy.version != "nested-window-policy-v1"
        )
        v2_policy_unsafe = factory_version == FACTORY_VERSION_V2 and (
            governed_policy.top_k != 10
            or governed_policy.target_gross_exposure != 0.95
            or governed_policy.max_name_weight != 0.095
            or governed_policy.max_industry_weight != 0.25
            or governed_policy.lot_size != 100
            or governed_policy.adv_participation != 0.10
            or governed_policy.version != "f4-standard-top10-policy-v2"
        )
        if v1_policy_unsafe or v2_policy_unsafe:
            raise ResearchSelectionBlocked("f4_candidate_policy_unsafe")
        if effective_policy is not None and asdict(effective_policy) != asdict(governed_policy):
            raise ResearchSelectionBlocked("f4_candidate_policy_override_forbidden")
        effective_policy = governed_policy
        selected_policy_hash = canonical_payload_hash(asdict(effective_policy))
        if str(selected_policy.get("policy_hash") or "") != selected_policy_hash:
            raise ResearchSelectionBlocked("f4_candidate_policy_hash_invalid")
        if factory_version == FACTORY_VERSION_V2:
            selected_alpha_spec_hash = str(fit.get("alpha_spec_hash") or "")
            selected_alpha_fit_hash = str(fit.get("alpha_fit_hash") or "")
            lock_alpha_spec_hash = str(selected_lock.get("alpha_spec_hash") or "")
            lock_alpha_fit_hash = str(selected_lock.get("alpha_fit_hash") or "")
            lock_policy_hash = str(selected_lock.get("portfolio_policy_hash") or "")
            if not all(
                (
                    selected_candidate_id,
                    selected_alpha_spec_hash,
                    selected_alpha_fit_hash,
                    selected_policy_hash,
                    selected_lock_hash,
                )
            ):
                raise ResearchSelectionBlocked("f4_candidate_v2_identity_missing")
            if selected_alpha_spec_hash != lock_alpha_spec_hash:
                raise ResearchSelectionBlocked("f4_candidate_alpha_identity_mismatch")
            if selected_alpha_fit_hash != lock_alpha_fit_hash:
                raise ResearchSelectionBlocked("f4_candidate_alpha_fit_identity_mismatch")
            if (
                lock_policy_hash != selected_policy_hash
                or str(selected_policy.get("lock_hash") or "") != selected_lock_hash
            ):
                raise ResearchSelectionBlocked("f4_candidate_policy_identity_mismatch")
            model = next(
                (
                    dict(item)
                    for item in candidate_spec.get("model_artifacts") or []
                    if str(item.get("candidate_id") or "") == selected_candidate_id
                    and str(item.get("window_id") or "")
                    == str(fit.get("window_id") or "")
                ),
                {},
            )
            lock_model_hash = selected_lock.get("model_artifact_hash")
            model_hash = model.get("model_artifact_hash") if model else None
            if lock_model_hash is None and model_hash is None:
                selected_model_artifact_hash = None
            elif (
                not isinstance(lock_model_hash, str)
                or not lock_model_hash
                or model_hash != lock_model_hash
            ):
                raise ResearchSelectionBlocked("f4_candidate_model_identity_mismatch")
            else:
                selected_model_artifact_hash = lock_model_hash
    elif effective_policy is None:
        effective_policy = PortfolioPolicy()
    target = build_target_weights(
        scored[["code", "industry", "score"]].to_dict("records"),
        effective_policy,
    )
    selected = scored.loc[scored["code"].isin(target.weights)].sort_values(
        ["score", "code"], ascending=[False, True]
    )
    positions: list[dict[str, Any]] = []
    for index, row in selected.iterrows():
        ranked = sorted(
            (
                (name, float(contributions[name].loc[index]))
                for name in factors
            ),
            key=lambda item: (-item[1], item[0]),
        )
        top = [
            {
                "factor": name,
                "factor_name": FACTOR_LABELS.get(name, name),
                "direction": "越低越优" if int(directions[name]) < 0 else "越高越优",
                "contribution": round(value, 8),
            }
            for name, value in ranked[:3]
        ]
        positions.append(
            {
                "code": str(row["code"]),
                "name": str(row["name"]),
                "industry_code": str(row["industry"]),
                "industry": str(row["industry_name"]),
                "score": round(float(row["score"]), 8),
                "target_weight": round(float(target.weights[str(row["code"])]), 8),
                "reference_close": float(row["close"]),
                "research_reason": "；".join(
                    f"{item['factor_name']}相对排名贡献 {item['contribution']:.4f}"
                    for item in top
                ),
                "positive_contributors": top,
            }
        )

    industry_weights: dict[str, float] = {}
    for row in positions:
        name = row["industry"]
        industry_weights[name] = round(
            industry_weights.get(name, 0.0) + row["target_weight"], 8
        )
    rejected = f4_status == "f4_rejected"
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "selection_status": (
            "diagnostic_research_portfolio"
            if rejected
            else "f4_research_portfolio"
        ),
        "selection_date": selection_date,
        "generated_at": str(generated_at),
        "generated_from_snapshot_id": snapshot_id,
        "snapshot_data_version": data_version,
        "universe": {
            "active_count": int(factor_snapshot.get("active_count") or 0),
            "data_count": int(factor_snapshot.get("data_count") or 0),
            "eligible_count": int(factor_snapshot.get("eligible_count") or 0),
            "data_coverage": float(factor_snapshot.get("data_coverage") or 0.0),
            "scored_count": int(len(scored)),
            "excluded_reasons": dict(factor_snapshot.get("excluded_reasons") or {}),
        },
        "f4_validation_id": validation_id,
        "f4_gate_status": f4_status,
        "factor_fit_window": str(fit.get("window_id") or ""),
        "factor_fit_end": str(fit.get("fit_end") or ""),
        "factor_fit_factors": list(factors),
        "portfolio_policy": asdict(effective_policy),
        "portfolio_policy_hash": selected_policy_hash or canonical_payload_hash(asdict(effective_policy)),
        "f4_candidate_id": selected_candidate_id or None,
        "f4_candidate_lock_hash": selected_lock_hash or None,
        "f4_factory_run_id": factory_run_id or None,
        "f4_factory_version": factory_version or None,
        "f4_alpha_spec_hash": selected_alpha_spec_hash or None,
        "f4_alpha_fit_hash": selected_alpha_fit_hash or None,
        "f4_model_artifact_hash": selected_model_artifact_hash,
        "positions": positions,
        "position_count": len(positions),
        "invested_weight": round(sum(row["target_weight"] for row in positions), 8),
        "cash_weight": round(float(target.cash_weight), 8),
        "industry_weights": dict(sorted(industry_weights.items())),
        "exclusions": dict(target.exclusions),
        "promotion_state": "research_only",
        "execution_authority": False,
        "not_a_trade_signal": True,
        "source_validation_rejected": rejected,
        "warnings": (
            ["F4组合级门禁未通过，本组合仅用于诊断研究，不得晋升或执行。"]
            if rejected
            else ["F4研究候选仍无执行权限，必须保持研究用途。"]
        ),
    }
    payload["portfolio_id"] = _canonical_id(payload)
    return payload

"""Publish isolated model-health records without trading authority."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime

from quant.adaptive.health import (
    HEALTH_STATES,
    evaluate_health_state,
    model_health_approval_consumed_key,
    model_health_approval_key,
    model_health_history_key,
    model_health_key,
    normalize_approval_ref,
    normalize_model_id,
    runtime_eligible,
    validate_health_record,
    validate_revalidation_approval,
)


MAX_RECENT_WINDOWS = 30
MAX_HEALTH_HISTORY = 30


def _normalize_recent_windows(value: object) -> tuple[list[dict], str | None]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return [
            {
                "hard_failure": True,
                "drift_failed": False,
                "reason": "invalid_recent_windows",
            }
        ], "invalid_recent_windows"

    normalized = []
    invalid = False
    for row in list(value)[-MAX_RECENT_WINDOWS:]:
        if not isinstance(row, Mapping) or not isinstance(
            row.get("hard_failure"), bool
        ) or not isinstance(row.get("drift_failed"), bool):
            normalized.append(
                {
                    "hard_failure": True,
                    "drift_failed": False,
                    "reason": "invalid_recent_windows",
                }
            )
            invalid = True
            continue
        normalized.append(deepcopy(dict(row)))
    if invalid and (
        not normalized
        or normalized[-1].get("reason") != "invalid_recent_windows"
    ):
        normalized.append(
            {
                "hard_failure": True,
                "drift_failed": False,
                "reason": "invalid_recent_windows",
            }
        )
        normalized = normalized[-MAX_RECENT_WINDOWS:]
    return normalized, "invalid_recent_windows" if invalid else None


def _hard_failure_reason(artifact_valid: bool, data_fresh: bool) -> str | None:
    if not artifact_valid and not data_fresh:
        return "artifact_invalid_and_data_stale"
    if not artifact_valid:
        return "artifact_invalid"
    if not data_fresh:
        return "data_stale"
    return None


def _summary(models: Mapping[str, object]) -> dict:
    summary = {"total": 0, **{state: 0 for state in HEALTH_STATES}, "runtime_eligible": 0}
    for record in models.values():
        if not isinstance(record, Mapping):
            continue
        summary["total"] += 1
        state = record.get("health_state")
        if state in HEALTH_STATES:
            summary[state] += 1
        if record.get("runtime_eligible") is True:
            summary["runtime_eligible"] += 1
    return summary


def publish_model_health(
    cache,
    model_id,
    promotion_state,
    recent_windows,
    failure_windows=3,
    artifact_valid=True,
    data_fresh=True,
    artifact_sha256=None,
    revalidation=None,
) -> dict:
    """Evaluate and publish health cache records only."""
    if not callable(getattr(cache, "atomic_update", None)):
        raise RuntimeError("cache.atomic_update is required")
    normalized_model_id = normalize_model_id(model_id)
    normalized_promotion_state = (
        promotion_state.strip() if isinstance(promotion_state, str) else ""
    )
    artifact_ok = artifact_valid is True
    data_ok = data_fresh is True
    normalized_windows, input_reason = _normalize_recent_windows(recent_windows)
    hard_failure_reason = _hard_failure_reason(artifact_ok, data_ok)
    if hard_failure_reason is not None:
        normalized_windows.append(
            {
                "hard_failure": True,
                "drift_failed": False,
                "reason": hard_failure_reason,
            }
        )
        normalized_windows = normalized_windows[-MAX_RECENT_WINDOWS:]

    requested_ref = None
    if isinstance(revalidation, Mapping):
        try:
            requested_ref = normalize_approval_ref(revalidation.get("approval_ref"))
        except ValueError:
            requested_ref = None

    model_key = model_health_key(normalized_model_id)
    history_key = model_health_history_key(normalized_model_id)
    latest_key = "adaptive:model_health:latest"
    approval_key = (
        model_health_approval_key(requested_ref) if requested_ref is not None else None
    )
    consumption_key = (
        model_health_approval_consumed_key(requested_ref)
        if requested_ref is not None
        else None
    )
    keys = [model_key, history_key, latest_key]
    if approval_key is not None:
        keys.extend([approval_key, consumption_key])
    now = datetime.now().astimezone()
    updated_at = now.isoformat(timespec="seconds")

    def updater(snapshot):
        windows = deepcopy(normalized_windows)
        invalid_persisted = False
        persisted = snapshot[model_key]
        if persisted is None:
            previous = "watch"
        else:
            try:
                previous = validate_health_record(persisted)["health_state"]
            except ValueError:
                previous = "quarantined"
                invalid_persisted = True
                windows.append(
                    {
                        "hard_failure": True,
                        "drift_failed": False,
                        "reason": "invalid_persisted_health",
                    }
                )
                windows = windows[-MAX_RECENT_WINDOWS:]

        approval_metadata = None
        replay_detected = (
            consumption_key is not None and snapshot[consumption_key] is not None
        )
        if replay_detected:
            previous = "quarantined"
            windows.append(
                {
                    "hard_failure": True,
                    "drift_failed": False,
                    "reason": "approval_already_consumed",
                }
            )
            windows = windows[-MAX_RECENT_WINDOWS:]
        if (
            approval_key is not None
            and not replay_detected
            and artifact_ok
            and data_ok
        ):
            try:
                approval_metadata = validate_revalidation_approval(
                    snapshot[approval_key],
                    approval_ref=requested_ref,
                    model_id=normalized_model_id,
                    artifact_sha256=artifact_sha256,
                    now=now,
                )
            except ValueError:
                approval_metadata = None

        evaluation = evaluate_health_state(
            previous,
            windows,
            failure_windows,
            revalidation_verified=approval_metadata is not None,
        )
        reason = (
            "invalid_persisted_health"
            if invalid_persisted
            else "approval_already_consumed"
            if replay_detected
            else hard_failure_reason or input_reason or evaluation["reason"]
        )
        accepted_metadata = (
            deepcopy(approval_metadata)
            if evaluation["revalidation_accepted"] and approval_metadata is not None
            else {}
        )
        record = {
            "model_id": normalized_model_id,
            "promotion_state": normalized_promotion_state,
            "health_state": evaluation["health_state"],
            "runtime_eligible": runtime_eligible(
                normalized_promotion_state,
                evaluation["health_state"],
                artifact_valid=artifact_ok,
                data_fresh=data_ok,
            ),
            "reason": reason,
            "trailing_failure_streak": evaluation["trailing_failure_streak"],
            "failure_windows": evaluation["failure_windows"],
            "revalidation_accepted": evaluation["revalidation_accepted"],
            "revalidation": accepted_metadata,
            "artifact_sha256": artifact_sha256 if isinstance(artifact_sha256, str) else "",
            "artifact_valid": artifact_ok,
            "data_fresh": data_ok,
            "updated_at": updated_at,
            "recent_windows": windows,
        }

        old_history = snapshot[history_key]
        history = list(old_history) if isinstance(old_history, list) else []
        history.append(deepcopy(record))
        old_latest = snapshot[latest_key]
        old_models = old_latest.get("models") if isinstance(old_latest, Mapping) else None
        models = deepcopy(dict(old_models)) if isinstance(old_models, Mapping) else {}
        models[normalized_model_id] = deepcopy(record)
        writes = {
            model_key: record,
            history_key: history[-MAX_HEALTH_HISTORY:],
            latest_key: {
                "updated_at": updated_at,
                "models": models,
                "summary": _summary(models),
            },
        }
        if evaluation["revalidation_accepted"] and consumption_key is not None:
            writes[consumption_key] = {
                "approval_ref": approval_metadata["approval_ref"],
                "model_id": normalized_model_id,
                "artifact_sha256": approval_metadata["artifact_sha256"],
                "consumed_at": updated_at,
                "evidence_sha256": approval_metadata["evidence_sha256"],
            }
        return writes

    written = cache.atomic_update(keys, updater)
    return written[model_key]

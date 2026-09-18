from __future__ import annotations

import math
import re
import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone


HEALTH_STATES = ("healthy", "watch", "degraded", "quarantined")
ELIGIBLE_PROMOTION_STATES = (
    "paper_active",
    "production_candidate",
    "approved",
)
_DEFAULT_FAILURE_WINDOWS = 3
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_RESERVED_IDS = {"latest", "history", "approval"}
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_APPROVAL_EVIDENCE_FIELDS = (
    "approval_ref",
    "model_id",
    "artifact_sha256",
    "validation_run_id",
    "approver_id",
    "approved_at",
    "expires_at",
    "retrained",
    "validation_passed",
    "human_approved",
)


def _normalize_token(value: object, *, label: str, max_length: int) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not 1 <= len(value) <= max_length
        or _SAFE_TOKEN.fullmatch(value) is None
        or value.lower() in _RESERVED_IDS
    ):
        raise ValueError(f"invalid {label}")
    return value


def normalize_model_id(value: object) -> str:
    return _normalize_token(value, label="model_id", max_length=96)


def normalize_approval_ref(value: object) -> str:
    return _normalize_token(value, label="approval_ref", max_length=128)


def model_health_key(model_id: object) -> str:
    return f"adaptive:model_health:{normalize_model_id(model_id)}"


def model_health_history_key(model_id: object) -> str:
    return f"adaptive:model_health:history:{normalize_model_id(model_id)}"


def model_health_approval_key(ref: object) -> str:
    return f"adaptive:model_health:approval:{normalize_approval_ref(ref)}"


def model_health_approval_consumed_key(ref: object) -> str:
    return f"adaptive:model_health:approval_consumed:{normalize_approval_ref(ref)}"


def validate_health_record(value: object, *, allow_missing: bool = False) -> dict:
    if value is None and allow_missing:
        return {
            "health_state": "watch",
            "artifact_valid": True,
            "data_fresh": True,
        }
    if not isinstance(value, Mapping):
        raise ValueError("invalid health record")
    if value.get("health_state") not in HEALTH_STATES:
        raise ValueError("invalid health record state")
    if not isinstance(value.get("artifact_valid"), bool) or not isinstance(
        value.get("data_fresh"), bool
    ):
        raise ValueError("invalid health record validity flags")
    return deepcopy(dict(value))


def compute_approval_evidence_sha256(value: Mapping[str, object]) -> str:
    if not isinstance(value, Mapping):
        raise ValueError("approval evidence must be a mapping")
    try:
        payload = {field: value[field] for field in _APPROVAL_EVIDENCE_FIELDS}
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid approval evidence fields") from exc
    return hashlib.sha256(encoded).hexdigest()


def _aware_datetime(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"invalid approval {label}")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid approval {label}") from exc
    if parsed.utcoffset() is None:
        raise ValueError(f"invalid approval {label}")
    return parsed


def validate_revalidation_approval(
    value: object,
    *,
    approval_ref: object,
    model_id: object,
    artifact_sha256: object,
    now: datetime | None = None,
) -> dict:
    expected_ref = normalize_approval_ref(approval_ref)
    expected_model = normalize_model_id(model_id)
    if not isinstance(artifact_sha256, str) or _SHA256.fullmatch(artifact_sha256) is None:
        raise ValueError("invalid approval artifact_sha256")
    if not isinstance(value, Mapping):
        raise ValueError("invalid approval record")
    if normalize_approval_ref(value.get("approval_ref")) != expected_ref:
        raise ValueError("approval_ref mismatch")
    if normalize_model_id(value.get("model_id")) != expected_model:
        raise ValueError("approval model_id mismatch")
    recorded_artifact = value.get("artifact_sha256")
    if (
        not isinstance(recorded_artifact, str)
        or _SHA256.fullmatch(recorded_artifact) is None
        or recorded_artifact != artifact_sha256
    ):
        raise ValueError("approval artifact_sha256 mismatch")
    validation_run_id = _normalize_token(
        value.get("validation_run_id"),
        label="approval validation_run_id",
        max_length=128,
    )
    approver_id = value.get("approver_id")
    if not isinstance(approver_id, str) or not approver_id.strip():
        raise ValueError("invalid approval approver_id")
    approved_at = _aware_datetime(value.get("approved_at"), "approved_at")
    expires_at = _aware_datetime(value.get("expires_at"), "expires_at")
    current = now or datetime.now(timezone.utc)
    if current.utcoffset() is None:
        raise ValueError("approval validation time must be timezone-aware")
    if approved_at > current or expires_at <= current or expires_at <= approved_at:
        raise ValueError("approval is not currently valid")
    if any(
        value.get(field) is not True
        for field in ("retrained", "validation_passed", "human_approved")
    ):
        raise ValueError("approval validation gates failed")
    evidence_sha256 = value.get("evidence_sha256")
    if not isinstance(evidence_sha256, str) or _SHA256.fullmatch(evidence_sha256) is None:
        raise ValueError("invalid approval evidence_sha256")
    expected_hash = compute_approval_evidence_sha256(value)
    if not hmac.compare_digest(evidence_sha256.lower(), expected_hash):
        raise ValueError("approval evidence hash mismatch")
    return {
        "approval_ref": expected_ref,
        "artifact_sha256": recorded_artifact,
        "validation_run_id": validation_run_id,
        "approver_id": approver_id,
        "approved_at": value["approved_at"],
        "expires_at": value["expires_at"],
        "evidence_sha256": evidence_sha256,
    }


def _normalize_failure_windows(value: object) -> int:
    if isinstance(value, bool):
        return _DEFAULT_FAILURE_WINDOWS
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return _DEFAULT_FAILURE_WINDOWS
    if not math.isfinite(number) or not number.is_integer():
        return _DEFAULT_FAILURE_WINDOWS
    return max(1, int(number))


def _result(
    health_state: str,
    reason: str,
    trailing_failure_streak: int,
    failure_windows: int,
    revalidation_accepted: bool = False,
) -> dict:
    return {
        "health_state": health_state,
        "reason": reason,
        "trailing_failure_streak": trailing_failure_streak,
        "failure_windows": failure_windows,
        "revalidation_accepted": revalidation_accepted,
    }


def _valid_window(row: object) -> bool:
    return (
        isinstance(row, Mapping)
        and isinstance(row.get("hard_failure"), bool)
        and isinstance(row.get("drift_failed"), bool)
    )


def evaluate_health_state(
    previous: str,
    recent_windows: Sequence[Mapping[str, object]],
    failure_windows: object,
    revalidation_verified: bool = False,
) -> dict:
    """Evaluate model health without mutating inputs or external state."""
    threshold = _normalize_failure_windows(failure_windows)
    rows = (
        list(recent_windows)
        if isinstance(recent_windows, Sequence)
        and not isinstance(recent_windows, (str, bytes))
        else []
    )
    malformed_windows = not (
        isinstance(recent_windows, Sequence)
        and not isinstance(recent_windows, (str, bytes))
        and all(_valid_window(row) for row in rows)
    )

    trailing_failure_streak = 0
    for row in reversed(rows):
        if _valid_window(row) and row.get("drift_failed") is True:
            trailing_failure_streak += 1
        else:
            break

    latest = rows[-1] if rows and isinstance(rows[-1], Mapping) else None
    if latest is not None and latest.get("hard_failure") is True:
        return _result(
            "quarantined",
            "hard_failure",
            trailing_failure_streak,
            threshold,
        )

    if previous not in HEALTH_STATES:
        return _result(
            "quarantined",
            "invalid_previous_state",
            trailing_failure_streak,
            threshold,
        )

    if malformed_windows:
        state = previous if previous in {"degraded", "quarantined"} else "watch"
        return _result(
            state,
            "invalid_recent_windows",
            trailing_failure_streak,
            threshold,
        )

    if trailing_failure_streak >= threshold:
        state = "quarantined" if previous in {"degraded", "quarantined"} else "degraded"
        reason = (
            "drift_failure_threshold_quarantine"
            if state == "quarantined"
            else "drift_failure_threshold_reached"
        )
        return _result(state, reason, trailing_failure_streak, threshold)

    if trailing_failure_streak:
        state = {
            "healthy": "watch",
            "watch": "watch",
            "degraded": "degraded",
            "quarantined": "quarantined",
        }[previous]
        reason = (
            "manual_revalidation_required"
            if state == "quarantined"
            else "drift_failure_observed"
        )
        return _result(state, reason, trailing_failure_streak, threshold)

    trailing_healthy = 0
    for row in reversed(rows):
        if row.get("hard_failure") is False and row.get("drift_failed") is False:
            trailing_healthy += 1
        else:
            break

    if previous == "quarantined":
        if any(row.get("hard_failure") is True for row in rows):
            return _result("quarantined", "hard_failure", 0, threshold)
        if revalidation_verified is True and trailing_healthy >= 2:
            return _result(
                "watch",
                "manual_revalidation_accepted",
                0,
                threshold,
                revalidation_accepted=True,
            )
        return _result(
            "quarantined",
            "manual_revalidation_required",
            0,
            threshold,
        )
    if previous == "degraded":
        if trailing_healthy:
            return _result("watch", "degraded_recovery_watch", 0, threshold)
        return _result("degraded", "healthy_evidence_required", 0, threshold)
    if previous == "healthy":
        return _result("healthy", "healthy", 0, threshold)

    if trailing_healthy >= 2:
        return _result("healthy", "healthy_windows_confirmed", 0, threshold)
    return _result("watch", "healthy_confirmation_pending", 0, threshold)


def runtime_eligible(
    promotion_state: str,
    health_state: str,
    *,
    artifact_valid: bool = True,
    data_fresh: bool = True,
) -> bool:
    return bool(
        promotion_state in ELIGIBLE_PROMOTION_STATES
        and health_state in HEALTH_STATES
        and health_state != "quarantined"
        and artifact_valid is True
        and data_fresh is True
    )

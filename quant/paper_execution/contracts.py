"""Stable F5 identifiers and state-machine contracts."""

from __future__ import annotations

import hashlib
import json


RUN_STATES = {
    "blocked",
    "prepared",
    "execution_pending",
    "executing",
    "reconciling",
    "completed",
    "completed_with_rejections",
    "halted_unknown",
}

TERMINAL_RUN_STATES = {
    "blocked",
    "completed",
    "completed_with_rejections",
    "halted_unknown",
}

TERMINAL_ORDER_STATES = {
    "filled",
    "rejected",
    "cancelled",
    "partially_filled_cancelled",
}

RUN_TRANSITIONS = {
    "blocked": set(),
    "prepared": {"execution_pending", "executing", "blocked", "halted_unknown"},
    "execution_pending": {"executing", "blocked", "halted_unknown"},
    "executing": {"reconciling", "execution_pending", "halted_unknown"},
    "reconciling": {"completed", "completed_with_rejections", "halted_unknown"},
    "completed": set(),
    "completed_with_rejections": set(),
    "halted_unknown": set(),
}


class InvalidStateTransition(ValueError):
    """Raised when persisted execution state would move illegally."""


def stable_id(prefix: str, *parts: object) -> str:
    """Return a deterministic, namespace-prefixed SHA-256 identifier."""

    canonical = json.dumps(
        parts,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{prefix}_{digest}"


def validate_run_state(state: str) -> None:
    if state not in RUN_STATES:
        raise ValueError(f"unknown_run_state:{state}")


def validate_transition(current: str, new: str) -> None:
    validate_run_state(current)
    validate_run_state(new)
    if new == current:
        return
    if new not in RUN_TRANSITIONS[current]:
        raise InvalidStateTransition(f"invalid_run_transition:{current}->{new}")

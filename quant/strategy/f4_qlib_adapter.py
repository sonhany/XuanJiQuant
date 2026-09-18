"""Research-only, window-scoped Qlib adapter for the F4 v2 candidate factory."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from quant.qlib.workflow_bridge import (
    WindowWorkflowError,
    WindowWorkflowRequest,
    WindowWorkflowResult,
    fit_window_workflow,
)

from .f4_alpha_contracts import F4CandidateV2, build_v2_candidate_registry
from .f4_candidate_factory import canonical_payload_hash
from .walk_forward import F4Window


# One stable public error type is used at both the bridge and strategy boundary.
QlibAlphaUnavailable = WindowWorkflowError


def _verify_preregistered_candidate(candidate: F4CandidateV2) -> None:
    try:
        candidate.validate()
    except (TypeError, ValueError) as exc:
        raise QlibAlphaUnavailable("qlib_candidate_unregistered", str(exc)) from exc
    approved = {
        item.candidate_id: item
        for item in build_v2_candidate_registry()
        if item.family == "qlib"
    }
    if candidate.family != "qlib" or approved.get(candidate.candidate_id) != candidate:
        raise QlibAlphaUnavailable("qlib_candidate_unregistered")


def _segments(window: F4Window) -> dict[str, tuple[str, str]]:
    if (
        not window.train_dates
        or not window.valid_dates
        or not window.test_dates
        or window.train_dates[-1] >= window.valid_dates[0]
        or window.valid_dates[-1] >= window.test_dates[0]
    ):
        raise QlibAlphaUnavailable("qlib_window_segments_invalid")
    return {
        "train": (
            str(window.train_dates[0].date()),
            str(window.train_dates[-1].date()),
        ),
        "valid": (
            str(window.valid_dates[0].date()),
            str(window.valid_dates[-1].date()),
        ),
        "test": (
            str(window.test_dates[0].date()),
            str(window.test_dates[-1].date()),
        ),
    }


def _allowed_segment_dates(
    window: F4Window,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return (
        (
            "valid",
            tuple(str(value.date()) for value in window.valid_dates),
        ),
        (
            "test",
            tuple(str(value.date()) for value in window.test_dates),
        ),
    )


def fit_qlib_window(
    *,
    candidate: F4CandidateV2,
    window: F4Window,
    provider_uri: Path,
    artifact_root: Path,
    runtime: Any | None = None,
    instruments: str = "market",
) -> WindowWorkflowResult:
    """Fit one pre-registered Qlib candidate and predict validation only."""

    _verify_preregistered_candidate(candidate)
    alpha = candidate.alpha_spec
    alpha_spec_hash = canonical_payload_hash(asdict(alpha))
    request = WindowWorkflowRequest(
        candidate_id=candidate.candidate_id,
        window_id=str(window.window_id),
        alpha_spec_hash=alpha_spec_hash,
        provider_uri=Path(provider_uri).resolve(),
        artifact_root=Path(artifact_root),
        handler=alpha.handler,
        model_type=alpha.model_type,
        seed=int(alpha.seed),
        segments=_segments(window),
        minimum_coverage=float(alpha.minimum_coverage),
        allowed_segment_dates=_allowed_segment_dates(window),
        instruments=str(instruments),
    )
    return fit_window_workflow(request, runtime=runtime)


__all__ = [
    "QlibAlphaUnavailable",
    "fit_qlib_window",
]

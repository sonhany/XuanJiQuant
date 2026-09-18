"""Bounded, deterministic and research-only F4 candidate selection."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .f4_contracts import F4Blocked, authority_fields
from .portfolio import PortfolioPolicy


FACTORY_VERSION_V1 = "f4-nested-candidate-factory-v1"
FACTORY_VERSION_V2 = "f4-multi-alpha-candidate-factory-v2"
SUPPORTED_FACTORY_VERSIONS = frozenset({FACTORY_VERSION_V1, FACTORY_VERSION_V2})

# Backwards-compatible alias for the existing six-policy nested factory.
FACTORY_VERSION = FACTORY_VERSION_V1

_SAFE_PATH_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_LOCK_HASH_EXCLUDED_FIELDS = frozenset(
    {"lock_hash", "promotion_state", "execution_authority"}
)
_LOWER_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CandidateUnavailable(ValueError):
    """One candidate is unusable; the remaining registry must continue."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = str(reason_code)
        self.detail = str(detail)
        super().__init__(
            self.reason_code if not self.detail else f"{self.reason_code}: {self.detail}"
        )


@dataclass(frozen=True, slots=True)
class CandidateWindowContext:
    """Serializable evidence binding one candidate to one outer window."""

    window_id: str
    candidate_id: str
    alpha_spec_hash: str
    alpha_fit_path: str
    alpha_fit_hash: str
    model_artifact_path: str | None
    model_artifact_hash: str | None
    validation_score_path: str
    validation_score_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate_schema(self) -> None:
        required_strings = (
            self.window_id,
            self.candidate_id,
            self.alpha_spec_hash,
            self.alpha_fit_path,
            self.alpha_fit_hash,
            self.validation_score_path,
            self.validation_score_hash,
        )
        if any(type(value) is not str or not value.strip() for value in required_strings):
            raise F4Blocked("candidate_window_context_schema_invalid")
        if any(
            not _LOWER_HEX_SHA256.fullmatch(value)
            for value in (
                self.alpha_spec_hash,
                self.alpha_fit_hash,
                self.validation_score_hash,
            )
        ):
            raise F4Blocked("candidate_window_context_schema_invalid")
        if (self.model_artifact_path is None) != (self.model_artifact_hash is None):
            raise F4Blocked("candidate_window_context_schema_invalid")
        if self.model_artifact_path is not None and (
            type(self.model_artifact_path) is not str
            or not self.model_artifact_path.strip()
            or type(self.model_artifact_hash) is not str
            or not _LOWER_HEX_SHA256.fullmatch(self.model_artifact_hash)
        ):
            raise F4Blocked("candidate_window_context_schema_invalid")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "CandidateWindowContext":
        expected = {
            "window_id",
            "candidate_id",
            "alpha_spec_hash",
            "alpha_fit_path",
            "alpha_fit_hash",
            "model_artifact_path",
            "model_artifact_hash",
            "validation_score_path",
            "validation_score_hash",
        }
        if type(payload) is not dict or set(payload) != expected:
            raise F4Blocked("candidate_window_context_schema_invalid")
        context = cls(
            window_id=payload["window_id"],
            candidate_id=payload["candidate_id"],
            alpha_spec_hash=payload["alpha_spec_hash"],
            alpha_fit_path=payload["alpha_fit_path"],
            alpha_fit_hash=payload["alpha_fit_hash"],
            model_artifact_path=payload["model_artifact_path"],
            model_artifact_hash=payload["model_artifact_hash"],
            validation_score_path=payload["validation_score_path"],
            validation_score_hash=payload["validation_score_hash"],
        )
        context.validate_schema()
        return context


def _canonical_hash(value: Mapping[str, Any] | Sequence[Any]) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_payload_hash(value: Mapping[str, Any] | Sequence[Any]) -> str:
    return _canonical_hash(value)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_component(value: Any) -> str:
    component = str(value)
    if (
        not _SAFE_PATH_COMPONENT.fullmatch(component)
        or component in {".", ".."}
        or "/" in component
        or "\\" in component
    ):
        raise F4Blocked("f4_v2_path_component_invalid", component)
    return component


def _safe_child(root: Path, *components: str) -> Path:
    resolved_root = Path(root).resolve()
    target = resolved_root.joinpath(*(_safe_component(value) for value in components)).resolve()
    try:
        target.relative_to(resolved_root)
    except ValueError as exc:
        raise F4Blocked("f4_v2_artifact_path_escape", str(target)) from exc
    return target


def _atomic_json_unique(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(
                dict(payload), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
            ),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_copy_verified(source: Path, target: Path, expected_hash: str) -> str:
    source = Path(source).resolve()
    if not source.is_file() or _file_sha256(source) != expected_hash:
        raise F4Blocked("candidate_window_context_artifact_hash_mismatch")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(
        f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    try:
        with source.open("rb") as reader, temporary.open("xb") as writer:
            shutil.copyfileobj(reader, writer)
            writer.flush()
            os.fsync(writer.fileno())
        if _file_sha256(temporary) != expected_hash:
            raise F4Blocked("candidate_window_context_artifact_copy_failed")
        if target.exists():
            if not target.is_file() or _file_sha256(target) != expected_hash:
                raise F4Blocked("candidate_selection_lock_artifact_identity_collision")
            temporary.unlink()
        else:
            os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return str(target.resolve())


def _load_json(path: Path, reason_code: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        raise F4Blocked(reason_code, str(exc)) from exc
    if not isinstance(payload, dict):
        raise F4Blocked(reason_code)
    return payload


def _candidate_alpha_hash(candidate: Any) -> str:
    return canonical_payload_hash(asdict(candidate.alpha_spec))


def _candidate_policy_hash(candidate: Any) -> str:
    return canonical_payload_hash(asdict(candidate.portfolio_policy))


def _lock_core(lock: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(lock).items()
        if key not in _LOCK_HASH_EXCLUDED_FIELDS
    }


def _verify_alpha_fit_artifact(path: Path, semantic_hash: str) -> str:
    """Return the byte hash after verifying the fit's declared semantic hash."""

    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise F4Blocked("candidate_window_context_artifact_hash_mismatch")
    byte_hash = _file_sha256(resolved)
    if byte_hash == semantic_hash:
        return byte_hash
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        raise F4Blocked("candidate_window_context_artifact_hash_mismatch") from exc
    if not isinstance(payload, dict) or semantic_hash not in {
        payload.get("artifact_hash"),
        payload.get("config_hash"),
        payload.get("alpha_fit_hash"),
    }:
        raise F4Blocked("candidate_window_context_artifact_hash_mismatch")
    return byte_hash


@dataclass(frozen=True, slots=True)
class F4CandidateSpec:
    top_k: int
    rebalance_bars: int
    target_gross_exposure: float
    max_name_weight: float
    max_industry_weight: float = 0.25
    minimum_abs_median_rank_ic: float = 0.02
    minimum_direction_consistency: float = 0.60
    minimum_factors: int = 3
    maximum_factors: int = 10
    lot_size: int = 100
    adv_participation: float = 0.10
    version: str = FACTORY_VERSION

    def payload(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def candidate_id(self) -> str:
        return _canonical_hash(self.payload())

    def to_dict(self) -> dict[str, Any]:
        return {"candidate_id": self.candidate_id, **self.payload(), **authority_fields()}

    def portfolio_policy(self) -> PortfolioPolicy:
        return PortfolioPolicy(
            top_k=self.top_k,
            rebalance_bars=self.rebalance_bars,
            max_name_weight=self.max_name_weight,
            max_industry_weight=self.max_industry_weight,
            lot_size=self.lot_size,
            adv_participation=self.adv_participation,
            target_gross_exposure=self.target_gross_exposure,
            version="nested-window-policy-v1",
        )


def build_candidate_registry() -> tuple[F4CandidateSpec, ...]:
    candidates = []
    for top_k in (5, 10):
        max_name_weight = 0.19 if top_k == 5 else 0.095
        for rebalance_bars in (5, 10, 20):
            candidates.append(
                F4CandidateSpec(
                    top_k=top_k,
                    rebalance_bars=rebalance_bars,
                    target_gross_exposure=0.95,
                    max_name_weight=max_name_weight,
                )
            )
    return tuple(candidates)


def candidate_factory_id(
    input_identity: Mapping[str, Any], candidates: Iterable[Any]
) -> str:
    registry = tuple(candidates)
    versions = {str(candidate.version) for candidate in registry}
    if len(versions) != 1 or not versions.issubset(SUPPORTED_FACTORY_VERSIONS):
        raise ValueError("candidate_factory_version_invalid")
    factory_version = next(iter(versions))
    return _canonical_hash(
        {
            "factory_version": factory_version,
            "input_identity": dict(input_identity),
            "candidate_registry_hash": candidate_registry_hash(registry),
            "registry": [candidate.to_dict() for candidate in registry],
        }
    )


def candidate_registry_hash(candidates: Iterable[Any]) -> str:
    registry = tuple(candidates)
    versions = {str(candidate.version) for candidate in registry}
    if len(versions) != 1 or not versions.issubset(SUPPORTED_FACTORY_VERSIONS):
        raise ValueError("candidate_registry_version_invalid")
    return canonical_payload_hash(
        {
            "factory_version": next(iter(versions)),
            "candidate_ids": [candidate.candidate_id for candidate in registry],
        }
    )


def _validation_key(candidate_id: str, metrics: Mapping[str, Any]) -> tuple[Any, ...]:
    after_cost_excess = float(
        metrics.get("after_cost_excess_return")
        if metrics.get("after_cost_excess_return") is not None
        else metrics.get("excess_return") or 0.0
    )
    return (
        -(1 if after_cost_excess > 0.0 else 0),
        -after_cost_excess,
        -float(metrics.get("sharpe") or 0.0),
        abs(float(metrics.get("max_drawdown") or 0.0)),
        float(metrics.get("turnover") or 0.0),
        candidate_id,
    )


def select_validation_winner(
    candidates: Iterable[Any],
    validation_metrics: Mapping[str, Mapping[str, Any]],
) -> tuple[str | None, list[dict[str, Any]]]:
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    eligible = []
    rows = []
    for candidate_id in sorted(by_id):
        metrics = dict(validation_metrics.get(candidate_id) or {})
        valid = (
            int(metrics.get("constraint_violation_count") or 0) == 0
            and int(metrics.get("future_data_violation_count") or 0) == 0
        )
        row = {
            "candidate_id": candidate_id,
            "eligible": valid,
            "metrics": metrics,
            **authority_fields(),
        }
        rows.append(row)
        if valid:
            eligible.append((_validation_key(candidate_id, metrics), candidate_id))
    eligible.sort()
    winner = eligible[0][1] if eligible else None
    rank_by_id = {candidate_id: rank for rank, (_key, candidate_id) in enumerate(eligible, 1)}
    for row in rows:
        row["validation_rank"] = rank_by_id.get(row["candidate_id"])
        row["selected"] = row["candidate_id"] == winner
    rows.sort(key=lambda row: (row["validation_rank"] is None, row["validation_rank"] or 0, row["candidate_id"]))
    return winner, rows


def _coerce_context(value: Any) -> CandidateWindowContext:
    if isinstance(value, CandidateWindowContext):
        return value
    if isinstance(value, Mapping):
        return CandidateWindowContext.from_mapping(value)
    raise F4Blocked("candidate_window_context_invalid")


def _verify_attempt_context(
    context: CandidateWindowContext,
    *,
    candidate: Any,
    window_id: str,
) -> None:
    context.validate_schema()
    if (
        context.window_id != window_id
        or context.candidate_id != candidate.candidate_id
        or context.alpha_spec_hash != _candidate_alpha_hash(candidate)
    ):
        raise F4Blocked("candidate_window_context_identity_mismatch")
    fit_path = Path(context.alpha_fit_path).resolve()
    validation_path = Path(context.validation_score_path).resolve()
    _verify_alpha_fit_artifact(fit_path, context.alpha_fit_hash)
    if (
        not validation_path.is_file()
        or _file_sha256(validation_path) != context.validation_score_hash
    ):
        raise F4Blocked("candidate_window_context_artifact_hash_mismatch")
    has_model_path = context.model_artifact_path is not None
    has_model_hash = context.model_artifact_hash is not None
    if has_model_path != has_model_hash:
        raise F4Blocked("candidate_window_context_model_identity_invalid")
    if has_model_path:
        model_path = Path(str(context.model_artifact_path)).resolve()
        if (
            not model_path.is_file()
            or _file_sha256(model_path) != context.model_artifact_hash
        ):
            raise F4Blocked("candidate_window_context_artifact_hash_mismatch")


def _stable_artifact_name(prefix: str, source: str) -> str:
    suffix = Path(source).suffix
    if len(suffix) > 12 or not re.fullmatch(r"(?:\.[A-Za-z0-9_-]+)?", suffix):
        suffix = ""
    return f"{prefix}{suffix}"


def _copy_locked_context(
    context: CandidateWindowContext,
    *,
    artifact_root: Path,
    factory_run_id: str,
    window_id: str,
) -> CandidateWindowContext:
    window_root = _safe_child(artifact_root, factory_run_id, window_id)
    fit_target = _safe_child(
        window_root,
        _stable_artifact_name("alpha-fit", context.alpha_fit_path),
    )
    validation_target = _safe_child(
        window_root,
        _stable_artifact_name("validation-score", context.validation_score_path),
    )
    fit_source = Path(context.alpha_fit_path)
    fit_byte_hash = _verify_alpha_fit_artifact(fit_source, context.alpha_fit_hash)
    fit_path = _atomic_copy_verified(fit_source, fit_target, fit_byte_hash)
    validation_path = _atomic_copy_verified(
        Path(context.validation_score_path),
        validation_target,
        context.validation_score_hash,
    )
    model_path: str | None = None
    if context.model_artifact_path is not None:
        model_target = _safe_child(
            window_root,
            _stable_artifact_name("model-artifact", context.model_artifact_path),
        )
        model_path = _atomic_copy_verified(
            Path(context.model_artifact_path),
            model_target,
            str(context.model_artifact_hash),
        )
    return CandidateWindowContext(
        window_id=context.window_id,
        candidate_id=context.candidate_id,
        alpha_spec_hash=context.alpha_spec_hash,
        alpha_fit_path=fit_path,
        alpha_fit_hash=context.alpha_fit_hash,
        model_artifact_path=model_path,
        model_artifact_hash=context.model_artifact_hash,
        validation_score_path=validation_path,
        validation_score_hash=context.validation_score_hash,
    )


def _verify_v2_lock(
    lock: Mapping[str, Any],
    *,
    candidate: Any,
    factory_run_id: str,
    window_id: str,
    lock_root: Path,
    artifact_root: Path,
    registry_hash: str,
    candidate_count: int,
    candidate_ids: frozenset[str],
) -> CandidateWindowContext:
    payload = dict(lock)
    required_exact = {
        "factory_run_id": factory_run_id,
        "window_id": window_id,
        "candidate_id": candidate.candidate_id,
        "candidate_registry_hash": registry_hash,
        "candidate_count": candidate_count,
        "alpha_spec_hash": _candidate_alpha_hash(candidate),
        "portfolio_policy_hash": _candidate_policy_hash(candidate),
        "selection_scope": "current_window_validation_only",
        "test_scope": "locked_winner_only",
        "promotion_state": "research_only",
        "execution_authority": False,
    }
    required_hash_fields = (
        "alpha_fit_hash",
        "alpha_fit_artifact_hash",
        "validation_score_hash",
        "validation_leaderboard_hash",
        "lock_hash",
    )
    if (
        any(payload.get(key) != value for key, value in required_exact.items())
        or any(
            not isinstance(payload.get(key), str)
            or len(str(payload.get(key))) != 64
            for key in required_hash_fields
        )
        or payload.get("lock_hash") != canonical_payload_hash(_lock_core(payload))
    ):
        raise F4Blocked("candidate_selection_lock_integrity_failed")
    if (payload.get("model_artifact_path") is None) != (
        payload.get("model_artifact_hash") is None
    ):
        raise F4Blocked("candidate_selection_lock_integrity_failed")

    resolved_artifact_root = Path(artifact_root).resolve()
    expected_window_root = _safe_child(
        resolved_artifact_root, factory_run_id, window_id
    )
    fit_path = Path(str(payload.get("alpha_fit_path") or "")).resolve()
    validation_path = Path(str(payload.get("validation_score_path") or "")).resolve()
    try:
        fit_path.relative_to(expected_window_root)
        validation_path.relative_to(expected_window_root)
    except ValueError as exc:
        raise F4Blocked("candidate_selection_lock_artifact_path_invalid") from exc
    if (
        not fit_path.is_file()
        or _file_sha256(fit_path) != payload["alpha_fit_artifact_hash"]
    ):
        raise F4Blocked("candidate_selection_lock_fit_hash_mismatch")
    try:
        _verify_alpha_fit_artifact(fit_path, str(payload["alpha_fit_hash"]))
    except F4Blocked as exc:
        raise F4Blocked("candidate_selection_lock_fit_hash_mismatch") from exc
    if (
        not validation_path.is_file()
        or _file_sha256(validation_path) != payload["validation_score_hash"]
    ):
        raise F4Blocked("candidate_selection_lock_validation_hash_mismatch")
    model_path_value = payload.get("model_artifact_path")
    if model_path_value is not None:
        model_path = Path(str(model_path_value)).resolve()
        try:
            model_path.relative_to(expected_window_root)
        except ValueError as exc:
            raise F4Blocked("candidate_selection_lock_artifact_path_invalid") from exc
        if (
            not model_path.is_file()
            or _file_sha256(model_path) != payload["model_artifact_hash"]
        ):
            raise F4Blocked("candidate_selection_lock_model_hash_mismatch")

    leaderboard_path = Path(
        str(payload.get("validation_leaderboard_path") or "")
    ).resolve()
    expected_lock_root = Path(lock_root).resolve()
    try:
        leaderboard_path.relative_to(expected_lock_root)
    except ValueError as exc:
        raise F4Blocked("candidate_selection_lock_leaderboard_path_invalid") from exc
    if (
        not leaderboard_path.is_file()
        or _file_sha256(leaderboard_path) != payload["validation_leaderboard_hash"]
    ):
        raise F4Blocked("candidate_selection_lock_leaderboard_hash_mismatch")
    leaderboard = _load_json(
        leaderboard_path, "candidate_selection_lock_leaderboard_invalid"
    )
    selected = [
        row
        for row in leaderboard.get("candidates") or []
        if row.get("selected") is True
    ]
    leaderboard_ids = {
        str(row.get("candidate_id") or "")
        for row in leaderboard.get("candidates") or []
    }
    if (
        leaderboard.get("factory_run_id") != factory_run_id
        or leaderboard.get("window_id") != window_id
        or leaderboard.get("candidate_registry_hash") != registry_hash
        or leaderboard.get("candidate_count") != candidate_count
        or leaderboard_ids != candidate_ids
        or len(leaderboard.get("candidates") or []) != candidate_count
        or len(selected) != 1
        or selected[0].get("candidate_id") != candidate.candidate_id
    ):
        raise F4Blocked("candidate_selection_lock_leaderboard_invalid")
    return CandidateWindowContext(
        window_id=window_id,
        candidate_id=candidate.candidate_id,
        alpha_spec_hash=str(payload["alpha_spec_hash"]),
        alpha_fit_path=str(fit_path),
        alpha_fit_hash=str(payload["alpha_fit_hash"]),
        model_artifact_path=(
            str(Path(str(model_path_value)).resolve())
            if model_path_value is not None
            else None
        ),
        model_artifact_hash=payload.get("model_artifact_hash"),
        validation_score_path=str(validation_path),
        validation_score_hash=str(payload["validation_score_hash"]),
    )


def run_v2_nested_window(
    *,
    factory_run_id: str,
    window: Any,
    candidates: Iterable[Any],
    fit_runner: Callable[[Any], CandidateWindowContext | Mapping[str, Any]],
    validation_runner: Callable[
        [Any, CandidateWindowContext], Mapping[str, Any]
    ],
    test_runner: Callable[
        [Any, CandidateWindowContext, Mapping[str, Any]], Mapping[str, Any]
    ],
    stable_lock_root: Path | str,
    stable_artifact_root: Path | str,
    fit_batch_runner: Callable[
        [tuple[Any, ...]],
        Mapping[
            str,
            CandidateWindowContext | Mapping[str, Any] | CandidateUnavailable,
        ],
    ]
    | None = None,
) -> dict[str, Any]:
    """Select with current-window validation, persist a lock, then test one winner."""

    safe_factory_run_id = _safe_component(factory_run_id)
    window_id = _safe_component(getattr(window, "window_id", ""))
    registry = tuple(candidates)
    if not registry:
        raise F4Blocked("candidate_registry_empty")
    by_id: dict[str, Any] = {}
    for candidate in registry:
        candidate.validate()
        if candidate.candidate_id in by_id:
            raise F4Blocked("candidate_registry_duplicate")
        by_id[candidate.candidate_id] = candidate
    registry_hash = candidate_registry_hash(registry)
    candidate_ids = frozenset(by_id)
    candidate_count = len(registry)

    lock_root = Path(stable_lock_root).resolve()
    artifact_root = Path(stable_artifact_root).resolve()
    lock_path = _safe_child(lock_root, f"{window_id}.json")
    if lock_path.is_file():
        lock = _load_json(lock_path, "candidate_selection_lock_integrity_failed")
        if (
            lock.get("candidate_registry_hash") != registry_hash
            or lock.get("candidate_count") != candidate_count
        ):
            raise F4Blocked("candidate_selection_lock_registry_mismatch")
        if (
            lock.get("promotion_state") != "research_only"
            or lock.get("execution_authority") is not False
            or not isinstance(lock.get("lock_hash"), str)
            or len(str(lock.get("lock_hash"))) != 64
            or lock.get("lock_hash") != canonical_payload_hash(_lock_core(lock))
        ):
            raise F4Blocked("candidate_selection_lock_integrity_failed")
        candidate_id = str(lock.get("candidate_id") or "")
        candidate = by_id.get(candidate_id)
        if candidate is None:
            raise F4Blocked("candidate_selection_lock_candidate_invalid")
        locked_context = _verify_v2_lock(
            lock,
            candidate=candidate,
            factory_run_id=safe_factory_run_id,
            window_id=window_id,
            lock_root=lock_root,
            artifact_root=artifact_root,
            registry_hash=registry_hash,
            candidate_count=candidate_count,
            candidate_ids=candidate_ids,
        )
        test_metrics = dict(test_runner(candidate, locked_context, lock))
        return {
            "factory_version": FACTORY_VERSION_V2,
            "factory_run_id": safe_factory_run_id,
            "window_id": window_id,
            "window_status": "completed",
            "selection_lock": lock,
            "validation_leaderboard": _load_json(
                Path(lock["validation_leaderboard_path"]),
                "candidate_selection_lock_leaderboard_invalid",
            ),
            "test_metrics": test_metrics,
            "lock_recovered": True,
            **authority_fields(),
        }

    attempt_root = _safe_child(
        artifact_root.parent, "attempts", safe_factory_run_id, window_id
    )
    contexts: dict[str, CandidateWindowContext] = {}
    validation_metrics: dict[str, dict[str, Any]] = {}
    unavailable: dict[str, str] = {}
    rule_candidates = tuple(
        candidate for candidate in registry if candidate.family != "qlib"
    )
    if any(candidate.family == "ensemble" for candidate in registry):
        if fit_batch_runner is None:
            raise F4Blocked("ensemble_batch_context_required")
        batch_values = dict(fit_batch_runner(rule_candidates))
        if set(batch_values) != {
            candidate.candidate_id for candidate in rule_candidates
        }:
            raise F4Blocked("ensemble_batch_context_incomplete")
    else:
        batch_values = (
            dict(fit_batch_runner(rule_candidates))
            if fit_batch_runner is not None
            else {}
        )

    # All training fits complete before any validation metric is observed.
    for candidate in registry:
        try:
            raw_context = (
                batch_values[candidate.candidate_id]
                if candidate.candidate_id in batch_values
                else fit_runner(candidate)
            )
            if isinstance(raw_context, CandidateUnavailable):
                unavailable[candidate.candidate_id] = raw_context.reason_code
                continue
            context = _coerce_context(raw_context)
            _verify_attempt_context(
                context, candidate=candidate, window_id=window_id
            )
            _atomic_json_unique(
                _safe_child(attempt_root, f"{candidate.candidate_id}.context.json"),
                context.to_dict(),
            )
            contexts[candidate.candidate_id] = context
        except CandidateUnavailable as exc:
            unavailable[candidate.candidate_id] = exc.reason_code

    for candidate in registry:
        context = contexts.get(candidate.candidate_id)
        if context is None:
            continue
        try:
            validation_metrics[candidate.candidate_id] = dict(
                validation_runner(candidate, context)
            )
        except CandidateUnavailable as exc:
            unavailable[candidate.candidate_id] = exc.reason_code
            contexts.pop(candidate.candidate_id, None)

    winner_id, leaderboard_rows = select_validation_winner(
        (candidate for candidate in registry if candidate.candidate_id in contexts),
        validation_metrics,
    )
    for candidate in registry:
        if candidate.candidate_id in unavailable:
            leaderboard_rows.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "eligible": False,
                    "selected": False,
                    "validation_rank": None,
                    "metrics": {},
                    "reason_code": unavailable[candidate.candidate_id],
                    **authority_fields(),
                }
            )
    leaderboard_rows.sort(
        key=lambda row: (
            row.get("validation_rank") is None,
            row.get("validation_rank") or 0,
            row["candidate_id"],
        )
    )
    leaderboard = {
        "factory_run_id": safe_factory_run_id,
        "window_id": window_id,
        "candidate_registry_hash": registry_hash,
        "candidate_count": candidate_count,
        "candidates": leaderboard_rows,
        **authority_fields(),
    }
    if winner_id is None:
        return {
            "factory_version": FACTORY_VERSION_V2,
            "factory_run_id": safe_factory_run_id,
            "window_id": window_id,
            "window_status": "candidate_validation_exhausted",
            "selection_lock": None,
            "validation_leaderboard": leaderboard,
            "test_metrics": None,
            "lock_recovered": False,
            **authority_fields(),
        }
    winner = by_id[winner_id]
    winner_context = _copy_locked_context(
        contexts[winner_id],
        artifact_root=artifact_root,
        factory_run_id=safe_factory_run_id,
        window_id=window_id,
    )
    leaderboard_path = _safe_child(lock_root, f"{window_id}.leaderboard.json")
    _atomic_json_unique(leaderboard_path, leaderboard)
    leaderboard_hash = _file_sha256(leaderboard_path)
    lock_core = {
        "factory_run_id": safe_factory_run_id,
        "window_id": window_id,
        "candidate_id": winner_id,
        "candidate_registry_hash": registry_hash,
        "candidate_count": candidate_count,
        "alpha_spec_hash": winner_context.alpha_spec_hash,
        "alpha_fit_path": winner_context.alpha_fit_path,
        "alpha_fit_hash": winner_context.alpha_fit_hash,
        "alpha_fit_artifact_hash": _file_sha256(
            Path(winner_context.alpha_fit_path)
        ),
        "model_artifact_path": winner_context.model_artifact_path,
        "model_artifact_hash": winner_context.model_artifact_hash,
        "validation_score_path": winner_context.validation_score_path,
        "validation_score_hash": winner_context.validation_score_hash,
        "portfolio_policy_hash": _candidate_policy_hash(winner),
        "validation_leaderboard_path": str(leaderboard_path.resolve()),
        "validation_leaderboard_hash": leaderboard_hash,
        "selection_scope": "current_window_validation_only",
        "test_scope": "locked_winner_only",
    }
    lock = {
        **lock_core,
        "lock_hash": canonical_payload_hash(lock_core),
        **authority_fields(),
    }
    _atomic_json_unique(lock_path, lock)
    persisted = _load_json(lock_path, "candidate_selection_lock_integrity_failed")
    locked_context = _verify_v2_lock(
        persisted,
        candidate=winner,
        factory_run_id=safe_factory_run_id,
        window_id=window_id,
        lock_root=lock_root,
        artifact_root=artifact_root,
        registry_hash=registry_hash,
        candidate_count=candidate_count,
        candidate_ids=candidate_ids,
    )
    test_metrics = dict(test_runner(winner, locked_context, persisted))
    return {
        "factory_version": FACTORY_VERSION_V2,
        "factory_run_id": safe_factory_run_id,
        "window_id": window_id,
        "window_status": "completed",
        "selection_lock": persisted,
        "validation_leaderboard": leaderboard,
        "test_metrics": test_metrics,
        "lock_recovered": False,
        **authority_fields(),
    }


def run_nested_candidate_selection(
    window_ids: Iterable[str],
    candidates: Iterable[F4CandidateSpec],
    *,
    validation_runner: Callable[[str, F4CandidateSpec], Mapping[str, Any]],
    test_runner: Callable[[str, F4CandidateSpec], Mapping[str, Any]],
    lock_writer: Callable[[list[dict[str, Any]]], None],
    existing_locks: Mapping[str, Mapping[str, Any]] | None = None,
    lock_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    registry = tuple(candidates)
    by_id = {candidate.candidate_id: candidate for candidate in registry}
    leaderboards: list[dict[str, Any]] = []
    locks: list[dict[str, Any]] = []
    test_metrics: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    recovered = dict(existing_locks or {})
    for raw_window_id in window_ids:
        window_id = str(raw_window_id)
        existing = dict(recovered.get(window_id) or {})
        if existing:
            winner_id = str(existing.get("candidate_id") or "")
            if winner_id not in by_id:
                raise ValueError("candidate_selection_lock_candidate_invalid")
            recovered_leaderboard = list(existing.get("validation_leaderboard") or [])
            if not recovered_leaderboard:
                raise ValueError("candidate_selection_lock_validation_missing")
            leaderboards.append(
                {
                    "window_id": window_id,
                    "candidates": recovered_leaderboard,
                    "lock_recovered": True,
                    **authority_fields(),
                }
            )
            locks.append(existing)
            results = dict(test_runner(window_id, by_id[winner_id]))
            test_metrics.append(
                {
                    "window_id": window_id,
                    "candidate_id": winner_id,
                    "metrics": results,
                    "lock_recovered": True,
                    **authority_fields(),
                }
            )
            continue
        validation = {
            candidate.candidate_id: dict(validation_runner(window_id, candidate))
            for candidate in registry
        }
        winner_id, leaderboard = select_validation_winner(registry, validation)
        leaderboards.append(
            {"window_id": window_id, "candidates": leaderboard, **authority_fields()}
        )
        if winner_id is None:
            rejected.append(
                {
                    "window_id": window_id,
                    "reason_code": "candidate_validation_exhausted",
                }
            )
            continue
        lock_core = {
            **dict(lock_identity or {}),
            "window_id": window_id,
            "candidate_id": winner_id,
            "selection_scope": "current_window_validation_only",
            "validation_leaderboard": leaderboard,
        }
        lock = {
            **lock_core,
            "lock_hash": _canonical_hash(lock_core),
            **authority_fields(),
        }
        locks.append(lock)
        lock_writer(list(locks))
        results = dict(test_runner(window_id, by_id[winner_id]))
        test_metrics.append(
            {
                "window_id": window_id,
                "candidate_id": winner_id,
                "metrics": results,
                **authority_fields(),
            }
        )
    return {
        "factory_version": FACTORY_VERSION,
        "candidate_factory_status": "exhausted" if rejected else "completed",
        "registry": [candidate.to_dict() for candidate in registry],
        "validation_leaderboards": leaderboards,
        "selection_locks": locks,
        "test_metrics": test_metrics,
        "rejected_windows": rejected,
        **authority_fields(),
    }

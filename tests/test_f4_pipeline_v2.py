from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from quant.strategy.f4_alpha_contracts import build_v2_candidate_registry
from quant.strategy.f4_candidate_factory import (
    CandidateUnavailable,
    CandidateWindowContext,
    candidate_factory_id,
    candidate_registry_hash,
    run_v2_nested_window,
)
from quant.strategy.f4_contracts import F4Blocked
from quant.strategy.walk_forward import F4Window


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _window(window_id: str = "wf-01") -> F4Window:
    dates = pd.bdate_range("2024-01-02", periods=12)
    return F4Window(
        window_id=window_id,
        train_dates=tuple(dates[:5]),
        valid_dates=tuple(dates[6:8]),
        test_dates=tuple(dates[9:11]),
        purge_bars=1,
        embargo_bars=1,
    )


def _metrics(excess: float) -> dict[str, float | int]:
    return {
        "after_cost_excess_return": excess,
        "excess_return": excess,
        "sharpe": 1.0 + excess,
        "max_drawdown": -0.10,
        "turnover": 0.5,
        "constraint_violation_count": 0,
        "future_data_violation_count": 0,
    }


def _context_writer(tmp_path: Path, *, with_model: bool = False):
    def write(candidate):
        root = tmp_path / "attempts" / candidate.alpha_spec.alpha_id
        root.mkdir(parents=True, exist_ok=True)
        fit_path = root / "fit.json"
        fit_path.write_text(
            json.dumps(
                {
                    "candidate_id": candidate.candidate_id,
                    "alpha_id": candidate.alpha_spec.alpha_id,
                    "window_id": "wf-01",
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        validation_path = root / "validation.csv"
        validation_path.write_text("code,score\nSH600000,1.0\n", encoding="utf-8")
        model_path = None
        model_hash = None
        if with_model:
            model_path = root / "model.bin"
            model_path.write_bytes(f"model:{candidate.candidate_id}".encode("ascii"))
            model_hash = _sha256(model_path)
        return CandidateWindowContext(
            window_id="wf-01",
            candidate_id=candidate.candidate_id,
            alpha_spec_hash=hashlib.sha256(
                json.dumps(
                    candidate.to_dict()["alpha_spec"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            alpha_fit_path=str(fit_path),
            alpha_fit_hash=_sha256(fit_path),
            model_artifact_path=str(model_path) if model_path else None,
            model_artifact_hash=model_hash,
            validation_score_path=str(validation_path),
            validation_score_hash=_sha256(validation_path),
        )

    return write


def _run(tmp_path: Path, *, candidates=None, test_runner=None, with_model=False):
    selected = tuple(candidates or build_v2_candidate_registry()[:3])
    return run_v2_nested_window(
        factory_run_id="factory-run-1",
        window=_window(),
        candidates=selected,
        fit_runner=_context_writer(tmp_path, with_model=with_model),
        validation_runner=lambda candidate, _fit: _metrics(
            {"M1": 0.01, "M2": 0.03, "M3": 0.02}.get(
                candidate.alpha_spec.alpha_id, 0.04
            )
        ),
        test_runner=test_runner
        or (lambda candidate, _fit, _lock: {"candidate_id": candidate.candidate_id}),
        stable_lock_root=tmp_path / "locks",
        stable_artifact_root=tmp_path / "locked-artifacts",
    )


def test_v2_pipeline_validates_all_candidates_but_tests_only_locked_winner(tmp_path):
    candidates = build_v2_candidate_registry()[:3]
    events: list[tuple[str, str]] = []

    def fit(candidate):
        events.append(("fit", candidate.candidate_id))
        return _context_writer(tmp_path)(candidate)

    result = run_v2_nested_window(
        factory_run_id="factory-run-1",
        window=_window(),
        candidates=candidates,
        fit_runner=fit,
        validation_runner=lambda candidate, _fit: events.append(
            ("valid", candidate.candidate_id)
        )
        or _metrics(0.03 if candidate.alpha_spec.alpha_id == "M2" else 0.01),
        test_runner=lambda candidate, _fit, _lock: events.append(
            ("test", candidate.candidate_id)
        )
        or _metrics(0.02),
        stable_lock_root=tmp_path / "locks",
        stable_artifact_root=tmp_path / "locked-artifacts",
    )

    winner = result["selection_lock"]["candidate_id"]
    assert [event for event in events if event[0] == "fit"] == [
        ("fit", candidate.candidate_id) for candidate in candidates
    ]
    assert [event for event in events if event[0] == "valid"] == [
        ("valid", candidate.candidate_id) for candidate in candidates
    ]
    assert [event[0] for event in events[: len(candidates) * 2]] == [
        *(["fit"] * len(candidates)),
        *(["valid"] * len(candidates)),
    ]
    assert [event for event in events if event[0] == "test"] == [("test", winner)]
    assert (tmp_path / "locks" / "wf-01.json").is_file()
    assert result["selection_lock"]["promotion_state"] == "research_only"
    assert result["selection_lock"]["execution_authority"] is False


def test_crash_after_lock_reuses_winner_without_refit_or_revalidation(tmp_path):
    with pytest.raises(RuntimeError, match="test crashed"):
        _run(
            tmp_path,
            test_runner=lambda *_args: (_ for _ in ()).throw(RuntimeError("test crashed")),
        )
    assert (tmp_path / "locks" / "wf-01.json").is_file()

    calls: list[str] = []
    result = run_v2_nested_window(
        factory_run_id="factory-run-1",
        window=_window(),
        candidates=build_v2_candidate_registry()[:3],
        fit_runner=lambda *_args: (_ for _ in ()).throw(AssertionError("fit reran")),
        validation_runner=lambda *_args: (_ for _ in ()).throw(
            AssertionError("validation reran")
        ),
        test_runner=lambda candidate, _fit, _lock: calls.append(candidate.candidate_id)
        or _metrics(0.02),
        stable_lock_root=tmp_path / "locks",
        stable_artifact_root=tmp_path / "locked-artifacts",
    )

    assert calls == [result["selection_lock"]["candidate_id"]]
    assert result["lock_recovered"] is True


def test_later_validation_cannot_change_an_existing_window_lock(tmp_path):
    first = _run(tmp_path)
    second = run_v2_nested_window(
        factory_run_id="factory-run-1",
        window=_window(),
        candidates=build_v2_candidate_registry()[:3],
        fit_runner=lambda *_args: (_ for _ in ()).throw(AssertionError("fit reran")),
        validation_runner=lambda *_args: _metrics(-1000.0),
        test_runner=lambda *_args: _metrics(0.0),
        stable_lock_root=tmp_path / "locks",
        stable_artifact_root=tmp_path / "locked-artifacts",
    )
    assert first["selection_lock"] == second["selection_lock"]


def test_tampered_locked_fit_blocks_test_access(tmp_path):
    first = _run(tmp_path)
    Path(first["selection_lock"]["alpha_fit_path"]).write_text(
        "tampered", encoding="utf-8"
    )
    with pytest.raises(F4Blocked, match="candidate_selection_lock_fit_hash_mismatch"):
        _run(tmp_path)


def test_tampered_locked_model_blocks_test_access(tmp_path):
    qlib = tuple(
        candidate
        for candidate in build_v2_candidate_registry()
        if candidate.alpha_spec.alpha_id == "Q1"
    )
    first = _run(tmp_path, candidates=qlib, with_model=True)
    Path(first["selection_lock"]["model_artifact_path"]).write_bytes(b"tampered")
    with pytest.raises(F4Blocked, match="candidate_selection_lock_model_hash_mismatch"):
        _run(tmp_path, candidates=qlib, with_model=True)


def test_tampered_validation_leaderboard_blocks_test_access(tmp_path):
    first = _run(tmp_path)
    Path(first["selection_lock"]["validation_leaderboard_path"]).write_text(
        "{}", encoding="utf-8"
    )
    with pytest.raises(
        F4Blocked, match="candidate_selection_lock_leaderboard_hash_mismatch"
    ):
        _run(tmp_path)


def test_tampered_lock_hash_blocks_test_access(tmp_path):
    _run(tmp_path)
    lock_path = tmp_path / "locks" / "wf-01.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["candidate_id"] = "forged"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    with pytest.raises(F4Blocked, match="candidate_selection_lock_integrity_failed"):
        _run(tmp_path)


def test_atomic_writes_leave_no_temporary_files(tmp_path):
    _run(tmp_path)
    assert not [path for path in tmp_path.rglob("*") if ".tmp" in path.name]


@pytest.mark.parametrize(
    ("factory_run_id", "window_id"),
    [("../escape", "wf-01"), ("factory-run-1", "../escape")],
)
def test_stable_paths_reject_escape_components(tmp_path, factory_run_id, window_id):
    with pytest.raises(F4Blocked, match="f4_v2_path_component_invalid"):
        run_v2_nested_window(
            factory_run_id=factory_run_id,
            window=_window(window_id),
            candidates=build_v2_candidate_registry()[:1],
            fit_runner=_context_writer(tmp_path),
            validation_runner=lambda *_args: _metrics(0.01),
            test_runner=lambda *_args: _metrics(0.01),
            stable_lock_root=tmp_path / "locks",
            stable_artifact_root=tmp_path / "locked-artifacts",
        )
    assert not (tmp_path.parent / "escape.json").exists()


def test_context_rejects_mismatched_candidate_identity(tmp_path):
    candidates = build_v2_candidate_registry()[:2]
    real_writer = _context_writer(tmp_path)

    def mismatched(candidate):
        context = real_writer(candidate)
        if candidate == candidates[0]:
            return replace(context, candidate_id=candidates[1].candidate_id)
        return context

    with pytest.raises(F4Blocked, match="candidate_window_context_identity_mismatch"):
        run_v2_nested_window(
            factory_run_id="factory-run-1",
            window=_window(),
            candidates=candidates,
            fit_runner=mismatched,
            validation_runner=lambda *_args: _metrics(0.01),
            test_runner=lambda *_args: _metrics(0.01),
            stable_lock_root=tmp_path / "locks",
            stable_artifact_root=tmp_path / "locked-artifacts",
        )


def test_ensemble_candidates_require_one_shared_batch_fit_context(tmp_path):
    registry = build_v2_candidate_registry()
    candidates = (
        next(item for item in registry if item.alpha_spec.alpha_id == "M1"),
        next(item for item in registry if item.alpha_spec.alpha_id == "E1"),
    )
    calls = []

    def batch_fit(requested):
        calls.append(tuple(item.alpha_spec.alpha_id for item in requested))
        writer = _context_writer(tmp_path)
        return {candidate.candidate_id: writer(candidate) for candidate in requested}

    run_v2_nested_window(
        factory_run_id="factory-run-1",
        window=_window(),
        candidates=candidates,
        fit_runner=lambda *_args: (_ for _ in ()).throw(
            AssertionError("rule candidate bypassed shared batch context")
        ),
        fit_batch_runner=batch_fit,
        validation_runner=lambda *_args: _metrics(0.01),
        test_runner=lambda *_args: _metrics(0.01),
        stable_lock_root=tmp_path / "locks",
        stable_artifact_root=tmp_path / "locked-artifacts",
    )

    assert calls == [("M1", "E1")]


def test_v2_factory_and_lock_bind_the_complete_ordered_registry(tmp_path):
    candidates = build_v2_candidate_registry()[:3]
    result = _run(tmp_path, candidates=candidates)
    expected_hash = candidate_registry_hash(candidates)

    assert result["selection_lock"]["candidate_registry_hash"] == expected_hash
    assert result["selection_lock"]["candidate_count"] == 3
    assert result["validation_leaderboard"]["candidate_registry_hash"] == expected_hash
    assert result["validation_leaderboard"]["candidate_count"] == 3
    assert {
        row["candidate_id"]
        for row in result["validation_leaderboard"]["candidates"]
    } == {candidate.candidate_id for candidate in candidates}
    assert candidate_factory_id({"snapshot": "v2"}, candidates) != candidate_factory_id(
        {"snapshot": "v2"}, candidates[:2]
    )


def test_recovery_rejects_same_factory_id_with_nonwinner_removed(tmp_path):
    candidates = build_v2_candidate_registry()[:3]
    first = _run(tmp_path, candidates=candidates)
    winner = first["selection_lock"]["candidate_id"]
    reduced = tuple(
        candidate
        for candidate in candidates
        if candidate.candidate_id == winner or candidate == candidates[0]
    )
    assert {candidate.candidate_id for candidate in reduced} != {
        candidate.candidate_id for candidate in candidates
    }

    with pytest.raises(F4Blocked, match="candidate_selection_lock_registry_mismatch"):
        _run(tmp_path, candidates=reduced)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value | {"unknown": "field"},
        lambda value: {key: item for key, item in value.items() if key != "window_id"},
        lambda value: value | {"candidate_id": 123},
        lambda value: value | {"model_artifact_path": "model.pkl"},
        lambda value: value | {"alpha_fit_hash": "A" * 64},
        lambda value: value | {"validation_score_hash": "abc"},
    ],
)
def test_candidate_window_context_mapping_requires_exact_typed_schema(tmp_path, mutate):
    candidate = build_v2_candidate_registry()[0]
    payload = _context_writer(tmp_path)(candidate).to_dict()

    with pytest.raises(F4Blocked, match="candidate_window_context_schema_invalid"):
        CandidateWindowContext.from_mapping(mutate(payload))


def test_partial_fixed_and_ensemble_failures_do_not_abort_other_candidates(tmp_path):
    registry = build_v2_candidate_registry()
    candidates = tuple(
        next(item for item in registry if item.alpha_spec.alpha_id == alpha_id)
        for alpha_id in ("M1", "M2", "E1", "E2")
    )
    writer = _context_writer(tmp_path)
    test_calls = []

    def batch_fit(requested):
        return {
            candidate.candidate_id: (
                CandidateUnavailable(
                    "alpha_fixed_unavailable"
                    if candidate.alpha_spec.alpha_id == "M1"
                    else "alpha_ensemble_unavailable"
                )
                if candidate.alpha_spec.alpha_id in {"M1", "E1"}
                else writer(candidate)
            )
            for candidate in requested
        }

    result = run_v2_nested_window(
        factory_run_id="factory-run-1",
        window=_window(),
        candidates=candidates,
        fit_runner=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected")),
        fit_batch_runner=batch_fit,
        validation_runner=lambda candidate, _context: _metrics(
            0.02 if candidate.alpha_spec.alpha_id == "E2" else 0.01
        ),
        test_runner=lambda candidate, *_args: test_calls.append(
            candidate.alpha_spec.alpha_id
        )
        or _metrics(0.01),
        stable_lock_root=tmp_path / "locks",
        stable_artifact_root=tmp_path / "locked-artifacts",
    )

    by_id = {
        row["candidate_id"]: row for row in result["validation_leaderboard"]["candidates"]
    }
    assert by_id[candidates[0].candidate_id]["reason_code"] == "alpha_fixed_unavailable"
    assert by_id[candidates[2].candidate_id]["reason_code"] == "alpha_ensemble_unavailable"
    assert test_calls == ["E2"]


def test_all_unavailable_candidates_return_complete_leaderboard_without_test_access(
    tmp_path,
):
    candidates = tuple(build_v2_candidate_registry()[:3])
    writer = _context_writer(tmp_path)
    test_calls = []

    result = run_v2_nested_window(
        factory_run_id="factory-run-1",
        window=_window(),
        candidates=candidates,
        fit_runner=writer,
        validation_runner=lambda *_args: (_ for _ in ()).throw(
            CandidateUnavailable("candidate_score_identity_invalid")
        ),
        test_runner=lambda *_args: test_calls.append(True),
        stable_lock_root=tmp_path / "locks",
        stable_artifact_root=tmp_path / "locked-artifacts",
    )

    assert result["window_status"] == "candidate_validation_exhausted"
    assert result["selection_lock"] is None
    assert result["test_metrics"] is None
    assert test_calls == []
    leaderboard = result["validation_leaderboard"]
    assert leaderboard["candidate_count"] == len(candidates)
    assert {row["candidate_id"] for row in leaderboard["candidates"]} == {
        candidate.candidate_id for candidate in candidates
    }
    assert {
        row["reason_code"] for row in leaderboard["candidates"]
    } == {"candidate_score_identity_invalid"}


def test_bad_qlib_validation_scores_mark_only_qlib_unavailable(tmp_path):
    from quant.strategy.f4_real_pipeline import _score_file_loader

    registry = build_v2_candidate_registry()
    fixed = next(item for item in registry if item.alpha_spec.alpha_id == "M1")
    qlib = next(item for item in registry if item.alpha_spec.alpha_id == "Q1")
    writer = _context_writer(tmp_path)
    fixed_context = writer(fixed)
    qlib_context = writer(qlib)
    bad_path = Path(qlib_context.validation_score_path)
    bad_path.write_text(
        "date,code,score\n2024-01-10,SH600000,nan\n", encoding="utf-8"
    )
    qlib_context = replace(
        qlib_context,
        validation_score_hash=_sha256(bad_path),
    )
    panel = pd.DataFrame(
        {
            "date": [pd.Timestamp("2024-01-10")],
            "instrument": ["SH600000"],
            "industry": ["I1"],
        }
    )
    tested = []

    def validate(candidate, context):
        if candidate.family == "qlib":
            loader = _score_file_loader(
                Path(context.validation_score_path), panel, minimum_coverage=0.95
            )
            loader(pd.Timestamp("2024-01-10"))
        return _metrics(0.01)

    result = run_v2_nested_window(
        factory_run_id="factory-run-1",
        window=_window(),
        candidates=(fixed, qlib),
        fit_runner=lambda candidate: (
            fixed_context if candidate == fixed else qlib_context
        ),
        validation_runner=validate,
        test_runner=lambda candidate, *_args: tested.append(candidate.alpha_spec.alpha_id)
        or _metrics(0.01),
        stable_lock_root=tmp_path / "locks",
        stable_artifact_root=tmp_path / "locked-artifacts",
    )

    qlib_row = next(
        row
        for row in result["validation_leaderboard"]["candidates"]
        if row["candidate_id"] == qlib.candidate_id
    )
    assert qlib_row["reason_code"] == "candidate_score_nonfinite"
    assert tested == ["M1"]


def test_qlib_score_loader_filters_non_tradable_prediction_superset(tmp_path):
    from quant.strategy.f4_real_pipeline import _score_file_loader

    score_path = tmp_path / "validation_predictions.csv"
    score_path.write_text(
        "date,instrument,score\n"
        "2024-01-10,SH600000,0.7\n"
        "2024-01-10,SH600001,0.9\n"
        "2024-01-10,SH600002,0.8\n",
        encoding="utf-8",
    )
    panel = pd.DataFrame(
        {
            "date": [pd.Timestamp("2024-01-10"), pd.Timestamp("2024-01-10")],
            "instrument": ["SH600000", "SH600001"],
            "pit_tradable": [True, False],
            "industry": ["I1", "I2"],
        }
    )

    loaded = _score_file_loader(
        score_path,
        panel,
        minimum_coverage=0.95,
    )(pd.Timestamp("2024-01-10"))

    assert loaded.to_dict("records") == [
        {"code": "SH600000", "industry": "I1", "score": 0.7}
    ]

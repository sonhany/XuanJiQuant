from __future__ import annotations

import json
import hashlib
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import pytest

from quant.strategy.f4_candidate_factory import (
    CandidateWindowContext,
    build_candidate_registry,
    candidate_factory_id,
    run_nested_candidate_selection,
    select_validation_winner,
)
from quant.strategy.walk_forward import F4Window


def test_f4_code_version_identity_binds_sorted_source_hashes(tmp_path):
    from quant.strategy.f4_real_pipeline import f4_code_version_identity

    (tmp_path / "z.py").write_text("z = 1\n", encoding="utf-8")
    (tmp_path / "a.py").write_text("a = 1\n", encoding="utf-8")

    first = f4_code_version_identity(
        tmp_path, relative_paths=("z.py", "a.py")
    )
    assert [row["path"] for row in first["files"]] == ["a.py", "z.py"]
    assert len(first["manifest_sha256"]) == 64

    (tmp_path / "a.py").write_text("a = 2\n", encoding="utf-8")
    second = f4_code_version_identity(
        tmp_path, relative_paths=("z.py", "a.py")
    )
    assert second["manifest_sha256"] != first["manifest_sha256"]


def test_f4_code_version_identity_rejects_missing_or_escaping_source(tmp_path):
    from quant.strategy.f4_real_pipeline import F4Blocked, f4_code_version_identity

    with pytest.raises(F4Blocked, match="f4_code_version_source_missing"):
        f4_code_version_identity(tmp_path, relative_paths=("missing.py",))
    with pytest.raises(F4Blocked, match="f4_code_version_path_invalid"):
        f4_code_version_identity(tmp_path, relative_paths=("../escape.py",))


def test_default_v2_adapter_uses_versioned_qlib_provider(tmp_path, monkeypatch):
    import quant.strategy.f4_real_pipeline as pipeline
    from quant.strategy.f4_alpha_contracts import build_v2_candidate_registry
    from quant.strategy.f4_candidate_factory import CandidateUnavailable
    from quant.strategy.f4_real_pipeline import F4InputPaths
    from quant.qlib.workflow_bridge import WindowWorkflowError

    dataset_root = tmp_path / "data" / "qlib" / "datasets" / "a_share_6y_daily"
    paths = F4InputPaths(
        dataset_root=dataset_root,
        adjusted_root=dataset_root / "adjusted",
        industry_path=tmp_path / "industry.json",
        benchmark_path=tmp_path / "benchmark.json",
        cache_root=tmp_path / "cache",
        dataset_version="data-v1",
        manifest_hash="a" * 64,
        end_date="2026-08-20",
    )
    seen = {}

    def fake_fit_qlib_window(**kwargs):
        seen["provider_uri"] = Path(kwargs["provider_uri"])
        seen["instruments"] = kwargs.get("instruments")
        raise WindowWorkflowError("probe_stop")

    monkeypatch.setattr(pipeline, "fit_qlib_window", fake_fit_qlib_window)
    adapter = pipeline._build_default_v2_adapter(
        paths=paths,
        full_panel=pd.DataFrame(),
        stable_artifact_root=tmp_path / "artifacts",
    )
    dates = pd.bdate_range("2026-01-05", periods=6)
    window = F4Window(
        window_id="wf-provider",
        train_dates=tuple(dates[:2]),
        valid_dates=tuple(dates[2:4]),
        test_dates=tuple(dates[4:]),
        purge_bars=1,
        embargo_bars=1,
    )
    candidate = next(item for item in build_v2_candidate_registry() if item.alpha_spec.alpha_id == "Q1")

    with pytest.raises(CandidateUnavailable, match="probe_stop"):
        adapter.fit_qlib(window, candidate, pd.DataFrame(), pd.DataFrame(), tmp_path / "fit")

    assert seen["provider_uri"] == tmp_path / "data" / "qlib" / "qlib_bin" / "a_share_6y_daily"
    assert seen["instruments"] == "market"


def test_default_v2_rule_adapter_excludes_nontradable_validation_identities(tmp_path):
    import quant.strategy.f4_real_pipeline as pipeline
    from quant.strategy.f4_alpha_contracts import build_v2_candidate_registry
    from quant.strategy.f4_real_pipeline import F4InputPaths

    dataset_root = tmp_path / "data" / "qlib" / "datasets" / "a_share_6y_daily"
    paths = F4InputPaths(
        dataset_root=dataset_root,
        adjusted_root=dataset_root / "adjusted",
        industry_path=tmp_path / "industry.json",
        benchmark_path=tmp_path / "benchmark.json",
        cache_root=tmp_path / "cache",
        dataset_version="data-v1",
        manifest_hash="a" * 64,
        end_date="2026-08-20",
    )
    instruments = [f"SH60{index:04d}" for index in range(20)]
    train_dates = pd.bdate_range("2026-01-05", periods=4)
    valid_dates = pd.bdate_range("2026-01-09", periods=2)

    def rows(dates):
        return pd.DataFrame(
            [
                {
                    "date": date,
                    "instrument": instrument,
                    "industry": f"I{index % 4}",
                    "ret_20": float(index + offset + 1) / 100.0,
                    "ret_60": float(index + offset + 2) / 100.0,
                    "forward_return_5d": float((index % 7) - 3) / 100.0,
                    "pit_tradable": not (index == 0),
                }
                for offset, date in enumerate(dates)
                for index, instrument in enumerate(instruments)
            ]
        )

    train_panel = rows(train_dates)
    valid_panel = rows(valid_dates)
    window = F4Window(
        window_id="wf-tradable",
        train_dates=tuple(train_dates),
        valid_dates=tuple(valid_dates),
        test_dates=tuple(valid_dates),
        purge_bars=1,
        embargo_bars=1,
    )
    candidate = next(
        item for item in build_v2_candidate_registry()
        if item.alpha_spec.alpha_id == "M1"
    )
    adapter = pipeline._build_default_v2_adapter(
        paths=paths,
        full_panel=pd.concat([train_panel, valid_panel], ignore_index=True),
        stable_artifact_root=tmp_path / "stable",
    )

    contexts = adapter.fit_rule_batch(
        window,
        (candidate,),
        train_panel,
        valid_panel,
        tmp_path / "attempt",
    )
    context = contexts[candidate.candidate_id]
    scores = pd.read_csv(context.validation_score_path)

    assert set(scores["code"]) == set(instruments[1:])
    assert len(scores) == len(valid_dates) * (len(instruments) - 1)


def _metrics(excess, *, sharpe=1.0, drawdown=-0.1, turnover=1.0, invalid=False):
    return {
        "excess_return": excess,
        "after_cost_excess_return": excess,
        "positive_excess_window_ratio": 1.0 if excess > 0 else 0.0,
        "sharpe": sharpe,
        "max_drawdown": drawdown,
        "turnover": turnover,
        "constraint_violation_count": 1 if invalid else 0,
        "future_data_violation_count": 0,
    }


def test_registry_is_stable_bounded_and_f5_compatible():
    first = build_candidate_registry()
    second = build_candidate_registry()

    assert first == second
    assert len(first) == 6
    assert {(item.top_k, item.rebalance_bars) for item in first} == {
        (5, 5), (5, 10), (5, 20), (10, 5), (10, 10), (10, 20)
    }
    assert len({item.candidate_id for item in first}) == 6
    assert all(item.top_k <= 10 for item in first)
    assert all(item.target_gross_exposure <= 0.95 for item in first)
    assert all(item.max_name_weight <= 0.20 for item in first)
    assert all(item.top_k * item.max_name_weight <= 0.95 + 1e-12 for item in first)
    assert candidate_factory_id({"snapshot": "v1"}, first) == candidate_factory_id(
        {"snapshot": "v1"}, second
    )


def test_validation_winner_is_stable_and_ignores_test_metrics():
    candidates = build_candidate_registry()
    validation = {
        candidates[0].candidate_id: _metrics(0.01, sharpe=0.9),
        candidates[1].candidate_id: _metrics(0.02, sharpe=0.8),
        candidates[2].candidate_id: _metrics(0.50, invalid=True),
    }

    winner_before, _ = select_validation_winner(candidates, validation)
    unrelated_test_returns = {item.candidate_id: 1000.0 for item in reversed(candidates)}
    winner_after, _ = select_validation_winner(candidates, validation)

    assert unrelated_test_returns
    assert winner_before == winner_after == candidates[1].candidate_id


def test_nested_selection_locks_before_test_and_tests_only_winner():
    candidates = build_candidate_registry()[:2]
    events = []

    def validation_runner(window_id, candidate):
        events.append(("validation", window_id, candidate.candidate_id))
        return _metrics(0.02 if candidate == candidates[1] else 0.01)

    def lock_writer(locks):
        events.append(("lock", locks[-1]["window_id"], locks[-1]["candidate_id"]))

    def test_runner(window_id, candidate):
        events.append(("test", window_id, candidate.candidate_id))
        assert any(
            item[0] == "lock" and item[1] == window_id and item[2] == candidate.candidate_id
            for item in events
        )
        return {"1.0": _metrics(0.03), "2.0": _metrics(0.01)}

    result = run_nested_candidate_selection(
        ["w1", "w2"],
        candidates,
        validation_runner=validation_runner,
        test_runner=test_runner,
        lock_writer=lock_writer,
    )

    assert len(result["selection_locks"]) == 2
    assert [event for event in events if event[0] == "test"] == [
        ("test", "w1", candidates[1].candidate_id),
        ("test", "w2", candidates[1].candidate_id),
    ]

    recovered_tests = []
    recovered = run_nested_candidate_selection(
        ["w1"],
        candidates,
        validation_runner=lambda *_args: (_ for _ in ()).throw(
            AssertionError("recovered lock reran validation")
        ),
        test_runner=lambda window_id, candidate: recovered_tests.append(
            (window_id, candidate.candidate_id)
        ) or {"1.0": _metrics(0.03)},
        lock_writer=lambda _locks: None,
        existing_locks={"w1": result["selection_locks"][0]},
    )
    assert recovered_tests == [("w1", candidates[1].candidate_id)]
    assert recovered["test_metrics"][0]["lock_recovered"] is True


def test_all_invalid_candidates_exhaust_without_test_access():
    candidates = build_candidate_registry()[:2]
    test_calls = []

    result = run_nested_candidate_selection(
        ["w1"],
        candidates,
        validation_runner=lambda _window, _candidate: _metrics(0.5, invalid=True),
        test_runner=lambda *_args: test_calls.append(True),
        lock_writer=lambda _locks: None,
    )

    assert test_calls == []
    assert result["candidate_factory_status"] == "exhausted"
    assert result["selection_locks"] == []
    assert result["rejected_windows"][0]["reason_code"] == "candidate_validation_exhausted"


def test_active_v2_pipeline_keeps_exhausted_window_leaderboard_without_lock_or_test():
    from quant.strategy.f4_real_pipeline import _aggregate_v2_window_results

    leaderboard = {
        "window_id": "wf-01",
        "candidate_count": 2,
        "candidates": [
            {
                "candidate_id": "candidate-1",
                "eligible": False,
                "reason_code": "candidate_score_identity_invalid",
            },
            {
                "candidate_id": "candidate-2",
                "eligible": False,
                "reason_code": "qlib_prediction_failed",
            },
        ],
    }

    aggregated = _aggregate_v2_window_results(
        [
            {
                "window_id": "wf-01",
                "window_status": "candidate_validation_exhausted",
                "validation_leaderboard": leaderboard,
                "selection_lock": None,
                "test_metrics": None,
            }
        ],
        [],
    )

    assert aggregated["validation_leaderboards"] == [leaderboard]
    assert aggregated["selection_locks"] == []
    assert aggregated["test_metrics"] == []
    assert aggregated["rejected_windows"] == [
        {"window_id": "wf-01", "reason_code": "candidate_validation_exhausted"}
    ]


def test_real_pipeline_runs_all_validation_candidates_but_only_locked_winner_tests(
    tmp_path, monkeypatch
):
    import quant.strategy.f4_real_pipeline as pipeline
    from quant.strategy.f4_alpha_contracts import build_v2_candidate_registry
    from quant.strategy.f4_real_pipeline import F4V2PipelineAdapter

    industry_path = tmp_path / "data" / "research" / "industry" / "pit_industry.json"
    benchmark_path = tmp_path / "data" / "research" / "benchmarks" / "000300.json"
    industry_path.parent.mkdir(parents=True)
    benchmark_path.parent.mkdir(parents=True)
    industry_path.write_text(json.dumps({"version": "industry-v1", "records": []}), encoding="utf-8")
    benchmark_path.write_text(json.dumps({"version": "benchmark-v1", "bars": []}), encoding="utf-8")
    dates = pd.bdate_range("2026-01-05", periods=8)
    window = F4Window(
        window_id="wf-01",
        train_dates=tuple(dates[:3]),
        valid_dates=tuple(dates[3:5]),
        test_dates=tuple(dates[5:7]),
        purge_bars=1,
        embargo_bars=1,
    )
    panel = pd.DataFrame(
        {
            "date": dates,
            "instrument": ["SH600000"] * len(dates),
            "industry": ["I1"] * len(dates),
        }
    )
    panel.attrs.update({"panel_id": "panel-v1"})
    benchmark_frame = pd.DataFrame({"date": dates, "close": range(100, 108)})
    events = []

    def context(candidate, artifact_root, *, with_model=False):
        candidate_root = artifact_root / candidate.alpha_spec.alpha_id
        candidate_root.mkdir(parents=True, exist_ok=True)
        fit_path = candidate_root / "fit.json"
        fit_path.write_text(
            json.dumps({"candidate_id": candidate.candidate_id}, sort_keys=True),
            encoding="utf-8",
        )
        score_path = candidate_root / "validation.csv"
        score_path.write_text("date,code,industry,score\n2026-01-08,SH600000,I1,1\n", encoding="utf-8")
        model_path = None
        model_hash = None
        if with_model:
            model_path = candidate_root / "model.pkl"
            model_path.write_bytes(candidate.candidate_id.encode("ascii"))
            model_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
        return CandidateWindowContext(
            window_id=window.window_id,
            candidate_id=candidate.candidate_id,
            alpha_spec_hash=pipeline.canonical_payload_hash(asdict(candidate.alpha_spec)),
            alpha_fit_path=str(fit_path),
            alpha_fit_hash=hashlib.sha256(fit_path.read_bytes()).hexdigest(),
            model_artifact_path=str(model_path) if model_path else None,
            model_artifact_hash=model_hash,
            validation_score_path=str(score_path),
            validation_score_hash=hashlib.sha256(score_path.read_bytes()).hexdigest(),
        )

    def fit_rule_batch(active_window, candidates, _train, _valid, artifact_root):
        assert active_window == window
        events.extend(("fit", candidate.alpha_spec.alpha_id) for candidate in candidates)
        return {
            candidate.candidate_id: context(candidate, artifact_root)
            for candidate in candidates
        }

    def fit_qlib(active_window, candidate, _train, _valid, artifact_root):
        assert active_window == window
        events.append(("fit", candidate.alpha_spec.alpha_id))
        return context(candidate, artifact_root, with_model=True)

    def validation_score_loader(_window, candidate, _context, _panel):
        events.append(("valid", candidate.alpha_spec.alpha_id))

        def load(signal_date):
            events.append(("score", "valid", candidate.alpha_spec.alpha_id))
            return pd.DataFrame(
                {"code": ["SH600000"], "industry": ["I1"], "score": [1.0]}
            )

        return load

    def test_score_loader(_window, candidate, _context, lock, _panel):
        assert Path(tmp_path / "data" / "research" / "f4" / "factory-v2" / "locks" / lock["factory_run_id"] / "wf-01.json").is_file()
        events.append(("test_loader", candidate.alpha_spec.alpha_id))

        def load(signal_date):
            events.append(("score", "test", candidate.alpha_spec.alpha_id))
            return pd.DataFrame(
                {"code": ["SH600000"], "industry": ["I1"], "score": [1.0]}
            )

        return load

    adapter = F4V2PipelineAdapter(
        fit_rule_batch=fit_rule_batch,
        fit_qlib=fit_qlib,
        validation_score_loader=validation_score_loader,
        test_score_loader=test_score_loader,
    )

    def simulate(_panel, _benchmark, simulated_window, _fit, *, cost_multiplier, policy, score_loader, candidate, **_kwargs):
        phase = "validation" if simulated_window.window_id.endswith("-validation") else "test"
        scores = score_loader(simulated_window.test_dates[0])
        assert list(scores.columns) == ["code", "industry", "score"]
        events.append((phase, candidate.alpha_spec.alpha_id, cost_multiplier))
        excess = (int(candidate.alpha_spec.alpha_id[1:]) / 100) + {
            "momentum": 0.01,
            "reversal": 0.02,
            "defensive": 0.03,
            "liquidity": 0.04,
            "ensemble": 0.05,
            "qlib": 0.06,
        }[candidate.family]
        return {
            "window_id": simulated_window.window_id,
            "excess_return": excess,
            "after_cost_return": excess,
            "sharpe": excess,
            "max_drawdown": -0.1,
            "turnover": 1.0,
            "total_cost": 1.0,
            "trade_count": 1,
            "constraint_violation_count": 0,
            "future_data_violation_count": 0,
            "promotion_state": "research_only",
            "execution_authority": False,
        }

    monkeypatch.setattr(pipeline, "build_or_load_factor_panel", lambda _paths: panel)
    monkeypatch.setattr(pipeline, "load_benchmark", lambda _path: benchmark_frame)
    monkeypatch.setattr(pipeline, "build_f4_windows", lambda _calendar: (window,))
    monkeypatch.setattr(pipeline, "simulate_f4_window", simulate)

    result = pipeline.run_real_f4_pipeline(
        project_root=tmp_path,
        manifest={
            "dataset_version": "pit-v1",
            "manifest_content_sha256": "manifest-v1",
            "end_date": "2026-01-14",
            "completed_symbols": ["SH600000"],
        },
        industry={"version": "industry-v1"},
        benchmark={"version": "benchmark-v1"},
        v2_adapter=adapter,
    )

    assert result["pipeline_version"] == pipeline.F4_PIPELINE_VERSION
    fit_events = [event for event in events if event[0] == "fit"]
    validation_events = [event for event in events if event[0] == "validation"]
    test_events = [event for event in events if event[0] == "test"]
    assert len(fit_events) == 24
    assert len(validation_events) == 24
    assert len(test_events) == 3
    assert {event[1] for event in test_events} == {"Q4"}
    assert result["candidate_count"] == 24
    assert {item["family"] for item in result["candidate_factory"]["registry"]} == {
        "momentum", "reversal", "defensive", "liquidity", "ensemble", "qlib"
    }
    assert result["candidate_spec"]["selected_policies"][0]["top_k"] == 10
    assert result["candidate_spec"]["selected_policies"][0]["target_gross_exposure"] == 0.95
    assert len([event for event in events if event[:2] == ("score", "valid")]) == 24
    assert len([event for event in events if event[:2] == ("score", "test")]) == 3
    factory_dir = tmp_path / "data" / "research" / "f4" / "factory-v2" / result["factory_run_id"]
    assert {path.name for path in factory_dir.iterdir()} == {
        "registry.json",
        "window_definitions.json",
        "alpha_fits.json",
        "model_artifacts.json",
        "validation_leaderboards.json",
        "candidate_selection_locks.json",
        "test_window_metrics.json",
        "cost_stress_metrics.json",
        "family_diagnostics.json",
        "factory_report.json",
    }
    authoritative = json.loads(
        (factory_dir.parent / "latest.json").read_text(encoding="utf-8")
    )
    assert authoritative["factory_run_id"] == result["factory_run_id"]
    assert result["factory_publication"]["publication_state"] == "committed"

    report_path = factory_dir / "factory_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    code_version = report["input_identity"]["code_version"]
    assert len(code_version["manifest_sha256"]) == 64
    assert [row["path"] for row in code_version["files"]] == sorted(
        pipeline.F4_CODE_VERSION_FILES
    )
    report["pipeline_result"]["candidate_count"] = 999
    report_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(Exception, match="candidate_factory_artifact_integrity_failed"):
        pipeline.run_real_f4_pipeline(
            project_root=tmp_path,
            manifest={
                "dataset_version": "pit-v1",
                "manifest_content_sha256": "manifest-v1",
                "end_date": "2026-01-14",
                "completed_symbols": ["SH600000"],
            },
            industry={"version": "industry-v1"},
            benchmark={"version": "benchmark-v1"},
            v2_adapter=adapter,
        )

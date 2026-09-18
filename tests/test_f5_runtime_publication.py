from __future__ import annotations

import json
import hashlib

import pytest


def test_f5_runtime_reads_selection_and_factor_from_complete_generation(tmp_path, monkeypatch):
    from quant.paper_execution import runtime

    publication_root = tmp_path / "daily"
    publication_root.mkdir()
    (publication_root / "latest.json").write_text("{}", encoding="utf-8")
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps({"portfolio_id": "complete-v1"}), encoding="utf-8")
    factor = tmp_path / "factor_snapshot_latest.json"
    factor.write_text(
        json.dumps(
            {"snapshot_id": "daily-v1", "data_version": "hash-v1", "as_of": "20260818"}
        ),
        encoding="utf-8",
    )
    f4 = tmp_path / "f4.json"
    f4.write_text(json.dumps({"status": "f4_research_candidate"}), encoding="utf-8")
    monkeypatch.setattr(runtime, "RESEARCH_PUBLICATION_ROOT", publication_root, raising=False)
    monkeypatch.setattr(runtime, "F4_LATEST_PATH", f4, raising=False)
    monkeypatch.setattr(
        runtime,
        "resolve_complete_artifact",
        lambda _root, name: selection if name == "selection.json" else factor,
        raising=False,
    )

    assert runtime._selection_evidence()["portfolio_id"] == "complete-v1"
    assert runtime._factor_evidence()["snapshot_id"] == "daily-v1"

    bundle_calls = []
    monkeypatch.setattr(
        runtime,
        "resolve_complete_generation",
        lambda _root: bundle_calls.append(True)
        or {
            "pointer": {"generation_id": "generation-v1"},
            "paths": {
                "selection.json": selection,
                "factor_snapshot_latest.json": factor,
            },
        },
    )
    bundle = runtime._research_bundle()
    assert bundle_calls == [True]
    assert bundle["generation_id"] == "generation-v1"
    assert bundle["selection"]["portfolio_id"] == "complete-v1"
    assert bundle["factor"]["snapshot_id"] == "daily-v1"


def test_f5_runtime_fails_closed_when_pointer_artifact_integrity_fails(tmp_path, monkeypatch):
    from quant.paper_execution import runtime

    publication_root = tmp_path / "daily"
    publication_root.mkdir()
    (publication_root / "latest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(runtime, "RESEARCH_PUBLICATION_ROOT", publication_root, raising=False)

    def broken_resolver(_root, _name):
        raise RuntimeError("hash mismatch")

    monkeypatch.setattr(runtime, "resolve_complete_artifact", broken_resolver, raising=False)

    assert runtime._selection_evidence() == {}
    assert runtime._factor_evidence()["quality_passed"] is False


def test_active_account_names_prefer_complete_research_generation_then_cache(monkeypatch):
    from quant.paper_execution import runtime

    class FakeLedger:
        def list_positions(self):
            return [{"code": code} for code in ("600519", "000001", "600000", "300001")]

        def close(self):
            return None

    class FakeCache:
        def get(self, key):
            return "缓存名称" if key == "stock:name:600000" else None

        def close(self):
            return None

    service = type(
        "Service",
        (),
        {"ledger": FakeLedger(), "policy": type("Policy", (), {"initial_capital": 1_000_000.0})()},
    )()
    monkeypatch.setattr(runtime, "build_runtime_service", lambda: service)
    monkeypatch.setattr(runtime, "create_cache", lambda: FakeCache())
    monkeypatch.setattr(
        runtime,
        "_selection_evidence",
        lambda: {"positions": [{"code": "600519", "name": "贵州茅台"}]},
    )
    monkeypatch.setattr(
        runtime,
        "_factor_evidence",
        lambda: {"rows": [{"code": "000001", "name": "平安银行"}]},
    )
    monkeypatch.setattr(
        runtime,
        "active_account_projection",
        lambda _ledger, _capital, *, limit, name_resolver: {
            "limit": limit,
            "names": {
                code: name_resolver(code)
                for code in ("600519", "000001", "600000", "300001")
            },
        },
    )

    result = runtime.load_active_account_projection(limit=25)

    assert result["names"] == {
        "600519": "贵州茅台",
        "000001": "平安银行",
        "600000": "缓存名称",
        "300001": "",
    }


def test_runtime_hydrates_v2_f4_candidate_evidence_from_authoritative_generation(
    tmp_path, monkeypatch
):
    from quant.paper_execution import runtime

    factory_run_id = "f" * 64
    f4 = tmp_path / "f4.json"
    f4.write_text(
        json.dumps(
            {
                "status": "f4_rejected",
                "factory_run_id": factory_run_id,
                "factory_version": "f4-multi-alpha-candidate-factory-v2",
                "candidate_spec_version": "f4-multi-alpha-candidate-factory-v2",
                "promotion_state": "research_only",
                "execution_authority": False,
            }
        ),
        encoding="utf-8",
    )
    generation = tmp_path / "factory-v2" / factory_run_id
    generation.mkdir(parents=True)
    (generation / "model_artifacts.json").write_text(
        json.dumps(
            {
                "factory_run_id": factory_run_id,
                "models": [],
                "promotion_state": "research_only",
                "execution_authority": False,
            }
        ),
        encoding="utf-8",
    )
    candidate_spec = {
        "version": "f4-multi-alpha-candidate-factory-v2",
        "factory_run_id": factory_run_id,
        "factor_fits": [
            {
                "window_id": "wf-01",
                "candidate_id": "candidate-v2",
                "alpha_spec_hash": "a" * 64,
                "alpha_fit_hash": "b" * 64,
            }
        ],
        "promotion_state": "research_only",
        "execution_authority": False,
    }
    monkeypatch.setattr(runtime, "F4_LATEST_PATH", f4)
    monkeypatch.setattr(
        runtime,
        "resolve_committed_v2_candidate_evidence",
        lambda _root, expected_factory_run_id: {
            "generation_dir": str(generation),
            "factory_run_id": expected_factory_run_id,
            "candidate_spec": candidate_spec,
            "model_artifacts": [],
        },
        raising=False,
    )

    result = runtime._f4_evidence()

    assert result["candidate_spec"]["factor_fits"][0]["alpha_fit_hash"] == "b" * 64
    assert result["candidate_spec"]["model_artifacts"] == []


def _seed_bound_f4_evidence(tmp_path, monkeypatch):
    from quant.paper_execution import runtime

    validation_id = "c" * 64
    factory_run_id = "f" * 64
    generation_id = "generation-current"
    publication_root = tmp_path / "daily"
    publication_root.mkdir()
    (publication_root / "latest.json").write_text("{}", encoding="utf-8")
    f4_latest = tmp_path / "f4-latest.json"
    f4_latest.write_text(
        json.dumps({
            "status": "f4_blocked",
            "reason_code": "f3_pit_date_mismatch",
            "candidate_spec_version": "f4-multi-alpha-candidate-factory-v2",
            "promotion_state": "research_only",
            "execution_authority": False,
        }),
        encoding="utf-8",
    )
    experimental = tmp_path / "experimental.json"
    experimental.write_text(
        json.dumps({
            "selection_status": "experimental_research_portfolio",
            "research_generation_id": generation_id,
            "selection_date": "20260904",
            "f4_validation_id": validation_id,
            "f4_factory_run_id": factory_run_id,
        }),
        encoding="utf-8",
    )
    validation_root = tmp_path / "validations"
    validation_dir = validation_root / validation_id
    validation_dir.mkdir(parents=True)
    identity = validation_dir / "identity.json"
    identity.write_text(
        json.dumps({
            "validation_id": validation_id,
            "promotion_state": "research_only",
            "execution_authority": False,
        }),
        encoding="utf-8",
    )
    identity_hash = hashlib.sha256(identity.read_bytes()).hexdigest()
    (validation_dir / "validation_report.json").write_text(
        json.dumps({
            "status": "f4_rejected",
            "validation_id": validation_id,
            "factory_run_id": factory_run_id,
            "candidate_spec_version": "f4-multi-alpha-candidate-factory-v2",
            "candidate_factory_status": "exhausted",
            "market_date": "2026-08-31",
            "reasons": ["sharpe_below_0_80"],
            "metrics": {
                "constraint_violation_count": 0,
                "future_data_violation_count": 0,
            },
            "input_status": {
                "benchmark": "present",
                "f3_evidence": "present",
                "pit_industry": "present",
                "pit_manifest": "complete",
                "pit_quality": "passed",
            },
            "promotion_state": "research_only",
            "execution_authority": False,
            "artifact_hashes": {"identity.json": identity_hash},
        }),
        encoding="utf-8",
    )
    candidate_spec = {
        "version": "f4-multi-alpha-candidate-factory-v2",
        "factory_run_id": factory_run_id,
        "promotion_state": "research_only",
        "execution_authority": False,
    }
    monkeypatch.setattr(runtime, "RESEARCH_PUBLICATION_ROOT", publication_root)
    monkeypatch.setattr(runtime, "F4_LATEST_PATH", f4_latest)
    monkeypatch.setattr(runtime, "EXPERIMENTAL_SELECTION_PATH", experimental)
    monkeypatch.setattr(runtime, "F4_VALIDATION_ROOT", validation_root, raising=False)
    monkeypatch.setattr(
        runtime,
        "resolve_complete_generation",
        lambda _root: {"pointer": {"generation_id": generation_id}, "paths": {}},
    )
    monkeypatch.setattr(
        runtime,
        "resolve_committed_v2_candidate_evidence",
        lambda _root, expected_factory_run_id: {
            "factory_run_id": expected_factory_run_id,
            "candidate_spec": candidate_spec,
            "model_artifacts": [],
        },
    )
    return runtime, identity


def test_runtime_keeps_current_bound_f4_when_newer_weekly_attempt_is_blocked(
    tmp_path, monkeypatch
):
    runtime, _identity = _seed_bound_f4_evidence(tmp_path, monkeypatch)

    result = runtime._f4_evidence()

    assert result["status"] == "f4_rejected"
    assert result["validation_id"] == "c" * 64
    assert result["factory_run_id"] == "f" * 64
    assert result["candidate_spec"]["model_artifacts"] == []


def test_runtime_rejects_bound_f4_when_immutable_validation_artifact_is_tampered(
    tmp_path, monkeypatch
):
    runtime, identity = _seed_bound_f4_evidence(tmp_path, monkeypatch)
    assert runtime._f4_evidence()["status"] == "f4_rejected"
    identity.write_text("{}", encoding="utf-8")

    assert runtime._f4_evidence() == {}


def test_runtime_loads_nested_experimental_policy(tmp_path, monkeypatch):
    from quant.paper_execution import runtime

    config = tmp_path / "f5.json"
    config.write_text(
        json.dumps(
            {
                "enabled": True,
                "live_execution_authority": False,
                "experimental_paper": {
                    "enabled": True,
                    "policy_version": "f5-experimental-paper-v1",
                    "allowed_f4_statuses": ["f4_rejected"],
                    "require_zero_constraint_violations": True,
                    "require_zero_future_data_violations": True,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "POLICY_PATH", config, raising=False)

    policy = runtime.load_policy()

    assert policy.enabled is True
    assert policy.experimental_paper.enabled is True
    assert policy.experimental_paper.allowed_f4_statuses == ("f4_rejected",)
    assert policy.live_execution_authority is False


def test_runtime_rejects_blocked_experimental_status(tmp_path, monkeypatch):
    from quant.paper_execution import runtime

    config = tmp_path / "f5.json"
    config.write_text(
        json.dumps(
            {
                "enabled": True,
                "experimental_paper": {
                    "enabled": True,
                    "allowed_f4_statuses": ["f4_rejected", "f4_blocked"],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "POLICY_PATH", config, raising=False)

    with pytest.raises(ValueError, match="experimental_f4_status_forbidden"):
        runtime.load_policy()


def test_runtime_loads_experimental_selection_only_for_same_generation(tmp_path, monkeypatch):
    from quant.paper_execution import runtime

    publication_root = tmp_path / "daily"
    publication_root.mkdir()
    (publication_root / "latest.json").write_text("{}", encoding="utf-8")
    daily_selection = tmp_path / "daily-selection.json"
    daily_selection.write_text(
        json.dumps({"portfolio_id": "diagnostic-old"}), encoding="utf-8"
    )
    factor = tmp_path / "factor.json"
    factor.write_text(
        json.dumps(
            {"snapshot_id": "snapshot-v1", "data_version": "data-v1", "as_of": "20260818"}
        ),
        encoding="utf-8",
    )
    f4 = tmp_path / "f4.json"
    f4.write_text(json.dumps({"status": "f4_rejected"}), encoding="utf-8")
    experimental = tmp_path / "experimental.json"
    experimental.write_text(
        json.dumps(
            {
                "portfolio_id": "experimental-v1",
                "selection_status": "experimental_research_portfolio",
                "research_generation_id": "generation-v1",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "RESEARCH_PUBLICATION_ROOT", publication_root)
    monkeypatch.setattr(runtime, "F4_LATEST_PATH", f4, raising=False)
    monkeypatch.setattr(
        runtime, "EXPERIMENTAL_SELECTION_PATH", experimental, raising=False
    )
    monkeypatch.setattr(
        runtime,
        "resolve_complete_generation",
        lambda _root: {
            "pointer": {"generation_id": "generation-v1"},
            "paths": {
                "selection.json": daily_selection,
                "factor_snapshot_latest.json": factor,
            },
        },
    )

    bundle = runtime._research_bundle()

    assert bundle["generation_id"] == "generation-v1"
    assert bundle["selection"]["portfolio_id"] == "experimental-v1"
    assert bundle["selection"]["research_generation_id"] == "generation-v1"

    experimental.write_text(
        json.dumps(
            {
                "portfolio_id": "experimental-old",
                "research_generation_id": "generation-old",
            }
        ),
        encoding="utf-8",
    )
    assert runtime._research_bundle()["selection"] == {}


def test_runtime_intraday_loader_actively_refreshes_exact_portfolio_codes(monkeypatch):
    from quant.paper_execution import runtime
    from scripts import market_data

    calls = []
    monkeypatch.setattr(
        market_data,
        "fetch_realtime",
        lambda codes, use_cache=True: calls.append((codes, use_cache))
        or {code: {"code": code, "price": 10, "volume": 1000} for code in codes},
    )

    result = runtime._fetch_realtime_quotes(["600016", "000166"])

    assert calls == [(["sh600016", "sz000166"], False)]
    assert set(result) == {"sh600016", "sz000166"}

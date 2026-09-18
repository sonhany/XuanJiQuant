import json

import pytest

import scripts.strategy_runner as runner


@pytest.fixture(autouse=True)
def _isolate_authoritative_publication_root(tmp_path, monkeypatch):
    monkeypatch.setattr(
        runner,
        "RESEARCH_PUBLICATION_ROOT",
        tmp_path / "isolated-publication",
    )


def _selection_payload(**overrides):
    payload = {
        "portfolio_id": "portfolio-v1",
        "selection_date": "20260818",
        "generated_from_snapshot_id": "daily-v1",
        "snapshot_data_version": "data-v1",
        "selection_status": "diagnostic_research_portfolio",
        "positions": [{"code": "000001", "name": "平安银行"}],
        "position_count": 1,
        "promotion_state": "research_only",
        "execution_authority": False,
        "not_a_trade_signal": True,
    }
    payload.update(overrides)
    return payload


def test_missing_f4_projection_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "F4_LATEST_PATH", str(tmp_path / "missing.json"))
    result = runner.action_market_scan()
    assert result["success"] is False
    assert result["status"] == "f4_blocked"
    assert result["reason_code"] == "f4_evidence_missing"


def test_market_scan_reads_only_valid_f4_projection(monkeypatch, tmp_path):
    latest = tmp_path / "latest.json"
    latest.write_text(
        json.dumps(
            {
                "validation_id": "abc",
                "candidate_spec_version": "f4-nested-candidate-factory-v1",
                "candidate_spec": {"version": "f4-nested-candidate-factory-v1"},
                "status": "f4_blocked",
                "reasons": ["pit_manifest_incomplete"],
                "promotion_state": "research_only",
                "execution_authority": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "F4_LATEST_PATH", str(latest))
    monkeypatch.setattr(
        runner,
        "build_f4_readiness",
        lambda *_args, **_kwargs: {
            "status": "blocked",
            "reason_code": "pit_manifest_incomplete",
            "trigger_required": False,
            "daily_market_date": "2026-08-28",
            "pit_market_date": "2026-08-28",
            "f4_evidence_market_date": "2026-08-21",
        },
        raising=False,
    )
    result = runner.action_market_scan()
    assert result["success"] is True
    assert result["data"]["validation_id"] == "abc"
    assert result["data"]["source"] == "f4_latest_projection"
    assert result["data"]["readiness"]["daily_market_date"] == "2026-08-28"


def test_market_scan_projects_v2_preflight_block_without_full_factory_report(
    monkeypatch, tmp_path
):
    latest = tmp_path / "latest.json"
    latest.write_text(
        json.dumps(
            {
                "validation_id": "blocked-v2",
                "candidate_spec_version": "f4-multi-alpha-candidate-factory-v2",
                "candidate_spec": {},
                "status": "f4_blocked",
                "reason_code": "f3_pit_date_mismatch",
                "reasons": ["f3_pit_date_mismatch"],
                "input_status": {
                    "benchmark": "present",
                    "f3_evidence": "present",
                    "pit_industry": "present",
                    "pit_manifest": "complete",
                    "pit_quality": "passed",
                },
                "promotion_state": "research_only",
                "execution_authority": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "F4_LATEST_PATH", str(latest))
    monkeypatch.setattr(
        runner,
        "build_f4_readiness",
        lambda *_args, **_kwargs: {
            "status": "blocked",
            "reason_code": "f3_pit_date_mismatch",
        },
        raising=False,
    )

    result = runner.action_market_scan()

    assert result["success"] is True
    assert result["data"]["status"] == "f4_blocked"
    assert result["data"]["reason_code"] == "f3_pit_date_mismatch"
    assert result["data"]["execution_authority"] is False


def test_corrupt_or_authorizing_projection_is_rejected(monkeypatch, tmp_path):
    latest = tmp_path / "latest.json"
    latest.write_text(
        json.dumps(
            {
                "validation_id": "abc",
                "status": "f4_research_candidate",
                "promotion_state": "approved",
                "execution_authority": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "F4_LATEST_PATH", str(latest))
    result = runner.action_market_scan()
    assert result["success"] is False
    assert result["reason_code"] == "artifact_integrity_failed"


def _v2_projection(tmp_path, **overrides):
    report = tmp_path / "factory_report.json"
    report.write_text("{}", encoding="utf-8")
    families = {
        name: {
            "registered": 4,
            "available": 4,
            "unavailable": 0,
            "validation_wins": 0,
            "reason_counts": {},
        }
        for name in (
            "momentum",
            "reversal",
            "defensive",
            "liquidity",
            "ensemble",
            "qlib",
        )
    }
    families["momentum"]["validation_wins"] = 1
    payload = {
        "validation_id": "validation-v2",
        "factory_version": "f4-multi-alpha-candidate-factory-v2",
        "candidate_spec_version": "f4-multi-alpha-candidate-factory-v2",
        "candidate_spec": {
            "version": "f4-multi-alpha-candidate-factory-v2",
            "selection_locks": [{"window_id": "wf-01"}],
        },
        "candidate_count": 24,
        "status": "f4_rejected_exhausted",
        "family_diagnostics": families,
        "stress_metrics": {
            multiplier: {
                "excess_return": excess_return,
                "after_cost_return": 0.01,
                "total_cost": 100.0,
                "window_count": 1,
                "trade_count": 3,
                "promotion_state": "research_only",
                "execution_authority": False,
            }
            for multiplier, excess_return in (
                ("1.0", 0.01),
                ("1.5", 0.005),
                ("2.0", -0.002),
            )
        },
        "artifact_path": str(report),
        "promotion_state": "research_only",
        "execution_authority": False,
    }
    payload.update(overrides)
    return payload


def test_market_scan_projects_verified_v2_family_diagnostics(monkeypatch, tmp_path):
    latest = tmp_path / "latest.json"
    latest.write_text(json.dumps(_v2_projection(tmp_path)), encoding="utf-8")
    monkeypatch.setattr(runner, "F4_LATEST_PATH", str(latest))

    result = runner.action_market_scan()

    assert result["success"] is True
    assert result["data"]["factory_version"] == "f4-multi-alpha-candidate-factory-v2"
    assert result["data"]["candidate_count"] == 24
    assert result["data"]["family_diagnostics"]["qlib"]["registered"] == 4


@pytest.mark.parametrize(
    "overrides",
    [
        {"candidate_count": 23},
        {"family_diagnostics": {}},
        {"stress_metrics": {"1.0": {"excess_return": float("nan")}}},
        {"artifact_path": "missing-report.json"},
        {"factory_version": "f4-unknown-v99"},
        {"factory_version": None},
        {"candidate_spec_version": None},
        {"candidate_spec": {}},
    ],
)
def test_market_scan_rejects_malformed_v2_projection(monkeypatch, tmp_path, overrides):
    latest = tmp_path / "latest.json"
    latest.write_text(json.dumps(_v2_projection(tmp_path, **overrides)), encoding="utf-8")
    monkeypatch.setattr(runner, "F4_LATEST_PATH", str(latest))

    result = runner.action_market_scan()

    assert result["success"] is False
    assert result["reason_code"] == "f4_evidence_integrity_failed"


@pytest.mark.parametrize("field", ["excess_return", "after_cost_return", "total_cost"])
def test_market_scan_rejects_non_finite_v2_cost_metric(monkeypatch, tmp_path, field):
    payload = _v2_projection(tmp_path)
    payload["stress_metrics"]["1.0"][field] = float("nan")
    latest = tmp_path / "latest.json"
    latest.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(runner, "F4_LATEST_PATH", str(latest))

    result = runner.action_market_scan()

    assert result["success"] is False
    assert result["reason_code"] == "f4_evidence_integrity_failed"


@pytest.mark.parametrize("mutation", ["wins", "reasons"])
def test_market_scan_rejects_inconsistent_v2_family_diagnostics(monkeypatch, tmp_path, mutation):
    payload = _v2_projection(tmp_path)
    if mutation == "wins":
        payload["family_diagnostics"]["momentum"]["validation_wins"] = 999
    else:
        payload["family_diagnostics"]["momentum"]["reason_counts"] = {"unavailable": 1}
    latest = tmp_path / "latest.json"
    latest.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(runner, "F4_LATEST_PATH", str(latest))

    result = runner.action_market_scan()

    assert result["success"] is False
    assert result["reason_code"] == "f4_evidence_integrity_failed"


def test_research_selection_reads_only_valid_projection(monkeypatch, tmp_path):
    latest = tmp_path / "selection.json"
    latest.write_text(json.dumps(_selection_payload()), encoding="utf-8")
    monkeypatch.setattr(runner, "SELECTION_LATEST_PATH", str(latest), raising=False)

    result = runner.action_research_selection()

    assert result["success"] is True
    assert result["data"]["portfolio_id"] == "portfolio-v1"
    assert result["data"]["source"] == "research_selection_latest_projection"
    assert result["data"]["execution_authority"] is False


def test_missing_research_selection_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(
        runner,
        "SELECTION_LATEST_PATH",
        str(tmp_path / "missing.json"),
        raising=False,
    )

    result = runner.action_research_selection()

    assert result["success"] is False
    assert result["reason_code"] == "research_selection_missing"


def test_research_selection_rejects_authorizing_projection(monkeypatch, tmp_path):
    latest = tmp_path / "selection.json"
    latest.write_text(
        json.dumps(
            _selection_payload(
                promotion_state="approved",
                execution_authority=True,
                not_a_trade_signal=False,
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "SELECTION_LATEST_PATH", str(latest), raising=False)

    result = runner.action_research_selection()

    assert result["success"] is False
    assert result["reason_code"] == "research_selection_integrity_failed"


def test_research_selection_rejects_position_count_mismatch(monkeypatch, tmp_path):
    latest = tmp_path / "selection.json"
    latest.write_text(
        json.dumps(_selection_payload(position_count=2)),
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "SELECTION_LATEST_PATH", str(latest), raising=False)

    result = runner.action_research_selection()

    assert result["success"] is False
    assert result["reason_code"] == "research_selection_integrity_failed"


def test_research_selection_rejects_non_numeric_position_count(monkeypatch, tmp_path):
    latest = tmp_path / "selection.json"
    latest.write_text(
        json.dumps(_selection_payload(position_count="invalid")),
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "SELECTION_LATEST_PATH", str(latest), raising=False)

    result = runner.action_research_selection()

    assert result["success"] is False
    assert result["reason_code"] == "research_selection_integrity_failed"


def test_research_selection_serves_complete_generation_during_refresh(monkeypatch, tmp_path):
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps(_selection_payload(selection_date="20260812")), encoding="utf-8")
    publication_root = tmp_path / "daily"
    publication_root.mkdir()
    (publication_root / "latest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(runner, "RESEARCH_PUBLICATION_ROOT", publication_root)
    monkeypatch.setattr(
        runner,
        "resolve_complete_artifact",
        lambda _root, name: selection if name == "selection.json" else None,
        raising=False,
    )
    monkeypatch.setattr(
        runner,
        "read_publication_status",
        lambda _root: {"state": "refreshing", "target_date": "20260813"},
        raising=False,
    )

    result = runner.action_research_selection()

    assert result["success"] is True
    assert result["data"]["selection_date"] == "20260812"
    assert result["data"]["is_current"] is False
    assert result["data"]["research_refresh"]["state"] == "refreshing"


def test_completed_research_selection_is_not_current_when_market_date_advanced(
    monkeypatch, tmp_path
):
    selection = tmp_path / "selection.json"
    selection.write_text(
        json.dumps(_selection_payload(selection_date="20260908")), encoding="utf-8"
    )
    publication_root = tmp_path / "daily"
    publication_root.mkdir()
    (publication_root / "latest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(runner, "RESEARCH_PUBLICATION_ROOT", publication_root)
    monkeypatch.setattr(
        runner,
        "resolve_complete_artifact",
        lambda _root, name: selection if name == "selection.json" else None,
        raising=False,
    )
    monkeypatch.setattr(
        runner,
        "read_publication_status",
        lambda _root: {
            "state": "completed",
            "target_date": "20260908",
            "generation_id": "generation-20260908",
        },
        raising=False,
    )
    monkeypatch.setattr(runner, "get_expected_date", lambda: "20260909", raising=False)

    result = runner.action_research_selection()

    assert result["success"] is True
    assert result["data"]["is_current"] is False
    assert result["data"]["expected_latest_date"] == "20260909"
    assert "20260908" in result["data"]["freshness_warning"]

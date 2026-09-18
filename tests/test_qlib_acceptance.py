from scripts.qlib_acceptance import evaluate_acceptance


def complete_acceptance_snapshot(tmp_path):
    artifacts = {
        name: "a" * 64 for name in (
            "params.pkl", "pred.pkl", "label.pkl",
            "sig_analysis/ic.pkl", "sig_analysis/ric.pkl",
            "portfolio_analysis/report_normal_1day.pkl",
            "portfolio_analysis/positions_normal_1day.pkl",
            "portfolio_analysis/port_analysis_1day.pkl",
        )
    }
    return {
        "data_root": str(tmp_path / "qlib"),
        "quality": {"passed": True, "gate_version": "qlib_phase1_gate_v1"},
        "workflow_runs": [
            {"id": "wf_alpha158_lgb", "handler": "Alpha158", "model_type": "LightGBM", "status": "succeeded", "artifacts": dict(artifacts)},
            {"id": "wf_alpha360_lgb", "handler": "Alpha360", "model_type": "LightGBM", "status": "succeeded", "artifacts": dict(artifacts)},
            {"id": "wf_alpha158_xgb", "handler": "Alpha158", "model_type": "XGBoost", "status": "succeeded", "artifacts": dict(artifacts)},
            {"id": "wf_alpha158_linear", "handler": "Alpha158", "model_type": "Linear", "status": "succeeded", "artifacts": dict(artifacts)},
        ],
        "backtests": [
            {"workflow_run_id": "wf_alpha158_lgb", "engine": "qlib_official", "signal_hash": "s" * 64},
            {"workflow_run_id": "wf_alpha158_lgb", "engine": "xuanji_ashare", "signal_hash": "s" * 64},
        ],
        "gate": {"gate_version": "qlib_phase1_gate_v1", "status": "candidate"},
        "shadow_signals": [{"schema_version": "xuanji_shadow_signal_v1", "has_orders": False}],
        "schedule": {"mode": "weekly", "consecutive_successes": 2},
    }


def test_acceptance_rejects_missing_artifact(tmp_path):
    snapshot = complete_acceptance_snapshot(tmp_path)
    snapshot["workflow_runs"][0]["artifacts"].pop("pred.pkl")
    result = evaluate_acceptance(snapshot)
    assert result["passed"] is False
    assert "recorder_artifacts_incomplete" in result["reason_codes"]


def test_acceptance_requires_two_schedule_successes(tmp_path):
    snapshot = complete_acceptance_snapshot(tmp_path)
    snapshot["schedule"]["consecutive_successes"] = 1
    result = evaluate_acceptance(snapshot)
    assert result["passed"] is False
    assert "schedule_successes_below_2" in result["reason_codes"]


def test_complete_snapshot_passes(tmp_path):
    result = evaluate_acceptance(complete_acceptance_snapshot(tmp_path))
    assert result["passed"] is True
    assert result["gate_version"] == "qlib_phase1_gate_v1"


def test_acceptance_rejects_mismatched_dual_backtest_signal(tmp_path):
    snapshot = complete_acceptance_snapshot(tmp_path)
    snapshot["backtests"][1]["signal_hash"] = "x" * 64
    result = evaluate_acceptance(snapshot)
    assert result["passed"] is False
    assert "dual_backtest_signal_mismatch" in result["reason_codes"]


def test_acceptance_rejects_shadow_orders(tmp_path):
    snapshot = complete_acceptance_snapshot(tmp_path)
    snapshot["shadow_signals"][0]["has_orders"] = True
    result = evaluate_acceptance(snapshot)
    assert result["passed"] is False
    assert "shadow_signal_contains_orders" in result["reason_codes"]

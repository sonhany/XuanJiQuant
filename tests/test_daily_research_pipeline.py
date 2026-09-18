import json
import os
from datetime import datetime
from pathlib import Path

from scripts.run_daily_research_pipeline import run_daily_pipeline


def _snapshot(as_of: str, *, quality: str = "passed", freshness: str = "fresh"):
    return {
        "snapshot_id": f"daily-{as_of}",
        "as_of": as_of,
        "quality_status": quality,
        "freshness_status": freshness,
        "content_hash": f"hash-{as_of}",
        "expected_count": 5203,
        "available_count": 5201,
    }


def _selection(as_of: str):
    compact = as_of.replace("-", "")
    return {
        "portfolio_id": f"portfolio-{compact}",
        "selection_date": compact,
        "generated_from_snapshot_id": f"daily-{as_of}",
        "snapshot_data_version": f"hash-{as_of}",
        "promotion_state": "research_only",
        "execution_authority": False,
        "not_a_trade_signal": True,
        "position_count": 1,
        "positions": [{"code": "000001", "target_weight": 0.1}],
    }


def _shadow_baseline_result():
    return {
        "schema": "nautilus-baseline-result-v1",
        "mode": "continuous_full_replay",
        "batch_id": "daily-shadow-baseline",
        "account_id": "daily-shadow",
        "revision": 3,
        "cash": "99054.99",
        "equity": "99993.99",
        "positions": {"600000": 100},
        "orders": [{"id": "o1", "quantity": 100}],
        "fills": [{"intent_id": "o1", "side": "buy", "quantity": 100, "price": "9.40"}],
        "reconciliation": {"passed": True, "checks": {"cash": True, "positions": True}},
        "live_execution_authority": False,
    }


def _shadow_raw_output():
    return {
        "recommendation": {
            "stance": "rebalance_candidate",
            "target_weights": [{"code": "600000", "weight": 0.06}],
            "confidence": 0.66,
            "rationale": "日频基线完成后的只读影子研究建议。",
        }
    }


def test_stale_snapshot_is_refreshed_before_research_runs():
    snapshots = iter([_snapshot("2026-08-14"), _snapshot("2026-08-17")])
    calls = []

    result = run_daily_pipeline(
        now=datetime(2026, 8, 18, 8, 30),
        workers=6,
        snapshot_reader=lambda: next(snapshots),
        command_runner=lambda script, arguments, timeout_seconds: calls.append(
            (script, arguments, timeout_seconds)
        )
        or {"success": True, "exit_code": 0},
        factor_artifact_reader=lambda: {
            "data_end_date": "20260817",
            "data_version": "hash-2026-08-17",
            "promotion_state": "research_only",
            "execution_authority": False,
            "factors": [{"factor": "ret_5"}],
        },
        selection_artifact_reader=lambda: _selection("2026-08-17"),
    )

    assert result["success"] is True
    assert result["expected_date"] == "20260817"
    assert [call[0] for call in calls] == [
        "daily_update.py",
        "research_training_scheduler.py",
    ]
    assert calls[0][1] == ("--workers", "6")


def test_research_does_not_run_when_refresh_stays_stale():
    snapshots = iter([_snapshot("2026-08-14"), _snapshot("2026-08-14")])
    calls = []

    result = run_daily_pipeline(
        now=datetime(2026, 8, 18, 8, 30),
        snapshot_reader=lambda: next(snapshots),
        command_runner=lambda script, arguments, timeout_seconds: calls.append(script)
        or {"success": True, "exit_code": 0},
        factor_artifact_reader=lambda: {},
        selection_artifact_reader=lambda: {},
    )

    assert result["success"] is False
    assert result["reason_code"] == "daily_snapshot_gate_failed"
    assert calls == ["daily_update.py"]


def test_snapshot_without_identity_never_starts_research_publication():
    invalid = _snapshot("2026-08-17")
    invalid.pop("snapshot_id")
    calls = []

    result = run_daily_pipeline(
        now=datetime(2026, 8, 18, 8, 30),
        snapshot_reader=lambda: invalid,
        command_runner=lambda script, *_args: calls.append(script)
        or {"success": True, "exit_code": 0},
        factor_artifact_reader=lambda: {},
        selection_artifact_reader=lambda: {},
    )

    assert result["reason_code"] == "daily_snapshot_gate_failed"
    assert calls == ["daily_update.py"]


def test_current_snapshot_skips_data_refresh_but_runs_research():
    calls = []

    result = run_daily_pipeline(
        now=datetime(2026, 8, 18, 8, 30),
        snapshot_reader=lambda: _snapshot("2026-08-17"),
        command_runner=lambda script, arguments, timeout_seconds: calls.append(script)
        or {"success": True, "exit_code": 0},
        factor_artifact_reader=lambda: {
            "data_end_date": "20260817",
            "data_version": "hash-2026-08-17",
            "promotion_state": "research_only",
            "execution_authority": False,
            "factors": [{"factor": "ret_5"}],
        },
        selection_artifact_reader=lambda: _selection("2026-08-17"),
    )

    assert result["success"] is True
    assert result["data_refresh_performed"] is False
    assert calls == ["research_training_scheduler.py"]


def test_current_factor_artifact_must_match_snapshot_version():
    result = run_daily_pipeline(
        now=datetime(2026, 8, 18, 8, 30),
        snapshot_reader=lambda: _snapshot("2026-08-17"),
        command_runner=lambda *_args, **_kwargs: {"success": True, "exit_code": 0},
        factor_artifact_reader=lambda: {
            "data_end_date": "20260817",
            "data_version": "old-hash",
            "promotion_state": "research_only",
            "execution_authority": False,
            "factors": [{"factor": "ret_5"}],
        },
        selection_artifact_reader=lambda: _selection("2026-08-17"),
    )

    assert result["success"] is False
    assert result["reason_code"] == "factor_artifact_gate_failed"


def test_daily_pipeline_requires_current_selection_artifact():
    result = run_daily_pipeline(
        now=datetime(2026, 8, 18, 8, 30),
        snapshot_reader=lambda: _snapshot("2026-08-17"),
        command_runner=lambda *_args, **_kwargs: {"success": True, "exit_code": 0},
        factor_artifact_reader=lambda: {
            "data_end_date": "20260817",
            "data_version": "hash-2026-08-17",
            "promotion_state": "research_only",
            "execution_authority": False,
            "factors": [{"factor": "ret_5"}],
        },
        selection_artifact_reader=lambda: _selection("2026-08-14"),
    )

    assert result["success"] is False
    assert result["reason_code"] == "research_selection_gate_failed"


def test_factor_gate_failure_never_reads_selection_artifact():
    selection_reads = []
    result = run_daily_pipeline(
        now=datetime(2026, 8, 18, 8, 30),
        snapshot_reader=lambda: _snapshot("2026-08-17"),
        command_runner=lambda *_args, **_kwargs: {"success": True, "exit_code": 0},
        factor_artifact_reader=lambda: {},
        selection_artifact_reader=lambda: selection_reads.append(True) or {},
    )

    assert result["reason_code"] == "factor_artifact_gate_failed"
    assert selection_reads == []


def _write_generation_artifacts(directory: Path, as_of: str) -> None:
    compact = as_of.replace("-", "")
    authority = {"promotion_state": "research_only", "execution_authority": False}
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "factor_snapshot_latest.json").write_text(
        json.dumps(
            {
                "as_of": compact,
                "latest_kline_date": compact,
                "snapshot_id": f"daily-{as_of}",
                "data_version": f"hash-{as_of}",
                "n": 1,
                "active_count": 1,
                "data_count": 1,
                "eligible_count": 1,
                "data_coverage": 1.0,
                "rows": [
                    {
                        "code": "000001",
                        "date": compact,
                        "factors": {"range_pct": 1.0},
                    }
                ],
                **authority,
            }
        ),
        encoding="utf-8",
    )
    (directory / "factor_evaluation.json").write_text(
        json.dumps(
            {
                "data_end_date": compact,
                "snapshot_id": f"daily-{as_of}",
                "data_version": f"hash-{as_of}",
                "n_stocks": 1,
                "active_count": 1,
                "data_count": 1,
                "eligible_count": 1,
                "factors": [{"factor": "range_pct"}],
                **authority,
            }
        ),
        encoding="utf-8",
    )
    (directory / "selection.json").write_text(
        json.dumps(_selection(as_of)),
        encoding="utf-8",
    )


def test_daily_pipeline_publishes_only_complete_staging_generation(tmp_path):
    publication_root = tmp_path / "data" / "research" / "daily"
    mirrors = {
        "factor_snapshot_latest.json": tmp_path / "data" / "factor_snapshot_latest.json",
        "factor_evaluation.json": tmp_path / "data" / "factor_evaluation.json",
        "selection.json": tmp_path / "data" / "research" / "selections" / "latest.json",
    }

    calls = []

    def runner(script, arguments, timeout_seconds):
        calls.append((script, arguments))
        if script == "research_training_scheduler.py":
            generation_dir = Path(os.environ["XUANJI_RESEARCH_GENERATION_DIR"])
            _write_generation_artifacts(generation_dir, "2026-08-17")
        return {"success": True, "exit_code": 0}

    result = run_daily_pipeline(
        now=datetime(2026, 8, 18, 8, 30),
        snapshot_reader=lambda: _snapshot("2026-08-17"),
        command_runner=runner,
        publication_root=publication_root,
        compatibility_mirrors=mirrors,
        readiness_builder=lambda: {
            "status": "blocked",
            "reason_code": "pit_manifest_incomplete",
            "trigger_required": False,
        },
    )

    pointer = json.loads((publication_root / "latest.json").read_text(encoding="utf-8"))
    assert result["success"] is True
    assert result["generation_id"] == pointer["generation_id"]
    assert result["f4_readiness"]["reason_code"] == "pit_manifest_incomplete"
    assert result["stages"][-1]["stage"] == "f4_readiness"
    assert all(path.is_file() for path in mirrors.values())
    assert json.loads(mirrors["selection.json"].read_text(encoding="utf-8"))[
        "snapshot_data_version"
    ] == "hash-2026-08-17"
    assert calls == [
        ("research_training_scheduler.py", ("--once", "--lane", "daily")),
        ("generate_experimental_portfolio.py", ("--generation-id", pointer["generation_id"])),
    ]

    repeated_calls = []
    repeated = run_daily_pipeline(
        now=datetime(2026, 8, 18, 8, 35),
        snapshot_reader=lambda: _snapshot("2026-08-17"),
        command_runner=lambda script, arguments, _timeout: repeated_calls.append(
            (script, arguments)
        )
        or {"success": True},
        publication_root=publication_root,
        compatibility_mirrors=mirrors,
    )
    assert repeated_calls == [
        ("generate_experimental_portfolio.py", ("--generation-id", pointer["generation_id"])),
    ]
    assert repeated["success"] is True
    assert repeated["publication_no_op"] is True
    assert repeated["generation_id"] == pointer["generation_id"]


def test_daily_pipeline_failure_keeps_previous_pointer(tmp_path):
    from quant.research.publication import begin_refresh, publish_generation

    publication_root = tmp_path / "data" / "research" / "daily"
    previous = begin_refresh(
        publication_root,
        target_date="20260816",
        snapshot_id="daily-2026-08-16",
        data_version="hash-2026-08-16",
        started_at="2026-08-16T16:20:00+08:00",
    )
    _write_generation_artifacts(previous.staging_dir, "2026-08-16")
    previous_pointer = publish_generation(
        publication_root,
        previous,
        finished_at="2026-08-16T16:40:00+08:00",
    )

    def runner(script, arguments, timeout_seconds):
        generation_dir = Path(os.environ["XUANJI_RESEARCH_GENERATION_DIR"])
        _write_generation_artifacts(generation_dir, "2026-08-17")
        (generation_dir / "selection.json").unlink()
        return {"success": True, "exit_code": 0}

    result = run_daily_pipeline(
        now=datetime(2026, 8, 18, 8, 30),
        snapshot_reader=lambda: _snapshot("2026-08-17"),
        command_runner=runner,
        publication_root=publication_root,
        compatibility_mirrors={},
    )

    current_pointer = json.loads(
        (publication_root / "latest.json").read_text(encoding="utf-8")
    )
    status = json.loads((publication_root / "status.json").read_text(encoding="utf-8"))
    assert result["success"] is False
    assert current_pointer["generation_id"] == previous_pointer["generation_id"]
    assert status["state"] == "failed"


def test_daily_pipeline_marks_generation_failed_when_scheduler_raises(tmp_path):
    publication_root = tmp_path / "data" / "research" / "daily"

    def runner(*_args):
        raise RuntimeError("scheduler_crashed")

    result = run_daily_pipeline(
        now=datetime(2026, 8, 18, 8, 30),
        snapshot_reader=lambda: _snapshot("2026-08-17"),
        command_runner=runner,
        publication_root=publication_root,
        compatibility_mirrors={},
    )

    status = json.loads((publication_root / "status.json").read_text(encoding="utf-8"))
    assert result["success"] is False
    assert result["reason_code"] == "research_training_exception"
    assert status["state"] == "failed"
    assert status["reason_code"] == "research_training_exception"


def test_daily_pipeline_reports_partial_publication_when_compatibility_mirror_fails(
    tmp_path,
):
    publication_root = tmp_path / "data" / "research" / "daily"
    invalid_mirror = tmp_path / "data" / "factor_evaluation.json"
    invalid_mirror.mkdir(parents=True)
    mirrors = {
        "factor_snapshot_latest.json": tmp_path / "data" / "factor_snapshot_latest.json",
        "factor_evaluation.json": invalid_mirror,
        "selection.json": tmp_path / "data" / "research" / "selections" / "latest.json",
    }

    def runner(script, _arguments, _timeout_seconds):
        if script == "research_training_scheduler.py":
            _write_generation_artifacts(
                Path(os.environ["XUANJI_RESEARCH_GENERATION_DIR"]), "2026-08-17"
            )
        return {"success": True, "exit_code": 0}

    result = run_daily_pipeline(
        now=datetime(2026, 8, 18, 8, 30),
        snapshot_reader=lambda: _snapshot("2026-08-17"),
        command_runner=runner,
        publication_root=publication_root,
        compatibility_mirrors=mirrors,
    )

    pointer = json.loads((publication_root / "latest.json").read_text(encoding="utf-8"))
    assert result["success"] is False
    assert result["reason_code"] == "research_compatibility_mirror_sync_failed"
    assert result["publication_committed"] is True
    assert result["generation_id"] == pointer["generation_id"]
    assert result["mirror_sync_state"] == "failed"

    invalid_mirror.rmdir()
    calls = []

    def must_not_recompute(script, arguments, _timeout):
        calls.append((script, arguments))
        assert script == "generate_experimental_portfolio.py"
        return {"success": True}

    recovered = run_daily_pipeline(
        now=datetime(2026, 8, 18, 8, 35),
        snapshot_reader=lambda: _snapshot("2026-08-17"),
        command_runner=must_not_recompute,
        publication_root=publication_root,
        compatibility_mirrors=mirrors,
    )

    assert calls == [
        ("generate_experimental_portfolio.py", ("--generation-id", pointer["generation_id"])),
    ]
    assert recovered["success"] is True
    assert recovered["publication_recovered"] is True
    assert recovered["generation_id"] == pointer["generation_id"]

    status_path = publication_root / "status.json"
    pending = json.loads(status_path.read_text(encoding="utf-8"))
    pending["mirror_sync_state"] = "pending"
    status_path.write_text(json.dumps(pending), encoding="utf-8")
    pending_calls = []
    pending_recovery = run_daily_pipeline(
        now=datetime(2026, 8, 18, 8, 40),
        snapshot_reader=lambda: _snapshot("2026-08-17"),
        command_runner=lambda script, arguments, _timeout: pending_calls.append(
            (script, arguments)
        )
        or {"success": True},
        publication_root=publication_root,
        compatibility_mirrors=mirrors,
    )
    assert pending_calls == [
        ("generate_experimental_portfolio.py", ("--generation-id", pointer["generation_id"])),
    ]
    assert pending_recovery["success"] is True
    assert pending_recovery["publication_recovered"] is True


def test_daily_pipeline_triggers_readonly_shadow_cycle_after_publication(tmp_path):
    publication_root = tmp_path / "data" / "research" / "daily"
    shadow_root = tmp_path / "data" / "nautilus-baseline" / "shadow-daily"
    shadow_store = tmp_path / "data" / "nautilus-baseline" / "shadow.sqlite3"
    baseline_path = tmp_path / "data" / "nautilus-baseline" / "baseline_result.json"
    raw_output_path = tmp_path / "data" / "nautilus-baseline" / "ai_raw_output.json"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        json.dumps(_shadow_baseline_result(), ensure_ascii=False),
        encoding="utf-8",
    )
    raw_output_path.write_text(
        json.dumps(_shadow_raw_output(), ensure_ascii=False),
        encoding="utf-8",
    )

    def runner(script, _arguments, _timeout_seconds):
        if script == "research_training_scheduler.py":
            _write_generation_artifacts(
                Path(os.environ["XUANJI_RESEARCH_GENERATION_DIR"]), "2026-08-17"
            )
        return {"success": True, "exit_code": 0}

    result = run_daily_pipeline(
        now=datetime(2026, 8, 18, 8, 30),
        snapshot_reader=lambda: _snapshot("2026-08-17"),
        command_runner=runner,
        publication_root=publication_root,
        compatibility_mirrors={},
        readiness_builder=lambda: {"status": "ready", "reason_code": ""},
        shadow_baseline_result_path=baseline_path,
        shadow_raw_output_path=raw_output_path,
        shadow_artifact_root=shadow_root,
        shadow_store_path=shadow_store,
    )

    shadow_stage = result["stages"][-1]
    assert result["success"] is True
    assert shadow_stage["stage"] == "shadow_research"
    assert shadow_stage["success"] is True
    assert shadow_stage["status"] == "recorded"
    assert shadow_stage["live_execution_authority"] is False
    assert shadow_stage["can_trigger_order"] is False
    assert Path(shadow_stage["runtime_summary_path"]).is_file()
    assert Path(shadow_stage["context_output_path"]).is_file()
    assert Path(shadow_stage["report_output_path"]).is_file()
    assert shadow_store.is_file()
    assert not (tmp_path / "data" / "paper" / "f5_ledger.db").exists()


def test_daily_pipeline_exports_runtime_summary_but_skips_shadow_cycle_without_ai_output(tmp_path):
    publication_root = tmp_path / "data" / "research" / "daily"
    shadow_root = tmp_path / "data" / "nautilus-baseline" / "shadow-daily"
    baseline_path = tmp_path / "data" / "nautilus-baseline" / "baseline_result.json"
    raw_output_path = tmp_path / "data" / "nautilus-baseline" / "missing_raw.json"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        json.dumps(_shadow_baseline_result(), ensure_ascii=False),
        encoding="utf-8",
    )

    def runner(script, _arguments, _timeout_seconds):
        if script == "research_training_scheduler.py":
            _write_generation_artifacts(
                Path(os.environ["XUANJI_RESEARCH_GENERATION_DIR"]), "2026-08-17"
            )
        return {"success": True, "exit_code": 0}

    result = run_daily_pipeline(
        now=datetime(2026, 8, 18, 8, 30),
        snapshot_reader=lambda: _snapshot("2026-08-17"),
        command_runner=runner,
        publication_root=publication_root,
        compatibility_mirrors={},
        readiness_builder=lambda: {"status": "ready", "reason_code": ""},
        shadow_baseline_result_path=baseline_path,
        shadow_raw_output_path=raw_output_path,
        shadow_artifact_root=shadow_root,
    )

    shadow_stage = result["stages"][-1]
    assert result["success"] is True
    assert shadow_stage["stage"] == "shadow_research"
    assert shadow_stage["success"] is True
    assert shadow_stage["status"] == "skipped"
    assert shadow_stage["reason_code"] == "shadow_ai_raw_output_missing"
    assert Path(shadow_stage["runtime_summary_path"]).is_file()
    assert "report_output_path" not in shadow_stage


def test_daily_pipeline_fails_when_shadow_ai_output_is_invalid(tmp_path):
    publication_root = tmp_path / "data" / "research" / "daily"
    shadow_root = tmp_path / "data" / "nautilus-baseline" / "shadow-daily"
    baseline_path = tmp_path / "data" / "nautilus-baseline" / "baseline_result.json"
    raw_output_path = tmp_path / "data" / "nautilus-baseline" / "ai_raw_output.json"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        json.dumps(_shadow_baseline_result(), ensure_ascii=False),
        encoding="utf-8",
    )
    raw_output_path.write_text(
        json.dumps(
            {
                "recommendation": {
                    "stance": "rebalance_candidate",
                    "target_weights": [{"code": "600000", "weight": 1.2}],
                    "confidence": 0.66,
                    "rationale": "非法输出权重越界。",
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def runner(script, _arguments, _timeout_seconds):
        if script == "research_training_scheduler.py":
            _write_generation_artifacts(
                Path(os.environ["XUANJI_RESEARCH_GENERATION_DIR"]), "2026-08-17"
            )
        return {"success": True, "exit_code": 0}

    result = run_daily_pipeline(
        now=datetime(2026, 8, 18, 8, 30),
        snapshot_reader=lambda: _snapshot("2026-08-17"),
        command_runner=runner,
        publication_root=publication_root,
        compatibility_mirrors={},
        readiness_builder=lambda: {"status": "ready", "reason_code": ""},
        shadow_baseline_result_path=baseline_path,
        shadow_raw_output_path=raw_output_path,
        shadow_artifact_root=shadow_root,
    )

    shadow_stage = result["stages"][-1]
    assert result["success"] is False
    assert result["reason_code"] == "shadow_research_failed"
    assert shadow_stage["stage"] == "shadow_research"
    assert shadow_stage["success"] is False
    assert shadow_stage["reason_code"] == "shadow_cycle_validation_failed"
    assert shadow_stage["status"] == "validation_failed"
    assert Path(shadow_stage["runtime_summary_path"]).is_file()


def test_failure_status_write_cannot_mask_scheduler_exception(tmp_path, monkeypatch):
    publication_root = tmp_path / "data" / "research" / "daily"
    monkeypatch.setattr(
        "scripts.run_daily_research_pipeline.mark_refresh_failed",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("status unavailable")),
    )

    result = run_daily_pipeline(
        now=datetime(2026, 8, 18, 8, 30),
        snapshot_reader=lambda: _snapshot("2026-08-17"),
        command_runner=lambda *_args: (_ for _ in ()).throw(
            RuntimeError("scheduler_crashed")
        ),
        publication_root=publication_root,
        compatibility_mirrors={},
    )

    assert result["success"] is False
    assert result["reason_code"] == "research_training_exception"
    assert result["error"] == "scheduler_crashed"

from quant.strategy.f4_readiness import evaluate_f4_readiness


def _inputs(**overrides):
    values = {
        "manifest": {
            "status": "complete",
            "dataset_version": "daily-pit-2020-08-28",
            "adjustment_schema_version": "qlib_adjustment_v1",
            "end_date": "2026-08-28",
            "requested": 5435,
            "processed": 5435,
            "completed_symbols": ["SH600000"],
        },
        "quality": {
            "status": "passed",
            "dataset_version": "daily-pit-2020-08-28",
            "data_latest_date": "2026-08-28",
        },
        "industry": {
            "effective_dated": True,
            "coverage": 0.99,
            "version": "industry-v1",
        },
        "benchmark": {
            "coverage": 1.0,
            "code": "000300",
            "version": "benchmark-v1",
        },
        "factor_publication": {
            "target_date": "20260828",
            "data_version": "daily-v1",
            "promotion_state": "research_only",
            "execution_authority": False,
        },
        "f4_projection": {
            "market_date": "2026-08-21",
            "generated_at": "2026-08-22T22:17:09+08:00",
            "validation_id": "f4-old",
            "promotion_state": "research_only",
            "execution_authority": False,
        },
    }
    values.update(overrides)
    return values


def test_complete_current_inputs_require_one_event_driven_f4_run():
    result = evaluate_f4_readiness(**_inputs())

    assert result["status"] == "ready"
    assert result["trigger_required"] is True
    assert result["daily_market_date"] == "2026-08-28"
    assert result["pit_market_date"] == "2026-08-28"
    assert result["f4_evidence_market_date"] == "2026-08-21"


def test_incomplete_pit_reports_progress_without_hiding_daily_date():
    manifest = {
        **_inputs()["manifest"],
        "status": "incomplete",
        "processed": 2375,
    }
    result = evaluate_f4_readiness(**_inputs(manifest=manifest))

    assert result["status"] == "blocked"
    assert result["reason_code"] == "pit_manifest_incomplete"
    assert result["trigger_required"] is False
    assert result["pit_progress"] == {"processed": 2375, "requested": 5435}
    assert result["daily_market_date"] == "2026-08-28"


def test_current_f4_evidence_does_not_trigger_duplicate_run():
    projection = {
        **_inputs()["f4_projection"],
        "market_date": "2026-08-28",
        "validation_id": "f4-current",
    }
    result = evaluate_f4_readiness(**_inputs(f4_projection=projection))

    assert result["status"] == "current"
    assert result["trigger_required"] is False


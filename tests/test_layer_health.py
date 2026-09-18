from datetime import datetime


def _publication(*, as_of="20260819"):
    return {
        "pointer": {
            "generation_id": "generation-1",
            "target_date": as_of,
            "snapshot_id": f"snapshot-{as_of}",
            "data_version": "data-version-1",
            "promotion_state": "research_only",
            "execution_authority": False,
        },
        "factor": {
            "as_of": as_of,
            "n_stocks": 4990,
            "eligible_count": 4990,
            "data_coverage": 0.9996,
            "factors": [{"factor": f"factor-{index}"} for index in range(58)],
            "snapshot_id": f"snapshot-{as_of}",
            "data_version": "data-version-1",
            "promotion_state": "research_only",
            "execution_authority": False,
        },
        "selection": {
            "selection_date": as_of,
            "position_count": 20,
            "generated_from_snapshot_id": f"snapshot-{as_of}",
            "snapshot_data_version": "data-version-1",
            "promotion_state": "research_only",
            "execution_authority": False,
        },
    }


def test_four_layer_health_uses_authoritative_freshness_and_paper_ledger():
    from quant.health import project_four_layer_health

    result = project_four_layer_health(
        expected_date="20260819",
        data_coverage={
            "fresh": True,
            "coverage_date": "20260819",
            "expected_date": "20260819",
            "expected_coverage": 0.9996,
            "total_count": 5205,
            "dominant_count": 5203,
        },
        publication=_publication(),
        f4={
            "status": "f4_rejected_exhausted",
            "data_end_date": "20260819",
            "validation_id": "validation-1",
            "promotion_state": "research_only",
            "execution_authority": False,
            "reasons": ["positive_excess_window_ratio_below_0_60"],
        },
        paper={
            "enabled": True,
            "kill_switch": False,
            "live_execution_authority": False,
            "paper_execution_authority": True,
            "execution_mode": "paper_intraday",
            "market_fact_timestamp": "20260820111317",
            "strategy_quality_status": "unqualified",
            "latest_run": {
                "run_id": "paper-1",
                "status": "completed",
                "order_count": 5,
                "fill_count": 5,
                "updated_at": "2026-08-20T11:13:17+08:00",
            },
            "reconciliation_failed": False,
        },
        checked_at=datetime(2026, 8, 20, 15, 20),
    )

    assert result["data_layer"]["status"] == "ok"
    assert result["factor_layer"]["status"] == "ok"
    assert result["factor_layer"]["registered_factor_count"] == 58
    assert result["factor_layer"]["eligible_stock_count"] == 4990
    assert result["strategy_layer"]["status"] == "warning"
    assert result["strategy_layer"]["reason"] == "f4_rejected_exhausted"
    assert result["execution_layer"]["status"] == "ok"
    assert result["execution_layer"]["order_count"] == 5
    assert result["execution_layer"]["live_execution_authority"] is False
    assert result["overall"] == "warning"


def test_four_layer_health_reports_stale_factor_without_calling_it_broken():
    from quant.health import project_four_layer_health

    publication = _publication(as_of="20260819")
    publication["refresh"] = {"state": "refreshing", "target_date": "20260820"}
    result = project_four_layer_health(
        expected_date="20260820",
        data_coverage={
            "fresh": True,
            "coverage_date": "20260820",
            "expected_date": "20260820",
            "expected_coverage": 0.998,
            "total_count": 5203,
            "dominant_count": 5193,
        },
        publication=publication,
        f4={},
        paper={"live_execution_authority": False, "latest_run": None},
        checked_at=datetime(2026, 8, 20, 15, 40),
    )

    assert result["data_layer"]["status"] == "ok"
    assert result["factor_layer"]["status"] == "warning"
    assert result["factor_layer"]["freshness"] == "stale"
    assert result["factor_layer"]["reason"] == "factor_refreshing"
    assert result["factor_layer"]["refresh_target_date"] == "20260820"
    assert result["strategy_layer"]["status"] == "error"
    assert result["execution_layer"]["status"] == "warning"


def test_four_layer_health_fails_closed_on_authority_or_reconciliation_error():
    from quant.health import project_four_layer_health

    publication = _publication()
    publication["factor"]["execution_authority"] = True
    result = project_four_layer_health(
        expected_date="20260819",
        data_coverage={"fresh": True, "coverage_date": "20260819"},
        publication=publication,
        f4={"status": "f4_research_candidate"},
        paper={
            "live_execution_authority": False,
            "latest_run": {"status": "halted_unknown"},
            "reconciliation_failed": True,
        },
    )

    assert result["factor_layer"]["status"] == "error"
    assert result["execution_layer"]["status"] == "error"
    assert result["overall"] == "error"


def test_data_layer_uses_daily_refresh_grace_before_escalating_to_error():
    from quant.health import project_four_layer_health

    common = {
        "expected_date": "20260820",
        "data_coverage": {
            "fresh": False,
            "coverage_date": "20260819",
            "expected_date": "20260820",
            "expected_coverage": 0.04,
        },
        "publication": _publication(),
        "f4": {},
        "paper": {"live_execution_authority": False},
    }

    pending = project_four_layer_health(
        **common, checked_at=datetime(2026, 8, 20, 16, 0)
    )
    overdue = project_four_layer_health(
        **common, checked_at=datetime(2026, 8, 20, 16, 41)
    )

    assert pending["data_layer"]["status"] == "warning"
    assert pending["data_layer"]["reason"] == "daily_refresh_pending"
    assert overdue["data_layer"]["status"] == "error"
    assert overdue["data_layer"]["reason"] == "market_daily_coverage_stale_or_incomplete"


def test_blocked_paper_run_is_not_reported_as_healthy_execution():
    from quant.health import project_four_layer_health

    result = project_four_layer_health(
        expected_date="20260820",
        data_coverage={"fresh": True, "coverage_date": "20260820"},
        publication=_publication(as_of="20260820"),
        f4={},
        paper={
            "enabled": True,
            "kill_switch": False,
            "live_execution_authority": False,
            "execution_mode": "paper_daily",
            "reason_code": "selection_stale",
            "latest_run": {
                "run_id": "blocked-1",
                "status": "blocked",
                "reason_code": "selection_stale",
            },
        },
    )

    assert result["execution_layer"]["status"] == "warning"
    assert result["execution_layer"]["reason"] == "selection_stale"
    assert result["execution_layer"]["freshness"] == "not_applicable"


def test_current_readiness_reason_replaces_stale_historical_block_reason():
    from quant.health import project_four_layer_health

    result = project_four_layer_health(
        expected_date="20260820",
        data_coverage={"fresh": True, "coverage_date": "20260820"},
        publication=_publication(as_of="20260820"),
        f4={"status": "f4_rejected"},
        paper={
            "enabled": True,
            "kill_switch": False,
            "live_execution_authority": False,
            "execution_mode": "paper_intraday",
            "reason_code": "outside_intraday_window",
            "current_readiness": {
                "paper_execution_ready": True,
                "market_window_allowed": False,
                "reason_code": "outside_intraday_window",
            },
            "latest_run": {
                "run_id": "blocked-old",
                "status": "blocked",
                "reason_code": "validation_identity_mismatch",
            },
        },
    )

    assert result["execution_layer"]["status"] == "warning"
    assert result["execution_layer"]["reason"] == "outside_intraday_window"
    assert result["execution_layer"]["freshness"] == "not_applicable"


def test_current_completed_paper_run_is_not_reported_as_cycle_pending():
    from quant.health import project_four_layer_health

    result = project_four_layer_health(
        expected_date="20260826",
        data_coverage={"fresh": True, "coverage_date": "20260826"},
        publication=_publication(as_of="20260826"),
        f4={"status": "f4_rejected"},
        paper={
            "enabled": True,
            "kill_switch": False,
            "live_execution_authority": False,
            "paper_execution_authority": True,
            "execution_mode": "paper_intraday",
            "market_fact_timestamp": "20260826130518",
            "current_readiness": {
                "paper_execution_ready": True,
                "market_window_allowed": True,
                "reason_code": "eligible_experimental",
            },
            "latest_run": {
                "run_id": "paper-current",
                "status": "completed",
                "order_count": 12,
                "fill_count": 12,
                "updated_at": "2026-08-26T13:05:18+08:00",
            },
        },
        checked_at=datetime(2026, 8, 26, 14, 40),
    )

    assert result["execution_layer"]["status"] == "ok"
    assert result["execution_layer"]["reason"] is None
    assert result["execution_layer"]["freshness"] == "session_current"

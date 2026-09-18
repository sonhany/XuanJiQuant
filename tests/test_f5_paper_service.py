from datetime import datetime
import json

import pytest

from quant.paper_execution.ledger import PaperLedger
from quant.paper_execution.policy import ExperimentalPaperPolicy, PaperExecutionPolicy
from quant.paper_execution.service import PaperExecutionService


def _selection(status="f4_research_candidate", date="20260818"):
    return {
        "portfolio_id": "portfolio-eligible",
        "selection_status": "f4_research_portfolio" if status == "f4_research_candidate" else "diagnostic_research_portfolio",
        "selection_date": date,
        "generated_from_snapshot_id": "snapshot-v1",
        "snapshot_data_version": "data-v1",
        "f4_validation_id": "validation-v1",
        "f4_gate_status": status,
        "position_count": 2,
        "positions": [
            {"code": "600001", "target_weight": 0.2, "reference_close": 10.0},
            {"code": "600002", "target_weight": 0.2, "reference_close": 20.0},
        ],
        "invested_weight": 0.4,
        "cash_weight": 0.6,
        "portfolio_policy": {"version": "portfolio-policy-v1", "top_k": 2, "lot_size": 100},
        "promotion_state": "research_only",
        "execution_authority": False,
        "not_a_trade_signal": True,
    }


def _f4(status="f4_research_candidate"):
    return {"status": status, "validation_id": "validation-v1", "portfolio_policy_version": "portfolio-policy-v1", "cost_model_version": "cost-model-v1", "promotion_state": "research_only", "execution_authority": False}


def _service(tmp_path, selection, f4):
    ledger = PaperLedger(tmp_path / "f5.db")
    bars = {
        ("600001", "20260819"): {"date": "20260819", "open": 10.0, "close": 10.5, "volume": 1_000_000},
        ("600002", "20260819"): {"date": "20260819", "open": 20.0, "close": 19.5, "volume": 1_000_000},
    }
    service = PaperExecutionService(
        ledger=ledger,
        policy=PaperExecutionPolicy(enabled=True),
        risk={"kill_switch": False, "max_position_count": 10, "max_position_pct": 0.2, "max_gross_exposure_pct": 95, "max_orders_per_run": 20, "min_cash_buffer_pct": 2},
        selection_loader=lambda: selection,
        f4_loader=lambda: f4,
        factor_loader=lambda: {"snapshot_id": "snapshot-v1", "data_version": "data-v1", "as_of": selection["selection_date"], "quality_passed": True},
        market_bar_loader=lambda code, session: bars.get((code, session)),
        next_session=lambda date: "20260819" if date == "20260818" else "20260820",
    )
    return ledger, service


def test_eligible_fixture_prepares_then_executes_and_reconciles(tmp_path):
    ledger, service = _service(tmp_path, _selection(), _f4())
    first = service.run_due(datetime(2026, 8, 18, 16, 40))
    assert first["prepared"]["status"] == "prepared"
    second = service.run_due(datetime(2026, 8, 19, 16, 40))
    completed = next(run for run in ledger.list_runs() if run["intended_session"] == "20260819")
    assert completed["status"] == "completed"
    assert ledger.count("paper_orders") == 2
    assert ledger.count("paper_fills") == 2
    assert ledger.count("paper_positions") == 2
    assert ledger.count("paper_equity_snapshots") == 1
    assert ledger.count("paper_reconciliations") == 10
    assert second["settled"][0]["reconciliation_passed"] is True


def test_intraday_readiness_is_current_and_never_writes_ledger(tmp_path):
    ledger, service = _service(tmp_path, _selection(), _f4())

    result = service.intraday_readiness(datetime(2026, 8, 19, 12, 0))

    assert result["paper_execution_ready"] is True
    assert result["market_window_allowed"] is False
    assert result["reason_code"] == "outside_intraday_window"
    assert result["validation_id"] == "validation-v1"
    assert ledger.count("paper_runs") == 0


def test_prepare_consumes_selection_and_factor_from_one_bundle(tmp_path):
    selection = _selection()
    factor = {
        "snapshot_id": "snapshot-v1",
        "data_version": "data-v1",
        "as_of": "20260818",
        "quality_passed": True,
    }
    calls = []
    service = PaperExecutionService(
        ledger=PaperLedger(tmp_path / "bundle.db"),
        policy=PaperExecutionPolicy(enabled=True),
        risk={"kill_switch": False, "max_position_count": 10, "max_position_pct": 0.2, "max_gross_exposure_pct": 95, "max_orders_per_run": 20, "min_cash_buffer_pct": 2},
        selection_loader=lambda: (_ for _ in ()).throw(AssertionError("split selection read")),
        f4_loader=lambda: _f4(),
        factor_loader=lambda: (_ for _ in ()).throw(AssertionError("split factor read")),
        research_bundle_loader=lambda: calls.append(True) or {"selection": selection, "factor": factor},
        market_bar_loader=lambda _code, _session: None,
        next_session=lambda _date: "20260819",
    )

    result = service.run_due("20260818")

    assert calls == [True]
    assert result["prepared"]["status"] == "prepared"


@pytest.mark.parametrize(
    "bundle, expected_reason",
    [
        ({}, "selection_missing"),
        ({"factor": {"quality_passed": True}}, "selection_missing"),
        ({"selection": _selection()}, "factor_evidence_unavailable"),
    ],
)
def test_incomplete_bundle_fails_closed_without_split_loader_fallback(
    tmp_path, bundle, expected_reason
):
    service = PaperExecutionService(
        ledger=PaperLedger(tmp_path / f"bundle-{expected_reason}.db"),
        policy=PaperExecutionPolicy(enabled=True),
        risk={"kill_switch": False, "max_position_count": 10, "max_position_pct": 0.2, "max_gross_exposure_pct": 95, "max_orders_per_run": 20, "min_cash_buffer_pct": 2},
        selection_loader=lambda: (_ for _ in ()).throw(AssertionError("split selection read")),
        f4_loader=lambda: _f4(),
        factor_loader=lambda: (_ for _ in ()).throw(AssertionError("split factor read")),
        research_bundle_loader=lambda: bundle,
        market_bar_loader=lambda _code, _session: None,
        next_session=lambda _date: "20260819",
    )

    result = service.run_due("20260818")

    assert result["prepared"]["status"] == "blocked"
    assert result["prepared"]["reason_code"] == expected_reason


def test_f4_rejected_records_one_blocked_run_and_no_orders(tmp_path):
    selection = _selection("f4_rejected")
    ledger, service = _service(tmp_path, selection, _f4("f4_rejected"))
    result = service.run_due(datetime(2026, 8, 18, 16, 40))
    assert result["prepared"]["status"] == "blocked"
    assert result["prepared"]["reason_code"] == "blocked_by_f4"
    assert ledger.count("paper_orders") == 0
    assert ledger.count("paper_fills") == 0
    service.run_due(datetime(2026, 8, 18, 16, 40))
    assert ledger.count("paper_runs") == 1


def test_duplicate_due_call_never_duplicates_side_effects(tmp_path):
    ledger, service = _service(tmp_path, _selection(), _f4())
    service.run_due(datetime(2026, 8, 18, 16, 40))
    service.run_due(datetime(2026, 8, 19, 16, 40))
    counts = {table: ledger.count(table) for table in ("paper_orders", "paper_fills", "paper_cash_ledger", "paper_equity_snapshots")}
    service.run_due(datetime(2026, 8, 19, 16, 40))
    assert counts == {table: ledger.count(table) for table in counts}


def test_experimental_prepare_persists_lane_and_quality_evidence(tmp_path):
    from tests.test_f5_paper_eligibility import _experimental_pair

    selection, f4 = _experimental_pair()
    for index, position in enumerate(selection["positions"], 1):
        position["reference_close"] = 10.0 + index
    ledger = PaperLedger(tmp_path / "experimental.db")
    service = PaperExecutionService(
        ledger=ledger,
        policy=PaperExecutionPolicy(
            enabled=True,
            experimental_paper=ExperimentalPaperPolicy(enabled=True),
        ),
        risk={
            "kill_switch": False,
            "max_position_count": 10,
            "max_position_pct": 0.2,
            "max_gross_exposure_pct": 95,
            "max_orders_per_run": 20,
            "min_cash_buffer_pct": 2,
        },
        selection_loader=lambda: selection,
        f4_loader=lambda: f4,
        factor_loader=lambda: {},
        research_bundle_loader=lambda: {
            "generation_id": "generation-v1",
            "selection": selection,
            "factor": {
                "snapshot_id": "snapshot-v1",
                "data_version": "data-v1",
                "as_of": "20260818",
                "quality_passed": True,
            },
        },
        market_bar_loader=lambda _code, _session: None,
        next_session=lambda _date: "20260819",
    )

    result = service.run_due("20260818")

    assert result["prepared"]["status"] == "prepared"
    assert result["prepared"]["execution_lane"] == "experimental_paper"
    assert result["prepared"]["strategy_quality_status"] == "unqualified"
    assert result["prepared"]["f4_status"] == "f4_rejected"
    assert result["prepared"]["f4_reasons"] == ["sharpe_below_0_80"]
    assert result["prepared"]["research_generation_id"] == "generation-v1"


def _intraday_service(
    tmp_path,
    *,
    quote_timestamp="20260820105400",
    selection_date="20260819",
    next_session_value="20260821",
):
    from tests.test_f5_paper_eligibility import _experimental_pair

    selection, f4 = _experimental_pair()
    selection["selection_date"] = selection_date
    for index, position in enumerate(selection["positions"], 1):
        position["reference_close"] = 10.0 + index
    quotes = {
        ("sh" if str(row["code"]).startswith("6") else "sz") + str(row["code"]): {
            "code": ("sh" if str(row["code"]).startswith("6") else "sz") + str(row["code"]),
            "price": 10.0 + index,
            "volume": 1_000_000,
            "timestamp": quote_timestamp,
            "source": "tdx_quant",
            "chg_pct": 1.0,
            "trading_state": "active",
        }
        for index, row in enumerate(selection["positions"], 1)
    }
    ledger = PaperLedger(tmp_path / "intraday.db")
    service = PaperExecutionService(
        ledger=ledger,
        policy=PaperExecutionPolicy(
            enabled=True,
            experimental_paper=ExperimentalPaperPolicy(enabled=True),
        ),
        risk={
            "kill_switch": False,
            "max_position_count": 10,
            "max_position_pct": 0.2,
            "max_gross_exposure_pct": 95,
            "max_orders_per_run": 20,
            "min_cash_buffer_pct": 2,
        },
        selection_loader=lambda: selection,
        f4_loader=lambda: f4,
        factor_loader=lambda: {},
        research_bundle_loader=lambda: {
            "generation_id": "generation-v1",
            "selection": selection,
            "factor": {
                "snapshot_id": "snapshot-v1",
                "data_version": "data-v1",
                "as_of": selection_date,
                "quality_passed": True,
            },
        },
        realtime_quote_loader=lambda _codes: quotes,
        market_bar_loader=lambda _code, _session: None,
        next_session=lambda _date: next_session_value,
    )
    return ledger, service


def _staged_intraday_service(tmp_path):
    from tests.test_f5_paper_eligibility import _experimental_pair

    selection, f4 = _experimental_pair()
    selection["selection_date"] = "20260819"
    for position in selection["positions"]:
        position["reference_close"] = 10.0
    quote_clock = ["20260820105530"]
    ledger = PaperLedger(tmp_path / "staged-intraday.db")
    seed = ledger.claim_run(
        portfolio_id="seed-portfolio",
        validation_id="seed-validation",
        intended_session="20260819",
        policy_hash="seed-policy",
        input_hash="seed-input",
        input_payload={},
        initial_status="completed",
    )
    ledger.apply_execution_bundle(
        run_id=seed["run_id"],
        orders=[],
        fills=[],
        positions=[
            {
                "code": f"{500000 + index:06d}",
                "quantity": 5000,
                "available_qty": 0,
                "today_buy_qty": 5000,
                "avg_price": 10.0,
                "current_price": 10.0,
                "realized_pnl": 0.0,
            }
            for index in range(16)
        ],
        cash_entries=[
            {
                "entry_id": "seed-cash",
                "run_id": seed["run_id"],
                "entry_type": "seed",
                "amount": -900000.0,
                "balance_after": 100000.0,
            }
        ],
    )
    service = PaperExecutionService(
        ledger=ledger,
        policy=PaperExecutionPolicy(
            enabled=True,
            experimental_paper=ExperimentalPaperPolicy(enabled=True),
        ),
        risk={
            "kill_switch": False,
            "max_position_count": 10,
            "max_position_pct": 0.2,
            "max_gross_exposure_pct": 95,
            "max_orders_per_run": 20,
            "min_cash_buffer_pct": 2,
        },
        selection_loader=lambda: selection,
        f4_loader=lambda: f4,
        factor_loader=lambda: {},
        research_bundle_loader=lambda: {
            "generation_id": "generation-v1",
            "selection": selection,
            "factor": {
                "snapshot_id": "snapshot-v1",
                "data_version": "data-v1",
                "as_of": "20260819",
                "quality_passed": True,
            },
        },
        realtime_quote_loader=lambda codes: {
            code: {
                "code": code,
                "price": 10.0,
                "volume": 1_000_000,
                "timestamp": quote_clock[0],
                "source": "tdx_quant",
                "chg_pct": 0.0,
                "trading_state": "active",
            }
            for code in codes
        },
        market_bar_loader=lambda _code, _session: None,
        next_session=lambda _date: "20260821",
    )
    return ledger, service, quote_clock


def test_intraday_cycle_uses_previous_complete_selection_and_settles_now(tmp_path):
    ledger, service = _intraday_service(tmp_path)

    result = service.run_intraday(datetime(2026, 8, 20, 10, 55))

    assert result["execution_mode"] == "paper_intraday"
    assert result["live_execution_authority"] is False
    assert result["run"]["status"] == "completed"
    assert result["run"]["intended_session"] == "20260820"
    assert result["run"]["execution_lane"] == "experimental_paper"
    assert result["run"]["strategy_quality_status"] == "unqualified"
    assert ledger.count("paper_orders") > 0
    assert ledger.count("paper_fills") > 0
    assert ledger.count("paper_equity_snapshots") == 1
    assert ledger.count("paper_reconciliations") == 10


def test_intraday_cycle_is_idempotent_for_same_portfolio_and_session(tmp_path):
    ledger, service = _intraday_service(tmp_path)
    first = service.run_intraday(datetime(2026, 8, 20, 10, 55))
    counts = {name: ledger.count(name) for name in ("paper_runs", "paper_orders", "paper_fills", "paper_equity_snapshots")}

    second = service.run_intraday(datetime(2026, 8, 20, 10, 56))

    assert second["run"]["run_id"] == first["run"]["run_id"]
    assert {name: ledger.count(name) for name in counts} == counts


def test_intraday_staged_rebalance_continues_with_new_batch_until_target_converges(tmp_path):
    ledger, service, quote_clock = _staged_intraday_service(tmp_path)

    first = service.run_intraday(datetime(2026, 8, 20, 10, 55, 40))
    quote_clock[0] = "20260820105610"
    second = service.run_intraday(datetime(2026, 8, 20, 10, 56, 20))
    quote_clock[0] = "20260820105640"
    third = service.run_intraday(datetime(2026, 8, 20, 10, 56, 50))

    assert first["run"]["batch_index"] == 0
    assert second["run"]["batch_index"] == 1
    assert second["run"]["run_id"] != first["run"]["run_id"]
    assert third["target_converged"] is True
    assert third["idempotent"] is True
    assert ledger.count("paper_runs") == 3  # one seed plus two execution batches
    assert ledger.count("paper_orders") == 26
    assert {row["code"] for row in ledger.list_positions()} == {
        f"{600000 + index:06d}" for index in range(10)
    }


def test_intraday_settlement_preserves_staged_plan_metadata_in_final_order_payload(tmp_path):
    ledger, service, _quote_clock = _staged_intraday_service(tmp_path)

    result = service.run_intraday(datetime(2026, 8, 20, 10, 55, 40))
    payloads = [json.loads(row["payload_json"]) for row in ledger.list_orders(result["run"]["run_id"])]

    assert len(payloads) == 20
    assert {payload["planned_order_count"] for payload in payloads} == {26}
    assert {payload["deferred_order_count"] for payload in payloads} == {6}
    assert all(payload["partial_rebalance"] is True for payload in payloads)


def test_intraday_stale_quote_blocks_without_poisoning_next_retry(tmp_path):
    ledger, service = _intraday_service(tmp_path, quote_timestamp="20260820105000")

    result = service.run_intraday(datetime(2026, 8, 20, 10, 55))

    assert result["status"] == "blocked"
    assert result["reason_code"].startswith("intraday_quote_stale")
    assert ledger.count("paper_runs") == 0


def test_intraday_lunch_window_skips_without_side_effects(tmp_path):
    ledger, service = _intraday_service(tmp_path)

    result = service.run_intraday(datetime(2026, 8, 20, 12, 0))

    assert result["status"] == "skipped"
    assert result["reason_code"] == "outside_intraday_window"
    assert ledger.count("paper_runs") == 0


def test_daily_fallback_does_not_replay_orders_after_same_session_intraday_completion(
    tmp_path,
):
    ledger, service = _intraday_service(
        tmp_path,
        quote_timestamp="20260821100000",
        selection_date="20260820",
        next_session_value="20260821",
    )
    prepared = service.run_due(datetime(2026, 8, 20, 17, 10))["prepared"]
    assert prepared["status"] == "prepared"

    intraday = service.run_intraday(datetime(2026, 8, 21, 10, 1))
    assert intraday["run"]["status"] == "completed"
    fill_count = ledger.count("paper_fills")

    due = service.run_due(datetime(2026, 8, 21, 17, 10))
    daily = ledger.get_run(prepared["run_id"])

    assert daily["status"] == "blocked"
    assert daily["reason_code"] == "superseded_by_intraday"
    assert due["settled"][0]["reason_code"] == "superseded_by_intraday"
    assert ledger.count("paper_fills") == fill_count

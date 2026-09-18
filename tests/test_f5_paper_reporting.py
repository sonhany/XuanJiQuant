from quant.paper_execution.ledger import PaperLedger
from quant.paper_execution.reporting import active_account_projection, status_projection


def _claim(ledger: PaperLedger, status: str):
    return ledger.claim_run(
        portfolio_id=f"portfolio-{status}",
        validation_id="validation-1",
        intended_session="20260820",
        policy_hash="a" * 64,
        input_hash="b" * 64,
        initial_status=status,
        reason_code="blocked_by_f4" if status == "blocked" else None,
    )


def test_status_separates_installed_capability_from_current_authority(tmp_path):
    ledger = PaperLedger(tmp_path / "f5.db")
    ledger.set_setting("enabled", True)
    blocked = _claim(ledger, "blocked")

    status = status_projection(ledger)

    assert status["paper_execution_capability"] is True
    assert status["paper_execution_authority"] is False
    assert status["latest_run"]["run_id"] == blocked["run_id"]
    assert status["reason_code"] == "blocked_by_f4"


def test_eligible_prepared_run_has_current_paper_authority(tmp_path):
    ledger = PaperLedger(tmp_path / "f5.db")
    ledger.set_setting("enabled", True)
    _claim(ledger, "prepared")

    status = status_projection(ledger)

    assert status["paper_execution_capability"] is True
    assert status["paper_execution_authority"] is True
    assert status["live_execution_authority"] is False


def test_status_exposes_strategy_quality_and_execution_lane(tmp_path):
    ledger = PaperLedger(tmp_path / "f5.db")
    ledger.set_setting("enabled", True)
    ledger.claim_run(
        portfolio_id="portfolio-experimental",
        validation_id="validation-1",
        intended_session="20260820",
        policy_hash="a" * 64,
        input_hash="b" * 64,
        initial_status="prepared",
        audit_context={
            "execution_lane": "experimental_paper",
            "strategy_quality_status": "unqualified",
            "f4_status": "f4_rejected",
            "f4_reasons": ["sharpe_below_0_80"],
            "research_generation_id": "generation-v1",
            "experimental_policy_version": "f5-experimental-paper-v1",
        },
    )

    status = status_projection(ledger)

    assert status["execution_lane"] == "experimental_paper"
    assert status["strategy_quality_status"] == "unqualified"
    assert status["f4_status"] == "f4_rejected"
    assert status["f4_reasons"] == ["sharpe_below_0_80"]
    assert status["research_generation_id"] == "generation-v1"
    assert status["live_execution_authority"] is False


def test_status_exposes_intraday_mode_and_quote_timestamp(tmp_path):
    ledger = PaperLedger(tmp_path / "f5.db")
    ledger.set_setting("enabled", True)
    ledger.claim_run(
        portfolio_id="portfolio-intraday",
        validation_id="validation-1",
        intended_session="20260820",
        policy_hash="a" * 64,
        input_hash="b" * 64,
        initial_status="completed",
        input_payload={
            "intraday_quotes": {
                "600016": {
                    "price": 3.42,
                    "quote_timestamp": "20260820105347",
                    "source": "tdx_quant",
                }
            }
        },
        audit_context={
            "execution_lane": "experimental_paper",
            "strategy_quality_status": "unqualified",
        },
    )

    status = status_projection(ledger)

    assert status["execution_mode"] == "paper_intraday"
    assert status["market_fact_timestamp"] == "20260820105347"
    assert status["market_fact_sources"] == ["tdx_quant"]


def test_status_projection_separates_current_readiness_from_historical_tail(tmp_path):
    ledger = PaperLedger(tmp_path / "f5.db")
    status = status_projection(
        ledger,
        current_readiness={
            "execution_mode": "paper_intraday",
            "execution_lane": "experimental_paper",
            "strategy_quality_status": "unqualified",
            "f4_status": "f4_rejected",
            "research_generation_id": "generation-current",
            "reason_code": "outside_intraday_window",
            "paper_execution_ready": True,
            "market_window_allowed": False,
        },
    )

    assert status["reason_code"] == "outside_intraday_window"
    assert status["execution_lane"] == "experimental_paper"
    assert status["current_readiness"]["paper_execution_ready"] is True


def test_active_account_projection_is_the_single_f5_account_contract(tmp_path):
    ledger = PaperLedger(tmp_path / "f5.db")
    run = _claim(ledger, "executing")
    order = {
        "order_id": "order-1",
        "client_order_id": "client-1",
        "code": "600519",
        "direction": "buy",
        "target_qty": 100,
        "current_qty": 0,
        "quantity": 100,
        "filled_qty": 0,
        "cancelled_qty": 0,
        "status": "planned",
    }
    ledger.store_planned_orders(run["run_id"], [order])
    settled = {
        **order,
        "filled_qty": 100,
        "status": "filled",
        "filled_price": 10.0,
    }
    ledger.apply_settlement_bundle(
        run_id=run["run_id"],
        orders=[settled],
        fills=[{
            "fill_id": "fill-1",
            "order_id": "order-1",
            "code": "600519",
            "direction": "buy",
            "quantity": 100,
            "price": 10.0,
        }],
        positions=[{
            "code": "600519",
            "quantity": 100,
            "available_qty": 0,
            "today_buy_qty": 100,
            "avg_price": 10.0,
            "current_price": 10.5,
        }],
        cash_entries=[{
            "entry_id": "cash-1",
            "order_id": "order-1",
            "fill_id": "fill-1",
            "entry_type": "buy",
            "amount": -1000.0,
            "balance_after": 999000.0,
        }],
        equity_snapshot={
            "snapshot_id": "snapshot-1",
            "run_id": run["run_id"],
            "cash": 999000.0,
            "market_value": 1050.0,
            "total_equity": 1000050.0,
            "daily_pnl": 50.0,
            "position_count": 1,
        },
    )

    projection = active_account_projection(
        ledger,
        1_000_000.0,
        name_resolver=lambda code: "贵州茅台" if code == "600519" else "",
    )

    assert projection["ledger_authority"] == "f5"
    assert projection["ledger"] == "data/paper/f5_ledger.db"
    assert projection["account"]["total_equity"] == 1000050.0
    assert projection["account"]["daily_pnl"] == 50.0
    assert projection["account"]["position_count"] == 1
    assert projection["positions"][0]["code"] == "600519"
    assert projection["positions"][0]["name"] == "贵州茅台"
    assert projection["positions"][0]["cost_value"] == 1000.0
    assert projection["positions"][0]["market_value"] == 1050.0
    assert projection["positions"][0]["unrealized_pnl"] == 50.0
    assert projection["positions"][0]["unrealized_pnl_pct"] == 5.0
    assert projection["positions"][0]["total_pnl"] == 50.0
    assert projection["positions"][0]["position_weight_pct"] > 0.10
    assert projection["account"]["unrealized_pnl"] == 50.0
    assert projection["account"]["realized_pnl"] == 0.0
    assert projection["orders"][0]["order_id"] == "order-1"
    assert projection["orders"][0]["name"] == "贵州茅台"
    assert projection["trades"][0]["fill_id"] == "fill-1"
    assert projection["trades"][0]["name"] == "贵州茅台"
    assert projection["equity_history"][0]["equity"] == 1000050.0


def test_active_account_projection_ignores_live_mark_from_older_execution_batch(tmp_path):
    ledger = PaperLedger(tmp_path / "stale-live-mark.db")
    first = ledger.claim_run(
        portfolio_id="portfolio-staged",
        validation_id="validation-1",
        intended_session="20260820",
        policy_hash="c" * 64,
        batch_index=0,
        input_hash="first-input",
        initial_status="completed",
    )
    ledger.apply_settlement_bundle(
        run_id=first["run_id"],
        orders=[],
        fills=[],
        positions=[{
            "code": "600519",
            "quantity": 100,
            "available_qty": 100,
            "today_buy_qty": 0,
            "avg_price": 10.0,
            "current_price": 10.0,
        }],
        cash_entries=[{
            "entry_id": "cash-first",
            "entry_type": "seed",
            "amount": -1000.0,
            "balance_after": 999000.0,
        }],
        equity_snapshot={
            "snapshot_id": "equity-first",
            "run_id": first["run_id"],
            "cash": 999000.0,
            "market_value": 1000.0,
            "total_equity": 1000000.0,
            "daily_pnl": 0.0,
            "position_count": 1,
        },
    )
    ledger.replace_live_marks(
        {
            "snapshot_id": "live-first",
            "quote_timestamp": "20260820110000",
            "received_at": "2026-08-20T03:00:00+00:00",
            "source": "tdx_quant",
            "stale": False,
        },
        [{
            "code": "600519",
            "price": 12.0,
            "quote_timestamp": "20260820110000",
            "source": "tdx_quant",
            "stale": False,
        }],
        {
            "run_id": first["run_id"],
            "market_snapshot_id": "live-first",
            "quote_timestamp": "20260820110000",
            "valuation_as_of": "2026-08-20T03:00:00+00:00",
            "cash": 999000.0,
            "market_value": 1200.0,
            "total_equity": 1000200.0,
            "daily_pnl": 200.0,
            "unrealized_pnl": 200.0,
            "position_count": 1,
            "stale": False,
            "daily_pnl_baseline": "previous_session_close",
        },
    )
    second = ledger.claim_run(
        portfolio_id="portfolio-staged",
        validation_id="validation-1",
        intended_session="20260820",
        policy_hash="c" * 64,
        batch_index=1,
        input_hash="second-input",
        initial_status="completed",
    )
    ledger.apply_settlement_bundle(
        run_id=second["run_id"],
        orders=[],
        fills=[],
        positions=[{
            "code": "600519",
            "quantity": 200,
            "available_qty": 100,
            "today_buy_qty": 100,
            "avg_price": 10.0,
            "current_price": 11.0,
        }],
        cash_entries=[{
            "entry_id": "cash-second",
            "entry_type": "buy",
            "amount": -1200.0,
            "balance_after": 997800.0,
        }],
        equity_snapshot={
            "snapshot_id": "equity-second",
            "run_id": second["run_id"],
            "cash": 997800.0,
            "market_value": 2200.0,
            "total_equity": 1000000.0,
            "daily_pnl": -200.0,
            "position_count": 1,
        },
    )

    projection = active_account_projection(ledger, 1_000_000.0)

    assert projection["account"]["total_equity"] == 1000000.0
    assert projection["account"]["market_value"] == 2200.0
    assert projection["account"]["valuation_as_of"] == projection["equity_history"][-1]["as_of"]
    assert projection["positions"][0]["current_price"] == 11.0


def test_f5_runner_account_uses_unified_runtime_projection(monkeypatch):
    from scripts import f5_paper_runner as runner

    sentinel = {"ledger_authority": "f5", "positions": [{"code": "600519", "name": "贵州茅台"}]}
    monkeypatch.setattr(
        runner,
        "load_active_account_projection",
        lambda limit=200: {**sentinel, "limit": limit},
        raising=False,
    )

    result = runner.handle({"action": "account", "limit": 25})

    assert result["data"] == {**sentinel, "limit": 25}

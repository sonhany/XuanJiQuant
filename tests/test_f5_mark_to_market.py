from __future__ import annotations

from datetime import datetime
import json

import pytest

from quant.paper_execution.ledger import PaperLedger
from quant.paper_execution.policy import PaperExecutionPolicy
from quant.paper_execution.reporting import active_account_projection
from quant.paper_execution.service import PaperExecutionService


def _seed_position(ledger: PaperLedger):
    run = ledger.claim_run(
        portfolio_id="portfolio-mark",
        validation_id="validation-mark",
        intended_session="20260901",
        policy_hash="a" * 64,
        input_hash="b" * 64,
        initial_status="executing",
    )
    order = {
        "order_id": "order-mark",
        "client_order_id": "client-mark",
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
    ledger.apply_settlement_bundle(
        run_id=run["run_id"],
        orders=[{**order, "filled_qty": 100, "status": "filled", "filled_price": 10.0}],
        fills=[{
            "fill_id": "fill-mark", "order_id": "order-mark", "code": "600519",
            "direction": "buy", "quantity": 100, "price": 10.0,
        }],
        positions=[{
            "code": "600519", "quantity": 100, "available_qty": 100,
            "today_buy_qty": 0, "avg_price": 10.0, "current_price": 10.5,
        }],
        cash_entries=[{
            "entry_id": "cash-mark", "order_id": "order-mark", "fill_id": "fill-mark",
            "entry_type": "buy", "amount": -1000.0, "balance_after": 999000.0,
        }],
        equity_snapshot={
            "snapshot_id": "equity-before-mark", "cash": 999000.0,
            "market_value": 1050.0, "total_equity": 1000050.0,
            "daily_pnl": 50.0, "position_count": 1,
        },
    )
    return run


def _service(ledger):
    return PaperExecutionService(
        ledger=ledger,
        policy=PaperExecutionPolicy(enabled=True),
        risk={},
        selection_loader=lambda: {},
        f4_loader=lambda: {},
        factor_loader=lambda: {},
        market_bar_loader=lambda _code, _date: None,
        next_session=lambda value: value,
    )


def _snapshot(*, stale=False, snapshot_id="market-snapshot-1"):
    return {
        "snapshot_id": snapshot_id,
        "quote_timestamp": "20260901093600",
        "received_at": "2026-09-01T09:36:01+08:00",
        "market_phase": "continuous_auction",
        "stale": stale,
        "quotes": {
            "600519": {
                "code": "600519", "price": 10.7, "source": "tdx_quant",
                "quote_timestamp": "20260901093600", "stale": stale,
            }
        },
    }


def _execution_facts(ledger):
    return json.dumps(
        {
            "orders": ledger.list_orders(),
            "fills": ledger.list_fills(),
            "cash": ledger.list_cash_entries(),
            "positions": ledger.list_positions(),
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


def test_mark_updates_live_equity_without_mutating_execution_facts(tmp_path):
    ledger = PaperLedger(tmp_path / "mark.db")
    _seed_position(ledger)
    service = _service(ledger)
    before = _execution_facts(ledger)

    out = service.mark_to_market(
        _snapshot(), now=datetime(2026, 9, 1, 9, 36, 1)
    )

    assert out["success"] is True
    assert out["market_snapshot_id"] == "market-snapshot-1"
    assert out["total_equity"] == pytest.approx(1_000_070.0)
    assert out["daily_pnl"] == pytest.approx(70.0)
    assert out["daily_pnl_baseline"] == "latest_equity_daily_pnl"
    assert out["valuation_as_of"] == "2026-09-01T01:36:01+00:00"
    assert _execution_facts(ledger) == before


def test_reporting_prefers_committed_live_mark_but_keeps_trade_position_facts(tmp_path):
    ledger = PaperLedger(tmp_path / "report.db")
    _seed_position(ledger)
    _service(ledger).mark_to_market(
        _snapshot(), now=datetime(2026, 9, 1, 9, 36, 1)
    )

    projection = active_account_projection(ledger, 1_000_000.0)

    assert projection["account"]["total_equity"] == pytest.approx(1_000_070.0)
    assert projection["account"]["daily_pnl"] == pytest.approx(70.0)
    assert projection["account"]["market_snapshot_id"] == "market-snapshot-1"
    assert projection["positions"][0]["current_price"] == pytest.approx(10.7)
    assert projection["positions"][0]["quantity"] == 100
    assert projection["positions"][0]["avg_price"] == pytest.approx(10.0)


def test_stale_or_incomplete_snapshot_does_not_replace_live_account(tmp_path):
    ledger = PaperLedger(tmp_path / "stale.db")
    _seed_position(ledger)
    service = _service(ledger)
    service.mark_to_market(_snapshot(), now=datetime(2026, 9, 1, 9, 36, 1))

    stale = service.mark_to_market(
        _snapshot(stale=True, snapshot_id="stale-snapshot"),
        now=datetime(2026, 9, 1, 9, 36, 2),
    )

    assert stale["success"] is False
    assert stale["reason_code"] == "market_snapshot_stale"
    assert ledger.live_account()["market_snapshot_id"] == "market-snapshot-1"


def test_hot_stale_snapshot_can_update_valuation_when_valuation_window_is_fresh(tmp_path):
    ledger = PaperLedger(tmp_path / "valuation-fresh.db")
    _seed_position(ledger)
    service = _service(ledger)
    snapshot = _snapshot(stale=True, snapshot_id="sina-valuation-snapshot")
    snapshot["valuation_stale"] = False
    snapshot["quotes"]["600519"]["valuation_stale"] = False

    out = service.mark_to_market(
        snapshot, now=datetime(2026, 9, 1, 9, 36, 8)
    )

    assert out["success"] is True
    assert out["market_snapshot_id"] == "sina-valuation-snapshot"


def test_duplicate_market_snapshot_is_idempotent(tmp_path):
    ledger = PaperLedger(tmp_path / "duplicate.db")
    _seed_position(ledger)
    service = _service(ledger)
    first = service.mark_to_market(
        _snapshot(), now=datetime(2026, 9, 1, 9, 36, 1)
    )

    second = service.mark_to_market(
        _snapshot(), now=datetime(2026, 9, 1, 9, 36, 2)
    )

    assert first["success"] is True
    assert second["success"] is True
    assert second["idempotent"] is True
    assert ledger.live_account()["market_snapshot_id"] == "market-snapshot-1"


@pytest.mark.parametrize("field", ["codes", "quotes", "price", "quantity", "cash", "date"])
def test_runner_rejects_mark_to_market_business_parameters(monkeypatch, field):
    from scripts import f5_paper_runner as runner

    monkeypatch.setattr(
        runner.service,
        "mark_to_market",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not execute")),
        raising=False,
    )
    out = runner.handle({"action": "mark_to_market", field: "forbidden"})

    assert out["success"] is False
    assert out["reason"] == "mark_to_market_parameters_forbidden"

from __future__ import annotations

import json

import pytest

from quant.paper_execution.ledger import PaperLedger


def _ledger(tmp_path):
    return PaperLedger(tmp_path / "f5-live-marks.db")


def _run(ledger):
    return ledger.claim_run(
        portfolio_id="portfolio-live",
        validation_id="validation-live",
        intended_session="20260901",
        policy_hash="a" * 64,
        input_hash="b" * 64,
        initial_status="prepared",
    )


def _batch(snapshot_id="snapshot-1"):
    return {
        "snapshot_id": snapshot_id,
        "quote_timestamp": "20260901093501",
        "received_at": "2026-09-01T09:35:02+08:00",
        "source": "tdx_quant",
        "stale": False,
    }


def _marks():
    return [
        {"code": "600519", "price": 1190.0, "quote_timestamp": "20260901093501", "source": "tdx_quant", "stale": False},
        {"code": "000001", "price": 11.7, "quote_timestamp": "20260901093501", "source": "tdx_quant", "stale": False},
    ]


def _account(run_id, snapshot_id="snapshot-1"):
    return {
        "run_id": run_id,
        "market_snapshot_id": snapshot_id,
        "quote_timestamp": "20260901093501",
        "valuation_as_of": "2026-09-01T09:35:02+08:00",
        "cash": 100000.0,
        "market_value": 50000.0,
        "total_equity": 150000.0,
        "daily_pnl": 500.0,
        "unrealized_pnl": 400.0,
        "position_count": 2,
        "stale": False,
        "daily_pnl_baseline": "previous_session_close",
    }


def _trade_counts(ledger):
    return {
        table: ledger.count(table)
        for table in ("paper_orders", "paper_fills", "paper_cash_ledger", "paper_positions")
    }


def test_live_mark_schema_is_additive_and_initially_empty(tmp_path):
    ledger = _ledger(tmp_path)

    assert {"paper_live_marks", "paper_live_account"}.issubset(ledger.table_names())
    assert ledger.live_marks() == []
    assert ledger.live_account() is None


def test_replace_live_marks_is_atomic_and_preserves_trade_facts(tmp_path):
    ledger = _ledger(tmp_path)
    run = _run(ledger)
    before = _trade_counts(ledger)

    ledger.replace_live_marks(_batch(), _marks(), _account(run["run_id"]))

    assert ledger.live_account()["market_snapshot_id"] == "snapshot-1"
    assert [row["code"] for row in ledger.live_marks()] == ["000001", "600519"]
    assert _trade_counts(ledger) == before


def test_same_snapshot_is_idempotent_but_identity_collision_fails(tmp_path):
    ledger = _ledger(tmp_path)
    run = _run(ledger)
    account = _account(run["run_id"])
    ledger.replace_live_marks(_batch(), _marks(), account)
    ledger.replace_live_marks(_batch(), _marks(), account)
    assert ledger.count("paper_live_marks") == 2

    collision = dict(account)
    collision["total_equity"] = 999999.0
    with pytest.raises(ValueError, match="live_mark_identity_collision"):
        ledger.replace_live_marks(_batch(), _marks(), collision)


def test_mark_equity_history_is_throttled_to_thirty_seconds(tmp_path):
    ledger = _ledger(tmp_path)
    run = _run(ledger)
    account = _account(run["run_id"])
    ledger.replace_live_marks(_batch(), _marks(), account)

    assert ledger.maybe_append_equity_from_mark(account, now="2026-09-01T01:35:02+00:00") is True
    assert ledger.maybe_append_equity_from_mark(account, now="2026-09-01T01:35:31+00:00") is False
    assert ledger.maybe_append_equity_from_mark(account, now="2026-09-01T01:35:32+00:00") is True
    assert ledger.count("paper_equity_snapshots") == 2


def test_live_mark_batch_rejects_duplicate_code_and_mismatched_account(tmp_path):
    ledger = _ledger(tmp_path)
    run = _run(ledger)
    marks = _marks()
    with pytest.raises(ValueError, match="live_mark_duplicate_code"):
        ledger.replace_live_marks(_batch(), [marks[0], marks[0]], _account(run["run_id"]))
    with pytest.raises(ValueError, match="live_mark_snapshot_mismatch"):
        ledger.replace_live_marks(_batch(), marks, _account(run["run_id"], snapshot_id="other"))

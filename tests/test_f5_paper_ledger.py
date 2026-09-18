import hashlib
import sqlite3

import pytest

from quant.paper_execution.contracts import InvalidStateTransition, stable_id
from quant.paper_execution.ledger import PaperLedger


def _ledger(tmp_path):
    return PaperLedger(tmp_path / "f5-ledger.db")


def test_stable_id_is_deterministic_and_namespaced():
    first = stable_id("paper_run", "portfolio-1", "20260820", "policy-v1")
    second = stable_id("paper_run", "portfolio-1", "20260820", "policy-v1")
    assert first == second
    assert first.startswith("paper_run_")
    assert len(first.split("_", 2)[-1]) == 64


def test_ledger_creates_only_neutral_f5_tables(tmp_path):
    ledger = _ledger(tmp_path)
    tables = set(ledger.table_names())
    assert {
        "paper_settings",
        "paper_runs",
        "paper_orders",
        "paper_fills",
        "paper_positions",
        "paper_cash_ledger",
        "paper_equity_snapshots",
        "paper_live_marks",
        "paper_live_account",
        "paper_reconciliations",
        "paper_audit_events",
    }.issubset(tables)
    assert not any("agent" in name or name.startswith("ai_") for name in tables)


def test_claim_run_is_idempotent(tmp_path):
    ledger = _ledger(tmp_path)
    first = ledger.claim_run(
        portfolio_id="portfolio-1",
        validation_id="validation-1",
        intended_session="20260820",
        policy_hash="a" * 64,
        input_hash="b" * 64,
        initial_status="prepared",
    )
    second = ledger.claim_run(
        portfolio_id="portfolio-1",
        validation_id="validation-1",
        intended_session="20260820",
        policy_hash="a" * 64,
        input_hash="b" * 64,
        initial_status="prepared",
    )
    assert first["run_id"] == second["run_id"]
    assert first["created"] is True
    assert second["created"] is False
    assert ledger.count("paper_runs") == 1


def test_planned_order_sequence_survives_ledger_round_trip(tmp_path):
    """Catches hashed order IDs reordering sell-first plans into buy-first execution."""
    ledger = _ledger(tmp_path)
    run = ledger.claim_run(
        portfolio_id="portfolio-sequence",
        validation_id="validation-1",
        intended_session="20260828",
        policy_hash="a" * 64,
        input_hash="b" * 64,
        initial_status="prepared",
    )
    sell = {
        "order_id": "z-sell-order",
        "client_order_id": "z-sell-client",
        "code": "600000",
        "direction": "sell",
        "target_qty": 0,
        "current_qty": 100,
        "quantity": 100,
        "request_price": 10.0,
    }
    buy = {
        "order_id": "a-buy-order",
        "client_order_id": "a-buy-client",
        "code": "000001",
        "direction": "buy",
        "target_qty": 100,
        "current_qty": 0,
        "quantity": 100,
        "request_price": 10.0,
    }

    ledger.store_planned_orders(run["run_id"], [sell, buy])
    restored = ledger.list_orders(run["run_id"])

    assert [row["direction"] for row in restored] == ["sell", "buy"]
    assert [row["sequence_no"] for row in restored] == [0, 1]


def test_claim_run_persists_experimental_audit_context(tmp_path):
    ledger = _ledger(tmp_path)
    run = ledger.claim_run(
        portfolio_id="portfolio-experimental",
        validation_id="validation-v1",
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

    assert run["execution_lane"] == "experimental_paper"
    assert run["strategy_quality_status"] == "unqualified"
    assert run["f4_status"] == "f4_rejected"
    assert run["f4_reasons"] == ["sharpe_below_0_80"]
    assert run["research_generation_id"] == "generation-v1"
    assert run["experimental_policy_version"] == "f5-experimental-paper-v1"


def test_old_ledger_migrates_without_rewriting_historical_runs(tmp_path):
    path = tmp_path / "f5-v2.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE paper_runs (
            run_id TEXT PRIMARY KEY,
            run_key TEXT NOT NULL UNIQUE,
            portfolio_id TEXT NOT NULL,
            validation_id TEXT NOT NULL,
            intended_session TEXT NOT NULL,
            policy_hash TEXT NOT NULL,
            input_hash TEXT NOT NULL,
            input_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL,
            reason_code TEXT,
            owner_pid INTEGER,
            lease_expires_at REAL,
            order_count INTEGER NOT NULL DEFAULT 0,
            fill_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO paper_runs(
            run_id,run_key,portfolio_id,validation_id,intended_session,
            policy_hash,input_hash,input_json,status,reason_code,created_at,updated_at
        ) VALUES(
            'historical-run','historical-key','historical-portfolio','historical-validation',
            '20260819','policy','input','{}','blocked','blocked_by_f4',
            '2026-08-19T16:40:00+00:00','2026-08-19T16:40:00+00:00'
        );
        PRAGMA user_version=2;
        """
    )
    connection.commit()
    connection.close()

    ledger = PaperLedger(path)
    old = ledger.list_runs()[0]

    assert old["run_id"] == "historical-run"
    assert old["execution_lane"] == "legacy_unknown"
    assert old["strategy_quality_status"] == "unknown"
    assert old["f4_reasons"] == []
    assert old["batch_index"] == 0
    assert sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0] == 6


def test_run_identity_collision_fails_closed(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.claim_run(
        portfolio_id="portfolio-1",
        validation_id="validation-1",
        intended_session="20260820",
        policy_hash="a" * 64,
        input_hash="b" * 64,
        initial_status="prepared",
    )
    with pytest.raises(ValueError, match="run_identity_collision"):
        ledger.claim_run(
            portfolio_id="portfolio-1",
            validation_id="validation-2",
            intended_session="20260820",
            policy_hash="a" * 64,
            input_hash="c" * 64,
            initial_status="prepared",
        )


def test_state_machine_rejects_invalid_terminal_transition(tmp_path):
    ledger = _ledger(tmp_path)
    run = ledger.claim_run(
        portfolio_id="portfolio-1",
        validation_id="validation-1",
        intended_session="20260820",
        policy_hash="a" * 64,
        input_hash="b" * 64,
        initial_status="blocked",
        reason_code="blocked_by_f4",
    )
    with pytest.raises(InvalidStateTransition):
        ledger.transition_run(run["run_id"], "executing")


def test_lease_owner_cannot_be_stolen_before_expiry(tmp_path):
    ledger = _ledger(tmp_path)
    run = ledger.claim_run(
        portfolio_id="portfolio-1",
        validation_id="validation-1",
        intended_session="20260820",
        policy_hash="a" * 64,
        input_hash="b" * 64,
        initial_status="prepared",
    )
    assert ledger.acquire_lease(run["run_id"], owner_pid=101, now=1000.0, ttl_seconds=60)
    assert not ledger.acquire_lease(run["run_id"], owner_pid=202, now=1050.0, ttl_seconds=60)
    assert ledger.acquire_lease(run["run_id"], owner_pid=202, now=1061.0, ttl_seconds=60)


def test_execution_bundle_is_atomic_on_duplicate_fill(tmp_path):
    ledger = _ledger(tmp_path)
    run = ledger.claim_run(
        portfolio_id="portfolio-1",
        validation_id="validation-1",
        intended_session="20260820",
        policy_hash="a" * 64,
        input_hash="b" * 64,
        initial_status="executing",
    )
    order = {
        "order_id": "order-1",
        "client_order_id": "client-1",
        "code": "600519",
        "direction": "buy",
        "quantity": 100,
        "filled_qty": 100,
        "cancelled_qty": 0,
        "status": "filled",
    }
    duplicate_fills = [
        {"fill_id": "fill-1", "order_id": "order-1", "code": "600519", "direction": "buy", "quantity": 100, "price": 10.0},
        {"fill_id": "fill-1", "order_id": "order-1", "code": "600519", "direction": "buy", "quantity": 100, "price": 10.0},
    ]
    with pytest.raises(sqlite3.IntegrityError):
        ledger.apply_execution_bundle(
            run_id=run["run_id"],
            orders=[order],
            fills=duplicate_fills,
            positions=[{"code": "600519", "quantity": 100, "available_qty": 0, "today_buy_qty": 100, "avg_price": 10.0, "current_price": 10.0}],
            cash_entries=[{"entry_id": "cash-1", "entry_type": "buy", "amount": -1000.0, "balance_after": 999000.0}],
        )
    assert ledger.count("paper_orders") == 0
    assert ledger.count("paper_fills") == 0
    assert ledger.count("paper_positions") == 0
    assert ledger.count("paper_cash_ledger") == 0


def test_independent_ledger_does_not_touch_quant_db(tmp_path):
    quant_db = tmp_path / "quant.db"
    quant_db.write_bytes(b"historical-audit-fact")
    before = hashlib.sha256(quant_db.read_bytes()).hexdigest()
    ledger = _ledger(tmp_path)
    ledger.set_setting("enabled", True)
    after = hashlib.sha256(quant_db.read_bytes()).hexdigest()
    assert before == after

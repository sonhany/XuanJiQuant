"""Persistent and auditable F5 paper-execution ledger."""

from __future__ import annotations

import json
import hashlib
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from .contracts import stable_id, validate_run_state, validate_transition


SCHEMA_VERSION = 6


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _public_run(row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
    value = dict(row)
    value.pop("input_json", None)
    raw_reasons = value.pop("f4_reasons_json", "[]")
    try:
        reasons = json.loads(raw_reasons) if isinstance(raw_reasons, str) else raw_reasons
    except json.JSONDecodeError:
        reasons = []
    value["f4_reasons"] = reasons if isinstance(reasons, list) else []
    return value


class PaperLedger:
    """Owns the independent F5 SQLite ledger and its atomic operations."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, timeout=5.0, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._create_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _create_schema(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS paper_settings (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS paper_runs (
            run_id TEXT PRIMARY KEY,
            run_key TEXT NOT NULL UNIQUE,
            portfolio_id TEXT NOT NULL,
            validation_id TEXT NOT NULL,
            intended_session TEXT NOT NULL,
            policy_hash TEXT NOT NULL,
            batch_index INTEGER NOT NULL DEFAULT 0,
            input_hash TEXT NOT NULL,
            input_json TEXT NOT NULL DEFAULT '{}',
            execution_lane TEXT NOT NULL DEFAULT 'legacy_unknown',
            strategy_quality_status TEXT NOT NULL DEFAULT 'unknown',
            f4_status TEXT,
            f4_reasons_json TEXT NOT NULL DEFAULT '[]',
            research_generation_id TEXT,
            experimental_policy_version TEXT,
            status TEXT NOT NULL,
            reason_code TEXT,
            owner_pid INTEGER,
            lease_expires_at REAL,
            order_count INTEGER NOT NULL DEFAULT 0,
            fill_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS paper_orders (
            order_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES paper_runs(run_id),
            client_order_id TEXT NOT NULL UNIQUE,
            code TEXT NOT NULL,
            direction TEXT NOT NULL,
            target_qty INTEGER NOT NULL DEFAULT 0,
            current_qty INTEGER NOT NULL DEFAULT 0,
            sequence_no INTEGER NOT NULL DEFAULT 0,
            quantity INTEGER NOT NULL,
            filled_qty INTEGER NOT NULL DEFAULT 0,
            cancelled_qty INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            reject_reason TEXT,
            request_price REAL,
            filled_price REAL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS paper_fills (
            fill_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES paper_runs(run_id),
            order_id TEXT NOT NULL REFERENCES paper_orders(order_id),
            code TEXT NOT NULL,
            direction TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price REAL NOT NULL,
            commission REAL NOT NULL DEFAULT 0,
            stamp_tax REAL NOT NULL DEFAULT 0,
            slippage REAL NOT NULL DEFAULT 0,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS paper_positions (
            code TEXT PRIMARY KEY,
            quantity INTEGER NOT NULL,
            available_qty INTEGER NOT NULL,
            today_buy_qty INTEGER NOT NULL DEFAULT 0,
            avg_price REAL NOT NULL,
            current_price REAL NOT NULL,
            realized_pnl REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS paper_cash_ledger (
            entry_id TEXT PRIMARY KEY,
            run_id TEXT REFERENCES paper_runs(run_id),
            order_id TEXT,
            fill_id TEXT,
            entry_type TEXT NOT NULL,
            amount REAL NOT NULL,
            balance_after REAL NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS paper_equity_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES paper_runs(run_id),
            cash REAL NOT NULL,
            market_value REAL NOT NULL,
            total_equity REAL NOT NULL,
            daily_pnl REAL NOT NULL DEFAULT 0,
            drawdown_pct REAL NOT NULL DEFAULT 0,
            position_count INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS paper_live_marks (
            code TEXT PRIMARY KEY,
            snapshot_id TEXT NOT NULL,
            quote_timestamp TEXT NOT NULL,
            source TEXT NOT NULL,
            price REAL NOT NULL,
            received_at TEXT NOT NULL,
            stale INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS paper_live_account (
            singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
            run_id TEXT NOT NULL REFERENCES paper_runs(run_id),
            market_snapshot_id TEXT NOT NULL,
            quote_timestamp TEXT NOT NULL,
            valuation_as_of TEXT NOT NULL,
            cash REAL NOT NULL,
            market_value REAL NOT NULL,
            total_equity REAL NOT NULL,
            daily_pnl REAL NOT NULL,
            unrealized_pnl REAL NOT NULL,
            position_count INTEGER NOT NULL,
            stale INTEGER NOT NULL DEFAULT 0,
            daily_pnl_baseline TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS paper_reconciliations (
            check_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES paper_runs(run_id),
            check_name TEXT NOT NULL,
            passed INTEGER NOT NULL,
            expected_json TEXT NOT NULL,
            actual_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS paper_audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT REFERENCES paper_runs(run_id),
            event_type TEXT NOT NULL,
            reason_code TEXT,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_paper_runs_session ON paper_runs(intended_session, created_at);
        CREATE INDEX IF NOT EXISTS idx_paper_orders_run ON paper_orders(run_id);
        CREATE INDEX IF NOT EXISTS idx_paper_fills_run ON paper_fills(run_id);
        """
        with self._lock:
            self._conn.executescript(schema)
            columns = {
                str(row[1])
                for row in self._conn.execute("PRAGMA table_info(paper_runs)").fetchall()
            }
            if "input_json" not in columns:
                self._conn.execute(
                    "ALTER TABLE paper_runs ADD COLUMN input_json TEXT NOT NULL DEFAULT '{}'"
                )
            migrations = {
                "execution_lane": "TEXT NOT NULL DEFAULT 'legacy_unknown'",
                "strategy_quality_status": "TEXT NOT NULL DEFAULT 'unknown'",
                "f4_status": "TEXT",
                "f4_reasons_json": "TEXT NOT NULL DEFAULT '[]'",
                "research_generation_id": "TEXT",
                "experimental_policy_version": "TEXT",
                "batch_index": "INTEGER NOT NULL DEFAULT 0",
            }
            for name, definition in migrations.items():
                if name not in columns:
                    self._conn.execute(
                        f'ALTER TABLE paper_runs ADD COLUMN "{name}" {definition}'
                    )
            order_columns = {
                str(row[1])
                for row in self._conn.execute(
                    "PRAGMA table_info(paper_orders)"
                ).fetchall()
            }
            if "sequence_no" not in order_columns:
                self._conn.execute(
                    "ALTER TABLE paper_orders ADD COLUMN sequence_no INTEGER NOT NULL DEFAULT 0"
                )
            self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            self._conn.commit()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.rollback()
                raise
            else:
                self._conn.commit()

    def table_names(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        return [str(row[0]) for row in rows]

    def count(self, table: str) -> int:
        if table not in self.table_names():
            raise ValueError(f"unknown_table:{table}")
        with self._lock:
            return int(self._conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])

    def set_setting(self, key: str, value: Any) -> None:
        now = _utc_now()
        with self._transaction() as conn:
            conn.execute(
                """INSERT INTO paper_settings(key, value_json, updated_at) VALUES(?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at""",
                (key, _json(value), now),
            )

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._conn.execute(
                "SELECT value_json FROM paper_settings WHERE key=?", (key,)
            ).fetchone()
        return default if row is None else json.loads(row[0])

    def claim_run(
        self,
        *,
        portfolio_id: str,
        validation_id: str,
        intended_session: str,
        policy_hash: str,
        batch_index: int = 0,
        input_hash: str,
        initial_status: str,
        reason_code: str | None = None,
        input_payload: Mapping[str, Any] | None = None,
        audit_context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        validate_run_state(initial_status)
        batch_index = int(batch_index)
        if batch_index < 0:
            raise ValueError("paper_run_batch_index_invalid")
        run_key = (
            stable_id("paper_run", portfolio_id, intended_session, policy_hash)
            if batch_index == 0
            else stable_id(
                "paper_run", portfolio_id, intended_session, policy_hash, "batch", batch_index
            )
        )
        run_id = stable_id("paper_run_record", run_key)
        now = _utc_now()
        audit = dict(audit_context or {})
        execution_lane = str(audit.get("execution_lane") or "legacy_unknown")
        quality_status = str(audit.get("strategy_quality_status") or "unknown")
        f4_status = str(audit.get("f4_status") or "") or None
        raw_f4_reasons = audit.get("f4_reasons") or []
        if not isinstance(raw_f4_reasons, (list, tuple)):
            raise ValueError("f4_reasons_invalid")
        f4_reasons = [str(value) for value in raw_f4_reasons if str(value)]
        generation_id = str(audit.get("research_generation_id") or "") or None
        experimental_version = str(audit.get("experimental_policy_version") or "") or None
        with self._transaction() as conn:
            row = conn.execute("SELECT * FROM paper_runs WHERE run_key=?", (run_key,)).fetchone()
            if row is not None:
                if row["validation_id"] != validation_id or row["input_hash"] != input_hash:
                    raise ValueError("run_identity_collision")
                result = _public_run(row)
                result["created"] = False
                return result
            conn.execute(
                """INSERT INTO paper_runs(
                    run_id, run_key, portfolio_id, validation_id, intended_session,
                    policy_hash, batch_index, input_hash, input_json, execution_lane,
                    strategy_quality_status, f4_status, f4_reasons_json,
                    research_generation_id, experimental_policy_version,
                    status, reason_code, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    run_key,
                    portfolio_id,
                    validation_id,
                    intended_session,
                    policy_hash,
                    batch_index,
                    input_hash,
                    _json(dict(input_payload or {})),
                    execution_lane,
                    quality_status,
                    f4_status,
                    _json(f4_reasons),
                    generation_id,
                    experimental_version,
                    initial_status,
                    reason_code,
                    now,
                    now,
                ),
            )
            conn.execute(
                "INSERT INTO paper_audit_events(run_id,event_type,reason_code,payload_json,created_at) VALUES(?,?,?,?,?)",
                (
                    run_id,
                    "run_claimed",
                    reason_code,
                    _json(
                        {
                            "status": initial_status,
                            "batch_index": batch_index,
                            "execution_lane": execution_lane,
                            "strategy_quality_status": quality_status,
                        }
                    ),
                    now,
                ),
            )
            result = _public_run(conn.execute("SELECT * FROM paper_runs WHERE run_id=?", (run_id,)).fetchone())
            result["created"] = True
            return result

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM paper_runs WHERE run_id=?", (run_id,)).fetchone()
        return None if row is None else _public_run(row)

    def transition_run(self, run_id: str, new_state: str, reason_code: str | None = None) -> dict[str, Any]:
        now = _utc_now()
        with self._transaction() as conn:
            row = conn.execute("SELECT * FROM paper_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(f"unknown_run:{run_id}")
            validate_transition(str(row["status"]), new_state)
            conn.execute(
                "UPDATE paper_runs SET status=?, reason_code=?, updated_at=? WHERE run_id=?",
                (new_state, reason_code, now, run_id),
            )
            conn.execute(
                "INSERT INTO paper_audit_events(run_id,event_type,reason_code,payload_json,created_at) VALUES(?,?,?,?,?)",
                (run_id, "run_transition", reason_code, _json({"from": row["status"], "to": new_state}), now),
            )
            return _public_run(conn.execute("SELECT * FROM paper_runs WHERE run_id=?", (run_id,)).fetchone())

    def find_run(
        self,
        portfolio_id: str,
        intended_session: str,
        policy_hash: str,
        batch_index: int = 0,
    ) -> dict[str, Any] | None:
        run_key = (
            stable_id("paper_run", portfolio_id, intended_session, policy_hash)
            if int(batch_index) == 0
            else stable_id(
                "paper_run",
                portfolio_id,
                intended_session,
                policy_hash,
                "batch",
                int(batch_index),
            )
        )
        with self._lock:
            row = self._conn.execute("SELECT * FROM paper_runs WHERE run_key=?", (run_key,)).fetchone()
        return None if row is None else _public_run(row)

    def list_execution_runs(
        self, portfolio_id: str, intended_session: str, policy_hash: str
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM paper_runs
                   WHERE portfolio_id=? AND intended_session=? AND policy_hash=?
                   ORDER BY batch_index, created_at, rowid""",
                (portfolio_id, intended_session, policy_hash),
            ).fetchall()
        return [_public_run(row) for row in rows]

    def list_runs(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = "SELECT * FROM paper_runs"
        params: list[Any] = []
        if status:
            query += " WHERE status=?"
            params.append(status)
        query += " ORDER BY intended_session DESC, created_at DESC LIMIT ?"
        params.append(int(limit))
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [_public_run(row) for row in rows]

    def run_input(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute("SELECT input_json FROM paper_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown_run:{run_id}")
        return dict(json.loads(row[0] or "{}"))

    def store_planned_orders(self, run_id: str, orders: Iterable[Mapping[str, Any]]) -> None:
        rows = list(orders)
        now = _utc_now()
        with self._transaction() as conn:
            for sequence_no, order in enumerate(rows):
                conn.execute(
                    """INSERT INTO paper_orders(
                        order_id,run_id,client_order_id,code,direction,target_qty,current_qty,
                        sequence_no,quantity,filled_qty,cancelled_qty,status,reject_reason,request_price,
                        filled_price,payload_json,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        order["order_id"], run_id, order["client_order_id"], order["code"], order["direction"],
                        int(order.get("target_qty", 0)), int(order.get("current_qty", 0)), int(sequence_no),
                        int(order["quantity"]), 0, 0, "planned", None, order.get("request_price"), None,
                        _json(dict(order)), now, now,
                    ),
                )
            conn.execute(
                "UPDATE paper_runs SET order_count=?, updated_at=? WHERE run_id=?",
                (len(rows), now, run_id),
            )

    def list_orders(self, run_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        query = "SELECT * FROM paper_orders"
        params: list[Any] = []
        if run_id:
            query += " WHERE run_id=?"
            params.append(run_id)
        query += " ORDER BY created_at, sequence_no, order_id LIMIT ?"
        params.append(int(limit))
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def list_fills(self, run_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        query = "SELECT * FROM paper_fills"
        params: list[Any] = []
        if run_id:
            query += " WHERE run_id=?"
            params.append(run_id)
        query += " ORDER BY created_at, fill_id LIMIT ?"
        params.append(int(limit))
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def list_cash_entries(self, run_id: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        query = "SELECT * FROM paper_cash_ledger"
        params: list[Any] = []
        if run_id:
            query += " WHERE run_id=?"
            params.append(run_id)
        query += " ORDER BY created_at, entry_id LIMIT ?"
        params.append(int(limit))
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def list_positions(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM paper_positions WHERE quantity <> 0 ORDER BY code"
            ).fetchall()
        return [dict(row) for row in rows]

    def live_marks(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM paper_live_marks ORDER BY code"
            ).fetchall()
        output = []
        for source in rows:
            row = dict(source)
            row["stale"] = bool(row.get("stale"))
            output.append(row)
        return output

    def live_account(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM paper_live_account WHERE singleton_id=1"
            ).fetchone()
        if row is None:
            return None
        output = dict(row)
        output["stale"] = bool(output.get("stale"))
        return output

    def replace_live_marks(
        self,
        batch: Mapping[str, Any],
        marks: Iterable[Mapping[str, Any]],
        account: Mapping[str, Any],
    ) -> None:
        snapshot_id = str(batch.get("snapshot_id") or "")
        if not snapshot_id:
            raise ValueError("live_mark_snapshot_missing")
        if str(account.get("market_snapshot_id") or "") != snapshot_id:
            raise ValueError("live_mark_snapshot_mismatch")
        mark_rows = [dict(row) for row in marks]
        codes = [str(row.get("code") or "").zfill(6) for row in mark_rows]
        if not codes or any(not code.isdigit() or len(code) != 6 for code in codes):
            raise ValueError("live_mark_code_invalid")
        if len(codes) != len(set(codes)):
            raise ValueError("live_mark_duplicate_code")
        normalized_marks = []
        for code, source in zip(codes, mark_rows, strict=True):
            price = float(source.get("price") or 0)
            if price <= 0:
                raise ValueError("live_mark_price_invalid")
            normalized_marks.append(
                {
                    "code": code,
                    "snapshot_id": snapshot_id,
                    "quote_timestamp": str(source.get("quote_timestamp") or batch.get("quote_timestamp") or ""),
                    "source": str(source.get("source") or batch.get("source") or ""),
                    "price": price,
                    "received_at": str(batch.get("received_at") or account.get("valuation_as_of") or ""),
                    "stale": bool(source.get("stale", batch.get("stale", False))),
                }
            )
        normalized_marks.sort(key=lambda row: row["code"])
        normalized_account = {
            "run_id": str(account.get("run_id") or ""),
            "market_snapshot_id": snapshot_id,
            "quote_timestamp": str(account.get("quote_timestamp") or batch.get("quote_timestamp") or ""),
            "valuation_as_of": str(account.get("valuation_as_of") or batch.get("received_at") or ""),
            "cash": float(account.get("cash") or 0),
            "market_value": float(account.get("market_value") or 0),
            "total_equity": float(account.get("total_equity") or 0),
            "daily_pnl": float(account.get("daily_pnl") or 0),
            "unrealized_pnl": float(account.get("unrealized_pnl") or 0),
            "position_count": int(account.get("position_count") or 0),
            "stale": bool(account.get("stale", batch.get("stale", False))),
            "daily_pnl_baseline": str(account.get("daily_pnl_baseline") or ""),
        }
        if not normalized_account["run_id"] or not normalized_account["valuation_as_of"]:
            raise ValueError("live_mark_account_identity_missing")
        content_hash = hashlib.sha256(
            _json({"marks": normalized_marks, "account": normalized_account}).encode("utf-8")
        ).hexdigest()
        now = _utc_now()
        with self._transaction() as conn:
            existing = conn.execute(
                "SELECT market_snapshot_id,content_hash FROM paper_live_account WHERE singleton_id=1"
            ).fetchone()
            if existing is not None and str(existing["market_snapshot_id"]) == snapshot_id:
                if str(existing["content_hash"]) != content_hash:
                    raise ValueError("live_mark_identity_collision")
                return
            conn.execute("DELETE FROM paper_live_marks")
            for row in normalized_marks:
                conn.execute(
                    """INSERT INTO paper_live_marks(
                        code,snapshot_id,quote_timestamp,source,price,received_at,stale,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        row["code"], row["snapshot_id"], row["quote_timestamp"], row["source"],
                        row["price"], row["received_at"], 1 if row["stale"] else 0, now,
                    ),
                )
            conn.execute(
                """INSERT INTO paper_live_account(
                    singleton_id,run_id,market_snapshot_id,quote_timestamp,valuation_as_of,
                    cash,market_value,total_equity,daily_pnl,unrealized_pnl,position_count,
                    stale,daily_pnl_baseline,content_hash,updated_at
                ) VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(singleton_id) DO UPDATE SET
                    run_id=excluded.run_id,market_snapshot_id=excluded.market_snapshot_id,
                    quote_timestamp=excluded.quote_timestamp,valuation_as_of=excluded.valuation_as_of,
                    cash=excluded.cash,market_value=excluded.market_value,total_equity=excluded.total_equity,
                    daily_pnl=excluded.daily_pnl,unrealized_pnl=excluded.unrealized_pnl,
                    position_count=excluded.position_count,stale=excluded.stale,
                    daily_pnl_baseline=excluded.daily_pnl_baseline,
                    content_hash=excluded.content_hash,updated_at=excluded.updated_at""",
                (
                    normalized_account["run_id"], snapshot_id, normalized_account["quote_timestamp"],
                    normalized_account["valuation_as_of"], normalized_account["cash"],
                    normalized_account["market_value"], normalized_account["total_equity"],
                    normalized_account["daily_pnl"], normalized_account["unrealized_pnl"],
                    normalized_account["position_count"], 1 if normalized_account["stale"] else 0,
                    normalized_account["daily_pnl_baseline"], content_hash, now,
                ),
            )

    def maybe_append_equity_from_mark(
        self,
        account: Mapping[str, Any],
        *,
        minimum_interval_seconds: int = 30,
        now: str | None = None,
        force: bool = False,
    ) -> bool:
        created_at = str(now or _utc_now())
        current = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        with self._transaction() as conn:
            latest = conn.execute(
                "SELECT created_at FROM paper_equity_snapshots ORDER BY created_at DESC,rowid DESC LIMIT 1"
            ).fetchone()
            if latest is not None and not force:
                previous = datetime.fromisoformat(str(latest["created_at"]).replace("Z", "+00:00"))
                if (current - previous).total_seconds() < int(minimum_interval_seconds):
                    return False
            run_id = str(account.get("run_id") or "")
            if conn.execute("SELECT 1 FROM paper_runs WHERE run_id=?", (run_id,)).fetchone() is None:
                raise ValueError("live_mark_run_missing")
            snapshot_id = stable_id(
                "paper_equity_mark",
                str(account.get("market_snapshot_id") or ""),
                created_at,
            )
            conn.execute(
                """INSERT INTO paper_equity_snapshots(
                    snapshot_id,run_id,cash,market_value,total_equity,daily_pnl,
                    drawdown_pct,position_count,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    snapshot_id, run_id, float(account.get("cash") or 0),
                    float(account.get("market_value") or 0), float(account.get("total_equity") or 0),
                    float(account.get("daily_pnl") or 0), float(account.get("drawdown_pct") or 0),
                    int(account.get("position_count") or 0), created_at,
                ),
            )
            return True

    def account(self, initial_capital: float) -> dict[str, Any]:
        with self._lock:
            cash = self._conn.execute(
                "SELECT balance_after FROM paper_cash_ledger ORDER BY created_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
            equity = self._conn.execute(
                "SELECT total_equity FROM paper_equity_snapshots ORDER BY created_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
        positions = {row["code"]: row for row in self.list_positions()}
        current_cash = float(initial_capital if cash is None else cash[0])
        market_value = sum(float(row["quantity"]) * float(row["current_price"]) for row in positions.values())
        return {
            "cash": current_cash,
            "total_equity": float(equity[0]) if equity is not None else current_cash + market_value,
            "positions": positions,
        }

    def apply_settlement_bundle(
        self,
        *,
        run_id: str,
        orders: Iterable[Mapping[str, Any]],
        fills: Iterable[Mapping[str, Any]],
        positions: Iterable[Mapping[str, Any]],
        cash_entries: Iterable[Mapping[str, Any]],
        equity_snapshot: Mapping[str, Any],
    ) -> None:
        order_rows = list(orders)
        fill_rows = list(fills)
        position_rows = list(positions)
        cash_rows = list(cash_entries)
        now = _utc_now()
        with self._transaction() as conn:
            for order in order_rows:
                cursor = conn.execute(
                    """UPDATE paper_orders SET filled_qty=?, cancelled_qty=?, status=?, reject_reason=?,
                       filled_price=?, payload_json=?, updated_at=? WHERE order_id=? AND run_id=?""",
                    (
                        int(order.get("filled_qty", 0)), int(order.get("cancelled_qty", 0)), order["status"],
                        order.get("reject_reason"), order.get("filled_price"), _json(dict(order)), now,
                        order["order_id"], run_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ValueError(f"planned_order_missing:{order.get('order_id')}")
            for fill in fill_rows:
                conn.execute(
                    """INSERT INTO paper_fills(
                        fill_id,run_id,order_id,code,direction,quantity,price,commission,
                        stamp_tax,slippage,payload_json,created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        fill["fill_id"], run_id, fill["order_id"], fill["code"], fill["direction"],
                        int(fill["quantity"]), float(fill["price"]), float(fill.get("commission", 0)),
                        float(fill.get("stamp_tax", 0)), float(fill.get("slippage", 0)), _json(dict(fill)), now,
                    ),
                )
            for position in position_rows:
                conn.execute(
                    """INSERT INTO paper_positions(code,quantity,available_qty,today_buy_qty,avg_price,current_price,realized_pnl,updated_at)
                       VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(code) DO UPDATE SET
                       quantity=excluded.quantity,available_qty=excluded.available_qty,
                       today_buy_qty=excluded.today_buy_qty,avg_price=excluded.avg_price,
                       current_price=excluded.current_price,realized_pnl=excluded.realized_pnl,
                       updated_at=excluded.updated_at""",
                    (
                        position["code"], int(position["quantity"]), int(position["available_qty"]),
                        int(position.get("today_buy_qty", 0)), float(position.get("avg_price", 0)),
                        float(position.get("current_price", 0)), float(position.get("realized_pnl", 0)), now,
                    ),
                )
            for entry in cash_rows:
                conn.execute(
                    "INSERT INTO paper_cash_ledger(entry_id,run_id,order_id,fill_id,entry_type,amount,balance_after,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        entry["entry_id"], run_id, entry.get("order_id"), entry.get("fill_id"),
                        entry["entry_type"], float(entry["amount"]), float(entry["balance_after"]), now,
                    ),
                )
            snapshot_id = equity_snapshot["snapshot_id"]
            conn.execute(
                """INSERT INTO paper_equity_snapshots(snapshot_id,run_id,cash,market_value,total_equity,daily_pnl,drawdown_pct,position_count,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    snapshot_id, run_id, float(equity_snapshot["cash"]), float(equity_snapshot["market_value"]),
                    float(equity_snapshot["total_equity"]), float(equity_snapshot.get("daily_pnl", 0)),
                    float(equity_snapshot.get("drawdown_pct", 0)), int(equity_snapshot["position_count"]), now,
                ),
            )
            conn.execute(
                "UPDATE paper_runs SET fill_count=?, updated_at=? WHERE run_id=?",
                (len(fill_rows), now, run_id),
            )

    def store_reconciliations(self, run_id: str, checks: Iterable[Mapping[str, Any]]) -> None:
        now = _utc_now()
        with self._transaction() as conn:
            for check in checks:
                check_id = stable_id("paper_check", run_id, check["check_name"])
                conn.execute(
                    "INSERT INTO paper_reconciliations(check_id,run_id,check_name,passed,expected_json,actual_json,created_at) VALUES(?,?,?,?,?,?,?)",
                    (
                        check_id, run_id, check["check_name"], 1 if check["passed"] else 0,
                        _json(check.get("expected")), _json(check.get("actual")), now,
                    ),
                )

    def list_equity(self, limit: int = 500) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM paper_equity_snapshots
                   ORDER BY created_at DESC, rowid DESC LIMIT ?""",
                (int(limit),),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_reconciliations(self, run_id: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        query = "SELECT * FROM paper_reconciliations"
        params: list[Any] = []
        if run_id:
            query += " WHERE run_id=?"
            params.append(run_id)
        query += " ORDER BY created_at DESC, check_name LIMIT ?"
        params.append(int(limit))
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def list_audit(self, limit: int = 1000) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM paper_audit_events ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [dict(row) for row in rows]

    def acquire_lease(self, run_id: str, *, owner_pid: int, now: float, ttl_seconds: int) -> bool:
        expires = float(now) + int(ttl_seconds)
        with self._transaction() as conn:
            cursor = conn.execute(
                """UPDATE paper_runs SET owner_pid=?, lease_expires_at=?, updated_at=?
                   WHERE run_id=? AND (owner_pid IS NULL OR owner_pid=? OR lease_expires_at IS NULL OR lease_expires_at < ?)""",
                (owner_pid, expires, _utc_now(), run_id, owner_pid, float(now)),
            )
            return cursor.rowcount == 1

    def apply_execution_bundle(
        self,
        *,
        run_id: str,
        orders: Iterable[Mapping[str, Any]],
        fills: Iterable[Mapping[str, Any]],
        positions: Iterable[Mapping[str, Any]],
        cash_entries: Iterable[Mapping[str, Any]],
    ) -> None:
        order_rows = list(orders)
        fill_rows = list(fills)
        position_rows = list(positions)
        cash_rows = list(cash_entries)
        now = _utc_now()
        with self._transaction() as conn:
            if conn.execute("SELECT 1 FROM paper_runs WHERE run_id=?", (run_id,)).fetchone() is None:
                raise KeyError(f"unknown_run:{run_id}")
            for sequence_no, order in enumerate(order_rows):
                conn.execute(
                    """INSERT INTO paper_orders(
                        order_id,run_id,client_order_id,code,direction,target_qty,current_qty,
                        sequence_no,quantity,filled_qty,cancelled_qty,status,reject_reason,request_price,
                        filled_price,payload_json,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        order["order_id"], run_id, order["client_order_id"], order["code"], order["direction"],
                        int(order.get("target_qty", 0)), int(order.get("current_qty", 0)), int(sequence_no), int(order["quantity"]),
                        int(order.get("filled_qty", 0)), int(order.get("cancelled_qty", 0)), order["status"],
                        order.get("reject_reason"), order.get("request_price"), order.get("filled_price"),
                        _json(dict(order)), now, now,
                    ),
                )
            for fill in fill_rows:
                conn.execute(
                    """INSERT INTO paper_fills(
                        fill_id,run_id,order_id,code,direction,quantity,price,commission,
                        stamp_tax,slippage,payload_json,created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        fill["fill_id"], run_id, fill["order_id"], fill["code"], fill["direction"],
                        int(fill["quantity"]), float(fill["price"]), float(fill.get("commission", 0)),
                        float(fill.get("stamp_tax", 0)), float(fill.get("slippage", 0)), _json(dict(fill)), now,
                    ),
                )
            for position in position_rows:
                conn.execute(
                    """INSERT INTO paper_positions(
                        code,quantity,available_qty,today_buy_qty,avg_price,current_price,realized_pnl,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(code) DO UPDATE SET quantity=excluded.quantity,
                        available_qty=excluded.available_qty,today_buy_qty=excluded.today_buy_qty,
                        avg_price=excluded.avg_price,current_price=excluded.current_price,
                        realized_pnl=excluded.realized_pnl,updated_at=excluded.updated_at""",
                    (
                        position["code"], int(position["quantity"]), int(position["available_qty"]),
                        int(position.get("today_buy_qty", 0)), float(position["avg_price"]),
                        float(position["current_price"]), float(position.get("realized_pnl", 0)), now,
                    ),
                )
            for entry in cash_rows:
                conn.execute(
                    """INSERT INTO paper_cash_ledger(
                        entry_id,run_id,order_id,fill_id,entry_type,amount,balance_after,created_at
                    ) VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        entry["entry_id"], run_id, entry.get("order_id"), entry.get("fill_id"),
                        entry["entry_type"], float(entry["amount"]), float(entry["balance_after"]), now,
                    ),
                )
            conn.execute(
                "UPDATE paper_runs SET order_count=order_count+?, fill_count=fill_count+?, updated_at=? WHERE run_id=?",
                (len(order_rows), len(fill_rows), now, run_id),
            )

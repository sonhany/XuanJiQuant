"""Structured audit tables for autonomous trading events."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any


STRUCTURED_TABLES = {
    "ai_decisions": """
        CREATE TABLE IF NOT EXISTS ai_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_id TEXT,
            generated_at TEXT,
            valid_until TEXT,
            trade_policy TEXT,
            trade_allowed INTEGER,
            model_version TEXT,
            prompt_version TEXT,
            confidence REAL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """,
    "orders": """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            decision_id TEXT,
            order_id TEXT,
            code TEXT,
            direction TEXT,
            quantity INTEGER,
            status TEXT,
            source TEXT,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """,
    "trades": """
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            decision_id TEXT,
            trade_id TEXT,
            order_id TEXT,
            code TEXT,
            direction TEXT,
            quantity INTEGER,
            price REAL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """,
    "positions_snapshots": """
        CREATE TABLE IF NOT EXISTS positions_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            decision_id TEXT,
            source TEXT,
            total_equity REAL,
            cash REAL,
            position_count INTEGER,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """,
    "risk_events": """
        CREATE TABLE IF NOT EXISTS risk_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            decision_id TEXT,
            order_id TEXT,
            code TEXT,
            direction TEXT,
            reason TEXT,
            approved INTEGER,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """,
    "model_calls": """
        CREATE TABLE IF NOT EXISTS model_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT,
            scene TEXT,
            model TEXT,
            success INTEGER,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """,
    "audit_events": """
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            decision_id TEXT,
            event_type TEXT NOT NULL,
            source TEXT,
            ref_id TEXT,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """,
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def _conn(cache) -> sqlite3.Connection | None:
    return getattr(cache, "_conn", None)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl_type: str = "TEXT") -> None:
    if column not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")


def ensure_audit_schema(cache) -> bool:
    conn = _conn(cache)
    if conn is None:
        return False
    for ddl in STRUCTURED_TABLES.values():
        conn.execute(ddl)
    for table in ("orders", "trades", "positions_snapshots", "risk_events", "audit_events"):
        _ensure_column(conn, table, "run_id")
        _ensure_column(conn, table, "decision_id")
    _ensure_column(conn, "risk_events", "order_id")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_decisions_decision_id ON ai_decisions(decision_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_run_id ON orders(run_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_order_id ON trades(order_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_risk_events_run_id ON risk_events(run_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_type_time ON audit_events(event_type, created_at)")
    conn.commit()
    return True


def write_audit_event(cache, event_type: str, payload: Any, *, source: str = "", ref_id: str = "") -> bool:
    conn = _conn(cache)
    if conn is None:
        return False
    ensure_audit_schema(cache)
    conn.execute(
        "INSERT INTO audit_events(run_id, decision_id, event_type, source, ref_id, payload, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            (payload or {}).get("run_id") if isinstance(payload, dict) else None,
            (payload or {}).get("decision_id") if isinstance(payload, dict) else None,
            event_type, source, ref_id, _json(payload), _now()
        ),
    )
    conn.commit()
    return True


def write_ai_decision(cache, decision: dict, *, source: str = "ai_loop") -> bool:
    conn = _conn(cache)
    if conn is None:
        return False
    ensure_audit_schema(cache)
    conn.execute(
        """INSERT INTO ai_decisions(
            decision_id, generated_at, valid_until, trade_policy, trade_allowed,
            model_version, prompt_version, confidence, payload, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            decision.get("decision_id"),
            decision.get("generated_at"),
            decision.get("valid_until"),
            decision.get("trade_policy"),
            1 if decision.get("trade_allowed") else 0,
            decision.get("model_version"),
            decision.get("prompt_version"),
            decision.get("confidence"),
            _json({"source": source, **decision}),
            _now(),
        ),
    )
    conn.commit()
    return True


def write_order_event(cache, order: dict, *, source: str = "paper") -> bool:
    conn = _conn(cache)
    if conn is None:
        return False
    ensure_audit_schema(cache)
    conn.execute(
        "INSERT INTO orders(run_id, decision_id, order_id, code, direction, quantity, status, source, payload, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            order.get("run_id"),
            order.get("decision_id"),
            order.get("order_id") or order.get("id"),
            order.get("code"),
            order.get("direction"),
            order.get("qty") or order.get("quantity"),
            order.get("status") or ("filled" if order.get("success") else "rejected"),
            source,
            _json(order),
            _now(),
        ),
    )
    conn.commit()
    return True


def write_trade_event(cache, trade: dict, *, source: str = "execution") -> bool:
    conn = _conn(cache)
    if conn is None:
        return False
    ensure_audit_schema(cache)
    conn.execute(
        "INSERT INTO trades(run_id, decision_id, trade_id, order_id, code, direction, quantity, price, payload, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            trade.get("run_id"),
            trade.get("decision_id"),
            trade.get("id") or trade.get("trade_id"),
            trade.get("order_id"),
            trade.get("code"),
            trade.get("direction"),
            trade.get("quantity"),
            trade.get("price"),
            _json({"source": source, **trade}),
            _now(),
        ),
    )
    conn.commit()
    return True


def write_risk_event(cache, event: dict, *, source: str = "risk_gateway") -> bool:
    conn = _conn(cache)
    if conn is None:
        return False
    ensure_audit_schema(cache)
    conn.execute(
        "INSERT INTO risk_events(run_id, decision_id, order_id, code, direction, reason, approved, payload, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            event.get("run_id") or (event.get("intent") or {}).get("run_id"),
            event.get("decision_id") or (event.get("intent") or {}).get("decision_id"),
            event.get("order_id") or (event.get("intent") or {}).get("order_id"),
            event.get("code") or (event.get("intent") or {}).get("code"),
            event.get("direction") or (event.get("intent") or {}).get("direction"),
            event.get("reason"),
            1 if event.get("approved") else 0,
            _json({"source": source, **event}),
            _now(),
        ),
    )
    conn.commit()
    return True


def write_position_snapshot(cache, snapshot: dict, *, source: str = "paper") -> bool:
    conn = _conn(cache)
    if conn is None:
        return False
    ensure_audit_schema(cache)
    conn.execute(
        "INSERT INTO positions_snapshots(run_id, decision_id, source, total_equity, cash, position_count, payload, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            snapshot.get("run_id"),
            snapshot.get("decision_id"),
            source,
            snapshot.get("total_equity"),
            snapshot.get("cash"),
            snapshot.get("position_count"),
            _json(snapshot),
            _now(),
        ),
    )
    conn.commit()
    return True


def write_model_call(cache, payload: dict) -> bool:
    conn = _conn(cache)
    if conn is None:
        return False
    ensure_audit_schema(cache)
    conn.execute(
        "INSERT INTO model_calls(provider, scene, model, success, payload, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            payload.get("provider"),
            payload.get("scene"),
            payload.get("model"),
            1 if payload.get("success") else 0,
            _json(payload),
            _now(),
        ),
    )
    conn.commit()
    return True


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description]
    out = []
    for row in cur.fetchall():
        item = {cols[i]: row[i] for i in range(len(cols))}
        if "payload" in item:
            try:
                item["payload"] = json.loads(item["payload"])
            except Exception:
                pass
        out.append(item)
    return out


def latest_audit_replays(cache, limit: int = 20) -> list[dict]:
    conn = _conn(cache)
    if conn is None:
        return []
    ensure_audit_schema(cache)
    limit = max(1, min(int(limit or 20), 100))
    return _rows(
        conn,
        """
        SELECT run_id, decision_id, event_type, source, ref_id, payload, created_at
        FROM audit_events
        WHERE event_type IN ('paper_run', 'ai_loop', 'risk_gateway')
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    )


def get_audit_replay(cache, *, run_id: str = "", decision_id: str = "", limit: int = 100) -> dict:
    """Return enough structured audit data to replay a decision/order path."""
    conn = _conn(cache)
    if conn is None:
        return {"success": False, "error": "cache has no sqlite connection"}
    ensure_audit_schema(cache)
    limit = max(1, min(int(limit or 100), 500))
    if not run_id and not decision_id:
        latest = _rows(
            conn,
            "SELECT run_id, decision_id FROM audit_events ORDER BY id DESC LIMIT 1",
        )
        if latest:
            run_id = latest[0].get("run_id") or ""
            decision_id = latest[0].get("decision_id") or ""

    clauses = []
    params: list[Any] = []
    if run_id:
        clauses.append("run_id = ?")
        params.append(run_id)
    if decision_id:
        clauses.append("decision_id = ?")
        params.append(decision_id)
    where = (" WHERE " + " OR ".join(clauses)) if clauses else ""
    decisions = []
    if decision_id:
        decisions = _rows(
            conn,
            "SELECT * FROM ai_decisions WHERE decision_id = ? ORDER BY id DESC LIMIT ?",
            (decision_id, limit),
        )
    return {
        "success": True,
        "run_id": run_id,
        "decision_id": decision_id,
        "decisions": decisions,
        "risk_events": _rows(conn, f"SELECT * FROM risk_events{where} ORDER BY id DESC LIMIT ?", tuple(params + [limit])),
        "orders": _rows(conn, f"SELECT * FROM orders{where} ORDER BY id DESC LIMIT ?", tuple(params + [limit])),
        "trades": _rows(conn, f"SELECT * FROM trades{where} ORDER BY id DESC LIMIT ?", tuple(params + [limit])),
        "positions": _rows(conn, f"SELECT * FROM positions_snapshots{where} ORDER BY id DESC LIMIT ?", tuple(params + [limit])),
        "audit_events": _rows(conn, f"SELECT * FROM audit_events{where} ORDER BY id DESC LIMIT ?", tuple(params + [limit])),
    }

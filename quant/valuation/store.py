"""Structured SQLite persistence for stock valuation results."""
from __future__ import annotations

import json
import math
import numbers
import sqlite3
from collections.abc import Mapping
from datetime import datetime, timezone
from datetime import date as date_type
from decimal import Decimal
from typing import Any
from uuid import uuid4

from .contracts import VALID_STATUSES, normalize_code


class ValuationDataIntegrityError(RuntimeError):
    """Raised when a persisted valuation payload cannot be decoded safely."""


def _cache_resources(cache) -> tuple[sqlite3.Connection, Any]:
    conn = getattr(cache, "_conn", None)
    lock = getattr(cache, "_lock", None)
    if conn is None or lock is None:
        raise TypeError("valuation cache must expose both _conn and _lock")
    return conn, lock


def _normalize_json(value: Any, path: str = "$") -> Any:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError(f"non-finite decimal at {path}")
        return float(value)
    if isinstance(value, numbers.Real):
        normalized = float(value)
        if not math.isfinite(normalized):
            raise ValueError(f"non-finite number at {path}")
        return normalized
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date_type):
        return value.isoformat()
    if isinstance(value, Mapping):
        normalized = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(
                    f"unsupported JSON key at {path}: {type(key).__name__}"
                )
            normalized[key] = _normalize_json(item, f"{path}.{key}")
        return normalized
    if isinstance(value, (list, tuple)):
        return [
            _normalize_json(item, f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    raise TypeError(f"unsupported JSON value at {path}: {type(value).__name__}")


def _json(value: Any) -> str:
    return json.dumps(
        _normalize_json(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def _parse_json(value: str, field: str, valuation_id: str) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValuationDataIntegrityError(
            f"invalid {field} JSON for valuation_id={valuation_id}"
        ) from exc


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def ensure_valuation_schema(cache) -> bool:
    """Create valuation storage using the cache's existing SQLite connection."""
    conn, lock = _cache_resources(cache)
    with lock:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stock_valuations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                valuation_id TEXT NOT NULL,
                code TEXT NOT NULL,
                name TEXT,
                valuation_type TEXT NOT NULL,
                status TEXT NOT NULL,
                data_date TEXT,
                report_period TEXT,
                formula_version TEXT,
                model_version TEXT,
                prompt_version TEXT,
                input_payload TEXT NOT NULL,
                output_payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_stock_valuations_code_type_created
            ON stock_valuations(code, valuation_type, created_at)
            """
        )
        conn.execute("DROP INDEX IF EXISTS idx_stock_valuations_valuation_id")
        indexes = {
            row[1]
            for row in conn.execute(
                "PRAGMA index_list(stock_valuations)"
            ).fetchall()
        }
        if "uq_stock_valuations_id_type" not in indexes:
            conn.execute(
                """
                DELETE FROM stock_valuations
                WHERE id NOT IN (
                    SELECT MAX(id)
                    FROM stock_valuations
                    GROUP BY valuation_id, valuation_type
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX uq_stock_valuations_id_type
                ON stock_valuations(valuation_id, valuation_type)
                """
            )
        conn.commit()
    return True


def save_valuation(cache, valuation: dict) -> str:
    """Persist one valuation result and return its generated identifier."""
    conn, lock = _cache_resources(cache)

    code = normalize_code(valuation.get("code"))
    if not code:
        raise ValueError("invalid stock code")
    valuation_type = str(valuation.get("valuation_type") or "").strip()
    if not valuation_type:
        raise ValueError("valuation_type is required")
    status = str(valuation.get("status") or "").strip()
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid valuation status: {status}")

    ensure_valuation_schema(cache)
    valuation_id = str(valuation.get("valuation_id") or uuid4().hex)
    values = (
        valuation_id,
        code,
        str(valuation.get("name") or ""),
        valuation_type,
        status,
        str(valuation.get("data_date") or ""),
        str(valuation.get("report_period") or ""),
        str(valuation.get("formula_version") or ""),
        str(valuation.get("model_version") or ""),
        str(valuation.get("prompt_version") or ""),
        _json(valuation.get("input") if valuation.get("input") is not None else {}),
        _json(valuation.get("output") if valuation.get("output") is not None else {}),
        _now(),
    )
    with lock:
        conn.execute(
            """
            INSERT INTO stock_valuations (
                valuation_id, code, name, valuation_type, status,
                data_date, report_period, formula_version, model_version,
                prompt_version, input_payload, output_payload, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(valuation_id, valuation_type) DO UPDATE SET
                code = excluded.code,
                name = excluded.name,
                status = excluded.status,
                data_date = excluded.data_date,
                report_period = excluded.report_period,
                formula_version = excluded.formula_version,
                model_version = excluded.model_version,
                prompt_version = excluded.prompt_version,
                input_payload = excluded.input_payload,
                output_payload = excluded.output_payload
            """,
            values,
        )
        conn.commit()
    return valuation_id


def latest_valuation(cache, code: object, valuation_type: str) -> dict | None:
    """Read the newest valuation for a stock and valuation type."""
    conn, lock = _cache_resources(cache)
    normalized = normalize_code(code)
    kind = str(valuation_type or "").strip()
    if not normalized or not kind:
        return None
    ensure_valuation_schema(cache)
    with lock:
        row = conn.execute(
            """
            SELECT
                valuation_id, code, name, valuation_type, status,
                data_date, report_period, formula_version, model_version,
                prompt_version, input_payload, output_payload, created_at
            FROM stock_valuations
            WHERE code = ? AND valuation_type = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (normalized, kind),
        ).fetchone()
    if row is None:
        return None
    return {
        "valuation_id": row[0],
        "code": row[1],
        "name": row[2],
        "valuation_type": row[3],
        "status": row[4],
        "data_date": row[5],
        "report_period": row[6],
        "formula_version": row[7],
        "model_version": row[8],
        "prompt_version": row[9],
        "input": _parse_json(row[10], "input_payload", row[0]),
        "output": _parse_json(row[11], "output_payload", row[0]),
        "created_at": row[12],
    }

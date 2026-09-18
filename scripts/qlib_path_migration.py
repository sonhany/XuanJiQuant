from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from quant.qlib.paths import data_root, resolve_data_path


OBSOLETE_ROOTS = (
    r"C:\XuanJiQuant-QlibData",
    r"C:\AlphaCouncil-QlibData",
    r"C:\Users\HYSHEN\AlphaCouncil2-AI\data\qlib",
)
TABLE_SPECS = {
    "datasets": {
        "path_columns": ("path",),
        "json_columns": ("metadata_json",),
        "status_mutable": True,
    },
    "experiments": {
        "path_columns": ("path",),
        "json_columns": ("metrics_json", "config_json"),
        "status_mutable": True,
    },
    "models": {
        "path_columns": ("path",),
        "json_columns": ("metrics_json",),
        "status_mutable": True,
    },
    "workflow_runs": {
        "path_columns": ("recorded_path",),
        "json_columns": ("artifacts_json", "metrics_json", "gate_json"),
        "status_mutable": False,
    },
    "jobs": {
        "path_columns": (),
        "json_columns": ("params_json", "result_json"),
        "status_mutable": False,
    },
}


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_windows(value: str) -> str:
    return str(value or "").strip().replace("/", "\\").rstrip("\\").lower()


def _obsolete_suffix(value: str) -> tuple[str, str] | None:
    normalized = _normalized_windows(value)
    for root in OBSOLETE_ROOTS:
        normalized_root = _normalized_windows(root)
        if normalized == normalized_root:
            return root, ""
        prefix = normalized_root + "\\"
        if normalized.startswith(prefix):
            return root, normalized[len(prefix) :]
    return None


def _path_key(key: str) -> bool:
    normalized = str(key or "").strip().lower()
    return normalized in {"path", "root", "uri"} or normalized.endswith(
        ("_path", "_root", "_uri")
    )


def _walk_path_values(
    value: Any,
    *,
    prefix: tuple[str | int, ...] = (),
) -> Iterable[tuple[tuple[str | int, ...], str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = (*prefix, str(key))
            if isinstance(child, str) and _obsolete_suffix(child):
                yield child_prefix, child
            elif isinstance(child, (dict, list)):
                yield from _walk_path_values(child, prefix=child_prefix)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            if isinstance(child, (dict, list)):
                yield from _walk_path_values(child, prefix=(*prefix, index))


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _primary_key(conn: sqlite3.Connection, table: str) -> str:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    for row in rows:
        if int(row[5] or 0) > 0:
            return str(row[1])
    if any(str(row[1]) == "id" for row in rows):
        return "id"
    raise RuntimeError(f"table has no stable primary key: {table}")


def _target(active_root: Path, original: str) -> tuple[Path, bool]:
    matched = _obsolete_suffix(original)
    if matched is None:
        raise ValueError("path is not obsolete")
    _root, suffix = matched
    parts = [part for part in suffix.split("\\") if part]
    target = active_root.joinpath(*parts).resolve()
    if target != active_root and active_root not in target.parents:
        raise ValueError("mapped Qlib path escapes active root")
    return target, target.exists()


def _scan(conn: sqlite3.Connection, active_root: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    available = _tables(conn)
    for table, spec in TABLE_SPECS.items():
        if table not in available:
            continue
        columns = _columns(conn, table)
        primary_key = _primary_key(conn, table)
        selected = [primary_key]
        selected.extend(column for column in spec["path_columns"] if column in columns)
        selected.extend(column for column in spec["json_columns"] if column in columns)
        rows = conn.execute(
            f"SELECT {', '.join(selected)} FROM {table}"
        ).fetchall()
        for row in rows:
            row_id = str(row[primary_key])
            for column in spec["path_columns"]:
                if column not in columns:
                    continue
                original = str(row[column] or "")
                if not _obsolete_suffix(original):
                    continue
                target, exists = _target(active_root, original)
                items.append(
                    {
                        "table": table,
                        "primary_key": primary_key,
                        "row_id": row_id,
                        "column": column,
                        "json_path": [],
                        "locator": column,
                        "original_path": original,
                        "target_path": str(target) if exists else "",
                        "target_exists": exists,
                        "action": "map_to_active" if exists else "invalidate_missing",
                    }
                )
            for column in spec["json_columns"]:
                if column not in columns:
                    continue
                try:
                    payload = json.loads(str(row[column] or "{}"))
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                for json_path, original in _walk_path_values(payload):
                    target, exists = _target(active_root, original)
                    items.append(
                        {
                            "table": table,
                            "primary_key": primary_key,
                            "row_id": row_id,
                            "column": column,
                            "json_path": list(json_path),
                            "locator": f"{column}." + ".".join(map(str, json_path)),
                            "original_path": original,
                            "target_path": str(target) if exists else "",
                            "target_exists": exists,
                            "action": "map_to_active" if exists else "invalidate_missing",
                        }
                    )
    return items


def _set_json_path(payload: Any, path: list[str | int], value: str, state: str) -> Any:
    cursor = payload
    for part in path[:-1]:
        cursor = cursor[int(part)] if isinstance(cursor, list) else cursor[str(part)]
    leaf = path[-1]
    if isinstance(cursor, list):
        cursor[int(leaf)] = value
    else:
        key = str(leaf)
        cursor[key] = value
        cursor[f"{key}_state"] = state
    return payload


def _apply_item(conn: sqlite3.Connection, item: dict[str, Any]) -> None:
    table = item["table"]
    primary_key = item["primary_key"]
    row_id = item["row_id"]
    column = item["column"]
    replacement = item["target_path"]
    state = "active" if item["target_exists"] else "missing_historical"
    if not item["json_path"]:
        conn.execute(
            f"UPDATE {table} SET {column}=? WHERE {primary_key}=?",
            (replacement, row_id),
        )
        if not item["target_exists"] and TABLE_SPECS[table]["status_mutable"]:
            if "status" in _columns(conn, table):
                conn.execute(
                    f"UPDATE {table} SET status='missing_historical' WHERE {primary_key}=?",
                    (row_id,),
                )
        return
    row = conn.execute(
        f"SELECT {column} FROM {table} WHERE {primary_key}=?",
        (row_id,),
    ).fetchone()
    payload = json.loads(str(row[column] or "{}"))
    updated = _set_json_path(payload, item["json_path"], replacement, state)
    conn.execute(
        f"UPDATE {table} SET {column}=? WHERE {primary_key}=?",
        (json.dumps(updated, ensure_ascii=False, sort_keys=True), row_id),
    )


def migrate(
    *,
    db_path: str | Path,
    active_root: str | Path,
    dry_run: bool = True,
) -> dict[str, Any]:
    db = Path(db_path).resolve()
    active = Path(active_root).resolve()
    if not db.is_file():
        raise FileNotFoundError(f"Qlib registry not found: {db}")
    active.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True) as readonly:
        readonly.row_factory = sqlite3.Row
        items = _scan(readonly, active)
    report: dict[str, Any] = {
        "dry_run": bool(dry_run),
        "database": str(db),
        "active_root": str(active),
        "obsolete_active_count": len(items),
        "items": items,
        "backup_path": "",
        "backup_sha256": "",
        "post_scan_obsolete_active_count": len(items),
        "executed_at": _stamp(),
    }
    if dry_run or not items:
        return report

    before_hash = _sha256(db)
    backup = db.with_name(
        f"{db.name}.backup-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
    )
    shutil.copy2(db, backup)
    backup_hash = _sha256(backup)
    if backup_hash != before_hash:
        backup.unlink(missing_ok=True)
        raise RuntimeError("Qlib registry backup hash mismatch")

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        for item in items:
            _apply_item(conn, item)
        if "audit_events" in _tables(conn):
            conn.execute(
                """
                INSERT INTO audit_events (
                    event_type, entity_type, entity_id, detail_json, created_at
                ) VALUES ('qlib_path_migration', 'registry', ?, ?, ?)
                """,
                (
                    str(db),
                    json.dumps(
                        {
                            "database_sha256_before": before_hash,
                            "backup_path": str(backup),
                            "backup_sha256": backup_hash,
                            "items": items,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    _stamp(),
                ),
            )
        conn.commit()

    with sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True) as readonly:
        readonly.row_factory = sqlite3.Row
        remaining = _scan(readonly, active)
    report.update(
        {
            "backup_path": backup,
            "backup_sha256": backup_hash,
            "post_scan_obsolete_active_count": len(remaining),
        }
    )
    if remaining:
        raise RuntimeError("obsolete active Qlib paths remain after migration")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit and migrate obsolete Qlib paths")
    parser.add_argument("--db", default=str(resolve_data_path("qlib_meta.db")))
    parser.add_argument("--active-root", default=str(data_root()))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", default="")
    args = parser.parse_args()
    report = migrate(
        db_path=args.db,
        active_root=args.active_root,
        dry_run=not args.apply,
    )
    report_path = (
        Path(args.report).resolve()
        if args.report
        else resolve_data_path(
            "reports",
            f"qlib_path_migration_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        )
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(json.dumps({**report, "report_path": str(report_path)}, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Qlib 第一阶段只读验收器；不得采集、训练、晋升或写入数据库。"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quant.qlib.artifact_importer import REQUIRED_ARTIFACTS
from quant.qlib.paths import data_root, resolve_data_path
from quant.qlib.promotion_gate import GATE_VERSION


REQUIRED_HANDLERS = {"Alpha158", "Alpha360"}
REQUIRED_MODELS = {"LightGBM", "XGBoost", "Linear"}
REQUIRED_RECORD_TYPES = {"SignalRecord", "SigAnaRecord", "PortAnaRecord"}
REQUIRED_ENGINES = {"qlib_official", "xuanji_ashare"}


def _known_unsafe_root(value: Any) -> bool:
    normalized = str(value or "").replace("/", "\\").lower()
    return any(
        marker in normalized
        for marker in (
            "\\alphacouncil2-ai",
            "c:\\xuanjiquant-qlibdata",
            "c:\\alphacouncil-qlibdata",
        )
    )


def evaluate_acceptance(snapshot: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    quality = snapshot.get("quality") or {}
    workflows = list(snapshot.get("workflow_runs") or [])
    backtests = list(snapshot.get("backtests") or [])
    gate = snapshot.get("gate") or {}
    shadow_signals = list(snapshot.get("shadow_signals") or [])
    schedule = snapshot.get("schedule") or {}

    if _known_unsafe_root(snapshot.get("data_root")):
        reasons.append("inactive_or_unsafe_data_root")
    if quality.get("passed") is not True:
        reasons.append("six_year_quality_failed")
    if quality.get("gate_version") != GATE_VERSION:
        reasons.append("quality_gate_version_mismatch")

    successful = [item for item in workflows if item.get("status") == "succeeded"]
    handlers = {str(item.get("handler")) for item in successful}
    models = {str(item.get("model_type")) for item in successful}
    if not REQUIRED_HANDLERS.issubset(handlers):
        reasons.append("required_handlers_missing")
    if not REQUIRED_MODELS.issubset(models):
        reasons.append("required_models_missing")
    if not successful or any(
        not all(name in (item.get("artifacts") or {}) for name in REQUIRED_ARTIFACTS)
        for item in successful
    ):
        reasons.append("recorder_artifacts_incomplete")

    by_workflow: dict[str, dict[str, str]] = {}
    for item in backtests:
        workflow_id = str(item.get("workflow_run_id") or "")
        engine = str(item.get("engine") or "")
        signal_hash = str(item.get("signal_hash") or "")
        if workflow_id and engine in REQUIRED_ENGINES:
            by_workflow.setdefault(workflow_id, {})[engine] = signal_hash
    dual = [engines for engines in by_workflow.values() if REQUIRED_ENGINES.issubset(engines)]
    if not dual:
        reasons.append("dual_backtest_missing")
    elif not any(len(set(engines.values())) == 1 and next(iter(engines.values()), "") for engines in dual):
        reasons.append("dual_backtest_signal_mismatch")

    if gate.get("gate_version") != GATE_VERSION or gate.get("status") not in {
        "candidate", "rejected", "review_required"
    }:
        reasons.append("unified_gate_missing_or_stale")
    if not shadow_signals:
        reasons.append("shadow_signal_missing")
    elif any(
        item.get("schema_version") != "xuanji_shadow_signal_v1"
        for item in shadow_signals
    ):
        reasons.append("shadow_signal_schema_invalid")
    if any(item.get("has_orders") is True for item in shadow_signals):
        reasons.append("shadow_signal_contains_orders")
    if int(schedule.get("consecutive_successes") or 0) < 2:
        reasons.append("schedule_successes_below_2")

    unique_reasons = list(dict.fromkeys(reasons))
    return {
        "passed": not unique_reasons,
        "gate_version": GATE_VERSION,
        "reason_codes": unique_reasons,
        "quality": "passed" if quality.get("passed") is True else "failed",
        "handlers": sorted(handlers & REQUIRED_HANDLERS),
        "models": sorted(models & REQUIRED_MODELS),
        "record_types": sorted(REQUIRED_RECORD_TYPES),
        "backtests": sorted(REQUIRED_ENGINES if dual else set()),
        "schedule_mode": str(schedule.get("mode") or "weekly"),
        "schedule_consecutive_successes": int(schedule.get("consecutive_successes") or 0),
        "data_root": str(snapshot.get("data_root") or ""),
        "safety_boundary": "read_only_offline_acceptance",
    }


def _connect_read_only(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _json(value: Any) -> dict[str, Any]:
    try:
        return json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _latest_matrix(workflows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[tuple[str, str], dict[str, Any]] = {}
    for item in workflows:
        key = (str(item.get("handler") or ""), str(item.get("model_type") or ""))
        if key not in selected and item.get("status") == "succeeded":
            selected[key] = item
    return list(selected.values())


def _schedule_successes(events: list[dict[str, Any]], mode: str = "weekly") -> int:
    successes = 0
    for event in events:
        detail = event.get("detail") or {}
        if detail.get("mode") != mode:
            continue
        if event.get("event_type") == "schedule_cycle_failed":
            break
        if event.get("event_type") == "schedule_cycle_succeeded" and detail.get("no_op") is not True:
            successes += 1
    return successes


def _read_snapshot(root: Path, database: Path) -> dict[str, Any]:
    with _connect_read_only(database) as connection:
        quality_rows = []
        if _table_exists(connection, "quality_reports"):
            quality_rows = connection.execute(
                "SELECT * FROM quality_reports ORDER BY created_at DESC"
            ).fetchall()
        quality = None
        if quality_rows:
            row = dict(quality_rows[0])
            quality = {
                **_json(row.get("report_json")),
                "passed": bool(row.get("passed")),
                "gate_version": row.get("gate_version"),
                "dataset_version": row.get("dataset_version"),
            }

        workflow_rows = []
        if _table_exists(connection, "workflow_runs"):
            workflow_rows = connection.execute(
                "SELECT * FROM workflow_runs ORDER BY created_at DESC"
            ).fetchall()
        workflows = []
        for source in workflow_rows:
            item = dict(source)
            item["artifacts"] = _json(item.pop("artifacts_json", "{}"))
            item["metrics"] = _json(item.pop("metrics_json", "{}"))
            item["gate"] = _json(item.pop("gate_json", "{}"))
            workflows.append(item)
        selected_workflows = _latest_matrix(workflows)

        backtest_rows = []
        if _table_exists(connection, "backtest_results"):
            backtest_rows = connection.execute(
                "SELECT * FROM backtest_results ORDER BY created_at DESC"
            ).fetchall()
        backtests = [dict(row) for row in backtest_rows]

        audit_rows = []
        if _table_exists(connection, "audit_events"):
            audit_rows = connection.execute(
                "SELECT event_type, detail_json, created_at FROM audit_events "
                "WHERE event_type IN ('schedule_cycle_succeeded','schedule_cycle_failed') "
                "ORDER BY id DESC LIMIT 500"
            ).fetchall()
        events = [
            {"event_type": row["event_type"], "detail": _json(row["detail_json"])}
            for row in audit_rows
        ]

    gate = next(
        (
            item.get("gate")
            for item in workflows
            if (item.get("gate") or {}).get("gate_version") == GATE_VERSION
        ),
        {},
    )
    shadow_signals = []
    shadow_root = root / "shadow_signals"
    if shadow_root.exists():
        for path in sorted(shadow_root.glob("*/*.json"), reverse=True):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            shadow_signals.append(
                {
                    "schema_version": payload.get("schema_version"),
                    "has_orders": bool(payload.get("orders")),
                }
            )
    return {
        "data_root": str(root),
        "quality": quality,
        "workflow_runs": selected_workflows,
        "backtests": backtests,
        "gate": gate,
        "shadow_signals": shadow_signals,
        "schedule": {
            "mode": "weekly",
            "consecutive_successes": _schedule_successes(events, "weekly"),
        },
    }


def evaluate_current_workspace() -> dict[str, Any]:
    root = data_root()
    database = resolve_data_path("qlib_meta.db")
    if not root.exists() or not database.exists():
        result = evaluate_acceptance(
            {
                "data_root": str(root),
                "quality": None,
                "workflow_runs": [],
                "backtests": [],
                "gate": {},
                "shadow_signals": [],
                "schedule": {"mode": "weekly", "consecutive_successes": 0},
            }
        )
        result["reason_codes"] = list(dict.fromkeys(["active_data_root_or_registry_missing", *result["reason_codes"]]))
        result["passed"] = False
        return result
    return evaluate_acceptance(_read_snapshot(root, database))


def main() -> int:
    result = evaluate_current_workspace()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

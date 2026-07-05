"""Audit helpers for paper trading runs."""
from __future__ import annotations

from quant.data.audit import (
    ensure_audit_schema,
    write_audit_event,
    write_position_snapshot,
)


def ensure_schema(cache) -> bool:
    return ensure_audit_schema(cache)


def record_run(cache, summary: dict, cfg: dict, status: dict) -> None:
    decision = summary.get("decision") or {}
    write_audit_event(cache, "paper_run", {
        "run_id": summary.get("run_id"),
        "decision_id": decision.get("decision_id"),
        "summary": summary,
        "config": cfg,
        "status": status,
    }, source="paper_trader")
    account = (summary.get("objective_status") or {}).get("account") or {}
    if account:
        write_position_snapshot(cache, {
            **account,
            "run_id": summary.get("run_id"),
            "decision_id": decision.get("decision_id"),
        }, source="paper_trader")

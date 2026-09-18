"""Authoritative, read-only health projection for the four active quant layers."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from quant.research.publication import read_publication_status, resolve_complete_generation


def _compact_date(value: Any) -> str:
    return str(value or "").replace("-", "")[:8]


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"health artifact is not an object: {path.name}")
    return value


def load_research_publication(root: Path | str) -> dict[str, Any]:
    """Resolve factor and selection evidence from one verified generation."""
    publication_root = Path(root) / "data" / "research" / "daily"
    try:
        generation = resolve_complete_generation(publication_root)
        paths = generation["paths"]
        return {
            "pointer": dict(generation["pointer"]),
            "factor": _read_json(Path(paths["factor_evaluation.json"])),
            "selection": _read_json(Path(paths["selection.json"])),
            "refresh": read_publication_status(publication_root),
        }
    except Exception as exc:
        return {"error": type(exc).__name__}


def load_f4_projection(root: Path | str) -> dict[str, Any]:
    try:
        return _read_json(Path(root) / "data" / "research" / "f4" / "latest.json")
    except Exception as exc:
        return {"error": type(exc).__name__}


def project_four_layer_health(
    *,
    expected_date: str,
    data_coverage: dict[str, Any],
    publication: dict[str, Any],
    f4: dict[str, Any],
    paper: dict[str, Any],
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    """Project health without deriving strategy or execution permission."""
    checked = checked_at or datetime.now()
    expected = _compact_date(expected_date)
    data_as_of = _compact_date(data_coverage.get("coverage_date"))
    data_fresh = bool(data_coverage.get("fresh")) and bool(data_as_of)
    refresh_pending = bool(
        not data_fresh
        and checked.strftime("%Y%m%d") == expected
        and (checked.hour, checked.minute) < (16, 40)
    )
    data_layer = {
        "status": "ok" if data_fresh else "warning" if refresh_pending else "error",
        "freshness": "current" if data_fresh else "stale",
        "as_of": data_as_of or None,
        "expected_as_of": expected or None,
        "coverage": data_coverage.get("expected_coverage"),
        "covered_instruments": data_coverage.get("dominant_count"),
        "instrument_records": data_coverage.get("total_count"),
        "source": "quant.db/kline:*:d",
        "reason": (
            None
            if data_fresh
            else "daily_refresh_pending"
            if refresh_pending
            else "market_daily_coverage_stale_or_incomplete"
        ),
    }

    pointer = publication.get("pointer") if isinstance(publication, dict) else None
    factor = publication.get("factor") if isinstance(publication, dict) else None
    selection = publication.get("selection") if isinstance(publication, dict) else None
    refresh = publication.get("refresh") if isinstance(publication, dict) else None
    pointer = pointer if isinstance(pointer, dict) else {}
    factor = factor if isinstance(factor, dict) else {}
    selection = selection if isinstance(selection, dict) else {}
    refresh = refresh if isinstance(refresh, dict) else {}
    factor_as_of = _compact_date(factor.get("as_of") or factor.get("latest_kline_date"))
    factor_identity_valid = bool(
        pointer.get("generation_id")
        and pointer.get("snapshot_id") == factor.get("snapshot_id")
        and pointer.get("data_version") == factor.get("data_version")
        and pointer.get("promotion_state") == "research_only"
        and pointer.get("execution_authority") is False
        and factor.get("promotion_state", "research_only") == "research_only"
        and factor.get("execution_authority", False) is False
    )
    factor_current = bool(factor_as_of and data_as_of and factor_as_of == data_as_of)
    factor_status = "error" if not factor_identity_valid else "ok" if factor_current else "warning"
    factor_layer = {
        "status": factor_status,
        "freshness": "current" if factor_current else "stale" if factor_as_of else "unknown",
        "as_of": factor_as_of or None,
        "expected_as_of": data_as_of or expected or None,
        "generation_id": pointer.get("generation_id"),
        "registered_factor_count": len(factor.get("factors") or []),
        "eligible_stock_count": factor.get("eligible_count") or factor.get("n_stocks"),
        "coverage": factor.get("data_coverage"),
        "source": "verified research generation/factor_evaluation.json",
        "authority": "research_only",
        "refresh_state": refresh.get("state"),
        "refresh_target_date": _compact_date(refresh.get("target_date")) or None,
        "reason": (
            "research_generation_identity_invalid"
            if not factor_identity_valid
            else None
            if factor_current
            else "factor_refreshing"
            if refresh.get("state") == "refreshing"
            else "factor_evaluation_lags_data_layer"
        ),
    }

    f4_status = str(f4.get("status") or "") if isinstance(f4, dict) else ""
    f4_identity_valid = bool(
        f4_status
        and f4.get("validation_id")
        and f4.get("promotion_state", "research_only") == "research_only"
        and f4.get("execution_authority", False) is False
    )
    selection_identity_valid = bool(
        selection.get("selection_date")
        and selection.get("generated_from_snapshot_id") == pointer.get("snapshot_id")
        and selection.get("snapshot_data_version") == pointer.get("data_version")
        and selection.get("promotion_state") == "research_only"
        and selection.get("execution_authority") is False
    )
    if not f4_identity_valid or not selection_identity_valid:
        strategy_status = "error"
        strategy_reason = "strategy_or_selection_identity_invalid"
    elif f4_status in {"f4_research_candidate", "candidate", "passed"}:
        strategy_status = "ok"
        strategy_reason = None
    else:
        strategy_status = "warning"
        strategy_reason = f4_status
    strategy_layer = {
        "status": strategy_status,
        "freshness": "current" if _compact_date(selection.get("selection_date")) == factor_as_of else "stale",
        "selection_as_of": _compact_date(selection.get("selection_date")) or None,
        "f4_data_as_of": _compact_date(
            f4.get("market_date") or f4.get("data_end_date") or f4.get("market_data_date")
        ) or None,
        "f4_status": f4_status or None,
        "validation_id": f4.get("validation_id"),
        "position_count": selection.get("position_count"),
        "source": "F4 latest + verified research selection",
        "authority": "research_only",
        "reason": strategy_reason,
    }

    latest_run = paper.get("latest_run") if isinstance(paper, dict) else None
    latest_run = latest_run if isinstance(latest_run, dict) else {}
    current_readiness = (
        paper.get("current_readiness") if isinstance(paper, dict) else None
    )
    current_readiness = (
        current_readiness if isinstance(current_readiness, dict) else {}
    )
    live_authority = paper.get("live_execution_authority") if isinstance(paper, dict) else None
    reconciliation_failed = bool(paper.get("reconciliation_failed")) if isinstance(paper, dict) else False
    halted = latest_run.get("status") == "halted_unknown"
    market_fact_as_of = str(paper.get("market_fact_timestamp") or "")
    execution_session_current = bool(
        market_fact_as_of and _compact_date(market_fact_as_of) == checked.strftime("%Y%m%d")
    )
    execution_mode = str(paper.get("execution_mode") or "")
    latest_run_status = str(latest_run.get("status") or "")
    paper_reason = (
        current_readiness.get("reason_code")
        or paper.get("reason_code")
        or latest_run.get("reason_code")
    )
    if live_authority is not False or reconciliation_failed or halted:
        execution_status = "error"
        execution_reason = "execution_authority_or_reconciliation_invalid"
    elif not latest_run:
        execution_status = "warning"
        execution_reason = "paper_execution_has_no_run"
    elif not paper.get("enabled") or paper.get("kill_switch"):
        execution_status = "warning"
        execution_reason = "paper_execution_paused"
    elif current_readiness:
        if current_readiness.get("paper_execution_ready") is not True:
            execution_status = "warning"
            execution_reason = paper_reason or "paper_execution_blocked"
        elif current_readiness.get("market_window_allowed") is not True:
            execution_status = "warning"
            execution_reason = paper_reason or "outside_intraday_window"
        elif latest_run_status in {"completed", "completed_with_rejections"} and execution_session_current:
            execution_status = "ok"
            execution_reason = None
        else:
            execution_status = "warning"
            execution_reason = "paper_execution_cycle_pending"
    elif latest_run_status == "blocked":
        execution_status = "warning"
        execution_reason = paper_reason or "paper_execution_blocked"
    else:
        execution_status = "ok"
        execution_reason = None
    if current_readiness and current_readiness.get("market_window_allowed") is False:
        execution_freshness = "not_applicable"
    elif execution_mode == "paper_daily" and not market_fact_as_of:
        execution_freshness = "not_applicable"
    elif execution_session_current:
        execution_freshness = "session_current"
    else:
        execution_freshness = "stale" if latest_run else "unknown"
    execution_layer = {
        "status": execution_status,
        "freshness": execution_freshness,
        "ledger_as_of": latest_run.get("updated_at"),
        "market_fact_as_of": market_fact_as_of or None,
        "mode": execution_mode or None,
        "run_id": latest_run.get("run_id"),
        "run_status": latest_run.get("status"),
        "order_count": latest_run.get("order_count", 0),
        "fill_count": latest_run.get("fill_count", 0),
        "strategy_quality": paper.get("strategy_quality_status"),
        "paper_execution_authority": bool(paper.get("paper_execution_authority")),
        "live_execution_authority": False if live_authority is False else live_authority,
        "source": "data/paper/f5_ledger.db",
        "reason": execution_reason,
        "current_readiness": current_readiness or None,
        "historical_run_reason": latest_run.get("reason_code"),
    }

    statuses = [
        data_layer["status"],
        factor_layer["status"],
        strategy_layer["status"],
        execution_layer["status"],
    ]
    overall = "error" if "error" in statuses else "warning" if "warning" in statuses else "ok"
    return {
        "data_layer": data_layer,
        "factor_layer": factor_layer,
        "strategy_layer": strategy_layer,
        "execution_layer": execution_layer,
        "checked_at": checked.isoformat(timespec="seconds"),
        "overall": overall,
    }

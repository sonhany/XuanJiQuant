"""Deterministic promotion state machine for AI factors and strategies."""
from __future__ import annotations

from datetime import datetime


STATES = ("candidate", "shadow", "paper_active", "production_candidate", "approved", "retired")
MIN_SHADOW_PASSES = 1
MIN_PAPER_PASSES = 3
MIN_PRODUCTION_PASSES = 5
MAX_RETIRE_FAILS = 3


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _score_factor(entry: dict) -> dict:
    ev = entry.get("eval") or {}
    return {
        "passed": bool(ev.get("passed")),
        "best_abs_ic": float(ev.get("best_abs_ic") or 0),
        "best_ir": float(ev.get("best_ir") or 0),
        "n_records": int(ev.get("n_records") or 0),
    }


def _score_strategy(entry: dict) -> dict:
    train_sharpe = float(entry.get("train_sharpe") or 0)
    val_sharpe = float(entry.get("val_sharpe") or 0)
    bt = entry.get("backtest") or {}
    metrics = bt.get("metrics") or {}
    return {
        "passed": bool(entry.get("beats_baseline")),
        "train_sharpe": train_sharpe,
        "val_sharpe": val_sharpe,
        "total_return_pct": float(metrics.get("total_return_pct") or 0),
        "max_drawdown_pct": float(metrics.get("max_drawdown_pct") or 0),
    }


def _factor_level(metrics: dict) -> int:
    if not metrics["passed"]:
        return 0
    if metrics["best_abs_ic"] >= 0.06 and metrics["best_ir"] >= 0.6 and metrics["n_records"] >= 200:
        return 3
    if metrics["best_abs_ic"] >= 0.03 and metrics["best_ir"] >= 0.3:
        return 1
    return 0


def _strategy_level(metrics: dict) -> int:
    if not metrics["passed"]:
        return 0
    if metrics["val_sharpe"] >= 0.8 and metrics["total_return_pct"] > 0 and metrics["max_drawdown_pct"] <= 12:
        return 3
    if metrics["val_sharpe"] > 0:
        return 1
    return 0


def _streak(history: list[dict], min_level: int) -> int:
    n = 0
    for row in reversed(history):
        if int(row.get("level") or 0) >= min_level:
            n += 1
        else:
            break
    return n


def _fail_streak(history: list[dict]) -> int:
    n = 0
    for row in reversed(history):
        if int(row.get("level") or 0) <= 0:
            n += 1
        else:
            break
    return n


def _next_state(history: list[dict], previous: str) -> str:
    if previous == "approved":
        return "approved"
    if _fail_streak(history) >= MAX_RETIRE_FAILS and previous in ("paper_active", "production_candidate", "approved"):
        return "retired"
    if _streak(history, 3) >= MIN_PRODUCTION_PASSES:
        return "production_candidate"
    if _streak(history, 1) >= MIN_PAPER_PASSES:
        return "paper_active"
    if _streak(history, 1) >= MIN_SHADOW_PASSES:
        return "shadow"
    return "candidate"


def apply_promotion_state(kind: str, entry: dict, cache) -> dict:
    """Attach and persist promotion state for a candidate.

    kind: "factor" or "strategy". The state is advanced only by deterministic
    metrics. Human/manual review can later mark production_candidate as approved.
    """
    if kind not in {"factor", "strategy"}:
        raise ValueError(f"unknown promotion kind: {kind}")
    name = entry.get("name") or entry.get("strategy") or "unknown"
    key = f"ai:{kind}:promotion:{name}"
    old = cache.get(key) or {}
    previous = old.get("state", "candidate")
    if previous not in STATES:
        previous = "candidate"
    metrics = _score_factor(entry) if kind == "factor" else _score_strategy(entry)
    history = old.get("history") or []
    level = _factor_level(metrics) if kind == "factor" else _strategy_level(metrics)
    history.append({"time": _now(), "metrics": metrics, "level": level})
    history = history[-30:]
    state = _next_state(history, previous)
    history[-1]["state"] = state
    record = {
        "name": name,
        "kind": kind,
        "state": state,
        "previous_state": previous,
        "metrics": metrics,
        "level": level,
        "shadow_streak": _streak(history, 1),
        "production_streak": _streak(history, 3),
        "fail_streak": _fail_streak(history),
        "thresholds": {
            "shadow_passes": MIN_SHADOW_PASSES,
            "paper_passes": MIN_PAPER_PASSES,
            "production_passes": MIN_PRODUCTION_PASSES,
            "retire_fails": MAX_RETIRE_FAILS,
        },
        "updated_at": _now(),
        "history": history,
    }
    cache.set(key, record)
    listing_key = f"ai:{kind}:promotion"
    listing = cache.get(listing_key) or {}
    listing[name] = record
    cache.set(listing_key, listing)
    out = dict(entry)
    out["promotion_state"] = state
    out["promotion"] = record
    return out

"""Read-only projections for the F5 API and UI."""

from __future__ import annotations

from typing import Callable

from .ledger import PaperLedger


def active_account_projection(
    ledger: PaperLedger,
    initial_capital: float,
    *,
    limit: int = 200,
    name_resolver: Callable[[str], str] | None = None,
) -> dict:
    """Project the single active simulated account from the F5 ledger."""
    raw_positions = ledger.list_positions()
    live_account = ledger.live_account()
    equities = ledger.list_equity(limit=max(1, int(limit)))
    latest = equities[0] if equities else {}
    if live_account and str(live_account.get("run_id") or "") != str(
        latest.get("run_id") or ""
    ):
        live_account = None
    live_marks = {
        str(row.get("code") or "").zfill(6): row
        for row in ledger.live_marks()
    } if live_account else {}
    ledger_account = ledger.account(initial_capital)
    market_value = float(
        live_account.get("market_value")
        if live_account and live_account.get("market_value") is not None
        else latest.get("market_value")
        if latest.get("market_value") is not None
        else sum(
            float(row.get("quantity") or 0)
            * float(row.get("current_price") or 0)
            for row in raw_positions
        )
    )
    total_equity = float(
        live_account.get("total_equity")
        if live_account and live_account.get("total_equity") is not None
        else ledger_account.get("total_equity") or 0
    )
    positions = []
    for source in raw_positions:
        row = dict(source)
        code = str(row.get("code") or "").zfill(6)
        quantity = int(row.get("quantity") or 0)
        average_price = float(row.get("avg_price") or 0)
        mark = live_marks.get(code) or {}
        current_price = float(mark.get("price") or row.get("current_price") or 0)
        realized_pnl = float(row.get("realized_pnl") or 0)
        cost_value = quantity * average_price
        position_market_value = quantity * current_price
        unrealized_pnl = position_market_value - cost_value
        positions.append(
            {
                **row,
                "code": code,
                "name": str(name_resolver(code) if name_resolver else "").strip(),
                "current_price": current_price,
                "price_updated_at": mark.get("updated_at") or row.get("updated_at"),
                "cost_value": cost_value,
                "market_value": position_market_value,
                "unrealized_pnl": unrealized_pnl,
                "unrealized_pnl_pct": (
                    (current_price - average_price) / average_price * 100
                    if average_price > 0
                    else 0.0
                ),
                "realized_pnl": realized_pnl,
                "total_pnl": unrealized_pnl + realized_pnl,
                "position_weight_pct": (
                    position_market_value / total_equity * 100
                    if total_equity > 0
                    else 0.0
                ),
            }
        )
    unrealized_pnl = sum(float(row["unrealized_pnl"]) for row in positions)
    realized_pnl = sum(float(row["realized_pnl"]) for row in positions)
    def named_rows(rows):
        output = []
        for source in rows:
            row = dict(source)
            code = str(row.get("code") or "").zfill(6)
            output.append(
                {
                    **row,
                    "code": code,
                    "name": str(name_resolver(code) if name_resolver else "").strip(),
                }
            )
        return output

    orders = named_rows(ledger.list_orders(limit=limit))
    trades = named_rows(ledger.list_fills(limit=limit))
    total_pnl = total_equity - float(initial_capital)
    account = {
        "initial_capital": float(initial_capital),
        "cash": float(ledger_account.get("cash") or 0),
        "market_value": market_value,
        "total_equity": total_equity,
        "daily_pnl": (
            float(live_account["daily_pnl"])
            if live_account and live_account.get("daily_pnl") is not None
            else float(latest["daily_pnl"])
            if latest.get("daily_pnl") is not None
            else None
        ),
        "total_pnl": total_pnl,
        "total_pnl_pct": (
            total_pnl / float(initial_capital) * 100
            if float(initial_capital) > 0
            else 0.0
        ),
        "position_count": len(positions),
        "unrealized_pnl": unrealized_pnl,
        "realized_pnl": realized_pnl,
        "updated_at": live_account.get("valuation_as_of") if live_account else latest.get("created_at"),
        "market_snapshot_id": live_account.get("market_snapshot_id") if live_account else None,
        "quote_timestamp": live_account.get("quote_timestamp") if live_account else None,
        "valuation_as_of": live_account.get("valuation_as_of") if live_account else latest.get("created_at"),
        "stale": bool(live_account.get("stale")) if live_account else None,
        "daily_pnl_baseline": live_account.get("daily_pnl_baseline") if live_account else None,
    }
    equity_history = [
        {
            "date": str(row.get("created_at") or "")[:10],
            "equity": float(row.get("total_equity") or 0),
            "cash": float(row.get("cash") or 0),
            "daily_pnl": float(row.get("daily_pnl") or 0),
            "position_count": int(row.get("position_count") or 0),
            "as_of": row.get("created_at"),
        }
        for row in reversed(equities)
    ]
    return {
        "ledger_authority": "f5",
        "ledger": "data/paper/f5_ledger.db",
        "account": account,
        "status": account,
        "positions": positions,
        "orders": orders,
        "trades": trades,
        "equity_history": equity_history,
        "live_execution_authority": False,
    }


def status_projection(
    ledger: PaperLedger,
    current_readiness: dict | None = None,
) -> dict:
    runs = ledger.list_runs(limit=1)
    latest = runs[0] if runs else None
    enabled = bool(ledger.get_setting("enabled", False))
    kill_switch = bool(ledger.get_setting("kill_switch", False))
    latest_input = ledger.run_input(latest["run_id"]) if latest else {}
    intraday_quotes = dict(latest_input.get("intraday_quotes") or {})
    quote_timestamps = sorted(
        {
            str(row.get("quote_timestamp") or row.get("timestamp") or "")
            for row in intraday_quotes.values()
            if str(row.get("quote_timestamp") or row.get("timestamp") or "")
        }
    )
    quote_sources = sorted(
        {
            str(row.get("source") or "")
            for row in intraday_quotes.values()
            if str(row.get("source") or "")
        }
    )
    authorized_run_states = {
        "prepared",
        "execution_pending",
        "executing",
        "reconciling",
        "completed",
        "completed_with_rejections",
    }
    paper_execution_authority = bool(
        enabled
        and not kill_switch
        and latest
        and latest.get("status") in authorized_run_states
    )
    projection = {
        "success": True,
        "execution_mode": "paper_intraday" if intraday_quotes else "paper_daily",
        "market_fact_timestamp": quote_timestamps[-1] if quote_timestamps else None,
        "market_fact_sources": quote_sources,
        "paper_execution_capability": True,
        "paper_execution_authority": paper_execution_authority,
        "live_execution_authority": False,
        "enabled": enabled,
        "kill_switch": kill_switch,
        "execution_lane": (latest or {}).get("execution_lane", "inactive"),
        "strategy_quality_status": (latest or {}).get(
            "strategy_quality_status", "unknown"
        ),
        "f4_status": (latest or {}).get("f4_status"),
        "f4_reasons": list((latest or {}).get("f4_reasons") or []),
        "research_generation_id": (latest or {}).get("research_generation_id"),
        "experimental_policy_version": (latest or {}).get(
            "experimental_policy_version"
        ),
        "latest_run": latest,
        "reason_code": (latest or {}).get("reason_code"),
        "ledger": "data/paper/f5_ledger.db",
    }
    if current_readiness is not None:
        current = dict(current_readiness)
        projection.update(
            {
                "execution_mode": current.get("execution_mode")
                or projection["execution_mode"],
                "enabled": current.get("enabled", projection["enabled"]),
                "kill_switch": current.get(
                    "kill_switch", projection["kill_switch"]
                ),
                "execution_lane": current.get(
                    "execution_lane", projection["execution_lane"]
                ),
                "strategy_quality_status": current.get(
                    "strategy_quality_status",
                    projection["strategy_quality_status"],
                ),
                "f4_status": current.get("f4_status", projection["f4_status"]),
                "f4_reasons": current.get(
                    "f4_reasons", projection["f4_reasons"]
                ),
                "research_generation_id": current.get(
                    "research_generation_id",
                    projection["research_generation_id"],
                ),
                "reason_code": current.get(
                    "reason_code", projection["reason_code"]
                ),
                "paper_execution_ready": bool(
                    current.get("paper_execution_ready", False)
                ),
                "current_readiness": current,
            }
        )
    return projection

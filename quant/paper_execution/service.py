"""Single deterministic orchestration entry for the F5 daily cycle."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timezone
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from .contracts import stable_id
from .eligibility import evaluate_eligibility
from .intraday import IntradayQuoteError, classify_intraday_window, normalize_intraday_quotes
from .ledger import PaperLedger
from .planner import build_order_intents
from .policy import PaperExecutionPolicy
from .reconciler import reconcile_run
from .simulator import simulate_intraday_order, simulate_order


MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")


def _compact(value: date | datetime | str) -> str:
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y%m%d")
    return str(value).replace("-", "")[:8]


class PaperExecutionService:
    """Settle due prepared runs, then prepare today's eligible portfolio."""

    def __init__(
        self,
        *,
        ledger: PaperLedger,
        policy: PaperExecutionPolicy,
        risk: Mapping[str, Any],
        selection_loader: Callable[[], Mapping[str, Any] | None],
        f4_loader: Callable[[], Mapping[str, Any] | None],
        factor_loader: Callable[[], Mapping[str, Any] | None],
        market_bar_loader: Callable[[str, str], Mapping[str, Any] | None],
        next_session: Callable[[str], str],
        research_bundle_loader: Callable[[], Mapping[str, Any] | None] | None = None,
        realtime_quote_loader: Callable[[list[str]], Mapping[str, Mapping[str, Any]]] | None = None,
    ):
        self.ledger = ledger
        self.policy = policy
        self.risk = dict(risk)
        self.selection_loader = selection_loader
        self.f4_loader = f4_loader
        self.factor_loader = factor_loader
        self.research_bundle_loader = research_bundle_loader
        self.market_bar_loader = market_bar_loader
        self.next_session = next_session
        self.realtime_quote_loader = realtime_quote_loader

    def _effective_policy(self) -> PaperExecutionPolicy:
        return replace(
            self.policy,
            enabled=bool(self.ledger.get_setting("enabled", self.policy.enabled)),
            kill_switch=bool(self.ledger.get_setting("kill_switch", self.policy.kill_switch)),
        )

    def mark_to_market(self, snapshot: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
        """Commit a valuation-only market snapshot without execution side effects."""
        market_snapshot_id = str(snapshot.get("snapshot_id") or "")
        if not market_snapshot_id:
            return {"success": False, "reason_code": "market_snapshot_missing"}
        if snapshot.get("valuation_stale", snapshot.get("stale")) is True:
            return {"success": False, "reason_code": "market_snapshot_stale"}
        existing_live = self.ledger.live_account()
        if (
            existing_live
            and str(existing_live.get("market_snapshot_id") or "") == market_snapshot_id
        ):
            return {"success": True, "idempotent": True, **existing_live}
        quote_timestamp = str(snapshot.get("quote_timestamp") or "")
        if quote_timestamp[:8] != now.strftime("%Y%m%d"):
            return {"success": False, "reason_code": "market_snapshot_trade_date_mismatch"}
        positions = self.ledger.list_positions()
        if not positions:
            return {"success": False, "reason_code": "mark_to_market_no_positions"}
        quotes = snapshot.get("quotes") or {}
        if not isinstance(quotes, Mapping):
            return {"success": False, "reason_code": "market_snapshot_invalid"}
        marks = []
        market_value = 0.0
        unrealized_pnl = 0.0
        for position in positions:
            code = str(position.get("code") or "").zfill(6)
            quote = quotes.get(code)
            if not isinstance(quote, Mapping) or quote.get(
                "valuation_stale", quote.get("stale")
            ) is True:
                return {"success": False, "reason_code": "market_snapshot_incomplete"}
            price = float(quote.get("price") or 0)
            source = str(quote.get("source") or "")
            if price <= 0 or not source:
                return {"success": False, "reason_code": "market_snapshot_invalid"}
            quantity = int(position.get("quantity") or 0)
            average_price = float(position.get("avg_price") or 0)
            market_value += quantity * price
            unrealized_pnl += quantity * (price - average_price)
            marks.append(
                {
                    "code": code,
                    "price": price,
                    "quote_timestamp": str(quote.get("quote_timestamp") or quote_timestamp),
                    "source": source,
                    "stale": False,
                }
            )
        run = next(iter(self.ledger.list_runs(limit=1)), None)
        if run is None:
            return {"success": False, "reason_code": "mark_to_market_run_missing"}
        cash = float(self.ledger.account(self.policy.initial_capital).get("cash") or 0)
        total_equity = cash + market_value
        live = self.ledger.live_account()
        equities = self.ledger.list_equity(limit=1)
        latest_equity_run = (
            self.ledger.get_run(str(equities[0].get("run_id") or ""))
            if equities
            else None
        )
        if live and str(live.get("quote_timestamp") or "")[:8] == now.strftime("%Y%m%d"):
            baseline_equity = float(live.get("total_equity") or 0) - float(live.get("daily_pnl") or 0)
            baseline_kind = str(live.get("daily_pnl_baseline") or "live_account_daily_pnl")
        elif equities and str((latest_equity_run or {}).get("intended_session") or "") == now.strftime("%Y%m%d"):
            baseline_equity = float(equities[0].get("total_equity") or 0) - float(equities[0].get("daily_pnl") or 0)
            baseline_kind = "latest_equity_daily_pnl"
        elif equities:
            baseline_equity = float(equities[0].get("total_equity") or 0)
            baseline_kind = "previous_session_close"
        else:
            baseline_equity = total_equity
            baseline_kind = "first_mark"
        valuation_time = (
            now.astimezone(timezone.utc)
            if now.tzinfo is not None
            else now.replace(tzinfo=MARKET_TIMEZONE).astimezone(timezone.utc)
        ).isoformat(timespec="seconds")
        account = {
            "run_id": str(run["run_id"]),
            "market_snapshot_id": market_snapshot_id,
            "quote_timestamp": quote_timestamp,
            "valuation_as_of": valuation_time,
            "cash": cash,
            "market_value": market_value,
            "total_equity": total_equity,
            "daily_pnl": total_equity - baseline_equity,
            "unrealized_pnl": unrealized_pnl,
            "position_count": len(positions),
            "stale": False,
            "daily_pnl_baseline": baseline_kind,
        }
        batch = {
            "snapshot_id": market_snapshot_id,
            "quote_timestamp": quote_timestamp,
            "received_at": str(snapshot.get("received_at") or valuation_time),
            "source": ",".join(sorted({str(mark["source"]) for mark in marks})),
            "stale": False,
        }
        self.ledger.replace_live_marks(batch, marks, account)
        self.ledger.maybe_append_equity_from_mark(account, now=valuation_time)
        return {"success": True, **account}

    def run_due(self, as_of: datetime | date | str) -> dict[str, Any]:
        market_date = _compact(as_of)
        settled: list[dict[str, Any]] = []
        for run in reversed(self.ledger.list_runs(limit=1000)):
            if run["status"] in {"prepared", "execution_pending"} and str(run["intended_session"]) <= market_date:
                intraday = self._completed_intraday_run(run)
                if intraday is not None:
                    superseded = self.ledger.transition_run(
                        str(run["run_id"]), "blocked", "superseded_by_intraday"
                    )
                    settled.append(
                        {
                            **superseded,
                            "superseding_run_id": intraday.get("run_id"),
                        }
                    )
                else:
                    settled.append(self._settle(run))
        prepared = self._prepare(market_date)
        return {
            "success": True,
            "execution_mode": "paper_daily",
            "live_execution_authority": False,
            "market_date": market_date,
            "settled": settled,
            "prepared": prepared,
        }

    def _completed_intraday_run(
        self, daily_run: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        """Return the same-session intraday terminal that replaces a daily fallback."""

        for candidate in self.ledger.list_runs(limit=1000):
            if candidate.get("run_id") == daily_run.get("run_id"):
                continue
            if (
                candidate.get("portfolio_id") != daily_run.get("portfolio_id")
                or str(candidate.get("intended_session") or "")
                != str(daily_run.get("intended_session") or "")
                or candidate.get("status")
                not in {"completed", "completed_with_rejections"}
            ):
                continue
            payload = self.ledger.run_input(str(candidate["run_id"]))
            if payload.get("intraday_quotes"):
                return candidate
        return None

    def run_intraday(self, as_of: datetime) -> dict[str, Any]:
        gate = classify_intraday_window(as_of)
        market_date = as_of.strftime("%Y%m%d")
        base = {
            "success": True,
            "execution_mode": "paper_intraday",
            "live_execution_authority": False,
            "market_date": market_date,
            "market_session": gate.session,
        }
        if not gate.allowed:
            return base | {"status": "skipped", "reason_code": gate.reason_code}

        bundle = (
            dict(self.research_bundle_loader() or {})
            if self.research_bundle_loader is not None
            else {}
        )
        selection = (
            dict(bundle.get("selection") or {})
            if self.research_bundle_loader is not None
            else dict(self.selection_loader() or {})
        )
        factor = (
            dict(bundle.get("factor") or {})
            if self.research_bundle_loader is not None
            else dict(self.factor_loader() or {})
        )
        f4_latest = dict(self.f4_loader() or {})
        policy = replace(self._effective_policy(), execution_mode="paper_intraday")
        portfolio_id = str(
            selection.get("portfolio_id") or stable_id("missing_portfolio", market_date)
        )
        prior_runs = self.ledger.list_execution_runs(
            portfolio_id, market_date, policy.policy_hash
        )
        target_codes = {
            str(row.get("code") or "").zfill(6)
            for row in selection.get("positions") or []
        }
        frozen_target_quantities: dict[str, int] = {}
        for prior in prior_runs:
            for prior_order in self.ledger.list_orders(str(prior["run_id"]), 1000):
                code = str(prior_order.get("code") or "").zfill(6)
                if code in target_codes and code not in frozen_target_quantities:
                    frozen_target_quantities[code] = int(
                        prior_order.get("target_qty") or 0
                    )
        latest_prior = prior_runs[-1] if prior_runs else None
        if latest_prior is not None and latest_prior.get("status") not in {
            "completed",
            "completed_with_rejections",
        }:
            return base | {
                "status": latest_prior.get("status"),
                "run": latest_prior,
                "idempotent": True,
            }
        batch_index = (
            int(latest_prior.get("batch_index") or 0) + 1
            if latest_prior is not None
            else 0
        )

        expected_selection_date = str(
            factor.get("as_of") or selection.get("selection_date") or ""
        ).replace("-", "")
        eligibility = evaluate_eligibility(
            selection=selection,
            f4_latest=f4_latest,
            factor_evidence=factor,
            policy=policy,
            risk=self.risk,
            intended_session=market_date,
            expected_selection_date=expected_selection_date,
        )
        if not eligibility.eligible:
            return base | {"status": "blocked", "reason_code": eligibility.reason_code}

        account = self.ledger.account(policy.initial_capital)
        if not prior_runs:
            account = {
                **account,
                "positions": {
                    code: {
                        **row,
                        "available_qty": int(row.get("quantity") or 0),
                        "today_buy_qty": 0,
                    }
                    for code, row in account["positions"].items()
                },
            }
        required_codes = sorted(
            {
                str(row.get("code") or "").zfill(6)
                for row in selection.get("positions") or []
            }
            | {str(code).zfill(6) for code in account["positions"]}
        )
        if self.realtime_quote_loader is None:
            return base | {"status": "blocked", "reason_code": "intraday_quote_loader_unavailable"}
        try:
            facts = normalize_intraday_quotes(
                self.realtime_quote_loader(required_codes),
                required_codes,
                now=as_of,
                max_age_seconds=120,
            )
        except IntradayQuoteError as exc:
            return base | {"status": "blocked", "reason_code": str(exc)}

        validation_id = str(
            selection.get("f4_validation_id") or f4_latest.get("validation_id") or "missing"
        )
        payload = {
            "selection": selection,
            "f4": f4_latest,
            "factor": factor,
            "research_generation_id": bundle.get("generation_id"),
            "intraday_quotes": facts,
        }
        audit_context = {
            "execution_lane": eligibility.evidence.get("execution_lane"),
            "strategy_quality_status": eligibility.evidence.get("strategy_quality_status"),
            "f4_status": f4_latest.get("status"),
            "f4_reasons": f4_latest.get("reasons") or [],
            "research_generation_id": bundle.get("generation_id"),
            "experimental_policy_version": selection.get("experimental_policy_version"),
        }
        try:
            preview_orders = build_order_intents(
                selection,
                account,
                self.risk,
                {code: float(fact["price"]) for code, fact in facts.items()},
                run_id=f"preview-batch-{batch_index}",
                lot_size=policy.lot_size,
                frozen_target_quantities=frozen_target_quantities,
            )
        except ValueError as exc:
            reason = str(exc).split(":", 1)[0]
            payload["execution_batch"] = {
                "batch_index": batch_index,
                "previous_run_id": (latest_prior or {}).get("run_id"),
            }
            blocked = self.ledger.claim_run(
                portfolio_id=portfolio_id,
                validation_id=validation_id,
                intended_session=market_date,
                policy_hash=policy.policy_hash,
                batch_index=batch_index,
                input_hash=stable_id("paper_intraday_input", payload).split("_", 2)[-1],
                input_payload=payload,
                audit_context=audit_context,
                initial_status="blocked",
                reason_code=reason,
            )
            return base | {"status": "blocked", "reason_code": reason, "run": blocked}
        if latest_prior is not None and not preview_orders:
            return base | {
                "status": latest_prior.get("status"),
                "run": latest_prior,
                "idempotent": True,
                "target_converged": True,
            }
        payload["execution_batch"] = {
            "batch_index": batch_index,
            "previous_run_id": (latest_prior or {}).get("run_id"),
            "planned_order_count": (
                preview_orders[0].get("planned_order_count")
                if preview_orders
                else 0
            ),
            "deferred_order_count": (
                preview_orders[0].get("deferred_order_count")
                if preview_orders
                else 0
            ),
            "frozen_target_quantities": frozen_target_quantities,
        }
        run = self.ledger.claim_run(
            portfolio_id=portfolio_id,
            validation_id=validation_id,
            intended_session=market_date,
            policy_hash=policy.policy_hash,
            batch_index=batch_index,
            input_hash=stable_id("paper_intraday_input", payload).split("_", 2)[-1],
            input_payload=payload,
            audit_context=audit_context,
            initial_status="prepared",
        )
        orders = build_order_intents(
            selection,
            account,
            self.risk,
            {code: float(fact["price"]) for code, fact in facts.items()},
            run_id=run["run_id"],
            lot_size=policy.lot_size,
            frozen_target_quantities=frozen_target_quantities,
        )
        self.ledger.store_planned_orders(run["run_id"], orders)
        completed = self._settle_using_facts(run, facts, intraday=True, policy=policy)
        return base | {"status": completed.get("status"), "run": completed, "idempotent": False}

    def intraday_readiness(self, as_of: datetime) -> dict[str, Any]:
        """Evaluate the current paper lane without quotes, orders, or ledger writes."""

        gate = classify_intraday_window(as_of)
        market_date = as_of.strftime("%Y%m%d")
        bundle = (
            dict(self.research_bundle_loader() or {})
            if self.research_bundle_loader is not None
            else {}
        )
        selection = (
            dict(bundle.get("selection") or {})
            if self.research_bundle_loader is not None
            else dict(self.selection_loader() or {})
        )
        factor = (
            dict(bundle.get("factor") or {})
            if self.research_bundle_loader is not None
            else dict(self.factor_loader() or {})
        )
        f4_latest = dict(self.f4_loader() or {})
        policy = replace(self._effective_policy(), execution_mode="paper_intraday")
        expected_selection_date = str(
            factor.get("as_of") or selection.get("selection_date") or ""
        ).replace("-", "")
        eligibility = evaluate_eligibility(
            selection=selection,
            f4_latest=f4_latest,
            factor_evidence=factor,
            policy=policy,
            risk=self.risk,
            intended_session=market_date,
            expected_selection_date=expected_selection_date,
        )
        reason_code = (
            eligibility.reason_code
            if not eligibility.eligible
            else gate.reason_code
            if not gate.allowed
            else eligibility.reason_code
        )
        return {
            "success": True,
            "execution_mode": "paper_intraday",
            "market_date": market_date,
            "market_session": gate.session,
            "market_window_allowed": gate.allowed,
            "paper_execution_ready": eligibility.eligible,
            "paper_execution_authority": False,
            "live_execution_authority": False,
            "enabled": policy.enabled,
            "kill_switch": policy.kill_switch,
            "execution_lane": eligibility.evidence.get("execution_lane", "blocked"),
            "strategy_quality_status": eligibility.evidence.get(
                "strategy_quality_status", "invalid"
            ),
            "f4_status": f4_latest.get("status"),
            "f4_reasons": list(f4_latest.get("reasons") or []),
            "research_generation_id": bundle.get("generation_id"),
            "selection_date": selection.get("selection_date"),
            "validation_id": selection.get("f4_validation_id"),
            "reason_code": reason_code,
        }

    def _prepare(self, market_date: str) -> dict[str, Any]:
        bundle = (
            dict(self.research_bundle_loader() or {})
            if self.research_bundle_loader is not None
            else {}
        )
        selection = (
            dict(bundle.get("selection") or {})
            if self.research_bundle_loader is not None
            else dict(self.selection_loader() or {})
        )
        f4_latest = dict(self.f4_loader() or {})
        factor = (
            dict(bundle.get("factor") or {})
            if self.research_bundle_loader is not None
            else dict(self.factor_loader() or {})
        )
        intended_session = self.next_session(market_date)
        policy = self._effective_policy()
        portfolio_id = str(selection.get("portfolio_id") or stable_id("missing_portfolio", market_date))
        validation_id = str(selection.get("f4_validation_id") or f4_latest.get("validation_id") or "missing")
        existing = self.ledger.find_run(portfolio_id, intended_session, policy.policy_hash)
        if existing is not None:
            return existing
        eligibility = evaluate_eligibility(
            selection=selection,
            f4_latest=f4_latest,
            factor_evidence=factor,
            policy=policy,
            risk=self.risk,
            intended_session=intended_session,
            expected_selection_date=market_date,
        )
        payload = {
            "selection": selection,
            "f4": f4_latest,
            "factor": factor,
            "research_generation_id": bundle.get("generation_id"),
        }
        input_hash = stable_id("paper_input", payload).split("_", 2)[-1]
        status = "prepared" if eligibility.eligible else "blocked"
        audit_context = {
            "execution_lane": eligibility.evidence.get(
                "execution_lane", "blocked" if not eligibility.eligible else "validated_paper"
            ),
            "strategy_quality_status": eligibility.evidence.get(
                "strategy_quality_status", "invalid" if not eligibility.eligible else "validated"
            ),
            "f4_status": eligibility.evidence.get("f4_status") or f4_latest.get("status"),
            "f4_reasons": eligibility.evidence.get("f4_reasons")
            or f4_latest.get("reasons")
            or [],
            "research_generation_id": bundle.get("generation_id"),
            "experimental_policy_version": selection.get("experimental_policy_version"),
        }
        run = self.ledger.claim_run(
            portfolio_id=portfolio_id,
            validation_id=validation_id,
            intended_session=intended_session,
            policy_hash=policy.policy_hash,
            input_hash=input_hash,
            input_payload=payload,
            audit_context=audit_context,
            initial_status=status,
            reason_code=None if eligibility.eligible else eligibility.reason_code,
        )
        if not eligibility.eligible:
            return run
        account = self.ledger.account(policy.initial_capital)
        prices = {
            str(row.get("code") or "").zfill(6): float(row.get("reference_close") or 0)
            for row in selection.get("positions") or []
        }
        for code, position in account["positions"].items():
            prices.setdefault(code, float(position.get("current_price") or position.get("avg_price") or 0))
        try:
            orders = build_order_intents(
                selection, account, self.risk, prices, run_id=run["run_id"], lot_size=policy.lot_size
            )
        except ValueError as exc:
            reason = str(exc).split(":", 1)[0]
            return self.ledger.transition_run(run["run_id"], "blocked", reason)
        self.ledger.store_planned_orders(run["run_id"], orders)
        return self.ledger.get_run(run["run_id"]) or run

    def _settle(self, run: Mapping[str, Any]) -> dict[str, Any]:
        run_id = str(run["run_id"])
        orders = self.ledger.list_orders(run_id)
        bars = {order["code"]: self.market_bar_loader(order["code"], str(run["intended_session"])) for order in orders}
        if any(bar is None for bar in bars.values()):
            if run["status"] == "prepared":
                self.ledger.transition_run(run_id, "execution_pending", "market_facts_incomplete")
            return {"run_id": run_id, "status": "execution_pending", "reason_code": "market_facts_incomplete"}
        return self._settle_using_facts(run, bars, intraday=False)

    def _settle_using_facts(
        self,
        run: Mapping[str, Any],
        market_facts: Mapping[str, Mapping[str, Any]],
        *,
        intraday: bool,
        policy: PaperExecutionPolicy | None = None,
    ) -> dict[str, Any]:
        run_id = str(run["run_id"])
        orders = self.ledger.list_orders(run_id)
        if run["status"] == "execution_pending":
            self.ledger.transition_run(run_id, "executing")
        else:
            self.ledger.transition_run(run_id, "executing")

        policy = policy or self._effective_policy()
        initial = self.ledger.account(policy.initial_capital)
        initial_positions = {
            code: dict(row, available_qty=int(row.get("quantity") or 0), today_buy_qty=0)
            for code, row in initial["positions"].items()
        }
        working = {
            "cash": float(initial["cash"]),
            "total_equity": float(initial["total_equity"]),
            "positions": {code: dict(row) for code, row in initial_positions.items()},
        }
        initial_for_reconcile = {"cash": working["cash"], "positions": {code: dict(row) for code, row in working["positions"].items()}}
        final_orders: list[dict[str, Any]] = []
        fills: list[dict[str, Any]] = []
        cash_entries: list[dict[str, Any]] = []
        for planned in orders:
            fact = market_facts[planned["code"]]
            result = (
                simulate_intraday_order(planned, fact, working, policy)
                if intraday
                else simulate_order(planned, fact, working, policy)
            )
            try:
                planned_payload = json.loads(str(planned.get("payload_json") or "{}"))
            except json.JSONDecodeError:
                planned_payload = {}
            planned_row = dict(planned)
            planned_row.pop("payload_json", None)
            order = {
                **planned_payload,
                **planned_row,
                **dict(result.order),
                "run_id": run_id,
            }
            final_orders.append(order)
            if result.fill is None:
                continue
            fill = dict(result.fill, run_id=run_id)
            fills.append(fill)
            working["cash"] += result.cash_delta
            cash_entries.append(
                {
                    "run_id": run_id,
                    "entry_id": stable_id("paper_cash", fill["fill_id"]),
                    "order_id": fill["order_id"],
                    "fill_id": fill["fill_id"],
                    "entry_type": fill["direction"],
                    "amount": result.cash_delta,
                    "balance_after": working["cash"],
                }
            )
            code = fill["code"]
            current = working["positions"].setdefault(
                code,
                {"code": code, "quantity": 0, "available_qty": 0, "today_buy_qty": 0, "avg_price": 0.0, "current_price": fill["price"], "realized_pnl": 0.0},
            )
            old_qty = int(current.get("quantity") or 0)
            if fill["direction"] == "buy":
                new_qty = old_qty + int(fill["quantity"])
                current["avg_price"] = (
                    (old_qty * float(current.get("avg_price") or 0) + int(fill["quantity"]) * float(fill["price"])) / new_qty
                    if new_qty else 0.0
                )
                current["quantity"] = new_qty
                current["today_buy_qty"] = int(current.get("today_buy_qty") or 0) + int(fill["quantity"])
            else:
                current["quantity"] = old_qty - int(fill["quantity"])
                current["available_qty"] = int(current.get("available_qty") or 0) - int(fill["quantity"])

        for code, position in working["positions"].items():
            fact = market_facts.get(code)
            if not fact and not intraday:
                fact = self.market_bar_loader(code, str(run["intended_session"]))
            mark = (fact or {}).get("price" if intraday else "close")
            if mark is not None:
                position["current_price"] = float(mark)
            position["code"] = code
        market_value = sum(
            int(row.get("quantity") or 0) * float(row.get("current_price") or 0)
            for row in working["positions"].values()
        )
        equity = {
            "snapshot_id": stable_id("paper_equity", run_id, run["intended_session"]),
            "run_id": run_id,
            "cash": working["cash"],
            "market_value": market_value,
            "total_equity": working["cash"] + market_value,
            "daily_pnl": working["cash"] + market_value - float(initial["total_equity"]),
            "drawdown_pct": 0.0,
            "position_count": sum(1 for row in working["positions"].values() if int(row.get("quantity") or 0) > 0),
        }
        final_account = {"cash": working["cash"], "positions": working["positions"]}
        try:
            self.ledger.apply_settlement_bundle(
                run_id=run_id,
                orders=final_orders,
                fills=fills,
                positions=working["positions"].values(),
                cash_entries=cash_entries,
                equity_snapshot=equity,
            )
        except Exception:
            self.ledger.transition_run(run_id, "execution_pending", "transaction_rolled_back")
            raise
        self.ledger.transition_run(run_id, "reconciling")
        reconciliation = reconcile_run(
            self.ledger.get_run(run_id) or run,
            initial_for_reconcile,
            final_account,
            final_orders,
            fills,
            cash_entries,
            equity,
        )
        self.ledger.store_reconciliations(run_id, reconciliation.checks)
        if not reconciliation.passed:
            self.ledger.set_setting("kill_switch", True)
            completed = self.ledger.transition_run(run_id, "halted_unknown", "reconciliation_failed")
        else:
            state = "completed_with_rejections" if any(order["status"] == "rejected" for order in final_orders) else "completed"
            completed = self.ledger.transition_run(run_id, state)
        return {**completed, "reconciliation_passed": reconciliation.passed}

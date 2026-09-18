# Realtime Agent Paper Trading Design

## Goal

Make the Agent Runtime the autonomous controller for intraday paper trading while
keeping deterministic data, verification, risk, authority, execution, and audit
boundaries. "Realtime" means a 10-second quote/event path plus a bounded
minute-level decision path. It does not mean HFT or live-broker execution.

## Safety Boundary

- Paper trading only. No live broker route is introduced.
- Quote events never create orders or grant execution permission.
- The model proposes goals and tool use; deterministic portfolio output is the
  only source of target weights.
- Runtime authority, policy hash, verifier, risk gateway, T+1, price limits,
  cash, exposure, turnover, slippage, and audit remain mandatory.
- Invalid, stale, missing, or conflicting evidence fails closed.
- Agent handoff is allowed only after the existing shadow-evidence gate passes.

## Runtime Flow

1. Quote sync refreshes the bounded universe every 10 seconds during trading.
2. A pure detector records quote freshness and publishes deduplicated,
   non-authorizing market-anomaly events.
3. In `paper_guarded`, the scheduler runs the execution Agent on a dedicated
   short intraday interval instead of the legacy 10-minute interval.
4. The Agent uses research tools, generates a deterministic portfolio plan,
   verifies that plan, and returns a ready decision supported by observations.
5. Runtime extracts the latest verified portfolio decision from persisted tool
   observations; it does not accept invented execution authority from the model.
6. The existing paper controller publishes a policy-bound decision, rechecks
   risk, routes paper orders, records fills, and audits the complete chain.

## Decision Source

The strict six-field planner contract remains unchanged. This preserves its
security property: the model cannot add `execution_eligible`, `trade_allowed`, or
authority fields. When the planner reaches `ready_to_decide`, runtime must find:

- a successful `generate_portfolio_plan` observation with a bounded decision;
- a later successful `verify_portfolio_plan` observation;
- evidence references in the final plan.

Without that chain, guarded execution terminates as `decision_evidence_missing`.
The runtime may continue accepting an explicit decision only from internal test
planners, but production model output cannot pass the strict planner schema with
that field.

## GLM Permission Semantics

The operator prompt must describe `paper_trade_allowed` as a boolean decision,
not show a literal constant `false`. The model may set it true only when fresh
data, normal trade policy, portfolio evidence, and risk evidence all support a
paper-trading cycle. Deterministic verification remains authoritative.

## Cadence And Limits

- Quote/event path: 10 seconds in the existing trading-session sync loop.
- Agent decision path: configurable `agent_intraday_interval_sec`, default 60
  seconds after Agent handoff.
- Legacy/shadow path: existing mode intervals remain unchanged.
- Guarded paper execution tools: at most one invocation per run and eight per
  day, aligned with the existing daily intraday-cycle risk cap.

## Workbench Visibility

The paper workbench shows one compact realtime control strip:

- execution owner and runtime mode;
- quote heartbeat and freshness;
- Agent cycle state, last completion, next cycle, and duration;
- decision funnel: candidates, target weights, orders, and fills;
- current policy and the precise no-trade/no-fill reason.

These fields are derived from persisted runtime, scheduler, sync, decision, and
execution evidence. The UI does not infer a successful trade from model text.

## Handoff

After regression and runtime validation, wait for the existing shadow gate to
reach readiness. Stop scheduler and paper daemon, call the policy-hash-bound
handoff command, restart scheduler, and verify one guarded Agent cycle. If any
gate fails, leave execution with the legacy owner or rollback through the
existing control service; never edit authority state directly.

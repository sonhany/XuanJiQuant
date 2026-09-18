# Realtime Agent Paper Trading Implementation Plan

## Scope

Implement near-realtime autonomous paper trading under the existing Agent
authority, verifier, risk, execution, and audit controls.

## Tasks

1. Add failing tests for extracting a portfolio decision only from a successful
   generate-then-verify observation chain; reject missing, reversed, malformed,
   or execution-claiming evidence.
2. Implement the runtime decision-evidence extractor and use it before guarded
   decision publication.
3. Add failing tests proving the GLM operator prompt does not hard-code
   `paper_trade_allowed=false`, then replace the constant with explicit boolean
   decision criteria.
4. Add failing contract tests for eight daily guarded paper cycles, then align
   both paper execution tools with the existing risk-cycle cap.
5. Add failing unit tests for quote anomaly detection, cooldown, freshness
   status, and the no-authorization invariant; implement and integrate it into
   quote sync.
6. Add failing scheduler tests for a separate Agent-owned intraday interval;
   implement `agent_intraday_interval_sec` without changing legacy/shadow cadence.
7. Extend persisted Agent/scheduler status and the paper workbench with realtime
   heartbeat, cycle, authority, funnel, and no-trade evidence.
8. Update README with architecture, cadence, safety, status semantics, handoff,
   rollback, and operational verification.
9. Run focused tests, the Agent regression suites, full Python tests, frontend
   tests/build, runtime smoke checks, and browser layout/console verification.
10. After the shadow evidence gate passes, perform the controlled policy-hash
    handoff and verify one safe `paper_guarded` Agent cycle.

## Completion Criteria

- The production Agent can publish a non-empty, verified portfolio decision.
- A model response alone cannot authorize execution or bypass risk.
- Quote status updates on the 10-second path and decision cadence is visible.
- Paper execution can run up to the configured eight guarded cycles per day.
- The workbench identifies the active controller and explains every no-trade
  outcome using persisted evidence.
- All regression/build/browser checks pass, and the runtime is either safely
  handed off to Agent or left unchanged with a concrete gate failure reported.

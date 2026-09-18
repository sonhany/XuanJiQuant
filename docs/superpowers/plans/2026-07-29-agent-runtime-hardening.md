# Agent Runtime Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the paper-only Agent Runtime observable, reconcilable, event-aware, and stable enough to accumulate honest shadow evidence without bypassing execution authority.

**Architecture:** Keep `legacy_ai_loop` as the sole execution owner while hardening the existing bounded runtime. Read APIs expose summaries, reconciliation is append-only sidecar evidence, planner fallback creates a separate model-pinned shadow Run only before any tool call, and event-driven work is admitted through a bounded durable inbox with explicit Agent roles.

**Tech Stack:** Python 3, SQLite, existing `SqliteCache` and `AgentStore`, React/TypeScript, Node contract tests, pytest.

---

### Task 1: Bounded Run List Serialization

**Files:**
- Modify: `scripts/agent_runner.py`
- Test: `tests/test_agent_runtime.py`

- [x] Add a regression test that seeds large context snapshots and proves `_response_line(dispatch(agent_runs))` remains a successful JSON line.
- [x] Verify the test fails with `response serialization failed`.
- [x] Map list records through `quant.agent.replay.public_run` while preserving the full detail endpoint.
- [x] Verify focused read API tests pass.

### Task 2: Evidence-backed Historical Reconciliation

**Files:**
- Modify: `quant/agent/control.py`
- Modify: `scripts/agent_control.py`
- Test: `tests/test_agent_control.py`

- [x] Add failing tests for a legacy partial IOC order with a matching trade and for a terminal cache-write tool independently proven `not_executed`.
- [x] Add bounded reconciliation sidecars whose evidence hashes bind current immutable facts.
- [x] Keep raw order/trade/tool rows unchanged and expose resolved warnings separately from active blockers.
- [x] Add a maintenance CLI action and verify repeated reconciliation is idempotent.

### Task 3: Planner Diagnostics and Safe Model Fallback

**Files:**
- Modify: `quant/agent/planner.py`
- Modify: `quant/agent/runtime.py`
- Modify: `scripts/llm_registry.py`
- Modify: `scripts/ai_scheduler.py`
- Test: `tests/test_agent_runtime.py`
- Test: `tests/test_agent_scheduler_cutover.py`

- [x] Add failing tests for structured Planner diagnostics without raw prompts or secrets.
- [x] Persist diagnostic code, provider, model, stage, attempt count, and repair status on failed Runs.
- [x] Add a deterministic fallback selection helper.
- [x] Add a failing scheduler test proving fallback is allowed only for shadow Runs with zero tool calls and no execution eligibility.
- [x] Run fallback as a new model-pinned Run and record both attempts in shadow evidence; never reuse the failed Run or request execution.

### Task 4: Event Inbox, Agent Roles, and Outcome Memory

**Files:**
- Create: `quant/agent/events.py`
- Modify: `scripts/agent_runner.py`
- Modify: `scripts/ai_risk_agent.py`
- Modify: `scripts/execution_runner.py`
- Test: `tests/test_agent_events.py`
- Test: `tests/test_agent_scheduler_cutover.py`

- [x] Add failing tests for bounded event publication, deduplication, role routing, and terminal acknowledgement.
- [x] Implement a SQLite-backed/cache-backed inbox for market anomaly, disclosure, financial report, risk alert, and order feedback events.
- [x] Route events only to the existing data/research/portfolio/risk/execution/review role boundaries; execution events remain paper-gated.
- [x] Store compact prediction-versus-outcome lessons with provenance and retention limits.

### Task 5: Operator Visibility and Documentation

**Files:**
- Modify: `components/AgentRuntimeStatus.tsx`
- Modify: `scripts/agent_runtime_frontend_contract_tests.mjs`
- Modify: `README.md`

- [x] Add failing UI contract checks for infrastructure success rate, planner diagnostics, fallback chain, event queue, and reconciliation warnings.
- [x] Display what the Agent observed, which model attempted work, why it stopped, which tool ran, verifier status, and why execution is blocked.
- [x] Document operational thresholds and explicitly keep live trading outside the runtime.

### Task 6: Verification and Runtime Check

**Files:**
- No production changes unless verification exposes a root cause.

- [x] Run focused Python and Node contracts.
- [x] Run the full Python suite and all project Node contract scripts.
- [x] Build the frontend.
- [x] Restart only the affected local services, inspect logs, query Agent control status, and verify the Web diagnostics with the in-app browser.
- [x] Confirm persistent owner remains `legacy_ai_loop` unless real shadow evidence independently satisfies every handoff condition.

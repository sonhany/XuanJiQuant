# F5 Deterministic Paper Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independent, persistent, deterministic daily paper-execution loop that consumes only F4-qualified research portfolios and closes orders, fills, cash, positions, equity, reconciliation, audit, API, UI, and scheduling without enabling live trading.

**Architecture:** Add a neutral `quant.paper_execution` bounded context backed by `data/paper/f5_ledger.db`. The daily service first settles a previously prepared plan from governed next-session daily bars, reconciles the account, then prepares the newest eligible portfolio; current rejected research must record a blocked run with zero orders. Existing `quant.db`, `execution:state`, Agent tables, and legacy execution runner remain read-only historical facts.

**Tech Stack:** Python 3, SQLite, dataclasses, pytest, Node HTTP routes/contracts, React/TypeScript, Vite, PowerShell Task Scheduler.

---

### Task 1: F5 contracts and independent SQLite ledger

**Files:**
- Create: `quant/paper_execution/__init__.py`
- Create: `quant/paper_execution/contracts.py`
- Create: `quant/paper_execution/ledger.py`
- Create: `tests/test_f5_paper_ledger.py`

- [ ] Write failing tests proving schema creation, deterministic IDs, unique run identity, atomic cash/position writes, lease ownership, terminal-state validation, and isolation from `data/quant.db`.
- [ ] Run `python -m pytest tests\test_f5_paper_ledger.py -q` and verify failures are caused by the missing package.
- [ ] Define these exact state constants in `contracts.py`:

```python
RUN_STATES = {
    "blocked", "prepared", "execution_pending", "executing",
    "reconciling", "completed", "completed_with_rejections",
    "halted_unknown",
}
TERMINAL_ORDER_STATES = {
    "filled", "rejected", "cancelled", "partially_filled_cancelled",
}

def stable_id(prefix: str, *parts: object) -> str:
    canonical = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}_{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"
```

- [ ] Implement `PaperLedger` with WAL, foreign keys, busy timeout, `BEGIN IMMEDIATE`, schema versioning, run leases, and the eight tables required by the design.
- [ ] Ensure `run_key = stable_id("paper_run", portfolio_id, intended_session, policy_hash)` is unique and repeat claims return the existing run instead of creating side effects.
- [ ] Rerun `python -m pytest tests\test_f5_paper_ledger.py -q` and verify GREEN.

### Task 2: Eligibility and policy compatibility gate

**Files:**
- Create: `quant/paper_execution/eligibility.py`
- Create: `quant/paper_execution/policy.py`
- Create: `tests/test_f5_paper_eligibility.py`
- Modify: `quant/risk/config.py`

- [ ] Write failing tests for `f4_rejected`, diagnostic selection, stale selection, validation mismatch, data hash mismatch, disabled policy, kill switch, duplicate run, and F4 Top20 versus hard max-position 10 incompatibility.
- [ ] Add a passing fixture with `f4_research_candidate`, ten positions, matching validation/data identities, and restrictive hard limits.
- [ ] Run `python -m pytest tests\test_f5_paper_eligibility.py -q` and verify RED.
- [ ] Implement immutable `PaperExecutionPolicy` with version, enabled, initial capital, cost model, participation cap, and simulation-only authority fields.
- [ ] Implement `evaluate_eligibility(...) -> EligibilityResult` that returns one stable reason code and detailed evidence without creating orders.
- [ ] Add a new `load_paper_execution_risk_config` path that merges defaults, F5 policy, and hard limits only; it must not read `ai_manifest.json` or `ai:autonomous:config`.
- [ ] Rerun eligibility and existing risk tests; require all reason branches to pass.

### Task 3: Target-delta planner and deterministic fill simulator

**Files:**
- Create: `quant/paper_execution/planner.py`
- Create: `quant/paper_execution/simulator.py`
- Create: `tests/test_f5_paper_planner.py`
- Create: `tests/test_f5_paper_simulator.py`

- [ ] Write failing planner tests for sell-first ordering, buy board lots, odd-lot full exits, cash scaling, unchanged targets, and no silent truncation of incompatible portfolios.
- [ ] Implement `build_order_intents(selection, account, risk, prices)` using target weights and previous-close equity; output deterministic `client_order_id` values.
- [ ] Write failing simulator tests for governed next-session open fills, suspension, buy limit-up, sell limit-down, missing price, volume participation, commission/stamp/slippage, T+1, and partial-fill terminal remainder.
- [ ] Implement `simulate_order(intent, market_bar, account, policy)` so partial fills end as `partially_filled_cancelled` with `filled_qty + cancelled_qty == quantity`.
- [ ] Run both focused test files and verify GREEN.

### Task 4: Cash, positions, equity, and reconciliation

**Files:**
- Create: `quant/paper_execution/reconciler.py`
- Create: `tests/test_f5_paper_reconciliation.py`

- [ ] Write failing tests for all ten invariants in the design, including duplicate fills, negative cash, T+1 availability, mismatched identities, and unbalanced cash.
- [ ] Implement `reconcile_run(...)` returning per-check expected/actual evidence and an aggregate `passed` flag.
- [ ] Make completed states impossible unless every order is terminal and every reconciliation check passes.
- [ ] Map deterministic transaction rollback to retryable `execution_pending`; map unprovable side effects to `halted_unknown` and persist the F5 kill switch.
- [ ] Run reconciliation and ledger tests and verify GREEN.

### Task 5: Daily orchestration and CLI

**Files:**
- Create: `quant/paper_execution/service.py`
- Create: `quant/paper_execution/reporting.py`
- Create: `scripts/f5_paper_execution.py`
- Create: `scripts/f5_paper_runner.py`
- Create: `tests/test_f5_paper_service.py`

- [ ] Write failing end-to-end tests using a temporary ledger, fixed clock, fixed candidate portfolio, and two governed trading-day bars.
- [ ] Require the eligible fixture to transition `prepared -> executing -> reconciling -> completed`, producing orders, fills, cash entries, positions, equity, and passed reconciliation.
- [ ] Require current-style `f4_rejected` evidence to create one `blocked` run with `reason_code=blocked_by_f4` and zero orders/fills.
- [ ] Require duplicate `--once` calls to return the original run with unchanged row counts.
- [ ] Implement `PaperExecutionService.run_due(as_of)` to settle a due plan, mark/reconcile it, then prepare the newest eligible portfolio.
- [ ] Implement runner read actions `status/runs/orders/fills/positions/equity/reconciliations/audit` and controlled actions `set_enabled/set_kill_switch/run_due`; reject all arbitrary-order verbs.
- [ ] Run all F5 Python tests and verify GREEN.

### Task 6: API authorization and execution boundary

**Files:**
- Create: `server/routes/paper-execution.mjs`
- Modify: `server/router.mjs`
- Create: `scripts/f5_paper_execution_contract_tests.mjs`
- Modify: `scripts/run_contract_suite.mjs`

- [ ] Write a failing Node contract requiring the new route, read-only action registration, token-protected control actions, simulation-only response fields, and explicit rejection of `place_order/fill_order/cancel_order`.
- [ ] Register `/api/paper-execution` in `router.mjs`; read actions use the global read-only whitelist and control actions retain localhost, JSON, and API-token requirements.
- [ ] Ensure the route never imports the legacy execution engine or `LiveBrokerAdapter`.
- [ ] Run `node scripts\f5_paper_execution_contract_tests.mjs` and `npm run test:contracts`; verify GREEN.

### Task 7: F5 operational UI and removal of retired configuration

**Files:**
- Modify: `components/ExecutionPanel.tsx`
- Modify: `components/PaperPanel.tsx`
- Replace: `components/PaperStrategyConfig.tsx`
- Modify: `lib/workbench-state.mjs`
- Create: `scripts/f5_paper_ui_contract_tests.mjs`

- [ ] Write a failing UI contract requiring F5 status, eligibility reason, source portfolio/validation IDs, next session, orders, fills, positions, equity, reconciliation, kill-switch state, and Chinese status labels.
- [ ] Require the contract to reject AI/Agent, provider/model, manual universe, arbitrary strategy, and manual-order controls from the active F5 pages.
- [ ] Convert “模拟执行” into the F5 run/order/fill/reconciliation view and “模拟组合” into the F5 account/position/equity view; place the legacy ledger in a clearly historical subsection.
- [ ] Replace `PaperStrategyConfig` with read-only versioned F5 policy plus enabled/kill-switch controls; no hard-limit relaxation UI is permitted.
- [ ] Show current activity honestly as “F5 已就绪 · F4 未通过” or “组合政策与硬风控不兼容”, not “执行未启用”.
- [ ] Run the new UI contract, `npx tsc --noEmit`, and `npm run build`; verify GREEN.

### Task 8: Deterministic schedule and handoff

**Files:**
- Create: `scripts/install_f5_paper_task.ps1`
- Modify: `README.md`
- Modify: `docs/XUANJI_HANDOFF.md`
- Modify: `docs/XUANJI_SYSTEM_WORKFLOW_MAP.md`
- Modify: `scripts/research_boundary_contract_tests.mjs`

- [ ] Add a failing contract for the 16:40 Monday-Friday task, 15-minute restart interval, three retries, two-hour limit, and `IgnoreNew` overlap policy.
- [ ] Implement `XuanJiQuant-Paper-Daily` installation with the active project Python and working directory; the CLI must still consult the trading calendar and data freshness gate.
- [ ] Document F4-to-F5 authority transition, independent ledger, blocked current state, operations, recovery, reason codes, and the prohibition on real trading.
- [ ] Install the task only after focused and full regression tests pass; verify its executable, working directory, trigger, overlap, retry, and disabled-live boundary.
- [ ] Run the documentation/schedule contracts and verify GREEN.

### Task 9: Full verification and runtime acceptance

**Files:**
- Verify only; update Task 8 runtime evidence after checks.

- [ ] Run `python -m pytest -q` and require zero failures.
- [ ] Run `npm run test:contracts`, `npx tsc --noEmit`, and `npm run build`.
- [ ] Run `node scripts\web_verify.mjs` and `node scripts\ui_verify.mjs`.
- [ ] Restart only the XuanJiQuant API process and verify `/api/paper-execution` status plus token-protected controls.
- [ ] Run the active due cycle and verify `blocked_by_f4` or `portfolio_policy_incompatible`, zero F5 orders, and unchanged historical `quant.db` counts/hashes.
- [ ] Run browser validation for F5 status, Chinese reason, account, orders/fills, reconciliation, no framework overlay, and zero relevant console errors.
- [ ] Confirm no real-broker module, Agent process, arbitrary-order action, or legacy execution-state write has been activated.


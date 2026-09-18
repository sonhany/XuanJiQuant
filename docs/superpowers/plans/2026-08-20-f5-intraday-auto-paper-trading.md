# F5 Intraday Auto Paper Trading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Use the latest complete research portfolio to execute one idempotent, real-time-price paper cycle during the current A-share trading session.

**Architecture:** Add a separate intraday session gate, quote contract and simulator while reusing F5 eligibility, planner, ledger and reconciliation. A parameter-free scheduler owns triggers; pages and arbitrary order requests never choose securities or prices.

**Tech Stack:** Python, SQLite, Node ESM, React/TypeScript, Windows Task Scheduler, pytest.

---

### Task 1: Intraday Time and Quote Contracts

**Files:**
- Create: `quant/paper_execution/intraday.py`
- Test: `tests/test_f5_intraday.py`

- [ ] Write failing tests for the two trading windows, lunch/after-hours rejection, current-day quote timestamp, 120-second freshness, finite price/volume and vendor-code normalization.
- [ ] Run `python -m pytest tests/test_f5_intraday.py -q` and verify missing symbols fail.
- [ ] Implement `classify_intraday_window()` and `normalize_intraday_quotes()` with stable reason codes.
- [ ] Run the focused test and verify all cases pass.

### Task 2: Real-Time Simulator

**Files:**
- Modify: `quant/paper_execution/simulator.py`
- Test: `tests/test_f5_paper_simulator.py`

- [ ] Write failing tests proving realtime `price`, not daily `open`, controls fill price and that suspended/limit/capacity rules remain active.
- [ ] Run the simulator tests and verify RED.
- [ ] Implement `simulate_intraday_order()` using existing fee, slippage, participation and T+1 rules.
- [ ] Run the simulator tests and verify GREEN.

### Task 3: Intraday Service Cycle

**Files:**
- Modify: `quant/paper_execution/service.py`
- Modify: `quant/paper_execution/runtime.py`
- Modify: `quant/paper_execution/ledger.py`
- Test: `tests/test_f5_paper_service.py`
- Test: `tests/test_f5_runtime_publication.py`

- [ ] Write failing tests for previous-complete-day selection, current-session intended date, immediate settlement, idempotent duplicate calls, stale quotes and no cross-generation fallback.
- [ ] Run the service/runtime tests and verify RED.
- [ ] Add injected realtime quote loader and `run_intraday()`; call eligibility with the factor `as_of` date, plan with realtime prices, settle immediately and persist quote evidence.
- [ ] Run service, ledger, simulator and reconciliation tests and verify GREEN.

### Task 4: Runner, API and Scheduler

**Files:**
- Create: `scripts/f5_paper_intraday.py`
- Create: `scripts/install_f5_intraday_task.ps1`
- Modify: `scripts/f5_paper_runner.py`
- Modify: `server/routes/paper-execution.mjs`
- Modify: `scripts/f5_paper_execution_contract_tests.mjs`
- Modify: `scripts/f5_schedule_contract_tests.mjs`

- [ ] Write failing contracts requiring parameter-free `run_intraday`, explicit arbitrary-parameter rejection, weekday five-minute task and `IgnoreNew`.
- [ ] Run both Node contracts and verify RED.
- [ ] Implement the runner, route allowlist and task installer; the runner actively calls `fetch_realtime(codes, use_cache=False)`.
- [ ] Run Python runner tests and Node contracts and verify GREEN.

### Task 5: Truthful UI and Operations

**Files:**
- Modify: `quant/paper_execution/reporting.py`
- Modify: `components/ExecutionPanel.tsx`
- Modify: `components/PaperPanel.tsx`
- Modify: `lib/workbench-state.mjs`
- Modify: `README.md`
- Modify: `docs/XUANJI_HANDOFF.md`
- Modify: `scripts/web_verify.mjs`
- Modify: `scripts/ui_verify.mjs`

- [ ] Write failing reporting/UI contracts for “盘中实验模拟”, quote timestamp, execution mode and permanent no-live label.
- [ ] Implement status and Chinese UI projections without adding security/order inputs.
- [ ] Install only `XuanJiQuant-Paper-Intraday`, verify its action and workspace, then run one parameter-free cycle only if the session gate and quote freshness both pass.
- [ ] Run focused tests, full Python, all Node contracts, TypeScript, Vite, Web/UI and browser console checks.
- [ ] Record run ID, quote timestamps, orders, fills, positions, equity, reconciliation and `live_execution_authority=false` in both handoff documents.


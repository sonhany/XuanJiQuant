# Full Project Health Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify and repair the complete XuanJiQuant research and paper-trading system using current code, database, API, browser, performance, and audit evidence.

**Architecture:** Audit each independent subsystem first, then trace every failure across React -> Node routes -> Python runners -> quant modules -> SQLite/audit tables. Apply only root-cause fixes with focused regression coverage, then run the full integrated verification suite and update README with dated evidence and remaining limitations.

**Tech Stack:** React 19, TypeScript, Vite, Node.js ESM, Python 3.14, pytest, SQLite, Playwright/browser verification.

---

### Task 1: Establish Repository And Runtime Baseline

**Files:**
- Inspect: `package.json`
- Inspect: `requirements.txt`
- Inspect: `server/`
- Inspect: `scripts/`
- Inspect: `quant/`
- Inspect: `components/`
- Inspect: `tests/`
- Modify after evidence: `README.md`

- [ ] List source and test files while excluding `node_modules/`, `data/`, `dist/`, and generated logs.
- [ ] Record listeners on ports 8888 and 8880 and list project-owned Node/Python processes.
- [ ] Enumerate Python and Node test entry points.
- [ ] Confirm the active database path, schema, table counts, and database integrity.

### Task 2: Audit Data Freshness And Source Routing

**Files:**
- Inspect: `quant/data/`
- Inspect: `scripts/data_runner.py`
- Inspect: `scripts/market_data.py`
- Inspect: `server/routes/data.mjs`
- Inspect: `server/routes/market.mjs`
- Test: `scripts/data_source_chain_contract_tests.py`
- Test: `scripts/tdx_quant_source_contract_tests.py`
- Test: `scripts/data_source_policy_tests.mjs`
- Test: `scripts/top_amount_freshness_tests.mjs`

- [ ] Compare `stock:universe`, `stock:name:*`, K-line coverage, `stock_daily_summary`, financial coverage, and latest trading dates.
- [ ] Verify TdxQuant-first routing, Tencent/Sina fallback behavior, and tdxrs Tick classification.
- [ ] Verify Top100 turnover amount, latest price, code/name mapping, and stale flags from the live API.
- [ ] Identify missing or inconsistent records and trace their producing code before any repair.

### Task 3: Audit Factor And Strategy Engines

**Files:**
- Inspect: `quant/factor/`
- Inspect: `quant/strategy/`
- Inspect: `quant/backtest/`
- Inspect: `scripts/factor_runner.py`
- Inspect: `scripts/strategy_runner.py`
- Inspect: `data/factor_evaluation.json`
- Test: `tests/`
- Test: factor and strategy contract scripts under `scripts/`

- [ ] Validate factor metadata, Chinese labels, factor count, evaluation windows, latest data date, IC/IR, neutralized IC, grouped returns, long-short returns, fees, and correlation outputs.
- [ ] Validate strategy metadata, market scan, backtest constraints, T+1, commissions, slippage, limit-up/limit-down handling, and promotion inputs.
- [ ] Compare cached and uncached response behavior and record performance.
- [ ] Trace and fix only reproducible correctness or stability failures.

### Task 4: Audit Paper Trading, Risk, Execution, And AI

**Files:**
- Inspect: `scripts/paper_trader.py`
- Inspect: `server/routes/paper.mjs`
- Inspect: `server/paper_manager.mjs`
- Inspect: `quant/risk/gateway.py`
- Inspect: `scripts/ai_*.py`
- Inspect: `quant/ai/`
- Test: `tests/`
- Test: paper, verifier, promotion, gateway, audit, and scheduler contract scripts.

- [ ] Verify paper daemon and AI scheduler lifecycle, current policy, verifier state, and GLM connectivity.
- [ ] Verify every order path synchronously passes the risk gateway and cannot bypass hard limits.
- [ ] Validate structured records in `ai_decisions`, `model_calls`, `orders`, `trades`, `positions_snapshots`, `risk_events`, and `audit_events`.
- [ ] Replay at least one complete decision/order chain and verify reasons, risk decisions, and fills are observable.
- [ ] Confirm tests do not reset or contaminate the persistent paper account.

### Task 5: Run Integrated Verification

**Files:**
- Test: `tests/`
- Test: `scripts/*.mjs`
- Test: `scripts/*_tests.py`
- Build: `package.json`

- [ ] Run `python -m pytest tests -q`.
- [ ] Run targeted Python contract tests discovered under `scripts/`.
- [ ] Run targeted Node contract tests discovered under `scripts/`.
- [ ] Run `npm run build`.
- [ ] Run `node scripts/web_verify.mjs`.
- [ ] Run `node scripts/ui_verify.mjs`.
- [ ] Verify the rendered browser flow, console health, key navigation, and primary interactions.

### Task 6: Repair Confirmed Failures

**Files:**
- Modify only files implicated by reproduced failures.
- Add or update focused tests beside the relevant subsystem.

- [ ] Capture exact failing command, error, affected input, and component boundary.
- [ ] Trace the failure to its source and compare with a working local pattern.
- [ ] Add the smallest regression test that demonstrates the failure.
- [ ] Apply the smallest root-cause fix.
- [ ] Re-run the focused test, adjacent subsystem tests, and full verification suite.

### Task 7: Performance, Resource, And Documentation Closure

**Files:**
- Modify: `README.md`

- [ ] Measure core API latency, startup behavior, process count, CPU time, memory, threads, handles, and database size.
- [ ] Record current healthy evidence separately from known limitations and unverified external-service conditions.
- [ ] Update README startup instructions, subsystem health, data dates, test results, performance, risks, and next actions.
- [ ] Re-read the README sections and verify every new claim against fresh command output.

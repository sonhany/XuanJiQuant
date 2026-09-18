# Unified Active Paper Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the F5 SQLite ledger the only active simulated-account source across APIs, UI, risk, alerts, reports, and market-data subscriptions while preserving the old ledger as immutable audit history.

**Architecture:** Add one read-only account projection beside the F5 ledger and route every active consumer through it. Keep legacy action names as compatibility aliases, but never copy legacy balances or positions into F5 and never grant live execution authority.

**Tech Stack:** Python 3, SQLite, Node.js ESM, React/TypeScript, pytest, Node contract tests, Vite.

---

### Task 1: Define the F5 account projection

**Files:**
- Modify: `quant/paper_execution/reporting.py`
- Test: `tests/test_f5_paper_reporting.py`

- [ ] Add a failing test that builds a temporary `PaperLedger`, records positions, cash and an equity snapshot, and expects `active_account_projection` to return `ledger_authority=f5`, one account, positions, activity and ascending equity history.
- [ ] Run `.venv-qlib\Scripts\python.exe -m pytest tests\test_f5_paper_reporting.py -q` and verify failure because the projection does not exist.
- [ ] Implement `active_account_projection(ledger, initial_capital, limit=200)` without reading `execution:state`.
- [ ] Run the focused test and verify it passes.

### Task 2: Expose the projection through F5 and compatibility APIs

**Files:**
- Modify: `scripts/f5_paper_runner.py`
- Modify: `server/routes/paper-execution.mjs`
- Modify: `server/routes/execution.mjs`
- Test: `scripts/f5_paper_execution_contract_tests.mjs`
- Test: `scripts/execution_risk_gateway_contract_tests.mjs`

- [ ] Add failing contracts requiring `account/all/trades` to be backed by `f5_paper_runner.py` and forbidding `execution_runner.py` in the active execution route.
- [ ] Run both contract files and verify the expected failure.
- [ ] Add F5 `account` and compatibility read actions; map `/api/execution` read actions to them while keeping every write action blocked.
- [ ] Run both contracts and the focused F5 Python tests.

### Task 3: Switch cockpit and portfolio risk to the same projection

**Files:**
- Modify: `server/routes/workbench.mjs`
- Modify: `scripts/risk_runner.py`
- Modify: `components/DashboardPanel.tsx`
- Test: `tests/test_workbench_status_contract.py`
- Test: `tests/test_risk_metrics.py`

- [ ] Add failing tests proving workbench and risk use the F5 projection and expose `ledger_authority=f5`.
- [ ] Run the focused tests and verify they fail on legacy `execution_runner`/`execution:state` dependencies.
- [ ] Replace those dependencies with `active_account_projection`; add the unified-ledger label to the cockpit.
- [ ] Run the focused tests and verify identical account and position facts.

### Task 4: Switch alerts, tick subscriptions, and reports

**Files:**
- Modify: `scripts/alert_runner.py`
- Modify: `scripts/tick_collector.py`
- Modify: `scripts/daily_report.py`
- Test: `tests/test_daily_report_reconciliation.py`
- Test: `scripts/tick_collector_contract_tests.py`
- Create: `tests/test_active_ledger_consumers.py`

- [ ] Add failing tests proving all three consumers use F5 and never read `execution:state` for current facts.
- [ ] Run the focused tests and verify the legacy-source failure.
- [ ] Use the shared F5 projection in each consumer; keep legacy audit records untouched.
- [ ] Run the focused tests and verify account source, positions and subscriptions are F5-derived.

### Task 5: Remove conflicting copy and update validation/documentation

**Files:**
- Modify: `components/PaperPanel.tsx`
- Modify: `scripts/full_validation.py`
- Modify: `scripts/ui_verify.mjs`
- Modify: `scripts/web_verify.mjs`
- Modify: `README.md`
- Modify: `docs/XUANJI_HANDOFF.md`
- Modify: `docs/XUANJI_SYSTEM_WORKFLOW_MAP.md`

- [ ] Add a failing Node contract requiring the “single active F5 ledger” copy and cross-surface equality checks.
- [ ] Replace old dual-ledger wording and validation of `execution:state` with F5 authority checks.
- [ ] Run Node contracts, API verification and documentation placeholder scans.

### Task 6: Runtime reload and complete verification

**Files:**
- No new source files.

- [ ] Restart only the current project's API process so persistent Python runners load the new projection.
- [ ] Verify 8880/8888, scheduled tasks, F5 authority, no live authority, and zero new backend errors.
- [ ] Run Python full pytest, Node contracts, TypeScript, Vite, `test_api.py`, `full_validation.py`, Web and UI verification.
- [ ] Use the in-app browser to verify all eight requested modules, console health, screenshot evidence, and equality of cockpit/risk/F5 values.


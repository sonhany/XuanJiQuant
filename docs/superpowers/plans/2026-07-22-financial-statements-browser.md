# Financial Statements Browser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only financial statements tab that displays every locally stored financial dataset for one stock code.

**Architecture:** Add a `financials` action to the existing persistent Python data runner and authorize it as read-only in the Node router. Keep presentation in a focused `FinancialStatementsPanel.tsx` component and mount it from `DbPanel.tsx`.

**Tech Stack:** Python, SQLite-backed cache, Node HTTP router, React 19, TypeScript, Vite.

---

### Task 1: Backend Financial Data Contract

**Files:**
- Create: `tests/test_data_financials.py`
- Modify: `scripts/data_runner.py`
- Modify: `server/router.mjs`

- [ ] Write a failing test using a fake cache with `fin:abstract:600519`, `fin:crosscheck:600519`, and an additional future financial key.
- [ ] Verify the test fails because `action_financials` is missing.
- [ ] Implement code normalization, dynamic `fin:*:<code>` key discovery, JSON-safe value normalization, history metadata, and empty results.
- [ ] Register `financials` in `ACTIONS` and in `/api/data` read-only actions.
- [ ] Run `python -m pytest tests/test_data_financials.py -q`.

### Task 2: Frontend Financial Statements Surface

**Files:**
- Create: `components/FinancialStatementsPanel.tsx`
- Modify: `components/DbPanel.tsx`
- Create: `scripts/financial_statements_contract_tests.mjs`

- [ ] Write a failing contract test requiring the new tab immediately after `realtime`, the component mount, and `action: 'financials'`.
- [ ] Verify the contract fails before implementation.
- [ ] Build a query form with six-digit normalization and Enter-key submission.
- [ ] Render summary metrics, the complete normalized history table, and all remaining raw datasets.
- [ ] Use stable table dimensions, horizontal scrolling, sticky headers, and concise loading/error/empty states.
- [ ] Run `node scripts/financial_statements_contract_tests.mjs`.

### Task 3: Documentation And Verification

**Files:**
- Modify: `README.md`

- [ ] Document the financial statements tab and the `financials` read-only action.
- [ ] Run the focused Python and Node tests.
- [ ] Run `npm run build`.
- [ ] Restart only the persistent data runner so the live backend loads the new action.
- [ ] Verify `600519` through `/api/data`.
- [ ] Verify the rendered tab, query interaction, nonblank tables, and console health in the browser.

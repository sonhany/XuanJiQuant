# XuanJiQuant Full Functional Inspection and Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify all eight product areas against live APIs, rendered pages, current timestamps, data coverage, logs, and the F5 paper ledger; repair reproducible defects without weakening authority or risk boundaries.

**Architecture:** Treat the five deterministic layers and the Web projection as separate evidence boundaries. Read-only inspection may cover every route; mutations are limited to source/tests/docs and narrowly scoped recovery of this project's scheduled jobs or services. F5 remains paper-only and consumes published research evidence through the existing verifier and risk gateway.

**Tech Stack:** Python 3.14, Node.js ESM, React 19, TypeScript 5.8, Vite 8, Playwright, SQLite.

**Spec:** User request in the current task, 2026-09-10.

## Global Constraints

- Operate only in `C:\Users\HYSHEN\XuanJiQuant`.
- Do not perform real trading or enable live execution authority.
- Do not bypass verifier, risk gateway, PIT quality gates, or paper-only controls.
- Do not represent cached, partial, historical, rejected, or blocked evidence as current success.
- Avoid overlapping market-session execution; use read-only inspection during the session.
- Preserve the single F5 authority at `data/paper/f5_ledger.db`.

---

### Task 1: Establish runtime and evidence baseline

**Files:**
- Inspect: `server/router.mjs`
- Inspect: `scripts/full_validation.py`
- Inspect: `data/paper/f5_ledger.db`

**Interfaces:**
- Consumes: local scheduled tasks, ports 8880/8888, read-only API routes, SQLite ledger.
- Produces: timestamped baseline for services, execution authority, data dates, coverage, and task state.

- [ ] Query service tasks and ports.
- [ ] Query all read-only route families with response timing.
- [ ] Run SQLite `quick_check` and summarize current-session runs, orders, fills, reconciliation, positions, and account.
- [ ] Classify each result as current, historical, partial, blocked, or unavailable.

### Task 2: Verify the eight functional areas

**Files:**
- Inspect: `components/*.tsx`
- Inspect: `server/routes/*.mjs`
- Inspect: `scripts/*_runner.py`

**Interfaces:**
- Consumes: live API responses and rendered Web application.
- Produces: an eight-section pass/fail matrix with timestamps and sources.

- [ ] Verify cockpit risk, equity, target portfolio, and diagnostic projection.
- [ ] Verify factor metadata, rankings, lists, IC, segmented/batch evaluation, and evaluation time.
- [ ] Verify strategy scan, research portfolio, strategy list/run projection, and paper configuration.
- [ ] Verify F5 execution overview, orders, fills, positions, evidence, and diagnostics.
- [ ] Verify risk, system health/logs, and audit replay.
- [ ] Verify alert records, rules, and statistics.
- [ ] Verify market browser, valuation, realtime quotes, financials, K-lines, and data management.
- [ ] Verify Jin10 and CNInfo status/query projections without treating upstream unavailability as success.

### Task 3: Repair reproducible defects with TDD

**Files:**
- Modify only after a failing test identifies the owning module.
- Test: matching `tests/test_*.py` or `scripts/*_contract_tests.mjs`.

**Interfaces:**
- Consumes: failures from Tasks 1-2.
- Produces: minimal compatibility-preserving fixes and regression tests.

- [ ] Trace each failure to its producing layer and state authority.
- [ ] Add one minimal failing test per behavior defect and observe the expected failure.
- [ ] Implement the smallest source change and rerun the targeted test.
- [ ] Recover only this project's task/service when a restart is necessary and safe.

### Task 4: Full verification and handoff

**Files:**
- Modify: `README.md`
- Modify: `docs/XUANJI_HANDOFF.md`

**Interfaces:**
- Consumes: repaired source and current runtime.
- Produces: source-traceable handoff plus complete regression evidence.

- [ ] Run relevant Python tests and then the full Python suite when changes affect shared boundaries.
- [ ] Run every Node contract file.
- [ ] Run `npx tsc --noEmit` and `npm run build`.
- [ ] Run `scripts/web_verify.mjs`, `scripts/ui_verify.mjs`, and the full/API validation scripts.
- [ ] Use Playwright to check page identity, nonblank content, framework overlays, console errors, and representative interactions.
- [ ] Update README and handoff with the changed call chain, evidence, remaining blockers, and authority limits.

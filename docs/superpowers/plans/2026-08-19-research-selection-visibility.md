# Research Selection Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the current research-only daily selection through the strategy API and display it beside F4 evidence with unambiguous date labels.

**Architecture:** Keep F4 and daily selection as separate read-only projections. Add one validated runner action for `selections/latest.json`, then have `StrategyPanel` fetch both projections independently so one failure cannot hide the other.

**Tech Stack:** Python, React/TypeScript, Node source contracts, pytest, Vite.

---

### Task 1: Read-only selection projection

**Files:**
- Modify: `scripts/strategy_runner.py`
- Modify: `tests/test_strategy_f4_projection.py`

- [x] Add failing tests for a valid selection, missing file, invalid authority and mismatched position count.
- [x] Run `python -m pytest tests\test_strategy_f4_projection.py -q` and verify RED failures caused by the missing action.
- [x] Add `SELECTION_LATEST_PATH` and `action_research_selection`; validate identity, allowed status, authority and positions before returning data.
- [x] Register only the new read action in `ACTIONS`; do not add write actions.
- [x] Rerun the focused Python tests and verify GREEN.

### Task 2: Selection and dual-date UI

**Files:**
- Modify: `scripts/f4_strategy_ui_contract_tests.mjs`
- Modify: `components/StrategyPanel.tsx`

- [x] Extend the UI contract to require `research_selection`, `F4/PIT 数据截止日`, `当前因子/选股日`, `每日研究选股组合`, `不构成交易信号` and research reason rendering.
- [x] Run `node scripts\f4_strategy_ui_contract_tests.mjs` and verify RED.
- [x] Add independent selection loading/error state and request `action: 'research_selection'`.
- [x] Replace the ambiguous F4 date label and add the current selection date metric.
- [x] Render the validated positions table with the reason column at the right and maximum available width.
- [x] Rerun the UI contract and TypeScript checks and verify GREEN.

### Task 3: Handoff and boundary documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/XUANJI_HANDOFF.md`
- Modify: `docs/XUANJI_SYSTEM_WORKFLOW_MAP.md`
- Modify: `scripts/research_boundary_contract_tests.mjs`

- [x] Add contract assertions for the two separate projections and non-trading boundary, then verify RED.
- [x] Document the F4/PIT weekly date, daily selection date, API action and failure-closed behavior.
- [x] Rerun documentation contracts and verify GREEN.

### Task 4: Runtime and regression verification

**Files:**
- Verify only.

- [x] Run focused Python tests for strategy projections and research selection.
- [x] Run all Node contracts, `npx tsc --noEmit` and `npm run build`.
- [x] Call live `market_scan` and `research_selection` APIs; verify separate dates, 20 positions and false execution authority.
- [x] Run `web_verify.mjs` and `ui_verify.mjs`; require zero browser console errors.
- [x] Recheck execution and paper write boundaries remain closed.
- [x] Update the handoff runtime snapshot without presenting a historical result as current success.

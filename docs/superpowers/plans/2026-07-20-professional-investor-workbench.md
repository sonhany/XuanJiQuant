# Professional Investor Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a trustworthy, decision-first, responsive simulation trading
workbench based on the approved 2026-07-20 live UI audit.

**Architecture:** Add one read-only workbench status contract that normalizes
account, scheduler, risk, alert, market, and authorization state. Consume that
contract through shared frontend helpers and a responsive application shell,
then refactor the cockpit and high-risk trading surfaces around the same truth.

**Tech Stack:** React 19, TypeScript, Vite, Node HTTP routes, Python runners,
SQLite KV state, Node built-in tests, pytest, Browser/IAB QA.

---

### Task 1: Unified workbench status contract

**Files:**
- Create: `server/routes/workbench.mjs`
- Modify: `server/router.mjs`
- Create: `tests/test_workbench_status_contract.py`

- [ ] Write failing tests for canonical scheduler state, account snapshot,
  subsystem errors, freshness, and fail-closed trade permission.
- [ ] Run `python -m pytest tests/test_workbench_status_contract.py -q` and
  confirm the new route contract is absent.
- [ ] Implement the read-only `/api/workbench action=status` route using
  existing persistent runners and cache state without modifying trading state.
- [ ] Re-run the focused test and confirm it passes.

### Task 2: Shared frontend workbench helpers

**Files:**
- Create: `lib/workbench-state.mjs`
- Create: `scripts/workbench_frontend_contract_tests.mjs`
- Create: `components/WorkbenchStatus.tsx`

- [ ] Write failing Node tests for freshness, permission derivation,
  percentage display, role capabilities, and unknown/loading states.
- [ ] Run `node scripts/workbench_frontend_contract_tests.mjs` and confirm the
  helpers are missing.
- [ ] Implement the helpers and reusable status/error components.
- [ ] Re-run the contract tests and confirm they pass.

### Task 3: Responsive application shell and honest local profile

**Files:**
- Modify: `App.tsx`
- Create: `components/AppShell.tsx`
- Create: `components/LocalProfileScreen.tsx`

- [ ] Add contract assertions for five navigation workspaces, logout/profile
  switching, role visibility, and mobile drawer hooks.
- [ ] Implement grouped navigation, global truth bar, local profile wording,
  logout, role-based visibility, and mobile drawer behavior.
- [ ] Verify desktop and 390px layouts have no horizontal page overflow.

### Task 4: Decision-first cockpit and scheduler controls

**Files:**
- Modify: `components/DashboardPanel.tsx`
- Modify: `components/AutonomousSchedulingDrawer.tsx`

- [ ] Add contract assertions that primary cockpit metrics exclude token and
  watchdog values and include permission/freshness/risk fields.
- [ ] Rebuild the first viewport around equity, P&L, exposure, cash, drawdown,
  risk state, target-current deltas, alerts, and source timestamps.
- [ ] Move operational AI details into a collapsible diagnostics section.
- [ ] Normalize percent inputs and separate save/start/run/debug actions with
  explicit scope and confirmation.

### Task 5: Safe simulation execution and paper portfolio

**Files:**
- Modify: `components/ExecutionPanel.tsx`
- Modify: `components/PaperPanel.tsx`
- Modify: `components/PaperStrategyConfig.tsx`

- [ ] Add contract assertions for simulation badge, order type, price,
  notional, available resources, pre-trade state, confirmation, and disabled
  submission when risk state is unknown.
- [ ] Implement the professional simulation order ticket and detailed order
  blotter without adding any real broker path.
- [ ] Make PaperPanel use canonical scheduler/account state and render
  performance/risk before logs.
- [ ] Unify position-limit descriptions and move token reset to diagnostics.

### Task 6: Authoritative risk and alert surfaces

**Files:**
- Modify: `components/RiskPanel.tsx`
- Modify: `components/AlertPanel.tsx`

- [ ] Add contract assertions for unknown/loading/error states and VaR
  methodology labels.
- [ ] Split portfolio risk, system diagnostics, and audit replay into tabs.
- [ ] Prevent failed requests from rendering healthy or zero states.
- [ ] Add operator/reason prompts for alert state-changing actions and protect
  critical rules from one-click silence.

### Task 7: Research and operations boundary cleanup

**Files:**
- Modify: `components/DbPanel.tsx`
- Modify: `components/FactorPanel.tsx`
- Modify: `components/StrategyPanel.tsx`
- Modify: `components/Jin10DataPanel.tsx`
- Modify: `components/QlibResearchPanel.tsx`
- Modify: `components/ValuationPanel.tsx`

- [ ] Add research-boundary and permission-state contract assertions.
- [ ] Label research results, expose as-of/source information, and distinguish
  unauthorized from empty results.
- [ ] Place data operations and Qlib controls under the system/research
  workspace while preserving existing functionality.

### Task 8: Documentation and complete verification

**Files:**
- Modify: `README.md`
- Modify: `.env.example`

- [ ] Document the new workspaces, truth bar, role capabilities, authorization,
  fail-closed behavior, responsive limits, and verification commands.
- [ ] Run focused Node and pytest contracts.
- [ ] Run relevant existing execution, risk, alert, paper, and authorization
  tests.
- [ ] Run `npm run build`.
- [ ] Start or reuse the local services and verify all five workspaces in
  Browser/IAB at desktop and 390px mobile viewports.
- [ ] Confirm no framework overlay, no relevant console errors, no horizontal
  mobile overflow, and no contradictory scheduler/account/risk state.


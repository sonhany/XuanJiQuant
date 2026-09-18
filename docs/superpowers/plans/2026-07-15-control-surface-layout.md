# Control Surface Layout Implementation Plan

> **For agentic workers:** Implement task-by-task with contract tests before
> production edits. Preserve the existing backend and `paper:config` contract.

**Goal:** Move autonomous scheduling into a cockpit drawer, move persistent
paper strategy and LLM configuration into a dedicated strategy-workspace tab,
focus the paper screen on execution monitoring, and simplify the root README
for model handoff.

**Architecture:** Add two focused frontend components. Keep
`DashboardPanel.tsx`, `StrategyPanel.tsx`, and `PaperPanel.tsx` as page
orchestrators. Continue reading and writing persistent paper settings through
the existing paper route and storage key.

**Tech Stack:** React 19, TypeScript, Lucide React, Vite, Node source contract
tests, Playwright browser verification.

---

### Task 1: Add failing ownership contract tests

**Files:**
- Create: `scripts/control_surface_layout_contract_tests.mjs`

- [ ] Assert that the cockpit imports and renders
  `AutonomousSchedulingDrawer`.
- [ ] Assert that the drawer owns the requested objective, model, risk, save,
  start, stop, run-once, and debug controls.
- [ ] Assert that the strategy workspace imports and renders
  `PaperStrategyConfig` under `模拟交易配置`.
- [ ] Assert that `PaperStrategyConfig` uses `/api/strategy` metadata and the
  existing `/api/paper` status, set-config, LLM-test, and usage actions.
- [ ] Assert that `PaperPanel` no longer owns editable strategy or LLM
  configuration.
- [ ] Run the new test and confirm that it fails before implementation.

### Task 2: Extract the autonomous scheduling drawer

**Files:**
- Create: `components/AutonomousSchedulingDrawer.tsx`
- Modify: `components/DashboardPanel.tsx`

- [ ] Build the responsive right-side drawer with overlay, close button, and
  Escape handling.
- [ ] Move target equity, horizon, provider, ultra mode, and four risk fields
  into the drawer.
- [ ] Preserve save, start, stop, run-once, and debug requests.
- [ ] Add a cockpit-header settings action and keep refresh separate.
- [ ] Convert the former control card into a read-only objective and target
  portfolio overview.
- [ ] Add narrow-screen stacking for the cockpit objective and main grids.

### Task 3: Add persistent paper configuration to the strategy workspace

**Files:**
- Create: `components/PaperStrategyConfig.tsx`
- Modify: `components/StrategyPanel.tsx`

- [ ] Load strategy metadata and persisted paper configuration without flashing
  destructive defaults.
- [ ] Render strategy/execution configuration and LLM decision configuration in
  a responsive two-column workspace.
- [ ] Track loaded values separately from edited values and expose dirty state.
- [ ] Validate position percentage, maximum positions, trade time, universe,
  and required strategy values.
- [ ] Save strategy and LLM fields in one `set_config` request while preserving
  backend-only fields.
- [ ] Keep LLM connection testing independent from saving.
- [ ] Preserve LLM token usage refresh/reset controls.
- [ ] Add retry, reload, save-in-progress, success, and failure states.
- [ ] Warn before leaving the tab when edits are unsaved.

### Task 4: Focus the paper screen on execution monitoring

**Files:**
- Modify: `components/PaperPanel.tsx`

- [ ] Remove local editable strategy, execution-limit, and LLM configuration
  state.
- [ ] Remove strategy metadata loading and configuration persistence helpers.
- [ ] Remove the strategy/LLM configuration card and save button.
- [ ] Keep read-only active strategy and LLM mode in the runtime status area.
- [ ] Make `测试执行一次` call `run_now` using the already saved
  `paper:config`.
- [ ] Keep AI screening functional by using the active saved provider.
- [ ] Stop AI screening refreshes from mutating a hidden local universe.

### Task 5: Simplify and archive documentation

**Files:**
- Create: `docs/README_REFERENCE.md`
- Modify: `README.md`

- [ ] Copy the current detailed README to the reference path without content
  loss.
- [ ] Replace the root README with a concise startup and model-handoff guide.
- [ ] Document page ownership and the `paper:config` relationship.
- [ ] Retain safety, verifier, risk-gateway, simulated-trading, and objective
  disclaimer boundaries.
- [ ] Link the detailed reference and current architecture/training documents.

### Task 6: Regression and visual verification

**Files:**
- Modify if needed: focused frontend files above

- [ ] Run the new ownership contract test.
- [ ] Run existing LLM and paper-screen contract tests that do not submit
  trades.
- [ ] Run `npm run build`.
- [ ] Verify the cockpit drawer at desktop and narrow viewport widths.
- [ ] Verify the new strategy tab, dirty state, responsive layout, and
  connection-test controls without saving changed values.
- [ ] Verify the paper screen layout and active-configuration summary.
- [ ] Check console errors, clipping, overlap, and horizontal scrolling.
- [ ] Do not submit a paper order or enable live trading during visual checks.

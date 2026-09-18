# Cockpit Asset Summary Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge objective progress, target portfolio, and paper account metrics
into one cockpit surface without changing data sources or trading behavior.

**Architecture:** Keep the existing `DashboardPanel.tsx` data loading and Card
component. Replace the upper card's metric structure, derive capital
utilization during render, and remove the later standalone account card.

**Tech Stack:** React 19, TypeScript, inline responsive CSS, Node source
contract tests, Vite.

---

### Task 1: Define the ownership contract

**Files:**
- Modify: `scripts/control_surface_layout_contract_tests.mjs`

- [ ] Add assertions that require `目标与账户总览` and `资金使用率`.
- [ ] Count `当前权益`, `可用现金`, `持仓市值`, and `持仓数量` labels and require
  exactly one occurrence each.
- [ ] Assert that `当前账户状态` is absent.
- [ ] Assert that README names the unified surface and single equity source.
- [ ] Run `node scripts/control_surface_layout_contract_tests.mjs`.
- [ ] Confirm failure reports the missing unified asset summary.

### Task 2: Consolidate cockpit financial metrics

**Files:**
- Modify: `components/DashboardPanel.tsx`

- [ ] Derive canonical current equity from
  `account?.total_equity ?? objective?.current_equity ?? 0`.
- [ ] Derive capital utilization from market value and canonical equity.
- [ ] Rename the upper card to `目标与账户总览`.
- [ ] Render eight unique metrics in the upper summary area.
- [ ] Keep the latest target portfolio in the right side of the same card.
- [ ] Remove the standalone `当前账户状态` card.
- [ ] Preserve existing account and objective timestamps in one footer line.
- [ ] Run the focused contract test and confirm it passes.

### Task 3: Update documentation

**Files:**
- Modify: `README.md`

- [ ] Replace separate objective/account wording with the unified cockpit
  surface.
- [ ] State that current equity appears once and prefers paper execution account
  equity.
- [ ] Keep target portfolio and scheduling drawer documentation unchanged.
- [ ] Run the focused contract test and confirm README assertions pass.

### Task 4: Verify layout and regressions

**Files:**
- Verify: `components/DashboardPanel.tsx`
- Verify: `README.md`

- [ ] Run `node scripts/control_surface_layout_contract_tests.mjs`.
- [ ] Run `node scripts/paper_screen_realtime_contract_tests.mjs`.
- [ ] Run `npm run build`.
- [ ] Open the cockpit without changing configuration.
- [ ] Confirm no repeated account labels at desktop width.
- [ ] Confirm metrics stack without horizontal overflow at narrow width.
- [ ] Confirm browser console has no errors or warnings.
- [ ] Do not save configuration, run the scheduler, or submit a paper trade.

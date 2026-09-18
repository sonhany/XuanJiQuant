# UI Audit Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the three approved UI audit findings without changing trading behavior or data contracts.

**Architecture:** Keep the existing AppShell and page components. Move the mobile navigation trigger into a shell-owned command row, stop the cockpit comparison grid from stretching its shorter column, and normalize non-semantic accents to the existing cyan token.

**Tech Stack:** React, TypeScript, inline component CSS, Node contract tests, Vite.

---

### Task 1: Lock the approved UI contracts

**Files:**
- Create: `scripts/ui_audit_fixes_contract_tests.mjs`

- [ ] Write assertions for a mobile command bar, no bottom-fixed menu trigger, natural cockpit grid height, and cyan non-semantic accents.
- [ ] Run `node scripts/ui_audit_fixes_contract_tests.mjs`.
- [ ] Confirm the test fails because the approved changes are not implemented.

### Task 2: Move mobile navigation into a command row

**Files:**
- Modify: `components/AppShell.tsx`

- [ ] Derive the current destination label from `WORKSPACES`.
- [ ] Render a mobile-only command row below the live index bar.
- [ ] Place the 38px menu button inside that row.
- [ ] Remove the fixed bottom-left positioning and obsolete bottom content padding.
- [ ] Run the focused contract test.

### Task 3: Remove cockpit grid stretching

**Files:**
- Modify: `components/DashboardPanel.tsx`

- [ ] Add `align-items: start` to `.cockpit-band`.
- [ ] Run the focused contract test.

### Task 4: Normalize decorative accents

**Files:**
- Modify: `components/ExecutionPanel.tsx`
- Modify: `components/RiskPanel.tsx`
- Modify: `components/AlertPanel.tsx`
- Modify: `components/PaperStrategyConfig.tsx`

- [ ] Replace orange, pink, coral, and purple decorative accents with `#38BDF8`.
- [ ] Preserve red, green, and yellow where they communicate gain/loss, warning, rejection, or risk.
- [ ] Run the focused contract test and existing related contracts.

### Task 5: Verify rendered behavior

- [ ] Run `npx tsc --noEmit`.
- [ ] Run `npm run build`.
- [ ] Verify the cockpit at desktop and 390px mobile widths.
- [ ] Open and close the mobile navigation drawer.
- [ ] Verify execution, risk, alerts, and strategy configuration use the cyan non-semantic accent.
- [ ] Confirm there are no relevant browser console errors.


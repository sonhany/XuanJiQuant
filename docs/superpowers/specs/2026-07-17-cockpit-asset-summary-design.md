# Cockpit Asset Summary Consolidation Design

## Goal

Consolidate the cockpit's objective progress, target portfolio, and paper
account status into one asset-and-objective surface. Each financial value must
have one canonical display location.

## Current Problem

The cockpit currently shows:

- current equity in `目标进度与组合`
- the same value again as total equity in `当前账户状态`
- target portfolio in the upper summary
- cash, market value, and position count in a separate right-column card

This duplicates equity and separates values that investors read together.

## Approved Layout

Rename the existing upper card to `目标与账户总览`.

The card uses two areas:

1. asset and objective summary
2. latest target portfolio

The asset and objective summary contains eight unique values:

- current equity
- target equity
- objective progress
- remaining days
- available cash
- position market value
- position count
- capital utilization

Current equity uses `account.total_equity` first and falls back to
`objective.current_equity`. It is not displayed anywhere else on the cockpit.

Capital utilization is derived as:

`market_value / total_equity * 100`

When total equity is zero or unavailable, display `0.00%`.

## Target Portfolio

The latest target portfolio remains on the right side of the same card and
continues to show:

- stock code
- target weight
- confidence
- committee or portfolio summary

Its empty state and source data remain unchanged.

## Removed Surface

Delete the standalone `当前账户状态` card from the right column.

The right column then contains:

- AI loop timeline
- historical memory

No API, backend state, polling interval, or storage key changes are required.

## Responsive Layout

Desktop:

- summary area: approximately 65%
- target portfolio: approximately 35%
- eight metrics: four columns by two rows

Medium width:

- the portfolio stacks below the summary
- metrics use two columns

Narrow width:

- metrics use one column
- no horizontal scrolling

## README

Update the cockpit responsibility section in `README.md` to describe one
`目标与账户总览` surface containing objective metrics, account metrics, and the
latest target portfolio.

The README must state that current equity is displayed once and sourced from
the paper execution account when available.

## Testing

Extend `scripts/control_surface_layout_contract_tests.mjs` so it fails before
implementation unless:

- `目标与账户总览` exists
- `资金使用率` exists
- `当前账户状态` no longer exists
- the account metric labels appear exactly once in `DashboardPanel.tsx`
- README documents the unified surface

Run the focused contract test, production build, and browser checks at desktop
and narrow widths.

## Acceptance Criteria

- the cockpit contains one asset-and-objective card
- current equity is rendered once
- cash, market value, and position count are rendered once
- capital utilization is shown
- the target portfolio remains visible in the same card
- the standalone account card is removed
- README matches the implemented layout
- no backend or trading behavior changes

# Control Surface Layout Design

## Goal

Reorganize the existing control surfaces without replacing the current visual
system:

- keep the cockpit focused on portfolio, risk, and autonomous-loop status
- move persistent paper strategy and LLM decision configuration into the
  strategy workspace
- keep the paper screen focused on execution monitoring and operational review
- reduce the root README to a concise model-handoff document while preserving
  the existing detailed reference

This is a frontend ownership and information-architecture change. It must not
change the paper configuration key, scheduler semantics, risk limits, verifier
boundary, execution behavior, or database schema.

## Current Configuration Relationships

The paper strategy fields and the LLM decision fields are two parts of the same
persistent runtime configuration:

- storage key: `paper:config`
- strategy metadata: `/api/strategy` with action `meta`
- configuration read: `/api/paper` with action `status`
- configuration write: `/api/paper` with action `set_config`
- LLM connectivity test: `/api/paper` with action `test_llm`

The following consumers depend on this configuration:

- `scripts/paper_runner.py`
- `scripts/paper_trader.py`
- `quant/risk/config.py`

Moving the controls must preserve these contracts. The UI must not create a
second configuration source or translate the values into a new storage shape.

## Page Responsibilities

### Cockpit

The cockpit is a read-oriented decision overview. It owns:

- portfolio and objective progress
- current market and global risk context
- subsystem health
- autonomous-loop status and recent activity
- a single entry point for autonomous scheduling settings

It does not expose persistent configuration inputs in the main content area.

### Strategy Workspace

The strategy workspace owns research and configuration:

- market scanning
- factor combinations
- strategy catalog
- one-off strategy runs and backtests
- persistent paper strategy and LLM decision configuration

One-off run parameters and persistent paper configuration remain separate
because they have different lifecycles and side effects.

### Paper Trading

The paper screen is an operational execution monitor. It owns:

- scheduler and execution status
- account and PnL summary
- positions, orders, trades, decisions, reports, and logs
- the existing manual test-execution action

It no longer owns strategy selection, paper position limits, execution time, or
LLM decision configuration.

## Cockpit Layout

Preserve the existing application navigation, brand treatment, and live index
bar. Reorganize the cockpit content into this hierarchy:

1. page header, freshness indicator, and `调度设置` action
2. primary portfolio and objective metrics
3. compact subsystem-health row
4. global risk and market context beside the AI loop timeline
5. position summary and recent exceptions

The scheduling action opens a right-side drawer. The drawer should be about
440 px wide on desktop and use the full viewport width on narrow screens.

### Scheduling Drawer

The drawer contains four ordered sections:

1. objective: target equity and duration
2. model: provider and ultra mode
3. risk: the four existing risk parameters
4. operations: start, stop, run once, and debug full loop

Action hierarchy:

- `启动` is the primary action
- `立即跑一轮` is secondary
- `停止` is destructive and visually restrained until needed
- `调试完整闭环` is an advanced action, separated from routine controls

Closing the drawer does not reset values. Existing requests, validation, toast
feedback, and autonomous status refresh behavior remain intact.

## Strategy Workspace Layout

Add a top-level tab named `模拟交易配置` after `策略运行`.

The desktop layout uses a responsive 12-column grid:

- left area, 7-8 columns: strategy and execution configuration
- right area, 4-5 columns: LLM decision configuration and active-config summary

At narrow widths the areas stack into one column.

### Strategy And Execution Area

This area contains the existing persistent fields:

- strategy
- strategy parameters
- universe
- position size percentage
- maximum positions
- trade time

Strategy metadata continues to come from `/api/strategy`. The current values
continue to come from `/api/paper`.

### LLM Decision Area

This area contains:

- enabled state
- provider
- decision mode
- connection test
- token-usage summary where currently available
- a compact summary of the active saved configuration

The UI must distinguish edited form values from the last saved active
configuration.

### Save Behavior

A stable action row remains visible at the bottom of the configuration surface.
It contains:

- dirty-state indicator
- last saved or last loaded timestamp
- reset/reload action when useful
- primary save action

Saving remains a single `set_config` operation so strategy and LLM values do not
diverge.

## Paper Trading Layout

Remove the `策略配置` and `AI 大模型决策` configuration surfaces.

Use the reclaimed space to strengthen the execution hierarchy:

1. runtime status, latest run, next run, and manual test-execution action
2. account equity, available cash, market value, and daily PnL
3. existing operational tabs for positions, orders, trades, decisions, reports,
   and logs

The screen may show the currently active strategy and LLM mode as read-only
status, but it must not duplicate editable controls.

## Component Boundaries

Create focused components instead of increasing the size of the current panels:

- `components/AutonomousSchedulingDrawer.tsx`
- `components/PaperStrategyConfig.tsx`

`DashboardPanel.tsx` owns drawer visibility and passes the existing autonomous
configuration and actions into `AutonomousSchedulingDrawer`.

`StrategyPanel.tsx` owns the new tab and renders `PaperStrategyConfig`.

`PaperStrategyConfig` owns loading, editing, dirty-state tracking, saving, and
LLM connectivity testing for `paper:config`.

`PaperPanel.tsx` removes the migrated state and controls while retaining
execution-monitoring state and actions.

## Interaction And Error States

### Loading

- render stable skeleton or disabled form structure
- do not flash default values before persisted values load

### Load Failure

- show an inline error near the configuration surface
- preserve the rest of the strategy workspace
- provide a retry action

### Dirty State

- mark the tab and action row when edited values differ from the loaded values
- warn before leaving the configuration tab with unsaved edits
- do not overwrite edits during background status refreshes

### Save

- disable repeated submissions while saving
- validate numeric and required values before the request
- after success, update the active-config snapshot from the saved response or a
  fresh status read
- on failure, retain all edits and show the backend error

### LLM Test

- test the currently selected provider and form values
- do not save automatically
- do not clear an existing provider configuration when testing fails

### Autonomous Operations

- preserve existing start, stop, run-once, and debug behavior
- disable incompatible operations while a request is active
- preserve current backend error details in user-visible feedback

## Visual Rules

- use the existing restrained dark theme and spacing system
- keep one primary accent plus semantic gain, loss, warning, and error colors
- use spacing and typography before adding borders
- avoid nested cards and decorative dashboard containers
- use Lucide icons for settings, close, refresh, save, play, stop, and debug
- keep financial values aligned and rendered with the existing numeric font
- use fixed control heights so loading and validation messages do not shift the
  page structure

## README Restructure

Move the current root README content to:

`docs/README_REFERENCE.md`

Replace the root README with a concise handoff document containing:

1. project purpose and non-live-trading safety boundary
2. five-minute startup and service ports
3. L0-L6 architecture and runtime data flow
4. page responsibility map
5. `paper:config` ownership and major API contracts
6. important directories and state stores
7. common verification commands
8. current limitations and handoff checklist
9. links to detailed architecture, training, design, and archived documentation

The root README must retain the statement that the one-year objective is a
research and pressure-testing target, not a return promise and not permission
to relax risk controls.

## Testing Strategy

Follow a frontend contract-test-first workflow.

Add a focused Node contract test that initially fails and proves:

- the cockpit renders the scheduling drawer entry
- all requested scheduling fields and four actions are owned by the drawer
- the strategy workspace renders the `模拟交易配置` tab
- the new configuration component uses the existing strategy and paper APIs
- the paper screen no longer renders editable strategy and LLM configuration
- the persistent storage/API contract has not been renamed

Then run:

- the new focused contract test
- existing paper and LLM contract tests
- `npm run build`
- browser verification at desktop and narrow viewport widths

Browser verification covers:

- drawer open, close, scrolling, and action hierarchy
- strategy-tab switching and responsive stacking
- load, dirty, save, error, and connection-test states
- paper-screen monitoring layout after configuration removal
- no overlap, clipping, or unintended horizontal scrolling

## Acceptance Criteria

- the existing cockpit remains the default cockpit; no V2 or V2.1 replacement
- cockpit configuration inputs exist only in the right-side drawer
- the drawer includes all eight requested configuration values and all four
  requested operations
- persistent strategy and LLM controls exist only under `模拟交易配置`
- one-off `策略运行` behavior remains unchanged
- the paper screen remains usable for monitoring and manual execution testing
- `paper:config` and all related backend contracts remain compatible
- no database migration is introduced
- the root README is concise and the previous detail remains available
- focused tests, relevant regressions, build, and browser layout checks pass

## Out Of Scope

- changing strategy algorithms or factor logic
- changing scheduler timing or autonomous-loop semantics
- changing risk limits or verifier behavior
- connecting to a live broker
- redesigning the global application navigation
- adopting the shelved cockpit V2.1

# Professional Investor Workbench Design

## Goal

Transform the current mixed research and operations console into a trustworthy
professional investor workbench without weakening verifier, risk gateway, T+1,
simulation-only, or audit boundaries.

The approved source for this design is the live UI audit performed on
2026-07-20. The user explicitly approved direct implementation without another
design review gate.

## Non-negotiable safety boundaries

- The application remains simulation and research only.
- No real broker integration or real-money order path is added.
- Missing, stale, unauthorized, or contradictory risk/account state fails
  closed and must never be rendered as "normal" or "allowed to trade".
- Existing verifier, risk gateway, T+1, price-limit, suspension, lot-size,
  cash, exposure, and kill-switch checks remain authoritative.
- High-impact controls require an explicit scope summary and confirmation.
- Research, model, and backtest metrics never imply live profitability.

## Information architecture

The application shell groups the current ten destinations into five workspaces:

1. Investment: cockpit.
2. Portfolio and trading: paper portfolio and simulation execution.
3. Risk: portfolio risk, alerts, and audit replay.
4. Research: strategy, factors, valuation, and Qlib.
5. Data and system: market data, news, data operations, scheduling, model cost,
   and diagnostics.

Desktop keeps a compact left rail. Narrow viewports use a top command bar and
an off-canvas navigation drawer. The main content must never be compressed
beside a fixed 200px sidebar.

## Global truth bar

Every authenticated application screen displays one canonical status bar:

- environment: simulation;
- account snapshot time and freshness;
- market phase;
- data connectivity;
- account connectivity;
- risk connectivity;
- trade permission: allowed, blocked, or unknown;
- operator and selected role.

The truth bar is built from a unified read-only API response. A partial failure
is represented per subsystem. Unknown or stale risk state blocks trade-capable
controls.

## Cockpit

The first viewport is investment-decision first:

- current equity;
- day P&L and day return;
- drawdown;
- cash;
- gross and net exposure;
- risk budget usage;
- trade permission and blocking reasons;
- account and market data as-of times.

Primary content:

- portfolio performance versus benchmark;
- current versus target holdings and rebalance delta;
- current risk exceptions and alerts;
- target portfolio with labels for target weight and confidence;
- external market risk with methodology, timestamp, confidence, and portfolio
  impact.

Scheduler, watchdog, token usage, memory statistics, tool execution, and the
full AI timeline move into a collapsible diagnostics area.

The extreme target-equity progress display is removed from the primary
cockpit. Planning data may remain in scheduling settings with a clear
simulation-only warning.

## Scheduling and configuration

- Percentages are displayed consistently as percentages.
- The saved value may remain decimal where required by backend contracts.
- Strategy position limits and autonomous risk limits show their effective
  source and conflicts.
- Model provider is read-only while only GLM is available.
- "Ultra Thinking" is renamed "Enhanced reasoning" with latency/cost help.
- Start, stop, run once, and full-loop diagnostics are distinct operations.
- Start does not silently save edited configuration.
- Run once states whether it produces analysis only, simulated intents, or
  simulated orders.
- Full-loop diagnostics are restricted to an advanced section and require
  confirmation.

## Simulation execution

The order ticket contains:

- symbol and resolved name;
- latest price and timestamp;
- market/limit order type;
- limit price when required;
- quantity and estimated notional;
- available cash or sellable quantity;
- estimated costs and slippage note;
- pre-trade checks and blocking reasons;
- explicit simulation badge;
- confirmation before submission.

The order list exposes order id, side, type, requested price, filled price,
status, rejection reason, timestamps, and cancel action where supported.

## Risk and alerts

Risk is the authoritative page and is separated from system diagnostics.
Required portfolio fields include:

- gross/net exposure;
- concentration;
- volatility;
- VaR with horizon, confidence, method, and sign convention;
- drawdown;
- liquidity and days-to-exit when available;
- current violations and pre-trade blocks.

Risk API failure renders a blocking error. It never renders an empty healthy
state.

Alert counts render as unknown while loading or unauthorized. Acknowledge,
resolve, silence, rule enablement, and rule disablement require operator
identity and a reason where the backend supports it. Critical trade, risk, and
data-integrity alerts cannot be silently hidden by a default one-hour action.

## Research and operations boundaries

- Factor, strategy, valuation, and Qlib surfaces are marked "research result".
- Backtests show benchmark, costs, out-of-sample status, and known limitations
  where data is available.
- PID, storage size, data-source probing, backfills, collection, model
  promotion, token reset, and diagnostics live under Data and System.
- Protected control failure is shown as a permission state, not as empty data.
- Qlib not-ready state remains visible but does not occupy the investor
  decision workflow.

## Authentication and role behavior

The existing local profile selector is presented honestly as a local workspace
profile, not secure authentication. It controls frontend visibility:

- simulation operator: decision, paper, risk, and permitted simulation actions;
- risk reviewer: read-only investment/risk/audit views;
- researcher: research and data views, no scheduler or order actions.

Backend token authorization remains mandatory for protected actions. The shell
provides logout/profile switching and shows when the frontend control token is
not configured.

## Responsive and accessibility requirements

- Desktop target: 1280px and wider.
- Tablet: grouped navigation drawer and two-column metric layouts.
- Mobile: one-column content, off-canvas navigation, no horizontal page scroll.
- Buttons remain at least 36px high and have visible focus treatment.
- Status is never communicated by color alone.
- A-share red-up/green-down semantics are used for A-share prices and returns;
  risk severity retains red/yellow/green semantics with text labels.

## Testing

- Python/API tests cover the unified status contract and fail-closed behavior.
- Node contract tests cover navigation grouping, percentage conversion,
  permission visibility, freshness labels, and trade-state derivation.
- Existing Python tests remain unchanged unless the implementation changes an
  intentional contract.
- Vite build and TypeScript checks must pass.
- Browser QA covers login/profile selection, cockpit, scheduling drawer,
  execution ticket, risk failure state, alerts, research navigation, desktop,
  and 390px mobile layout.


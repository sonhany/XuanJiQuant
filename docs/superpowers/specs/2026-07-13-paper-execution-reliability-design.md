# Paper Execution Reliability Design

## Goal

Repair the paper execution path so that autonomous trading uses normalized live
quotes, cannot permanently lock itself after historical orders, can always
reduce risk when legal A-share constraints permit, and persists execution state
with replayable audit evidence.

## Scope

This change remains paper-only. It does not add a live broker, weaken the AI
decision contract, bypass the verifier, or allow orders around T+1, suspension,
or limit-down constraints.

## Architecture

1. `scripts/execution_runner.py` remains the runtime execution service.
2. A cross-process execution lock serializes state-changing operations from the
   Web runner, paper trader, and scheduler stop scanner.
3. Read-only status actions calculate fresh marks without writing the shared
   state document.
4. Runtime state is normalized on load so legacy paper-router summary records
   do not count as executable orders.
5. Risk checks derive whether an order is exposure-reducing from the current
   portfolio. Legal reducing sells ignore entry-blocking limits such as daily
   loss, drawdown, turnover, and per-run order count.
6. Daily-loss and drawdown gates use persisted day-start and peak-equity
   baselines.
7. Paper orders carry deterministic `client_order_id` values. Successful or
   active orders are deduplicated in the execution service; transient failures
   remain retryable.
8. Execution state and critical order/trade audit rows are committed in one
   SQLite transaction when SQLite is the active cache.

## Data Compatibility

Existing positions, cash, trades, and canonical orders are preserved. Duplicate
legacy order-summary rows are merged into their canonical order by order ID.
Existing databases gain baseline fields only:

- `trading_day`
- `day_start_equity`
- `peak_equity`

## Risk Semantics

Risk-increasing buys remain subject to every configured limit. Exposure-reducing
sells remain subject to:

- valid code, direction, quantity, and price
- suspension and limit-down restrictions
- current position quantity
- T+1 available quantity

They are not blocked by daily-loss, drawdown, turnover, capital-cap, kill-switch,
or per-run order-count gates. This preserves emergency de-risking without
allowing new exposure.

## Execution Fidelity

Live quote responses are normalized from prefixed keys such as `sh600519` and
`sz000001` to requested six-digit codes. Automatic market fills use a
configurable volume participation cap and quantity-sensitive impact slippage
when a valid intraday/daily volume observation exists. Missing volume falls back
to the current fixed base slippage instead of fabricating liquidity.

## Audit

The following state changes must produce structured audit rows:

- order accepted, rejected, partially filled, or filled
- manual fill and cancellation
- reset
- stop configuration and triggered stop attempt

SQLite execution-state and order/trade rows are written transactionally.
Non-SQLite caches retain the existing best-effort path.

## Verification

- Regression tests must fail against the previous implementation.
- Unit tests cover quote normalization, reducing exits, per-run counts,
  daily-loss/drawdown baselines, idempotency, state normalization, trailing
  stops, and atomic persistence.
- Existing risk, paper, audit, strategy, and frontend build checks must pass.
- Runtime verification is read-only after restart; no test order is submitted.

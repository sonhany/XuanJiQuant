# Paper Execution Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make paper execution live-price aware, concurrency-safe, exit-safe, correctly rate-limited, idempotent, and transactionally audited.

**Architecture:** Keep `scripts/execution_runner.py` as the runtime service while extracting cross-process locking and transactional persistence into focused helpers. Preserve all verifier and hard-risk boundaries, but distinguish exposure-increasing orders from legal exposure-reducing exits.

**Tech Stack:** Python 3.11, SQLite WAL, pytest, Node/React build verification.

---

### Task 1: Quote normalization and execution marks

**Files:**
- Modify: `scripts/execution_runner.py`
- Test: `tests/test_execution_reliability.py`

- [ ] Add failing tests proving prefixed market keys are not resolved.
- [ ] Normalize quote keys back to requested six-digit codes.
- [ ] Verify single and batch live-price tests pass.

### Task 2: Risk-reducing exits and account baselines

**Files:**
- Modify: `quant/risk/gateway.py`
- Modify: `scripts/execution_runner.py`
- Modify: `scripts/paper/pretrade_risk.py`
- Test: `tests/test_risk_gateway.py`
- Test: `tests/test_execution_reliability.py`

- [ ] Add failing tests for stop sells blocked by loss, turnover, order count, and kill switch.
- [ ] Derive reducing status from portfolio positions.
- [ ] Add day-start and peak-equity fields and enforce real daily loss/drawdown.
- [ ] Keep T+1, suspension, and limit-down blocking for reducing exits.

### Task 3: Order state normalization and per-run limits

**Files:**
- Modify: `scripts/execution_runner.py`
- Test: `tests/test_execution_reliability.py`

- [ ] Add failing tests for legacy duplicate order rows and lifetime order counts.
- [ ] Normalize duplicate state rows by order ID.
- [ ] Count canonical orders for the current run only.
- [ ] Persist the normalized state during controlled startup migration.

### Task 4: Cross-process state serialization

**Files:**
- Create: `quant/execution/state_lock.py`
- Modify: `scripts/execution_runner.py`
- Test: `tests/test_execution_state_lock.py`

- [ ] Add failing lock and read-only mutation tests.
- [ ] Implement a reentrant cross-process file lock with timeout.
- [ ] Wrap every state-changing action.
- [ ] Stop status, positions, and all actions from persisting mark-only refreshes.

### Task 5: End-to-end idempotency

**Files:**
- Modify: `scripts/paper/order_router.py`
- Modify: `scripts/paper_trader.py`
- Modify: `scripts/execution_runner.py`
- Test: `tests/test_paper_order_router.py`
- Test: `tests/test_execution_reliability.py`

- [ ] Add failing tests for retryable failures and duplicate successful intents.
- [ ] Generate deterministic `client_order_id` values.
- [ ] Deduplicate active/successful orders in execution state.
- [ ] Mark paper decisions only after successful order acceptance.

### Task 6: Stops and simulated fill fidelity

**Files:**
- Modify: `scripts/execution_runner.py`
- Test: `tests/test_execution_reliability.py`

- [ ] Add failing tests for trailing-stop overwrite and T+1 partial exits.
- [ ] Preserve the configured trailing stop after market fills.
- [ ] Sell only available quantity during emergency exits.
- [ ] Add volume participation and quantity-sensitive impact slippage.

### Task 7: Transactional audit persistence

**Files:**
- Modify: `quant/data/audit.py`
- Modify: `scripts/execution_runner.py`
- Test: `tests/test_execution_audit_atomic.py`

- [ ] Add failing tests for atomic state/order/trade commits.
- [ ] Add one SQLite transaction helper for execution state and structured events.
- [ ] Audit cancellation, reset, stop configuration, and stop attempts.
- [ ] Preserve a best-effort fallback for non-SQLite caches.

### Task 8: Documentation, migration, and verification

**Files:**
- Modify: `README.md`

- [ ] Update execution, risk, idempotency, stop, and audit documentation.
- [ ] Run the focused regression suite.
- [ ] Run all Python tests and contract tests.
- [ ] Run `npm run build`.
- [ ] Restart the local services without enabling live trading.
- [ ] Verify status, positions, normalized order count, live price source, and audit health using read-only calls.

# XuanJiQuant Realtime Market and Cockpit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-flight, near-real-time market synchronization path that updates market browse, watch quotes, F5 mark-to-market, cockpit equity, and deterministic risk without creating orders or weakening data truth.

**Architecture:** A server-side synchronization policy governs a hot quote loop and a complete-market loop. A local SSE service broadcasts committed snapshots; a fixed F5 mark-to-market action consumes only trusted server cache facts and writes current valuation inside the F5 ledger. The cockpit reads a fast valuation/risk path while slow diagnostics refresh in the background.

**Tech Stack:** Python 3.14 data/F5 runners, SQLite WAL, Node.js 24 HTTP/SSE, React 19, TypeScript 5.8, Vite 8, native `EventSource`, pytest, Node contract tests, Playwright/browser QA.

**Spec:** `docs/superpowers/specs/2026-09-01-realtime-market-cockpit-design.md`

## Global Constraints

- Active workspace is only `C:\Users\HYSHEN\XuanJiQuant`; never read from or write to the frozen backup.
- Hot quote interval is 1000 ms, timeout 800 ms, maximum 200 symbols, and stale threshold 3000 ms.
- Complete-market target interval is 8000 ms; only a complete generation may replace Top100.
- F5 current-account authority remains `data/paper/f5_ledger.db`; no fallback to `execution:state`.
- Mark-to-market cannot change orders, fills, cash ledger entries, quantities, average cost, strategy evidence, or execution authority.
- `live_execution_authority=false` is invariant.
- Do not add npm dependencies; use native Node HTTP and browser `EventSource`.
- Current directory has no `.git`; do not initialize a repository. At each checkpoint record fresh test evidence instead of committing.
- All implementation uses TDD: failing test, observed expected failure, minimal implementation, passing focused test, then broader regression.

## File and Responsibility Map

- `config/data_sync_policy.json`: single cross-language cadence and freshness authority.
- `quant/data/sync_policy.py`: typed Python validation and policy lookup.
- `server/sync-policy.mjs`: Node validation and policy lookup.
- `scripts/data_runner.py`: trustworthy hot snapshots and complete Top100 generations.
- `server/data-runners.mjs`: isolated persistent runners for normal, hot, and full-market lanes.
- `server/market-stream-service.mjs`: subscription union, loops, single-flight state, F5 mark trigger, and event publication.
- `server/routes/market-stream.mjs`: local read-only SSE framing and lifecycle.
- `quant/paper_execution/ledger.py`: F5 live mark/account schema and transactional persistence.
- `quant/paper_execution/service.py`: valuation calculation without trade mutation.
- `scripts/f5_paper_runner.py`: fixed no-parameter `mark_to_market` action and live projection.
- `quant/paper_execution/reporting.py`: current-account projection from committed live valuation.
- `server/workbench-cache.mjs`: non-blocking slow diagnostics cache.
- `server/routes/workbench.mjs`: fast REST composition and cockpit event projection.
- `hooks/useMarketStream.ts`: shared SSE subscription, sequence checks, reconnect, visibility handling, and polling fallback.
- `components/DbPanel.tsx`: Top100 and watch-quote stream consumers.
- `components/DashboardPanel.tsx`: cockpit mark consumer and three freshness timestamps.
- Existing Jin10/CNINFO/risk/alerts panels: consume policy cadences rather than private arbitrary timers.

---

### Task 1: Cross-Language Synchronization Policy

**Files:**
- Create: `config/data_sync_policy.json`
- Create: `quant/data/sync_policy.py`
- Create: `server/sync-policy.mjs`
- Test: `tests/test_data_sync_policy.py`
- Test: `scripts/data_sync_policy_contract_tests.mjs`

**Interfaces:**
- Produces Python `load_sync_policy() -> dict[str, SyncPolicy]` and `policy_snapshot() -> dict`.
- Produces Node `syncPolicy(name)` and `syncPolicySnapshot()`.
- Both readers reject missing datasets, non-positive cadence, active cadence faster than the hard floor, and JSON schema drift.

- [ ] **Step 1: Write failing Python policy tests**

```python
def test_policy_contains_all_governed_domains():
    policies = load_sync_policy()
    assert policies["hot_quotes"].active_interval_ms == 1000
    assert policies["market_top100"].active_interval_ms == 8000
    assert policies["cockpit_risk"].active_interval_ms == 2000
    assert policies["jin10_flash"].active_interval_ms == 30000
    assert policies["cninfo_latest"].active_interval_ms == 60000

def test_policy_rejects_frontend_override_below_hard_floor(tmp_path):
    path = write_policy(tmp_path, hot_quotes={"active_interval_ms": 100})
    with pytest.raises(ValueError, match="hard floor"):
        load_sync_policy(path)
```

- [ ] **Step 2: Run Python tests and observe expected import/file failure**

Run: `python -m pytest tests/test_data_sync_policy.py -q`

Expected: FAIL because `quant.data.sync_policy` and the JSON authority do not exist.

- [ ] **Step 3: Write failing Node parity contract**

```js
const pyPolicy = JSON.parse(fs.readFileSync('config/data_sync_policy.json', 'utf8'));
assert.equal(syncPolicy('hot_quotes').active_interval_ms, 1000);
assert.deepEqual(syncPolicySnapshot(), pyPolicy.datasets);
```

- [ ] **Step 4: Implement the policy authority and both readers**

The JSON must contain the complete matrix from spec section 11.1 with fields:

```json
{
  "schema_version": "xuanji-data-sync-policy-v1",
  "datasets": {
    "hot_quotes": {"active_interval_ms": 1000, "background_interval_ms": 60000, "stale_after_ms": 3000, "hard_floor_ms": 1000},
    "market_top100": {"active_interval_ms": 8000, "background_interval_ms": 60000, "stale_after_ms": 12000, "hard_floor_ms": 8000},
    "cockpit_risk": {"active_interval_ms": 2000, "background_interval_ms": 60000, "stale_after_ms": 3000, "hard_floor_ms": 2000}
  }
}
```

Add every remaining row from the spec with explicit owner/source/fallback and market phase fields.

- [ ] **Step 5: Run focused policy tests**

Run: `python -m pytest tests/test_data_sync_policy.py -q; node scripts/data_sync_policy_contract_tests.mjs`

Expected: all pass.

- [ ] **Step 6: Record checkpoint evidence**

Record the two fresh passing summaries in the task progress. Do not initialize Git.

---

### Task 2: Trustworthy Hot and Complete-Market Snapshots

**Files:**
- Modify: `scripts/data_runner.py`
- Modify: `scripts/market_data.py`
- Create: `tests/test_realtime_snapshot_contract.py`
- Modify: `scripts/data_browser_latency_contract_tests.mjs`

**Interfaces:**
- Produces action `hot_snapshot` accepting only normalized `codes` and returning `{snapshot_id, quote_timestamp, received_at, market_phase, quotes, stale, age_ms}`.
- Produces complete `stocks` snapshots with `{generation_id, coverage, complete, refreshing, latest_time}`.
- Completed Top100 generations always return `refreshing=false`; building state is separate metadata.

- [ ] **Step 1: Write failing snapshot identity and freshness tests**

```python
def test_hot_snapshot_has_stable_identity_and_per_symbol_freshness(monkeypatch):
    monkeypatch.setattr(data_runner, "fetch_realtime", fixed_quotes)
    out = data_runner.action_hot_snapshot({"codes": ["600519", "000001"]})
    assert out["snapshot_id"]
    assert out["quotes"]["600519"]["age_ms"] >= 0
    assert out["quotes"]["600519"]["stale"] is False

def test_completed_background_top_snapshot_is_not_marked_refreshing():
    out = build_complete_top_snapshot(background_refresh=True)
    assert out["complete"] is True
    assert out["refreshing"] is False
```

- [ ] **Step 2: Run focused tests and observe missing action/incorrect refreshing failure**

Run: `python -m pytest tests/test_realtime_snapshot_contract.py -q`

- [ ] **Step 3: Implement snapshot normalization and atomic complete generation**

Add helpers with exact signatures:

```python
def normalize_hot_snapshot(codes: list[str], quotes: dict, *, received_at: datetime) -> dict: ...
def action_hot_snapshot(req: dict) -> dict: ...
def complete_top_generation(rows: list[dict], meta: dict) -> dict: ...
```

Use content hashes over sorted normalized codes, quote timestamps, sources, and prices. Keep the existing stale generation until the new full-market coverage gate passes.

- [ ] **Step 4: Add single-flight and timeout tests**

```python
def test_overlapping_top_refresh_returns_existing_generation_and_does_not_start_second_worker(): ...
def test_hot_snapshot_rejects_future_or_wrong_trade_date_quote(): ...
def test_partial_hot_failure_marks_only_failed_symbol_stale(): ...
```

- [ ] **Step 5: Run data-layer tests**

Run: `python -m pytest tests/test_realtime_snapshot_contract.py scripts/data_source_chain_contract_tests.py -q`

Expected: all pass.

- [ ] **Step 6: Record checkpoint evidence**

Record test totals and one live 15-symbol `hot_snapshot` latency measurement.

---

### Task 3: Market Stream Service and Local SSE Route

**Files:**
- Create: `server/data-runners.mjs`
- Modify: `server/routes/data.mjs`
- Create: `server/market-stream-service.mjs`
- Create: `server/routes/market-stream.mjs`
- Modify: `server/router.mjs`
- Modify: `server/index.mjs`
- Test: `scripts/market_stream_service_tests.mjs`
- Test: `scripts/market_stream_route_contract_tests.mjs`

**Interfaces:**
- `MarketStreamService.subscribe(clientId, codes, channels, send) -> unsubscribe()`.
- `MarketStreamService.snapshot() -> {clients, symbols, loops, last_success, last_error}`.
- GET `/api/market-stream?codes=600519,000001&channels=hot_quotes,market_top100,cockpit_mark` returns SSE.

- [ ] **Step 1: Write failing single-flight service tests with injected clocks/runners**

```js
const service = new MarketStreamService({ hotRunner, fullRunner, clock, policy });
service.subscribe('a', ['600519'], ['hot_quotes'], sendA);
service.subscribe('b', ['600519'], ['hot_quotes'], sendB);
await clock.tickAsync(1000);
assert.equal(hotRunner.calls.length, 1);
assert.equal(sendA.events.at(-1).type, 'hot_quotes');
assert.equal(sendB.events.at(-1).snapshot_id, sendA.events.at(-1).snapshot_id);
```

- [ ] **Step 2: Run and observe missing module failure**

Run: `node scripts/market_stream_service_tests.mjs`

- [ ] **Step 3: Implement isolated runners and service loops**

`data-runners.mjs` exports three singleton runners: `dataReadRunner`, `dataHotRunner`, `dataFullRunner`. Hot and full loops use different processes. Service loops use a boolean in-flight gate, absolute deadline, and latest-event replacement rather than unbounded queues.

- [ ] **Step 4: Write and run SSE route failure tests**

Assert local Origin enforcement, event ids, heartbeat formatting, maximum 200 symbols, and cleanup after socket close.

- [ ] **Step 5: Implement SSE route and server lifecycle**

The route writes:

```text
id: <sequence>\n
event: hot_quotes\n
data: <single-line-json>\n\n
```

Register server shutdown cleanup. Do not accept token in query parameters.

- [ ] **Step 6: Run focused Node tests**

Run: `node scripts/market_stream_service_tests.mjs; node scripts/market_stream_route_contract_tests.mjs; npm run test:contracts`

- [ ] **Step 7: Record checkpoint evidence**

Record event counts and prove two subscribers generate one hot-runner call.

---

### Task 4: F5 Live Mark Ledger Schema

**Files:**
- Modify: `quant/paper_execution/ledger.py`
- Test: `tests/test_f5_live_marks.py`

**Interfaces:**
- `PaperLedger.replace_live_marks(batch: dict, marks: list[dict], account: dict) -> None`.
- `PaperLedger.live_marks() -> list[dict]`.
- `PaperLedger.live_account() -> dict | None`.
- `PaperLedger.maybe_append_equity_from_mark(account, *, minimum_interval_seconds=30) -> bool`.

- [ ] **Step 1: Write failing migration and transactional tests**

```python
def test_live_mark_tables_are_created_without_changing_existing_rows(ledger):
    before = ledger_invariant_hashes(ledger)
    assert ledger.live_marks() == []
    assert ledger_invariant_hashes(ledger) == before

def test_replace_live_marks_is_atomic_and_preserves_trade_facts(ledger):
    before = trade_fact_hashes(ledger)
    ledger.replace_live_marks(batch, marks, account)
    assert ledger.live_account()["market_snapshot_id"] == batch["snapshot_id"]
    assert trade_fact_hashes(ledger) == before
```

- [ ] **Step 2: Run tests and observe missing methods failure**

Run: `python -m pytest tests/test_f5_live_marks.py -q`

- [ ] **Step 3: Implement idempotent schema and methods**

Create `paper_live_marks` keyed by code and `paper_live_account` with singleton id `current`. Use one transaction for batch, mark rows, and live account. Reject duplicate snapshot ids with different content.

- [ ] **Step 4: Add 30-second history throttle tests**

Test first mark, 29-second no append, 30-second append, and execution-event forced append.

- [ ] **Step 5: Run ledger and reconciliation regressions**

Run: `python -m pytest tests/test_f5_live_marks.py tests/test_f5_paper_ledger.py tests/test_f5_paper_reconciliation.py -q`

- [ ] **Step 6: Record checkpoint evidence**

Record schema test count and invariant hashes from the fixture test output.

---

### Task 5: Fixed F5 Mark-to-Market Action

**Files:**
- Modify: `quant/paper_execution/service.py`
- Modify: `quant/paper_execution/reporting.py`
- Modify: `scripts/f5_paper_runner.py`
- Modify: `server/routes/paper-execution.mjs`
- Test: `tests/test_f5_mark_to_market.py`
- Modify: `scripts/f5_paper_execution_contract_tests.mjs`

**Interfaces:**
- `PaperExecutionService.mark_to_market(snapshot: dict, *, now: datetime) -> dict` is internal and consumes validated server snapshot format.
- Runner action `{action: "mark_to_market"}` accepts no other business fields and loads trusted `hot_snapshot` from the shared cache itself.
- Account projection includes `market_snapshot_id`, `quote_timestamp`, `valuation_as_of`, `stale`, and `daily_pnl_baseline`.

- [ ] **Step 1: Write failing no-parameter boundary tests**

```python
@pytest.mark.parametrize("field", ["codes", "quotes", "price", "quantity", "cash", "date"])
def test_runner_rejects_mark_to_market_business_parameters(field):
    out = run_action({"action": "mark_to_market", field: "forbidden"})
    assert out["success"] is False
    assert out["reason_code"] == "mark_to_market_parameters_forbidden"
```

- [ ] **Step 2: Write failing valuation and invariant tests**

```python
def test_mark_updates_equity_and_daily_pnl_without_trade_mutation(service):
    before = immutable_execution_hashes(service.ledger)
    out = service.mark_to_market(snapshot, now=NOW)
    assert out["total_equity"] == pytest.approx(expected_equity)
    assert out["daily_pnl"] == pytest.approx(expected_equity - previous_close_equity)
    assert immutable_execution_hashes(service.ledger) == before
```

- [ ] **Step 3: Run and observe missing action failure**

Run: `python -m pytest tests/test_f5_mark_to_market.py -q`

- [ ] **Step 4: Implement trusted cache loading, validation, and valuation**

Reject wrong trade date, age over 3 seconds in active session, non-positive price, unknown source, and missing holdings. During execution write contention return `mark_deferred_execution_active`; do not trigger recovery or kill switch.

- [ ] **Step 5: Make reporting prefer committed live account**

`active_account_projection` uses `paper_live_account` only when it matches current holdings and passes freshness state. It retains stale values with timestamps but never labels them live. Quantity, average cost, and cash continue from existing ledger facts.

- [ ] **Step 6: Run focused and existing F5 tests**

Run: `python -m pytest tests/test_f5_mark_to_market.py tests/test_f5_paper_reporting.py tests/test_f5_runtime_publication.py tests/test_f5_paper_service.py -q; node scripts/f5_paper_execution_contract_tests.mjs`

- [ ] **Step 7: Record checkpoint evidence**

Record before/after immutable hashes and one 15-position valuation result.

---

### Task 6: Cockpit Fast Path and Stream Coupling

**Files:**
- Create: `server/workbench-cache.mjs`
- Modify: `server/routes/workbench.mjs`
- Modify: `server/market-stream-service.mjs`
- Test: `scripts/workbench_fast_path_tests.mjs`
- Modify: `scripts/cockpit_latency_contract_tests.mjs`

**Interfaces:**
- `WorkbenchSlowCache.start()` refreshes health every 10 seconds and research selection every 30 seconds.
- `composeFastWorkbenchStatus({activeLedger, risk, slow, paperStatus})` returns account/risk immediately with independent slow timestamps.
- `MarketStreamService` calls fixed F5 `mark_to_market` after each valid hot snapshot containing holdings, then emits `cockpit_mark`.

- [ ] **Step 1: Write failing non-blocking cache test**

```js
const slowHealth = deferred();
const result = await composeRequest({ healthPromise: slowHealth.promise, account: fastAccount });
assert.equal(result.account.total_equity, fastAccount.total_equity);
assert.equal(result.diagnostics.state, 'refreshing');
```

- [ ] **Step 2: Run and observe current 3-second blocking failure**

Run: `node scripts/workbench_fast_path_tests.mjs`

- [ ] **Step 3: Implement slow cache and fast composer**

Initial workbench request may start slow refresh but must not await it. Cache objects carry `as_of`, `stale`, `last_error`, and `refreshing`.

- [ ] **Step 4: Bind risk to the same market snapshot**

Risk output must include `market_snapshot_id`, `valuation_as_of`, and `calculated_at`. Reject mixed batch in tests.

- [ ] **Step 5: Add market-stream F5 trigger tests**

Prove one mark action per unique hot snapshot, no mark on duplicate snapshot, no mark when holdings are absent, and no stream failure when mark is deferred.

- [ ] **Step 6: Run focused and latency contracts**

Run: `node scripts/workbench_fast_path_tests.mjs; node scripts/cockpit_latency_contract_tests.mjs; npm run test:contracts`

- [ ] **Step 7: Record checkpoint evidence**

Measure 20 warm workbench requests and record median/p95; target p95 below 300 ms.

---

### Task 7: Shared React SSE Hook and Market Pages

**Files:**
- Create: `hooks/useMarketStream.ts`
- Create: `lib/market-stream-types.ts`
- Modify: `components/DbPanel.tsx`
- Test: `scripts/market_stream_frontend_contract_tests.mjs`
- Modify: `scripts/data_browser_latency_contract_tests.mjs`

**Interfaces:**
- `useMarketStream({channels, codes, enabled, fallback})` returns `{events, status, lastEventAt, reconnects, truncated}`.
- Events are ignored when sequence is duplicate/older.
- Exactly one of SSE or fallback polling may be active.

- [ ] **Step 1: Write failing source contracts**

Assert native `EventSource`, visibility handling, ordered event id, reconnect delays `[1000,2000,5000,10000]`, cleanup, and absence of old 5/15-second primary polling timers.

- [ ] **Step 2: Run and observe missing hook failure**

Run: `node scripts/market_stream_frontend_contract_tests.mjs`

- [ ] **Step 3: Implement hook with injectable EventSource for tests**

Batch React state updates per snapshot. Close stream on unmount or subscription change. On 30-second outage start policy-governed fallback; stop it immediately on SSE open.

- [ ] **Step 4: Convert market browse and realtime panel**

Top100 uses `market_top100`; watch panel uses `hot_quotes`. Keep initial REST snapshot. Render actual quote timestamp/source/stale state rather than browser receipt time.

- [ ] **Step 5: Add render-performance safeguards**

Memoize row components and only flash changed prices. Do not reconstruct all rows when snapshot id is unchanged.

- [ ] **Step 6: Run contracts, TypeScript, and build**

Run: `node scripts/market_stream_frontend_contract_tests.mjs; node scripts/data_browser_latency_contract_tests.mjs; npx tsc --noEmit; npm run build`

- [ ] **Step 7: Record checkpoint evidence**

Record build result and React update counts for unchanged versus changed snapshots.

---

### Task 8: Cockpit Streaming UI and Freshness Truth

**Files:**
- Modify: `components/DashboardPanel.tsx`
- Modify: `lib/workbench-state.mjs`
- Test: `scripts/cockpit_realtime_contract_tests.mjs`
- Modify: `scripts/cockpit_target_portfolio_contract_tests.mjs`

**Interfaces:**
- Initial `status` loads complete workbench state.
- `cockpit_mark` patches only account, positions, risk, and freshness when snapshot id is newer.
- UI shows quote, valuation, and risk timestamps plus `实时/延迟/休市/降级/不可用`.

- [ ] **Step 1: Write failing UI truth contracts**

Assert the three timestamps, 3-second yellow threshold, 15-second red threshold, market phase label, stream status, and no numeric zero for unavailable PnL.

- [ ] **Step 2: Run and observe missing streaming/freshness UI failure**

Run: `node scripts/cockpit_realtime_contract_tests.mjs`

- [ ] **Step 3: Implement stream patching and periodic full reconciliation**

Use SSE marks continuously and perform a full REST reconciliation every 30 seconds. The manual refresh remains available and triggers only read/reconciliation, never trade execution.

- [ ] **Step 4: Keep slow diagnostics visibly independent**

Render diagnostics `as_of` and stale status separately; do not replace live KPI status with slow diagnostics status.

- [ ] **Step 5: Run frontend regressions**

Run: `node scripts/cockpit_realtime_contract_tests.mjs; node scripts/cockpit_target_portfolio_contract_tests.mjs; npx tsc --noEmit; npm run build`

- [ ] **Step 6: Record checkpoint evidence**

Record a two-minute sample showing changing quote/valuation/risk timestamps with stable order/fill counts.

---

### Task 9: Full-Function Synchronization Governance

**Files:**
- Modify: `components/Jin10DataPanel.tsx`
- Modify: `components/CninfoDisclosurePanel.tsx`
- Modify: `components/RiskPanel.tsx`
- Modify: `components/AlertPanel.tsx`
- Modify: `components/FinancialStatementsPanel.tsx`
- Modify: `server/routes/sync.mjs`
- Modify: `server/router.mjs`
- Test: `scripts/full_sync_policy_contract_tests.mjs`
- Test: `tests/test_sync_catalog.py`

**Interfaces:**
- Read-only `/api/sync` action `catalog` returns every policy row with `fact_as_of`, `last_success`, `stale`, `coverage`, `state`, and `reason`.
- Panels use policy cadences; they cannot hard-code faster upstream timers.

- [ ] **Step 1: Write failing catalog and panel cadence tests**

Test all spec matrix domains exist. Assert Jin10 flash 30 seconds, news 60 seconds, calendar 5 minutes, CNINFO visible 60 seconds/background 5 minutes, risk 2 seconds/60 seconds, alert 5 seconds/60 seconds, and system health 10 seconds.

- [ ] **Step 2: Run and observe missing catalog/policy consumption failure**

Run: `python -m pytest tests/test_sync_catalog.py -q; node scripts/full_sync_policy_contract_tests.mjs`

- [ ] **Step 3: Implement sync catalog aggregation**

Aggregate existing runner status and cache timestamps without starting expensive refreshes from a read action. Static/daily/weekly datasets report their natural fact boundary and next scheduled update.

- [ ] **Step 4: Replace private panel timers with policy values**

Use visibility-aware active/background cadence. Financials refresh on open and new disclosure identity, not every minute. Factor/F4/Qlib panels report deterministic schedule freshness and never retrain from page polling.

- [ ] **Step 5: Run focused and all contracts**

Run: `python -m pytest tests/test_sync_catalog.py -q; node scripts/full_sync_policy_contract_tests.mjs; npm run test:contracts`

- [ ] **Step 6: Record checkpoint evidence**

Capture the catalog JSON summary and prove every UI domain maps to one policy owner.

---

### Task 10: Load, Failure, Browser, and Full Regression Verification

**Files:**
- Create: `scripts/realtime_load_verify.mjs`
- Modify: `scripts/web_verify.mjs`
- Modify: `scripts/ui_verify.mjs`
- Modify: `README.md`
- Modify: `docs/XUANJI_HANDOFF.md`
- Update: the current project workflow visualization source if it is generated from repository documentation; do not edit the frozen standalone snapshot as runtime authority.

**Interfaces:**
- `realtime_load_verify.mjs --clients 10 --seconds 120` reports upstream calls, event count, median/p95 freshness, API median/p95, RSS delta, reconnects, and invariant hashes.

- [ ] **Step 1: Write load verifier assertions before production tuning**

```js
assert(report.hot_quote_freshness_p95_ms <= 2000);
assert(report.top100_freshness_p95_ms <= 12000);
assert(report.cockpit_valuation_freshness_p95_ms <= 3000);
assert(report.workbench_latency_p95_ms < 300);
assert(report.upstream_call_multiplier <= 1.1);
assert.equal(report.execution_invariants_changed, false);
```

- [ ] **Step 2: Run load verifier and retain the first failing metrics**

Run: `node scripts/realtime_load_verify.mjs --clients 10 --seconds 120`

Use the failures to tune only bounded batch size, cadence, and cache placement; do not relax acceptance thresholds.

- [ ] **Step 3: Run source-failure scenarios**

Simulate timeout, partial symbols, wrong date, stale quote, SSE disconnect, slow client, API restart, and concurrent F5 execution. Verify explicit stale state and unchanged trade facts.

- [ ] **Step 4: Run complete automated regression**

Run:

```powershell
python -m pytest -q
npm run test:contracts
npx tsc --noEmit
npm run build
python scripts\test_api.py
python scripts\full_validation.py
node scripts\web_verify.mjs
node scripts\ui_verify.mjs
```

Expected: zero failures; skips must be explained by existing platform constraints.

- [ ] **Step 5: Run browser QA**

Target flow: market browse opens -> Top100 receives a newer complete snapshot -> realtime watch prices update -> cockpit equity/risk timestamps advance -> no order/fill count changes.

Verify page identity, nonblank content, no framework overlay, no console warning/error, visible timestamps, stale fallback, reconnect, manual refresh, desktop and one mobile viewport.

- [ ] **Step 6: Update handoff documentation**

Document component ownership, policy matrix, SSE/fallback behavior, F5 live mark schema, fixed no-parameter action, performance evidence, failure states, test totals, and the fact that current data is near-real-time Level-1 rather than licensed tick streaming.

- [ ] **Step 7: Final completion gate**

Re-run `node scripts/realtime_load_verify.mjs --clients 10 --seconds 120` after all regression tests. Completion requires every assertion passing, matching market snapshot ids across quote/account/risk, and `live_execution_authority=false`.

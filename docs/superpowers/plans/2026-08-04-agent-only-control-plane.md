# Agent-Only Control Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the legacy AI control plane completely, make Agent Runtime the only automated paper-trading controller, and fail closed on stale evidence or runtime failure.

**Architecture:** The scheduler creates only Agent Runs. Verified Agent publications are the only automated decisions accepted by the paper trader, while deterministic risk, execution sessions, fencing and the ledger remain independent. Runtime failure transitions to maintenance/no-new-position instead of another controller, and macro freshness is evaluated independently from heavy market-data work.

**Tech Stack:** Python 3.14, SQLite, Node.js ESM, React/TypeScript, pytest, Node contract tests, Vite.

---

### Task 1: Agent-Only Architecture Contracts

**Files:**
- Create: `tests/test_agent_only_architecture.py`
- Create: `scripts/agent_only_contract_tests.mjs`
- Modify: `package.json`

- [ ] **Step 1: Write failing source-boundary tests**

The Python test scans active Python modules and asserts that `scripts/ai_loop.py`, `_run_legacy_cycle`, `run_legacy_ai_loop_paper`, the legacy rollback confirmation and multi-owner policy are absent. The Node contract scans active server, component and library sources for the same retired control surface while excluding immutable logs and database rows.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python -m pytest tests\test_agent_only_architecture.py -q
node scripts\agent_only_contract_tests.mjs
```

Expected: both fail against the existing dual-controller architecture.

- [ ] **Step 3: Register the Node contract in the normal contract suite**

Add the new script alongside the existing contract commands so later verification cannot omit it.

### Task 2: Agent-Only Policy and Authority

**Files:**
- Modify: `quant/agent/policies.py`
- Modify: `quant/agent/control.py`
- Modify: `tests/test_agent_policies.py`
- Modify: `tests/test_agent_control.py`
- Modify: `tests/test_agent_execution_sessions.py`

- [ ] **Step 1: Write failing policy tests**

Required behavior:

```python
policy = resolve_runtime_policy({
    "agent_runtime_enabled": True,
    "agent_runtime_mode": "paper_guarded",
})
assert policy["execution_owner"] == "agent_runtime"
```

Also assert that non-Agent grants/sessions are rejected and rollback changes the runtime to maintenance/shadow without transferring ownership.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
python -m pytest tests\test_agent_policies.py tests\test_agent_control.py tests\test_agent_execution_sessions.py -q
```

- [ ] **Step 3: Remove multi-owner policy**

Make Agent Runtime the single automated actor. Remove old owner defaults, handoff targets, session sources and rollback confirmation. Keep epoch, fencing, lease, session binding, order claims and fail-closed validation.

- [ ] **Step 4: Add transactional schema migration**

Rebuild the mutable authority/session schema so new rows accept only `agent_runtime` for automated execution. Invalidate active sessions and increment fencing state during migration. Do not rewrite historical trade/order/risk facts.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run the command from Step 2 and require zero failures.

### Task 3: Agent-Only Scheduler and Runtime Watchdog

**Files:**
- Modify: `scripts/ai_scheduler.py`
- Modify: `scripts/agent_runner.py`
- Modify: `scripts/ai_trading_cycle.py`
- Delete: `scripts/ai_loop.py`
- Modify: `tests/test_agent_scheduler_cutover.py`
- Modify: `tests/test_agent_runtime.py`
- Modify: `tests/test_ai_trading_cycle_stop_authority.py`

- [ ] **Step 1: Write failing scheduler tests**

Assert that every scheduler mode routes to `_run_agent_cycle`, there is no old/double-run branch, and three consecutive failures or an expired cycle deadline produces a maintenance/fail-closed result without invoking another controller.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
python -m pytest tests\test_agent_scheduler_cutover.py tests\test_agent_runtime.py tests\test_ai_trading_cycle_stop_authority.py -q
```

- [ ] **Step 3: Migrate reusable analysis dependencies**

Move any still-used decision assembly or status helper into focused Agent modules. No active module may import the deleted loop.

- [ ] **Step 4: Delete the old loop and scheduler branches**

Remove the file, old scheduler entry, shadow comparison against the old loop, automatic fallback and old status keys. Shadow mode remains an Agent-only non-executing mode.

- [ ] **Step 5: Add watchdog semantics**

Persist cycle start, heartbeat and deadline. A live PID with an expired deadline is unhealthy. Stop new execution Runs, invalidate stale execution eligibility and expose maintenance status.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run the command from Step 2 and require zero failures.

### Task 4: Agent-Only Decision and Paper Execution Chain

**Files:**
- Modify: `scripts/ai_action_executor.py`
- Modify: `scripts/paper/decision_reader.py`
- Modify: `scripts/paper_trader.py`
- Modify: `scripts/paper_runner.py`
- Modify: `tests/test_agent_paper_closed_loop.py`
- Modify: `tests/test_agent_paper_trust_chain.py`
- Modify: `tests/test_decision_reader_binding.py`
- Modify: `tests/test_ai_action_executor_registry.py`

- [ ] **Step 1: Write failing execution-boundary tests**

Assert that the paper trader only accepts a verified Agent publication bound to the same Run, decision, session, epoch and fencing token. Public calls attempting the removed source must be rejected before orders or ledger writes.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
python -m pytest tests\test_agent_paper_closed_loop.py tests\test_agent_paper_trust_chain.py tests\test_decision_reader_binding.py tests\test_ai_action_executor_registry.py -q
```

- [ ] **Step 3: Remove old authorization and execution entry points**

Delete the old authority bundle, recovery state, paper entry and context variable. Make decision reader Agent-only and keep observation-safe no-new-position behavior for invalid evidence.

- [ ] **Step 4: Simplify paper trader source handling**

Automated execution must use `agent_runtime`; manual emergency operations remain separate and cannot mint automated Agent authority.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run the command from Step 2 and require zero failures.

### Task 5: Macro Freshness and Composite Risk Correctness

**Files:**
- Modify: `scripts/global_context.py`
- Modify: `server/routes/workbench.mjs`
- Modify: `scripts/global_context_source_contract_tests.py`
- Modify: `scripts/investor_workbench_upgrade_contract_tests.mjs`
- Add or modify: `tests/test_global_context_freshness.py`

- [ ] **Step 1: Write failing freshness tests**

Assert that a macro snapshot beyond TTL becomes `unknown/stale`, preserves its raw historical signal for display only, blocks new positions with `macro_context_stale`, and never reports the historical signal as current high risk.

- [ ] **Step 2: Run tests and verify RED**

```powershell
python -m pytest tests\test_global_context_freshness.py scripts\global_context_source_contract_tests.py -q
node scripts\investor_workbench_upgrade_contract_tests.mjs
```

- [ ] **Step 3: Implement timestamped macro freshness**

Emit collected/source timestamps, TTL, stale/error and confidence. Do not allow cached success to remain timeless.

- [ ] **Step 4: Fix workbench composite state**

Freshness must include macro, scheduler and Agent decision ages. `stale` is distinct from `high`; both can block new positions with different Chinese reasons.

- [ ] **Step 5: Run tests and verify GREEN**

Run the command from Step 2 and require zero failures.

### Task 6: API, UI, Documentation and Build Artifacts

**Files:**
- Modify: `server/routes/paper.mjs`
- Modify: `server/router.mjs`
- Modify: `components/AgentRuntimeStatus.tsx`
- Modify: `components/PaperPanel.tsx`
- Modify: `lib/workbench-state.mjs`
- Modify: `README.md`
- Modify: `docs/XUANJI_HANDOFF.md`
- Delete or rewrite: superseded Agent dual-controller specs/plans under `docs/superpowers`
- Regenerate: `dist/`

- [ ] **Step 1: Write failing API/UI contracts**

Assert that status exposes Agent control or maintenance only, no rollback-to-old action exists, and Chinese UI distinguishes macro high from macro data expiry.

- [ ] **Step 2: Run Node/UI contracts and verify RED**

```powershell
node scripts\agent_runtime_api_contract_tests.mjs
node scripts\agent_runtime_frontend_contract_tests.mjs
node scripts\system_chinese_display_contract_tests.mjs
node scripts\agent_only_contract_tests.mjs
```

- [ ] **Step 3: Remove old control surface and update Chinese display**

Delete old API actions, buttons, labels and fallback instructions. Update README and handoff relationships to the Agent-only call chain and maintenance recovery process.

- [ ] **Step 4: Rebuild and verify GREEN**

```powershell
npx tsc --noEmit
npm run build
node scripts\agent_only_contract_tests.mjs
```

### Task 7: Runtime Migration, Restart and Acceptance

**Files:**
- Modify only as required by failures found in Tasks 1-6.
- Runtime state: active XuanJiQuant database/cache and service processes.

- [ ] **Step 1: Run full pre-migration code verification**

```powershell
python -m pytest tests -q
npm run test:contracts
npx tsc --noEmit
npm run build
python scripts\smoke_test.py
```

- [ ] **Step 2: Stop scheduler and simulated execution safely**

Verify exact XuanJiQuant PIDs, stop only the affected scheduler/paper processes, and confirm no active execution session or unfinished order is being mutated.

- [ ] **Step 3: Apply Agent-only authority migration**

Run the tested migration path, set the active policy to enabled `paper_guarded`, invalidate old sessions, and verify the current authority actor is Agent Runtime.

- [ ] **Step 4: Start services and verify live behavior**

Confirm Web 8888 and API 8880, Agent heartbeat, scheduler cycle completion, macro freshness, composite-risk provenance and paper-only execution fencing.

- [ ] **Step 5: Run final acceptance again**

Repeat the full commands from Step 1 after restart. Perform actual HTTP requests to Web and API and source scans over active code plus rebuilt `dist`.

- [ ] **Step 6: Update acceptance evidence**

Record exact results and final Agent-only file relationships in README and `docs/XUANJI_HANDOFF.md`. The workspace has no Git metadata, so report changed files and verification evidence directly instead of claiming commits.


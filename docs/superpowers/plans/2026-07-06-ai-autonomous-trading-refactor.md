# AI Autonomous Trading Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the AI system into an intraday autonomous paper-trading cycle and a post-close research/inspection cycle while keeping live trading read-only/manual.

**Architecture:** `ai_scheduler.py` becomes a time router. `ai_trading_cycle.py` owns market-session decision, verifier, risk-gated paper execution, and stop checks. `ai_research_cycle.py` owns post-close data refresh, factor rebuild, strategy review, memory, and reports without submitting new orders.

**Tech Stack:** Python scheduler/agents, SQLite-backed cache/audit tables, Node contract tests, existing paper trader and risk gateway.

---

### Task 1: Scheduler Mode Contract

**Files:**
- Modify: `scripts/ai_scheduler.py`
- Create: `scripts/ai_autonomous_cycle_contract_tests.mjs`

- [x] **Step 1: Write failing contract tests**

```javascript
const scheduler = fs.readFileSync('scripts/ai_scheduler.py', 'utf-8');
assert(scheduler.includes('from scripts.ai_trading_cycle import run_trading_cycle'));
assert(scheduler.includes('from scripts.ai_research_cycle import run_research_cycle'));
assert(!scheduler.includes('run_loop(provider, trigger_paper=True, source="scheduler")'));
```

- [ ] **Step 2: Implement scheduler as a router**

Use `run_trading_cycle(provider, cfg, source="scheduler_intraday")` during market sessions and `run_research_cycle(provider, cfg)` after close.

- [ ] **Step 3: Run contract tests**

Run: `node scripts\ai_autonomous_cycle_contract_tests.mjs`
Expected: PASS.

### Task 2: Trading Cycle

**Files:**
- Create: `scripts/ai_trading_cycle.py`
- Modify: `scripts/ai_scheduler.py`

- [ ] **Step 1: Implement intraday cycle**

Run stops/risk/data checks, enforce cooldown and daily cycle count, then call `run_loop(provider, trigger_paper=True, source=source)` only when trading is allowed.

- [ ] **Step 2: Verify py_compile**

Run: `python -m py_compile scripts\ai_trading_cycle.py scripts\ai_scheduler.py`
Expected: exit code 0.

### Task 3: Research Cycle

**Files:**
- Create: `scripts/ai_research_cycle.py`
- Modify: `scripts/ai_scheduler.py`

- [ ] **Step 1: Implement post-close cycle**

Refresh data, rebuild factor snapshot once per day, run `run_loop(provider, trigger_paper=False, source="scheduler_research")`, and write audit events.

- [ ] **Step 2: Verify no post-close order trigger**

Run: `node scripts\ai_autonomous_cycle_contract_tests.mjs`
Expected: PASS.

### Task 4: Audit and Source Fidelity

**Files:**
- Modify: `quant/data/audit.py`
- Modify: `scripts/ai_action_executor.py`

- [ ] **Step 1: Preserve execution source**

Map `scheduler_intraday` through to `paper_trader.py --source scheduler_intraday` so logs can replay who triggered the order.

- [ ] **Step 2: Deduplicate decision audit stages**

Add `stage` to `ai_decisions`, and make `write_ai_decision()` replace the same `decision_id + stage` instead of appending duplicates forever.

- [ ] **Step 3: Run contract tests**

Run: `node scripts\ai_autonomous_cycle_contract_tests.mjs`
Expected: PASS.

### Task 5: Full Verification

**Files:**
- Test: existing test scripts

- [ ] **Step 1: Compile Python**

Run: `python -m py_compile scripts\ai_scheduler.py scripts\ai_trading_cycle.py scripts\ai_research_cycle.py scripts\ai_loop.py scripts\ai_action_executor.py scripts\paper_trader.py quant\risk\gateway.py quant\data\audit.py`

- [ ] **Step 2: Run regression tests**

Run contract, scheduler, security, log, LLM, objective, and web verification scripts.

- [ ] **Step 3: Report actual evidence**

Only report completion with fresh command output and any remaining gaps.

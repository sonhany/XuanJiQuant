# Configuration Closed Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every editable setting round-trip reliably and make the 20% single-stock cap identical in the UI, Agent plan, scheduler, risk metrics, and execution gateway.

**Architecture:** Keep the current cache keys and process layout. Centralize restrictive risk composition in `quant/risk/config.py`, synchronize autonomous business settings without changing scheduler lifecycle state, make the portfolio planner consume the authoritative resolver, and make React apply the server save acknowledgement.

**Tech Stack:** Python 3.14, pytest, React 19, TypeScript, Node contract tests, Vite, SQLite-backed cache, local Web/API smoke tests.

---

### Task 1: Lock the risk-composition regression

**Files:**
- Modify: `tests/test_risk_config.py`
- Test: `tests/test_risk_config.py`

- [ ] **Step 1: Write failing tests**

Add tests proving a stricter autonomous cap survives a looser paper snapshot, restrictive flags compose safely, and explicit execution config cannot relax the cap:

```python
def test_downstream_risk_snapshots_can_tighten_but_never_relax_global_limits():
    cache = FakeCache({
        "ai:autonomous:config": {"risk": {"max_position_pct": 0.10}},
        "paper:config": {"risk": {"max_position_pct": 0.20}},
    })
    assert load_risk_config(cache)["max_position_pct"] == 0.10
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_risk_config.py -q`

Expected: the new restrictive-composition assertion fails with `0.2 != 0.1`.

- [ ] **Step 3: Implement restrictive composition**

In `quant/risk/config.py`, add a field-aware merge used by `load_risk_config()`:

```python
def merge_restrictive_risk(base: dict, overlay: dict | None) -> dict:
    out = normalize_risk_config({"risk": base or {}})
    raw = overlay.get("risk") if isinstance(overlay, dict) and isinstance(overlay.get("risk"), dict) else {}
    candidate = normalize_risk_config({"risk": raw})
    for key in _MAX_LIMIT_KEYS:
        if key in raw:
            out[key] = min(out[key], candidate[key])
    for key in _MIN_LIMIT_KEYS:
        if key in raw:
            out[key] = max(out[key], candidate[key])
    if "capital_cap" in raw and candidate["capital_cap"] > 0:
        out["capital_cap"] = candidate["capital_cap"] if out["capital_cap"] <= 0 else min(out["capital_cap"], candidate["capital_cap"])
    if "kill_switch" in raw:
        out["kill_switch"] = out["kill_switch"] or candidate["kill_switch"]
    for key in _ALLOW_FLAG_KEYS:
        if key in raw:
            out[key] = out[key] and candidate[key]
    return out
```

Use ordinary override only for the global autonomous selection, then apply downstream paper/explicit config restrictively, followed by `apply_hard_limits()`.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/test_risk_config.py -q`

Expected: all tests pass.

### Task 2: Make autonomous save canonical and lifecycle-safe

**Files:**
- Modify: `scripts/ai_objective.py`
- Modify: `tests/test_llm_provider_switching.py`
- Test: `tests/test_llm_provider_switching.py`

- [ ] **Step 1: Write failing tests**

Add tests proving risk/target/execution fields synchronize to `ai:scheduler:config`, `enabled` remains the scheduler-owned current value, runtime-policy fields cannot be overwritten, and returned risk values are normalized.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_llm_provider_switching.py -q`

Expected: full configuration synchronization and lifecycle-preservation assertions fail.

- [ ] **Step 3: Implement minimal save normalization and synchronization**

Update `save_autonomous_config()` to normalize known scalar/risk/execution fields, persist the canonical autonomous config, deep-merge all business fields into the scheduler snapshot, then restore scheduler-owned `enabled` and `autonomous_enabled` values.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/test_llm_provider_switching.py -q`

Expected: all tests pass.

### Task 3: Bind Agent planning to authoritative risk

**Files:**
- Modify: `scripts/ai_portfolio_planner.py`
- Create: `tests/test_portfolio_planner_risk_binding.py`
- Test: `tests/test_portfolio_planner_risk_binding.py`

- [ ] **Step 1: Write failing tests**

Use an in-memory cache where autonomous risk is `0.8`, paper risk is `0.2`, and file hard cap is `0.2`; assert `_planner_risk_budget(config, cache_obj)["max_position_pct"] == 0.2` and `normalize_portfolio_plan()` clips a model-proposed `0.25` target to `0.20`.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_portfolio_planner_risk_binding.py -q`

Expected: planner returns `0.8` before the fix.

- [ ] **Step 3: Use `load_risk_config()` in the planner**

Make `_planner_risk_budget()` resolve risk through the shared loader while continuing to read `max_rebalance_orders` from execution config. Pass the planner module cache explicitly so tests do not touch the live database.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/test_portfolio_planner_risk_binding.py -q`

Expected: both binding and clipping tests pass.

### Task 4: Apply the server acknowledgement in React

**Files:**
- Modify: `components/DashboardPanel.tsx`
- Modify: `components/AutonomousSchedulingDrawer.tsx`
- Modify: `scripts/professional_cockpit_contract_tests.mjs`
- Test: `scripts/professional_cockpit_contract_tests.mjs`

- [ ] **Step 1: Write failing source contract**

Require a dedicated save handler to consume `paperAction()` output, set the returned canonical config, and show a Chinese success message containing the effective single-stock cap. Require opening the drawer to refresh from current server state.

- [ ] **Step 2: Verify RED**

Run: `node scripts/professional_cockpit_contract_tests.mjs`

Expected: acknowledgement-application assertions fail.

- [ ] **Step 3: Implement the save acknowledgement**

Add `saveAutonomousConfig()` in `DashboardPanel.tsx`; use the API response to call `setConfig(result.config)`, refresh status, and keep failed saves visibly failed. Add configured/effective risk text to the drawer without changing its layout hierarchy.

- [ ] **Step 4: Verify GREEN**

Run: `node scripts/professional_cockpit_contract_tests.mjs`

Expected: contract passes.

### Task 5: Audit all editable settings and control actions

**Files:**
- Create: `scripts/configuration_closed_loop_contract_tests.mjs`
- Modify: `tests/test_llm_provider_switching.py`
- Modify: `tests/test_risk_config.py`

- [ ] **Step 1: Add the cross-surface inventory contract**

Enumerate the autonomous fields, paper strategy fields, runtime actions, sync controls, and Tick collector controls. Assert each visible save/control maps to an allowed API action and each persisted business config has a runtime consumer.

- [ ] **Step 2: Run the inventory contract**

Run: `node scripts/configuration_closed_loop_contract_tests.mjs`

Expected: pass only when no UI control is orphaned.

- [ ] **Step 3: Run focused Python integration tests**

Run: `python -m pytest tests/test_risk_config.py tests/test_llm_provider_switching.py tests/test_portfolio_planner_risk_binding.py tests/test_risk_gateway.py tests/test_execution_reliability.py -q`

Expected: all pass.

### Task 6: Live 20% round-trip and rendered UI verification

**Files:**
- No production file changes expected.
- Temporary screenshots/scripts must remain outside the repository.

- [ ] **Step 1: Save 20% through the real API while the scheduler is stopped**

POST `/api/paper` with `action=ai_autonomous_set_config` and `risk.max_position_pct=0.2`. Read back autonomous, scheduler, paper, effective risk, and assert every runtime consumer resolves `0.2`.

- [ ] **Step 2: Exercise pure gateway boundaries**

Run an in-memory `check_order()` case that keeps projected weight below 20% and one above 20%; expect allow then rejection reason `max_position_pct`. Do not place an order.

- [ ] **Step 3: Verify the browser flow**

Flow: `http://127.0.0.1:8888` → open 调度设置 → enter 20 → 保存配置 → observe saved/effective 20% after refresh, with no console error and no scheduler start.

- [ ] **Step 4: Restore the scheduler**

Start the Agent scheduler in its prior `paper_guarded` mode only after configuration and tests are green; confirm one status cycle sees `risk_budget.max_position_pct=0.2` before permitting normal operation.

### Task 7: Full regression, performance, and handoff documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/XUANJI_HANDOFF.md`

- [ ] **Step 1: Document ownership and precedence**

Record the canonical config keys, restrictive merge rules, scheduler lifecycle boundary, Agent/gateway consumers, UI save acknowledgement, and diagnostic commands.

- [ ] **Step 2: Run full verification**

Run the repository's complete Python suite, every Node contract group in `package.json`/`scripts`, `npx tsc --noEmit`, `npm run build`, `node scripts/web_verify.mjs`, and the UI verification script. Record exact fresh counts.

- [ ] **Step 3: Sample performance and logs**

Sample `/api/workbench` repeatedly, inspect recent server/scheduler errors, confirm Web/API success, and verify no obsolete project process was touched.

- [ ] **Step 4: Self-review the requirement checklist**

Confirm the 20% value is identical across persistence, planning, metrics, gateway, and UI; confirm all inventoried settings have round-trip tests; report any remaining external-data or browser limitation explicitly.

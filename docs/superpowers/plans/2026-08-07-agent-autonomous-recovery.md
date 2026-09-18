# Agent Autonomous Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Agent Runtime autonomously refresh stale evidence, reconcile failures, recover through two non-executing validation cycles, and resume guarded paper trading without routine manual controls.

**Architecture:** Add a focused recovery service that persists lifecycle state independently from execution authority. The scheduler continues to run Agent-only, uses internal shadow runs while recovering, refreshes evidence before decisions, and promotes to `paper_guarded` only after two fresh deterministic passes. Public APIs become read-only except emergency stop, order cancellation, forced reduction, and emergency release into recovery.

**Tech Stack:** Python 3.14, SQLite cache/database, Node.js ESM, React/TypeScript, pytest, Node contract tests, Vite.

---

## File responsibilities

- `quant/agent/autonomous_recovery.py`: lifecycle snapshot, blockers, retry timing, success streak, atomic transitions and audit facts.
- `quant/agent/control.py`: Agent-only control facade; execution failure enters recovery and public status exposes autonomous lifecycle.
- `scripts/ai_scheduler.py`: schedules recovery runs, refreshes evidence, records recovery outcomes and never requests execution outside `paper_guarded`.
- `scripts/ai_stock_screener.py`: remains the single stock-screen freshness and refresh implementation.
- `server/routes/paper.mjs`: removes routine manual recovery/selection actions and exposes emergency-only controls.
- `components/AgentRuntimeStatus.tsx`: shows autonomous state and emergency controls without start/enable buttons.
- `components/PaperPanel.tsx`: removes manual screen/run controls and displays recovery evidence.
- `tests/test_agent_autonomous_recovery.py`: deterministic recovery state-machine tests.
- `tests/test_agent_only_architecture.py`: scheduler/evidence integration tests.
- `scripts/agent_control_contract_tests.mjs`: API and source-boundary contracts for the reduced control surface.

### Task 1: Persistent autonomous recovery state machine

**Files:**
- Create: `quant/agent/autonomous_recovery.py`
- Create: `tests/test_agent_autonomous_recovery.py`
- Modify: `quant/agent/control.py`
- Modify: `tests/test_agent_control.py`

- [ ] **Step 1: Write failing lifecycle tests**

Add tests that express the desired API before implementation:

```python
from quant.agent.autonomous_recovery import AgentRecoveryService


def test_two_distinct_successful_recovery_cycles_resume_paper(tmp_path):
    cache, control = _service(tmp_path)
    recovery = AgentRecoveryService(cache, control_factory=lambda _cache: control)
    recovery.enter_recovering(reason="tool_outcome_unknown")

    first = recovery.record_cycle(
        trigger_id="20260807:postclose:1",
        checks=_passing_checks(),
    )
    second = recovery.record_cycle(
        trigger_id="20260807:postclose:2",
        checks=_passing_checks(),
    )

    assert first["state"] == "recovering"
    assert first["success_streak"] == 1
    assert second["state"] == "paper_guarded"
    assert second["success_streak"] == 2
    assert control.status()["stage"] == "agent_controlled"


def test_duplicate_trigger_cannot_advance_recovery(tmp_path):
    cache, control = _service(tmp_path)
    recovery = AgentRecoveryService(cache, control_factory=lambda _cache: control)
    recovery.enter_recovering(reason="screen_market_data_stale")
    recovery.record_cycle(trigger_id="same", checks=_passing_checks())
    repeated = recovery.record_cycle(trigger_id="same", checks=_passing_checks())
    assert repeated["success_streak"] == 1


def test_hard_blocker_enters_maintenance_without_execution(tmp_path):
    cache, control = _service(tmp_path)
    recovery = AgentRecoveryService(cache, control_factory=lambda _cache: control)
    state = recovery.record_cycle(
        trigger_id="hard",
        checks={**_passing_checks(), "unknown_side_effects": 1},
    )
    assert state["state"] == "maintenance"
    assert state["blocker_code"] == "tool_outcome_unknown"
    assert control.status()["policy"]["agent_runtime_mode"] != "paper_guarded"
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m pytest tests\test_agent_autonomous_recovery.py tests\test_agent_control.py -q
```

Expected: collection fails because `quant.agent.autonomous_recovery` does not exist.

- [ ] **Step 3: Implement the minimal recovery service**

Create a service with these stable public methods and keys. The production implementation may extract the repeated transition body into a private helper, but it must preserve this behavior:

```python
from datetime import datetime, timedelta, timezone


RECOVERY_STATE_KEY = "agent:recovery:state"
RECOVERY_AUDIT_KEY = "agent:recovery:audit"
PASS_REQUIRED = 2
REQUIRED_TRUE = (
    "database_ready", "market_data_fresh", "screen_fresh", "macro_fresh",
    "verifier_passed", "authority_consistent", "hard_risk_clear",
    "emergency_stop_clear",
)


def _now():
    return datetime.now(timezone.utc)


def _initial_state():
    stamp = _now().isoformat()
    return {
        "schema_version": "agent_recovery.v1",
        "state": "recovering",
        "blocker_code": "runtime_recovery_required",
        "blocker_detail": "",
        "success_streak": 0,
        "attempt_count": 0,
        "last_trigger_id": "",
        "last_attempt_at": None,
        "next_retry_at": stamp,
        "updated_at": stamp,
        "checks": {},
    }


class AgentRecoveryService:
    def __init__(self, cache, *, control_factory):
        self.cache = cache
        self.control_factory = control_factory

    def status(self) -> dict:
        raw = self.cache.get(RECOVERY_STATE_KEY)
        return dict(raw) if type(raw) is dict else _initial_state()

    def _write(self, *, state: str, reason: str, reset_streak: bool = True) -> dict:
        now = _now()
        current = self.status()
        current.update({
            "state": state,
            "blocker_code": reason,
            "blocker_detail": "",
            "success_streak": 0 if reset_streak else current["success_streak"],
            "next_retry_at": (now + timedelta(minutes=1)).isoformat(),
            "updated_at": now.isoformat(),
        })
        self.cache.set(RECOVERY_STATE_KEY, current)
        return current

    def enter_recovering(self, *, reason: str) -> dict:
        self.control_factory(self.cache).enter_recovering_internal(reason=reason)
        return self._write(state="recovering", reason=reason)

    def enter_maintenance(self, *, reason: str) -> dict:
        self.control_factory(self.cache).enter_maintenance(reason=reason)
        return self._write(state="maintenance", reason=reason)

    def emergency_stop(self, *, reason: str) -> dict:
        self.control_factory(self.cache).enter_emergency_stop(reason=reason)
        return self._write(state="emergency_stop", reason="operator_emergency_stop")

    def release_emergency(self) -> dict:
        current = self.status()
        if current["state"] != "emergency_stop":
            return current
        return self.enter_recovering(reason="emergency_stop_released")

    def record_cycle(self, *, trigger_id: str, checks: dict) -> dict:
        current = self.status()
        if trigger_id == current["last_trigger_id"]:
            return current
        hard_code = ""
        if int(checks.get("unknown_side_effects", 0)) > 0:
            hard_code = "tool_outcome_unknown"
        elif int(checks.get("unfinished_orders", 0)) > 0:
            hard_code = "unfinished_orders"
        if hard_code:
            return self.enter_maintenance(reason=hard_code)
        passed = (
            int(checks.get("active_runs", 0)) == 0
            and int(checks.get("active_sessions", 0)) == 0
            and all(checks.get(name) is True for name in REQUIRED_TRUE)
        )
        now = _now()
        streak = current["success_streak"] + 1 if passed else 0
        blocker = "" if passed else next(
            (name for name in REQUIRED_TRUE if checks.get(name) is not True),
            "recovery_checks_failed",
        )
        updated = {
            **current,
            "state": "recovering",
            "blocker_code": blocker,
            "success_streak": streak,
            "attempt_count": current["attempt_count"] + 1,
            "last_trigger_id": trigger_id,
            "last_attempt_at": now.isoformat(),
            "next_retry_at": (now + timedelta(minutes=1)).isoformat(),
            "updated_at": now.isoformat(),
            "checks": dict(checks),
        }
        self.cache.set(RECOVERY_STATE_KEY, updated)
        if streak >= PASS_REQUIRED:
            control = self.control_factory(self.cache)
            status = control.status()
            control.enable_paper_guarded_autonomously(
                expected_policy_hash=status["policy"]["policy_hash"]
            )
            updated = {**updated, "state": "paper_guarded", "blocker_code": ""}
            self.cache.set(RECOVERY_STATE_KEY, updated)
        return updated
```

Persist exact fields `schema_version`, `state`, `blocker_code`, `blocker_detail`, `success_streak`, `attempt_count`, `last_trigger_id`, `last_attempt_at`, `next_retry_at`, `updated_at` and `checks`. Use `cache.atomic_update` for transition plus bounded audit append. Promotion must call an internal `AgentControlService.enable_paper_guarded_autonomously(expected_policy_hash=...)`; no confirmation string or public API is involved.

- [ ] **Step 4: Replace failure-to-maintenance with failure-to-recovery**

Change `record_agent_execution_outcome` so three consecutive non-completed execution cycles call `enter_recovering(reason="consecutive_agent_execution_failures")`. Keep hard reconciliation ambiguity in maintenance and keep the current owner fixed to `agent_runtime`.

- [ ] **Step 5: Run focused tests and verify GREEN**

```powershell
python -m pytest tests\test_agent_autonomous_recovery.py tests\test_agent_control.py tests\test_agent_runtime_quality.py -q
```

Expected: zero failures.

### Task 2: Evidence refresh during recovery

**Files:**
- Modify: `scripts/ai_scheduler.py`
- Modify: `tests/test_agent_only_architecture.py`
- Modify: `tests/test_ai_stock_screener.py`

- [ ] **Step 1: Write failing scheduler tests**

Add tests proving an internal recovery run refreshes evidence without execution:

```python
def test_recovering_scheduler_refreshes_screen_and_runs_non_executing_agent(monkeypatch):
    events = []
    _install_fresh_context(monkeypatch, events)
    _install_fresh_screen(monkeypatch, events)
    _install_agent_result(monkeypatch, events, mode="shadow")
    cycle = ai_scheduler._run_agent_cycle(
        "glm", "glm-5.2", "postclose",
        _policy(enabled=True, mode="shadow"),
        recovery_state="recovering",
    )
    assert events == ["context", "screen", "agent"]
    assert cycle["execution_requested"] is False
    assert cycle["steps"]["selection_screen"]["fresh"] is True


def test_failed_recovery_screen_never_reuses_old_candidates(monkeypatch):
    _install_failed_screen(monkeypatch, reason="screen_market_data_stale")
    cycle = _run_recovery_cycle(monkeypatch)
    assert cycle["status"] == "blocked"
    assert cycle["block_reason"] == "selection_screen_refresh_failed"
    assert cycle["steps"]["selection_screen"]["candidate_count"] == 0
```

- [ ] **Step 2: Run tests and verify RED**

```powershell
python -m pytest tests\test_agent_only_architecture.py tests\test_ai_stock_screener.py -q
```

Expected: recovery state is not accepted and the screen refresh is skipped outside executable intraday mode.

- [ ] **Step 3: Separate evidence preparation from execution request**

In `_run_agent_cycle`, compute:

```python
request_execution, reason = _agent_execution_request(scheduler_mode, policy)
prepare_selection = request_execution or recovery_state in {"recovering", "maintenance"}
```

When `prepare_selection` is true, call `ensure_screen_fresh(provider=provider)` before `agent_runner.run_once`. A failed refresh blocks that recovery attempt but does not terminate the scheduler or publish stale candidates. Run the Agent internally with `mode="shadow"` and `request_execution=False` during recovery.

- [ ] **Step 4: Record deterministic recovery checks**

After the Agent cycle, pass these concrete checks to `AgentRecoveryService.record_cycle`: `database_ready`, `active_runs`, `active_sessions`, `unknown_side_effects`, `unfinished_orders`, `market_data_fresh`, `screen_fresh`, `macro_fresh`, `verifier_passed`, `authority_consistent`, `hard_risk_clear`, and `emergency_stop_clear`.

- [ ] **Step 5: Run focused tests and verify GREEN**

```powershell
python -m pytest tests\test_agent_only_architecture.py tests\test_ai_stock_screener.py tests\test_agent_autonomous_recovery.py -q
```

Expected: zero failures.

### Task 3: Scheduler-owned autonomous lifecycle

**Files:**
- Modify: `scripts/ai_scheduler.py`
- Modify: `quant/agent/control.py`
- Modify: `scripts/agent_control.py`
- Modify: `tests/test_agent_control.py`
- Modify: `tests/test_agent_only_architecture.py`

- [ ] **Step 1: Write failing lifecycle integration tests**

Assert that a disabled historical `maintenance/observe` configuration is migrated to recovery, emergency stop is never auto-released, and no recovery cycle requests an execution session.

```python
def test_historical_maintenance_is_migrated_to_recovering(monkeypatch):
    state = ai_scheduler._normalize_agent_lifecycle(
        {"agent_runtime_enabled": False, "agent_runtime_mode": "observe"},
        recovery={"state": "maintenance", "blocker_code": "consecutive_agent_execution_failures"},
    )
    assert state["state"] == "recovering"
    assert state["runtime_mode"] == "shadow"
    assert state["request_execution"] is False


def test_emergency_stop_never_auto_migrates():
    state = ai_scheduler._normalize_agent_lifecycle(
        {"agent_runtime_enabled": False, "agent_runtime_mode": "observe"},
        recovery={"state": "emergency_stop", "blocker_code": "operator_emergency_stop"},
    )
    assert state["state"] == "emergency_stop"
```

- [ ] **Step 2: Run tests and verify RED**

```powershell
python -m pytest tests\test_agent_control.py tests\test_agent_only_architecture.py -q
```

- [ ] **Step 3: Implement scheduler lifecycle normalization**

At cycle start, load recovery status. Convert the existing non-emergency disabled state to `recovering`, save internal Agent config as enabled `shadow`, and run the normal Agent path. Preserve `emergency_stop` as disabled. Replace the unconditional `agent_runtime_maintenance` branch with recovery or emergency behavior.

- [ ] **Step 4: Restrict the CLI control surface**

Replace public lifecycle actions with `status`, `emergency_stop`, and `release_emergency`. The release action always returns to `recovering`, never directly to `paper_guarded`.

- [ ] **Step 5: Run focused tests and verify GREEN**

```powershell
python -m pytest tests\test_agent_control.py tests\test_agent_only_architecture.py tests\test_agent_autonomous_recovery.py -q
```

### Task 4: Remove routine manual API and UI controls

**Files:**
- Modify: `server/routes/paper.mjs`
- Modify: `server/router.mjs`
- Modify: `components/AgentRuntimeStatus.tsx`
- Modify: `components/PaperPanel.tsx`
- Modify: `scripts/agent_control_contract_tests.mjs`
- Modify: `scripts/agent_runtime_frontend_contract_tests.mjs`
- Modify: `scripts/paper_execution_state_contract_tests.mjs`
- Modify: `scripts/configuration_closed_loop_contract_tests.mjs`

- [ ] **Step 1: Rewrite contracts first and verify RED**

Require absence of routine actions and presence of emergency-only controls:

```javascript
for (const retired of [
  'agent_control_start_shadow', 'agent_control_enable',
  'ai_screen_run', 'ai_scheduler_run_once',
]) {
  assert(!route.includes(retired), `routine control must be removed: ${retired}`);
  assert(!component.includes(retired), `routine UI must be removed: ${retired}`);
  assert(!panel.includes(retired), `routine panel action must be removed: ${retired}`);
}
assert(route.includes('agent_control_emergency_stop'));
assert(route.includes('agent_control_release_emergency'));
assert(component.includes('自治恢复'));
assert(component.includes('紧急停止'));
```

Run:

```powershell
node scripts\agent_control_contract_tests.mjs
node scripts\agent_runtime_frontend_contract_tests.mjs
node scripts\paper_execution_state_contract_tests.mjs
node scripts\configuration_closed_loop_contract_tests.mjs
```

Expected: failures identify the existing buttons and routes.

- [ ] **Step 2: Remove public routine actions**

Delete the four route branches and router allow-list entries. Internal Python functions remain callable only by the scheduler/Agent and must not be exposed through `/api/paper`.

- [ ] **Step 3: Simplify the interface**

Remove the manual screen button and “运行一次 Agent 任务” from `PaperPanel`. Replace the manual control panel with read-only fields for autonomous state, blocker, success streak, last attempt, next retry, market-data date, screen date and coverage. Keep emergency stop and emergency release buttons with explicit confirmation.

- [ ] **Step 4: Run Node contracts and TypeScript**

```powershell
node scripts\agent_control_contract_tests.mjs
node scripts\agent_runtime_frontend_contract_tests.mjs
node scripts\paper_execution_state_contract_tests.mjs
node scripts\configuration_closed_loop_contract_tests.mjs
npx tsc --noEmit
```

Expected: zero failures and TypeScript exit code 0.

### Task 5: Documentation and architecture boundary

**Files:**
- Modify: `README.md`
- Modify: `docs/XUANJI_HANDOFF.md`
- Modify: `tests/test_agent_only_architecture.py`

- [ ] **Step 1: Add a failing architecture/documentation test**

Assert current docs name `recovering`, two-pass promotion, emergency-only human control, and the evidence chain; assert active routes/components contain none of the retired actions.

- [ ] **Step 2: Run the architecture test and verify RED**

```powershell
python -m pytest tests\test_agent_only_architecture.py -q
```

- [ ] **Step 3: Update README and handoff**

Document the exact chain `sync -> evidence coordinator -> Agent recovery/runtime -> verifier -> risk gateway -> paper session -> ledger`, the retry schedule, the two-pass rule, current runtime keys, public API boundary and emergency-only manual responsibilities.

- [ ] **Step 4: Run architecture tests and verify GREEN**

```powershell
python -m pytest tests\test_agent_only_architecture.py -q
node scripts\agent_only_contract_tests.mjs
```

### Task 6: Runtime migration and acceptance

**Files:**
- Modify only files required by observed failures.
- Runtime state: `data/quant.db` and XuanJiQuant-owned service processes.

- [ ] **Step 1: Run focused regression before runtime mutation**

```powershell
python -m pytest tests\test_agent_autonomous_recovery.py tests\test_agent_control.py tests\test_agent_only_architecture.py tests\test_agent_recovery.py tests\test_agent_runtime.py tests\test_agent_runtime_quality.py tests\test_ai_stock_screener.py -q
npm run test:contracts
npx tsc --noEmit
npm run build
```

- [ ] **Step 2: Verify no active execution work**

Use read-only Agent APIs and SQLite queries to require zero active Run, zero issued/active session, and zero pending/partial order before changing runtime lifecycle state.

- [ ] **Step 3: Reload only XuanJiQuant services that require new code**

Resolve exact PIDs from ports 8880/8888 and scheduler metadata. Restart only those processes; do not access or start the frozen backup.

- [ ] **Step 4: Migrate current lifecycle to recovery**

Record an audit event, set recovery state to `recovering`, and allow the scheduler to perform two non-executing recovery passes. Do not directly write `paper_guarded` and do not trigger a real trade.

- [ ] **Step 5: Verify live evidence**

Require API evidence for current data date, screen freshness, Agent lifecycle, blocker, success streak, scheduler cycle, verifier, execution authority and zero real-trading capability. Confirm stale or failed evidence remains fail-closed.

- [ ] **Step 6: Run full acceptance**

```powershell
python -m pytest tests -q
npm run test:contracts
npx tsc --noEmit
npm run build
python scripts\smoke_test.py
node scripts\web_verify.mjs
node scripts\ui_verify.mjs
```

Also request Web `http://127.0.0.1:8888` and API `http://127.0.0.1:8880`, inspect browser console errors, and report exact counts and response times.

The workspace has no Git metadata, so every task records changed files and test evidence without claiming commits.

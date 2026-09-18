# Trading Agent P1 Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a durable, model-neutral Agent Runtime that can observe, plan, call typed tools, validate, checkpoint, recover, replay, and safely trigger the existing paper trader under a single execution owner.

**Architecture:** Use a dependency-free Python finite-state machine and dedicated SQLite tables. Existing L1-L5 agents, selector, portfolio planner, verifier and paper trader remain business tools; the new runtime coordinates them through typed contracts and initially runs in observe/shadow mode before an audited switch to `paper_guarded`.

**Tech Stack:** Python 3.14 standard library, SQLite, existing cache/audit modules, Node.js API server, React 19, TypeScript, Vite, pytest.

---

## Preconditions

- Complete and verify `docs/superpowers/plans/2026-07-25-trading-agent-p0-reliability.md` first.
- `ai_decision.v2`, evidence verification and fail-closed fallback behavior must already exist.
- Do not initialize Git in this workspace. Use the test and changed-file checkpoints below.
- Do not connect a live broker or register a `live_side_effect` tool.

## File Map

Create:

```text
quant/agent/store.py                 Durable run/event/tool/checkpoint persistence
quant/agent/tool_registry.py         ai_tools.v2 parsing and permission checks
quant/agent/policies.py              Runtime mode and execution-owner rules
quant/agent/context.py               Bounded context snapshots
quant/agent/planner.py               Model-neutral planner adapter
quant/agent/runtime.py               FSM and orchestration
quant/agent/replay.py                Run reconstruction
scripts/agent_runner.py              CLI and API subprocess entry
tests/test_agent_store.py
tests/test_agent_tool_registry.py
tests/test_agent_policies.py
tests/test_agent_runtime.py
tests/test_agent_recovery.py
tests/test_agent_scheduler_cutover.py
scripts/agent_runtime_api_contract_tests.mjs
components/AgentRuntimeStatus.tsx
```

Modify:

```text
ai_tools.json
scripts/ai_scheduler.py
scripts/ai_action_executor.py
scripts/ai_loop.py
scripts/paper/decision_reader.py
scripts/paper_trader.py
scripts/paper_runner.py
server/router.mjs
server/routes/paper.mjs
components/PaperPanel.tsx
README.md
```

## Task 1: Durable Agent Store

**Files:**
- Create: `quant/agent/store.py`
- Modify: `quant/agent/__init__.py`
- Test: `tests/test_agent_store.py`

- [ ] **Step 1: Write failing schema and transaction tests**

```python
import sqlite3

from quant.agent.store import AgentStore


def _store(tmp_path):
    conn = sqlite3.connect(tmp_path / "agent.db")
    return AgentStore(conn)


def test_create_run_is_idempotent_by_trigger_id(tmp_path):
    store = _store(tmp_path)
    first = store.create_run(trigger_id="20260725:research_idle:1", agent_type="research", mode="observe", provider="opencode", model="deepseek-v4-flash-free")
    second = store.create_run(trigger_id="20260725:research_idle:1", agent_type="research", mode="observe", provider="opencode", model="deepseek-v4-flash-free")
    assert first["run_id"] == second["run_id"]


def test_checkpoint_and_event_commit_together(tmp_path):
    store = _store(tmp_path)
    run = store.create_run(trigger_id="trigger-2", agent_type="portfolio", mode="shadow", provider="glm", model="glm-5.2")
    store.checkpoint(run["run_id"], {**run, "status": "planning"}, event_type="state_transition")
    restored = store.get_run(run["run_id"])
    events = store.list_events(run["run_id"])
    assert restored["status"] == "planning"
    assert events[-1]["event_type"] == "state_transition"


def test_tool_call_idempotency_key_is_unique(tmp_path):
    store = _store(tmp_path)
    run = store.create_run(trigger_id="trigger-3", agent_type="execution", mode="paper_guarded", provider="glm", model="glm-5.2")
    first = store.begin_tool_call(run["run_id"], 1, "paper_trade_once", "same-key", {})
    second = store.begin_tool_call(run["run_id"], 1, "paper_trade_once", "same-key", {})
    assert first["tool_call_id"] == second["tool_call_id"]
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_agent_store.py -q`

Expected: FAIL because `AgentStore` does not exist.

- [ ] **Step 3: Implement schema creation and idempotent inserts**

```python
# quant/agent/store.py
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class AgentStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with self.conn:
            self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS agent_runs (
              run_id TEXT PRIMARY KEY, trigger_id TEXT NOT NULL UNIQUE,
              agent_type TEXT NOT NULL, mode TEXT NOT NULL, status TEXT NOT NULL,
              provider TEXT NOT NULL, model TEXT NOT NULL, plan_revision INTEGER NOT NULL,
              state_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              deadline_at TEXT
            );
            CREATE TABLE IF NOT EXISTS agent_events (
              event_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
              seq INTEGER NOT NULL, event_type TEXT NOT NULL, payload_json TEXT NOT NULL,
              created_at TEXT NOT NULL, UNIQUE(run_id, seq)
            );
            CREATE TABLE IF NOT EXISTS agent_tool_calls (
              tool_call_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, plan_revision INTEGER NOT NULL,
              tool_name TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE, status TEXT NOT NULL,
              input_json TEXT NOT NULL, output_json TEXT, error_json TEXT,
              started_at TEXT NOT NULL, finished_at TEXT
            );
            CREATE TABLE IF NOT EXISTS agent_checkpoints (
              run_id TEXT PRIMARY KEY, version INTEGER NOT NULL, state_json TEXT NOT NULL,
              state_sha256 TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            """)

    def create_run(self, *, trigger_id: str, agent_type: str, mode: str, provider: str, model: str) -> dict:
        existing = self.conn.execute("SELECT state_json FROM agent_runs WHERE trigger_id=?", (trigger_id,)).fetchone()
        if existing:
            return json.loads(existing[0])
        run_id = f"agent-{datetime.now():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:8]}"
        state = {"schema_version": "agent_run.v1", "run_id": run_id, "trigger_id": trigger_id,
                 "agent_type": agent_type, "mode": mode, "status": "created", "provider": provider,
                 "model": model, "plan_revision": 0, "iteration": 0, "observations": []}
        now = _now()
        with self.conn:
            self.conn.execute("INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                              (run_id, trigger_id, agent_type, mode, "created", provider, model, 0,
                               _json(state), now, now, None))
        return state

    def checkpoint(self, run_id: str, state: dict, *, event_type: str, payload: dict | None = None) -> dict:
        encoded = _json(state)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        now = _now()
        with self.conn:
            row = self.conn.execute("SELECT version FROM agent_checkpoints WHERE run_id=?", (run_id,)).fetchone()
            version = (int(row[0]) if row else 0) + 1
            self.conn.execute(
                "INSERT INTO agent_checkpoints VALUES(?,?,?,?,?) "
                "ON CONFLICT(run_id) DO UPDATE SET version=excluded.version,state_json=excluded.state_json,"
                "state_sha256=excluded.state_sha256,updated_at=excluded.updated_at",
                (run_id, version, encoded, digest, now),
            )
            self.conn.execute(
                "UPDATE agent_runs SET status=?,plan_revision=?,state_json=?,updated_at=? WHERE run_id=?",
                (state["status"], int(state.get("plan_revision", 0)), encoded, now, run_id),
            )
            seq = self.conn.execute(
                "SELECT COALESCE(MAX(seq),0)+1 FROM agent_events WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            self.conn.execute(
                "INSERT INTO agent_events(run_id,seq,event_type,payload_json,created_at) VALUES(?,?,?,?,?)",
                (run_id, seq, event_type, _json(payload or {}), now),
            )
        return {**state, "checkpoint_version": version, "state_sha256": digest}

    def get_run(self, run_id: str) -> dict | None:
        row = self.conn.execute("SELECT state_json FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def list_events(self, run_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT seq,event_type,payload_json,created_at FROM agent_events WHERE run_id=? ORDER BY seq", (run_id,)
        ).fetchall()
        return [{"seq": row[0], "event_type": row[1], "payload": json.loads(row[2]), "created_at": row[3]} for row in rows]

    def begin_tool_call(self, run_id: str, plan_revision: int, tool_name: str,
                        idempotency_key: str, arguments: dict) -> dict:
        row = self.conn.execute(
            "SELECT * FROM agent_tool_calls WHERE idempotency_key=?", (idempotency_key,)
        ).fetchone()
        if row:
            return self._tool_call(row)
        tool_call_id = f"tool-{uuid.uuid4().hex}"
        with self.conn:
            self.conn.execute(
                "INSERT INTO agent_tool_calls VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (tool_call_id, run_id, plan_revision, tool_name, idempotency_key, "running",
                 _json(arguments), None, None, _now(), None),
            )
        return self.get_tool_call_by_idempotency(idempotency_key)

    def finish_tool_call(self, tool_call_id: str, *, status: str,
                         output: dict | None = None, error: dict | None = None) -> dict:
        with self.conn:
            self.conn.execute(
                "UPDATE agent_tool_calls SET status=?,output_json=?,error_json=?,finished_at=? WHERE tool_call_id=?",
                (status, _json(output) if output is not None else None,
                 _json(error) if error is not None else None, _now(), tool_call_id),
            )
        row = self.conn.execute("SELECT * FROM agent_tool_calls WHERE tool_call_id=?", (tool_call_id,)).fetchone()
        return self._tool_call(row)

    def get_tool_call_by_idempotency(self, key: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM agent_tool_calls WHERE idempotency_key=?", (key,)).fetchone()
        return self._tool_call(row) if row else None

    def list_tool_calls(self, run_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM agent_tool_calls WHERE run_id=? ORDER BY started_at,tool_call_id", (run_id,)
        ).fetchall()
        return [self._tool_call(row) for row in rows]

    def list_runs(self, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT state_json FROM agent_runs ORDER BY updated_at DESC LIMIT ?",
            (max(1, min(int(limit), 200)),),
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    @staticmethod
    def _tool_call(row: sqlite3.Row) -> dict:
        value = dict(row)
        value["input"] = json.loads(value.pop("input_json"))
        value["output"] = json.loads(value.pop("output_json")) if value.get("output_json") else None
        value["error"] = json.loads(value.pop("error_json")) if value.get("error_json") else None
        return value
```

- [ ] **Step 4: Run store tests**

Run: `python -m pytest tests/test_agent_store.py -q`

Expected: all store tests pass.

- [ ] **Step 5: Checkpoint**

Run: `python -m pytest tests/test_agent_store.py -q; rg -n "CREATE TABLE|UNIQUE|with self.conn" quant\agent\store.py`

Expected: four tables exist, trigger and tool idempotency are unique, tests pass.

## Task 2: ai_tools.v2 Registry and Permissions

**Files:**
- Modify: `ai_tools.json`
- Create: `quant/agent/tool_registry.py`
- Test: `tests/test_agent_tool_registry.py`

- [ ] **Step 1: Write failing registry tests**

```python
import json
import pytest

from quant.agent.tool_registry import ToolPolicyError, ToolRegistry


def test_registry_rejects_unknown_tool():
    registry = ToolRegistry.from_file("ai_tools.json")
    with pytest.raises(ToolPolicyError, match="unknown tool"):
        registry.authorize("shell", {}, mode="paper_guarded", permission="paper_side_effect")


def test_paper_tool_is_blocked_in_observe_mode():
    registry = ToolRegistry.from_file("ai_tools.json")
    with pytest.raises(ToolPolicyError, match="mode"):
        registry.authorize("paper_trade_once", {}, mode="observe", permission="paper_side_effect")


def test_every_tool_has_v2_contract():
    raw = json.load(open("ai_tools.json", encoding="utf-8"))
    assert raw["schema_version"] == "ai_tools.v2"
    for tool in raw["tools"]:
        for key in ("version", "permission", "side_effect", "input_schema", "output_schema", "allowed_modes", "idempotency"):
            assert key in tool, (tool["name"], key)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_agent_tool_registry.py -q`

Expected: FAIL because current manifest is v1 and registry does not exist.

- [ ] **Step 3: Upgrade current tools without changing their names**

Add `schema_version: "ai_tools.v2"` and these fields to each existing tool:

```json
{
  "version": "1.0",
  "permission": "research",
  "side_effect": "cache_write",
  "input_schema": {"type": "object", "properties": {}, "additionalProperties": false},
  "output_schema": {"type": "object"},
  "allowed_modes": ["observe", "research", "shadow", "paper_guarded"],
  "max_per_run": 1,
  "idempotency": "run_id+tool+input_hash",
  "failure_policy": "return_observation"
}
```

Use `permission="paper_side_effect"`, `side_effect="paper_order"`, and `allowed_modes=["paper_guarded"]` for `paper_trade_once` and `paper_rebalance_once`. Keep `self_improve_propose` as `proposal_only` and `auto_allowed=false`. Do not add live tools.

- [ ] **Step 4: Implement registry authorization**

```python
# quant/agent/tool_registry.py
import json


class ToolPolicyError(ValueError):
    pass


class ToolRegistry:
    @classmethod
    def from_file(cls, path: str):
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
        if raw.get("schema_version") != "ai_tools.v2":
            raise ToolPolicyError("ai_tools.v2 required")
        return cls({row["name"]: row for row in raw.get("tools", [])}, raw.get("action_aliases", {}))

    def authorize(self, name: str, arguments: dict, *, mode: str, permission: str) -> dict:
        canonical = self.aliases.get(name, name)
        tool = self.tools.get(canonical)
        if not tool:
            raise ToolPolicyError(f"unknown tool: {name}")
        if mode not in tool.get("allowed_modes", []):
            raise ToolPolicyError(f"tool not allowed in mode: {mode}")
        if permission != tool.get("permission"):
            raise ToolPolicyError("permission mismatch")
        if not isinstance(arguments, dict):
            raise ToolPolicyError("arguments must be object")
        schema = tool.get("input_schema") or {}
        properties = schema.get("properties") or {}
        required = schema.get("required") or []
        missing = [key for key in required if key not in arguments]
        if missing:
            raise ToolPolicyError(f"missing required arguments: {','.join(missing)}")
        if schema.get("additionalProperties") is False:
            extra = sorted(set(arguments) - set(properties))
            if extra:
                raise ToolPolicyError(f"unexpected arguments: {','.join(extra)}")
        python_types = {"string": str, "number": (int, float), "integer": int,
                        "boolean": bool, "object": dict, "array": list}
        for key, value in arguments.items():
            expected = python_types.get((properties.get(key) or {}).get("type"))
            if expected and (not isinstance(value, expected) or
                             expected in {(int, float), int} and isinstance(value, bool)):
                raise ToolPolicyError(f"invalid argument type: {key}")
        return tool
```

- [ ] **Step 5: Run registry and old executor tests**

Run: `python -m pytest tests/test_agent_tool_registry.py -q; node scripts/ai_autonomous_cycle_contract_tests.mjs`

Expected: registry tests pass; update the Node contract to accept the v2 root while preserving all existing tool names and risk assertions.

## Task 3: Runtime Policies and Single Execution Owner

> Security upgrade: `resolve_runtime_policy(..., request_execution=True)` keeps
> the legacy diagnostic order (`enabled` -> `mode` -> `execution owner`) for
> compatibility, but configuration alone never authorizes execution. Actual
> paper execution requires a persistent fenced authority grant, a one-time
> issued/consumed execution session, and a final in-transaction session/order
> claim. Manual paper runs use a separately audited, mutually exclusive manual
> session and never impersonate either configured agent owner.

**Files:**
- Create: `quant/agent/policies.py`
- Test: `tests/test_agent_policies.py`

- [ ] **Step 1: Write failing owner and mode tests**

```python
import pytest
from quant.agent.policies import PolicyError, resolve_runtime_policy


def test_default_owner_is_legacy_and_runtime_is_observe():
    policy = resolve_runtime_policy({})
    assert policy["execution_owner"] == "legacy_ai_loop"
    assert policy["agent_runtime_mode"] == "observe"


def test_runtime_cannot_execute_without_ownership():
    with pytest.raises(PolicyError, match="execution owner"):
        resolve_runtime_policy({"agent_runtime_enabled": True, "agent_runtime_mode": "paper_guarded", "execution_owner": "legacy_ai_loop"}, request_execution=True)


def test_conflicting_alive_owners_fail_closed():
    with pytest.raises(PolicyError, match="owner conflict"):
        resolve_runtime_policy({"agent_runtime_enabled": True, "agent_runtime_mode": "paper_guarded", "execution_owner": "agent_runtime"}, request_execution=True, legacy_executing=True, runtime_executing=True)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_agent_policies.py -q`

Expected: FAIL because policy module does not exist.

- [ ] **Step 3: Implement explicit policy normalization**

```python
VALID_MODES = {"observe", "research", "shadow", "paper_guarded"}
VALID_OWNERS = {"legacy_ai_loop", "agent_runtime"}


class PolicyError(RuntimeError):
    pass


def resolve_runtime_policy(config: dict, *, request_execution: bool = False,
                           legacy_executing: bool = False, runtime_executing: bool = False) -> dict:
    mode = config.get("agent_runtime_mode", "observe")
    owner = config.get("execution_owner", "legacy_ai_loop")
    enabled = config.get("agent_runtime_enabled") is True
    if mode not in VALID_MODES or owner not in VALID_OWNERS:
        raise PolicyError("invalid runtime policy")
    if legacy_executing and runtime_executing:
        raise PolicyError("execution owner conflict")
    if request_execution and (not enabled or mode != "paper_guarded" or owner != "agent_runtime"):
        raise PolicyError("agent runtime is not execution owner")
    return {"agent_runtime_enabled": enabled, "agent_runtime_mode": mode, "execution_owner": owner}
```

- [ ] **Step 4: Run policy tests**

Run: `python -m pytest tests/test_agent_policies.py -q`

Expected: all pass.

- [ ] **Step 5: Checkpoint**

Run: `python -m pytest tests/test_agent_store.py tests/test_agent_tool_registry.py tests/test_agent_policies.py -q`

Expected: all foundational P1 tests pass.

## Task 4: Bounded Context Snapshots and Planner

**Files:**
- Create: `quant/agent/context.py`
- Create: `quant/agent/planner.py`
- Test: `tests/test_agent_runtime.py`

**Hardened contract (2026-07-26 quality review):**

- Project only the eight allowed state fields before traversing values. Unknown top-level
  fields, including logs, are ignored.
- Fully revalidate persisted snapshot dictionaries: exact schema, canonical UTC,
  section bounds, advisory-only objective, truncation schema, recursive secret-key
  rejection, UTF-8 byte limit and payload hash. Structural keys entering the model
  are ASCII-only; Unicode remains allowed in values.
- Bind every snapshot to `ToolRegistry.manifest_sha256`, computed from the complete
  canonical `ai_tools.v2` manifest (all tool fields plus flattened aliases). Runtime,
  context builder and Planner must share one explicit registry instance; any manifest
  revision invalidates an older snapshot before tool-summary validation.
- Expose only canonical, observe-safe, automatically allowed non-paper tools from
  `ai_tools.v2`. Reject aliases, unknown tools, proposal-only tools and paper tools.
- Require the bounded native-JSON model result to contain exact native-string
  `provider`, `model` and `requested_model` identities matching the constructor.
  Never repair free text, coerce values, fall back, or accept execution authority.

- [ ] **Step 1: Write failing context/planner tests**

```python
from pathlib import Path

from quant.agent.context import build_context_snapshot
from quant.agent.planner import AgentPlanner
from quant.agent.tool_registry import ToolRegistry


REGISTRY = ToolRegistry.from_file(Path(__file__).resolve().parents[1] / "ai_tools.json")


def _large_state_fixture():
    return {
        "market": [{"code": f"{index:06d}", "price": 10 + index, "note": "x" * 700} for index in range(100)],
        "data_quality": {"status": "healthy", "issues": []},
        "positions": [{"code": f"{index:06d}", "quantity": 100} for index in range(75)],
        "risk": {"level": "low", "critical_alerts": 0},
        "approved_research": [{"code": "600519", "score": 0.8}],
        "objective": {"objective_policy": "advisory_only", "required_annualized_return_pct": 120},
        "memory": [{"summary": f"memory-{index}"} for index in range(30)],
        "tools": [{"name": "run_risk_monitor"}],
        "logs": ["full log content must not enter planner context"],
    }


def test_context_excludes_full_logs_and_advisory_target_pressure():
    snapshot = build_context_snapshot(_large_state_fixture(), tool_registry=REGISTRY)
    assert "logs" not in snapshot
    assert "required_annualized_return_pct" not in str(snapshot["objective_for_planner"])
    assert len(str(snapshot)) < 30_000


def test_planner_pins_model_and_returns_valid_contract():
    captured = {}
    def fake_chat_json(provider, system, user, **kwargs):
        captured.update(provider=provider, model=kwargs.get("model"))
        return {
            "success": True,
            "provider": "opencode",
            "model": "nemotron-3-ultra-free",
            "requested_model": "nemotron-3-ultra-free",
            "data": {"goal": "inspect risk", "status": "need_tool", "tasks": [], "next_tool": {"name": "run_risk_monitor", "permission": "research", "arguments": {}}, "evidence_refs": [], "summary": "risk evidence is required"},
        }
    planner = AgentPlanner(
        "opencode",
        "nemotron-3-ultra-free",
        registry=REGISTRY,
        chat_json_fn=fake_chat_json,
    )
    context = build_context_snapshot(
        _large_state_fixture(),
        now_iso="2026-07-25T04:00:00Z",
        tool_registry=REGISTRY,
    )
    result = planner.plan({"run_id": "agent-1", "observations": []}, context)
    assert captured == {"provider": "opencode", "model": "nemotron-3-ultra-free"}
    assert result["status"] == "need_tool"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_agent_runtime.py -k "context or planner" -q`

Expected: FAIL because context and planner modules do not exist.

- [ ] **Step 3: Implement bounded snapshot construction**

`build_context_snapshot()` must project the input first, sanitize only allowed
sections, bind tools to a validated `ToolRegistry`, construct the truncation
summary and call `validate_context_snapshot()` before returning. The validator
must independently repeat the semantic checks for restored dictionaries; a
self-signed but semantically invalid snapshot must fail.

The snapshot retains only `registry_manifest_sha256` for replay compatibility.
Persisting historical full manifests is explicitly deferred to P1.10.

Cap market, positions and approved research at 50 rows, relevant memory at 10,
tools at 50, free text at 500 characters and canonical UTF-8 JSON below 30,000
bytes. NFKC/camel-case normalized secret and prompt keys are stripped while
building and rejected while restoring.

- [ ] **Step 4: Implement model-pinned planner**

The Planner must validate the entire model result as bounded finite native JSON
before reading fields. It then requires `success is True`, all three pinned
identity fields, a strict Planner output shape, a canonical tool name and matching
permission. Arguments receive a second tighter bound. Any exception, malformed
identity, Unicode/surrogate failure, hallucinated tool or normalized execution
authorization intent becomes a bounded redacted `PlannerError`; there is no
repair or fallback path.

- [ ] **Step 5: Run focused tests**

Run: `python -m pytest tests/test_agent_runtime.py -k "context or planner" -q`

Expected: selected tests pass.

## Task 5: Agent Runtime FSM

> **P1.5 quality closure (authoritative):** Runtime tool entrypoints must first
> extract only `run_id`, `checkpoint_version`, and `state_sha256`, reload the
> authoritative Run from `AgentStore`, and reject any stale or tampered identity
> before authorization or dispatch. Planner and verifier payloads are independently
> strict-validated by Runtime. Tool budgets are persisted through the Store's atomic
> `reserve_tool_call()` transaction. P1.5 has no execution capability: every
> `paper_side_effect` / `paper_order` request blocks with
> `execution_not_implemented` and reaches neither Registry authorization nor the
> dispatcher. This paragraph supersedes the historical RED/implementation sketches
> retained below for sequence context.

**Files:**
- Create: `quant/agent/runtime.py`
- Modify: `quant/agent/__init__.py`
- Test: `tests/test_agent_runtime.py`

- [ ] **Step 1: Write failing transition and budget tests**

```python
import sqlite3
import pytest
from quant.agent.runtime import AgentRuntime, InvalidTransition
from quant.agent.store import AgentStore


class ReadyPlanner:
    def plan(self, state, context):
        return {
            "goal": "observe safely",
            "status": "ready_to_decide",
            "tasks": [],
            "evidence_refs": ["evidence:test"],
            "summary": "observation complete",
            "decision": {"execution_eligible": False, "trade_policy": "no_new_position"},
        }


class NeverReadyPlanner:
    def plan(self, state, context):
        return {
            "goal": "collect risk",
            "status": "need_tool",
            "tasks": [],
            "next_tool": {"name": "run_risk_monitor", "permission": "research", "arguments": {}},
            "evidence_refs": [],
            "summary": "more observations required",
        }


class AllowRegistry:
    def authorize(self, name, arguments, *, mode, permission):
        return {"name": name, "permission": permission, "side_effect": "cache_write"}


class SuccessfulDispatcher:
    def execute(self, name, arguments, *, source, provider):
        return {"success": True, "tool": name, "data": {"risk_level": "low"}}


class PassVerifier:
    def verify(self, state, plan):
        return {"status": "pass", "reason_codes": []}


def _runtime(tmp_path, planner):
    return AgentRuntime(
        store=AgentStore(sqlite3.connect(tmp_path / "runtime.db")),
        planner=planner,
        registry=AllowRegistry(),
        dispatcher=SuccessfulDispatcher(),
        verifier=PassVerifier(),
        context_builder=lambda state: {"snapshot_id": "snapshot-test"},
        provider="opencode",
        model="deepseek-v4-flash-free",
        iteration_budget=2,
        tool_budget=2,
    )


@pytest.fixture
def runtime(tmp_path):
    return _runtime(tmp_path, ReadyPlanner())


@pytest.fixture
def runtime_with_never_ready_planner(tmp_path):
    return _runtime(tmp_path, NeverReadyPlanner())


def test_invalid_transition_is_rejected(runtime):
    run = runtime.create_run("trigger-a", "portfolio", "shadow")
    with pytest.raises(InvalidTransition):
        runtime.transition(run, "executing")


def test_transition_threads_checkpoint_cas_metadata(runtime):
    state = runtime.create_run("trigger-cas", "research", "observe")
    state = runtime.transition(state, "observing")
    assert state["checkpoint_version"] == 1
    assert state["state_sha256"]
    state = runtime.transition(state, "planning")
    assert state["checkpoint_version"] == 2
    assert state["state_sha256"]


def test_observe_mode_completes_without_execution(runtime):
    result = runtime.run("trigger-b", "research", "observe")
    assert result["status"] == "completed"
    assert result.get("execution_id") is None


def test_planner_budget_exhaustion_fails_closed(runtime_with_never_ready_planner):
    result = runtime_with_never_ready_planner.run("trigger-c", "portfolio", "shadow")
    assert result["status"] == "blocked"
    assert result["trade_policy"] == "no_new_position"
    assert result["block_reason"] == "planner_budget_exhausted"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_agent_runtime.py -k "transition or observe or budget" -q`

Expected: FAIL because runtime does not exist.

- [ ] **Step 3: Historical FSM draft (do not copy as production code)**

The snippet below predates the P1.5 quality closure. The production implementation
must additionally enforce all authoritative-state, strict-contract, atomic-budget,
fixed-error-code, and no-paper-capability requirements stated above. In particular,
local `tool_count`, caller-supplied `mode`, inferred permission, and direct dispatcher
execution are not valid production security boundaries.

```python
LEGAL_TRANSITIONS = {
    "created": {"observing", "failed"},
    "observing": {"planning", "blocked", "failed"},
    "planning": {"calling_tool", "deciding", "blocked", "failed"},
    "calling_tool": {"validating", "blocked", "failed"},
    "validating": {"planning", "deciding", "executing", "completed", "blocked", "failed"},
    "deciding": {"validating", "blocked", "failed"},
    "executing": {"reconciling", "blocked", "failed"},
    "reconciling": {"completed", "blocked", "failed"},
}


class InvalidTransition(RuntimeError):
    pass


class AgentRuntime:
    def __init__(self, *, store, planner, registry, dispatcher, verifier, context_builder,
                 provider: str, model: str, iteration_budget: int = 4, tool_budget: int = 12):
        self.store = store
        self.planner = planner
        self.registry = registry
        self.dispatcher = dispatcher
        self.verifier = verifier
        self.context_builder = context_builder
        self.provider = provider
        self.model = model
        self.iteration_budget = iteration_budget
        self.tool_budget = tool_budget

    def create_run(self, trigger_id: str, agent_type: str, mode: str) -> dict:
        return self.store.create_run(trigger_id=trigger_id, agent_type=agent_type, mode=mode,
                                     provider=self.provider, model=self.model)

    def transition(self, state: dict, next_status: str, *, event: dict | None = None) -> dict:
        if next_status not in LEGAL_TRANSITIONS.get(state["status"], set()):
            raise InvalidTransition(f"{state['status']} -> {next_status}")
        updated = {**state, "status": next_status}
        return self.store.checkpoint(
            state["run_id"], updated,
            event_type="state_transition", payload=event or {},
        )

    def run(self, trigger_id: str, agent_type: str, mode: str) -> dict:
        state = self.transition(self.create_run(trigger_id, agent_type, mode), "observing")
        context = self.context_builder(state)
        state = self.transition({**state, "context_snapshot": context}, "planning")
        tool_count = 0
        for iteration in range(1, self.iteration_budget + 1):
            state = {**state, "iteration": iteration}
            plan = self.planner.plan(state, context)
            if plan.get("status") == "need_tool":
                request = plan.get("next_tool") or {}
                if tool_count >= self.tool_budget:
                    break
                tool = self.registry.authorize(
                    request.get("name", ""), request.get("arguments") or {}, mode=mode,
                    permission=request.get("permission", "research"),
                )
                state = self.transition(state, "calling_tool", event={"tool": tool["name"]})
                observation = self.dispatcher.execute(
                    tool["name"], request.get("arguments") or {}, source=state["run_id"], provider=self.provider,
                )
                tool_count += 1
                state = self.transition({**state, "observations": [*state.get("observations", []), observation]}, "validating")
                state = self.transition(state, "planning")
                continue
            if plan.get("status") != "ready_to_decide":
                return self.transition({**state, "block_reason": "planner_contract_invalid",
                                        "trade_policy": "no_new_position"}, "blocked")
            state = self.transition({**state, "plan": plan}, "deciding")
            verification = self.verifier.verify(state, plan)
            state = self.transition({**state, "verification": verification}, "validating")
            if verification.get("status") != "pass":
                return self.transition({**state, "block_reason": "verification_failed",
                                        "trade_policy": "no_new_position"}, "blocked")
            if mode != "paper_guarded":
                return self.transition({**state, "trade_policy": "no_new_position"}, "completed")
            return self.transition({**state, "block_reason": "execution_not_implemented",
                                    "trade_policy": "no_new_position"}, "blocked")
        return self.transition({**state, "block_reason": "planner_budget_exhausted",
                                "trade_policy": "no_new_position"}, "blocked")
```

`transition()` must return the exact value returned by `store.checkpoint()` so
`checkpoint_version` and `state_sha256` flow into the next transition. Returning
the pre-checkpoint `updated` object discards CAS metadata; the following write is
required to fail with `AgentStoreConflictError`. Do not weaken Store CAS to make
that obsolete draft work.

Keep the constructor defaults at 4 iterations/12 tools for intraday; the caller may explicitly pass 8/30 for research runs.

- [ ] **Step 4: Run runtime tests**

Run: `python -m pytest tests/test_agent_runtime.py -q`

Expected: all runtime tests pass.

- [ ] **Step 5: Checkpoint**

Run: `python -m pytest tests/test_agent_store.py tests/test_agent_tool_registry.py tests/test_agent_policies.py tests/test_agent_runtime.py -q`

Expected: all foundational and FSM tests pass.

## Task 6: Tool Execution, Idempotency and Crash Recovery

> **Scope correction after P1.5 review:** P1.6 recovery examples cover only
> `read_only`/`research` tools with `none` or `cache_write` side effects. A running
> cache write whose outcome is not provable becomes `unknown` and is never retried.
> Paper tools remain unreachable in the default Runtime. Paper recovery tests that
> use `ExecutionAuthorityStore` plus grant/session fencing and matching audit/order
> evidence belong to P1.9. A manually constructed `reconciling` state may only
> complete after a read-only dispatcher reconciliation query returns bounded audit
> evidence; otherwise it blocks with `tool_outcome_unknown`.

**Files:**
- Modify: `scripts/ai_action_executor.py`
- Modify: `quant/agent/runtime.py`
- Modify: `quant/agent/store.py`
- Modify: `scripts/agent_runner.py`
- Test: `tests/test_agent_recovery.py`
- Test: `tests/test_agent_store.py`
- Test: `tests/test_ai_action_executor_registry.py`

> **P1.6 closure (2026-07-26):** Agent Store schema v3 enforces one active
> ToolCall per Run, separates claim and actual-dispatch counters, persists a UTC
> clock high-water mark, and permanently fences expired side-effect calls as
> `unknown`. The registered executor owns a same-database
> `ai_tool_execution_ledger`; completed results are cached by strict canonical
> idempotency identity, while `dispatching`/`unknown` are never redispatched.
> Runtime accepts reconciliation only after an independent AgentStore query
> matches the ledger row's tool, key, input/output hashes, audit id and receipt.
> An ordinary resume during an unexpired lease is a no-op: it does not reconcile,
> clear the owner claim or mutate the executor ledger. Expired side-effect calls
> are permanently fenced `unknown`; stale worker completion cannot overwrite the
> fence. A manually persisted non-paper `reconciling` Run may query the production
> ledger, but completes only when the output itself cross-binds the authoritative
> audit id and receipt. Critical Store writes confirm committed state after a lost
> COMMIT acknowledgement, and the executor rejects malformed same-name ledger
> schemas instead of reusing them.
> `agent_runner` exposes observe-only `resume`; paper dispatch remains zero and
> returns `execution_not_implemented` until P1.9.

- [x] **Step 1: Write failing recovery tests**

```python
import sqlite3
import pytest

from quant.agent.runtime import AgentRuntime
from quant.agent.store import AgentStore


class RecoveryPlanner:
    def plan(self, state, context):
        return {"status": "ready_to_decide", "decision": {"execution_eligible": False}}


class RecoveryRegistry:
    def authorize(self, name, arguments, *, mode, permission):
        return {
            "name": name,
            "permission": permission,
            "side_effect": "none" if name == "run_risk_monitor" else "cache_write",
        }


class CountingDispatcher:
    def __init__(self):
        self.calls = 0
        self.fail_once_tools = set()

    def fail_once(self, name):
        self.fail_once_tools.add(name)

    def execute(self, name, arguments, *, source, provider):
        self.calls += 1
        if name in self.fail_once_tools:
            self.fail_once_tools.remove(name)
            return {"success": False, "transient": True, "error": "temporary"}
        return {"success": True, "tool": name, "audit_id": f"audit-{self.calls}"}


class RecoveryVerifier:
    def verify(self, state, plan):
        return {"status": "pass", "reason_codes": []}


def _planning_run(runtime, trigger_id, mode):
    run = runtime.create_run(trigger_id, "execution", mode)
    run = runtime.transition(run, "observing")
    return runtime.transition(run, "planning")


@pytest.fixture
def runtime_fixture(tmp_path):
    dispatcher = CountingDispatcher()
    runtime = AgentRuntime(
        store=AgentStore(sqlite3.connect(tmp_path / "recovery.db")),
        planner=RecoveryPlanner(),
        registry=RecoveryRegistry(),
        dispatcher=dispatcher,
        verifier=RecoveryVerifier(),
        context_builder=lambda state: {},
        provider="opencode",
        model="deepseek-v4-flash-free",
    )
    return runtime, dispatcher


def test_recovery_does_not_repeat_completed_cache_write(runtime_fixture):
    runtime, dispatcher = runtime_fixture
    run = _planning_run(runtime, "trigger-recover", "observe")
    runtime.call_tool(run, "refresh_data", {})
    assert dispatcher.calls == 1
    recovered = runtime.resume(run["run_id"])
    assert dispatcher.calls == 1
    assert recovered["status"] == "completed"


def test_unknown_side_effect_outcome_blocks_recovery(runtime_fixture):
    runtime, dispatcher = runtime_fixture
    dispatcher.raise_for("refresh_data")
    run = _planning_run(runtime, "trigger-unknown", "observe")
    runtime.call_tool(run, "refresh_data", {})
    recovered = runtime.resume(run["run_id"])
    assert recovered["status"] == "blocked"
    assert recovered["block_reason"] == "tool_outcome_unknown"


def test_read_only_tool_may_retry_after_transient_failure(runtime_fixture):
    runtime, dispatcher = runtime_fixture
    dispatcher.fail_once("run_risk_monitor")
    run = _planning_run(runtime, "trigger-read", "observe")
    result = runtime.call_tool(run, "run_risk_monitor", {})
    assert result["status"] == "completed"
    assert dispatcher.calls == 2
```

- [x] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_agent_recovery.py -q`

Expected: FAIL because tool lifecycle and resume behavior are not implemented.

- [x] **Step 3: Expose a stable dispatcher from the existing executor**

Add a public wrapper without changing existing `run_executor()` behavior:

```python
def execute_registered_tool(
    tool: str,
    arguments: dict,
    *,
    source: str,
    provider: str,
    idempotency_key: str | None = None,
) -> dict:
    registry = ToolRegistry.from_file(TOOLS_PATH)
    canonical = registry.aliases.get(tool, tool)
    contract = registry.authorize(canonical, arguments, mode="research", ...)
    output = _execute_tool(canonical, {**contract, **arguments}, source, provider)
    return registry.validate_output(canonical, output)
```

Runtime must calculate:

```python
encoded = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
input_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
idempotency_key = f"{run_id}:{plan_revision}:{tool_name}:{input_hash}"
```

The lifecycle sketch below is limited to non-paper recovery. Runtime reloads
authoritative state, obtains permission and side-effect metadata from the canonical
Registry contract, passes true run/day counts, and atomically reserves the tool call
in `AgentStore` before dispatch.

Canonical argument JSON is produced with `json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`:

```python
import hashlib
import json


def call_tool(self, state: dict, tool_name: str, arguments: dict) -> dict:
    state = self._authoritative_tool_state(state)
    tool = self.registry.authorize(tool_name, arguments, ...)
    key = strict_idempotency_key(state, tool["name"], arguments)
    reservation = self.store.reserve_tool_call(..., idempotency_key=key)
    claim = self.store.claim_tool_call(reservation["tool_call"]["tool_call_id"], ...)
    return self._dispatch_claimed_tool(state, claim, arguments, ...)

def resume(self, run_id: str) -> dict:
    state = self.store.get_run(run_id)
    calls = self.store.list_tool_calls(run_id)
    # completed is never repeated; reserved may be claimed; dispatching none may
    # retry once; dispatching cache_write requires bound reconciliation evidence.
    # Unknown is persisted and blocks the Run.
    return state
```

Paper execution is not part of P1.6. Default `call_tool()` and `resume()` block paper
tools with `execution_not_implemented` and zero order dispatches. Paper reconciliation
requires P1.9 authority/session integration; unknown outcomes are never repeated.

- [x] **Step 4: Run recovery tests**

Run: `python -m pytest tests/test_agent_recovery.py -q`

Expected: all recovery tests pass.

- [x] **Step 5: Run existing execution idempotency tests**

Run: `python -m pytest tests/test_paper_order_router.py tests/test_execution_fill_risk.py tests/test_audit_replay_isolation.py -q`

Expected: all pass.

## Task 7: Agent Runner CLI

**Files:**
- Create: `scripts/agent_runner.py`
- Test: `tests/test_agent_runtime.py`

> **P1.7 closure (2026-07-26):** Agent Store schema v4 persists each ToolCall's
> authoritative side-effect contract. `cancel_run()` atomically fences the active
> ToolCall and checkpoints the Run: work not dispatched is cancelled, while a
> dispatched non-read-only outcome becomes permanently `unknown`. Stale lease
> holders cannot mark or finish after cancellation, and repeated/concurrent cancel
> produces one event. The runner uses bounded strict JSONL, fixed non-reflective
> errors and per-request stores. Query actions open SQLite with `mode=ro`, skip all
> schema/cache initialization and cleanup, tolerate missing databases/tables, and
> close every connection. Executor imports remain lazy; `run_once` remains observe
> by default and ignores `request_execution` as an authority signal.

- [x] **Step 1: Add failing action-dispatch tests**

```python
from scripts.agent_runner import dispatch


def test_status_action_is_read_only(monkeypatch):
    monkeypatch.setattr("scripts.agent_runner.runtime_status", lambda: {"running": False})
    result = dispatch({"action": "status"})
    assert result == {"success": True, "data": {"running": False}}


def test_run_action_defaults_to_observe(monkeypatch):
    captured = {}
    monkeypatch.setattr("scripts.agent_runner.run_once", lambda **kwargs: captured.update(kwargs) or {"status": "completed"})
    result = dispatch({"action": "run_once", "agent_type": "research"})
    assert captured["mode"] == "observe"
    assert result["success"] is True
```

- [x] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_agent_runtime.py -k "status_action or run_action" -q`

Expected: FAIL because CLI does not exist.

- [x] **Step 3: Implement JSON-stdin CLI actions**

```python
ACTIONS = {"status", "run_once", "list_runs", "run_detail", "events", "tool_calls", "replay", "cancel"}


def dispatch(req: dict) -> dict:
    action = str(req.get("action") or "status")
    if action not in ACTIONS:
        return {"success": False, "error": f"unknown action: {action}"}
    if action == "status":
        return {"success": True, "data": runtime_status()}
    if action == "run_once":
        return {"success": True, "data": run_once(agent_type=req.get("agent_type", "research"), mode=req.get("mode", "observe"), trigger_id=req.get("trigger_id"))}
    store = get_store()
    run_id = str(req.get("run_id") or "")
    if action == "list_runs":
        return {"success": True, "data": store.list_runs(req.get("limit", 50))}
    if action == "run_detail":
        return {"success": True, "data": store.get_run(run_id)}
    if action == "events":
        return {"success": True, "data": store.list_events(run_id)}
    if action == "tool_calls":
        return {"success": True, "data": store.list_tool_calls(run_id)}
    if action == "replay":
        return build_replay(store, run_id)
    if action == "cancel":
        return {"success": True, "data": cancel_run(store, run_id)}
    raise AssertionError(f"unhandled action: {action}")
```

Implement `get_store()` with `sqlite3.connect(os.environ.get("QUANT_DB_PATH", ROOT / "data" / "quant.db"), timeout=30)` and return `AgentStore(conn)`. `cancel_run()` returns `run_not_found` for an absent ID, leaves terminal runs unchanged, and checkpoints any active run as `blocked` with `block_reason="user_cancelled"`. Use the same final-line JSON stdout convention as other Python runners. Never print logs to stdout.

- [x] **Step 4: Run runner tests and smoke status**

Run:

```powershell
python -m pytest tests/test_agent_runtime.py -k "status_action or run_action" -q
'{"action":"status"}' | python scripts/agent_runner.py
```

Expected: tests pass and CLI emits one valid JSON object.

- [x] **Step 5: Checkpoint**

Run: `python -m pytest tests/test_agent_store.py tests/test_agent_runtime.py tests/test_agent_recovery.py -q`

Expected: all pass.

## Task 8: Scheduler Observe/Shadow Integration

**Files:**
- Modify: `scripts/ai_scheduler.py:109-455`
- Modify: `scripts/ai_loop.py`
- Test: `tests/test_agent_scheduler_cutover.py`

- [ ] **Step 1: Write failing scheduler ownership tests**

```python
import scripts.ai_scheduler as scheduler


def test_disabled_runtime_keeps_legacy_cycle(monkeypatch):
    monkeypatch.setattr(scheduler, "_read_cfg", lambda: {"agent_runtime_enabled": False, "provider": "opencode", "model": "deepseek-v4-flash-free"})
    monkeypatch.setattr(scheduler, "determine_mode", lambda: "research_idle")
    called = {"legacy": 0, "agent": 0}
    monkeypatch.setattr(scheduler, "_run_research_idle_cycle", lambda *a, **k: called.__setitem__("legacy", 1) or {"cycle": "legacy"})
    monkeypatch.setattr(scheduler, "_run_agent_cycle", lambda *a, **k: called.__setitem__("agent", 1) or {})
    scheduler.run_one_cycle()
    assert called == {"legacy": 1, "agent": 0}


def test_observe_runtime_cannot_trigger_paper():
    requested, reason = scheduler._agent_execution_request("intraday", {
        "agent_runtime_enabled": True,
        "agent_runtime_mode": "observe",
        "execution_owner": "legacy_ai_loop",
    })
    assert requested is False
    assert reason == ""


def test_paper_guarded_requires_agent_execution_owner():
    requested, reason = scheduler._agent_execution_request("intraday", {
        "agent_runtime_enabled": True,
        "agent_runtime_mode": "paper_guarded",
        "execution_owner": "legacy_ai_loop",
    })
    assert requested is False
    assert reason == "agent runtime is not execution owner"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_agent_scheduler_cutover.py -q`

Expected: FAIL because scheduler has no runtime branch.

- [ ] **Step 3: Add runtime branch behind explicit feature flags**

```python
policy = resolve_runtime_policy(cfg)
if policy["agent_runtime_enabled"]:
    result = _run_agent_cycle(provider, model, mode, policy)
else:
    result = _run_legacy_cycle(provider, mode, cfg)
```

Implement the execution request gate used by `_run_agent_cycle()`:

```python
def _agent_execution_request(scheduler_mode: str, policy: dict) -> tuple[bool, str]:
    if policy["agent_runtime_mode"] != "paper_guarded":
        return False, ""
    if scheduler_mode != "intraday":
        return False, ""
    if policy["execution_owner"] != "agent_runtime":
        return False, "agent runtime is not execution owner"
    return True, ""
```

Map scheduler modes with `{"intraday": "execution", "post_market": "review", "research_idle": "research"}` and create trigger IDs as `f"{date}:{scheduler_mode}:{cycle_seq}"`. Pass `request_execution=True` only when `_agent_execution_request()` returns true. If it returns a non-empty reason, emit a blocked cycle result; in observe/shadow it never calls paper execution.

- [ ] **Step 4: Make legacy ai_loop honor execution ownership**

Before Step 9 in `ai_loop.py`:

```python
runtime_cfg = cache.get("agent:config") or {}
owner = runtime_cfg.get("execution_owner", "legacy_ai_loop")
if trigger_paper and owner != "legacy_ai_loop":
    results["final"]["trade_allowed"] = False
    results["final"].setdefault("reason_codes", []).append("legacy_not_execution_owner")
    trigger_paper = False
```

- [ ] **Step 5: Run scheduler and autonomous regressions**

Run: `python -m pytest tests/test_agent_scheduler_cutover.py scripts/ai_scheduler_memory_contract_tests.py -q; node scripts/ai_autonomous_cycle_contract_tests.mjs`

Expected: all tests pass and legacy behavior remains unchanged while runtime is disabled.

## Task 9: Paper Decision Binding and Execution Reconciliation

**Files:**
- Modify: `scripts/paper/decision_reader.py`
- Modify: `scripts/paper_trader.py:453-735`
- Test: `tests/test_agent_recovery.py`
- Test: `tests/test_decision_reader_binding.py`

- [ ] **Step 1: Add failing v2 ownership tests**

```python
def test_paper_rejects_agent_decision_when_legacy_owns_execution():
    current = {**decision(), "run_id": "agent-1", "verifier_ok": True}
    cache = FakeCache({"ai:decision:latest": current})
    loaded, errors = decision_reader.load_valid_decision(
        cache, require_verifier=False, execution_owner="legacy_ai_loop"
    )
    assert loaded["trade_allowed"] is False
    assert "agent_runtime_not_execution_owner" in loaded["reason_codes"]
    assert errors


def test_paper_accepts_verified_agent_adapter_when_runtime_owns_execution():
    current = {**decision(), "run_id": "agent-2", "verifier_ok": True}
    cache = FakeCache({
        "ai:decision:latest": current,
        "ai:verifier:latest": {
            "overall": "pass",
            "decision_id": current["decision_id"],
            "generated_at": current["generated_at"],
        },
    })
    loaded, errors = decision_reader.load_valid_decision(
        cache, require_verifier=True, execution_owner="agent_runtime"
    )
    assert loaded["trade_allowed"] is True
    assert loaded["run_id"] == "agent-2"
    assert errors == []
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_decision_reader_binding.py -k agent -q`

Expected: FAIL because decision reader has no execution-owner parameter.

- [ ] **Step 3: Extend decision reader without parsing Planner output**

Only read `ai:decision:latest` after the Runtime has written the verified v1 adapter. Preserve the existing `(decision, errors)` return contract and add `execution_owner="legacy_ai_loop"` as a keyword-only parameter:

```python
if execution_owner == "agent_runtime":
    if decision.get("run_id", "").startswith("agent-") is False:
        errors.append("agent decision missing")
        decision["trade_allowed"] = False
        decision["trade_policy"] = "no_new_position"
        decision.setdefault("reason_codes", []).append("agent_decision_missing")
    elif decision.get("verifier_ok") is not True:
        errors.append("agent verifier not passed")
        decision["trade_allowed"] = False
        decision["trade_policy"] = "no_new_position"
        decision.setdefault("reason_codes", []).append("agent_verifier_not_passed")
elif str(decision.get("run_id", "")).startswith("agent-"):
    errors.append("agent runtime is not execution owner")
    decision["trade_allowed"] = False
    decision["trade_policy"] = "no_new_position"
    decision.setdefault("reason_codes", []).append("agent_runtime_not_execution_owner")
```

Do not change `client_order_id`; it already binds date, decision, code, direction and quantity. Preserve the paper trader's own `summary.run_id` as the paper run ID, and add the Agent identifier separately as `agent_run_id=decision.get("run_id")` to order, trade, risk and audit payloads.

- [ ] **Step 4: Reconcile after paper execution**

The paper run ID and Agent run ID are different namespaces. Reconcile by indexed `decision_id`, then require the JSON payload's `agent_run_id` to equal the Runtime run ID:

```python
import json


def reconcile_paper_execution(conn, *, agent_run_id: str, decision_id: str) -> dict:
    rows = conn.execute(
        "SELECT run_id,decision_id,order_id,status,payload FROM orders WHERE decision_id=? ORDER BY id",
        (decision_id,),
    ).fetchall()
    matched = []
    mismatched = []
    for row in rows:
        payload = json.loads(row[4])
        item = {"paper_run_id": row[0], "decision_id": row[1], "order_id": row[2],
                "status": row[3], "agent_run_id": payload.get("agent_run_id")}
        (matched if item["agent_run_id"] == agent_run_id else mismatched).append(item)
    unknown = [item["order_id"] for item in matched if item["status"] not in {"filled", "rejected", "cancelled"}]
    if mismatched:
        unknown.extend(item["order_id"] for item in mismatched)
    return {"matched": matched, "unknown_orders": sorted(set(unknown)),
            "paper_run_ids": sorted({item["paper_run_id"] for item in matched if item["paper_run_id"]})}
```

Then checkpoint:

```python
bounded_order_summary = reconciliation["matched"][:100]
no_unknown_orders = not reconciliation["unknown_orders"]
execution_id = (
    reconciliation["paper_run_ids"][0]
    if len(reconciliation["paper_run_ids"]) == 1 else None
)
checkpoint_state = {
    "status": "completed" if no_unknown_orders else "blocked",
    "execution_id": execution_id,
    "orders": bounded_order_summary,
    "reconciliation": {
        "unknown_orders": reconciliation["unknown_orders"],
        "matched": len(reconciliation["matched"]),
    },
}
```

- [ ] **Step 5: Run decision, recovery and paper regressions**

Run: `python -m pytest tests/test_decision_reader_binding.py tests/test_agent_recovery.py tests/test_paper_order_router.py tests/test_execution_fill_risk.py tests/test_audit_replay_isolation.py -q`

Expected: all pass.

## Task 10: Replay and Read-Only API

**Files:**
- Create: `quant/agent/replay.py`
- Modify: `scripts/agent_runner.py`
- Modify: `scripts/paper_runner.py`
- Modify: `server/router.mjs`
- Modify: `server/routes/paper.mjs`
- Create: `scripts/agent_runtime_api_contract_tests.mjs`

- [ ] **Step 1: Write failing replay and API contract tests**

```python
import sqlite3

from quant.agent.replay import build_replay
from quant.agent.store import AgentStore


def test_replay_reconstructs_ordered_events(tmp_path):
    store = AgentStore(sqlite3.connect(tmp_path / "replay.db"))
    run = store.create_run(
        trigger_id="trigger-replay", agent_type="research", mode="observe",
        provider="opencode", model="deepseek-v4-flash-free",
    )
    run = {**run, "status": "completed"}
    store.checkpoint(run["run_id"], run, event_type="state_transition", payload={"to": "completed"})
    call = store.begin_tool_call(run["run_id"], 0, "run_risk_monitor", "replay-key", {})
    store.finish_tool_call(call["tool_call_id"], status="completed", output={"success": True})
    replay = build_replay(store, run["run_id"])
    assert [event["seq"] for event in replay["events"]] == sorted(event["seq"] for event in replay["events"])
    assert replay["run"]["provider"] == "opencode"
    assert replay["tool_calls"][0]["input"]
```

Create Node assertions:

```javascript
assert(paperRoute.includes("action === 'agent_runtime_status'"));
assert(paperRoute.includes("action === 'agent_runs'"));
assert(paperRoute.includes("action === 'agent_replay'"));
assert(router.includes("'agent_runtime_status'"));
assert(router.includes("'agent_runs'"));
assert(router.includes("'agent_replay'"));
assert(!paperRoute.includes('API_KEY'));
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_agent_runtime.py -k replay -q; node scripts/agent_runtime_api_contract_tests.mjs`

Expected: both fail because replay and routes do not exist.

- [ ] **Step 3: Implement replay from AgentStore**

```python
def build_replay(store: AgentStore, run_id: str) -> dict:
    run = store.get_run(run_id)
    if not run:
        return {"success": False, "error": "run not found", "run_id": run_id}
    return {
        "success": True,
        "run": run,
        "events": store.list_events(run_id),
        "tool_calls": store.list_tool_calls(run_id),
    }
```

- [ ] **Step 4: Add API actions through agent_runner**

Read-only actions:

```text
agent_runtime_status
agent_runs
agent_run_detail
agent_run_events
agent_tool_calls
agent_replay
```

Control actions `agent_run_once`, `agent_cancel`, and `agent_retry_blocked` must remain outside `READ_ONLY_ACTIONS` and use the existing local token protection. Encode request JSON as base64 before embedding it in Python runner source, matching current protected route patterns.

- [ ] **Step 5: Run API and security contracts**

Run: `node scripts/agent_runtime_api_contract_tests.mjs; node scripts/security_regression_tests.mjs; node scripts/valuation_api_contract_tests.mjs`

Expected: all report PASS.

## Task 11: Read-Only Runtime UI

**Files:**
- Create: `components/AgentRuntimeStatus.tsx`
- Modify: `components/PaperPanel.tsx`
- Create or modify: `scripts/agent_runtime_frontend_contract_tests.mjs`

- [ ] **Step 1: Write failing frontend contract**

```javascript
assert(fs.existsSync('components/AgentRuntimeStatus.tsx'));
const component = fs.readFileSync('components/AgentRuntimeStatus.tsx', 'utf8');
for (const label of ['当前任务', '最近工具', '验证结果', '执行权限', '阻塞原因']) {
  assert(component.includes(label), `missing ${label}`);
}
assert(component.includes("action: 'agent_runtime_status'"));
assert(component.includes("action: 'agent_runs'"));
assert(!component.includes('prompt_text'));
assert(!component.includes('chain_of_thought'));
```

- [ ] **Step 2: Run contract and verify failure**

Run: `node scripts/agent_runtime_frontend_contract_tests.mjs`

Expected: FAIL because component does not exist.

- [ ] **Step 3: Implement compact read-only status component**

Use the existing PaperPanel API helper and styles. Render stable rows:

```tsx
<section className="agent-runtime-status" aria-label="Agent运行状态">
  <header><Bot size={16} /><strong>Agent Runtime</strong><StatusBadge status={runtime.status} /></header>
  <dl>
    <div><dt>当前任务</dt><dd>{runtime.current_task?.summary || '--'}</dd></div>
    <div><dt>最近工具</dt><dd>{runtime.last_tool?.name || '--'}</dd></div>
    <div><dt>验证结果</dt><dd>{runtime.verification?.status || '--'}</dd></div>
    <div><dt>执行权限</dt><dd>{runtime.mode || 'observe'}</dd></div>
    <div><dt>阻塞原因</dt><dd>{runtime.block_reason || '无'}</dd></div>
  </dl>
</section>
```

Do not add start/stop/order controls here. Existing scheduling drawer remains the control surface.

- [ ] **Step 4: Integrate into PaperPanel and run contracts**

Run: `node scripts/agent_runtime_frontend_contract_tests.mjs; npm run build`

Expected: contract passes and Vite build succeeds. Existing chunk-size warning is acceptable.

- [ ] **Step 5: Browser verification**

With the existing frontend running, open Strategy Run / Paper Trading and verify at desktop width:

- Runtime status renders without nested cards.
- Long task/block text wraps and does not overlap.
- Observe/shadow mode is visually distinguishable from paper-guarded.
- No console errors occur.
- No prompt, API key or hidden reasoning is visible.

## Task 12: Documentation, Full Regression and Safe Cutover Drill

**Files:**
- Modify: `README.md`
- Modify if needed: `docs/superpowers/specs/2026-07-25-trading-agent-runtime-design.md`

- [ ] **Step 1: Update README**

Document:

```markdown
### Agent Runtime

- Default: disabled, mode `observe`, execution owner `legacy_ai_loop`.
- Observe/shadow never trigger paper orders.
- `paper_guarded` requires `execution_owner=agent_runtime` and an audit event.
- Current and historical runs are queryable by run ID; model identity is pinned per run.
- Recovery never repeats a side-effect tool without idempotency/reconciliation evidence.
```

Include CLI status and read-only API examples. Do not document a live mode as available.

- [ ] **Step 2: Run complete P0/P1 Python suite**

Run:

```powershell
python -m pytest tests/test_agent_contracts.py tests/test_agent_evidence.py tests/test_agent_verifiers.py tests/test_agent_decision_adapter.py tests/test_agent_p0_integration.py tests/test_agent_store.py tests/test_agent_tool_registry.py tests/test_agent_policies.py tests/test_agent_runtime.py tests/test_agent_recovery.py tests/test_agent_scheduler_cutover.py -q
python -m pytest tests/test_decision_reader_binding.py tests/test_paper_order_router.py tests/test_execution_fill_risk.py tests/test_audit_replay_isolation.py tests/test_llm_unified_management.py tests/test_llm_provider_switching.py -q
python -m pytest scripts/valuation_engine_tests.py -q
```

Expected: all pass.

- [ ] **Step 3: Run Node and build regression suite**

Run:

```powershell
node scripts/agent_runtime_api_contract_tests.mjs
node scripts/agent_runtime_frontend_contract_tests.mjs
node scripts/ai_autonomous_cycle_contract_tests.mjs
node scripts/llm_provider_switch_contract_tests.mjs
node scripts/security_regression_tests.mjs
node scripts/valuation_api_contract_tests.mjs
npm run build
```

Expected: all contracts pass and build succeeds.

- [ ] **Step 4: Perform an observe-only runtime drill**

Set only:

```json
{
  "agent_runtime_enabled": true,
  "agent_runtime_mode": "observe",
  "execution_owner": "legacy_ai_loop"
}
```

Run one Agent cycle. Verify:

- one `agent_runs` row and ordered events are created;
- provider/model match the model registry at Run creation;
- tool calls are read/research only;
- no `paper_trade_once` or `paper_rebalance_once` call exists;
- paper order/trade counts do not change;
- replay reconstructs the Run.

- [ ] **Step 5: Perform a shadow recovery drill**

In a test database, stop the test runtime after a completed read-only tool call, then resume it. Verify the tool call count remains one and the Run completes. Repeat with a seeded unknown paper side-effect status and verify the Run becomes blocked.

- [ ] **Step 6: Do not switch paper execution ownership yet**

P1 delivery ends with `execution_owner=legacy_ai_loop` unless the user separately approves a paper-guarded cutover after reviewing observe/shadow evidence. Record this exact final state in the delivery report.

- [ ] **Step 7: Changed-file checkpoint**

Run:

```powershell
Get-ChildItem quant\agent,tests\test_agent*.py,scripts\agent_runner.py,components\AgentRuntimeStatus.tsx | Select-Object FullName,Length
rg -n "agent_runtime_enabled|agent_runtime_mode|execution_owner" scripts server components README.md
rg -n "live_side_effect|LiveBrokerAdapter" ai_tools.json quant\agent scripts\agent_runner.py
```

Expected: the first two scans show planned files and flags; the final scan shows no registered live tool and no Agent Runtime call to `LiveBrokerAdapter`.

## Design Coverage Check

| Design requirement | Implementation coverage |
|---|---|
| Strict contracts, evidence, semantic rejection and non-trading fallback | P0 Tasks 1-7 |
| Target objective is advisory and cannot pressure sizing | P0 Task 5; P1 Task 4 |
| Durable Run, ordered events, checkpoints and model pinning | P1 Tasks 1, 4 and 5 |
| Typed tools, permission modes and no live tool | P1 Tasks 2, 3 and 6 |
| Bounded FSM, iteration/tool budgets and fail-closed behavior | P1 Tasks 4-6 |
| Idempotency, crash recovery and unknown side-effect blocking | P1 Task 6 |
| Single execution owner and reversible observe/shadow rollout | P1 Tasks 3, 8, 9 and 12 |
| v2 decision provenance with v1 paper compatibility | P0 Task 6; P1 Task 9 |
| Paper execution reconciliation without conflating Agent and paper run IDs | P1 Task 9 |
| Read-only status, run history and replay | P1 Tasks 7, 10 and 11 |
| No online self-modification and no autonomous live trading | Preconditions and P1 Task 12 |

P2-P4 evaluation windows, broker connectivity, approval tokens and any live-trading capability remain intentionally outside these implementation plans.

# Trading Agent P0 Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fail closed on malformed, semantically incomplete, stale, or unsupported AI output before any proposal can become an execution-eligible paper decision.

**Architecture:** Add a dependency-free `quant.agent` contract and verifier layer beside the existing `quant.ai` decision contract. Keep `ai_decision.v1` and the paper trader stable; operator and portfolio outputs gain evidence and `execution_eligible`, and the existing verifier consumes the new checks before preserving trade permission.

**Tech Stack:** Python 3.14 standard library, SQLite cache, pytest, existing React/Vite contract tests.

---

## Workspace Constraint

This workspace has no valid `.git` directory. Do not initialize Git. Replace each commit checkpoint with the exact test command and changed-file review listed in the task.

## File Map

Create:

```text
quant/agent/__init__.py           Public P0 contract/verifier exports
quant/agent/contracts.py          Planner, evidence and execution-eligibility contracts
quant/agent/evidence.py           Canonical evidence hashing and bounded locators
quant/agent/verifiers.py          Deterministic semantic/evidence verification
quant/agent/decision.py           ai_decision.v2 builder and v1 compatibility adapter
tests/test_agent_contracts.py
tests/test_agent_evidence.py
tests/test_agent_verifiers.py
tests/test_agent_decision_adapter.py
tests/test_agent_p0_integration.py
```

Modify:

```text
scripts/ai_operator.py
scripts/ai_portfolio_planner.py
scripts/ai_loop.py
scripts/ai_verifier.py
quant/ai/contracts.py
README.md
```

## Task 1: Agent Contract Primitives

**Files:**
- Create: `quant/agent/__init__.py`
- Create: `quant/agent/contracts.py`
- Test: `tests/test_agent_contracts.py`

- [ ] **Step 1: Write failing contract tests**

```python
import pytest

from quant.agent.contracts import ContractError, validate_planner_output


def test_planner_output_requires_evidence_before_deciding():
    with pytest.raises(ContractError, match="evidence_refs"):
        validate_planner_output({
            "goal": "生成目标组合",
            "status": "ready_to_decide",
            "tasks": [],
            "next_tool": None,
            "evidence_refs": [],
            "summary": "可以交易",
        })


def test_blocked_planner_output_cannot_request_tool():
    with pytest.raises(ContractError, match="blocked.*next_tool"):
        validate_planner_output({
            "goal": "检查数据",
            "status": "blocked",
            "tasks": [],
            "next_tool": {"name": "refresh_data", "arguments": {}},
            "evidence_refs": [],
            "summary": "数据不可用",
        })


def test_need_tool_requires_registered_shape():
    result = validate_planner_output({
        "goal": "选股",
        "status": "need_tool",
        "tasks": [{"id": "task-1", "status": "pending", "summary": "运行选股"}],
        "next_tool": {"name": "run_stock_screener", "arguments": {"top_n": 20}},
        "evidence_refs": [],
        "summary": "需要选股观察",
    })
    assert result["next_tool"]["name"] == "run_stock_screener"
```

- [ ] **Step 2: Run the tests and verify import failure**

Run: `python -m pytest tests/test_agent_contracts.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'quant.agent'`.

- [ ] **Step 3: Implement strict planner validation**

```python
# quant/agent/contracts.py
from __future__ import annotations

import copy
from typing import Any

PLANNER_STATUSES = {"need_tool", "ready_to_decide", "blocked"}


class ContractError(ValueError):
    pass


def _text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def validate_planner_output(raw: dict | None) -> dict:
    if not isinstance(raw, dict):
        raise ContractError("planner output must be object")
    out = copy.deepcopy(raw)
    out["goal"] = _text(out.get("goal"), 240)
    out["status"] = _text(out.get("status"), 32)
    out["summary"] = _text(out.get("summary"), 800)
    out["tasks"] = out.get("tasks") if isinstance(out.get("tasks"), list) else []
    out["evidence_refs"] = [
        _text(value, 128) for value in (out.get("evidence_refs") or []) if _text(value, 128)
    ]
    if not out["goal"] or not out["summary"]:
        raise ContractError("goal and summary are required")
    if out["status"] not in PLANNER_STATUSES:
        raise ContractError("invalid planner status")
    tool = out.get("next_tool")
    if out["status"] == "need_tool":
        if not isinstance(tool, dict) or not _text(tool.get("name"), 80):
            raise ContractError("need_tool requires next_tool")
        out["next_tool"] = {
            "name": _text(tool.get("name"), 80),
            "arguments": tool.get("arguments") if isinstance(tool.get("arguments"), dict) else {},
        }
    elif tool:
        raise ContractError(f"{out['status']} cannot include next_tool")
    else:
        out["next_tool"] = None
    if out["status"] == "ready_to_decide" and not out["evidence_refs"]:
        raise ContractError("ready_to_decide requires evidence_refs")
    return out
```

Export `ContractError` and `validate_planner_output` from `quant/agent/__init__.py`.

- [ ] **Step 4: Run the focused tests**

Run: `python -m pytest tests/test_agent_contracts.py -q`

Expected: `3 passed`.

- [ ] **Step 5: Checkpoint**

Run: `Get-Content quant\agent\contracts.py; python -m pytest tests/test_agent_contracts.py -q`

Expected: contract file contains no trading or cache imports; all tests pass.

## Task 2: Canonical Evidence Records

**Files:**
- Create: `quant/agent/evidence.py`
- Modify: `quant/agent/__init__.py`
- Test: `tests/test_agent_evidence.py`

- [ ] **Step 1: Write failing evidence tests**

```python
from quant.agent.evidence import build_evidence, validate_evidence


def test_evidence_hash_is_stable_for_key_order():
    first = build_evidence("market", "sqlite:daily_summary", "2026-07-25T14:30:00+08:00", {"b": 2, "a": 1})
    second = build_evidence("market", "sqlite:daily_summary", "2026-07-25T14:30:00+08:00", {"a": 1, "b": 2})
    assert first["content_sha256"] == second["content_sha256"]
    assert first["evidence_id"] == second["evidence_id"]


def test_evidence_locator_rejects_paths_and_secrets():
    record = build_evidence(
        "financial",
        "sqlite:financials",
        "2026-07-25T14:30:00+08:00",
        {"roe": 0.16},
        locator={"cache_key": "fin:300450", "file_path": "C:/secret", "token": "abc"},
    )
    assert record["locator"] == {"cache_key": "fin:300450"}


def test_validate_evidence_detects_tampering():
    record = build_evidence("risk", "cache:risk", "2026-07-25T14:30:00+08:00", {"policy": "normal"})
    record["content"] = {"policy": "no_new_position"}
    result = validate_evidence(record)
    assert result["valid"] is False
    assert "hash" in result["errors"]
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_agent_evidence.py -q`

Expected: FAIL because `quant.agent.evidence` does not exist.

- [ ] **Step 3: Implement evidence hashing and validation**

```python
# quant/agent/evidence.py
from __future__ import annotations

import hashlib
import json
from datetime import datetime

ALLOWED_KINDS = {"market", "financial", "announcement", "factor", "strategy", "risk", "position", "tool_result"}
ALLOWED_LOCATORS = {"cache_key", "table", "record_id", "endpoint_action"}


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def build_evidence(kind: str, source: str, as_of: str, content, *, freshness: str = "fresh", summary: str = "", locator: dict | None = None) -> dict:
    digest = hashlib.sha256(_canonical(content).encode("utf-8")).hexdigest()
    safe_locator = {key: str(value)[:240] for key, value in (locator or {}).items() if key in ALLOWED_LOCATORS}
    return {
        "evidence_id": f"ev-{digest[:16]}",
        "kind": kind,
        "source": str(source)[:160],
        "as_of": str(as_of),
        "content_sha256": digest,
        "freshness": freshness,
        "summary": str(summary or "")[:300],
        "locator": safe_locator,
        "content": content,
    }


def validate_evidence(record: dict) -> dict:
    errors = []
    if record.get("kind") not in ALLOWED_KINDS:
        errors.append("kind")
    try:
        datetime.fromisoformat(str(record.get("as_of", "")).replace("Z", "+00:00"))
    except ValueError:
        errors.append("as_of")
    expected = hashlib.sha256(_canonical(record.get("content")).encode("utf-8")).hexdigest()
    if expected != record.get("content_sha256"):
        errors.append("hash")
    if record.get("evidence_id") != f"ev-{expected[:16]}":
        errors.append("evidence_id")
    return {"valid": not errors, "errors": errors, "record": record}
```

- [ ] **Step 4: Run evidence tests**

Run: `python -m pytest tests/test_agent_evidence.py -q`

Expected: `3 passed`.

- [ ] **Step 5: Checkpoint**

Run: `python -m pytest tests/test_agent_contracts.py tests/test_agent_evidence.py -q`

Expected: `6 passed`.

## Task 3: Deterministic Semantic and Evidence Verifiers

**Files:**
- Create: `quant/agent/verifiers.py`
- Modify: `quant/agent/__init__.py`
- Test: `tests/test_agent_verifiers.py`

- [ ] **Step 1: Write failing semantic tests using the observed bad output class**

```python
from quant.agent.verifiers import verify_evidence_refs, verify_semantics


def test_semantic_verifier_rejects_prompt_repetition():
    result = verify_semantics({
        "summary": "我们被问到：你是A股量化模拟盘系统的AI总控 Operator。JSON schema如下",
        "actions": [{"tool": "evaluate_factors"}],
        "trade_policy": "normal",
    })
    assert result["status"] == "fail"
    assert "prompt_repetition" in result["reason_codes"]


def test_semantic_verifier_rejects_trade_without_completed_answer():
    result = verify_semantics({
        "summary": "需要继续分析，暂时无法给出结论",
        "paper_trade_allowed": True,
        "trade_policy": "normal",
        "actions": [],
    })
    assert result["status"] == "fail"
    assert "incomplete_answer" in result["reason_codes"]


def test_evidence_verifier_requires_market_position_risk_and_strategy():
    evidence = {
        "ev-market": {"kind": "market", "freshness": "fresh"},
        "ev-risk": {"kind": "risk", "freshness": "fresh"},
    }
    result = verify_evidence_refs(["ev-market", "ev-risk"], evidence, execution_eligible=True)
    assert result["status"] == "fail"
    assert set(result["missing_kinds"]) == {"position", "strategy"}
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_agent_verifiers.py -q`

Expected: FAIL because verifier functions are missing.

- [ ] **Step 3: Implement deterministic verifier results**

```python
# quant/agent/verifiers.py
from __future__ import annotations

PROMPT_MARKERS = ("我们被问到", "你是A股量化模拟盘系统", "JSON schema如下", "不要输出推理过程")
INCOMPLETE_MARKERS = ("需要继续分析", "无法给出结论", "信息不足，稍后", "作为一个AI")
REQUIRED_TRADE_EVIDENCE = {"market", "position", "risk", "strategy"}


def _result(name: str, reasons: list[str], **extra) -> dict:
    return {"name": name, "status": "fail" if reasons else "pass", "reason_codes": reasons, **extra}


def verify_semantics(payload: dict) -> dict:
    text = " ".join(str(payload.get(key) or "") for key in ("summary", "reason", "objective_note"))
    reasons = []
    if any(marker in text for marker in PROMPT_MARKERS):
        reasons.append("prompt_repetition")
    if any(marker in text for marker in INCOMPLETE_MARKERS):
        reasons.append("incomplete_answer")
    if payload.get("paper_trade_allowed") and payload.get("trade_policy") != "normal":
        reasons.append("trade_permission_policy_conflict")
    return _result("semantic", reasons)


def verify_evidence_refs(refs: list[str], evidence_by_id: dict, *, execution_eligible: bool) -> dict:
    missing_refs = [ref for ref in refs if ref not in evidence_by_id]
    kinds = {evidence_by_id[ref].get("kind") for ref in refs if ref in evidence_by_id}
    stale_refs = [ref for ref in refs if evidence_by_id.get(ref, {}).get("freshness") in {"stale", "unknown"}]
    missing_kinds = sorted(REQUIRED_TRADE_EVIDENCE - kinds) if execution_eligible else []
    reasons = []
    if missing_refs:
        reasons.append("missing_evidence_ref")
    if stale_refs and execution_eligible:
        reasons.append("stale_evidence")
    if missing_kinds:
        reasons.append("missing_required_evidence")
    return _result("evidence", reasons, missing_refs=missing_refs, stale_refs=stale_refs, missing_kinds=missing_kinds)
```

- [ ] **Step 4: Run verifier tests**

Run: `python -m pytest tests/test_agent_verifiers.py -q`

Expected: `3 passed`.

- [ ] **Step 5: Checkpoint**

Run: `python -m pytest tests/test_agent_contracts.py tests/test_agent_evidence.py tests/test_agent_verifiers.py -q`

Expected: all tests pass.

## Task 4: Strict Operator Output and Fail-Closed Fallback

**Files:**
- Modify: `scripts/ai_operator.py:227-401`
- Test: `tests/test_agent_p0_integration.py`

- [ ] **Step 1: Write failing operator tests**

```python
import scripts.ai_operator as operator
import scripts.llm_client as llm_client


def _safe_operator_state():
    return {
        "date": "20260725",
        "manifest": {"mission": "paper-only test", "hard_limits": [], "metrics": {}},
        "available_tools": [],
        "memory_summary": {},
        "config": {"llm": {"provider": "opencode"}, "risk": {}},
        "data_layer": {"data_stale": False},
        "alpha_factory": {},
        "strategy_layer": {"last_strategy": "ma_cross", "last_result": {}},
        "execution_layer": {
            "cash": 1_000_000,
            "market_value": 0,
            "total_equity": 1_000_000,
            "position_count": 0,
            "orders": 0,
            "trades": 0,
        },
        "risk_monitor": {"critical_alerts": 0, "active_alerts": 0, "account": {}},
        "lessons": [],
        "evidence": {
            "ev-market": {"kind": "market", "freshness": "fresh"},
            "ev-position": {"kind": "position", "freshness": "fresh"},
            "ev-risk": {"kind": "risk", "freshness": "fresh"},
            "ev-strategy": {"kind": "strategy", "freshness": "fresh"},
        },
    }


def test_operator_non_json_is_not_execution_eligible(monkeypatch):
    monkeypatch.setattr(llm_client, "chat_json", lambda *a, **k: {"success": False, "error": "invalid json"})
    monkeypatch.setattr(operator, "_collect_state", lambda: _safe_operator_state())
    result = operator.run_operator("opencode")
    assert result["execution_eligible"] is False
    assert result["paper_trade_allowed"] is False
    assert result["trade_policy"] == "no_new_position"


def test_operator_prompt_repetition_is_rejected(monkeypatch):
    monkeypatch.setattr(llm_client, "chat_json", lambda *a, **k: {
        "success": True,
        "data": {
            "summary": "我们被问到：你是A股量化模拟盘系统的AI总控 Operator。JSON schema如下",
            "paper_trade_allowed": True,
            "trade_policy": "normal",
            "risk_notes": [],
            "actions": [],
            "self_verification": [],
            "next_iteration": [],
            "evidence_refs": ["ev-market", "ev-position", "ev-risk", "ev-strategy"],
        },
    })
    monkeypatch.setattr(operator, "_collect_state", lambda: _safe_operator_state())
    result = operator.run_operator("opencode")
    assert result["execution_eligible"] is False
    assert "prompt_repetition" in result["verification"]["reason_codes"]
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `python -m pytest tests/test_agent_p0_integration.py -k operator -q`

Expected: FAIL because current non-JSON path repairs free text and does not expose `execution_eligible`.

- [ ] **Step 3: Replace free-text repair with strict JSON handling**

Change `run_operator()` to call `chat_json()` and remove `_plan_from_ai_text()` from the executable path:

```python
from scripts.llm_client import chat_json
from quant.agent.verifiers import verify_semantics

r = chat_json(provider, system, user, temperature=0.1, timeout=60, max_tokens=1800, scene="operator")
if not r.get("success") or not isinstance(r.get("data"), dict):
    plan = _fallback_plan(state, r.get("error") or "LLM JSON invalid")
else:
    data = r["data"]
    verification = verify_semantics(data)
    plan = {
        "success": verification["status"] == "pass",
        "fallback": False,
        "execution_eligible": verification["status"] == "pass",
        "verification": verification,
        "date": state.get("date"),
        "generated_at": _now(),
        "provider": provider,
        "summary": str(data.get("summary") or "")[:800],
        "paper_trade_allowed": bool(data.get("paper_trade_allowed", False)) and verification["status"] == "pass",
        "trade_policy": data.get("trade_policy", "no_new_position"),
        "risk_notes": data.get("risk_notes", []),
        "actions": _normalize_actions(data.get("actions", [])),
        "self_verification": data.get("self_verification", []),
        "next_iteration": data.get("next_iteration", []),
        "evidence_refs": data.get("evidence_refs", []),
        "state": state,
    }
```

Make `_fallback_plan()` always return:

```python
{
    "success": False,
    "fallback": True,
    "error": reason,
    "date": state.get("date"),
    "generated_at": _now(),
    "provider": state.get("config", {}).get("llm", {}).get("provider", ""),
    "summary": "AI总控输出不可验证，已进入保守模式。",
    "execution_eligible": False,
    "paper_trade_allowed": False,
    "trade_policy": "no_new_position",
    "verification": {"name": "semantic", "status": "fail", "reason_codes": ["llm_fallback"]},
    "risk_notes": [str(reason or "LLM输出无效")[:200]],
    "actions": [],
    "self_verification": [],
    "next_iteration": ["等待下一周期重新生成并验证"],
    "evidence_refs": [],
    "state": state,
}
```

- [ ] **Step 4: Run operator tests**

Run: `python -m pytest tests/test_agent_p0_integration.py -k operator -q`

Expected: operator tests pass.

- [ ] **Step 5: Run existing model and autonomous contracts**

Run: `python -m pytest tests/test_llm_unified_management.py tests/test_llm_provider_switching.py -q; node scripts/ai_autonomous_cycle_contract_tests.mjs`

Expected: Python tests pass and Node contract prints its PASS message. Update source-text assertions only when they conflict with the new fail-closed contract; do not weaken model routing assertions.

## Task 5: Portfolio Fallback Cannot Trade

**Files:**
- Modify: `scripts/ai_portfolio_planner.py:113-267`
- Modify: `scripts/ai_loop.py:357-528`
- Test: `tests/test_agent_p0_integration.py`

- [ ] **Step 1: Add failing portfolio fallback tests**

```python
import scripts.ai_portfolio_planner as planner
from scripts.ai_loop import _portfolio_execution_gate


def test_fallback_portfolio_is_research_only():
    context = {"candidate_pool": ["600519", "300450"], "current_positions": [], "risk": {}}
    result = planner._fallback_plan(context, "model unavailable")
    assert result["execution_eligible"] is False
    assert result["trade_policy"] == "no_new_position"
    assert all(row["action"] != "buy" for row in result["rebalance_plan"])


def test_ai_loop_requires_execution_eligible():
    allowed, reason = _portfolio_execution_gate({
        "success": True,
        "execution_eligible": False,
        "trade_policy": "normal",
        "target_weights": [{"code": "600519", "target_weight": 0.1}],
    })
    assert allowed is False
    assert reason == "portfolio_not_execution_eligible"


def test_target_equity_pressure_is_not_sent_to_portfolio_planner():
    objective = {
        "objective_policy": "advisory_only",
        "target_equity": 100_000_000,
        "required_annualized_return_pct": 900,
        "objective_pressure": "extreme",
        "progress_pct": 1.0,
    }
    context = planner._planner_objective_context(objective)
    assert context == {"objective_policy": "advisory_only"}
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_agent_p0_integration.py -k portfolio -q`

Expected: FAIL because fallback currently produces equal-weight buy targets and the loop does not check eligibility.

- [ ] **Step 3: Make fallback research-only**

In `_fallback_plan()` preserve candidates for display but prohibit executable buys:

```python
return {
    "success": False,
    "fallback": True,
    "execution_eligible": False,
    "trade_policy": "no_new_position",
    "target_weights": [],
    "rebalance_plan": [
        {"code": row["code"], "action": "hold", "target_weight": row.get("current_weight", 0), "reason": "LLM不可用，研究兜底不可交易"}
        for row in context.get("current_positions", [])
    ],
    "research_candidates": context.get("candidate_pool", []),
    "fallback_reason": reason,
}
```

In `ai_loop.py`, add and use the same pure gate in the final policy calculation:

```python
def _portfolio_execution_gate(portfolio: dict | None) -> tuple[bool, str]:
    if portfolio and portfolio.get("execution_eligible") is not True:
        return False, "portfolio_not_execution_eligible"
    return True, ""


portfolio_eligible, portfolio_reason = _portfolio_execution_gate(portfolio)
if not portfolio_eligible:
    final_policy["trade_allowed"] = False
    final_policy["trade_policy"] = "no_new_position"
    final_policy.setdefault("reason_codes", []).append(portfolio_reason)
```

In `ai_portfolio_planner.py`, keep target progress available to the UI but remove return-pressure fields from the model and execution context:

```python
def _planner_objective_context(objective: dict | None) -> dict:
    value = objective or {}
    return {"objective_policy": value.get("objective_policy", "advisory_only")}
```

Call `run_portfolio_committee(provider, candidate_pool=candidate_pool, objective=_planner_objective_context(objective_status), loop_results=results)`. Position sizing continues to use only the unified risk budget, account state and executable market data.

- [ ] **Step 4: Run portfolio and loop tests**

Run: `python -m pytest tests/test_agent_p0_integration.py -k "portfolio or loop" -q`

Expected: all selected tests pass.

- [ ] **Step 5: Run paper execution regression tests**

Run: `python -m pytest tests/test_decision_reader_binding.py tests/test_paper_order_router.py tests/test_execution_fill_risk.py -q`

Expected: all pass; no real or paper order is submitted by tests.

## Task 6: ai_decision.v2 and v1 Compatibility Adapter

**Files:**
- Create: `quant/agent/decision.py`
- Modify: `quant/agent/__init__.py`
- Modify: `quant/ai/contracts.py:69-190`
- Test: `tests/test_agent_decision_adapter.py`

- [ ] **Step 1: Write failing adapter tests**

```python
from datetime import datetime, timedelta

from quant.agent.decision import build_decision_v2, decision_v2_to_v1


def test_v2_research_fallback_maps_to_non_trading_v1():
    v2 = build_decision_v2(
        run_id="agent-1",
        provider="opencode",
        model="deepseek-v4-flash-free",
        execution_eligible=False,
        trade_policy="normal",
        evidence_refs=["ev-market"],
        target_weights=[{"code": "600519", "target_weight": 0.1}],
    )
    v1 = decision_v2_to_v1(v2)
    assert v1["trade_allowed"] is False
    assert v1["trade_policy"] == "no_new_position"
    assert v1["target_weights"] == []


def test_v2_keeps_trace_and_model_identity():
    v2 = build_decision_v2(
        run_id="agent-2",
        provider="opencode",
        model="nemotron-3-ultra-free",
        execution_eligible=True,
        trade_policy="normal",
        evidence_refs=["ev-market", "ev-position", "ev-risk", "ev-strategy"],
        target_weights=[],
    )
    v1 = decision_v2_to_v1(v2)
    assert v1["run_id"] == "agent-2"
    assert v1["model_version"] == "opencode/nemotron-3-ultra-free"
    assert v2["schema_version"] == "ai_decision.v2"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_agent_decision_adapter.py -q`

Expected: FAIL because adapter does not exist.

- [ ] **Step 3: Implement v2 construction and fail-closed v1 mapping**

```python
# quant/agent/decision.py
from __future__ import annotations

from datetime import datetime, timedelta
from quant.ai.contracts import normalize_ai_decision


def build_decision_v2(*, run_id: str, provider: str, model: str, execution_eligible: bool,
                      trade_policy: str, evidence_refs: list[str], target_weights: list[dict],
                      rebalance_plan: list[dict] | None = None, risk_budget: dict | None = None,
                      reason_codes: list[str] | None = None) -> dict:
    now = datetime.now()
    return {
        "schema_version": "ai_decision.v2",
        "run_id": run_id,
        "provider": provider,
        "model": model,
        "prompt_version": "agent.p0.v1",
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "valid_until": (now + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S"),
        "execution_eligible": bool(execution_eligible),
        "trade_policy": trade_policy if execution_eligible else "no_new_position",
        "evidence_refs": list(evidence_refs),
        "target_weights": list(target_weights) if execution_eligible else [],
        "rebalance_plan": list(rebalance_plan or []) if execution_eligible else [],
        "risk_budget": dict(risk_budget or {}),
        "reason_codes": list(reason_codes or []),
    }


def decision_v2_to_v1(value: dict) -> dict:
    eligible = value.get("execution_eligible") is True
    raw = {
        **value,
        "trade_policy": value.get("trade_policy") if eligible else "no_new_position",
        "trade_allowed": eligible and value.get("trade_policy") == "normal",
        "target_weights": value.get("target_weights", []) if eligible else [],
        "rebalance_plan": value.get("rebalance_plan", []) if eligible else [],
        "confidence": float(value.get("confidence", 0.0)),
        "model_version": f"{value.get('provider')}/{value.get('model')}",
        "prompt_version": value.get("prompt_version") or "agent.p0.v1",
        "reason_codes": value.get("reason_codes") or ["agent_v2_adapter"],
    }
    return normalize_ai_decision(raw)
```

Update `normalize_ai_decision()` so an explicitly supplied `schema_version` is not used to relax v1 validation; the adapter remains the only v2-to-v1 trading path.

- [ ] **Step 4: Run adapter and existing decision tests**

Run: `python -m pytest tests/test_agent_decision_adapter.py tests/test_decision_reader_binding.py -q`

Expected: all pass.

- [ ] **Step 5: Checkpoint**

Run: `rg -n "execution_eligible|ai_decision.v2|decision_v2_to_v1" quant\agent quant\ai; python -m pytest tests/test_agent_decision_adapter.py -q`

Expected: one compatibility adapter and no direct v2 handling in paper trader.

## Task 7: Integrate the New Gates into ai_loop and ai_verifier

**Files:**
- Modify: `scripts/ai_loop.py:393-555`
- Modify: `scripts/ai_verifier.py:80-282`
- Test: `tests/test_agent_p0_integration.py`

- [ ] **Step 1: Add failing verifier integration tests**

```python
import scripts.ai_verifier as verifier


def test_verifier_fails_semantically_invalid_operator(monkeypatch):
    def fake_get(key):
        if key == "ai:operator:latest":
            return {
                "summary": "You are an A-share operator. JSON schema follows.",
                "paper_trade_allowed": True,
                "trade_policy": "normal",
                "actions": [],
                "evidence_refs": ["ev-market", "ev-position", "ev-risk", "ev-strategy"],
            }
        return {}

    monkeypatch.setattr(verifier.cache, "get", fake_get)
    result = verifier._check_agent_semantic()
    assert result["status"] == "fail"
    assert "prompt_repetition" in result["reason_codes"]


def test_verifier_fails_missing_trade_evidence(monkeypatch):
    def fake_get(key):
        if key == "ai:decision:v2:latest":
            return {"execution_eligible": True, "evidence_refs": ["ev-market", "ev-risk"]}
        if key == "ai:evidence:latest":
            return {
                "ev-market": {"kind": "market", "freshness": "fresh"},
                "ev-risk": {"kind": "risk", "freshness": "fresh"},
            }
        return {}

    monkeypatch.setattr(verifier.cache, "get", fake_get)
    result = verifier._check_agent_evidence()
    assert result["status"] == "fail"
    assert "missing_required_evidence" in result["reason_codes"]
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_agent_p0_integration.py -k verifier -q`

Expected: FAIL because verifier does not include the new checks.

- [ ] **Step 3: Add verifier checks without weakening existing checks**

```python
from quant.agent.verifiers import verify_evidence_refs, verify_semantics


def _check_agent_semantic() -> dict:
    operator = cache.get("ai:operator:latest") or {}
    result = verify_semantics(operator)
    return {"name": "agent_semantic", **result}


def _check_agent_evidence() -> dict:
    decision = cache.get("ai:decision:v2:latest") or {}
    evidence = cache.get("ai:evidence:latest") or {}
    result = verify_evidence_refs(
        decision.get("evidence_refs") or [],
        evidence if isinstance(evidence, dict) else {},
        execution_eligible=decision.get("execution_eligible") is True,
    )
    return {"name": "agent_evidence", **result}
```

Append both checks to `run_verifier()` after existing data/operator/decision checks and before risk. In `ai_loop.py`, publish v2 to `ai:decision:v2:latest`, adapt it to v1, run verifier, and force both versions to non-trading when verifier fails.

- [ ] **Step 4: Run focused integration tests**

Run: `python -m pytest tests/test_agent_p0_integration.py -q`

Expected: all P0 integration tests pass.

- [ ] **Step 5: Run autonomous, decision and paper regressions**

Run:

```powershell
python -m pytest tests/test_agent_contracts.py tests/test_agent_evidence.py tests/test_agent_verifiers.py tests/test_agent_decision_adapter.py tests/test_agent_p0_integration.py tests/test_decision_reader_binding.py tests/test_paper_order_router.py tests/test_execution_fill_risk.py -q
node scripts/ai_autonomous_cycle_contract_tests.mjs
node scripts/security_regression_tests.mjs
```

Expected: all Python tests pass and both Node scripts report PASS.

## Task 8: P0 Documentation and Full Verification

**Files:**
- Modify: `README.md`
- Modify only if contract assertions require it: `scripts/ai_autonomous_cycle_contract_tests.mjs`

- [ ] **Step 1: Add README operational semantics**

Document these exact points under the AI autonomous section:

```markdown
### Agent P0 failure policy

- Non-JSON, prompt repetition, incomplete answers and missing evidence cannot become execution eligible.
- LLM and equal-weight fallbacks are research-only and force `no_new_position`.
- `ai_decision.v2` is adapted to the existing v1 paper contract only after verification.
- A model switch affects new decisions; historical decisions retain their original model identity.
```

- [ ] **Step 2: Scan for contradictory fallback documentation**

Run: `rg -n "等权|fallback|兜底|非JSON|execution_eligible|ai_decision.v2" README.md docs scripts\ai_*.py`

Expected: no text claims a model failure fallback may automatically buy or rebalance.

- [ ] **Step 3: Run the P0 test suite**

Run:

```powershell
python -m pytest tests/test_agent_contracts.py tests/test_agent_evidence.py tests/test_agent_verifiers.py tests/test_agent_decision_adapter.py tests/test_agent_p0_integration.py -q
python -m pytest tests/test_llm_unified_management.py tests/test_llm_provider_switching.py tests/test_decision_reader_binding.py tests/test_paper_order_router.py tests/test_execution_fill_risk.py -q
python -m pytest scripts/valuation_engine_tests.py -q
node scripts/ai_autonomous_cycle_contract_tests.mjs
node scripts/llm_provider_switch_contract_tests.mjs
node scripts/security_regression_tests.mjs
npm run build
```

Expected: all tests and build pass. The existing Vite chunk-size warning is acceptable; any new warning or failure is not.

- [ ] **Step 4: Run read-only runtime verification**

With the existing API already running, call read-only status actions only:

```powershell
$body = @{action='ai_all_status'} | ConvertTo-Json
$result = Invoke-RestMethod -Uri 'http://127.0.0.1:8880/api/paper' -Method Post -ContentType 'application/json' -Body $body
$result.data.verifier | ConvertTo-Json -Depth 6
```

Expected: status is readable, no order action is called, and new verifier fields appear after the next normal cycle. Do not manually trigger a paper cycle for verification.

- [ ] **Step 5: Changed-file checkpoint**

Run: `Get-ChildItem quant\agent,tests\test_agent*.py | Select-Object FullName,Length; rg -n "execution_eligible" scripts\ai_operator.py scripts\ai_portfolio_planner.py scripts\ai_loop.py scripts\ai_verifier.py README.md`

Expected: changes remain limited to the files listed by this plan.

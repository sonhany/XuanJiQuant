# F5 Experimental Auto Paper Trading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `f4_rejected` 且数据、身份、约束均可信的研究策略自动进入明确标记的 F5 实验模拟通道，生成订单、成交、持仓、权益与对账，同时永久保持实盘权限关闭。

**Architecture:** 在研究域生成绑定当前完整 generation 和 F4 最新稳定锁的 `experimental_research_portfolio`；F5 准入把策略质量与模拟许可拆开，分别支持 `validated_paper` 和 `experimental_paper`。账本持久化执行通道及 F4 证据，API/UI 展示双状态，旧执行入口和实盘权限不改变。

**Tech Stack:** Python 3.11/3.14、SQLite、Node.js ESM、React/TypeScript、pytest、Vite。

---

## File Structure

- Create `quant/strategy/experimental_selection.py`: 派生实验组合并校验 F4 拒绝原因、候选锁和研究代际。
- Create `scripts/generate_experimental_portfolio.py`: 原子发布版本化实验组合和 `latest.json` 指针。
- Create `tests/test_experimental_research_selection.py`: 实验组合身份、幂等和失败关闭测试。
- Modify `scripts/run_daily_research_pipeline.py`: 完整日频 generation 提交后生成或恢复当日实验组合。
- Modify `quant/paper_execution/policy.py`: 增加不可变实验模拟政策。
- Modify `config/f5_paper_execution.json`: 显式启用实验模拟。
- Modify `quant/paper_execution/eligibility.py`: 派生策略质量和执行通道。
- Modify `quant/paper_execution/runtime.py`: 单次加载完整因子 generation 和同身份实验组合。
- Modify `quant/paper_execution/service.py`: 将执行通道和 F4 证据写入账本。
- Modify `quant/paper_execution/ledger.py`: 升级 schema v3 并兼容旧记录。
- Modify `quant/paper_execution/reporting.py`: API 返回双状态和 F4 原因。
- Modify `components/ExecutionPanel.tsx` and `components/PaperPanel.tsx`: 中文展示实验模拟和策略质量。
- Modify `README.md` and `docs/XUANJI_HANDOFF.md`: 固化模块关系、调度和操作说明。

### Task 1: Versioned Experimental Policy

**Files:**
- Modify: `quant/paper_execution/policy.py`
- Modify: `quant/paper_execution/runtime.py`
- Modify: `config/f5_paper_execution.json`
- Test: `tests/test_f5_paper_eligibility.py`
- Test: `tests/test_f5_runtime_publication.py`

- [ ] **Step 1: Write the failing policy tests**

```python
def test_experimental_policy_is_explicit_and_never_grants_live_authority():
    policy = PaperExecutionPolicy(
        enabled=True,
        experimental_paper=ExperimentalPaperPolicy(enabled=True),
    )
    assert policy.experimental_paper.allowed_f4_statuses == ("f4_rejected",)
    assert policy.live_execution_authority is False

def test_experimental_policy_rejects_f4_blocked():
    with pytest.raises(ValueError, match="experimental_f4_status_forbidden"):
        ExperimentalPaperPolicy(enabled=True, allowed_f4_statuses=("f4_blocked",))
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_f5_paper_eligibility.py tests/test_f5_runtime_publication.py -q`

Expected: FAIL because `ExperimentalPaperPolicy` and nested configuration loading do not exist.

- [ ] **Step 3: Implement the immutable nested policy**

```python
@dataclass(frozen=True, slots=True)
class ExperimentalPaperPolicy:
    enabled: bool = False
    policy_version: str = "f5-experimental-paper-v1"
    allowed_f4_statuses: tuple[str] = ("f4_rejected",)
    require_zero_constraint_violations: bool = True
    require_zero_future_data_violations: bool = True

    def __post_init__(self) -> None:
        if not self.policy_version:
            raise ValueError("experimental_policy_version_missing")
        if tuple(self.allowed_f4_statuses) != ("f4_rejected",):
            raise ValueError("experimental_f4_status_forbidden")

@dataclass(frozen=True, slots=True)
class PaperExecutionPolicy:
    version: str = "f5-paper-policy-v1"
    enabled: bool = False
    kill_switch: bool = False
    initial_capital: float = 1_000_000.0
    commission_rate: float = 0.0003
    minimum_commission: float = 5.0
    stamp_tax_rate: float = 0.0005
    transfer_fee_rate: float = 0.00001
    slippage_rate: float = 0.0001
    participation_cap: float = 0.10
    lot_size: int = 100
    execution_mode: str = "paper_daily"
    paper_execution_authority: bool = True
    live_execution_authority: bool = False
    experimental_paper: ExperimentalPaperPolicy = field(default_factory=ExperimentalPaperPolicy)
```

`runtime.load_policy()` must construct `ExperimentalPaperPolicy` from nested JSON before `PaperExecutionPolicy`. Update `config/f5_paper_execution.json` with the exact approved object.

- [ ] **Step 4: Run GREEN**

Run: `python -m pytest tests/test_f5_paper_eligibility.py tests/test_f5_runtime_publication.py -q`

Expected: all selected tests PASS.

### Task 2: Deterministic Experimental Research Portfolio

**Files:**
- Create: `quant/strategy/experimental_selection.py`
- Create: `scripts/generate_experimental_portfolio.py`
- Create: `tests/test_experimental_research_selection.py`
- Modify: `scripts/run_daily_research_pipeline.py`
- Modify: `tests/test_daily_research_pipeline.py`

- [ ] **Step 1: Write failing builder tests**

```python
def test_rejected_factory_builds_bound_experimental_portfolio(fixtures):
    result = build_experimental_selection(
        factor_snapshot=fixtures.factor_snapshot,
        factor_evaluation=fixtures.factor_evaluation,
        f4_latest=fixtures.rejected_f4,
        candidate_spec=fixtures.candidate_spec,
        industry_records=fixtures.industries,
        research_generation_id="generation-v1",
        generated_at="2026-08-20T16:20:00+08:00",
    )
    assert result["selection_status"] == "experimental_research_portfolio"
    assert result["research_generation_id"] == "generation-v1"
    assert result["f4_candidate_id"]
    assert result["f4_candidate_lock_hash"]
    assert result["portfolio_policy_hash"]
    assert result["promotion_state"] == "research_only"
    assert result["execution_authority"] is False

@pytest.mark.parametrize("reason", ["future_data_detected", "portfolio_constraint_failed"])
def test_non_performance_reason_is_forbidden(fixtures, reason):
    f4 = {**fixtures.rejected_f4, "reasons": [reason]}
    with pytest.raises(ResearchSelectionBlocked, match="experimental_f4_reason_forbidden"):
        build_experimental_selection(f4_latest=f4, **fixtures.builder_inputs)
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_experimental_research_selection.py -q`

Expected: collection FAIL because the module and builder do not exist.

- [ ] **Step 3: Implement the governed wrapper**

```python
PERFORMANCE_REASONS = frozenset({
    "positive_excess_window_ratio_below_0_60",
    "after_cost_excess_return_not_positive",
    "sharpe_below_0_80",
    "max_drawdown_below_minus_0_20",
    "double_cost_excess_return_not_positive",
})

def canonical_selection_id(payload: Mapping[str, Any]) -> str:
    identity = dict(payload)
    identity.pop("portfolio_id", None)
    identity.pop("generated_at", None)
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

def build_experimental_selection(
    *,
    factor_snapshot: Mapping[str, Any],
    factor_evaluation: Mapping[str, Any],
    f4_latest: Mapping[str, Any],
    candidate_spec: Mapping[str, Any],
    industry_records: Iterable[Mapping[str, Any]],
    research_generation_id: str,
    generated_at: str,
) -> dict[str, Any]:
    reasons = tuple(str(value) for value in f4_latest.get("reasons") or ())
    if f4_latest.get("status") != "f4_rejected":
        raise ResearchSelectionBlocked("experimental_f4_status_forbidden")
    if not reasons or not set(reasons).issubset(PERFORMANCE_REASONS):
        raise ResearchSelectionBlocked("experimental_f4_reason_forbidden")
    metrics = dict(f4_latest.get("metrics") or {})
    if int(metrics.get("constraint_violation_count") or 0):
        raise ResearchSelectionBlocked("portfolio_constraint_failed")
    if int(metrics.get("future_data_violation_count") or 0):
        raise ResearchSelectionBlocked("future_data_detected")
    payload = build_research_selection(
        factor_snapshot=factor_snapshot,
        factor_evaluation=factor_evaluation,
        f4_latest=f4_latest,
        candidate_spec=candidate_spec,
        industry_records=industry_records,
        generated_at=generated_at,
    )
    payload.update({
        "selection_status": "experimental_research_portfolio",
        "research_generation_id": research_generation_id,
        "experimental_policy_version": "f5-experimental-paper-v1",
        "f4_reasons": list(reasons),
        "warnings": ["F4未通过，仅允许实验模拟，不构成合格策略或实盘信号。"],
    })
    payload["portfolio_id"] = canonical_selection_id(payload)
    return payload
```

The wrapper must reuse `build_research_selection()` so the latest factor fit, selected policy, lock hash and canonical policy hash remain authoritative. No fallback to `PortfolioPolicy()` is allowed for the candidate-factory contract.

- [ ] **Step 4: Implement atomic versioned publication**

`generate_experimental_portfolio.py` resolves one complete research generation and atomically writes:

```text
data/research/experimental_selections/<portfolio_id>/portfolio.json
data/research/experimental_selections/latest.json
```

An identical identity is a no-op; different content under the same identity raises `experimental_selection_identity_collision`.

- [ ] **Step 5: Add the daily post-publication stage**

In both new-publication and no-op/recovery branches invoke:

```python
experimental = runner(
    "generate_experimental_portfolio.py",
    ("--generation-id", str(generation_id)),
    10 * 60,
)
```

It returns `not_applicable` when F4 is validated, but fails the daily pipeline when F4 is rejected and the current experimental portfolio cannot be published.

- [ ] **Step 6: Run GREEN**

Run: `python -m pytest tests/test_experimental_research_selection.py tests/test_daily_research_pipeline.py tests/test_generate_research_portfolio.py tests/test_research_selection.py -q`

Expected: all selected tests PASS; a daily no-op can repair a missing experimental selection without rebuilding factors.

### Task 3: Dual-Lane F5 Eligibility

**Files:**
- Modify: `quant/paper_execution/eligibility.py`
- Modify: `tests/test_f5_paper_eligibility.py`

- [ ] **Step 1: Write RED dual-lane cases**

```python
def test_performance_rejected_strategy_is_experimentally_eligible():
    selection, f4 = _experimental_pair()
    result = _evaluate(selection=selection, f4=f4, policy=_experimental_policy())
    assert result.eligible is True
    assert result.reason_code == "eligible_experimental"
    assert result.evidence["execution_lane"] == "experimental_paper"
    assert result.evidence["strategy_quality_status"] == "unqualified"

def test_blocked_or_unsafe_f4_never_enters_experimental_lane():
    selection, f4 = _experimental_pair()
    f4["status"] = "f4_blocked"
    assert _evaluate(selection=selection, f4=f4, policy=_experimental_policy()).eligible is False
    f4["status"] = "f4_rejected"
    f4["metrics"]["future_data_violation_count"] = 1
    assert _evaluate(selection=selection, f4=f4, policy=_experimental_policy()).reason_code == "future_data_detected"
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_f5_paper_eligibility.py -q`

Expected: rejected evidence still returns `blocked_by_f4`.

- [ ] **Step 3: Implement explicit lane classification**

```python
def _classify_lane(selection, f4_latest, policy):
    if f4_latest.get("status") == "f4_research_candidate":
        return "validated_paper", "validated", "eligible"
    if (
        policy.experimental_paper.enabled
        and f4_latest.get("status") == "f4_rejected"
        and selection.get("selection_status") == "experimental_research_portfolio"
    ):
        return "experimental_paper", "unqualified", "eligible_experimental"
    return "blocked", "invalid", "blocked_by_f4"
```

Run common authority, date, data identity, policy and candidate lock checks for both allowed lanes. Experimental mode bypasses only the five performance reasons.

- [ ] **Step 4: Run GREEN**

Run: `python -m pytest tests/test_f5_paper_eligibility.py -q`

Expected: validated and experimental lanes pass; stale, unsafe and blocked evidence remain rejected.

### Task 4: Runtime Bundle and Auditable Ledger v3

**Files:**
- Modify: `quant/paper_execution/runtime.py`
- Modify: `quant/paper_execution/service.py`
- Modify: `quant/paper_execution/ledger.py`
- Modify: `tests/test_f5_runtime_publication.py`
- Modify: `tests/test_f5_paper_service.py`
- Modify: `tests/test_f5_paper_ledger.py`

- [ ] **Step 1: Write RED runtime and migration tests**

```python
def test_runtime_loads_experimental_selection_only_for_same_generation(tmp_path, monkeypatch):
    bundle = runtime._research_bundle()
    assert bundle["generation_id"] == "generation-v1"
    assert bundle["selection"]["research_generation_id"] == "generation-v1"

def test_old_ledger_migrates_without_rewriting_historical_runs(tmp_path):
    ledger = PaperLedger(_create_v2_fixture(tmp_path))
    old = ledger.list_runs()[0]
    assert old["execution_lane"] == "legacy_unknown"
    assert old["strategy_quality_status"] == "unknown"
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_f5_runtime_publication.py tests/test_f5_paper_service.py tests/test_f5_paper_ledger.py -q`

Expected: missing experimental selection resolution and schema v3 columns.

- [ ] **Step 3: Load one generation plus its linked selection**

```python
if f4_status == "f4_rejected":
    selection = _read_json(EXPERIMENTAL_SELECTION_PATH)
    if selection.get("research_generation_id") != generation_id:
        selection = {}
else:
    selection = _read_json(paths["selection.json"])
```

Do not fall back to the daily diagnostic mirror after a linked experimental selection fails identity validation.

- [ ] **Step 4: Add backward-compatible ledger fields**

Set `SCHEMA_VERSION = 3` and add stable defaults:

```sql
execution_lane TEXT NOT NULL DEFAULT 'legacy_unknown',
strategy_quality_status TEXT NOT NULL DEFAULT 'unknown',
f4_status TEXT,
f4_reasons_json TEXT NOT NULL DEFAULT '[]',
research_generation_id TEXT,
experimental_policy_version TEXT
```

Extend `claim_run()` with `audit_context` and insert these values in the same transaction. Existing rows keep the defaults.
`_public_run()` must decode `f4_reasons_json` into a public `f4_reasons` list and remove the storage-only JSON column.

- [ ] **Step 5: Persist eligibility evidence from the service**

```python
audit_context = {
    "execution_lane": eligibility.evidence.get("execution_lane", "blocked"),
    "strategy_quality_status": eligibility.evidence.get("strategy_quality_status", "invalid"),
    "f4_status": f4_latest.get("status"),
    "f4_reasons": list(f4_latest.get("reasons") or []),
    "research_generation_id": bundle.get("generation_id"),
    "experimental_policy_version": selection.get("experimental_policy_version"),
}
```

Both lanes must keep the same planner, simulator and reconciler and always return `live_execution_authority=False`.

- [ ] **Step 6: Run GREEN and settlement regression**

Run: `python -m pytest tests/test_f5_runtime_publication.py tests/test_f5_paper_service.py tests/test_f5_paper_ledger.py tests/test_f5_paper_simulator.py tests/test_f5_paper_reconciliation.py -q`

Expected: migration, dual-lane preparation, partial fills, rejections and reconciliation PASS.

### Task 5: API and Chinese UI Truthfulness

**Files:**
- Modify: `quant/paper_execution/reporting.py`
- Modify: `tests/test_f5_paper_reporting.py`
- Modify: `scripts/f5_paper_execution_contract_tests.mjs`
- Modify: `scripts/f5_paper_ui_contract_tests.mjs`
- Modify: `components/ExecutionPanel.tsx`
- Modify: `components/PaperPanel.tsx`
- Modify: `components/PaperStrategyConfig.tsx`
- Modify: `lib/workbench-state.mjs`

- [ ] **Step 1: Write RED API and UI contracts**

```python
def test_status_exposes_strategy_quality_and_execution_lane(ledger):
    status = status_projection(ledger)
    assert status["execution_lane"] == "experimental_paper"
    assert status["strategy_quality_status"] == "unqualified"
    assert status["live_execution_authority"] is False
    assert status["f4_reasons"] == ["sharpe_below_0_80"]
```

Node contracts must require `实验模拟自动交易`, `策略质量：未通过F4`, `模拟执行许可`, `实盘权限：未启用`, plus Chinese mappings for all five performance reasons.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_f5_paper_reporting.py -q; node scripts/f5_paper_execution_contract_tests.mjs; node scripts/f5_paper_ui_contract_tests.mjs`

Expected: missing projection fields and labels fail.

- [ ] **Step 3: Implement status projection and UI**

`status_projection()` copies the latest run's lane, quality, F4 status and decoded reasons while deriving paper authority only from authorized run states.

```tsx
<StatusBadge label={lane === 'experimental_paper' ? '实验模拟自动交易' : '验证通过模拟'} />
<div>策略质量：{quality === 'unqualified' ? '未通过F4' : '已通过F4研究门禁'}</div>
<div>模拟执行许可：{authority ? '已授权' : '未授权'}</div>
<div>实盘权限：未启用</div>
```

Remove the empty-state assertion that F4 rejection always requires an empty account. Keep orders, fills, positions, equity and reconciliation visible.

- [ ] **Step 4: Run GREEN**

Run the Python reporting test and both Node contracts again; all must PASS.

### Task 6: Integration, Documentation, and Operational Closure

**Files:**
- Modify: `README.md`
- Modify: `docs/XUANJI_HANDOFF.md`
- Modify: `scripts/web_verify.mjs`
- Modify: `scripts/ui_verify.mjs`

- [ ] **Step 1: Add integration assertions**

Verify `paper_execution_capability=true`, experimental fixture lane/quality, conditional paper authority, `live_execution_authority=false`, and permanent `arbitrary_order_action_forbidden` for user-supplied orders.

- [ ] **Step 2: Update handoff docs**

Document this exact chain:

```text
16:20 data/factor generation
  -> current F4 stable winner identity
  -> experimental_research_portfolio
16:40 F5 run_due
  -> experimental_paper or validated_paper
  -> orders/fills/positions/equity/reconciliation
  -> live_execution_authority=false
```

F4 rejection remains an adverse quality fact; experimental fills are not proof of profitability.

- [ ] **Step 3: Run focused and full regression**

```powershell
python -m pytest tests/test_experimental_research_selection.py tests/test_f5_paper_eligibility.py tests/test_f5_runtime_publication.py tests/test_f5_paper_service.py tests/test_f5_paper_ledger.py tests/test_f5_paper_reporting.py -q
python -m pytest -q
npm run test:contracts
npx tsc --noEmit
npm run build
node scripts/web_verify.mjs
node scripts/ui_verify.mjs
```

Expected: focused tests and complete Python suite pass; all Node contracts, TypeScript, Vite, Web and UI verification pass without browser console warnings or errors.

- [ ] **Step 4: Reload only XuanJiQuant services if required**

Resolve listeners on 8880/8888, verify command lines contain `C:\Users\HYSHEN\XuanJiQuant`, and restart only the process that must reload. Never touch the frozen backup.

- [ ] **Step 5: Verify live API and next governed cycle**

Query `/api/paper-execution` status. If the current complete selection date equals the expected market date, invoke parameter-free `run_due` once and verify an experimental prepared run with planned orders. Otherwise keep the scheduler for the first cycle after 16:20 and report the exact next eligible time; do not backdate or fabricate market data.

Final evidence must include run ID, intended session, execution lane, strategy quality, order/fill counts, reconciliation state and `live_execution_authority=false`.

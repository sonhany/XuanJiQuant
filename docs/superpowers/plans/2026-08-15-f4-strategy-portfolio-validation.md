# F4 Strategy and Portfolio Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, point-in-time, walk-forward strategy and portfolio validation pipeline whose highest authority is `f4_research_candidate` with `research_only` and no execution authority.

**Architecture:** Add small pure Python modules for identity/contracts, windows, dataset gates, portfolio construction, simulation, metrics and the F4 gate. A single orchestration script writes immutable validation evidence and a latest read-only projection; the weekly research scheduler calls it, while the Strategy API/UI only displays the projection. The legacy 2026-08-07 scan remains an audit artifact but is removed from current-state authority.

**Tech Stack:** Python 3.14, dataclasses, pandas/numpy, pytest, SQLite research ledger, Node contract tests, React 19/TypeScript/Vite.

---

## File structure

- Create `quant/strategy/f4_contracts.py`: stable status/error codes, validation identity and JSON-safe contracts.
- Create `quant/strategy/walk_forward.py`: deterministic trading-calendar window builder.
- Create `quant/strategy/f4_dataset.py`: manifest/quality/PIT/benchmark gates and factor eligibility.
- Create `quant/strategy/portfolio.py`: score-to-weight construction and hard constraints.
- Create `quant/strategy/portfolio_backtest.py`: research-only target-weight simulation.
- Create `quant/strategy/f4_metrics.py`: per-window/aggregate/stress metrics.
- Create `quant/strategy/f4_gate.py`: the only F4 status decision.
- Create `scripts/validate_strategy_portfolios.py`: end-to-end orchestration and atomic evidence writes.
- Modify `scripts/research_training_scheduler.py`: replace legacy scan handler with F4 validation.
- Modify `scripts/strategy_runner.py`: expose only F4 latest evidence for `market_scan`; remove proxy success.
- Modify `components/StrategyPanel.tsx`: display F4 truth and research boundary.
- Modify `README.md`, `docs/XUANJI_HANDOFF.md`, `docs/XUANJI_SYSTEM_WORKFLOW_MAP.md`: handoff and workflow.

The workspace has no `.git`; each task uses a passing targeted test as its checkpoint instead of a commit.

### Task 1: Contracts and deterministic identity

**Files:**
- Create: `tests/test_f4_contracts.py`
- Create: `quant/strategy/f4_contracts.py`

- [ ] **Step 1: Write the failing contract tests**

```python
from quant.strategy.f4_contracts import (
    F4Blocked,
    F4ValidationIdentity,
    authority_fields,
)


def test_identity_changes_when_any_governance_version_changes():
    base = dict(
        market_date="2026-08-14",
        factor_snapshot_id="snap-1",
        factor_data_version="factor-v1",
        factor_universe_version="universe-v1",
        pit_dataset_version="pit-v1",
        benchmark_version="benchmark-v1",
        candidate_spec_version="candidate-v1",
        portfolio_policy_version="portfolio-v1",
        cost_model_version="cost-v1",
        gate_version="f4-gate-v1",
    )
    first = F4ValidationIdentity(**base)
    second = F4ValidationIdentity(**{**base, "benchmark_version": "benchmark-v2"})
    assert first.validation_id != second.validation_id
    assert first.to_dict()["validation_id"] == first.validation_id


def test_authority_is_always_research_only():
    assert authority_fields() == {
        "promotion_state": "research_only",
        "execution_authority": False,
    }


def test_blocked_error_has_stable_reason_code():
    error = F4Blocked("pit_manifest_incomplete", "status=incomplete")
    assert error.reason_code == "pit_manifest_incomplete"
    assert str(error) == "pit_manifest_incomplete: status=incomplete"
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_f4_contracts.py -q`

Expected: collection fails with `ModuleNotFoundError: quant.strategy.f4_contracts`.

- [ ] **Step 3: Implement the minimal contracts**

Implement frozen dataclasses, canonical sorted JSON hashing with SHA-256, `F4Blocked`, and these status constants:

```python
F4_BUILDING = "f4_building"
F4_BLOCKED = "f4_blocked"
F4_REJECTED = "f4_rejected"
F4_RESEARCH_CANDIDATE = "f4_research_candidate"


def authority_fields() -> dict[str, object]:
    return {"promotion_state": "research_only", "execution_authority": False}
```

`F4ValidationIdentity.to_dict()` must include all source fields plus `validation_id` and authority fields.

- [ ] **Step 4: Run GREEN**

Run: `python -m pytest tests/test_f4_contracts.py -q`

Expected: `3 passed`.

### Task 2: Purged walk-forward windows

**Files:**
- Create: `tests/test_f4_walk_forward.py`
- Create: `quant/strategy/walk_forward.py`

- [ ] **Step 1: Write failing window tests**

```python
import pandas as pd
import pytest

from quant.strategy.f4_contracts import F4Blocked
from quant.strategy.walk_forward import build_f4_windows


def test_windows_are_non_overlapping_and_apply_purge_and_embargo():
    calendar = pd.bdate_range("2020-01-01", periods=1300)
    windows = build_f4_windows(calendar)
    assert len(windows) >= 4
    for window in windows:
        assert window.train_end < window.valid_start
        assert window.valid_end < window.test_start
        assert window.purge_bars == 20
        assert window.embargo_bars == 5
        assert len(window.train_dates) == 504
        assert len(window.valid_dates) == 126
        assert len(window.test_dates) == 126


def test_insufficient_calendar_fails_closed():
    with pytest.raises(F4Blocked, match="walk_forward_window_insufficient"):
        build_f4_windows(pd.bdate_range("2024-01-01", periods=800))
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_f4_walk_forward.py -q`

Expected: import failure for `quant.strategy.walk_forward`.

- [ ] **Step 3: Implement `F4Window` and `build_f4_windows`**

Use exactly 504 training, 126 validation, 126 test, 20 purge, 5 embargo, 126 step and minimum four complete windows. Normalize and sort the calendar, reject duplicates and return immutable tuples of timestamps.

- [ ] **Step 4: Run GREEN**

Run: `python -m pytest tests/test_f4_walk_forward.py -q`

Expected: `2 passed`.

### Task 3: PIT dataset and benchmark gates

**Files:**
- Create: `tests/test_f4_dataset.py`
- Create: `quant/strategy/f4_dataset.py`

- [ ] **Step 1: Write failing gate tests**

```python
import json
import pytest

from quant.strategy.f4_contracts import F4Blocked
from quant.strategy.f4_dataset import load_f4_dataset_refs, eligible_factor_names


def test_incomplete_manifest_blocks_real_validation(tmp_path):
    manifest = tmp_path / "manifest.json"
    quality = tmp_path / "quality.json"
    manifest.write_text(json.dumps({"status": "incomplete", "dataset_version": "pit-v1"}))
    quality.write_text(json.dumps({"status": "passed", "dataset_version": "pit-v1"}))
    with pytest.raises(F4Blocked, match="pit_manifest_incomplete"):
        load_f4_dataset_refs(manifest, quality, None, None)


def test_fundamental_factors_require_announcement_date_pit():
    factors, excluded = eligible_factor_names(
        ["ret_20", "roe"],
        financial_pit_passed=False,
    )
    assert factors == ["ret_20"]
    assert excluded == {"roe": "financial_pit_missing"}
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_f4_dataset.py -q`

Expected: import failure for `quant.strategy.f4_dataset`.

- [ ] **Step 3: Implement dataset gates**

`load_f4_dataset_refs()` must validate complete manifest, passed quality with the same dataset version, effective-dated PIT masks, at least 95% effective-dated industry coverage and a versioned benchmark. It must never substitute the current universe or an equal-weight benchmark. `eligible_factor_names()` must allow technical/price-volume factors and exclude the 11 fundamental factors unless the financial announcement-date PIT gate passes.

- [ ] **Step 4: Run GREEN**

Run: `python -m pytest tests/test_f4_dataset.py -q`

Expected: targeted tests pass.

### Task 4: Portfolio construction constraints

**Files:**
- Create: `tests/test_f4_portfolio.py`
- Create: `quant/strategy/portfolio.py`

- [ ] **Step 1: Write failing portfolio tests**

```python
from quant.strategy.portfolio import PortfolioPolicy, build_target_weights


def test_top20_weights_obey_single_name_and_industry_caps():
    rows = [
        {"code": f"{i:06d}", "score": 100 - i, "industry": f"I{i % 5}"}
        for i in range(30)
    ]
    result = build_target_weights(rows, PortfolioPolicy())
    assert len(result.weights) == 20
    assert max(result.weights.values()) <= 0.10
    totals = {}
    for row in rows:
        totals[row["industry"]] = totals.get(row["industry"], 0) + result.weights.get(row["code"], 0)
    assert max(totals.values()) <= 0.25 + 1e-12
    assert sum(result.weights.values()) <= 1.0


def test_unknown_industry_does_not_bypass_cap():
    rows = [{"code": f"{i:06d}", "score": 100 - i, "industry": ""} for i in range(30)]
    result = build_target_weights(rows, PortfolioPolicy())
    assert sum(result.weights.values()) <= 0.25 + 1e-12
    assert result.cash_weight >= 0.75 - 1e-12
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_f4_portfolio.py -q`

Expected: import failure for `quant.strategy.portfolio`.

- [ ] **Step 3: Implement deterministic construction**

Create immutable `PortfolioPolicy(top_k=20, rebalance_bars=5, max_name_weight=0.10, max_industry_weight=0.25, lot_size=100, adv_participation=0.10)` and `PortfolioTarget(weights, cash_weight, exclusions)`. Sort by descending score then code, assign equal weights, cap industry/unknown buckets and leave unallocated weight as cash.

- [ ] **Step 4: Run GREEN**

Run: `python -m pytest tests/test_f4_portfolio.py -q`

Expected: targeted tests pass.

### Task 5: Research-only portfolio simulator

**Files:**
- Create: `tests/test_f4_portfolio_backtest.py`
- Create: `quant/strategy/portfolio_backtest.py`

- [ ] **Step 1: Write failing execution-rule tests**

```python
from quant.strategy.portfolio_backtest import CostModel, simulate_rebalance


def test_rebalance_applies_lot_and_adv_capacity():
    result = simulate_rebalance(
        cash=1_000_000,
        positions={},
        target_weights={"600000": 0.10},
        market={"600000": {"price": 10.0, "adv20_shares": 5000, "tradable": True}},
        cost=CostModel(),
    )
    assert result.fills[0].quantity == 500
    assert result.capacity_rejected_notional == 95_000
    assert result.fills[0].quantity % 100 == 0


def test_limit_up_and_suspension_reject_buys():
    result = simulate_rebalance(
        cash=100_000,
        positions={},
        target_weights={"600000": 0.10, "600001": 0.10},
        market={
            "600000": {"price": 10, "adv20_shares": 100000, "tradable": True, "limit_up": True},
            "600001": {"price": 10, "adv20_shares": 100000, "tradable": False},
        },
        cost=CostModel(),
    )
    assert result.fills == ()
    assert result.reject_counts == {"limit_up": 1, "suspended": 1}
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_f4_portfolio_backtest.py -q`

Expected: import failure for `quant.strategy.portfolio_backtest`.

- [ ] **Step 3: Implement the minimal simulator**

Add frozen `CostModel` and result/fill dataclasses. Calculate desired target notional from equity, enforce tradability, PIT status, T+1 sells, limit locks, 100-share buys and 10% ADV participation. Apply commission, minimum commission, sell stamp tax, transfer fee and slippage. Rejected quantity remains cash and is never auto-filled later.

- [ ] **Step 4: Run GREEN**

Run: `python -m pytest tests/test_f4_portfolio_backtest.py -q`

Expected: targeted tests pass.

### Task 6: Metrics, cost stress and the single F4 gate

**Files:**
- Create: `tests/test_f4_gate.py`
- Create: `quant/strategy/f4_metrics.py`
- Create: `quant/strategy/f4_gate.py`

- [ ] **Step 1: Write failing gate tests**

```python
from quant.strategy.f4_gate import evaluate_f4_gate


def passing_metrics():
    return {
        "window_count": 5,
        "positive_excess_window_ratio": 0.60,
        "after_cost_excess_return": 0.08,
        "sharpe": 0.90,
        "max_drawdown": -0.15,
        "double_cost_excess_return": 0.01,
        "constraint_violation_count": 0,
        "future_data_violation_count": 0,
    }


def test_all_hard_metrics_produce_research_candidate_without_authority():
    result = evaluate_f4_gate(passing_metrics(), blocked_reasons=[])
    assert result["status"] == "f4_research_candidate"
    assert result["promotion_state"] == "research_only"
    assert result["execution_authority"] is False


def test_data_failure_is_blocked_and_metric_failure_is_rejected():
    assert evaluate_f4_gate(passing_metrics(), ["pit_manifest_incomplete"])["status"] == "f4_blocked"
    weak = {**passing_metrics(), "sharpe": 0.79}
    result = evaluate_f4_gate(weak, [])
    assert result["status"] == "f4_rejected"
    assert "sharpe_below_0_80" in result["reasons"]
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_f4_gate.py -q`

Expected: import failure for `quant.strategy.f4_gate`.

- [ ] **Step 3: Implement metrics and `f4_gate_v1`**

Metrics must compare aligned portfolio and benchmark returns, calculate excess, annualized return/volatility, Sharpe, information ratio, max drawdown, Calmar, positive-window ratio, turnover, cash, costs, capacity and reject counts. `evaluate_f4_gate()` applies exactly the approved thresholds and always appends authority fields.

- [ ] **Step 4: Run GREEN**

Run: `python -m pytest tests/test_f4_gate.py -q`

Expected: targeted tests pass.

### Task 7: Orchestration, immutable evidence and current blocking truth

**Files:**
- Create: `tests/test_f4_validation_pipeline.py`
- Create: `scripts/validate_strategy_portfolios.py`

- [ ] **Step 1: Write failing pipeline tests**

```python
import json

from scripts.validate_strategy_portfolios import run_validation, write_validation_evidence


def test_current_incomplete_manifest_returns_blocked(tmp_path):
    result = run_validation(
        project_root=tmp_path,
        manifest={"status": "incomplete", "dataset_version": "pit-v1"},
        quality={},
    )
    assert result["status"] == "f4_blocked"
    assert result["reasons"] == ["pit_manifest_incomplete"]
    assert result["execution_authority"] is False


def test_evidence_is_immutable_and_latest_is_a_projection(tmp_path):
    result = {"validation_id": "abc", "status": "f4_blocked", "reasons": ["pit_manifest_incomplete"]}
    paths = write_validation_evidence(tmp_path, result)
    assert json.loads(paths.report.read_text())["validation_id"] == "abc"
    assert json.loads(paths.latest.read_text())["validation_id"] == "abc"
    assert paths.report != paths.latest
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_f4_validation_pipeline.py -q`

Expected: import failure or missing functions.

- [ ] **Step 3: Implement orchestration**

The script must load the current F3 evidence, six-year manifest/quality/PIT/benchmark, build identity, stop at the first data gate with stable reasons, and only run windows when inputs pass. Write `data/research/f4/<validation_id>/validation_report.json` once and atomically replace `data/research/f4/latest.json`. Re-running an existing identity must parse and validate the immutable report before returning `no_op=true`.

- [ ] **Step 4: Run GREEN and execute current real gate**

Run:

```powershell
python -m pytest tests/test_f4_validation_pipeline.py -q
python scripts/validate_strategy_portfolios.py --once
```

Expected: tests pass; real result is `f4_blocked` with `pit_manifest_incomplete`, not a candidate.

### Task 8: Scheduler and read-only Strategy API truth

**Files:**
- Modify: `tests/test_research_training_scheduler.py`
- Create: `tests/test_strategy_f4_projection.py`
- Modify: `scripts/research_training_scheduler.py`
- Modify: `scripts/strategy_runner.py`

- [ ] **Step 1: Add failing scheduler and projection tests**

Assert `_strategy_handler` invokes `validate_strategy_portfolios.py --once`, never `scan_strategies.py`. Assert `action_market_scan()` reads `data/research/f4/latest.json`; when absent it returns `success=false`, `status=f4_blocked`, `reason_code=f4_evidence_missing`. Assert it never builds `snapshot_proxy` or labels legacy scan current.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_research_training_scheduler.py tests/test_strategy_f4_projection.py -q`

Expected: assertions fail against the current legacy handler/proxy.

- [ ] **Step 3: Replace the authority path**

Update the scheduler handler to call the F4 script. Replace `action_market_scan()` with strict latest-projection loading and integrity checks. Keep manual `run/backtest` actions as `diagnostic_only=true`, `promotion_state=research_only`, `execution_authority=false`.

- [ ] **Step 4: Run GREEN**

Run: `python -m pytest tests/test_research_training_scheduler.py tests/test_strategy_f4_projection.py -q`

Expected: targeted tests pass.

### Task 9: F4 UI truth and Chinese status mapping

**Files:**
- Create: `scripts/f4_strategy_ui_contract_tests.mjs`
- Modify: `components/StrategyPanel.tsx`

- [ ] **Step 1: Write failing Node contract**

The contract reads `StrategyPanel.tsx` and asserts it contains `F4 策略与组合验证`, `仅供研究`, `样本外窗口`, `数据门禁`, `成本压力`, `容量约束`, `f4_blocked`, and no `snapshot_proxy` success wording. It also asserts the panel does not contain production promotion or automatic trade actions.

- [ ] **Step 2: Run RED**

Run: `node scripts/f4_strategy_ui_contract_tests.mjs`

Expected: failure because the current panel presents legacy market scan.

- [ ] **Step 3: Implement the read-only F4 view**

Keep the existing Strategy page shell but replace the market-scan summary with status, versions, block/reject reasons, walk-forward table, portfolio/benchmark metrics, cost stress, capacity and the research-only warning. Manual backtest tabs remain visibly diagnostic and cannot be merged into F4 ranking.

- [ ] **Step 4: Run GREEN and frontend compile**

Run:

```powershell
node scripts/f4_strategy_ui_contract_tests.mjs
npx tsc --noEmit
npm run build
```

Expected: contract, TypeScript and Vite build pass.

### Task 10: Handoff, workflow and full verification

**Files:**
- Modify: `README.md`
- Modify: `docs/XUANJI_HANDOFF.md`
- Modify: `docs/XUANJI_SYSTEM_WORKFLOW_MAP.md`

- [ ] **Step 1: Update authoritative documentation**

Document F3→F4 inputs, modules, identity, schedule, statuses, artifacts, API/UI authority, current `pit_manifest_incomplete` truth and the distinction between implementation completion and real validation passage. Mark the 2026-08-07 scan as historical evidence only.

- [ ] **Step 2: Run focused Python verification**

Run:

```powershell
python -m pytest tests/test_f4_contracts.py tests/test_f4_walk_forward.py tests/test_f4_dataset.py tests/test_f4_portfolio.py tests/test_f4_portfolio_backtest.py tests/test_f4_gate.py tests/test_f4_validation_pipeline.py tests/test_research_training_scheduler.py tests/test_strategy_f4_projection.py -q
```

Expected: all focused tests pass.

- [ ] **Step 3: Run full project verification**

Run:

```powershell
python -m pytest -q
npm run test:contracts
npx tsc --noEmit
npm run build
node scripts/web_verify.mjs
node scripts/ui_verify.mjs
```

Expected: zero failures. If live Web/API verification is unavailable, report it as an unverified external/runtime item rather than claiming success.

- [ ] **Step 4: Verify real F4 state and authority boundary**

Read `data/research/f4/latest.json` and confirm:

```json
{
  "status": "f4_blocked",
  "promotion_state": "research_only",
  "execution_authority": false
}
```

The reason must remain `pit_manifest_incomplete` while the real manifest is incomplete. Do not change the manifest, quality result or gate threshold as part of F4 implementation.

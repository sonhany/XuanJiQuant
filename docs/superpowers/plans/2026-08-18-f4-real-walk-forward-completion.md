# F4 Real Walk-Forward Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the approved F4方案A by producing real purged walk-forward factor fitting, long-only portfolio backtests, cost/capacity stress evidence, and the single F4 gate from the six-year PIT dataset.

**Architecture:** Add one focused real-data module that converts versioned adjusted bars, daily PIT masks, effective-dated industries, and the versioned benchmark into a cached factor panel. It computes daily cross-sectional rank IC once, freezes train-only factor directions/weights per window, simulates validation/test portfolios with next-day execution and A-share constraints, and returns complete window/stress evidence to the existing immutable validation orchestrator. The pipeline remains research-only and cannot write positions, orders, trades, paper configuration, or execution authority.

**Tech Stack:** Python 3.14, pandas, numpy, PyArrow Parquet, pytest, existing F4 contracts/portfolio simulator/gate, React/TypeScript/Vite read-only projection.

---

## File structure

- Create `quant/strategy/f4_real_pipeline.py`: PIT panel cache, daily rank IC, train-only fitting, next-day portfolio simulation, and per-window evidence.
- Create `tests/test_f4_real_pipeline.py`: synthetic PIT integration tests for no-lookahead fitting, factor selection, backtest constraints, and cost stress.
- Modify `quant/strategy/f4_gate.py`: version the completed real gate implementation without changing approved thresholds.
- Modify `scripts/validate_strategy_portfolios.py`: invoke the real pipeline, write all approved evidence files, and preserve immutable/no-op semantics.
- Modify `tests/test_f4_validation_pipeline.py`: assert real pipeline orchestration and complete evidence layout.
- Modify `components/StrategyPanel.tsx` and its Node contract only if new evidence fields are not already rendered.
- Modify `README.md`, `docs/XUANJI_HANDOFF.md`, and `docs/XUANJI_SYSTEM_WORKFLOW_MAP.md`: replace the placeholder-input status with the verified real F4 result.

The workspace has no `.git`; each green targeted test and immutable artifact hash is the checkpoint.

### Task 1: Versioned PIT factor panel

**Files:**
- Create: `tests/test_f4_real_pipeline.py`
- Create: `quant/strategy/f4_real_pipeline.py`

- [ ] **Step 1: Write failing panel tests**

```python
def test_panel_uses_only_pit_rows_and_effective_industry(tmp_path):
    paths = write_synthetic_f4_inputs(tmp_path, periods=900, symbols=24)
    panel = build_or_load_factor_panel(paths, force=True)
    assert panel["date"].max() == paths.end_date
    assert panel.loc[panel["date"] < "2023-01-01", "industry"].eq("old").all()
    assert panel.loc[panel["date"] >= "2023-01-01", "industry"].eq("new").all()
    assert panel.query("tradable == False")["pit_tradable"].eq(False).all()


def test_panel_cache_identity_binds_dataset_and_factor_registry(tmp_path):
    paths = write_synthetic_f4_inputs(tmp_path, periods=900, symbols=24)
    first = build_or_load_factor_panel(paths, force=True)
    second = build_or_load_factor_panel(paths, force=False)
    assert first.attrs["panel_id"] == second.attrs["panel_id"]
    assert first.attrs["dataset_version"] == paths.dataset_version
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_f4_real_pipeline.py -q`

Expected: collection fails because `quant.strategy.f4_real_pipeline` does not exist.

- [ ] **Step 3: Implement the panel contract**

Implement these public contracts:

```python
@dataclass(frozen=True, slots=True)
class F4InputPaths:
    dataset_root: Path
    manifest_path: Path
    industry_path: Path
    benchmark_path: Path
    cache_root: Path
    dataset_version: str
    manifest_hash: str
    end_date: str


def build_or_load_factor_panel(paths: F4InputPaths, *, force: bool = False) -> pd.DataFrame:
    """Return only adjusted PIT bars at or before end_date with 47 technical/price-volume factors."""
```

Read `adjusted/*.json`; require matching `data_version`; retain OHLCV/amount, PIT flags, shifted 20-day ADV, and only `TECHNICAL_FACTORS + PRICE_VOLUME_FACTORS`. Map industry by the latest `effective_from <= date`, otherwise `industry_unknown`. Persist a Snappy Parquet panel plus metadata JSON under `data/research/f4/cache/<panel_id>/`; use atomic replacement and reject cache identity drift.

- [ ] **Step 4: Run GREEN**

Run: `python -m pytest tests/test_f4_real_pipeline.py -q`

Expected: panel tests pass.

### Task 2: Train-only rank IC fitting and frozen window configuration

**Files:**
- Modify: `tests/test_f4_real_pipeline.py`
- Modify: `quant/strategy/f4_real_pipeline.py`

- [ ] **Step 1: Add failing no-lookahead tests**

```python
def test_window_fit_uses_train_dates_only_and_freezes_validation_and_test():
    panel, window = synthetic_predictive_panel()
    fit = fit_window_factors(panel, window)
    assert 3 <= len(fit.factors) <= 10
    assert fit.fit_end == str(window.train_end.date())
    mutated = panel.copy()
    mutated.loc[mutated.date.isin(window.test_dates), fit.factors] *= -1000
    assert fit_window_factors(mutated, window) == fit


def test_training_with_fewer_than_three_eligible_factors_is_rejected():
    panel, window = synthetic_predictive_panel(predictive_factors=2)
    with pytest.raises(F4Blocked, match="train_factor_insufficient"):
        fit_window_factors(panel, window)
```

- [ ] **Step 2: Run RED and observe missing behavior**

Run: `python -m pytest tests/test_f4_real_pipeline.py -q`

Expected: failures for missing `fit_window_factors`.

- [ ] **Step 3: Implement daily IC and fit**

```python
@dataclass(frozen=True, slots=True)
class WindowFactorFit:
    window_id: str
    factors: tuple[str, ...]
    directions: dict[str, int]
    weights: dict[str, float]
    median_rank_ic: dict[str, float]
    direction_consistency: dict[str, float]
    fit_end: str
```

Calculate 5-day forward returns only where the outcome date remains inside the train segment. For every train date compute cross-sectional Spearman rank IC, then require `abs(median_ic) >= 0.02` and sign consistency `>= 0.60`; sort by absolute median IC then factor name, keep 3–10, normalize absolute IC weights, and freeze the result for validation/test.

- [ ] **Step 4: Run GREEN**

Run: `python -m pytest tests/test_f4_real_pipeline.py -q`

Expected: fitting tests pass.

### Task 3: Next-day portfolio backtest and cost stress

**Files:**
- Modify: `tests/test_f4_real_pipeline.py`
- Modify: `quant/strategy/f4_real_pipeline.py`

- [ ] **Step 1: Add failing simulation tests**

```python
def test_test_window_uses_previous_day_signal_and_reports_constraints():
    panel, benchmark, window, fit = synthetic_backtest_inputs()
    result = simulate_f4_window(panel, benchmark, window, fit, cost_multiplier=1.0)
    assert result["signal_lag_bars"] == 1
    assert result["rebalance_bars"] == 5
    assert result["max_name_weight"] <= 0.10 + 1e-12
    assert result["max_industry_weight"] <= 0.25 + 1e-12
    assert result["future_data_violation_count"] == 0


def test_cost_stress_runs_exactly_one_one_point_five_and_two_times():
    evidence = run_f4_windows(*synthetic_pipeline_inputs())
    assert sorted(evidence["stress_metrics"]) == ["1.0", "1.5", "2.0"]
    assert evidence["double_cost_excess_return"] == evidence["stress_metrics"]["2.0"]["excess_return"]
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_f4_real_pipeline.py -q`

Expected: failures for missing simulation/evidence fields.

- [ ] **Step 3: Implement simulation**

Use the prior trading day's frozen-factor cross-sectional percentile scores, execute at the next trading day's open every five bars, and mark equity at close. Reuse `build_target_weights()` and `simulate_rebalance()`; pass current-day PIT/limit/suspension flags, previous-day `adv20_shares`, and T+1 sellable quantities. Run identical signals at 1.0/1.5/2.0 cost multipliers. Return validation and test metrics, curves, turnover, cash, costs, capacity rejects, reject counts, and constraint/future-data violation counters.

- [ ] **Step 4: Run GREEN**

Run: `python -m pytest tests/test_f4_real_pipeline.py tests/test_f4_portfolio.py tests/test_f4_portfolio_backtest.py -q`

Expected: all targeted portfolio tests pass.

### Task 4: Real orchestration and immutable evidence

**Files:**
- Modify: `tests/test_f4_validation_pipeline.py`
- Modify: `quant/strategy/f4_gate.py`
- Modify: `scripts/validate_strategy_portfolios.py`

- [ ] **Step 1: Add failing orchestration tests**

```python
def test_complete_inputs_run_real_windows_without_injected_metrics(tmp_path, monkeypatch):
    monkeypatch.setattr(validator, "run_real_f4_pipeline", fake_passing_real_pipeline)
    result = validator.run_validation(project_root=complete_fixture(tmp_path))
    assert result["status"] == "f4_research_candidate"
    assert result["window_count"] >= 4
    assert result["execution_authority"] is False


def test_evidence_directory_contains_all_approved_files(tmp_path):
    paths = write_validation_evidence(tmp_path, passing_result_with_windows())
    names = {path.name for path in paths.report.parent.iterdir()}
    assert names == {
        "identity.json", "window_definitions.json", "candidate_spec.json",
        "portfolio_policy.json", "cost_model.json", "window_metrics.json",
        "aggregate_metrics.json", "gate_result.json", "validation_report.json",
    }
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_f4_validation_pipeline.py -q`

Expected: orchestration still returns `f4_validation_inputs_missing` and evidence files are absent.

- [ ] **Step 3: Connect the real pipeline**

Bump `GATE_VERSION` from placeholder `f4-gate-v2` to completed `f4-gate-v3` without changing thresholds, ensuring a new immutable `validation_id`. When data gates pass and no explicit test metrics are injected, call `run_real_f4_pipeline()`. Aggregate base and 2x metrics, pass them to `evaluate_f4_gate()`, include window/stress evidence in the report, and atomically write the nine approved evidence files. Re-running the same identity validates all file hashes before returning `no_op=true`.

- [ ] **Step 4: Run GREEN**

Run: `python -m pytest tests/test_f4_validation_pipeline.py tests/test_f4_gate.py tests/test_strategy_f4_projection.py -q`

Expected: targeted pipeline/gate/projection tests pass.

### Task 5: Execute the real six-year validation

**Files:**
- Runtime outputs: `data/research/f4/cache/<panel_id>/`
- Runtime outputs: `data/research/f4/<validation_id>/`
- Runtime projection: `data/research/f4/latest.json`

- [ ] **Step 1: Run the real pipeline once**

Run: `python scripts/validate_strategy_portfolios.py --once`

Expected: at least four real walk-forward windows are present. The result is honestly either `f4_rejected` or `f4_research_candidate`; data/integrity failures remain `f4_blocked` with a stable reason code.

- [ ] **Step 2: Verify the evidence identity and authority**

Read the nine evidence files and confirm their `validation_id`, factor/PIT/industry/benchmark versions, window count, stress multipliers, and hashes agree. Confirm `promotion_state=research_only` and `execution_authority=false` everywhere.

- [ ] **Step 3: Verify API truth**

Run `POST /api/strategy {"action":"market_scan"}` and confirm it projects the same validation ID/status/window metrics without reading the legacy scan.

### Task 6: UI, handoff, and full regression

**Files:**
- Modify if required: `components/StrategyPanel.tsx`
- Modify: `README.md`
- Modify: `docs/XUANJI_HANDOFF.md`
- Modify: `docs/XUANJI_SYSTEM_WORKFLOW_MAP.md`

- [ ] **Step 1: Update read-only F4 presentation and documentation**

Display real windows, aggregate metrics, 1.0/1.5/2.0 cost stress, capacity/reject statistics and the final gate reasons. Preserve “仅供研究，不构成目标持仓或交易信号”. Document the actual result as timestamped evidence, not a permanent claim.

- [ ] **Step 2: Run focused verification**

Run:

```powershell
python -m pytest tests/test_f4_real_pipeline.py tests/test_f4_validation_pipeline.py tests/test_f4_walk_forward.py tests/test_f4_portfolio.py tests/test_f4_portfolio_backtest.py tests/test_f4_gate.py tests/test_strategy_f4_projection.py tests/test_research_training_scheduler.py -q
```

Expected: zero failures.

- [ ] **Step 3: Run full verification**

Run:

```powershell
python -m pytest -q
npm run test:contracts
npx tsc --noEmit
npm run build
node scripts/web_verify.mjs
node scripts/ui_verify.mjs
```

Expected: zero failures. Browser console inspection must also show no warning/error on the F4 strategy page.


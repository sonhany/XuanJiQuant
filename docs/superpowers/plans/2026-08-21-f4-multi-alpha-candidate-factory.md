# F4 Multi-Alpha Candidate Factory v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build 24 pre-registered, reproducible Alpha/strategy candidates and rerun the complete six-year purged out-of-sample F4 validation without lowering gates or granting execution authority.

**Architecture:** Introduce a versioned Alpha contract, separate deterministic-rule and Qlib adapters, and feed both through the existing per-window nested validation/atomic-lock/test pipeline. Publish v2 evidence under a separate authoritative directory, preserve v1 history, and expose family-level diagnostics through the existing read-only strategy API and page.

**Tech Stack:** Python 3, pandas, NumPy, Qlib/MLflow, pytest, React 19, TypeScript, Node contract tests, Vite, Playwright verification.

---

## Execution constraints

- Work only in `C:\Users\HYSHEN\XuanJiQuant`.
- Do not read, start, test, write, or modify `C:\Users\HYSHEN\AlphaCouncil2-AI`.
- Keep `f4-gate-v4` thresholds unchanged.
- Every v2 artifact must contain `promotion_state=research_only` and `execution_authority=false`.
- Do not initialize Git. This directory currently has no `.git`, so each task ends with a verification checkpoint instead of a commit. Preserve an exact changed-file and test-evidence list in the final report.
- Do not run the full six-year validation until Tasks 1–9 and the full regression in Task 10 pass.
- A final `f4_rejected_exhausted` is a valid research outcome. It must not be altered by changing formulas or gates after viewing test results.

## File structure

### New Python modules

- `quant/strategy/f4_alpha_contracts.py` — immutable v2 Alpha/candidate schemas, validation, canonical identity, 24-candidate registry.
- `quant/strategy/f4_alpha_rules.py` — rule feature derivation, cross-sectional preprocessing, fixed-family scoring, train-only ensemble fitting.
- `quant/strategy/f4_qlib_adapter.py` — window-scoped Qlib training/prediction adapter, artifact hashing, coverage and finite-value checks.
- `quant/strategy/f4_v2_publication.py` — v2 evidence schemas, cross-file integrity validation, idempotent atomic publication and resolver.

### Existing Python modules to modify

- `quant/strategy/f4_candidate_factory.py` — retain v1 compatibility; add version-agnostic nested selection hooks and v2 lock fields.
- `quant/strategy/f4_real_pipeline.py` — orchestrate candidate-specific fit/score, stable winner artifacts, test isolation and family diagnostics.
- `quant/strategy/research_selection.py` — accept verified v1/v2 identities without weakening policy/lock checks.
- `quant/paper_execution/eligibility.py` — recognize v2 identity and continue exact F4/selection/policy binding.
- `scripts/validate_strategy_portfolios.py` — route v2 pipeline, write the latest projection only after complete publication.
- `scripts/strategy_runner.py` — validate and project v2 family evidence through read-only `market_scan`.

### Frontend and documentation

- `components/StrategyPanel.tsx` — show v2 family coverage, window winners, cost stress and gate reasons.
- `scripts/f4_strategy_ui_contract_tests.mjs` — lock Chinese truth labels and research-only wording.
- `README.md` — replace active six-candidate description with v2 architecture while preserving dated v1 audit facts.
- `docs/XUANJI_HANDOFF.md` — document module ownership, version compatibility, schedule and evidence paths.

### New tests

- `tests/test_f4_alpha_registry_v2.py`
- `tests/test_f4_alpha_rules_v2.py`
- `tests/test_f4_alpha_ensembles_v2.py`
- `tests/test_f4_qlib_adapter_v2.py`
- `tests/test_f4_pipeline_v2.py`
- `tests/test_f4_v2_publication.py`

## Task 1: Immutable v2 Alpha and candidate registry

**Files:**
- Create: `quant/strategy/f4_alpha_contracts.py`
- Create: `tests/test_f4_alpha_registry_v2.py`
- Modify: `quant/strategy/f4_candidate_factory.py:14-58`

- [ ] **Step 1: Write failing registry tests**

Add tests that assert the registry is bounded, unique, safe and free of unverified fundamental inputs:

```python
from dataclasses import replace

import pytest

from quant.strategy.f4_alpha_contracts import (
    FACTORY_VERSION_V2,
    build_v2_candidate_registry,
)


def test_v2_registry_has_six_families_and_twenty_four_unique_candidates():
    registry = build_v2_candidate_registry()
    assert len(registry) == 24
    assert {item.family for item in registry} == {
        "momentum", "reversal", "defensive", "liquidity", "ensemble", "qlib"
    }
    assert {family: sum(item.family == family for item in registry) for family in {
        "momentum", "reversal", "defensive", "liquidity", "ensemble", "qlib"
    }} == {
        "momentum": 4, "reversal": 4, "defensive": 4,
        "liquidity": 4, "ensemble": 4, "qlib": 4,
    }
    assert len({item.candidate_id for item in registry}) == 24
    assert all(item.version == FACTORY_VERSION_V2 for item in registry)


def test_candidate_identity_covers_alpha_and_portfolio_policy():
    candidate = build_v2_candidate_registry()[0]
    changed_alpha = replace(
        candidate,
        alpha_spec=replace(candidate.alpha_spec, label_horizon_bars=10),
    )
    changed_policy = replace(
        candidate,
        portfolio_policy=replace(candidate.portfolio_policy, rebalance_bars=5),
    )
    assert changed_alpha.candidate_id != candidate.candidate_id
    assert changed_policy.candidate_id != candidate.candidate_id


def test_registry_excludes_unverified_fundamental_factors():
    forbidden = {"roe", "roa", "gross_margin", "net_margin", "revenue_growth",
                 "profit_growth", "debt_ratio", "current_ratio",
                 "inventory_turnover", "receivable_turnover", "asset_turnover"}
    used = {
        feature
        for candidate in build_v2_candidate_registry()
        for feature in candidate.alpha_spec.input_features
    }
    assert not (used & forbidden)


def test_unsafe_policy_is_rejected():
    candidate = build_v2_candidate_registry()[0]
    with pytest.raises(ValueError, match="candidate_policy_unsafe"):
        replace(
            candidate,
            portfolio_policy=replace(candidate.portfolio_policy, target_gross_exposure=1.01),
        ).validate()
```

- [ ] **Step 2: Run tests and confirm the red state**

Run:

```powershell
python -m pytest tests/test_f4_alpha_registry_v2.py -q
```

Expected: collection fails with `ModuleNotFoundError: quant.strategy.f4_alpha_contracts`.

- [ ] **Step 3: Implement contracts and the exact registry**

Create frozen dataclasses and canonical hashing:

```python
FACTORY_VERSION_V1 = "f4-nested-candidate-factory-v1"
FACTORY_VERSION_V2 = "f4-multi-alpha-candidate-factory-v2"
SUPPORTED_FACTORY_VERSIONS = frozenset({FACTORY_VERSION_V1, FACTORY_VERSION_V2})


@dataclass(frozen=True, slots=True)
class AlphaSpec:
    alpha_id: str
    family: str
    input_features: tuple[str, ...]
    formula: tuple[tuple[str, float], ...]
    preprocessing: str
    fit_method: str
    label_horizon_bars: int = 5
    minimum_coverage: float = 0.95
    seed: int = 20260821
    handler: str = ""
    model_type: str = ""
    version: str = "f4-alpha-spec-v2"


@dataclass(frozen=True, slots=True)
class F4CandidateV2:
    family: str
    alpha_spec: AlphaSpec
    portfolio_policy: PortfolioPolicy
    version: str = FACTORY_VERSION_V2

    @property
    def candidate_id(self) -> str:
        return canonical_payload_hash(self.payload())

    def validate(self) -> None:
        policy = self.portfolio_policy
        if (
            policy.top_k != 10
            or not 0 < policy.target_gross_exposure <= 0.95
            or not 0 < policy.max_name_weight <= 0.095
            or not 0 < policy.max_industry_weight <= 0.25
            or policy.lot_size != 100
            or not 0 < policy.adv_participation <= 0.10
        ):
            raise ValueError("candidate_policy_unsafe")
```

Define all 24 entries exactly as Sections 6–7 of the approved specification. Represent unary negatives explicitly in `formula`, for example `("-volatility_20", 0.60)`. Represent ratios with the derived feature names created in Task 2: `ret_20_over_volatility_20`, `ret_60_over_volatility_60` and `turnover_5_over_20`. For Q1–Q4 set `formula=()`, `fit_method="qlib_model"`, and the exact handler/model pair.

Keep the existing `FACTORY_VERSION` alias bound to v1 until downstream readers are migrated in Task 8. Export explicit v1/v2 constants immediately so new code never guesses by presence of `factory_run_id`.

- [ ] **Step 4: Run registry tests**

Run:

```powershell
python -m pytest tests/test_f4_alpha_registry_v2.py tests/test_f4_candidate_factory.py -q
```

Expected: all tests pass; existing six-candidate v1 tests remain unchanged.

- [ ] **Step 5: Verification checkpoint**

Run `git rev-parse --is-inside-work-tree`; expected output is the existing fatal non-repository message. Do not initialize Git. Record the two changed files and passing test count.

## Task 2: Rule feature transforms and deterministic cross-sectional preprocessing

**Files:**
- Create: `quant/strategy/f4_alpha_rules.py`
- Create: `tests/test_f4_alpha_rules_v2.py`
- Modify: `quant/strategy/f4_real_pipeline.py:40-44, 93-105, 177-257`

- [ ] **Step 1: Write failing preprocessing tests**

```python
import numpy as np
import pandas as pd

from quant.strategy.f4_alpha_rules import derive_rule_features, preprocess_cross_section


def test_price_scale_features_are_dimensionless():
    frame = pd.DataFrame({
        "close": [10.0], "ema_12": [8.0], "ema_26": [10.0],
        "macd_hist": [0.5], "atr_14": [0.2],
        "boll_upper": [12.0], "boll_lower": [8.0], "boll_mid": [10.0],
    })
    result = derive_rule_features(frame)
    assert result.loc[0, "ema_gap_12"] == 0.25
    assert result.loc[0, "ema_gap_26"] == 0.0
    assert result.loc[0, "macd_hist_norm"] == 0.05
    assert result.loc[0, "atr_14_norm"] == 0.02
    assert result.loc[0, "boll_width"] == 0.4


def test_preprocessing_is_industry_neutral_and_finite():
    frame = pd.DataFrame({
        "instrument": ["A", "B", "C", "D"],
        "industry": ["I1", "I1", "I2", "I2"],
        "ret_20": [1.0, 3.0, 1000.0, 5.0],
    })
    result = preprocess_cross_section(frame, ("ret_20",))
    assert np.isfinite(result["ret_20"]).all()
    assert result.groupby("industry")["ret_20"].mean().round(12).eq(0.5).all()


def test_non_finite_ratio_is_missing_not_zero():
    frame = pd.DataFrame({"ret_20": [0.2], "volatility_20": [0.0]})
    result = derive_rule_features(frame)
    assert np.isnan(result.loc[0, "ret_20_over_volatility_20"])
```

- [ ] **Step 2: Run tests and confirm missing functions**

Run `python -m pytest tests/test_f4_alpha_rules_v2.py -q`.

Expected: import failure for `f4_alpha_rules`.

- [ ] **Step 3: Implement transforms and preprocessing**

Use explicit safe division and per-industry ranks:

```python
def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    denominator = pd.to_numeric(denominator, errors="coerce")
    valid = denominator.abs() > 1e-12
    return pd.to_numeric(numerator, errors="coerce").where(valid).div(denominator.where(valid))


def derive_rule_features(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["ema_gap_12"] = _safe_divide(result["close"], result["ema_12"]) - 1.0
    result["ema_gap_26"] = _safe_divide(result["close"], result["ema_26"]) - 1.0
    result["macd_hist_norm"] = _safe_divide(result["macd_hist"], result["close"])
    result["atr_14_norm"] = _safe_divide(result["atr_14"], result["close"])
    result["boll_width"] = _safe_divide(
        result["boll_upper"] - result["boll_lower"], result["boll_mid"]
    )
    result["ret_20_over_volatility_20"] = _safe_divide(result["ret_20"], result["volatility_20"])
    result["ret_60_over_volatility_60"] = _safe_divide(result["ret_60"], result["volatility_60"])
    result["turnover_5_over_20"] = _safe_divide(result["turnover_5"], result["turnover_20"])
    return result.replace([np.inf, -np.inf], np.nan)
```

Implement five-MAD clipping, industry de-meaning, then within-industry percentile ranking in that exact order. If an industry contains one usable value, retain a neutral rank of `0.5`; do not manufacture cross-industry ordering.

Extend the F4 panel cache identity with the derived-feature schema version and derived feature names. A v1 cache must not be reused as v2.

- [ ] **Step 4: Run focused tests**

Run:

```powershell
python -m pytest tests/test_f4_alpha_rules_v2.py tests/test_f4_real_pipeline.py tests/test_f4_dataset.py -q
```

Expected: all pass, including cache identity rejection tests.

- [ ] **Step 5: Verification checkpoint**

Record the new module, test file and F4 panel identity changes. Confirm no file under `data/research/f4` was written by unit tests outside pytest temporary directories.

## Task 3: Fixed-rule fitting, scoring and ensemble candidates

**Files:**
- Modify: `quant/strategy/f4_alpha_rules.py`
- Create: `tests/test_f4_alpha_ensembles_v2.py`
- Modify: `quant/strategy/f4_real_pipeline.py:260-363`

- [ ] **Step 1: Write failing fit and leakage tests**

```python
import pandas as pd

from quant.strategy.f4_alpha_contracts import build_v2_candidate_registry
from quant.strategy.f4_alpha_rules import fit_rule_alpha, score_rule_alpha


def test_rule_fit_uses_train_rows_only():
    candidate = next(item for item in build_v2_candidate_registry() if item.alpha_spec.alpha_id == "E2")
    train = _panel("2024-01-01", periods=40, reverse_after=None)
    altered_validation = _panel("2024-03-01", periods=10, reverse_after=0)
    first = fit_rule_alpha(candidate, train, window_id="wf-01")
    second = fit_rule_alpha(candidate, train, window_id="wf-01")
    assert first.to_dict() == second.to_dict()
    assert altered_validation["forward_return_5d"].sum() != train["forward_return_5d"].sum()


def test_correlation_pruning_uses_stable_name_tie_break():
    candidate = next(item for item in build_v2_candidate_registry() if item.alpha_spec.alpha_id == "E3")
    fit = fit_rule_alpha(candidate, _perfectly_correlated_training_panel(), window_id="wf-01")
    assert fit.selected_signals == tuple(sorted(fit.selected_signals))
    assert len(fit.selected_signals) < len(fit.input_signals)


def test_rule_score_rejects_coverage_below_ninety_five_percent():
    candidate = next(item for item in build_v2_candidate_registry() if item.alpha_spec.alpha_id == "M1")
    fit = fit_rule_alpha(candidate, _complete_training_panel(), window_id="wf-01")
    with pytest.raises(AlphaUnavailable, match="alpha_score_coverage_below_0_95"):
        score_rule_alpha(candidate, fit, _mostly_missing_cross_section())
```

The helper fixtures must use deterministic in-memory frames with at least 20 instruments per date and explicit expected rankings.

- [ ] **Step 2: Run the new tests and confirm red failures**

Run `python -m pytest tests/test_f4_alpha_ensembles_v2.py -q`.

Expected: missing `fit_rule_alpha`, `score_rule_alpha` and `AlphaUnavailable`.

- [ ] **Step 3: Implement serializable rule fits**

Add an immutable fit artifact:

```python
@dataclass(frozen=True, slots=True)
class RuleAlphaFit:
    candidate_id: str
    alpha_id: str
    window_id: str
    fit_start: str
    fit_end: str
    input_signals: tuple[str, ...]
    selected_signals: tuple[str, ...]
    directions: dict[str, int]
    weights: dict[str, float]
    median_rank_ic: dict[str, float]
    direction_consistency: dict[str, float]
    training_coverage: float
    artifact_hash: str
```

Fixed M/R/D/L candidates keep their formula weights and verify training coverage. E1 uses equal family-sleeve weights; E2 uses normalized shrunken median Rank IC; E3 removes `|rho| >= 0.70` signals and chooses by stability then name; E4 splits the train dates into four chronological subperiods and weights by direction consistency and the worst subperiod Rank IC. All functions receive only the train panel and must not accept validation/test frames.

Replace `_score_cross_section(frame, fit)` with a scorer interface that consumes one immutable candidate fit:

```python
def score_rule_alpha(
    candidate: F4CandidateV2,
    fit: RuleAlphaFit,
    cross_section: pd.DataFrame,
) -> pd.DataFrame:
    if fit.candidate_id != candidate.candidate_id:
        raise AlphaUnavailable("alpha_fit_candidate_identity_mismatch")
    prepared = derive_rule_features(cross_section)
    ranked = preprocess_cross_section(prepared, fit.selected_signals)
    score = pd.Series(0.0, index=ranked.index, dtype=float)
    usable = pd.Series(True, index=ranked.index)
    for name in fit.selected_signals:
        values = pd.to_numeric(ranked[name], errors="coerce")
        usable &= values.notna()
        score += values.fillna(0.0) * fit.directions[name] * fit.weights[name]
    output = ranked.loc[usable, ["instrument", "industry"]].copy()
    output["score"] = score.loc[usable]
    coverage = len(output) / len(ranked) if len(ranked) else 0.0
    if coverage < candidate.alpha_spec.minimum_coverage:
        raise AlphaUnavailable("alpha_score_coverage_below_0_95")
    if not np.isfinite(output["score"]).all():
        raise AlphaUnavailable("alpha_score_non_finite")
    return output.rename(columns={"instrument": "code"})[["code", "industry", "score"]]
```

The implementation must reject candidate/fit identity mismatch, missing inputs, non-finite scores and coverage below 95% with stable reason codes.

- [ ] **Step 4: Run rule and legacy pipeline tests**

Run:

```powershell
python -m pytest tests/test_f4_alpha_rules_v2.py tests/test_f4_alpha_ensembles_v2.py tests/test_f4_real_pipeline.py -q
```

Expected: all pass; legacy v1 helpers remain available until Task 6 migrates orchestration.

- [ ] **Step 5: Verification checkpoint**

Record fit artifact schema and exact reason codes. Confirm no function in `f4_alpha_rules.py` imports validation, gate, paper execution or order modules.

## Task 4: Window-scoped Qlib adapter

**Files:**
- Create: `quant/strategy/f4_qlib_adapter.py`
- Create: `tests/test_f4_qlib_adapter_v2.py`
- Modify: `quant/qlib/workflow_bridge.py:18-50, 186-232`
- Modify: `quant/qlib/workflow_config.py:11-55, 60-108`

- [ ] **Step 1: Write failing adapter tests with a fake runtime**

```python
from pathlib import Path

import pandas as pd
import pytest

from quant.strategy.f4_qlib_adapter import QlibAlphaUnavailable, fit_qlib_window


def test_qlib_window_fits_train_and_does_not_predict_test_before_lock(tmp_path):
    runtime = FakeWindowRuntime()
    artifact = fit_qlib_window(
        candidate=_qlib_candidate("Q1"),
        window=_window(),
        provider_uri=tmp_path / "provider",
        artifact_root=tmp_path / "artifacts",
        runtime=runtime,
    )
    assert runtime.fit_segments == ["train"]
    assert runtime.predicted_segments == ["valid"]
    assert "test" not in runtime.predicted_segments
    assert artifact.validation_prediction_hash


@pytest.mark.parametrize("payload", [
    {"coverage": 0.94, "scores": [1.0]},
    {"coverage": 1.00, "scores": [float("nan")]},
])
def test_invalid_qlib_prediction_fails_without_rule_fallback(tmp_path, payload):
    runtime = FakeWindowRuntime(validation_payload=payload)
    with pytest.raises(QlibAlphaUnavailable):
        fit_qlib_window(
            candidate=_qlib_candidate("Q1"), window=_window(),
            provider_uri=tmp_path / "provider",
            artifact_root=tmp_path / "artifacts", runtime=runtime,
        )
    assert runtime.rule_fallback_calls == 0


def test_test_prediction_requires_verified_lock(tmp_path):
    artifact = _fit_artifact(tmp_path)
    with pytest.raises(QlibAlphaUnavailable, match="qlib_test_lock_invalid"):
        artifact.predict_test(lock={"lock_hash": "forged"})
```

- [ ] **Step 2: Run tests and verify the adapter is absent**

Run `python -m pytest tests/test_f4_qlib_adapter_v2.py -q`.

Expected: module import failure.

- [ ] **Step 3: Add a Qlib window workflow boundary**

Do not reuse `run_workflow()` unchanged because it currently generates signal and portfolio analysis for the configured test segment in one call. Add a window-scoped API that separates fitting from segment prediction:

```python
@dataclass(frozen=True, slots=True)
class WindowWorkflowResult:
    candidate_id: str
    window_id: str
    handler: str
    model_type: str
    seed: int
    config_hash: str
    model_path: Path
    model_sha256: str
    validation_prediction_path: Path
    validation_prediction_sha256: str
    validation_coverage: float


def fit_window_workflow(request: WindowWorkflowRequest, *, runtime=None) -> WindowWorkflowResult:
    dataset = runtime.build_dataset(request.dataset_config)
    model = runtime.build_model(request.model_config)
    model.fit(dataset)
    runtime.save_model(model, request.model_path)
    validation = model.predict(dataset, segment="valid")
    return validate_and_write_validation_prediction(request, model, validation)
```

Add a separate `predict_locked_test(result, lock, runtime=None)` that first verifies `candidate_id`, `window_id`, model SHA-256, Alpha spec hash and lock hash, then predicts only the test segment. Use unique same-directory temporary files plus `os.replace`. JSON/CSV prediction writers must reject NaN and Infinity.

Qlib dependency import failures map to `qlib_dependency_unavailable`; model fit errors map to `qlib_training_failed`; prediction coverage and finite-value errors use distinct stable codes.

- [ ] **Step 4: Run Qlib and workflow regression tests**

Run:

```powershell
python -m pytest tests/test_f4_qlib_adapter_v2.py tests/test_qlib_workflow_bridge.py tests/test_qlib_workflow_config.py tests/test_qlib_artifact_importer.py -q
```

Expected: all pass. Existing weekly Qlib workflow behavior remains unchanged because the new window API is additive.

- [ ] **Step 5: Verification checkpoint**

Confirm tests use a fake runtime and temporary paths; they must not start a real Qlib training job or write `data/qlib`.

## Task 5: Candidate-specific nested validation and durable v2 locks

**Files:**
- Modify: `quant/strategy/f4_candidate_factory.py:60-190`
- Modify: `quant/strategy/f4_real_pipeline.py:352-533, 602-970`
- Create: `tests/test_f4_pipeline_v2.py`
- Modify: `tests/test_f4_candidate_factory.py`

- [ ] **Step 1: Write failing isolation and recovery tests**

```python
def test_v2_pipeline_validates_all_candidates_but_tests_only_locked_winner(tmp_path):
    events = []
    result = run_v2_nested_window(
        window=_window(),
        candidates=_three_candidates(),
        fit_runner=lambda candidate: events.append(("fit", candidate.candidate_id)) or _fit(candidate),
        validation_runner=lambda candidate, fit: events.append(("valid", candidate.candidate_id)) or _metrics(candidate),
        test_runner=lambda candidate, fit, lock: events.append(("test", candidate.candidate_id)) or _test_metrics(),
        stable_lock_root=tmp_path / "locks",
    )
    winner = result["selection_lock"]["candidate_id"]
    assert [event for event in events if event[0] == "test"] == [("test", winner)]
    assert (tmp_path / "locks" / "wf-01.json").is_file()


def test_crash_after_lock_reuses_winner_without_revalidation(tmp_path):
    _write_verified_lock_and_fit(tmp_path)
    calls = []
    run_v2_nested_window(
        window=_window(), candidates=_three_candidates(),
        fit_runner=lambda *_: (_ for _ in ()).throw(AssertionError("fit reran")),
        validation_runner=lambda *_: (_ for _ in ()).throw(AssertionError("validation reran")),
        test_runner=lambda candidate, fit, lock: calls.append(candidate.candidate_id) or _test_metrics(),
        stable_lock_root=tmp_path / "locks",
    )
    assert calls == [_locked_candidate_id(tmp_path)]


def test_later_validation_never_changes_earlier_window_lock(tmp_path):
    first = run_factory_with_windows(tmp_path, later_validation_scale=1.0)
    second = run_factory_with_windows(tmp_path, later_validation_scale=-1000.0)
    assert first["selection_locks"][0] == second["selection_locks"][0]
```

- [ ] **Step 2: Run tests and verify they fail against v1 orchestration**

Run `python -m pytest tests/test_f4_pipeline_v2.py -q`.

Expected: missing `run_v2_nested_window` and v2 lock schema.

- [ ] **Step 3: Implement unified candidate contexts and stable artifacts**

Introduce a serializable context interface:

```python
@dataclass(frozen=True, slots=True)
class CandidateWindowContext:
    window_id: str
    candidate_id: str
    alpha_spec_hash: str
    alpha_fit_path: str
    alpha_fit_hash: str
    model_artifact_path: str | None
    model_artifact_hash: str | None
    validation_score_path: str
    validation_score_hash: str
```

For each window:

1. Fit and validate all available candidates using only train/validation.
2. Write their attempt-local contexts and leaderboard.
3. Select the winner using the fixed ordering.
4. Copy the winner fit/model into `factory-v2/locked-artifacts/<factory_run_id>/<window_id>/` using atomic files.
5. Hash the stable artifacts.
6. Write and reread `factory-v2/locks/<factory_run_id>/<window_id>.json`.
7. Load the winner from stable artifacts and run only its test.

Update `simulate_f4_window()` to receive a `score_loader(signal_date)` callable instead of assuming a single `WindowFactorFit`. The callable returns exactly `code`, `industry`, `score`. Rule and Qlib candidates use the same portfolio simulation after scoring.

The v2 lock must include every field in Section 9 of the approved specification. Recalculate `lock_hash` after removing only `lock_hash`, `promotion_state` and `execution_authority`; no truthiness-only checks.

- [ ] **Step 4: Run nested selection and simulation tests**

Run:

```powershell
python -m pytest tests/test_f4_pipeline_v2.py tests/test_f4_candidate_factory.py tests/test_f4_real_pipeline.py tests/test_f4_portfolio_backtest.py -q
```

Expected: all pass. Assertions prove non-winners have no test event and a recovered lock suppresses fit/validation.

- [ ] **Step 5: Verification checkpoint**

Inspect all new path joins with `Path.resolve()` and `relative_to(expected_root)` tests. Confirm no cleanup path can remove `factory-v2`, `locks`, the project root or a completed generation.

## Task 6: v2 evidence publication, integrity and idempotency

**Files:**
- Create: `quant/strategy/f4_v2_publication.py`
- Create: `tests/test_f4_v2_publication.py`
- Modify: `quant/strategy/f4_real_pipeline.py:635-682, 724-970`
- Modify: `scripts/validate_strategy_portfolios.py:65-224, 256-399`

- [ ] **Step 1: Write failing publication tests**

```python
def test_v2_publication_requires_all_ten_artifacts(tmp_path):
    staging = _complete_staging(tmp_path)
    (staging / "family_diagnostics.json").unlink()
    with pytest.raises(F4V2PublicationError, match="f4_v2_artifact_missing"):
        publish_v2_generation(_handle(tmp_path, staging))


def test_non_winner_test_artifact_blocks_publication(tmp_path):
    staging = _complete_staging(tmp_path)
    _append_non_winner_test_metric(staging)
    with pytest.raises(F4V2PublicationError, match="f4_v2_test_without_lock"):
        publish_v2_generation(_handle(tmp_path, staging))


def test_nan_or_authorizing_artifact_blocks_pointer_switch(tmp_path):
    old = _install_old_pointer(tmp_path)
    staging = _complete_staging(tmp_path, aggregate_sharpe=float("nan"))
    with pytest.raises(F4V2PublicationError):
        publish_v2_generation(_handle(tmp_path, staging))
    assert _read_pointer(tmp_path) == old


def test_complete_same_identity_is_idempotent_no_op(tmp_path):
    first = publish_v2_generation(_handle(tmp_path, _complete_staging(tmp_path)))
    second = publish_v2_generation(_same_handle_with_forbidden_runner(tmp_path))
    assert second["publication_no_op"] is True
    assert second["factory_run_id"] == first["factory_run_id"]
```

- [ ] **Step 2: Run tests and confirm missing publisher**

Run `python -m pytest tests/test_f4_v2_publication.py -q`.

Expected: import failure for `f4_v2_publication`.

- [ ] **Step 3: Implement strict v2 publication**

Required artifacts are exactly:

```python
REQUIRED_V2_ARTIFACTS = (
    "registry.json",
    "window_definitions.json",
    "alpha_fits.json",
    "model_artifacts.json",
    "validation_leaderboards.json",
    "candidate_selection_locks.json",
    "test_window_metrics.json",
    "cost_stress_metrics.json",
    "family_diagnostics.json",
    "factory_report.json",
)
```

Validate finite JSON recursively, exact authority fields, registry count/families, candidate hashes, lock-to-test one-to-one mapping, policy hash, Alpha fit/model hashes, and absence of test artifacts for non-winners. Write final generations to `data/research/f4/factory-v2/<factory_run_id>/` and use a single same-directory `os.replace` for the latest v2 pointer.

The compatibility `data/research/f4/latest.json` projection changes only after the v2 generation is complete. A projection or mirror write failure after the authoritative v2 pointer commit must be reported separately and must not roll back or mislabel the committed generation.

- [ ] **Step 4: Run publication and validation-entrypoint tests**

Run:

```powershell
python -m pytest tests/test_f4_v2_publication.py tests/test_f4_validation_pipeline.py tests/test_f4_gate.py -q
```

Expected: all pass, including old pointer preservation on pre-commit failure and idempotent reuse.

- [ ] **Step 5: Verification checkpoint**

Confirm all publication tests use temporary roots. Record the authoritative pointer and compatibility projection order in the implementation report.

## Task 7: F4 gate aggregation and six-family diagnostics

**Files:**
- Modify: `quant/strategy/f4_metrics.py`
- Modify: `quant/strategy/f4_real_pipeline.py`
- Modify: `tests/test_f4_metrics.py`
- Modify: `tests/test_f4_gate.py`
- Modify: `tests/test_f4_pipeline_v2.py`

- [ ] **Step 1: Add failing aggregate and gate-preservation tests**

```python
def test_v2_aggregate_uses_locked_test_winners_only():
    metrics = aggregate_v2_window_metrics(
        locked_tests=[_window_metric("wf-01", "M1", excess=0.02),
                      _window_metric("wf-02", "Q1", excess=-0.01)],
        validation_rows=[_window_metric("wf-01", "R1", excess=99.0)],
        double_cost_excess_return=0.001,
    )
    assert metrics["window_count"] == 2
    assert metrics["positive_excess_window_ratio"] == 0.5
    assert metrics["after_cost_excess_return"] == pytest.approx(0.01)


def test_f4_v4_thresholds_are_unchanged_for_v2():
    assert evaluate_f4_gate({
        "window_count": 4,
        "positive_excess_window_ratio": 0.60,
        "after_cost_excess_return": 0.0001,
        "sharpe": 0.80,
        "max_drawdown": -0.20,
        "double_cost_excess_return": 0.0001,
        "constraint_violation_count": 0,
        "future_data_violation_count": 0,
    }, [])["status"] == "f4_research_candidate"
```

- [ ] **Step 2: Run the focused tests**

Run `python -m pytest tests/test_f4_metrics.py tests/test_f4_gate.py tests/test_f4_pipeline_v2.py -q`.

Expected: missing v2 aggregation helper or family diagnostics assertions fail.

- [ ] **Step 3: Implement aggregation without changing the gate**

Add family diagnostics derived only after all test windows finish:

```python
def build_family_diagnostics(registry, candidate_statuses, selection_locks):
    return {
        family: {
            "registered": sum(c.family == family for c in registry),
            "available": sum(s["family"] == family and s["available"] for s in candidate_statuses),
            "unavailable": sum(s["family"] == family and not s["available"] for s in candidate_statuses),
            "validation_wins": sum(lock["family"] == family for lock in selection_locks),
            "reason_counts": stable_reason_counts(candidate_statuses, family),
        }
        for family in ("momentum", "reversal", "defensive", "liquidity", "ensemble", "qlib")
    }
```

Do not edit `GATE_VERSION` or any numeric comparison in `evaluate_f4_gate()`. Add a source-level contract test that locks the eight existing thresholds and rejects new bypass fields.

- [ ] **Step 4: Run gate and v2 pipeline tests**

Run:

```powershell
python -m pytest tests/test_f4_metrics.py tests/test_f4_gate.py tests/test_f4_pipeline_v2.py -q
```

Expected: all pass. The synthetic passing case remains `research_only` and `execution_authority=false`.

- [ ] **Step 5: Verification checkpoint**

Compare `quant/strategy/f4_gate.py` before and after. It must be byte-identical unless only comments/tests were added; no threshold edit is permitted.

## Task 8: Downstream v1/v2 identity compatibility and fail-closed F5 binding

**Files:**
- Modify: `quant/strategy/research_selection.py:18, 197-258, 330-338`
- Modify: `quant/paper_execution/eligibility.py:9, 157-203`
- Modify: `tests/test_research_selection.py`
- Modify: `tests/test_f5_paper_eligibility.py`
- Modify: `tests/test_experimental_research_selection.py`

- [ ] **Step 1: Write failing v2 identity tests**

```python
def test_research_selection_accepts_verified_v2_winner_identity():
    result = build_research_selection(**_v2_arguments())
    assert result["f4_factory_version"] == "f4-multi-alpha-candidate-factory-v2"
    assert result["f4_alpha_spec_hash"] == _v2_lock()["alpha_spec_hash"]
    assert result["f4_candidate_lock_hash"] == _v2_lock()["lock_hash"]


@pytest.mark.parametrize("missing", [
    "factory_run_id", "candidate_id", "alpha_spec_hash", "alpha_fit_hash",
    "portfolio_policy_hash", "lock_hash",
])
def test_v2_selection_missing_identity_fails_closed(missing):
    arguments = _v2_arguments()
    _remove_v2_identity(arguments, missing)
    with pytest.raises(ResearchSelectionBlocked):
        build_research_selection(**arguments)


def test_f5_v2_binding_rejects_alpha_hash_mismatch():
    result = evaluate_eligibility(
        selection=_v2_selection(alpha_spec_hash="forged"),
        f4_latest=_v2_f4_latest(),
        policy=_paper_policy(),
    )
    assert result.eligible is False
    assert result.reason_code == "f4_candidate_alpha_identity_mismatch"
```

- [ ] **Step 2: Run tests and verify v2 is not yet supported**

Run:

```powershell
python -m pytest tests/test_research_selection.py tests/test_experimental_research_selection.py tests/test_f5_paper_eligibility.py -q
```

Expected: v2 identity assertions fail while all existing v1 cases still pass.

- [ ] **Step 3: Implement explicit supported-version branching**

Replace `FACTORY_VERSION` equality guesses with:

```python
factory_version = str(candidate_spec.get("version") or "")
if factory_version == FACTORY_VERSION_V2:
    verify_v2_candidate_binding(candidate_spec, fit, selected_policy, selected_lock)
elif factory_version == FACTORY_VERSION_V1:
    verify_v1_candidate_binding(candidate_spec, fit, selected_policy, selected_lock)
else:
    raise ResearchSelectionBlocked("f4_candidate_factory_version_unsupported")
```

For v2, propagate and verify `alpha_spec_hash`, `alpha_fit_hash`, optional `model_artifact_hash`, `policy_hash`, `candidate_id`, `factory_run_id` and lock hash. A missing field must not fall back to v1. Keep the existing distinction between validated and experimental local paper eligibility; this task only proves identity and does not create live authority.

- [ ] **Step 4: Run downstream identity tests**

Run:

```powershell
python -m pytest tests/test_research_selection.py tests/test_experimental_research_selection.py tests/test_f5_paper_eligibility.py tests/test_f5_runtime_publication.py -q
```

Expected: all pass for valid v1/v2 evidence; every v2 drift case is blocked.

- [ ] **Step 5: Verification checkpoint**

Search for direct `== FACTORY_VERSION` checks under `quant/strategy`, `quant/paper_execution`, `scripts` and `tests`. Every active reader must use explicit v1/v2 branching or a verified supported-version helper.

## Task 9: Read-only API and Chinese strategy-page diagnostics

**Files:**
- Modify: `scripts/strategy_runner.py:392-426`
- Modify: `components/StrategyPanel.tsx:233-330`
- Modify: `scripts/f4_strategy_ui_contract_tests.mjs`
- Modify: `tests/test_strategy_f4_projection.py`

- [ ] **Step 1: Write failing API projection and UI contract tests**

```python
def test_market_scan_projects_v2_family_diagnostics(monkeypatch, tmp_path):
    latest = _write_complete_v2_projection(tmp_path)
    monkeypatch.setattr(strategy_runner, "F4_LATEST_PATH", str(latest))
    result = strategy_runner.action_market_scan()
    assert result["success"] is True
    assert result["data"]["factory_version"] == "f4-multi-alpha-candidate-factory-v2"
    assert result["data"]["candidate_count"] == 24
    assert result["data"]["family_diagnostics"]["qlib"]["registered"] == 4
```

Extend the Node contract with exact labels:

```javascript
for (const label of [
  '24 个预登记候选', '候选族', '验证胜出窗口',
  '1.0 倍成本', '1.5 倍成本', '2.0 倍成本',
  '研究结果，不代表已获交易权限'
]) {
  assert(source.includes(label), `F4 v2 strategy surface must include: ${label}`);
}
```

- [ ] **Step 2: Run API/UI tests and confirm red state**

Run:

```powershell
python -m pytest tests/test_strategy_f4_projection.py -q
node scripts/f4_strategy_ui_contract_tests.mjs
```

Expected: v2 projection fields and labels are absent.

- [ ] **Step 3: Implement strict projection and compact UI**

`action_market_scan()` must verify the v2 projection authority, candidate count, six family keys, finite cost metrics and report path before returning them. A malformed v2 projection returns `f4_evidence_integrity_failed`; it must not fall back to an old scan.

Add a compact six-row family table to `StrategyPanel.tsx`:

```tsx
{familyRows.map((row) => (
  <tr key={row.family}>
    <td>{familyLabels[row.family] || row.family}</td>
    <td>{row.registered}</td>
    <td>{row.available}</td>
    <td>{row.unavailable}</td>
    <td>{row.validation_wins}</td>
    <td>{formatReasonCounts(row.reason_counts)}</td>
  </tr>
))}
```

Keep the current F4/F5 distinction. Do not add “自动晋升”“实盘可用” or any control button. Show the three cost scenarios and complete gate reasons in Chinese.

- [ ] **Step 4: Run frontend verification**

Run:

```powershell
python -m pytest tests/test_strategy_f4_projection.py -q
node scripts/f4_strategy_ui_contract_tests.mjs
npx tsc --noEmit
npm run build
```

Expected: all pass with no TypeScript errors.

- [ ] **Step 5: Verification checkpoint**

Start no new service yet. Record UI files and contract results; browser verification is deferred to Task 10 after the project services are intentionally reloaded if necessary.

## Task 10: Documentation and full regression before real research execution

**Files:**
- Modify: `README.md:145-179`
- Modify: `docs/XUANJI_HANDOFF.md:122-169`
- Modify: `docs/XUANJI_SYSTEM_WORKFLOW_MAP.md` where active F4 v1 is described
- Modify: `scripts/research_boundary_contract_tests.mjs`

- [ ] **Step 1: Add documentation contract assertions**

Update the research-boundary contract to require:

```javascript
for (const text of [
  'f4-multi-alpha-candidate-factory-v2',
  '24 个预登记候选',
  'factory-v2/<factory_run_id>',
  '只有窗口锁定胜者可以读取 test',
  'promotion_state=research_only',
  'execution_authority=false'
]) {
  assert(readme.includes(text) || handoff.includes(text), `missing F4 v2 handoff: ${text}`);
}
```

- [ ] **Step 2: Update active architecture text without rewriting history**

In README and handoff:

- mark the six-candidate v1 paragraphs as dated historical evidence;
- document the four new module responsibilities;
- document 24 candidates, v2 locks, evidence directory and scheduler entrypoint;
- state that F4 v2 may still return `f4_rejected_exhausted`;
- retain all historical validation IDs, hashes, timestamps and old names.

Update the system workflow map source relationships, but do not regenerate or claim an interactive HTML map unless it is actually rebuilt and browser-verified.

- [ ] **Step 3: Run the complete regression**

Run:

```powershell
python -m pytest -q
npm run test:contracts
npx tsc --noEmit
npm run build
node scripts/web_verify.mjs
node scripts/ui_verify.mjs
```

Expected:

- Python: all tests pass, with only previously documented skips;
- Node contract suite: all tests pass;
- TypeScript: exit code 0;
- Vite: exit code 0;
- Web verification: every check passes;
- UI verification: every check passes.

- [ ] **Step 4: Browser verification**

With the existing project Web/API services or an explicitly reloaded XuanJiQuant process only, open `http://127.0.0.1:8888`, select “策略运行 → F4 组合验证”, and verify:

- candidate count is 24 for v2 evidence or clearly shows the retained v1 historical version before the real run;
- family table, three cost scenarios and all gate reasons render;
- no control grants execution authority;
- browser console has zero errors and zero warnings caused by this feature;
- 1366px desktop and 1024px viewport layouts do not clip the reason text.

- [ ] **Step 5: Regression checkpoint**

If any regression fails, stop before real six-year execution. Fix by adding a failing regression test, rerun the affected set, then rerun the complete regression.

## Task 11: Run the real six-year v2 out-of-sample validation

**Files written by the approved research workflow:**
- Create: `data/research/f4/factory-v2/<factory_run_id>/*`
- Modify atomically: `data/research/f4/latest.json`
- Modify through existing evidence writer: versioned F4 validation evidence and latest projection
- Preserve: all `data/research/f4/factory/<v1_factory_run_id>/*`

- [ ] **Step 1: Verify input identities before execution**

Run read-only checks through the existing validation entrypoint and inspect:

- six-year manifest status and `completed_symbols`;
- manifest data version/hash and end date;
- PIT historical industry version/hash and at least 95% train/validation coverage per window;
- benchmark version, full calendar coverage and last date;
- Qlib provider presence and Alpha158/Alpha360 capability;
- absence of an already-running strategy weekly/F4 process.

Any failed input identity check must stop with `f4_blocked`; do not start partial candidate evaluation.

- [ ] **Step 2: Execute exactly one v2 validation**

Run:

```powershell
python scripts/validate_strategy_portfolios.py --once
```

Expected: exit code 0 only when a complete, integrity-checked v2 result is published. A legitimate research rejection may still exit 0 if all engineering stages completed and the result explicitly records `f4_rejected_exhausted`; infrastructure, identity, lock or publication failures exit nonzero.

- [ ] **Step 3: Verify all v2 evidence**

Check:

- registry has 24 unique candidates and six families of four;
- at least four test windows exist;
- each window has exactly one verified winner lock;
- every test row matches its winner lock;
- non-winners have no test prediction/result;
- rule and Qlib fit/model hashes match on disk;
- 1.0x, 1.5x and 2.0x cost results use identical winners;
- family diagnostics counts reconcile to registry, availability and locks;
- all authority fields remain research-only and false;
- v1 directories and historical evidence are unchanged.

- [ ] **Step 4: Report the actual research result without reinterpretation**

Report:

- data end date, manifest hash, factory run ID and validation ID;
- duration and per-stage timing;
- 24-candidate availability and failure counts;
- winner family/candidate per window;
- positive excess window ratio, after-cost excess return, median Sharpe, worst max drawdown and double-cost excess return;
- exact final status and every gate reason;
- whether Qlib candidates trained successfully;
- explicit `promotion_state=research_only`, `execution_authority=false`, and live authority state.

Do not add or modify candidates after seeing this result. A new hypothesis requires a new specification and factory version.

- [ ] **Step 5: Final regression and handoff snapshot**

After the real run, repeat:

```powershell
python -m pytest -q
npm run test:contracts
npx tsc --noEmit
npm run build
node scripts/web_verify.mjs
node scripts/ui_verify.mjs
```

Append a timestamped runtime snapshot to README and handoff containing only verified IDs, metrics and test counts. Label it as a historical snapshot, not a permanent current-state claim.

## Final completion checklist

- [ ] 24 pre-registered candidates exist and are truly different Alpha/strategy specifications.
- [ ] Candidate thresholds and formula fields are consumed by fit and scoring code.
- [ ] No non-winner reads a window test segment.
- [ ] Stable locks survive crashes and prevent validation reselection.
- [ ] Qlib failures remain explicit and never fall back to a rule candidate under the same identity.
- [ ] F4 v4 gate code and thresholds are unchanged.
- [ ] v1 history remains intact and verified readers support v1/v2 explicitly.
- [ ] v2 evidence passes cross-file identity, hash, finite-value and authority checks.
- [ ] Python, Node, TypeScript, Vite, Web/UI and browser-console verification pass.
- [ ] The real six-year result is reported exactly, whether candidate or exhausted rejection.

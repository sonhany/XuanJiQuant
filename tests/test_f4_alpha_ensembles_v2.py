from __future__ import annotations

from dataclasses import replace
import inspect

import numpy as np
import pandas as pd
import pytest

import quant.strategy.f4_alpha_rules as alpha_rules
from quant.strategy.f4_alpha_contracts import build_v2_candidate_registry
from quant.strategy.f4_alpha_rules import (
    AlphaUnavailable,
    RuleAlphaFit,
    RuleAlphaTrainingContext,
    _chronological_subperiods,
    _correlation_cluster_representatives,
    fit_rule_alpha_batch,
    fit_rule_alpha,
    prepare_rule_alpha_training_context,
    score_rule_alpha,
)
from quant.strategy.f4_candidate_factory import canonical_payload_hash


def _candidate(alpha_id: str):
    return next(
        item
        for item in build_v2_candidate_registry()
        if item.alpha_spec.alpha_id == alpha_id
    )


def _training_panel(*, periods: int = 8, instruments: int = 20) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for day_index, day in enumerate(pd.bdate_range("2024-01-02", periods=periods)):
        for stock_index in range(instruments):
            signal = (stock_index - (instruments - 1) / 2) / instruments
            close = 10.0 + day_index * 0.01
            rows.append(
                {
                    "date": day,
                    "instrument": f"SH{600000 + stock_index:06d}",
                    "industry": f"I{stock_index % 4}",
                    "forward_return_5d": signal * 0.02,
                    "close": close,
                    "ema_12": close / (1.0 + 0.05 * signal),
                    "ema_26": close / (1.0 + 0.04 * signal),
                    "macd_hist": signal,
                    "atr_14": close * (0.08 - 0.02 * signal),
                    "boll_upper": close * (1.05 - 0.01 * signal),
                    "boll_lower": close * (0.95 + 0.01 * signal),
                    "boll_mid": close,
                    "ret_5": signal,
                    "ret_10": signal,
                    "ret_20": signal,
                    "ret_60": signal,
                    "roc_10": signal,
                    "trend_strength": signal,
                    "reversal_3": signal,
                    "reversal_5": signal,
                    "reversal_10": signal,
                    "overnight_ret": -signal,
                    "intraday_ret": -signal,
                    "bias_20": -signal,
                    "volatility_5": 0.30 - 0.05 * signal,
                    "volatility_20": 0.30 - 0.05 * signal,
                    "volatility_60": 0.30 - 0.05 * signal,
                    "range_pct": 0.20 - 0.03 * signal,
                    "vol_ratio_5": 2.0 + signal,
                    "turnover_5": 2.0 + signal,
                    "turnover_20": 1.0,
                    "amt_ratio_5": 2.0 + signal,
                    "pvcorr_5": signal,
                    "obv_slope_10": signal,
                    "ad_slope_10": signal,
                    "mfi_14": 50.0 + signal,
                    "vwap_dev_20": signal,
                    "pvcorr_10": signal,
                    "pvbeta_20": signal,
                }
            )
    return pd.DataFrame(rows)


def _cross_section(panel: pd.DataFrame) -> pd.DataFrame:
    return panel.loc[panel["date"].eq(panel["date"].max())].drop(
        columns=["forward_return_5d"]
    )


def test_fixed_rule_fit_preserves_registered_formula_and_signed_features():
    candidate = _candidate("D1")

    fit = fit_rule_alpha(candidate, _training_panel(), window_id="wf-01")

    assert isinstance(fit, RuleAlphaFit)
    assert fit.input_signals == ("-volatility_5", "-volatility_20")
    assert fit.selected_signals == fit.input_signals
    assert fit.directions == {"-volatility_5": 1, "-volatility_20": 1}
    assert fit.weights == pytest.approx(
        {"-volatility_5": 0.40, "-volatility_20": 0.60}
    )
    assert fit.training_coverage == pytest.approx(1.0)
    assert len(fit.artifact_hash) == 64
    with pytest.raises(TypeError):
        fit.weights["-volatility_5"] = 1.0


def test_rule_fit_is_deterministic_under_row_reordering_and_train_only_api():
    candidate = _candidate("E2")
    train = _training_panel()

    first = fit_rule_alpha(candidate, train, window_id="wf-01")
    second = fit_rule_alpha(
        candidate,
        train.sample(frac=1.0, random_state=20260821),
        window_id="wf-01",
    )

    assert first.to_dict() == second.to_dict()
    assert set(first.selected_signals).issubset(set(first.input_signals))
    assert sum(first.weights.values()) == pytest.approx(1.0)


def test_equal_family_sleeves_give_each_available_family_one_quarter():
    fit = fit_rule_alpha(_candidate("E1"), _training_panel(), window_id="wf-01")

    for prefix in ("M", "R", "D", "L"):
        assert sum(
            weight for name, weight in fit.weights.items() if name.startswith(prefix)
        ) == pytest.approx(0.25)


def test_correlation_pruning_uses_stability_then_stable_name_tie_break():
    fit = fit_rule_alpha(_candidate("E3"), _training_panel(), window_id="wf-01")

    assert fit.selected_signals == tuple(sorted(fit.selected_signals))
    assert len(fit.selected_signals) < len(fit.input_signals)
    assert fit.selected_signals == ("D1",)


def test_e3_uses_transitive_correlation_components_and_stable_name_tie_break():
    rng = np.random.default_rng(20260821)
    covariance = np.asarray(
        [[1.0, 0.75, 0.30], [0.75, 1.0, 0.75], [0.30, 0.75, 1.0]]
    )
    signals = pd.DataFrame(
        rng.multivariate_normal(np.zeros(3), covariance, size=5000),
        columns=["M1", "M2", "M3"],
    )
    correlations = signals.corr(method="spearman")
    assert abs(correlations.loc["M1", "M2"]) >= 0.70
    assert abs(correlations.loc["M2", "M3"]) >= 0.70
    assert abs(correlations.loc["M1", "M3"]) < 0.70

    selected = _correlation_cluster_representatives(
        signals,
        ("M1", "M2", "M3"),
        {"M1": 0.80, "M2": 0.90, "M3": 0.90},
    )
    tied = _correlation_cluster_representatives(
        signals,
        ("M1", "M2", "M3"),
        {"M1": 0.90, "M2": 0.90, "M3": 0.90},
    )

    assert selected == ("M2",)
    assert tied == ("M1",)


def test_four_subperiod_stability_weights_are_normalized_and_deterministic():
    candidate = _candidate("E4")
    train = _training_panel(periods=8)

    first = fit_rule_alpha(candidate, train, window_id="wf-01")
    second = fit_rule_alpha(candidate, train.copy(), window_id="wf-01")

    assert first.to_dict() == second.to_dict()
    assert first.selected_signals
    assert sum(first.weights.values()) == pytest.approx(1.0)
    assert all(weight > 0.0 for weight in first.weights.values())


def test_e4_uses_exactly_four_contiguous_chronological_subperiods():
    dates = tuple(pd.bdate_range("2024-01-02", periods=11))

    subperiods = _chronological_subperiods(pd.Series(dates[::-1]))

    assert len(subperiods) == 4
    assert tuple(len(part) for part in subperiods) == (3, 3, 3, 2)
    flattened = tuple(date for part in subperiods for date in part)
    assert flattened == dates
    assert all(part == tuple(sorted(part)) for part in subperiods)
    assert all(subperiods[index][-1] < subperiods[index + 1][0] for index in range(3))


def test_rule_score_checks_identity_hash_missing_inputs_and_coverage():
    panel = _training_panel()
    candidate = _candidate("M1")
    fit = fit_rule_alpha(candidate, panel, window_id="wf-01")
    cross_section = _cross_section(panel)

    with pytest.raises(AlphaUnavailable, match="alpha_fit_candidate_identity_mismatch"):
        score_rule_alpha(_candidate("M2"), fit, cross_section)

    with pytest.raises(AlphaUnavailable, match="alpha_fit_integrity_failed"):
        score_rule_alpha(candidate, replace(fit, weights={"ret_20": 1.0}), cross_section)

    with pytest.raises(AlphaUnavailable, match="alpha_input_missing"):
        score_rule_alpha(candidate, fit, cross_section.drop(columns="ret_60"))

    missing = cross_section.copy()
    missing.loc[missing.index[:2], "ret_60"] = np.nan
    with pytest.raises(AlphaUnavailable, match="alpha_score_coverage_below_0_95"):
        score_rule_alpha(candidate, fit, missing)


def test_score_revalidates_candidate_even_if_attacker_rebinds_fit_hash():
    panel = _training_panel()
    candidate = _candidate("M1")
    fit = fit_rule_alpha(candidate, panel, window_id="wf-01")
    tampered_alpha = replace(candidate.alpha_spec, minimum_coverage=0.0)
    tampered_candidate = replace(candidate, alpha_spec=tampered_alpha)
    rebound = replace(
        fit,
        candidate_id=tampered_candidate.candidate_id,
        artifact_hash="",
    )
    rebound = replace(rebound, artifact_hash=canonical_payload_hash(rebound._payload()))

    with pytest.raises(AlphaUnavailable, match="alpha_candidate_contract_invalid"):
        score_rule_alpha(tampered_candidate, rebound, _cross_section(panel))


def test_malformed_candidate_types_have_one_stable_failure_code_in_fit_and_score():
    panel = _training_panel()
    valid = _candidate("M1")
    fit = fit_rule_alpha(valid, panel, window_id="wf-01")
    malformed = replace(
        valid,
        alpha_spec=replace(valid.alpha_spec, minimum_coverage=None),
    )

    with pytest.raises(AlphaUnavailable) as fit_error:
        fit_rule_alpha(malformed, panel, window_id="wf-01")
    with pytest.raises(AlphaUnavailable) as score_error:
        score_rule_alpha(malformed, fit, _cross_section(panel))

    assert fit_error.value.reason_code == "alpha_candidate_contract_invalid"
    assert score_error.value.reason_code == "alpha_candidate_contract_invalid"


def test_fit_interface_cannot_accept_validation_or_test_and_external_changes_do_not_matter():
    parameters = inspect.signature(fit_rule_alpha).parameters
    assert "validation" not in parameters
    assert "validation_panel" not in parameters
    assert "test" not in parameters
    assert "test_panel" not in parameters

    train = _training_panel()
    validation = _training_panel()
    test = _training_panel()
    first = fit_rule_alpha(_candidate("E2"), train, window_id="wf-01")
    validation["forward_return_5d"] *= -100.0
    test["forward_return_5d"] = np.inf
    second = fit_rule_alpha(_candidate("E2"), train, window_id="wf-01")

    assert first.to_dict() == second.to_dict()
    with pytest.raises(TypeError):
        fit_rule_alpha(
            _candidate("E2"),
            train,
            window_id="wf-01",
            validation_panel=validation,
            test_panel=test,
        )


def test_multi_date_scoring_equals_independent_per_date_scoring():
    panel = _training_panel(periods=4)
    candidate = _candidate("M4")
    fit = fit_rule_alpha(candidate, _training_panel(), window_id="wf-01")
    batch_input = panel.drop(columns="forward_return_5d")

    batch = score_rule_alpha(candidate, fit, batch_input).sort_index()
    independent = pd.concat(
        score_rule_alpha(candidate, fit, frame)
        for _date, frame in batch_input.groupby("date", sort=True)
    ).sort_index()

    pd.testing.assert_frame_equal(batch, independent)


def test_fixed_candidate_fit_does_not_compute_daily_rank_ic(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("fixed rule must not compute daily Rank IC")

    monkeypatch.setattr(alpha_rules, "_daily_rank_ic_by_date", forbidden)

    fit = fit_rule_alpha(_candidate("M3"), _training_panel(), window_id="wf-01")

    assert fit.selected_signals == (
        "ret_20_over_volatility_20",
        "ret_60_over_volatility_60",
    )
    assert fit.training_coverage == pytest.approx(1.0)


def test_batch_ensemble_fit_reuses_one_preprocessing_and_one_daily_ic(monkeypatch):
    panel = _training_panel(periods=16, instruments=40)
    ensemble = tuple(_candidate(f"E{index}") for index in range(1, 5))
    calls = {"preprocess": 0, "daily_ic": 0}
    real_preprocess = alpha_rules._preprocess_by_date
    real_daily_ic = alpha_rules._daily_rank_ic_by_date

    def counted_preprocess(*args, **kwargs):
        calls["preprocess"] += 1
        return real_preprocess(*args, **kwargs)

    def counted_daily_ic(*args, **kwargs):
        calls["daily_ic"] += 1
        return real_daily_ic(*args, **kwargs)

    monkeypatch.setattr(alpha_rules, "_preprocess_by_date", counted_preprocess)
    monkeypatch.setattr(alpha_rules, "_daily_rank_ic_by_date", counted_daily_ic)

    fits = fit_rule_alpha_batch(ensemble, panel, window_id="wf-medium")

    assert len(fits) == 4
    assert calls == {"preprocess": 1, "daily_ic": 1}
    assert {fit.alpha_id for fit in fits} == {"E1", "E2", "E3", "E4"}


def test_explicit_training_context_is_bound_to_train_and_window_identity():
    panel = _training_panel()
    candidate = _candidate("E2")
    context = prepare_rule_alpha_training_context(panel, window_id="wf-01")

    assert isinstance(context, RuleAlphaTrainingContext)
    assert context.row_count == len(panel)
    first = fit_rule_alpha(
        candidate,
        panel,
        window_id="wf-01",
        training_context=context,
    )
    second = fit_rule_alpha(
        candidate,
        panel.sample(frac=1.0, random_state=7),
        window_id="wf-01",
        training_context=context,
    )
    assert first.to_dict() == second.to_dict()

    altered = panel.copy()
    altered.loc[altered.index[0], "forward_return_5d"] *= -1.0
    with pytest.raises(AlphaUnavailable, match="alpha_training_context_identity_mismatch"):
        fit_rule_alpha(
            candidate,
            altered,
            window_id="wf-01",
            training_context=context,
        )
    with pytest.raises(AlphaUnavailable, match="alpha_training_context_window_mismatch"):
        fit_rule_alpha(
            candidate,
            panel,
            window_id="wf-02",
            training_context=context,
        )


def test_shared_training_context_serves_fixed_and_ensemble_candidates_once(monkeypatch):
    panel = _training_panel()
    candidates = (_candidate("M1"), _candidate("M2"), _candidate("E1"))
    import quant.strategy.f4_alpha_rules as rules

    original = rules._preprocess_by_date
    original_identity = rules._frame_identity
    calls = 0
    identity_calls = 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    def counted_identity(*args, **kwargs):
        nonlocal identity_calls
        identity_calls += 1
        return original_identity(*args, **kwargs)

    monkeypatch.setattr(rules, "_preprocess_by_date", counted)
    monkeypatch.setattr(rules, "_frame_identity", counted_identity)

    fits = fit_rule_alpha_batch(candidates, panel, window_id="wf-shared")

    assert {fit.alpha_id for fit in fits} == {"M1", "M2", "E1"}
    assert calls == 1
    assert identity_calls == 1


def test_fixed_candidate_can_fit_from_verified_shared_context(monkeypatch):
    panel = _training_panel()
    context = prepare_rule_alpha_training_context(panel, window_id="wf-shared")
    import quant.strategy.f4_alpha_rules as rules

    monkeypatch.setattr(
        rules,
        "derive_rule_features",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("fixed candidate recomputed shared features")
        ),
    )

    fit = fit_rule_alpha(
        _candidate("M1"),
        panel,
        window_id="wf-shared",
        training_context=context,
    )

    assert fit.alpha_id == "M1"


def test_training_context_exposes_only_defensive_copies_and_recursive_read_only_ic():
    panel = _training_panel()
    candidate = _candidate("E2")
    context = prepare_rule_alpha_training_context(panel, window_id="wf-01")
    before_hash = context.artifact_hash
    before_fit = fit_rule_alpha(
        candidate, panel, window_id="wf-01", training_context=context
    ).to_dict()

    signals = context.signals
    target = context.target
    dates = context.dates
    instruments = context.instruments
    signals.iloc[0, 0] = 999.0
    target.iloc[0] = 999.0
    dates.iloc[0] = pd.Timestamp("1990-01-01")
    instruments.iloc[0] = "MUTATED"
    first_signal = context.input_signals[0]
    first_date = next(iter(context.daily_rank_ic[first_signal]))
    with pytest.raises(TypeError):
        context.daily_rank_ic[first_signal][first_date] = 999.0
    with pytest.raises(TypeError):
        context.daily_rank_ic[first_signal] = {}

    after_fit = fit_rule_alpha(
        candidate, panel, window_id="wf-01", training_context=context
    ).to_dict()
    assert context.artifact_hash == before_hash
    assert context.signals.iloc[0, 0] != 999.0
    assert context.target.iloc[0] != 999.0
    assert context.dates.iloc[0] != pd.Timestamp("1990-01-01")
    assert context.instruments.iloc[0] != "MUTATED"
    assert after_fit == before_fit


@pytest.mark.parametrize("change_value", [False, True])
def test_training_context_rejects_duplicate_date_instrument_observations(change_value):
    panel = _training_panel()
    duplicate = panel.iloc[[0]].copy()
    if change_value:
        duplicate["ret_20"] = duplicate["ret_20"] + 1.0
    ambiguous = pd.concat([panel, duplicate], ignore_index=True)

    with pytest.raises(AlphaUnavailable) as error:
        prepare_rule_alpha_training_context(ambiguous, window_id="wf-01")

    assert error.value.reason_code == "alpha_train_duplicate_observation"


def test_rule_score_is_finite_and_respects_defensive_signed_direction():
    panel = _training_panel()
    candidate = _candidate("D1")
    fit = fit_rule_alpha(candidate, panel, window_id="wf-01")

    scored = score_rule_alpha(candidate, fit, _cross_section(panel))

    assert list(scored.columns) == ["code", "industry", "score"]
    assert len(scored) == 20
    assert np.isfinite(scored["score"]).all()
    lowest_vol_code = _cross_section(panel).sort_values("volatility_20").iloc[0][
        "instrument"
    ]
    assert scored.sort_values("score").iloc[-1]["code"] == lowest_vol_code


def test_fit_fails_closed_for_missing_columns_nonfinite_target_and_low_coverage():
    candidate = _candidate("M1")
    panel = _training_panel()

    with pytest.raises(AlphaUnavailable, match="alpha_input_missing"):
        fit_rule_alpha(candidate, panel.drop(columns="ret_60"), window_id="wf-01")

    invalid_target = panel.copy()
    invalid_target["forward_return_5d"] = np.inf
    with pytest.raises(AlphaUnavailable, match="alpha_train_target_unavailable"):
        fit_rule_alpha(candidate, invalid_target, window_id="wf-01")

    low_coverage = panel.copy()
    low_coverage.loc[low_coverage.index[:20], "ret_60"] = np.nan
    with pytest.raises(AlphaUnavailable, match="alpha_train_coverage_below_0_95"):
        fit_rule_alpha(candidate, low_coverage, window_id="wf-01")

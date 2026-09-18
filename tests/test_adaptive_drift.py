import math
import warnings
from collections import deque
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.stats import ks_2samp as scipy_ks_2samp

from quant.adaptive.drift import compare_numeric_distributions


def test_equal_distributions_have_low_drift():
    out = compare_numeric_distributions(reference=[1, 2, 3, 4, 5] * 20, current=[1, 2, 3, 4, 5] * 20)
    assert out["available"] is True
    assert out["psi_available"] is True
    assert out["psi"] < 0.01
    assert out["ks_stat"] == 0


def test_shifted_distributions_raise_drift():
    out = compare_numeric_distributions(reference=list(range(100)), current=list(range(100, 200)))
    assert out["psi_available"] is True
    assert out["psi"] >= 0.25
    assert out["ks_stat"] >= 0.9


def test_missing_and_non_finite_values_are_reported():
    out = compare_numeric_distributions(reference=[1, 2, None, float("nan")], current=[None, float("inf"), 2, 3])
    assert math.isclose(out["reference_missing_rate"], 0.5)
    assert math.isclose(out["current_missing_rate"], 0.5)
    assert out["psi_available"] is False
    assert out["psi"] is None
    assert out["psi_reason"] == "insufficient_psi_samples"


def test_insufficient_samples_include_counts_and_missing_rates():
    out = compare_numeric_distributions(reference=["1", None, True], current=[2, "bad"])

    assert out == {
        "available": False,
        "reason": "insufficient_samples",
        "reference_count": 1,
        "current_count": 1,
        "reference_missing_rate": pytest.approx(2 / 3),
        "current_missing_rate": pytest.approx(1 / 2),
    }


@pytest.mark.parametrize("bins", [None, "bad", True, 3.5, float("nan"), float("inf")])
def test_malformed_bins_match_default_behavior(bins):
    reference = list(range(500))
    current = list(range(50, 550))
    expected = compare_numeric_distributions(reference, current)
    out = compare_numeric_distributions(reference, current, bins=bins)

    assert out["available"] is True
    assert out["psi_available"] is True
    assert out["psi_bins"] == 10
    assert out["psi"] == expected["psi"]


@pytest.mark.parametrize(("bins", "expected"), [(1, 2), (2, 2), (7, 5), (10_000, 5)])
def test_integral_bins_are_clamped_and_calibrated_to_sample_size(bins, expected):
    out = compare_numeric_distributions(range(100), range(10, 110), bins=bins)

    assert out["psi_available"] is True
    assert out["psi_bins"] == expected


def test_small_constant_distributions_only_produce_ks_metrics():
    out = compare_numeric_distributions([7] * 20, [7] * 20)

    assert out["available"] is True
    assert out["psi_available"] is False
    assert out["psi"] is None
    assert out["psi_reason"] == "insufficient_psi_samples"
    assert out["ks_stat"] == 0
    assert out["ks_pvalue"] == 1
    assert all(math.isfinite(out[key]) for key in ("ks_stat", "ks_pvalue"))


def test_adequate_constant_distributions_have_zero_psi():
    out = compare_numeric_distributions([7] * 40, [7] * 40)

    assert out["psi_available"] is True
    assert out["psi"] == 0
    assert out["psi_bins"] == 3


@pytest.mark.parametrize("current_value", [6.0, 8.0])
def test_constant_shifts_in_both_directions_raise_psi(current_value):
    out = compare_numeric_distributions([7.0] * 40, [current_value] * 40)

    assert out["psi_available"] is True
    assert out["psi"] > 0.25
    assert out["psi_bins"] == 3


@pytest.mark.parametrize(
    "current_value",
    [np.nextafter(7.0, -np.inf), np.nextafter(7.0, np.inf)],
)
def test_one_ulp_constant_shifts_are_detected(current_value):
    out = compare_numeric_distributions([7.0] * 40, [current_value] * 40)

    assert out["psi_available"] is True
    assert out["psi"] > 0.25


def test_tied_discrete_proportion_shift_raises_psi():
    reference = ([0.0] * 90) + ([1.0] * 10)
    current = ([0.0] * 50) + ([1.0] * 50)

    out = compare_numeric_distributions(reference, current)

    assert out["psi_available"] is True
    assert out["psi"] > 0.1
    assert out["psi_bins"] == 2


def test_mirrored_binary_high_majority_shift_raises_psi():
    reference = ([0.0] * 10) + ([1.0] * 90)
    current = ([0.0] * 50) + ([1.0] * 50)

    out = compare_numeric_distributions(reference, current)

    assert out["psi_available"] is True
    assert out["psi"] > 0.1
    assert out["psi_bins"] >= 2


def test_three_level_high_majority_shift_raises_psi():
    reference = ([0.0] * 5) + ([1.0] * 5) + ([2.0] * 90)
    current = ([0.0] * 35) + ([1.0] * 35) + ([2.0] * 30)

    out = compare_numeric_distributions(reference, current)

    assert out["psi_available"] is True
    assert out["psi"] > 0.1
    assert out["psi_bins"] >= 2


def test_convertible_strings_are_valid_and_bools_are_missing():
    out = compare_numeric_distributions((["1", "2.5", True] * 20), ([1, 2.5, False] * 20))

    assert out["available"] is True
    assert out["reference_count"] == 40
    assert out["current_count"] == 40
    assert math.isclose(out["reference_missing_rate"], 1 / 3)
    assert math.isclose(out["current_missing_rate"], 1 / 3)
    assert out["psi"] == 0


def test_metrics_are_non_negative_and_rounded_to_six_decimals():
    out = compare_numeric_distributions(range(100), range(1, 101), bins=6)

    assert out["psi"] >= 0
    for key in ("psi", "ks_stat", "ks_pvalue"):
        assert out[key] == round(out[key], 6)


def test_extreme_finite_values_do_not_overflow_or_hide_drift():
    maximum = float.fromhex("0x1.fffffffffffffp+1023")

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        out = compare_numeric_distributions([-maximum, maximum] * 20, [0.0, 1.0] * 20)

    assert out["available"] is True
    assert out["psi"] > 0
    assert all(math.isfinite(out[key]) for key in ("psi", "ks_stat", "ks_pvalue"))


def test_small_independent_samples_skip_psi_but_keep_ks():
    reference = np.random.default_rng(101).normal(size=20)
    current = np.random.default_rng(202).normal(size=20)

    out = compare_numeric_distributions(reference, current)

    assert out["available"] is True
    assert out["psi_available"] is False
    assert out["psi"] is None
    assert out["psi_reason"] == "insufficient_psi_samples"
    assert math.isfinite(out["ks_stat"])
    assert math.isfinite(out["ks_pvalue"])


def test_adequate_same_population_samples_have_calibrated_psi():
    reference = np.random.default_rng(303).normal(size=500)
    current = np.random.default_rng(404).normal(size=500)

    out = compare_numeric_distributions(reference, current)

    assert out["psi_available"] is True
    assert out["psi_bins"] == 10
    assert out["psi"] < 0.25


@pytest.mark.parametrize(
    "invalid",
    [
        1,
        1.5,
        "1,2,3",
        b"1,2,3",
        {"first": 1},
        np.array(1),
        np.array([[1, 2], [3, 4]]),
    ],
)
def test_non_flat_public_inputs_are_rejected(invalid):
    with pytest.raises(ValueError, match="flat, non-string iterable"):
        compare_numeric_distributions(invalid, [1, 2])


@pytest.mark.parametrize(
    "nested",
    [
        [[1], 2],
        [(1,), 2],
        [np.array([1]), 2],
        [{"first": 1}, 2],
    ],
)
def test_nested_values_are_rejected(nested):
    with pytest.raises(ValueError, match="flat, non-string iterable"):
        compare_numeric_distributions([1, 2], nested)


def test_generators_and_one_dimensional_arrays_are_accepted():
    reference = (value for value in range(40))
    current = np.arange(40)

    out = compare_numeric_distributions(reference, current)

    assert out["available"] is True
    assert out["reference_count"] == 40
    assert out["current_count"] == 40
    assert out["psi_available"] is True
    assert out["psi"] == 0


@pytest.mark.parametrize(
    "nested",
    [
        {1, 2},
        range(2),
        deque([1, 2]),
        (value for value in [1, 2]),
    ],
)
def test_any_nested_non_string_iterable_is_rejected(nested):
    with pytest.raises(ValueError, match="flat, non-string iterable"):
        compare_numeric_distributions([1, nested], [1, 2])


def test_extremely_large_integral_bins_do_not_raise():
    out = compare_numeric_distributions(range(100), range(10, 110), bins=10**1000)

    assert out["psi_available"] is True
    assert 2 <= out["psi_bins"] <= 5


def test_disjoint_two_value_samples_use_exact_ks_pvalue():
    out = compare_numeric_distributions([1, 2], [3, 4])

    assert out["ks_stat"] == 1.0
    assert out["ks_pvalue"] == 0.333333


def test_disjoint_three_value_samples_use_exact_ks_pvalue():
    out = compare_numeric_distributions([1, 2, 3], [4, 5, 6])

    assert out["ks_stat"] == 1.0
    assert out["ks_pvalue"] == 0.1


def test_partial_small_sample_shift_matches_scipy_exact():
    reference = [1, 2, 3, 4, 5]
    current = [3, 4, 5, 6, 7]
    expected = scipy_ks_2samp(reference, current, method="exact")

    out = compare_numeric_distributions(reference, current)

    assert out["ks_stat"] == round(float(expected.statistic), 6)
    assert out["ks_pvalue"] == round(float(expected.pvalue), 6)


@pytest.mark.parametrize(
    "failure",
    ["warning", "runtime_warning", "value_error", "floating_point_error"],
)
def test_exact_ks_failure_falls_back_to_asymp_without_warning(monkeypatch, failure):
    import quant.adaptive.drift as drift

    methods = []

    def controlled_ks_2samp(*args, method):
        methods.append(method)
        if method == "exact":
            if failure == "warning":
                warnings.warn("exact calculation failed", RuntimeWarning)
            if failure == "runtime_warning":
                raise RuntimeWarning("exact calculation failed")
            if failure == "value_error":
                raise ValueError("exact calculation failed")
            if failure == "floating_point_error":
                raise FloatingPointError("exact calculation failed")
        return SimpleNamespace(statistic=0.5, pvalue=0.25)

    monkeypatch.setattr(drift, "ks_2samp", controlled_ks_2samp)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        out = compare_numeric_distributions([1, 2, 3], [2, 3, 4])

    assert caught == []
    assert methods == ["exact", "asymp"]
    assert out["ks_stat"] == 0.5
    assert out["ks_pvalue"] == 0.25


def test_large_samples_use_asymp_without_attempting_exact(monkeypatch):
    import quant.adaptive.drift as drift

    methods = []

    def recording_ks_2samp(*args, method):
        methods.append(method)
        return SimpleNamespace(statistic=0.1, pvalue=0.2)

    monkeypatch.setattr(drift, "ks_2samp", recording_ks_2samp)
    out = compare_numeric_distributions(range(10_001), range(1, 10_002))

    assert methods == ["asymp"]
    assert out["ks_stat"] == 0.1
    assert out["ks_pvalue"] == 0.2


def test_non_finite_internal_psi_is_reported_as_unavailable(monkeypatch):
    import quant.adaptive.drift as drift

    monkeypatch.setattr(drift, "_psi", lambda reference, current, bins: (float("nan"), 3))

    out = compare_numeric_distributions(range(40), range(40))

    assert out["available"] is True
    assert out["psi_available"] is False
    assert out["psi"] is None
    assert out["psi_reason"] == "psi_numerical_failure"
    assert out["psi_bins"] == 3

from __future__ import annotations

import math
import warnings
from collections.abc import Iterable, Mapping
from numbers import Integral, Real

import numpy as np
from scipy.stats import ks_2samp


_DEFAULT_BINS = 10
_MAX_BINS = 1000
_PSI_SMOOTHING = 0.5
_KS_EXACT_MAX_SAMPLE = 10_000
MIN_PSI_SAMPLES = 40
_INPUT_ERROR = "must be a flat, non-string iterable"


def _finite(values: Iterable[object], name: str) -> tuple[np.ndarray, int]:
    if isinstance(values, (str, bytes, Mapping)):
        raise ValueError(f"{name} {_INPUT_ERROR}")
    if isinstance(values, np.ndarray) and values.ndim != 1:
        raise ValueError(f"{name} {_INPUT_ERROR}")
    try:
        iterator = iter(values)
    except TypeError as exc:
        raise ValueError(f"{name} {_INPUT_ERROR}") from exc

    rows = []
    total = 0
    for value in iterator:
        total += 1
        if isinstance(value, np.ndarray) or (
            isinstance(value, Iterable) and not isinstance(value, (str, bytes))
        ):
            raise ValueError(f"{name} {_INPUT_ERROR}")
        if isinstance(value, (bool, np.bool_)):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(number):
            rows.append(number)
    return np.asarray(rows, dtype=float), total


def _safe_bins(bins: object) -> int:
    if isinstance(bins, bool):
        return _DEFAULT_BINS
    if isinstance(bins, Integral):
        return min(max(int(bins), 2), _MAX_BINS)
    if not isinstance(bins, Real):
        return _DEFAULT_BINS
    try:
        numeric = float(bins)
    except (OverflowError, TypeError, ValueError):
        return _DEFAULT_BINS
    if not math.isfinite(numeric) or not numeric.is_integer():
        return _DEFAULT_BINS
    normalized = int(numeric)
    return min(max(normalized, 2), _MAX_BINS)


def _missing_rate(valid_count: int, total: int) -> float:
    if total == 0:
        return 0.0
    return float((total - valid_count) / total)


def _between(left: float, right: float) -> float:
    if left < 0.0 < right:
        midpoint = (left / 2.0) + (right / 2.0)
    else:
        midpoint = left + ((right - left) / 2.0)
    if left < midpoint < right:
        return midpoint
    return right


def _psi_edges(reference: np.ndarray, bins: int) -> np.ndarray:
    unique_values, counts = np.unique(reference, return_counts=True)
    if unique_values.size == 1:
        value = float(unique_values[0])
        if value == np.finfo(float).max:
            return np.asarray([-np.inf, value, np.inf])
        return np.asarray([-np.inf, value, np.nextafter(value, np.inf), np.inf])

    gap_masses = np.cumsum(counts)[:-1]
    targets = np.arange(1, bins, dtype=float) * (reference.size / bins)
    split_indexes = np.unique(
        [int(np.argmin(np.abs(gap_masses - target))) for target in targets]
    )
    internal_edges = [
        _between(float(unique_values[index]), float(unique_values[index + 1]))
        for index in split_indexes
    ]
    return np.asarray([-np.inf, *internal_edges, np.inf])


def _psi(reference: np.ndarray, current: np.ndarray, bins: int) -> tuple[float, int]:
    edges = _psi_edges(reference, bins)

    reference_counts, _ = np.histogram(reference, bins=edges)
    current_counts, _ = np.histogram(current, bins=edges)
    reference_rates = reference_counts.astype(float) + _PSI_SMOOTHING
    current_rates = current_counts.astype(float) + _PSI_SMOOTHING
    reference_rates /= reference_rates.sum()
    current_rates /= current_rates.sum()
    value = np.sum((current_rates - reference_rates) * np.log(current_rates / reference_rates))
    numeric_value = float(value)
    if not math.isfinite(numeric_value):
        return numeric_value, int(edges.size - 1)
    return max(0.0, numeric_value), int(edges.size - 1)


def _ks_test(reference: np.ndarray, current: np.ndarray):
    if max(reference.size, current.size) <= _KS_EXACT_MAX_SAMPLE:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", RuntimeWarning)
                return ks_2samp(reference, current, method="exact")
        except (RuntimeWarning, ValueError, FloatingPointError):
            pass

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return ks_2samp(reference, current, method="asymp")


def compare_numeric_distributions(
    reference: Iterable[object],
    current: Iterable[object],
    bins: int = 10,
) -> dict[str, object]:
    """Compare two flat numeric-like iterables with KS and calibrated PSI.

    Top-level strings, bytes, mappings, scalars, non-1-D arrays, and nested
    container values raise ``ValueError``. Non-convertible, boolean, and
    non-finite scalar values are counted as missing. ``available`` requires two
    finite values per sample and controls KS availability. PSI additionally
    requires ``MIN_PSI_SAMPLES`` finite values in each sample; otherwise
    ``psi`` is ``None`` and ``psi_reason`` explains why.
    """
    reference_values, reference_total = _finite(reference, "reference")
    current_values, current_total = _finite(current, "current")
    result = {
        "reference_count": int(reference_values.size),
        "current_count": int(current_values.size),
        "reference_missing_rate": _missing_rate(reference_values.size, reference_total),
        "current_missing_rate": _missing_rate(current_values.size, current_total),
    }

    if reference_values.size < 2 or current_values.size < 2:
        return {
            "available": False,
            "reason": "insufficient_samples",
            **result,
        }

    ks_result = _ks_test(reference_values, current_values)
    comparison = {
        "available": True,
        **result,
        "ks_stat": round(float(ks_result.statistic), 6),
        "ks_pvalue": round(float(ks_result.pvalue), 6),
    }
    min_sample_count = min(reference_values.size, current_values.size)
    if min_sample_count < MIN_PSI_SAMPLES:
        return {
            **comparison,
            "psi_available": False,
            "psi": None,
            "psi_reason": "insufficient_psi_samples",
        }

    effective_bins = min(_safe_bins(bins), max(2, int(min_sample_count) // 20))
    psi, actual_bins = _psi(reference_values, current_values, effective_bins)
    if not math.isfinite(psi):
        return {
            **comparison,
            "psi_available": False,
            "psi": None,
            "psi_reason": "psi_numerical_failure",
            "psi_bins": actual_bins,
        }
    return {
        **comparison,
        "psi_available": True,
        "psi": round(psi, 6),
        "psi_bins": actual_bins,
    }

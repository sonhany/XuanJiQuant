"""Deterministic feature transforms for research-only F4 v2 rule alphas."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any

import numpy as np
import pandas as pd

from .f4_alpha_contracts import (
    BASE_RULE_ALPHA_IDS,
    F4CandidateV2,
    build_v2_candidate_registry,
)
from .f4_candidate_factory import canonical_payload_hash


DERIVED_FEATURE_SCHEMA_VERSION = "f4-rule-derived-features-v2"
DERIVED_FEATURE_NAMES = (
    "ema_gap_12",
    "ema_gap_26",
    "macd_hist_norm",
    "atr_14_norm",
    "boll_width",
    "ret_20_over_volatility_20",
    "ret_60_over_volatility_60",
    "turnover_5_over_20",
)

_DERIVED_DEPENDENCIES = {
    "ema_gap_12": ("close", "ema_12"),
    "ema_gap_26": ("close", "ema_26"),
    "macd_hist_norm": ("macd_hist", "close"),
    "atr_14_norm": ("atr_14", "close"),
    "boll_width": ("boll_upper", "boll_lower", "boll_mid"),
    "ret_20_over_volatility_20": ("ret_20", "volatility_20"),
    "ret_60_over_volatility_60": ("ret_60", "volatility_60"),
    "turnover_5_over_20": ("turnover_5", "turnover_20"),
}


class AlphaUnavailable(ValueError):
    """Stable fail-closed reason for one unavailable v2 alpha candidate."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = str(reason_code)
        self.detail = str(detail)
        super().__init__(
            self.reason_code if not self.detail else f"{self.reason_code}: {self.detail}"
        )


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

    def __post_init__(self) -> None:
        for field_name in (
            "directions",
            "weights",
            "median_rank_ic",
            "direction_consistency",
        ):
            object.__setattr__(
                self,
                field_name,
                MappingProxyType(dict(getattr(self, field_name))),
            )

    def _payload(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "alpha_id": self.alpha_id,
            "window_id": self.window_id,
            "fit_start": self.fit_start,
            "fit_end": self.fit_end,
            "input_signals": list(self.input_signals),
            "selected_signals": list(self.selected_signals),
            "directions": dict(sorted(self.directions.items())),
            "weights": dict(sorted(self.weights.items())),
            "median_rank_ic": dict(sorted(self.median_rank_ic.items())),
            "direction_consistency": dict(
                sorted(self.direction_consistency.items())
            ),
            "training_coverage": float(self.training_coverage),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "artifact_hash": self.artifact_hash}

    def verify(self) -> None:
        selected = set(self.selected_signals)
        inputs = set(self.input_signals)
        numeric_maps = (
            self.weights,
            self.median_rank_ic,
            self.direction_consistency,
        )
        if (
            not self.window_id
            or not self.fit_start
            or not self.fit_end
            or not selected
            or len(selected) != len(self.selected_signals)
            or not selected.issubset(inputs)
            or set(self.directions) != selected
            or set(self.weights) != selected
            or set(self.median_rank_ic) != inputs
            or set(self.direction_consistency) != inputs
            or any(value not in {-1, 1} for value in self.directions.values())
            or any(
                not np.isfinite(float(value))
                for mapping in numeric_maps
                for value in mapping.values()
            )
            or any(float(value) <= 0.0 for value in self.weights.values())
            or not np.isclose(sum(self.weights.values()), 1.0, atol=1e-12)
            or not np.isfinite(float(self.training_coverage))
            or not 0.0 <= float(self.training_coverage) <= 1.0
            or canonical_payload_hash(self._payload()) != self.artifact_hash
        ):
            raise AlphaUnavailable("alpha_fit_integrity_failed")


@dataclass(frozen=True, slots=True)
class RuleAlphaTrainingContext:
    window_id: str
    train_identity: str
    fit_start: str
    fit_end: str
    row_count: int
    input_signals: tuple[str, ...]
    training_coverage: float
    artifact_hash: str
    _signal_columns: tuple[str, ...]
    _signal_shape: tuple[int, int]
    _signal_bytes: bytes
    _target_bytes: bytes
    _date_ns_bytes: bytes
    _instrument_blob: bytes
    _daily_ic_items: tuple[tuple[str, tuple[tuple[str, float], ...]], ...]

    @property
    def signals(self) -> pd.DataFrame:
        values = np.frombuffer(self._signal_bytes, dtype="<f8").reshape(
            self._signal_shape
        )
        return pd.DataFrame(values.copy(), columns=self._signal_columns)

    def signal_subset(self, names: Iterable[str]) -> pd.DataFrame:
        requested = tuple(str(name) for name in names)
        missing = sorted(set(requested) - set(self._signal_columns))
        if not requested or missing:
            raise AlphaUnavailable(
                "alpha_training_context_signal_missing", ",".join(missing)
            )
        positions = [self._signal_columns.index(name) for name in requested]
        values = np.frombuffer(self._signal_bytes, dtype="<f8").reshape(
            self._signal_shape
        )
        return pd.DataFrame(values[:, positions].copy(), columns=requested)

    @property
    def target(self) -> pd.Series:
        return pd.Series(
            np.frombuffer(self._target_bytes, dtype="<f8").copy(), dtype=float
        )

    @property
    def dates(self) -> pd.Series:
        values = np.frombuffer(self._date_ns_bytes, dtype="<i8").copy()
        return pd.Series(pd.to_datetime(values, unit="ns"), dtype="datetime64[ns]")

    @property
    def instruments(self) -> pd.Series:
        return pd.Series(self._instrument_blob.decode("utf-8").split("\n"), dtype=str)

    @property
    def daily_rank_ic(self):
        return MappingProxyType(
            {
                name: MappingProxyType(
                    {
                        pd.Timestamp(date).normalize(): float(value)
                        for date, value in observations
                    }
                )
                for name, observations in self._daily_ic_items
            }
        )

    def _payload(self) -> dict[str, Any]:
        return {
            "window_id": self.window_id,
            "train_identity": self.train_identity,
            "fit_start": self.fit_start,
            "fit_end": self.fit_end,
            "row_count": int(self.row_count),
            "input_signals": list(self.input_signals),
            "training_coverage": float(self.training_coverage),
            "signal_columns": list(self._signal_columns),
            "signal_shape": list(self._signal_shape),
            "signal_sha256": hashlib.sha256(self._signal_bytes).hexdigest(),
            "target_sha256": hashlib.sha256(self._target_bytes).hexdigest(),
            "date_ns_sha256": hashlib.sha256(self._date_ns_bytes).hexdigest(),
            "instrument_sha256": hashlib.sha256(self._instrument_blob).hexdigest(),
            "daily_ic_items": self._daily_ic_items,
        }

    def verify(self) -> None:
        if (
            not self.window_id
            or not self.train_identity
            or self._signal_shape != (self.row_count, len(self._signal_columns))
            or len(self._signal_bytes) != self.row_count * len(self._signal_columns) * 8
            or len(self._target_bytes) != self.row_count * 8
            or len(self._date_ns_bytes) != self.row_count * 8
            or (
                (self._instrument_blob.count(b"\n") + 1 if self._instrument_blob else 0)
                != self.row_count
            )
            or self.input_signals != BASE_RULE_ALPHA_IDS
            or self._signal_columns != BASE_RULE_ALPHA_IDS
            or not np.isfinite(float(self.training_coverage))
            or canonical_payload_hash(self._payload()) != self.artifact_hash
        ):
            raise AlphaUnavailable("alpha_training_context_integrity_failed")


def _numeric_column(frame: pd.DataFrame, name: str) -> pd.Series:
    if name not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[name], errors="coerce").astype(float)


def _frame_identity(frame: pd.DataFrame) -> str:
    ordered_columns = tuple(sorted(str(column) for column in frame.columns))
    ordered = frame.loc[:, ordered_columns].copy()
    sort_columns = [
        name for name in ("date", "__date", "instrument", "__instrument")
        if name in ordered.columns
    ]
    if sort_columns:
        ordered.sort_values(sort_columns, kind="mergesort", inplace=True)
    else:
        ordered.sort_values(list(ordered_columns), kind="mergesort", inplace=True)
    ordered.reset_index(drop=True, inplace=True)
    digest = hashlib.sha256()
    digest.update("\x1f".join(ordered_columns).encode("utf-8"))
    digest.update(
        "\x1f".join(str(ordered[name].dtype) for name in ordered_columns).encode(
            "utf-8"
        )
    )
    digest.update(
        pd.util.hash_pandas_object(ordered, index=False, categorize=True)
        .to_numpy(dtype="uint64")
        .tobytes()
    )
    return digest.hexdigest()


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    numerator = pd.to_numeric(numerator, errors="coerce")
    denominator = pd.to_numeric(denominator, errors="coerce")
    valid = numerator.map(np.isfinite) & denominator.map(np.isfinite) & (denominator > 1e-12)
    result = numerator.where(valid).div(denominator.where(valid))
    return result.replace([np.inf, -np.inf], np.nan)


def derive_rule_features(
    frame: pd.DataFrame,
    feature_names: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Add the versioned, dimensionless v2 rule features without mutating input."""

    result = frame.copy()
    requested = (
        set(DERIVED_FEATURE_NAMES)
        if feature_names is None
        else {_source_name(name) for name in feature_names} & set(DERIVED_FEATURE_NAMES)
    )
    close = _numeric_column(result, "close")
    if "ema_gap_12" in requested:
        result["ema_gap_12"] = _safe_divide(close, _numeric_column(result, "ema_12")) - 1.0
    if "ema_gap_26" in requested:
        result["ema_gap_26"] = _safe_divide(close, _numeric_column(result, "ema_26")) - 1.0
    if "macd_hist_norm" in requested:
        result["macd_hist_norm"] = _safe_divide(
            _numeric_column(result, "macd_hist"), close
        )
    if "atr_14_norm" in requested:
        result["atr_14_norm"] = _safe_divide(_numeric_column(result, "atr_14"), close)
    if "boll_width" in requested:
        result["boll_width"] = _safe_divide(
            _numeric_column(result, "boll_upper") - _numeric_column(result, "boll_lower"),
            _numeric_column(result, "boll_mid"),
        )
    if "ret_20_over_volatility_20" in requested:
        result["ret_20_over_volatility_20"] = _safe_divide(
            _numeric_column(result, "ret_20"), _numeric_column(result, "volatility_20")
        )
    if "ret_60_over_volatility_60" in requested:
        result["ret_60_over_volatility_60"] = _safe_divide(
            _numeric_column(result, "ret_60"), _numeric_column(result, "volatility_60")
        )
    if "turnover_5_over_20" in requested:
        result["turnover_5_over_20"] = _safe_divide(
            _numeric_column(result, "turnover_5"), _numeric_column(result, "turnover_20")
        )
    if requested:
        names = tuple(sorted(requested))
        result.loc[:, names] = result.loc[:, names].replace([np.inf, -np.inf], np.nan)
    return result


def _five_mad_clip(series: pd.Series) -> pd.Series:
    finite = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    median = finite.median(skipna=True)
    if not np.isfinite(median):
        return finite
    mad = (finite - median).abs().median(skipna=True)
    if not np.isfinite(mad) or mad <= 1e-12:
        return finite
    return finite.clip(lower=median - 5.0 * mad, upper=median + 5.0 * mad)


def _zero_one_percentile(series: pd.Series) -> pd.Series:
    result = pd.Series(np.nan, index=series.index, dtype=float)
    usable = series.dropna()
    if usable.empty:
        return result
    if len(usable) == 1:
        result.loc[usable.index] = 0.5
        return result
    ranks = usable.rank(method="average")
    result.loc[usable.index] = (ranks - 1.0) / (len(usable) - 1.0)
    return result


def preprocess_cross_section(
    frame: pd.DataFrame,
    feature_names: Iterable[str],
) -> pd.DataFrame:
    """Apply 5-MAD clipping, industry de-meaning and within-industry ranks."""

    if "industry" not in frame.columns:
        raise ValueError("industry_column_missing")
    result = frame.copy()
    industries = result["industry"]
    for feature in tuple(feature_names):
        feature = str(feature).strip()
        if not feature:
            raise ValueError("feature_name_empty")
        direction = -1.0 if feature.startswith("-") else 1.0
        source_name = feature[1:] if feature[:1] in {"-", "+"} else feature
        values = _numeric_column(result, source_name) * direction
        clipped = _five_mad_clip(values)
        demeaned = clipped - clipped.groupby(industries, dropna=False).transform("mean")
        ranked = demeaned.groupby(industries, dropna=False).transform(_zero_one_percentile)
        result[feature] = ranked.replace([np.inf, -np.inf], np.nan)
    return result


def _source_name(feature: str) -> str:
    return str(feature).lstrip("+-")


def _require_frame_contract(
    frame: pd.DataFrame,
    features: Iterable[str],
    *,
    training: bool,
) -> None:
    structural = {"instrument", "industry"}
    if training:
        structural.update({"date", "forward_return_5d"})
    if not structural.issubset(frame.columns):
        raise AlphaUnavailable("alpha_train_contract_missing" if training else "alpha_input_missing")
    missing: set[str] = set()
    for feature in features:
        source = _source_name(feature)
        dependencies = _DERIVED_DEPENDENCIES.get(source, (source,))
        missing.update(name for name in dependencies if name not in frame.columns)
    if missing:
        raise AlphaUnavailable("alpha_input_missing", ",".join(sorted(missing)))


def _preprocess_by_date(
    frame: pd.DataFrame,
    feature_names: Iterable[str],
) -> pd.DataFrame:
    features = tuple(feature_names)
    if "date" not in frame.columns:
        return preprocess_cross_section(frame, features)
    if "industry" not in frame.columns:
        raise ValueError("industry_column_missing")
    result = frame.copy()
    dates = result["date"]
    industries = result["industry"]
    for feature in features:
        feature = str(feature).strip()
        if not feature:
            raise ValueError("feature_name_empty")
        direction = -1.0 if feature.startswith("-") else 1.0
        source_name = feature[1:] if feature[:1] in {"-", "+"} else feature
        values = _numeric_column(result, source_name) * direction
        values = values.replace([np.inf, -np.inf], np.nan)

        date_groups = values.groupby(dates, sort=False, dropna=False)
        medians = date_groups.transform("median")
        deviations = (values - medians).abs()
        mads = deviations.groupby(dates, sort=False, dropna=False).transform(
            "median"
        )
        bounded = values.clip(lower=medians - 5.0 * mads, upper=medians + 5.0 * mads)
        usable_bounds = medians.map(np.isfinite) & mads.map(np.isfinite) & (mads > 1e-12)
        clipped = values.where(~usable_bounds, bounded)

        grouped = clipped.groupby(
            [dates, industries], sort=False, dropna=False
        )
        demeaned = clipped - grouped.transform("mean")
        demeaned_groups = demeaned.groupby(
            [dates, industries], sort=False, dropna=False
        )
        ranks = demeaned_groups.rank(method="average", na_option="keep")
        counts = demeaned_groups.transform("count")
        ranked = (ranks - 1.0) / (counts - 1.0)
        ranked = ranked.where(counts > 1, 0.5).where(demeaned.notna())
        result[feature] = ranked.replace([np.inf, -np.inf], np.nan)
    return result.sort_index()


def _fixed_score_series(
    candidate: F4CandidateV2,
    frame: pd.DataFrame,
) -> pd.Series:
    features = candidate.alpha_spec.input_features
    _require_frame_contract(frame, features, training=False)
    prepared = derive_rule_features(frame, features)
    ranked = _preprocess_by_date(prepared, features)
    score = pd.Series(0.0, index=ranked.index, dtype=float)
    usable = pd.Series(True, index=ranked.index, dtype=bool)
    for name, weight in candidate.alpha_spec.formula:
        values = pd.to_numeric(ranked[name], errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        )
        usable &= values.notna()
        score += values.fillna(0.0) * float(weight)
    return score.where(usable)


def _base_rule_candidates() -> tuple[F4CandidateV2, ...]:
    by_id = {
        candidate.alpha_spec.alpha_id: candidate
        for candidate in build_v2_candidate_registry()
    }
    return tuple(by_id[alpha_id] for alpha_id in BASE_RULE_ALPHA_IDS)


def _base_signal_frame(
    frame: pd.DataFrame,
    alpha_ids: Iterable[str] = BASE_RULE_ALPHA_IDS,
) -> pd.DataFrame:
    requested = tuple(alpha_ids)
    by_id = {
        candidate.alpha_spec.alpha_id: candidate
        for candidate in _base_rule_candidates()
    }
    if not requested or any(alpha_id not in by_id for alpha_id in requested):
        raise AlphaUnavailable("alpha_fit_input_identity_mismatch")
    candidates = tuple(by_id[alpha_id] for alpha_id in requested)
    features = tuple(
        dict.fromkeys(
            feature
            for candidate in candidates
            for feature in candidate.alpha_spec.input_features
        )
    )
    _require_frame_contract(frame, features, training=False)
    prepared = derive_rule_features(frame, features)
    ranked = _preprocess_by_date(prepared, features)
    signals: dict[str, pd.Series] = {}
    for candidate in candidates:
        score = pd.Series(0.0, index=ranked.index, dtype=float)
        usable = pd.Series(True, index=ranked.index, dtype=bool)
        for name, weight in candidate.alpha_spec.formula:
            values = pd.to_numeric(ranked[name], errors="coerce").replace(
                [np.inf, -np.inf], np.nan
            )
            usable &= values.notna()
            score += values.fillna(0.0) * float(weight)
        signals[candidate.alpha_spec.alpha_id] = score.where(usable)
    return pd.DataFrame(signals, index=frame.index)


def _daily_rank_ic_by_date(
    signals: pd.DataFrame,
    target: pd.Series,
    dates: pd.Series,
) -> dict[str, dict[pd.Timestamp, float]]:
    observations: dict[str, dict[pd.Timestamp, float]] = {
        name: {} for name in signals.columns
    }
    working = signals.copy()
    working["__target"] = pd.to_numeric(target, errors="coerce").replace(
        [np.inf, -np.inf], np.nan
    )
    working["__date"] = pd.to_datetime(dates, errors="coerce").dt.normalize()
    for date, cross_section in working.groupby("__date", sort=True):
        target_values = cross_section["__target"]
        for name in signals.columns:
            usable = pd.concat(
                [
                    pd.to_numeric(cross_section[name], errors="coerce"),
                    target_values,
                ],
                axis=1,
            ).replace([np.inf, -np.inf], np.nan).dropna()
            if (
                len(usable) < 20
                or usable.iloc[:, 0].nunique() < 2
                or usable.iloc[:, 1].nunique() < 2
            ):
                continue
            correlation = usable.iloc[:, 0].corr(usable.iloc[:, 1], method="spearman")
            if np.isfinite(correlation):
                observations[name][pd.Timestamp(date).normalize()] = float(correlation)
    return observations


def _daily_rank_ic(
    signals: pd.DataFrame,
    target: pd.Series,
    dates: pd.Series,
) -> dict[str, tuple[float, ...]]:
    dated = _daily_rank_ic_by_date(signals, target, dates)
    return {
        name: tuple(value for _date, value in sorted(observations.items()))
        for name, observations in dated.items()
    }


def _ic_statistics(
    daily_ic: dict[str, tuple[float, ...]],
) -> tuple[dict[str, float], dict[str, float], dict[str, int]]:
    medians: dict[str, float] = {}
    consistencies: dict[str, float] = {}
    directions: dict[str, int] = {}
    for name, observations in daily_ic.items():
        values = np.asarray(observations, dtype=float)
        median = float(np.median(values)) if len(values) else 0.0
        direction = 1 if median >= 0.0 else -1
        consistency = (
            float((np.sign(values) == direction).mean()) if len(values) else 0.0
        )
        medians[name] = median
        consistencies[name] = consistency
        directions[name] = direction
    return medians, consistencies, directions


def _qualified_signals(
    input_signals: tuple[str, ...],
    medians: dict[str, float],
    consistencies: dict[str, float],
) -> tuple[str, ...]:
    return tuple(
        name
        for name in input_signals
        if abs(medians[name]) > 1e-12 and consistencies[name] >= 0.60
    )


def _normalize_weights(raw: dict[str, float]) -> dict[str, float]:
    finite = {
        name: float(value)
        for name, value in raw.items()
        if np.isfinite(float(value)) and float(value) > 0.0
    }
    total = float(sum(finite.values()))
    if not finite or total <= 0.0:
        raise AlphaUnavailable("alpha_train_no_eligible_signals")
    return {name: finite[name] / total for name in sorted(finite)}


def _correlation_cluster_representatives(
    signals: pd.DataFrame,
    signal_names: Iterable[str],
    direction_consistency: dict[str, float],
) -> tuple[str, ...]:
    """Return one stable representative per absolute-correlation component."""

    names = tuple(sorted(dict.fromkeys(str(name) for name in signal_names)))
    if not names:
        raise AlphaUnavailable("alpha_train_no_eligible_signals")
    if any(name not in signals.columns for name in names):
        raise AlphaUnavailable("alpha_fit_input_identity_mismatch")
    correlations = signals.loc[:, names].corr(method="spearman")
    unvisited = set(names)
    representatives: list[str] = []
    while unvisited:
        root = min(unvisited)
        component: set[str] = set()
        pending = [root]
        while pending:
            current = pending.pop()
            if current in component:
                continue
            component.add(current)
            unvisited.discard(current)
            for other in names:
                if other in component:
                    continue
                correlation = correlations.loc[current, other]
                if np.isfinite(correlation) and abs(float(correlation)) >= 0.70:
                    pending.append(other)
        representative = sorted(
            component,
            key=lambda name: (-float(direction_consistency[name]), name),
        )[0]
        representatives.append(representative)
    return tuple(sorted(representatives))


def _chronological_subperiods(
    dates: pd.Series,
) -> tuple[tuple[pd.Timestamp, ...], ...]:
    normalized = tuple(
        sorted(pd.to_datetime(dates, errors="coerce").dropna().dt.normalize().unique())
    )
    if len(normalized) < 4:
        raise AlphaUnavailable("alpha_train_subperiod_insufficient")
    return tuple(
        tuple(pd.Timestamp(date).normalize() for date in part)
        for part in np.array_split(np.asarray(normalized), 4)
    )


def _ensemble_weights(
    candidate: F4CandidateV2,
    signals: pd.DataFrame,
    target: pd.Series,
    dates: pd.Series,
    daily_ic: dict[str, tuple[float, ...]],
    dated_daily_ic: dict[str, dict[pd.Timestamp, float]],
    medians: dict[str, float],
    consistencies: dict[str, float],
) -> tuple[tuple[str, ...], dict[str, int], dict[str, float]]:
    alpha_id = candidate.alpha_spec.alpha_id
    input_signals = candidate.alpha_spec.input_features
    qualified = _qualified_signals(input_signals, medians, consistencies)
    directions = {name: 1 if medians[name] >= 0.0 else -1 for name in qualified}
    if alpha_id == "E1":
        weights: dict[str, float] = {}
        for prefix in ("M", "R", "D", "L"):
            sleeve = tuple(name for name in qualified if name.startswith(prefix))
            if not sleeve:
                raise AlphaUnavailable("alpha_train_family_sleeve_unavailable", prefix)
            weights.update({name: 0.25 / len(sleeve) for name in sleeve})
        selected = tuple(sorted(weights))
        return selected, {name: directions[name] for name in selected}, weights
    if alpha_id == "E2":
        shrunken = {
            name: abs(medians[name]) * len(daily_ic[name]) / (len(daily_ic[name]) + 20.0)
            for name in qualified
        }
        weights = _normalize_weights(shrunken)
        selected = tuple(weights)
        return selected, {name: directions[name] for name in selected}, weights
    if alpha_id == "E3":
        if not qualified:
            raise AlphaUnavailable("alpha_train_no_eligible_signals")
        selected = _correlation_cluster_representatives(
            signals, qualified, consistencies
        )
        weights = {name: 1.0 / len(selected) for name in selected}
        return selected, {name: directions[name] for name in selected}, weights
    if alpha_id != "E4":
        raise AlphaUnavailable("alpha_fit_method_unsupported", alpha_id)

    normalized_dates = pd.to_datetime(dates, errors="coerce").dt.normalize()
    subperiods = _chronological_subperiods(normalized_dates)
    raw_weights: dict[str, float] = {}
    for name in qualified:
        subperiod_medians: list[float] = []
        for subperiod in subperiods:
            dated_values = [
                dated_daily_ic[name][pd.Timestamp(date).normalize()]
                for date in subperiod
                if pd.Timestamp(date).normalize() in dated_daily_ic[name]
            ]
            if not dated_values:
                subperiod_medians = []
                break
            subperiod_medians.append(float(np.median(dated_values)))
        if len(subperiod_medians) != 4:
            continue
        worst_directed = min(directions[name] * value for value in subperiod_medians)
        if worst_directed > 0.0:
            raw_weights[name] = consistencies[name] * worst_directed
    weights = _normalize_weights(raw_weights)
    selected = tuple(weights)
    return selected, {name: directions[name] for name in selected}, weights


def _new_fit(
    *,
    candidate: F4CandidateV2,
    window_id: str,
    fit_start: str,
    fit_end: str,
    input_signals: tuple[str, ...],
    selected_signals: tuple[str, ...],
    directions: dict[str, int],
    weights: dict[str, float],
    medians: dict[str, float],
    consistencies: dict[str, float],
    training_coverage: float,
) -> RuleAlphaFit:
    provisional = RuleAlphaFit(
        candidate_id=candidate.candidate_id,
        alpha_id=candidate.alpha_spec.alpha_id,
        window_id=str(window_id),
        fit_start=fit_start,
        fit_end=fit_end,
        input_signals=input_signals,
        selected_signals=selected_signals,
        directions=dict(directions),
        weights=dict(weights),
        median_rank_ic=dict(medians),
        direction_consistency=dict(consistencies),
        training_coverage=float(training_coverage),
        artifact_hash="",
    )
    completed = replace(
        provisional, artifact_hash=canonical_payload_hash(provisional._payload())
    )
    completed.verify()
    return completed


def _validate_candidate_contract(candidate: F4CandidateV2) -> None:
    try:
        candidate.validate()
    except (TypeError, ValueError, AttributeError) as exc:
        raise AlphaUnavailable("alpha_candidate_contract_invalid", str(exc)) from exc


def _validated_train_core(
    train_panel: pd.DataFrame,
) -> tuple[pd.Series, pd.Series]:
    if not isinstance(train_panel, pd.DataFrame) or train_panel.empty:
        raise AlphaUnavailable("alpha_train_empty")
    _require_frame_contract(train_panel, (), training=True)
    target = pd.to_numeric(
        train_panel["forward_return_5d"], errors="coerce"
    ).replace([np.inf, -np.inf], np.nan)
    if target.notna().sum() < 20 or target.nunique(dropna=True) < 2:
        raise AlphaUnavailable("alpha_train_target_unavailable")
    dates = pd.to_datetime(train_panel["date"], errors="coerce").dt.normalize()
    if dates.isna().any():
        raise AlphaUnavailable("alpha_train_date_invalid")
    observation_keys = pd.DataFrame(
        {
            "date": dates,
            "instrument": train_panel["instrument"].astype(str),
        },
        index=train_panel.index,
    )
    if observation_keys.duplicated(["date", "instrument"], keep=False).any():
        raise AlphaUnavailable("alpha_train_duplicate_observation")
    return target, dates


def prepare_rule_alpha_training_context(
    train_panel: pd.DataFrame,
    *,
    window_id: str,
) -> RuleAlphaTrainingContext:
    """Precompute one reusable, identity-bound ensemble training context."""

    target, dates = _validated_train_core(train_panel)
    ordered = train_panel.copy()
    ordered["date"] = dates
    ordered["instrument"] = ordered["instrument"].astype(str)
    ordered.sort_values(["date", "instrument"], kind="mergesort", inplace=True)
    ordered.reset_index(drop=True, inplace=True)
    target, dates = _validated_train_core(ordered)
    signals = _base_signal_frame(ordered).replace([np.inf, -np.inf], np.nan)
    training_coverage = float(signals.notna().all(axis=1).mean())
    if training_coverage < 0.95:
        raise AlphaUnavailable("alpha_train_coverage_below_0_95")
    dated_daily_ic = _daily_rank_ic_by_date(signals, target, dates)
    if not any(dated_daily_ic.values()):
        raise AlphaUnavailable("alpha_train_rank_ic_unavailable")
    signal_values = signals.to_numpy(dtype="<f8", copy=True)
    target_values = target.to_numpy(dtype="<f8", copy=True)
    date_values = (
        dates.to_numpy(dtype="datetime64[ns]", copy=True)
        .view("<i8")
        .copy()
    )
    instrument_values = tuple(ordered["instrument"].astype(str))
    if any("\n" in value or "\r" in value for value in instrument_values):
        raise AlphaUnavailable("alpha_train_instrument_invalid")
    provisional = RuleAlphaTrainingContext(
        window_id=str(window_id),
        train_identity=_frame_identity(train_panel),
        fit_start=str(pd.Timestamp(dates.min()).date()),
        fit_end=str(pd.Timestamp(dates.max()).date()),
        row_count=len(train_panel),
        input_signals=BASE_RULE_ALPHA_IDS,
        training_coverage=training_coverage,
        artifact_hash="",
        _signal_columns=tuple(signals.columns),
        _signal_shape=tuple(signal_values.shape),
        _signal_bytes=signal_values.tobytes(order="C"),
        _target_bytes=target_values.tobytes(order="C"),
        _date_ns_bytes=date_values.tobytes(order="C"),
        _instrument_blob="\n".join(instrument_values).encode("utf-8"),
        _daily_ic_items=tuple(
            (
                name,
                tuple(
                    (str(pd.Timestamp(date).date()), float(value))
                    for date, value in sorted(observations.items())
                ),
            )
            for name, observations in sorted(dated_daily_ic.items())
        ),
    )
    completed = replace(
        provisional, artifact_hash=canonical_payload_hash(provisional._payload())
    )
    completed.verify()
    return completed


def _verify_training_context(
    context: RuleAlphaTrainingContext,
    train_panel: pd.DataFrame,
    window_id: str,
) -> None:
    if not isinstance(context, RuleAlphaTrainingContext):
        raise AlphaUnavailable("alpha_training_context_invalid")
    context.verify()
    if context.window_id != str(window_id):
        raise AlphaUnavailable("alpha_training_context_window_mismatch")
    if context.train_identity != _frame_identity(train_panel):
        raise AlphaUnavailable("alpha_training_context_identity_mismatch")


def fit_rule_alpha_batch(
    candidates: Iterable[F4CandidateV2],
    train_panel: pd.DataFrame,
    *,
    window_id: str,
) -> tuple[RuleAlphaFit, ...]:
    """Fit a bounded candidate set while sharing one ensemble train context."""

    requested = tuple(candidates)
    for candidate in requested:
        _validate_candidate_contract(candidate)
    context = (
        prepare_rule_alpha_training_context(train_panel, window_id=window_id)
        if any(candidate.family != "qlib" for candidate in requested)
        else None
    )
    return tuple(
        fit_rule_alpha(
            candidate,
            train_panel,
            window_id=window_id,
            training_context=context if candidate.family != "qlib" else None,
            _training_context_preverified=context is not None,
        )
        for candidate in requested
    )


def fit_rule_alpha(
    candidate: F4CandidateV2,
    train_panel: pd.DataFrame,
    *,
    window_id: str,
    training_context: RuleAlphaTrainingContext | None = None,
    _training_context_preverified: bool = False,
) -> RuleAlphaFit:
    """Fit one registered rule alpha using only the supplied train panel."""

    _validate_candidate_contract(candidate)
    if candidate.family == "qlib":
        raise AlphaUnavailable("alpha_fit_method_unsupported", "qlib")
    input_signals = tuple(candidate.alpha_spec.input_features)

    if training_context is not None or candidate.family == "ensemble":
        context = training_context or prepare_rule_alpha_training_context(
            train_panel, window_id=window_id
        )
        if _training_context_preverified:
            context.verify()
            if context.window_id != str(window_id):
                raise AlphaUnavailable("alpha_training_context_window_mismatch")
        else:
            _verify_training_context(context, train_panel, window_id)
        context_signals = (
            input_signals
            if candidate.family == "ensemble"
            else (candidate.alpha_spec.alpha_id,)
        )
        missing = sorted(set(context_signals) - set(context.input_signals))
        if missing:
            raise AlphaUnavailable(
                "alpha_training_context_signal_missing", ",".join(missing)
            )
        signals = context.signal_subset(context_signals)
        target = context.target
        dates = context.dates
        dated_daily_ic = {
            name: dict(observations)
            for name, observations in context.daily_rank_ic.items()
            if candidate.family == "ensemble" and name in input_signals
        }
        training_coverage = float(signals.notna().all(axis=1).mean())
        fit_start = context.fit_start
        fit_end = context.fit_end
    else:
        target, dates = _validated_train_core(train_panel)
        _require_frame_contract(train_panel, input_signals, training=True)
        prepared = derive_rule_features(train_panel, input_signals)
        ranked = _preprocess_by_date(prepared, input_signals)
        signals = ranked.loc[:, input_signals].apply(pd.to_numeric, errors="coerce")
        signals = signals.replace([np.inf, -np.inf], np.nan)
        training_coverage = float(signals.notna().all(axis=1).mean())
        dated_daily_ic = {}
        fit_start = str(pd.Timestamp(dates.min()).date())
        fit_end = str(pd.Timestamp(dates.max()).date())
    required_coverage = max(0.95, float(candidate.alpha_spec.minimum_coverage))
    if training_coverage < required_coverage:
        raise AlphaUnavailable("alpha_train_coverage_below_0_95")

    if candidate.family != "ensemble":
        selected = input_signals
        directions = {name: 1 for name in selected}
        weights = {name: float(weight) for name, weight in candidate.alpha_spec.formula}
        medians = {name: 0.0 for name in input_signals}
        consistencies = {name: 0.0 for name in input_signals}
    else:
        daily_ic = {
            name: tuple(value for _date, value in sorted(observations.items()))
            for name, observations in dated_daily_ic.items()
        }
        medians, consistencies, _learned_directions = _ic_statistics(daily_ic)
        selected, directions, weights = _ensemble_weights(
            candidate,
            signals,
            target,
            dates,
            daily_ic,
            dated_daily_ic,
            medians,
            consistencies,
        )
    normalized_weights = _normalize_weights(weights)
    return _new_fit(
        candidate=candidate,
        window_id=window_id,
        fit_start=fit_start,
        fit_end=fit_end,
        input_signals=input_signals,
        selected_signals=selected,
        directions=directions,
        weights=normalized_weights,
        medians=medians,
        consistencies=consistencies,
        training_coverage=training_coverage,
    )


def score_rule_alpha(
    candidate: F4CandidateV2,
    fit: RuleAlphaFit,
    cross_section: pd.DataFrame,
) -> pd.DataFrame:
    """Score one frame with the immutable fit bound to the same candidate."""

    _validate_candidate_contract(candidate)
    if fit.candidate_id != candidate.candidate_id or fit.alpha_id != candidate.alpha_spec.alpha_id:
        raise AlphaUnavailable("alpha_fit_candidate_identity_mismatch")
    fit.verify()
    if fit.input_signals != tuple(candidate.alpha_spec.input_features):
        raise AlphaUnavailable("alpha_fit_input_identity_mismatch")
    if not isinstance(cross_section, pd.DataFrame) or cross_section.empty:
        raise AlphaUnavailable("alpha_score_empty")

    if candidate.family == "ensemble":
        values = _base_signal_frame(cross_section, fit.selected_signals).loc[
            :, fit.selected_signals
        ]
    else:
        _require_frame_contract(cross_section, fit.selected_signals, training=False)
        prepared = derive_rule_features(cross_section, fit.selected_signals)
        ranked = _preprocess_by_date(prepared, fit.selected_signals)
        values = ranked.loc[:, fit.selected_signals]
    values = values.apply(pd.to_numeric, errors="coerce").replace(
        [np.inf, -np.inf], np.nan
    )
    usable = values.notna().all(axis=1)
    score = pd.Series(0.0, index=values.index, dtype=float)
    for name in fit.selected_signals:
        score += (
            values[name].fillna(0.0)
            * fit.directions[name]
            * fit.weights[name]
        )
    output = cross_section.loc[usable, ["instrument", "industry"]].copy()
    output["score"] = score.loc[usable]
    coverage = len(output) / len(cross_section) if len(cross_section) else 0.0
    required_coverage = max(0.95, float(candidate.alpha_spec.minimum_coverage))
    if coverage < required_coverage:
        raise AlphaUnavailable("alpha_score_coverage_below_0_95")
    if not np.isfinite(output["score"]).all():
        raise AlphaUnavailable("alpha_score_non_finite")
    return output.rename(columns={"instrument": "code"})[["code", "industry", "score"]]


__all__ = [
    "AlphaUnavailable",
    "DERIVED_FEATURE_NAMES",
    "DERIVED_FEATURE_SCHEMA_VERSION",
    "RuleAlphaFit",
    "RuleAlphaTrainingContext",
    "derive_rule_features",
    "fit_rule_alpha",
    "fit_rule_alpha_batch",
    "prepare_rule_alpha_training_context",
    "preprocess_cross_section",
    "score_rule_alpha",
]

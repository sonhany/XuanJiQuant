"""Real-data, research-only F4 walk-forward portfolio validation.

The module is deliberately free of order, paper-account, or execution APIs.
It consumes immutable PIT research inputs and returns JSON-safe evidence only.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import numpy as np
import pandas as pd

from quant.factor.price_volume import PRICE_VOLUME_FACTORS, compute_price_volume
from quant.factor.technical import TECHNICAL_FACTORS, compute_technical
from quant.factor.fundamental import FUNDAMENTAL_FACTORS

from .f4_contracts import F4Blocked, authority_fields
from .f4_candidate_factory import (
    FACTORY_VERSION_V2,
    CandidateUnavailable,
    CandidateWindowContext,
    canonical_payload_hash,
    candidate_factory_id,
    candidate_registry_hash,
    run_v2_nested_window,
)
from .f4_metrics import build_family_diagnostics, calculate_return_metrics
from .f4_alpha_rules import (
    AlphaUnavailable,
    DERIVED_FEATURE_NAMES,
    DERIVED_FEATURE_SCHEMA_VERSION,
    RuleAlphaFit,
    derive_rule_features,
    fit_rule_alpha,
    prepare_rule_alpha_training_context,
    score_rule_alpha,
)
from .f4_alpha_contracts import F4CandidateV2, build_v2_candidate_registry
from .f4_qlib_adapter import QlibAlphaUnavailable, fit_qlib_window
from .f4_v2_publication import (
    F4V2PublicationError,
    REQUIRED_V2_ARTIFACTS,
    begin_v2_publication,
    publication_base_pointer,
    publish_v2_generation,
    write_v2_staging_artifact,
)
from .portfolio import PortfolioPolicy, build_target_weights
from .portfolio_backtest import CostModel, simulate_rebalance
from .walk_forward import F4Window, build_f4_windows


PANEL_SCHEMA_VERSION = "f4-factor-panel-v2"
F4_PIPELINE_VERSION = (
    "f4-real-pipeline-v7-pit-tradable-finite-adv-qlib-sqlite-market"
)
CANDIDATE_SPEC_VERSION = FACTORY_VERSION_V2
ELIGIBLE_FACTORS = tuple(TECHNICAL_FACTORS + PRICE_VOLUME_FACTORS)
F4_CODE_VERSION_FILES = (
    "quant/qlib/features.py",
    "quant/qlib/workflow_bridge.py",
    "quant/qlib/workflow_config.py",
    "quant/strategy/f4_alpha_contracts.py",
    "quant/strategy/f4_alpha_rules.py",
    "quant/strategy/f4_candidate_factory.py",
    "quant/strategy/f4_gate.py",
    "quant/strategy/f4_metrics.py",
    "quant/strategy/f4_qlib_adapter.py",
    "quant/strategy/f4_real_pipeline.py",
    "quant/strategy/portfolio.py",
    "quant/strategy/portfolio_backtest.py",
    "scripts/validate_strategy_portfolios.py",
)


def f4_code_version_identity(
    source_root: Path | str,
    *,
    relative_paths: Iterable[str] = F4_CODE_VERSION_FILES,
) -> dict[str, Any]:
    """Hash the exact source boundary that defines one F4 factory run."""

    root = Path(source_root).resolve()
    requested = tuple(str(value).replace("\\", "/") for value in relative_paths)
    if not requested or len(set(requested)) != len(requested):
        raise F4Blocked("f4_code_version_manifest_invalid")
    files: list[dict[str, str]] = []
    for relative in sorted(requested):
        target = (root / relative).resolve()
        if not target.is_relative_to(root):
            raise F4Blocked("f4_code_version_path_invalid")
        if not target.is_file():
            raise F4Blocked("f4_code_version_source_missing", relative)
        files.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            }
        )
    return {
        "manifest_sha256": canonical_payload_hash({"files": files}),
        "files": files,
    }


@dataclass(frozen=True, slots=True)
class F4InputPaths:
    dataset_root: Path
    adjusted_root: Path
    industry_path: Path
    benchmark_path: Path
    cache_root: Path
    dataset_version: str
    manifest_hash: str
    end_date: str
    industry_version: str = ""
    industry_hash: str = ""
    eligible_instruments: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WindowFactorFit:
    window_id: str
    factors: tuple[str, ...]
    directions: dict[str, int]
    weights: dict[str, float]
    median_rank_ic: dict[str, float]
    direction_consistency: dict[str, float]
    fit_end: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class F4V2PipelineAdapter:
    """Injectable fit/score boundary; the orchestrator still owns lock ordering."""

    fit_rule_batch: Callable[
        [F4Window, tuple[F4CandidateV2, ...], pd.DataFrame, pd.DataFrame, Path],
        Mapping[str, CandidateWindowContext | CandidateUnavailable],
    ]
    fit_qlib: Callable[
        [F4Window, F4CandidateV2, pd.DataFrame, pd.DataFrame, Path],
        CandidateWindowContext,
    ]
    validation_score_loader: Callable[
        [F4Window, F4CandidateV2, CandidateWindowContext, pd.DataFrame],
        Callable[[pd.Timestamp], pd.DataFrame],
    ]
    test_score_loader: Callable[
        [F4Window, F4CandidateV2, CandidateWindowContext, Mapping[str, Any], pd.DataFrame],
        Callable[[pd.Timestamp], pd.DataFrame],
    ]


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _panel_id(paths: F4InputPaths) -> str:
    payload = {
        "schema": PANEL_SCHEMA_VERSION,
        "dataset_version": paths.dataset_version,
        "manifest_hash": paths.manifest_hash,
        "industry_version": paths.industry_version,
        "industry_hash": paths.industry_hash,
        "end_date": paths.end_date,
        "factor_names": ELIGIBLE_FACTORS,
        "derived_feature_schema_version": DERIVED_FEATURE_SCHEMA_VERSION,
        "derived_feature_names": DERIVED_FEATURE_NAMES,
        "eligible_instruments": paths.eligible_instruments,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _industry_records(path: Path) -> dict[str, pd.DataFrame]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        raise F4Blocked("pit_industry_missing", str(exc)) from exc
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in payload.get("records") or []:
        instrument = str(row.get("instrument") or "")
        effective = pd.to_datetime(row.get("effective_from"), errors="coerce")
        if not instrument or pd.isna(effective):
            continue
        grouped.setdefault(instrument, []).append(
            {
                "effective_from": effective,
                "industry": str(row.get("industry_code") or "industry_unknown"),
            }
        )
    return {
        instrument: pd.DataFrame(rows).sort_values("effective_from")
        for instrument, rows in grouped.items()
    }


def _bool_column(frame: pd.DataFrame, name: str, default: bool) -> pd.Series:
    if name not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=bool)
    value = frame[name]
    if value.dtype == bool:
        return value.fillna(default)
    return pd.to_numeric(value, errors="coerce").fillna(int(default)).astype(bool)


def _prepare_symbol_frame(
    path: Path,
    *,
    inputs: F4InputPaths,
    industries: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    try:
        frame = pd.read_json(path)
    except (OSError, ValueError, TypeError) as exc:
        raise F4Blocked("pit_panel_source_invalid", f"{path.name}: {exc}") from exc
    if frame.empty:
        return frame
    required = {"instrument", "datetime", "open", "high", "low", "close", "volume", "amount"}
    if not required.issubset(frame.columns):
        raise F4Blocked("pit_panel_source_invalid", f"{path.name}: required fields missing")
    if "data_version" in frame.columns:
        mismatched = frame["data_version"].astype(str).ne(inputs.dataset_version)
        if mismatched.any():
            raise F4Blocked("pit_panel_version_mismatch", path.name)
    frame["date"] = pd.to_datetime(frame["datetime"], errors="coerce").dt.normalize()
    end_date = pd.Timestamp(inputs.end_date).normalize()
    frame = frame.loc[frame["date"].notna() & (frame["date"] <= end_date)].copy()
    frame.sort_values("date", inplace=True)
    for name in ("open", "high", "low", "close", "volume", "amount"):
        frame[name] = pd.to_numeric(frame[name], errors="coerce")
    frame = derive_rule_features(compute_price_volume(compute_technical(frame)))
    frame["forward_return_5d"] = frame["close"].shift(-5) / frame["close"] - 1.0
    frame["forward_date_5d"] = frame["date"].shift(-5)
    frame["adv20_shares"] = (
        frame["volume"].rolling(20, min_periods=20).mean().shift(1)
    )
    tradable = _bool_column(frame, "tradable", True)
    tradable &= ~_bool_column(frame, "paused", False)
    tradable &= ~_bool_column(frame, "is_st", False)
    tradable &= ~_bool_column(frame, "st_unknown", False)
    tradable &= ~_bool_column(frame, "delisted", False)
    frame["pit_tradable"] = tradable
    frame["limit_up"] = _bool_column(frame, "limit_up", False)
    frame["limit_down"] = _bool_column(frame, "limit_down", False)
    instrument = str(frame["instrument"].iloc[0])
    history = industries.get(instrument)
    if history is None or history.empty:
        frame["industry"] = "industry_unknown"
    else:
        frame = pd.merge_asof(
            frame.sort_values("date"),
            history,
            left_on="date",
            right_on="effective_from",
            direction="backward",
        )
        frame["industry"] = frame["industry"].fillna("industry_unknown")
        frame.drop(columns=["effective_from"], inplace=True)
    columns = [
        "date", "instrument", "open", "high", "low", "close", "volume", "amount",
        "adv20_shares", "pit_tradable", "limit_up", "limit_down", "industry",
        "forward_return_5d", "forward_date_5d", *ELIGIBLE_FACTORS,
        *DERIVED_FEATURE_NAMES,
    ]
    return frame[[name for name in columns if name in frame.columns]]


def build_or_load_factor_panel(
    paths: F4InputPaths,
    *,
    force: bool = False,
) -> pd.DataFrame:
    panel_id = _panel_id(paths)
    target_dir = paths.cache_root / panel_id
    parquet_path = target_dir / "factor_panel.parquet"
    metadata_path = target_dir / "metadata.json"
    if not force and parquet_path.is_file() and metadata_path.is_file():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if (
            metadata.get("panel_id") != panel_id
            or metadata.get("dataset_version") != paths.dataset_version
            or metadata.get("manifest_hash") != paths.manifest_hash
            or metadata.get("industry_version") != paths.industry_version
            or metadata.get("industry_hash") != paths.industry_hash
            or metadata.get("panel_schema_version") != PANEL_SCHEMA_VERSION
            or metadata.get("derived_feature_schema_version")
            != DERIVED_FEATURE_SCHEMA_VERSION
            or metadata.get("derived_feature_names") != list(DERIVED_FEATURE_NAMES)
        ):
            raise F4Blocked("factor_panel_cache_identity_mismatch")
        panel = pd.read_parquet(parquet_path)
        panel.attrs.update(metadata)
        return panel

    industries = _industry_records(paths.industry_path)
    frames: list[pd.DataFrame] = []
    eligible = set(paths.eligible_instruments)
    for source in sorted(paths.adjusted_root.glob("*.json")):
        if eligible and source.stem not in eligible:
            continue
        frame = _prepare_symbol_frame(source, inputs=paths, industries=industries)
        if not frame.empty:
            frames.append(frame)
    if not frames:
        raise F4Blocked("pit_panel_empty")
    panel = pd.concat(frames, ignore_index=True)
    panel.sort_values(["date", "instrument"], inplace=True, ignore_index=True)
    metadata = {
        "panel_id": panel_id,
        "panel_schema_version": PANEL_SCHEMA_VERSION,
        "dataset_version": paths.dataset_version,
        "manifest_hash": paths.manifest_hash,
        "industry_version": paths.industry_version,
        "industry_hash": paths.industry_hash,
        "end_date": paths.end_date,
        "row_count": int(len(panel)),
        "instrument_count": int(panel["instrument"].nunique()),
        "factor_count": len(ELIGIBLE_FACTORS) + len(DERIVED_FEATURE_NAMES),
        "base_factor_count": len(ELIGIBLE_FACTORS),
        "derived_feature_count": len(DERIVED_FEATURE_NAMES),
        "derived_feature_schema_version": DERIVED_FEATURE_SCHEMA_VERSION,
        "derived_feature_names": list(DERIVED_FEATURE_NAMES),
        "eligible_instrument_count": len(paths.eligible_instruments),
        **authority_fields(),
    }
    target_dir.mkdir(parents=True, exist_ok=True)
    temporary = parquet_path.with_name(f"{parquet_path.name}.{os.getpid()}.tmp")
    panel.to_parquet(temporary, index=False, compression="snappy")
    os.replace(temporary, parquet_path)
    _atomic_json(metadata_path, metadata)
    panel.attrs.update(metadata)
    return panel


def compute_daily_rank_ic(
    panel: pd.DataFrame,
    factor_names: Iterable[str],
) -> pd.DataFrame:
    factors = [str(name) for name in factor_names if str(name) in panel.columns]
    rows: list[dict[str, Any]] = []
    for date, frame in panel.groupby("date", sort=True):
        usable = frame[[*factors, "forward_return_5d"]].replace([np.inf, -np.inf], np.nan)
        target = usable["forward_return_5d"]
        if target.notna().sum() < 20 or target.nunique(dropna=True) < 2:
            continue
        ranked = usable[factors].rank(method="average", pct=True)
        target_rank = target.rank(method="average", pct=True)
        variable = ranked.columns[ranked.nunique(dropna=True).gt(1)]
        correlations = ranked[variable].corrwith(target_rank)
        rows.append(
            {
                "date": pd.Timestamp(date).normalize(),
                **{
                    name: (
                        float(correlations.get(name, np.nan))
                        if math.isfinite(correlations.get(name, np.nan))
                        else np.nan
                    )
                    for name in factors
                },
            }
        )
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def fit_window_factors(
    daily_ic: pd.DataFrame,
    window: F4Window,
    *,
    minimum_abs_median_ic: float = 0.02,
    minimum_direction_consistency: float = 0.60,
    minimum_factors: int = 3,
    maximum_factors: int = 10,
) -> WindowFactorFit:
    dates = {pd.Timestamp(value).normalize() for value in window.train_dates}
    training = daily_ic.loc[daily_ic["date"].isin(dates)]
    candidates: list[tuple[float, str, float, float, int]] = []
    for name in training.columns:
        if name == "date":
            continue
        values = pd.to_numeric(training[name], errors="coerce").dropna()
        if values.empty:
            continue
        median = float(values.median())
        if not math.isfinite(median) or abs(median) < minimum_abs_median_ic:
            continue
        direction = 1 if median > 0 else -1
        consistency = float((np.sign(values) == direction).mean())
        if consistency < minimum_direction_consistency:
            continue
        candidates.append((abs(median), name, median, consistency, direction))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    selected = candidates[:maximum_factors]
    if len(selected) < minimum_factors:
        raise F4Blocked(
            "train_factor_insufficient",
            f"window={window.window_id} actual={len(selected)} required={minimum_factors}",
        )
    total = sum(item[0] for item in selected)
    names = tuple(item[1] for item in selected)
    return WindowFactorFit(
        window_id=window.window_id,
        factors=names,
        directions={item[1]: item[4] for item in selected},
        weights={item[1]: item[0] / total for item in selected},
        median_rank_ic={item[1]: item[2] for item in selected},
        direction_consistency={item[1]: item[3] for item in selected},
        fit_end=str(window.train_end.date()),
    )


def _scaled_cost(multiplier: float) -> CostModel:
    base = CostModel()
    scale = max(0.0, float(multiplier))
    return CostModel(
        commission_rate=base.commission_rate * scale,
        min_commission=base.min_commission * scale,
        stamp_tax_rate=base.stamp_tax_rate * scale,
        transfer_fee_rate=base.transfer_fee_rate * scale,
        slippage_rate=base.slippage_rate * scale,
        adv_participation=base.adv_participation,
        lot_size=base.lot_size,
        version=base.version,
    )


def _score_cross_section(
    frame: pd.DataFrame,
    fit: WindowFactorFit | RuleAlphaFit,
    *,
    candidate: F4CandidateV2 | None = None,
) -> pd.DataFrame:
    if isinstance(fit, RuleAlphaFit):
        if candidate is None:
            raise F4Blocked("rule_alpha_candidate_missing")
        return score_rule_alpha(candidate, fit, frame)
    scored = frame[["instrument", "industry", *fit.factors]].copy()
    score = pd.Series(0.0, index=scored.index)
    usable = pd.Series(True, index=scored.index)
    for name in fit.factors:
        values = pd.to_numeric(scored[name], errors="coerce")
        usable &= values.notna()
        percentile = values.rank(method="average", pct=True)
        score += (percentile - 0.5) * fit.directions[name] * fit.weights[name]
    scored["score"] = score
    result = scored.loc[usable, ["instrument", "industry", "score"]].copy()
    return result.rename(columns={"instrument": "code"})


def simulate_f4_window(
    panel: pd.DataFrame,
    benchmark: pd.DataFrame,
    window: F4Window,
    fit: WindowFactorFit | RuleAlphaFit | None,
    *,
    cost_multiplier: float,
    initial_cash: float = 1_000_000.0,
    policy: PortfolioPolicy | None = None,
    candidate: F4CandidateV2 | None = None,
    score_loader: Callable[[pd.Timestamp], pd.DataFrame] | None = None,
) -> dict[str, Any]:
    if fit is None and score_loader is None:
        raise F4Blocked("candidate_score_source_missing")
    policy = policy or PortfolioPolicy()
    cost = _scaled_cost(cost_multiplier)
    all_dates = sorted(pd.Timestamp(value).normalize() for value in panel["date"].unique())
    date_index = {value: index for index, value in enumerate(all_dates)}
    test_dates = [pd.Timestamp(value).normalize() for value in window.test_dates]
    by_date = {date: frame for date, frame in panel.groupby("date", sort=False)}
    benchmark_frame = benchmark.copy()
    benchmark_frame["date"] = pd.to_datetime(benchmark_frame["date"]).dt.normalize()
    benchmark_close = benchmark_frame.set_index("date")["close"].astype(float).to_dict()
    cash = float(initial_cash)
    positions: dict[str, int] = {}
    previous_equity = float(initial_cash)
    portfolio_returns: list[float] = []
    benchmark_returns: list[float] = []
    equity_curve: list[dict[str, Any]] = []
    total_cost = 0.0
    turnover_notional = 0.0
    capacity_rejected = 0.0
    reject_counts: dict[str, int] = {}
    trade_count = 0
    cash_ratios: list[float] = []
    max_target_name_weight = 0.0
    max_target_industry_weight = 0.0
    max_realized_name_weight = 0.0
    max_realized_industry_weight = 0.0
    constraint_violations = 0
    future_data_violations = (
        int(pd.Timestamp(fit.fit_end) > window.train_end) if fit is not None else 0
    )

    previous_benchmark_close: float | None = None
    for offset, current_date in enumerate(test_dates):
        current = by_date.get(current_date)
        if current is None or current.empty:
            continue
        current = current.set_index("instrument", drop=False)
        if offset % policy.rebalance_bars == 0:
            index = date_index.get(current_date, -1)
            signal_date = all_dates[index - 1] if index > 0 else None
            if signal_date is not None and signal_date >= current_date:
                future_data_violations += 1
            signal = by_date.get(signal_date) if signal_date is not None else None
            if signal is not None and not signal.empty:
                if score_loader is not None:
                    candidates = score_loader(signal_date)
                    if (
                        not isinstance(candidates, pd.DataFrame)
                        or list(candidates.columns) != ["code", "industry", "score"]
                        or candidates["code"].astype(str).duplicated().any()
                        or not np.isfinite(
                            pd.to_numeric(candidates["score"], errors="coerce")
                        ).all()
                    ):
                        raise F4Blocked("candidate_score_contract_invalid")
                    # A segment-scoped model has no legal prediction for the
                    # lagged day immediately before that segment.  The exact
                    # empty schema therefore means "do not rebalance yet";
                    # missing rows inside the segment are rejected by the
                    # score loader before reaching this boundary.
                    candidates = candidates.copy()
                    candidates["code"] = candidates["code"].astype(str)
                    candidates["industry"] = candidates["industry"].astype(str)
                    candidates["score"] = pd.to_numeric(
                        candidates["score"], errors="raise"
                    ).astype(float)
                else:
                    candidates = _score_cross_section(
                        signal, fit, candidate=candidate
                    )
                target = build_target_weights(candidates.to_dict("records"), policy)
                target_industry = candidates.set_index("code")["industry"].to_dict()
                industry_targets: dict[str, float] = {}
                for instrument, weight in target.weights.items():
                    industry_name = str(target_industry.get(instrument) or "industry_unknown")
                    industry_targets[industry_name] = industry_targets.get(industry_name, 0.0) + weight
                current_target_name = max(target.weights.values(), default=0.0)
                current_target_industry = max(industry_targets.values(), default=0.0)
                max_target_name_weight = max(max_target_name_weight, current_target_name)
                max_target_industry_weight = max(
                    max_target_industry_weight, current_target_industry
                )
                if current_target_name > policy.max_name_weight + 1e-12:
                    constraint_violations += 1
                if current_target_industry > policy.max_industry_weight + 1e-12:
                    constraint_violations += 1
                market: dict[str, dict[str, Any]] = {}
                for instrument, row in current.iterrows():
                    market[instrument] = {
                        "price": float(row.get("open") or 0.0),
                        "adv20_shares": float(row.get("adv20_shares") or 0.0),
                        "tradable": bool(row.get("pit_tradable")),
                        "pit_tradable": bool(row.get("pit_tradable")),
                        "limit_up": bool(row.get("limit_up")),
                        "limit_down": bool(row.get("limit_down")),
                        "sellable_shares": int(positions.get(instrument, 0)),
                    }
                rebalance = simulate_rebalance(
                    cash=cash,
                    positions=positions,
                    target_weights=target.weights,
                    market=market,
                    cost=cost,
                )
                cash = rebalance.cash
                positions = rebalance.positions
                capacity_rejected += rebalance.capacity_rejected_notional
                for reason, count in rebalance.reject_counts.items():
                    reject_counts[reason] = reject_counts.get(reason, 0) + count
                for fill in rebalance.fills:
                    trade_count += 1
                    notional = fill.quantity * fill.price
                    turnover_notional += notional
                    total_cost += (
                        fill.commission
                        + fill.stamp_tax
                        + fill.transfer_fee
                        + fill.slippage * fill.quantity
                    )
        equity = cash
        industry_values: dict[str, float] = {}
        holding_values: dict[str, float] = {}
        for instrument, quantity in positions.items():
            if quantity <= 0 or instrument not in current.index:
                continue
            row = current.loc[instrument]
            close = float(row.get("close") or 0.0)
            value = quantity * close
            equity += value
            holding_values[instrument] = value
            industry = str(row.get("industry") or "industry_unknown")
            industry_values[industry] = industry_values.get(industry, 0.0) + value
        period_return = equity / previous_equity - 1.0 if previous_equity else 0.0
        portfolio_returns.append(float(period_return))
        previous_equity = equity
        if equity > 0:
            cash_ratios.append(cash / equity)
            max_realized_name_weight = max(
                max_realized_name_weight,
                max((value / equity for value in holding_values.values()), default=0.0),
            )
            max_realized_industry_weight = max(
                max_realized_industry_weight,
                max((value / equity for value in industry_values.values()), default=0.0),
            )
        benchmark_value = benchmark_close.get(current_date)
        if benchmark_value is None:
            benchmark_returns.append(0.0)
        else:
            benchmark_returns.append(
                benchmark_value / previous_benchmark_close - 1.0
                if previous_benchmark_close
                else 0.0
            )
            previous_benchmark_close = benchmark_value
        equity_curve.append(
            {
                "date": str(current_date.date()),
                "equity": float(equity),
                "cash": float(cash),
            }
        )

    metrics = calculate_return_metrics(portfolio_returns, benchmark_returns)
    return {
        "window_id": window.window_id,
        "cost_multiplier": float(cost_multiplier),
        "signal_lag_bars": 1,
        "rebalance_bars": policy.rebalance_bars,
        **metrics,
        "after_cost_return": metrics["total_return"],
        "turnover": turnover_notional / initial_cash,
        "cash_ratio": float(np.mean(cash_ratios)) if cash_ratios else 1.0,
        "total_cost": float(total_cost),
        "capacity_rejected_notional": float(capacity_rejected),
        "reject_counts": reject_counts,
        "trade_count": int(trade_count),
        "max_name_weight": float(max_target_name_weight),
        "max_industry_weight": float(max_target_industry_weight),
        "max_realized_name_weight": float(max_realized_name_weight),
        "max_realized_industry_weight": float(max_realized_industry_weight),
        "constraint_violation_count": int(constraint_violations),
        "future_data_violation_count": int(future_data_violations),
        "equity_curve": equity_curve,
        **authority_fields(),
    }


def load_benchmark(path: Path) -> pd.DataFrame:
    payload = json.loads(path.read_text(encoding="utf-8"))
    frame = pd.DataFrame(payload.get("bars") or [])
    if frame.empty or not {"date", "close"}.issubset(frame.columns):
        raise F4Blocked("benchmark_missing")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    return frame.dropna(subset=["date", "close"]).sort_values("date")


def _load_or_compute_daily_ic(panel: pd.DataFrame, cache_root: Path) -> pd.DataFrame:
    panel_id = str(panel.attrs.get("panel_id") or "")
    if not panel_id:
        raise F4Blocked("factor_panel_cache_identity_mismatch", "panel_id missing")
    cache_dir = cache_root / panel_id
    parquet_path = cache_dir / "daily_rank_ic.parquet"
    metadata_path = cache_dir / "daily_rank_ic_metadata.json"
    if parquet_path.is_file() and metadata_path.is_file():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if (
            metadata.get("panel_id") != panel_id
            or metadata.get("factor_names") != list(ELIGIBLE_FACTORS)
        ):
            raise F4Blocked("rank_ic_cache_identity_mismatch")
        return pd.read_parquet(parquet_path)
    daily_ic = compute_daily_rank_ic(panel, ELIGIBLE_FACTORS)
    if daily_ic.empty:
        raise F4Blocked("rank_ic_empty")
    cache_dir.mkdir(parents=True, exist_ok=True)
    temporary = parquet_path.with_name(f"{parquet_path.name}.{os.getpid()}.tmp")
    daily_ic.to_parquet(temporary, index=False, compression="snappy")
    os.replace(temporary, parquet_path)
    _atomic_json(
        metadata_path,
        {
            "panel_id": panel_id,
            "factor_names": list(ELIGIBLE_FACTORS),
            "date_count": int(daily_ic["date"].nunique()),
            "row_count": int(len(daily_ic)),
            **authority_fields(),
        },
    )
    return daily_ic


def _evaluation_panel(panel: pd.DataFrame, dates: Iterable[pd.Timestamp]) -> pd.DataFrame:
    requested = sorted(pd.Timestamp(value).normalize() for value in dates)
    if not requested:
        return panel.iloc[0:0].copy()
    calendar = sorted(pd.Timestamp(value).normalize() for value in panel["date"].unique())
    first_index = calendar.index(requested[0])
    start = calendar[max(0, first_index - 1)]
    return panel.loc[(panel["date"] >= start) & (panel["date"] <= requested[-1])]


def _simulation_window(window: F4Window, dates: tuple[pd.Timestamp, ...], suffix: str) -> F4Window:
    return F4Window(
        window_id=f"{window.window_id}-{suffix}",
        train_dates=window.train_dates,
        valid_dates=window.valid_dates,
        test_dates=dates,
        purge_bars=window.purge_bars,
        embargo_bars=window.embargo_bars,
    )


def _atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        frame.to_csv(temporary, index=False)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _rule_fit_from_path(path: Path) -> RuleAlphaFit:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return RuleAlphaFit(
        candidate_id=str(payload["candidate_id"]),
        alpha_id=str(payload["alpha_id"]),
        window_id=str(payload["window_id"]),
        fit_start=str(payload["fit_start"]),
        fit_end=str(payload["fit_end"]),
        input_signals=tuple(payload["input_signals"]),
        selected_signals=tuple(payload["selected_signals"]),
        directions=dict(payload["directions"]),
        weights=dict(payload["weights"]),
        median_rank_ic=dict(payload["median_rank_ic"]),
        direction_consistency=dict(payload["direction_consistency"]),
        training_coverage=float(payload["training_coverage"]),
        artifact_hash=str(payload["artifact_hash"]),
    )


def _score_file_loader(
    path: Path,
    panel: pd.DataFrame,
    *,
    minimum_coverage: float,
) -> Callable[[pd.Timestamp], pd.DataFrame]:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise F4Blocked("candidate_score_artifact_io_failed")
    try:
        raw = pd.read_csv(resolved)
    except OSError as exc:
        raise F4Blocked("candidate_score_artifact_io_failed", str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise CandidateUnavailable("candidate_score_schema_invalid", str(exc)) from exc
    date_column = "date" if "date" in raw.columns else "datetime"
    code_column = "code" if "code" in raw.columns else "instrument"
    if date_column not in raw.columns or code_column not in raw.columns or "score" not in raw.columns:
        raise CandidateUnavailable("candidate_score_schema_invalid")
    raw["_date"] = pd.to_datetime(raw[date_column], errors="coerce").dt.normalize()
    raw["_code"] = raw[code_column].astype(str)
    raw["_score"] = pd.to_numeric(raw["score"], errors="coerce")
    if raw[["_date", "_code"]].isna().any().any():
        raise CandidateUnavailable("candidate_score_identity_invalid")
    if raw["_score"].isna().any() or not np.isfinite(raw["_score"]).all():
        raise CandidateUnavailable("candidate_score_nonfinite")
    if raw.duplicated(["_date", "_code"], keep=False).any():
        raise CandidateUnavailable("candidate_score_identity_invalid")
    if not math.isfinite(float(minimum_coverage)) or not 0 < float(minimum_coverage) <= 1:
        raise F4Blocked("candidate_score_coverage_contract_invalid")
    score_start = raw["_date"].min()
    score_end = raw["_date"].max()

    def load(signal_date: pd.Timestamp) -> pd.DataFrame:
        normalized = pd.Timestamp(signal_date).normalize()
        selected = raw.loc[raw["_date"].eq(normalized), ["_code", "_score"]].copy()
        if selected.empty:
            if normalized < score_start or normalized > score_end:
                return pd.DataFrame(columns=["code", "industry", "score"])
            raise CandidateUnavailable("candidate_score_coverage_below_minimum")
        eligible = panel.loc[
            pd.to_datetime(panel["date"]).dt.normalize().eq(normalized)
        ].copy()
        if "pit_tradable" in eligible.columns:
            eligible = eligible.loc[eligible["pit_tradable"].fillna(False).astype(bool)]
        expected_codes = set(eligible["instrument"].astype(str))
        selected = selected.loc[selected["_code"].isin(expected_codes)].copy()
        selected_codes = set(selected["_code"])
        if (
            not expected_codes
            or len(selected_codes) / len(expected_codes) < float(minimum_coverage)
        ):
            raise CandidateUnavailable("candidate_score_coverage_below_minimum")
        if eligible["instrument"].astype(str).duplicated().any():
            raise CandidateUnavailable("candidate_score_identity_invalid")
        industries = eligible[["instrument", "industry"]].copy()
        industries["instrument"] = industries["instrument"].astype(str)
        try:
            selected = selected.merge(
                industries,
                left_on="_code",
                right_on="instrument",
                how="left",
                validate="one_to_one",
            )
        except (KeyError, ValueError) as exc:
            raise CandidateUnavailable("candidate_score_identity_invalid") from exc
        selected["industry"] = selected["industry"].fillna("industry_unknown")
        return selected.rename(columns={"_code": "code", "_score": "score"})[
            ["code", "industry", "score"]
        ]

    return load


def _tradable_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if "pit_tradable" not in frame.columns:
        return frame
    return frame.loc[frame["pit_tradable"].fillna(False).astype(bool)]


def _build_default_v2_adapter(
    *,
    paths: F4InputPaths,
    full_panel: pd.DataFrame,
    stable_artifact_root: Path,
) -> F4V2PipelineAdapter:
    qlib_results: dict[tuple[str, str], Any] = {}
    qlib_provider_uri = (
        paths.dataset_root.parent.parent
        / "qlib_bin"
        / paths.dataset_root.name
    ).resolve()

    def fit_rule_batch_runner(window, candidates, train_panel, valid_panel, artifact_root):
        contexts: dict[str, CandidateWindowContext | CandidateUnavailable] = {}
        ensemble_candidates = tuple(
            candidate for candidate in candidates if candidate.family == "ensemble"
        )
        ensemble_context = None
        ensemble_context_error: CandidateUnavailable | None = None
        if ensemble_candidates:
            try:
                ensemble_context = prepare_rule_alpha_training_context(
                    train_panel, window_id=window.window_id
                )
            except AlphaUnavailable as exc:
                ensemble_context_error = CandidateUnavailable(
                    exc.reason_code, exc.detail
                )
        for candidate in candidates:
            if candidate.family == "ensemble" and ensemble_context_error is not None:
                contexts[candidate.candidate_id] = ensemble_context_error
                continue
            try:
                fit = fit_rule_alpha(
                    candidate,
                    train_panel,
                    window_id=window.window_id,
                    training_context=ensemble_context,
                    _training_context_preverified=ensemble_context is not None,
                )
                candidate_root = artifact_root / candidate.candidate_id
                fit_path = candidate_root / "alpha_fit.json"
                _atomic_json(fit_path, fit.to_dict())
                score_rows: list[pd.DataFrame] = []
                for date, frame in valid_panel.groupby("date", sort=True):
                    eligible_frame = _tradable_rows(frame)
                    if eligible_frame.empty:
                        continue
                    scores = score_rule_alpha(candidate, fit, eligible_frame)
                    scores.insert(0, "date", str(pd.Timestamp(date).date()))
                    score_rows.append(scores)
                if not score_rows:
                    raise CandidateUnavailable("candidate_validation_scores_empty")
                score_path = candidate_root / "validation_scores.csv"
                _atomic_csv(score_path, pd.concat(score_rows, ignore_index=True))
                contexts[candidate.candidate_id] = CandidateWindowContext(
                    window_id=window.window_id,
                    candidate_id=candidate.candidate_id,
                    alpha_spec_hash=canonical_payload_hash(asdict(candidate.alpha_spec)),
                    alpha_fit_path=str(fit_path.resolve()),
                    alpha_fit_hash=fit.artifact_hash,
                    model_artifact_path=None,
                    model_artifact_hash=None,
                    validation_score_path=str(score_path.resolve()),
                    validation_score_hash=_sha256(score_path),
                )
            except AlphaUnavailable as exc:
                contexts[candidate.candidate_id] = CandidateUnavailable(
                    exc.reason_code, exc.detail
                )
            except CandidateUnavailable as exc:
                contexts[candidate.candidate_id] = exc
        return contexts

    def fit_qlib_runner(window, candidate, _train_panel, _valid_panel, artifact_root):
        try:
            result = fit_qlib_window(
                candidate=candidate,
                window=window,
                provider_uri=qlib_provider_uri,
                artifact_root=artifact_root / "qlib",
                instruments="market",
            )
        except QlibAlphaUnavailable as exc:
            raise CandidateUnavailable(exc.reason_code, exc.detail) from exc
        qlib_results[(window.window_id, candidate.candidate_id)] = result
        return CandidateWindowContext(
            window_id=window.window_id,
            candidate_id=candidate.candidate_id,
            alpha_spec_hash=result.alpha_spec_hash,
            alpha_fit_path=str(result.fit_manifest_path.resolve()),
            alpha_fit_hash=result.config_hash,
            model_artifact_path=str(result.model_path.resolve()),
            model_artifact_hash=result.model_sha256,
            validation_score_path=str(result.validation_prediction_path.resolve()),
            validation_score_hash=result.validation_prediction_sha256,
        )

    def validation_loader(_window, candidate, context, panel):
        return _score_file_loader(
            Path(context.validation_score_path),
            panel,
            minimum_coverage=float(candidate.alpha_spec.minimum_coverage),
        )

    def test_loader(window, candidate, context, lock, panel):
        if candidate.family != "qlib":
            fit = _rule_fit_from_path(Path(context.alpha_fit_path))

            def load(signal_date):
                frame = panel.loc[
                    pd.to_datetime(panel["date"]).dt.normalize().eq(
                        pd.Timestamp(signal_date).normalize()
                    )
                ]
                frame = _tradable_rows(frame)
                if frame.empty:
                    return pd.DataFrame(columns=["code", "industry", "score"])
                return score_rule_alpha(candidate, fit, frame)

            return load
        result = qlib_results.get((window.window_id, candidate.candidate_id))
        if result is None:
            from quant.qlib.workflow_bridge import WindowWorkflowResult

            manifest = json.loads(
                Path(context.alpha_fit_path).read_text(encoding="utf-8")
            )
            result = WindowWorkflowResult(
                candidate_id=candidate.candidate_id,
                window_id=window.window_id,
                alpha_spec_hash=context.alpha_spec_hash,
                handler=candidate.alpha_spec.handler,
                model_type=candidate.alpha_spec.model_type,
                seed=int(candidate.alpha_spec.seed),
                recorder_id=str(manifest.get("recorder_id") or ""),
                recorder_identity=str(manifest.get("recorder_identity") or ""),
                config_hash=str(manifest.get("config_hash") or ""),
                model_path=Path(str(context.model_artifact_path)).resolve(),
                model_sha256=str(context.model_artifact_hash),
                validation_prediction_path=Path(
                    context.validation_score_path
                ).resolve(),
                validation_prediction_sha256=context.validation_score_hash,
                validation_coverage=float(manifest.get("validation_coverage") or 0.0),
                artifact_root=stable_artifact_root.resolve(),
                provider_uri=qlib_provider_uri,
                instruments="market",
                segments=(
                    (
                        "test",
                        (
                            str(window.test_dates[0].date()),
                            str(window.test_dates[-1].date()),
                        ),
                    ),
                    (
                        "train",
                        (
                            str(window.train_dates[0].date()),
                            str(window.train_dates[-1].date()),
                        ),
                    ),
                    (
                        "valid",
                        (
                            str(window.valid_dates[0].date()),
                            str(window.valid_dates[-1].date()),
                        ),
                    ),
                ),
                minimum_coverage=float(candidate.alpha_spec.minimum_coverage),
                allowed_segment_dates=tuple(
                    (name, tuple(values))
                    for name, values in sorted(
                        dict(manifest.get("allowed_segment_dates") or {}).items()
                    )
                ),
                allowed_segment_identities=tuple(
                    (
                        name,
                        tuple(tuple(identity) for identity in identities),
                    )
                    for name, identities in sorted(
                        dict(
                            manifest.get("allowed_segment_identities") or {}
                        ).items()
                    )
                ),
                fit_manifest_path=Path(context.alpha_fit_path).resolve(),
            )
        locked_result = replace(
            result,
            model_path=Path(str(context.model_artifact_path)).resolve(),
            model_sha256=str(context.model_artifact_hash),
            validation_prediction_path=Path(context.validation_score_path).resolve(),
            validation_prediction_sha256=context.validation_score_hash,
            fit_manifest_path=Path(context.alpha_fit_path).resolve(),
            artifact_root=stable_artifact_root.resolve(),
        )
        prediction = locked_result.predict_test(lock=lock)
        return _score_file_loader(
            prediction.prediction_path,
            panel,
            minimum_coverage=float(candidate.alpha_spec.minimum_coverage),
        )

    return F4V2PipelineAdapter(
        fit_rule_batch=fit_rule_batch_runner,
        fit_qlib=fit_qlib_runner,
        validation_score_loader=validation_loader,
        test_score_loader=test_loader,
    )


def _aggregate_v2_window_results(
    window_results: list[dict[str, Any]],
    rejected_windows: list[dict[str, str]],
) -> dict[str, list[dict[str, Any]]]:
    leaderboards: list[dict[str, Any]] = []
    locks: list[dict[str, Any]] = []
    test_metrics: list[dict[str, Any]] = []
    rejected = list(rejected_windows)
    for result in window_results:
        window_id = str(result.get("window_id") or "")
        status = str(result.get("window_status") or "")
        leaderboard = result.get("validation_leaderboard")
        if not window_id or not isinstance(leaderboard, dict):
            raise F4Blocked("candidate_window_result_invalid")
        leaderboards.append(leaderboard)
        if status == "candidate_validation_exhausted":
            if result.get("selection_lock") is not None or result.get("test_metrics") is not None:
                raise F4Blocked("candidate_exhausted_window_test_leak")
            rejected.append(
                {
                    "window_id": window_id,
                    "reason_code": "candidate_validation_exhausted",
                }
            )
            continue
        if status != "completed":
            raise F4Blocked("candidate_window_status_invalid")
        lock = result.get("selection_lock")
        metrics = result.get("test_metrics")
        if not isinstance(lock, dict) or not isinstance(metrics, dict):
            raise F4Blocked("candidate_completed_window_evidence_missing")
        locks.append(lock)
        test_metrics.append(
            {
                "window_id": window_id,
                "candidate_id": lock["candidate_id"],
                "metrics": metrics,
                **authority_fields(),
            }
        )
    return {
        "validation_leaderboards": leaderboards,
        "selection_locks": locks,
        "test_metrics": test_metrics,
        "rejected_windows": rejected,
    }


def run_real_f4_pipeline(
    *,
    project_root: Path | str,
    manifest: Mapping[str, Any],
    industry: Mapping[str, Any],
    benchmark: Mapping[str, Any],
    v2_adapter: F4V2PipelineAdapter | None = None,
) -> dict[str, Any]:
    """Run the approved deterministic F4 pipeline without execution authority."""
    started_at = time.perf_counter()
    root = Path(project_root)
    dataset_root = root / "data" / "qlib" / "datasets" / "a_share_6y_daily"
    industry_path = root / "data" / "research" / "industry" / "pit_industry.json"
    benchmark_path = root / "data" / "research" / "benchmarks" / "000300.json"
    completed_symbols = tuple(sorted(str(value) for value in (manifest.get("completed_symbols") or [])))
    if not completed_symbols:
        raise F4Blocked("pit_manifest_completed_symbols_missing")
    paths = F4InputPaths(
        dataset_root=dataset_root,
        adjusted_root=dataset_root / "adjusted",
        industry_path=industry_path,
        benchmark_path=benchmark_path,
        cache_root=root / "data" / "research" / "f4" / "cache",
        dataset_version=str(manifest.get("dataset_version") or ""),
        manifest_hash=str(manifest.get("manifest_content_sha256") or ""),
        end_date=str(manifest.get("end_date") or ""),
        industry_version=str(industry.get("version") or ""),
        industry_hash=_sha256(industry_path) if industry_path.is_file() else "",
        eligible_instruments=completed_symbols,
    )
    if not paths.dataset_version or not paths.manifest_hash or not paths.end_date:
        raise F4Blocked("pit_manifest_identity_missing")
    if str(industry.get("version") or "") == "" or str(benchmark.get("version") or "") == "":
        raise F4Blocked("f4_reference_identity_missing")

    registry = build_v2_candidate_registry()
    registry_hash = candidate_registry_hash(registry)
    factory_identity = {
        "pipeline_version": F4_PIPELINE_VERSION,
        "code_version": f4_code_version_identity(
            Path(__file__).resolve().parents[2]
        ),
        "dataset_version": paths.dataset_version,
        "manifest_hash": paths.manifest_hash,
        "end_date": paths.end_date,
        "industry_version": paths.industry_version,
        "industry_hash": paths.industry_hash,
        "benchmark_version": str(benchmark.get("version") or ""),
    }
    factory_run_id = candidate_factory_id(factory_identity, registry)
    factory_parent = root / "data" / "research" / "f4" / "factory-v2"
    factory_dir = factory_parent / factory_run_id
    try:
        publication_handle = begin_v2_publication(
            root, factory_run_id=factory_run_id
        )
    except F4V2PublicationError as exc:
        raise F4Blocked(
            "candidate_factory_artifact_integrity_failed", str(exc)
        ) from exc
    if factory_dir.is_dir():
        try:
            publication = publish_v2_generation(publication_handle)
            report = dict(publication.get("factory_report") or {})
            pipeline_result = report.get("pipeline_result")
            if (
                not isinstance(pipeline_result, dict)
                or report.get("pipeline_result_sha256")
                != canonical_payload_hash(pipeline_result)
                or pipeline_result.get("factory_run_id") != factory_run_id
                or pipeline_result.get("promotion_state") != "research_only"
                or pipeline_result.get("execution_authority") is not False
            ):
                raise F4V2PublicationError("f4_v2_pipeline_result_invalid")
            publication_summary = {
                key: value
                for key, value in publication.items()
                if key != "factory_report"
            }
            return {
                **pipeline_result,
                "factory_no_op": True,
                "factory_publication": publication_summary,
            }
        except F4V2PublicationError as exc:
            raise F4Blocked(
                "candidate_factory_artifact_integrity_failed", str(exc)
            ) from exc

    panel = build_or_load_factor_panel(paths)
    benchmark_frame = load_benchmark(paths.benchmark_path)
    calendar = tuple(benchmark_frame["date"].drop_duplicates().sort_values())
    windows = build_f4_windows(calendar)

    definitions: list[dict[str, Any]] = []
    rejected_windows: list[dict[str, str]] = []
    contexts: dict[str, F4Window] = {}
    for window in windows:
        definition = window.to_dict()
        selection_slice = panel.loc[
            panel["date"].isin((*window.train_dates, *window.valid_dates))
        ]
        industry_coverage = float(
            selection_slice["industry"].ne("industry_unknown").mean()
        ) if not selection_slice.empty else 0.0
        definition["selection_industry_coverage"] = industry_coverage
        if industry_coverage < 0.95:
            definition["status"] = "window_rejected"
            definition["reason_code"] = "pit_industry_missing"
            rejected_windows.append(
                {"window_id": window.window_id, "reason_code": "pit_industry_missing"}
            )
            definitions.append(definition)
            continue
        definition["status"] = "completed"
        definitions.append(definition)
        contexts[window.window_id] = window

    stable_lock_root = factory_parent / "locks" / factory_run_id
    stable_lock_root.mkdir(parents=True, exist_ok=True)
    stable_artifact_root = factory_parent / "locked-artifacts"
    active_adapter = v2_adapter or _build_default_v2_adapter(
        paths=paths,
        full_panel=panel,
        stable_artifact_root=stable_artifact_root,
    )
    temporary_factory = publication_handle.staging_dir
    try:
        write_v2_staging_artifact(
            publication_handle,
            "registry.json",
            {
                "factory_run_id": factory_run_id,
                "factory_version": FACTORY_VERSION_V2,
                "candidate_registry_hash": registry_hash,
                "candidate_count": len(registry),
                "input_identity": factory_identity,
                "candidates": [candidate.to_dict() for candidate in registry],
                **authority_fields(),
            },
        )

        window_results: list[dict[str, Any]] = []
        for window_id, window in contexts.items():
            train_panel = _tradable_rows(
                panel.loc[panel["date"].isin(window.train_dates)]
            ).copy()
            valid_panel = _evaluation_panel(panel, window.valid_dates)
            attempt_root = (
                factory_parent / "attempts" / factory_run_id / window_id
            ).resolve()

            def fit_batch_runner(active_candidates, *, _window=window):
                return active_adapter.fit_rule_batch(
                    _window,
                    tuple(active_candidates),
                    train_panel,
                    valid_panel,
                    attempt_root,
                )

            def fit_runner(candidate, *, _window=window):
                return active_adapter.fit_qlib(
                    _window, candidate, train_panel, valid_panel, attempt_root
                )

            def validation_runner(candidate, context, *, _window=window):
                loader = active_adapter.validation_score_loader(
                    _window, candidate, context, valid_panel
                )
                result = simulate_f4_window(
                    valid_panel,
                    benchmark_frame,
                    _simulation_window(_window, _window.valid_dates, "validation"),
                    None,
                    cost_multiplier=1.0,
                    policy=candidate.portfolio_policy,
                    candidate=candidate,
                    score_loader=loader,
                )
                result["window_id"] = _window.window_id
                result["candidate_id"] = candidate.candidate_id
                result["after_cost_excess_return"] = result.get("excess_return", 0.0)
                return result

            def test_runner(candidate, context, lock, *, _window=window):
                test_panel = _evaluation_panel(panel, _window.test_dates)
                loader = active_adapter.test_score_loader(
                    _window, candidate, context, lock, test_panel
                )
                test_industry_coverage = float(
                    test_panel["industry"].ne("industry_unknown").mean()
                ) if not test_panel.empty else 0.0
                outputs: dict[str, dict[str, Any]] = {}
                for multiplier in (1.0, 1.5, 2.0):
                    result = simulate_f4_window(
                        test_panel,
                        benchmark_frame,
                        _window,
                        None,
                        cost_multiplier=multiplier,
                        policy=candidate.portfolio_policy,
                        candidate=candidate,
                        score_loader=loader,
                    )
                    result["candidate_context"] = context.to_dict()
                    result["candidate_id"] = candidate.candidate_id
                    result["portfolio_policy"] = asdict(candidate.portfolio_policy)
                    result["test_industry_coverage"] = test_industry_coverage
                    outputs[f"{multiplier:.1f}"] = result
                return outputs

            window_results.append(
                run_v2_nested_window(
                    factory_run_id=factory_run_id,
                    window=window,
                    candidates=registry,
                    fit_runner=fit_runner,
                    fit_batch_runner=fit_batch_runner,
                    validation_runner=validation_runner,
                    test_runner=test_runner,
                    stable_lock_root=stable_lock_root,
                    stable_artifact_root=stable_artifact_root,
                )
            )

        aggregated_windows = _aggregate_v2_window_results(
            window_results,
            rejected_windows,
        )

        nested = {
            "factory_version": FACTORY_VERSION_V2,
            "factory_run_id": factory_run_id,
            "candidate_registry_hash": registry_hash,
            "candidate_count": len(registry),
            "candidate_factory_status": "completed",
            "registry": [candidate.to_dict() for candidate in registry],
            "validation_leaderboards": aggregated_windows[
                "validation_leaderboards"
            ],
            "selection_locks": aggregated_windows["selection_locks"],
            "test_metrics": aggregated_windows["test_metrics"],
            "rejected_windows": aggregated_windows["rejected_windows"],
            **authority_fields(),
        }
        write_v2_staging_artifact(
            publication_handle,
            "candidate_selection_locks.json",
            {
                "factory_run_id": factory_run_id,
                "locks": nested["selection_locks"],
                "test_access_rule": "persistent_lock_hash_verified_before_current_window_test",
                **authority_fields(),
            },
        )
        write_v2_staging_artifact(
            publication_handle,
            "validation_leaderboards.json",
            {
                "factory_run_id": factory_run_id,
                "leaderboards": nested["validation_leaderboards"],
                **authority_fields(),
            },
        )

        validation_metrics: list[dict[str, Any]] = []
        for leaderboard in nested["validation_leaderboards"]:
            selected = next(
                (row for row in leaderboard["candidates"] if row.get("selected")),
                None,
            )
            if selected:
                validation_metrics.append(
                    {
                        "window_id": leaderboard["window_id"],
                        "candidate_id": selected["candidate_id"],
                        **dict(selected.get("metrics") or {}),
                    }
                )
        stress_windows: dict[str, list[dict[str, Any]]] = {
            "1.0": [], "1.5": [], "2.0": []
        }
        for item in nested["test_metrics"]:
            for multiplier, metrics in dict(item.get("metrics") or {}).items():
                stress_windows[multiplier].append(dict(metrics))

        stress_metrics: dict[str, dict[str, Any]] = {}
        for multiplier, rows in stress_windows.items():
            stress_metrics[multiplier] = {
                "window_metrics": rows,
                "window_count": len(rows),
                "excess_return": float(sum(float(row.get("excess_return") or 0.0) for row in rows)),
                "after_cost_return": float(sum(float(row.get("after_cost_return") or 0.0) for row in rows)),
                "total_cost": float(sum(float(row.get("total_cost") or 0.0) for row in rows)),
                "trade_count": int(sum(int(row.get("trade_count") or 0) for row in rows)),
                **authority_fields(),
            }

        selected_policies = [
            {
                "window_id": lock["window_id"],
                **asdict(next(candidate for candidate in registry if candidate.candidate_id == lock["candidate_id"]).portfolio_policy),
                "candidate_id": lock["candidate_id"],
                "lock_hash": lock["lock_hash"],
                "policy_hash": canonical_payload_hash(
                    asdict(next(candidate for candidate in registry if candidate.candidate_id == lock["candidate_id"]).portfolio_policy)
                ),
            }
            for lock in nested["selection_locks"]
        ]
        factor_fits = [
            {
                "window_id": lock["window_id"],
                "candidate_id": lock["candidate_id"],
                "alpha_spec_hash": lock["alpha_spec_hash"],
                "alpha_fit_path": lock["alpha_fit_path"],
                "alpha_fit_hash": lock["alpha_fit_hash"],
                "alpha_fit_artifact_hash": lock["alpha_fit_artifact_hash"],
            }
            for lock in nested["selection_locks"]
        ]
        model_artifacts = [
            {
                "window_id": lock["window_id"],
                "candidate_id": lock["candidate_id"],
                "model_artifact_path": lock["model_artifact_path"],
                "model_artifact_hash": lock["model_artifact_hash"],
            }
            for lock in nested["selection_locks"]
            if lock.get("model_artifact_path") is not None
        ]
        pipeline_result = {
            "pipeline_version": F4_PIPELINE_VERSION,
            "factory_run_id": factory_run_id,
            "candidate_factory_status": nested["candidate_factory_status"],
            "candidate_count": len(registry),
            "panel": {
                key: value for key, value in panel.attrs.items() if key != "execution_authority"
            } | authority_fields(),
            "window_definitions": definitions,
            "candidate_spec": {
                "version": CANDIDATE_SPEC_VERSION,
                "factory_run_id": factory_run_id,
                "eligible_factors": list(ELIGIBLE_FACTORS),
                "excluded_factors": {name: "financial_pit_missing" for name in FUNDAMENTAL_FACTORS},
                "selection": {
                    "minimum_abs_median_rank_ic": 0.02,
                    "minimum_direction_consistency": 0.60,
                    "minimum_factors": 3,
                    "maximum_factors": 10,
                    "fit_scope": "train_only",
                    "candidate_scope": "current_window_validation_only",
                    "test_scope": "locked_winner_only",
                },
                "registry": [candidate.to_dict() for candidate in registry],
                "factor_fits": factor_fits,
                "selected_policies": selected_policies,
                "selection_locks": nested["selection_locks"],
                "rejected_windows": nested["rejected_windows"],
                **authority_fields(),
            },
            "portfolio_policy": {
                "version": "f4-standard-top10-policy-v2",
                "max_position_count": 10,
                "target_gross_exposure": 0.95,
                "selected_by_window": selected_policies,
                **authority_fields(),
            },
            "cost_model": asdict(CostModel()) | authority_fields(),
            "validation_metrics": validation_metrics,
            "window_metrics": stress_windows["1.0"],
            "stress_metrics": stress_metrics,
            "candidate_factory": nested,
            **authority_fields(),
        }
        write_v2_staging_artifact(
            publication_handle,
            "window_definitions.json",
            {
                "factory_run_id": factory_run_id,
                "windows": definitions,
                **authority_fields(),
            },
        )
        write_v2_staging_artifact(
            publication_handle,
            "alpha_fits.json",
            {
                "factory_run_id": factory_run_id,
                "fits": factor_fits,
                **authority_fields(),
            },
        )
        write_v2_staging_artifact(
            publication_handle,
            "model_artifacts.json",
            {
                "factory_run_id": factory_run_id,
                "models": model_artifacts,
                **authority_fields(),
            },
        )
        write_v2_staging_artifact(
            publication_handle,
            "test_window_metrics.json",
            {
                "factory_run_id": factory_run_id,
                "windows": nested["test_metrics"],
                **authority_fields(),
            },
        )
        write_v2_staging_artifact(
            publication_handle,
            "cost_stress_metrics.json",
            {
                "factory_run_id": factory_run_id,
                "multipliers": stress_metrics,
                **authority_fields(),
            },
        )
        rows_by_candidate: dict[str, list[dict[str, Any]]] = {
            candidate.candidate_id: [] for candidate in registry
        }
        for leaderboard in nested["validation_leaderboards"]:
            for row in leaderboard.get("candidates") or []:
                candidate_id = str(row.get("candidate_id") or "")
                if candidate_id in rows_by_candidate:
                    rows_by_candidate[candidate_id].append(dict(row))
        candidate_statuses = []
        for candidate in registry:
            rows = rows_by_candidate[candidate.candidate_id]
            available = any(row.get("eligible") is True for row in rows)
            reasons = sorted(
                str(row.get("reason_code") or "")
                for row in rows
                if row.get("reason_code")
            )
            candidate_statuses.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "family": candidate.family,
                    "available": available,
                    "reason_code": "" if available or not reasons else reasons[0],
                }
            )
        family_diagnostics = build_family_diagnostics(
            registry, candidate_statuses, nested["selection_locks"]
        )
        write_v2_staging_artifact(
            publication_handle,
            "family_diagnostics.json",
            {
                "factory_run_id": factory_run_id,
                "families": family_diagnostics,
                **authority_fields(),
            },
        )
        family_status = {
            family: (
                "unavailable"
                if values["unavailable"] and not values["validation_wins"]
                else "available"
            )
            for family, values in family_diagnostics.items()
        }
        write_v2_staging_artifact(
            publication_handle,
            "factory_report.json",
            {
                "factory_run_id": factory_run_id,
                "factory_version": FACTORY_VERSION_V2,
                "candidate_registry_hash": registry_hash,
                "input_identity": factory_identity,
                "candidate_factory_status": nested["candidate_factory_status"],
                "candidate_count": len(registry),
                "family_count": len(family_diagnostics),
                "selected_window_count": len(nested["selection_locks"]),
                "runtime_seconds": max(0.0, time.perf_counter() - started_at),
                "family_status": family_status,
                "aggregate_metrics": {
                    multiplier: {
                        key: value
                        for key, value in metrics.items()
                        if key != "window_metrics"
                    }
                    for multiplier, metrics in stress_metrics.items()
                },
                "gate_version": "f4-gate-v4",
                "failure_reasons": [
                    item["reason_code"] for item in nested["rejected_windows"]
                ],
                "publication_base_pointer": publication_base_pointer(
                    publication_handle
                ),
                "artifact_hashes": {
                    name: _sha256(temporary_factory / name)
                    for name in REQUIRED_V2_ARTIFACTS
                    if name != "factory_report.json"
                },
                "pipeline_result": pipeline_result,
                "pipeline_result_sha256": canonical_payload_hash(pipeline_result),
                **authority_fields(),
            },
        )
        publication = publish_v2_generation(publication_handle)
        publication_summary = {
            key: value
            for key, value in publication.items()
            if key != "factory_report"
        }
        return {**pipeline_result, "factory_publication": publication_summary}
    except F4V2PublicationError as exc:
        if temporary_factory.exists() and temporary_factory.parent == factory_parent:
            shutil.rmtree(temporary_factory, ignore_errors=True)
        raise F4Blocked("f4_v2_publication_failed", str(exc)) from exc
    except Exception:
        if temporary_factory.exists() and temporary_factory.parent == factory_parent:
            shutil.rmtree(temporary_factory, ignore_errors=True)
        raise

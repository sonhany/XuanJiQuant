"""Reusable factor evaluation analytics.

The functions here deliberately operate on plain pandas DataFrames so the
offline evaluator, tests, and future workers can share the same metrics without
coupling to API runners.
"""

from __future__ import annotations

import math
from typing import Iterable

import numpy as np
import pandas as pd


def _numeric(value, default: float = 0.0) -> float:
    try:
        out = float(value)
        return default if math.isnan(out) or math.isinf(out) else out
    except Exception:
        return default


def build_evaluation_metadata(multi_klines: dict, *, lookback_bars: int, fwd_horizons: list[int]) -> dict:
    dates: list[str] = []
    bar_counts: list[int] = []
    for df in (multi_klines or {}).values():
        if df is None or getattr(df, "empty", True) or "date" not in df.columns:
            continue
        ds = [str(d).replace("-", "")[:8] for d in df["date"].tolist() if str(d)]
        ds = [d for d in ds if len(d) == 8 and d.isdigit()]
        if ds:
            dates.extend(ds)
            bar_counts.append(len(ds))
    return {
        "data_start_date": min(dates) if dates else "",
        "data_end_date": max(dates) if dates else "",
        "latest_kline_date": max(dates) if dates else "",
        "lookback_bars": int(lookback_bars),
        "fwd_horizons": [int(h) for h in fwd_horizons],
        "min_bars_per_stock": min(bar_counts) if bar_counts else 0,
        "max_bars_per_stock": max(bar_counts) if bar_counts else 0,
    }


def build_factor_forward_frame(
    multi_factor: dict,
    multi_klines: dict,
    factor_names: Iterable[str],
    fwd_horizons: Iterable[int],
    *,
    tail_rows_per_stock: int | None = None,
) -> pd.DataFrame:
    rows = []
    factor_names = list(factor_names)
    fwd_horizons = [int(h) for h in fwd_horizons]
    for code, fdf in (multi_factor or {}).items():
        kdf = (multi_klines or {}).get(code)
        if fdf is None or kdf is None or fdf.empty or kdf.empty:
            continue
        if "date" not in fdf.columns or "date" not in kdf.columns or "close" not in kdf.columns:
            continue
        fdf_s = fdf.sort_values("date").reset_index(drop=True).copy()
        kdf_s = kdf.sort_values("date").reset_index(drop=True).copy()
        cols = [c for c in factor_names if c in fdf_s.columns]
        if not cols:
            continue
        kdf_s["close"] = pd.to_numeric(kdf_s["close"], errors="coerce")
        for h in fwd_horizons:
            kdf_s[f"fwd_{h}"] = kdf_s["close"].pct_change(h).shift(-h)
        merged = fdf_s[["date"] + cols].merge(
            kdf_s[["date"] + [f"fwd_{h}" for h in fwd_horizons]],
            on="date",
            how="left",
        )
        if tail_rows_per_stock and tail_rows_per_stock > 0:
            merged = merged.tail(int(tail_rows_per_stock)).copy()
        merged["code"] = str(code)
        rows.append(merged)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def group_and_long_short_returns(
    long_df: pd.DataFrame,
    factor_name: str,
    *,
    horizon: int,
    n_groups: int = 5,
    cost_bps: float = 20.0,
) -> dict:
    fwd_col = f"fwd_{int(horizon)}"
    if long_df is None or long_df.empty or factor_name not in long_df.columns or fwd_col not in long_df.columns:
        return {"groups": {}, "long_short": {}, "long_short_after_cost": {}, "turnover": 0.0}

    df = long_df[["date", "code", factor_name, fwd_col]].copy()
    df[factor_name] = pd.to_numeric(df[factor_name], errors="coerce")
    df[fwd_col] = pd.to_numeric(df[fwd_col], errors="coerce")
    df = df.dropna(subset=[factor_name, fwd_col])
    if df.empty:
        return {"groups": {}, "long_short": {}, "long_short_after_cost": {}, "turnover": 0.0}

    spreads: list[float] = []
    top_returns: list[float] = []
    bottom_returns: list[float] = []
    group_returns: dict[int, list[float]] = {i: [] for i in range(1, n_groups + 1)}
    top_sets: list[set[str]] = []

    for _date, grp in df.groupby("date"):
        if len(grp) < max(3, n_groups):
            continue
        ranked = grp.sort_values(factor_name, ascending=True).reset_index(drop=True)
        try:
            ranked["group"] = pd.qcut(ranked.index + 1, q=n_groups, labels=False, duplicates="drop") + 1
        except ValueError:
            continue
        for group_id, g in ranked.groupby("group"):
            group_returns[int(group_id)].append(float(g[fwd_col].mean()))
        bottom = ranked[ranked["group"] == ranked["group"].min()]
        top = ranked[ranked["group"] == ranked["group"].max()]
        if top.empty or bottom.empty:
            continue
        top_ret = float(top[fwd_col].mean())
        bottom_ret = float(bottom[fwd_col].mean())
        top_returns.append(top_ret)
        bottom_returns.append(bottom_ret)
        spreads.append(top_ret - bottom_ret)
        top_sets.append(set(str(c) for c in top["code"].tolist()))

    def _summary(vals: list[float]) -> dict:
        if not vals:
            return {"mean_return": 0.0, "win_rate": 0.0, "n_periods": 0}
        arr = np.asarray(vals, dtype=float)
        return {
            "mean_return": round(float(np.nanmean(arr)), 6),
            "win_rate": round(float(np.nanmean(arr > 0)), 4),
            "n_periods": int(np.isfinite(arr).sum()),
        }

    turnovers = []
    for prev, cur in zip(top_sets, top_sets[1:]):
        denom = max(len(prev | cur), 1)
        turnovers.append(1 - len(prev & cur) / denom)
    turnover = float(np.nanmean(turnovers)) if turnovers else 0.0
    cost = turnover * (float(cost_bps) / 10000.0)
    after_cost = [s - cost for s in spreads]

    groups = {str(k): _summary(v) for k, v in group_returns.items()}
    groups["top"] = _summary(top_returns)
    groups["bottom"] = _summary(bottom_returns)
    return {
        "groups": groups,
        "long_short": _summary(spreads),
        "long_short_after_cost": _summary(after_cost),
        "turnover": round(turnover, 6),
        "cost_bps": float(cost_bps),
    }


def factor_correlation_top(
    multi_factor: dict,
    factor_names: Iterable[str],
    *,
    top_n: int = 3,
    tail_rows_per_stock: int | None = None,
) -> dict:
    rows = []
    factor_names = list(factor_names)
    for code, fdf in (multi_factor or {}).items():
        if fdf is None or getattr(fdf, "empty", True):
            continue
        cols = [c for c in factor_names if c in fdf.columns]
        if not cols:
            continue
        sub = fdf[cols].tail(int(tail_rows_per_stock)).copy() if tail_rows_per_stock else fdf[cols].copy()
        sub["code"] = str(code)
        rows.append(sub)
    if not rows:
        return {name: [] for name in factor_names}

    df = pd.concat(rows, ignore_index=True)
    for col in factor_names:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    min_obs = min(20, max(3, len(df) // 10))
    usable_cols = [
        c for c in factor_names
        if c in df.columns and df[c].notna().sum() >= min_obs and df[c].nunique(dropna=True) > 1
    ]
    if not usable_cols:
        return {name: [] for name in factor_names}
    corr = df[usable_cols].corr(method="spearman")
    out: dict[str, list[dict]] = {}
    for name in factor_names:
        peers = []
        if name in corr.columns:
            for peer, value in corr[name].drop(labels=[name], errors="ignore").dropna().items():
                peers.append({"factor": peer, "correlation": round(_numeric(value), 6)})
        peers.sort(key=lambda x: abs(x["correlation"]), reverse=True)
        out[name] = peers[:top_n]
    return out

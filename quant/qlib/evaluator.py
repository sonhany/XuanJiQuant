from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def promotion_status(metrics: dict[str, Any]) -> str:
    from .promotion_gate import evaluate_signal_stage

    rank_ic = float(metrics.get("rank_ic", float("-inf")))
    result = evaluate_signal_stage(
        quality_passed=True,
        signal_metrics={
            "window_count": 4,
            "median_rank_ic": rank_ic,
            "median_icir": float(metrics.get("icir", float("-inf"))),
            "positive_rank_ic_ratio": 1.0
            if metrics.get("segment_sign_consistent")
            else 0.0,
            "aggregate_after_cost_long_short": float(
                metrics.get("after_cost_long_short", 0)
            ),
            "aggregate_sharpe": float(metrics.get("sharpe", float("-inf"))),
            "max_drawdown": float(metrics.get("max_drawdown", float("-inf"))),
            "worst_rank_ic": rank_ic,
        },
    )
    return result["status"]


def evaluate_cross_section(
    prediction: pd.Series,
    label: pd.Series,
    *,
    cost_bps: float = 20.0,
    quantile: float = 0.2,
) -> dict[str, Any]:
    frame = pd.concat(
        [prediction.rename("score"), label.rename("label")],
        axis=1,
    ).dropna()
    if frame.empty:
        raise ValueError("prediction/label overlap is empty")
    date_level = "datetime" if "datetime" in frame.index.names else frame.index.names[-1]
    daily_ic = frame.groupby(level=date_level).apply(
        lambda group: group["score"].corr(group["label"], method="spearman")
    ).dropna()
    spread_rows = []
    for _, group in frame.groupby(level=date_level):
        ordered = group.sort_values("score")
        count = max(1, int(len(ordered) * quantile))
        spread_rows.append(
            float(ordered["label"].tail(count).mean() - ordered["label"].head(count).mean())
        )
    spread = pd.Series(spread_rows, dtype=float)
    after_cost = spread - float(cost_bps) / 10000.0
    equity = (1.0 + after_cost.fillna(0)).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    volatility = float(after_cost.std(ddof=0))
    sharpe = (
        float(after_cost.mean() / volatility * np.sqrt(252 / 5))
        if volatility > 0
        else 0.0
    )
    ic_std = float(daily_ic.std(ddof=0))
    rank_ic = float(daily_ic.mean()) if len(daily_ic) else 0.0
    return {
        "rank_ic": rank_ic,
        "ic_std": ic_std,
        "icir": rank_ic / ic_std if ic_std > 0 else 0.0,
        "ic_positive_ratio": float((daily_ic > 0).mean()) if len(daily_ic) else 0.0,
        "after_cost_long_short": float(after_cost.sum()),
        "sharpe": sharpe,
        "max_drawdown": float(drawdown.min()) if len(drawdown) else 0.0,
        "periods": int(len(spread)),
    }

"""组合级风险预算 — VaR/CVaR/相关性约束。

在 PortfolioManager 之上叠加风险约束，确保组合整体风险可控。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class RiskBudget:
    """组合风险预算约束。"""
    max_var: float = 0.05       # 最大 VaR (95%)
    max_cvar: float = 0.08      # 最大 CVaR (95%)
    max_corr: float = 0.7       # 任意两策略最大相关性
    max_single_weight: float = 0.5  # 单策略最大权重
    min_diversification: float = 1.5  # 最小分散化比率


def compute_var(returns: pd.Series, confidence: float = 0.95) -> float:
    """历史模拟法 VaR。"""
    if returns is None or returns.empty:
        return 0.0
    return float(-np.percentile(returns.dropna(), (1 - confidence) * 100))


def compute_cvar(returns: pd.Series, confidence: float = 0.95) -> float:
    """条件 VaR (Expected Shortfall)。"""
    if returns is None or returns.empty:
        return 0.0
    var = compute_var(returns, confidence)
    tail = returns[returns <= -var]
    return float(-tail.mean()) if not tail.empty else var


def correlation_matrix(returns_dict: dict[str, pd.Series]) -> pd.DataFrame:
    """多策略收益率相关性矩阵。"""
    if not returns_dict:
        return pd.DataFrame()
    df = pd.DataFrame(returns_dict)
    return df.corr()


def check_risk_budget(
    strategy_returns: dict[str, pd.Series],
    weights: dict[str, float],
    budget: RiskBudget,
) -> dict[str, Any]:
    """检查组合是否满足风险预算约束。

    Returns:
        {passed: bool, violations: [str], details: dict}
    """
    violations = []
    details: dict[str, Any] = {}

    # 单策略权重检查
    for name, w in weights.items():
        if w > budget.max_single_weight:
            violations.append(f"weight_{name}_{w:.2f}>{budget.max_single_weight}")

    # 组合 VaR/CVaR
    if strategy_returns:
        df = pd.DataFrame(strategy_returns)
        weights_arr = np.array([weights.get(c, 0.0) for c in df.columns])
        combo_returns = (df * weights_arr).sum(axis=1)

        var = compute_var(combo_returns)
        cvar = compute_cvar(combo_returns)
        details["portfolio_var"] = round(var, 6)
        details["portfolio_cvar"] = round(cvar, 6)

        if var > budget.max_var:
            violations.append(f"var_{var:.4f}>{budget.max_var}")
        if cvar > budget.max_cvar:
            violations.append(f"cvar_{cvar:.4f}>{budget.max_cvar}")

    # 相关性检查
    corr = correlation_matrix(strategy_returns)
    if not corr.empty:
        n = len(corr)
        for i in range(n):
            for j in range(i + 1, n):
                c = abs(corr.iloc[i, j])
                if c > budget.max_corr:
                    violations.append(f"corr_{corr.index[i]}-{corr.columns[j]}_{c:.2f}>{budget.max_corr}")
        details["avg_abs_corr"] = round(float(corr.values[np.triu_indices(n, k=1)].mean()), 4) if n > 1 else 0.0

        # 分散化比率
        vols = df.std() * np.sqrt(252)
        weighted_vol = float((vols * weights_arr).sum())
        portfolio_vol = float(combo_returns.std() * np.sqrt(252)) if not combo_returns.empty else 0.0
        div_ratio = weighted_vol / portfolio_vol if portfolio_vol > 0 else 1.0
        details["diversification_ratio"] = round(div_ratio, 4)
        if div_ratio < budget.min_diversification:
            violations.append(f"div_ratio_{div_ratio:.2f}<{budget.min_diversification}")

    return {
        "passed": len(violations) == 0,
        "violations": violations,
        "details": details,
    }

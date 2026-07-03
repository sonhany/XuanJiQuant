"""IC 评估 (Information Coefficient)

核心指标:
- Rank IC: 因子值排名与下期收益排名的 Spearman 相关系数
- IC Mean: 多个截面上 IC 的平均值
- IC Std: IC 的标准差
- IC IR: IC Mean / IC Std (信息比率)
- IC Decay: 不同持有期 (1d, 5d, 10d, 20d) 的 IC 衰减
- IC Positive Ratio: IC > 0 的比例 (胜率)
- T-stat: IC Mean / (IC Std / sqrt(N))

IC 值域 [-1, 1], 一般 |IC| > 0.03 视为有效, > 0.05 视为强因子
"""
import warnings
import numpy as np
import pandas as pd
from scipy.stats import spearmanr, pearsonr

# Suppress scipy constant-input warnings (expected when cross-section has no variance)
warnings.filterwarnings('ignore', module='scipy')


def rank_ic(factor_values: pd.Series, fwd_returns: pd.Series) -> dict:
    """计算单期 Rank IC

    Args:
        factor_values: 因子值
        fwd_returns: 下期收益 (对齐索引)

    Returns:
        dict {rank_ic, pearson_ic, n, p_value}
    """
    valid = factor_values.notna() & fwd_returns.notna()
    n = int(valid.sum())
    if n < 2:
        return {"rank_ic": None, "pearson_ic": None, "n": 0, "p_value": None}

    fv = factor_values[valid].values
    fr = fwd_returns[valid].values

    # Check for near-constant arrays (correlation undefined)
    if np.std(fv) < 1e-10 or np.std(fr) < 1e-10:
        return {"rank_ic": None, "pearson_ic": None, "n": n, "p_value": None}

    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        rank_corr, rank_p = spearmanr(fv, fr)
        pearson_corr, pearson_p = pearsonr(fv, fr)

    def _round(x):
        if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
            return None
        return round(float(x), 6)

    return {
        "rank_ic": _round(rank_corr),
        "pearson_ic": _round(pearson_corr),
        "n": n,
        "p_value": _round(rank_p),
    }


def compute_ic_series(factor_df: pd.DataFrame, fwd_returns: pd.DataFrame,
                      factor_col: str, fwd_col: str = 'fwd_ret',
                      date_col: str = 'date') -> pd.DataFrame:
    """计算每个截面的 IC

    Args:
        factor_df: 包含 [date, factor_col] 的 long-format DataFrame
        fwd_returns: 包含 [date, fwd_col] 的 long-format DataFrame
        factor_col: 因子列名
        fwd_col: 下期收益列名
        date_col: 日期列名

    Returns:
        DataFrame columns: [date, rank_ic, n]
    """
    merged = pd.merge(
        factor_df[[date_col, factor_col]],
        fwd_returns[[date_col, fwd_col]],
        on=date_col, how='inner'
    )
    merged[factor_col] = pd.to_numeric(merged[factor_col], errors='coerce')
    merged[fwd_col] = pd.to_numeric(merged[fwd_col], errors='coerce')

    out = []
    for date, grp in merged.groupby(date_col):
        r = rank_ic(grp[factor_col], grp[fwd_col])
        r[date_col] = date
        out.append(r)
    return pd.DataFrame(out)


def ic_summary(ic_series: pd.DataFrame, ic_col: str = 'rank_ic') -> dict:
    """汇总 IC 序列

    Args:
        ic_series: 包含 [date, ic_col] 的 DataFrame
        ic_col: IC 列名

    Returns:
        dict {mean, std, ir, positive_ratio, abs_mean, t_stat, n_periods}
    """
    vals = ic_series[ic_col].dropna()
    if len(vals) == 0:
        return {
            "mean": None, "std": None, "ir": None,
            "positive_ratio": None, "abs_mean": None,
            "t_stat": None, "n_periods": 0
        }
    mean = float(vals.mean())
    std = float(vals.std(ddof=1)) if len(vals) > 1 else 0.0
    ir = mean / std if std > 1e-9 else 0.0
    t_stat = mean / (std / np.sqrt(len(vals))) if std > 1e-9 else 0.0
    return {
        "mean": round(mean, 6),
        "std": round(std, 6),
        "ir": round(ir, 4),
        "positive_ratio": round(float((vals > 0).sum() / len(vals)), 4),
        "abs_mean": round(float(vals.abs().mean()), 6),
        "t_stat": round(float(t_stat), 4),
        "n_periods": int(len(vals)),
    }


def ic_decay(factor_df: pd.DataFrame, fwd_returns_by_horizon: dict,
             factor_col: str, fwd_col: str = 'fwd_ret',
             date_col: str = 'date') -> dict:
    """IC 衰减: 不同持有期 (1d/5d/10d/20d) 的 IC

    Args:
        factor_df: 因子 DataFrame
        fwd_returns_by_horizon: {horizon_str: fwd_returns_df}
        factor_col: 因子列名
    """
    out = {}
    for horizon, fwd_df in fwd_returns_by_horizon.items():
        ic_s = compute_ic_series(factor_df, fwd_df, factor_col, fwd_col, date_col)
        out[horizon] = ic_summary(ic_s)
    return out

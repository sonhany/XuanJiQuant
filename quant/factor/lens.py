"""FactorLens — 因子全方位分析框架

参考 BigQuant FactorLens 设计, 在现有 IC 评估基础上增加:
  1. 因子预处理: 去极值 (winsorize) + 标准化 (z-score)
  2. 分布分析: 偏度/峰度/覆盖率/缺失率
  3. 行业分布: 因子值在各行业的均值/中位数分布
  4. 市值分布: 因子值在大/中/小盘的分层统计
  5. 拥挤度分析: 因子持仓集中度 + 换手率
  6. 相关性矩阵: 因子间 Spearman 相关性热力图数据
  7. 综合报告: 一键生成多维度因子诊断

设计原则:
  - 纯 pandas/numpy, 不依赖外部可视化库 (输出 dict/JSON, 前端渲染)
  - 与现有 evaluation.py / ic.py 互补而非替代
  - 所有函数接受 DataFrame 输入, 不直接访问 cache
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

import numpy as np
import pandas as pd


# ═══════════════════════════════════════════════════════════════
# 1. 因子预处理
# ═══════════════════════════════════════════════════════════════

def winsorize(series: pd.Series, *, n_sigma: float = 3.0) -> pd.Series:
    """去极值: 将超出 mean ± n_sigma * std 的值截断到边界。

    Args:
        series: 因子值序列 (含 NaN)
        n_sigma: 标准差倍数 (默认 3σ)

    Returns:
        去极值后的序列 (NaN 保持不变)
    """
    valid = series.dropna()
    if len(valid) < 5:
        return series.copy()
    mean = valid.mean()
    std = valid.std(ddof=1)
    if std < 1e-12:
        return series.copy()
    lower = mean - n_sigma * std
    upper = mean + n_sigma * std
    return series.clip(lower=lower, upper=upper)


def standardize(series: pd.Series) -> pd.Series:
    """Z-score 标准化: (x - mean) / std。

    NaN 保持不变。
    """
    valid = series.dropna()
    if len(valid) < 2:
        return series.copy()
    mean = valid.mean()
    std = valid.std(ddof=1)
    if std < 1e-12:
        return series * 0.0
    return (series - mean) / std


def preprocess_factor(series: pd.Series, *, n_sigma: float = 3.0) -> pd.Series:
    """标准预处理流水线: winsorize → standardize。"""
    return standardize(winsorize(series, n_sigma=n_sigma))


# ═══════════════════════════════════════════════════════════════
# 2. 分布分析
# ═══════════════════════════════════════════════════════════════

def distribution_stats(series: pd.Series) -> dict:
    """因子分布统计: 均值/中位数/标准差/偏度/峰度/覆盖率/分位数。"""
    valid = series.dropna()
    n_total = len(series)
    n_valid = len(valid)
    coverage = n_valid / n_total if n_total > 0 else 0.0
    if n_valid < 3:
        return {
            "count": n_total, "valid": n_valid, "coverage": round(coverage, 4),
            "mean": None, "median": None, "std": None, "skewness": None,
            "kurtosis": None, "min": None, "max": None,
            "q25": None, "q75": None,
        }
    vals = valid.values.astype(float)
    return {
        "count": n_total,
        "valid": n_valid,
        "coverage": round(coverage, 4),
        "mean": round(float(np.mean(vals)), 6),
        "median": round(float(np.median(vals)), 6),
        "std": round(float(np.std(vals, ddof=1)), 6),
        "skewness": round(float(pd.Series(vals).skew()), 4),
        "kurtosis": round(float(pd.Series(vals).kurtosis()), 4),
        "min": round(float(np.min(vals)), 6),
        "max": round(float(np.max(vals)), 6),
        "q25": round(float(np.percentile(vals, 25)), 6),
        "q75": round(float(np.percentile(vals, 75)), 6),
    }


# ═══════════════════════════════════════════════════════════════
# 3. 行业分布分析
# ═══════════════════════════════════════════════════════════════

def industry_distribution(
    factor_df: pd.DataFrame,
    industry_map: dict[str, str],
    *,
    factor_col: str = "factor_value",
) -> dict:
    """因子值在各行业的分布统计。

    Args:
        factor_df: 长表 [date, code, factor_col] 或 [code, factor_col]
        industry_map: {code: 行业大类}
        factor_col: 因子列名

    Returns:
        {industry: {mean, median, std, count, weight}}
        weight = 该行业股票数 / 总股票数
    """
    df = factor_df.copy()
    if "code" not in df.columns:
        return {}
    df["industry"] = df["code"].map(industry_map).fillna("未知")
    df[factor_col] = pd.to_numeric(df[factor_col], errors="coerce")
    df = df.dropna(subset=[factor_col])
    if df.empty:
        return {}

    total_count = len(df)
    result = {}
    for ind, grp in df.groupby("industry"):
        vals = grp[factor_col].values
        result[ind] = {
            "mean": round(float(np.mean(vals)), 6),
            "median": round(float(np.median(vals)), 6),
            "std": round(float(np.std(vals, ddof=1)), 6) if len(vals) > 1 else 0.0,
            "count": int(len(vals)),
            "weight": round(len(vals) / total_count, 4),
        }
    return result


# ═══════════════════════════════════════════════════════════════
# 4. 市值分布分析
# ═══════════════════════════════════════════════════════════════

def market_cap_distribution(
    factor_df: pd.DataFrame,
    log_mktcap: pd.Series | None = None,
    *,
    factor_col: str = "factor_value",
    n_groups: int = 3,
) -> dict:
    """因子值在大/中/小盘的分层统计。

    Args:
        factor_df: 长表 [date, code, factor_col]
        log_mktcap: log(市值代理) 序列, 与 factor_df 同 index。None 则跳过。
        factor_col: 因子列名
        n_groups: 分组数 (默认 3: 大/中/小)

    Returns:
        {group_name: {mean, median, std, count}}
    """
    df = factor_df.copy()
    df[factor_col] = pd.to_numeric(df[factor_col], errors="coerce")
    df = df.dropna(subset=[factor_col])
    if df.empty:
        return {}

    if log_mktcap is not None and len(log_mktcap) == len(df):
        df["_mktcap"] = pd.to_numeric(log_mktcap, errors="coerce")
    elif "log_mktcap" in df.columns:
        df["_mktcap"] = pd.to_numeric(df["log_mktcap"], errors="coerce")
    else:
        return {"_no_mktcap": {"note": "市值数据不可用"}}

    df = df.dropna(subset=["_mktcap"])
    if len(df) < n_groups * 5:
        return {"_insufficient": {"note": f"样本不足 (n={len(df)})"}}

    try:
        df["_cap_group"] = pd.qcut(
            df["_mktcap"], q=n_groups,
            labels=["large_cap", "mid_cap", "small_cap"][:n_groups],
            duplicates="drop",
        )
    except ValueError:
        return {"_error": {"note": "市值分组失败 (数据方差不足)"}}

    result = {}
    for group, grp in df.groupby("_cap_group", observed=True):
        vals = grp[factor_col].values
        result[str(group)] = {
            "mean": round(float(np.mean(vals)), 6),
            "median": round(float(np.median(vals)), 6),
            "std": round(float(np.std(vals, ddof=1)), 6) if len(vals) > 1 else 0.0,
            "count": int(len(vals)),
        }
    return result


# ═══════════════════════════════════════════════════════════════
# 5. 拥挤度分析
# ═══════════════════════════════════════════════════════════════

def crowding_analysis(
    long_df: pd.DataFrame,
    factor_name: str,
    *,
    top_pct: float = 0.1,
    n_groups: int = 5,
) -> dict:
    """因子拥挤度: 分析因子头部持仓集中度和换手率。

    拥挤度高 → 因子已被广泛使用 → 未来可能失效。

    Args:
        long_df: 长表 [date, code, factor_name]
        factor_name: 因子列名
        top_pct: 头部股票占比 (默认 10%)
        n_groups: 分组数

    Returns:
        {
            concentration: 头部股票被重复选出的比例,
            turnover: 头部持仓的平均换手率,
            herding: 行业集中度 (头部持仓的行业分布熵),
        }
    """
    df = long_df[["date", "code", factor_name]].copy()
    df[factor_name] = pd.to_numeric(df[factor_name], errors="coerce")
    df = df.dropna(subset=[factor_name])
    if df.empty:
        return {"concentration": 0.0, "turnover": 0.0, "herding": 0.0}

    dates = sorted(df["date"].unique())
    if len(dates) < 2:
        return {"concentration": 0.0, "turnover": 0.0, "herding": 0.0}

    # 头部股票出现频率
    top_sets: list[set[str]] = []
    for date, grp in df.groupby("date"):
        n_top = max(1, int(len(grp) * top_pct))
        top = grp.nlargest(n_top, factor_name)
        top_sets.append(set(top["code"].tolist()))

    # concentration: 头部股票在所有日期中被重复选中的比例
    if top_sets:
        all_top_codes: dict[str, int] = {}
        for s in top_sets:
            for c in s:
                all_top_codes[c] = all_top_codes.get(c, 0) + 1
        max_freq = max(all_top_codes.values()) if all_top_codes else 0
        concentration = max_freq / len(dates)
    else:
        concentration = 0.0

    # turnover: Jaccard 距离
    turnovers = []
    for prev, cur in zip(top_sets, top_sets[1:]):
        union = len(prev | cur)
        inter = len(prev & cur)
        turnovers.append(1 - inter / union if union > 0 else 0.0)
    avg_turnover = float(np.mean(turnovers)) if turnovers else 0.0

    return {
        "concentration": round(concentration, 4),
        "turnover": round(avg_turnover, 4),
        "herding": _compute_herding(top_sets, long_df, factor_name),
        "n_dates": len(dates),
        "top_pct": top_pct,
    }


def _compute_herding(
    top_sets: list[set[str]],
    long_df: pd.DataFrame,
    factor_name: str,
) -> float:
    """计算头部持仓的行业集中度 (熵的归一化反指标)。

    herding ∈ [0, 1]: 0=完全分散, 1=全部集中在同一行业。
    """
    if not top_sets:
        return 0.0
    # 合并所有日期的头部股票
    all_top: dict[str, int] = {}
    for s in top_sets:
        for c in s:
            all_top[c] = all_top.get(c, 0) + 1
    if not all_top:
        return 0.0
    # 行业分布
    code_col = "code"
    if code_col not in long_df.columns:
        return 0.0
    ind_map = {}
    if "industry" in long_df.columns:
        ind_map = dict(zip(long_df[code_col], long_df["industry"]))
    if not ind_map:
        return 0.0
    ind_counts: dict[str, float] = {}
    for code, freq in all_top.items():
        ind = ind_map.get(code, "未知")
        ind_counts[ind] = ind_counts.get(ind, 0) + freq
    total = sum(ind_counts.values())
    if total <= 0:
        return 0.0
    probs = np.array([c / total for c in ind_counts.values()])
    probs = probs[probs > 0]
    entropy = -float(np.sum(probs * np.log2(probs)))
    max_entropy = np.log2(len(probs)) if len(probs) > 1 else 1.0
    herding = 1.0 - entropy / max_entropy if max_entropy > 0 else 0.0
    return round(herding, 4)


# ═══════════════════════════════════════════════════════════════
# 6. 因子相关性矩阵
# ═══════════════════════════════════════════════════════════════

def correlation_matrix(
    multi_factor: dict[str, pd.DataFrame],
    factor_names: Sequence[str],
    *,
    method: str = "spearman",
    tail_rows: int | None = None,
) -> dict:
    """计算因子间相关性矩阵。

    Args:
        multi_factor: {code: factor_df}
        factor_names: 因子名列表
        method: 'spearman' 或 'pearson'
        tail_rows: 每只股票取最近 N 行

    Returns:
        {
            factors: [factor_names],
            matrix: [[corr_ij]],  # 对称矩阵
            avg_abs_corr: 平均绝对相关性 (冗余度指标),
            highly_correlated: [(factor_a, factor_b, corr)] 前 N 对高相关因子,
        }
    """
    rows = []
    factor_names = list(factor_names)
    for code, fdf in (multi_factor or {}).items():
        if fdf is None or getattr(fdf, "empty", True):
            continue
        cols = [c for c in factor_names if c in fdf.columns]
        if not cols:
            continue
        sub = fdf[cols].tail(int(tail_rows)).copy() if tail_rows else fdf[cols].copy()
        rows.append(sub)
    if not rows:
        return {"factors": factor_names, "matrix": [], "avg_abs_corr": 0.0, "highly_correlated": []}

    df = pd.concat(rows, ignore_index=True)
    for col in factor_names:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    min_obs = max(20, len(df) // 10)
    usable = [
        c for c in factor_names
        if c in df.columns and df[c].notna().sum() >= min_obs and df[c].nunique(dropna=True) > 1
    ]
    if len(usable) < 2:
        return {"factors": factor_names, "matrix": [], "avg_abs_corr": 0.0, "highly_correlated": []}

    corr = df[usable].corr(method=method)
    matrix = corr.values.tolist()
    # 平均绝对相关性 (对角线排除)
    n = len(usable)
    mask = np.ones((n, n), dtype=bool)
    np.fill_diagonal(mask, False)
    avg_abs = float(np.abs(corr.values)[mask].mean()) if n > 1 else 0.0

    # 高相关因子对
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            pairs.append((usable[i], usable[j], round(float(corr.iloc[i, j]), 6)))
    pairs.sort(key=lambda x: abs(x[2]), reverse=True)

    return {
        "factors": usable,
        "matrix": [[round(v, 6) for v in row] for row in matrix],
        "avg_abs_corr": round(avg_abs, 4),
        "highly_correlated": pairs[:10],
    }


# ═══════════════════════════════════════════════════════════════
# 7. 综合因子诊断报告
# ═══════════════════════════════════════════════════════════════

def factor_diagnosis(
    factor_df: pd.DataFrame,
    factor_name: str,
    *,
    industry_map: dict[str, str] | None = None,
    log_mktcap: pd.Series | None = None,
    fwd_returns: pd.Series | None = None,
) -> dict:
    """单因子全方位诊断报告。

    Args:
        factor_df: 长表 [date, code, factor_name]
        factor_name: 因子列名
        industry_map: 行业映射 (可选)
        log_mktcap: 市值代理 (可选)
        fwd_returns: 下期收益 (可选, 用于 IC)

    Returns:
        综合诊断 dict
    """
    if factor_name not in factor_df.columns:
        return {"error": f"factor '{factor_name}' not found"}

    factor_series = factor_df[factor_name]

    # 1. 预处理对比
    raw_stats = distribution_stats(factor_series)
    processed = preprocess_factor(factor_series)
    processed_stats = distribution_stats(processed)

    # 2. 行业分布
    ind_dist = {}
    if industry_map:
        ind_dist = industry_distribution(
            factor_df[["code", factor_name]].drop_duplicates(),
            industry_map,
            factor_col=factor_name,
        )

    # 3. 市值分布
    cap_dist = {}
    if log_mktcap is not None:
        cap_dist = market_cap_distribution(
            factor_df[["date", "code", factor_name]],
            log_mktcap,
            factor_col=factor_name,
        )

    # 4. 基础 IC (如果有 fwd_returns)
    ic_info = None
    if fwd_returns is not None and len(fwd_returns) == len(factor_df):
        from quant.factor.ic import rank_ic
        ic_info = rank_ic(factor_series, fwd_returns)

    # 5. 综合评级
    ic_mean = ic_info.get("rank_ic") if ic_info else None
    ic_abs = abs(ic_mean) if ic_mean is not None else 0.0
    if ic_abs >= 0.05:
        tier = "strong"
    elif ic_abs >= 0.03:
        tier = "moderate"
    elif ic_abs >= 0.02:
        tier = "weak"
    else:
        tier = "ineffective"

    return {
        "factor_name": factor_name,
        "tier": tier,
        "raw_distribution": raw_stats,
        "processed_distribution": processed_stats,
        "industry_distribution": ind_dist,
        "market_cap_distribution": cap_dist,
        "ic": ic_info,
    }


def multi_factor_diagnosis(
    multi_factor: dict[str, pd.DataFrame],
    factor_names: Sequence[str],
    *,
    industry_map: dict[str, str] | None = None,
    log_mktcap_dict: dict[str, pd.DataFrame] | None = None,
    top_n: int = 10,
) -> dict:
    """批量因子诊断: 对所有因子做分布分析 + 相关性矩阵。

    Returns:
        {
            factors: {name: diagnosis_dict},
            correlation: correlation_matrix_dict,
            summary: {strong, moderate, weak, ineffective, total},
        }
    """
    # 合并所有股票的因子数据
    all_rows = []
    for code, fdf in (multi_factor or {}).items():
        if fdf is None or getattr(fdf, "empty", True):
            continue
        sub = fdf[["date", "code"] + [c for c in factor_names if c in fdf.columns]].copy()
        all_rows.append(sub)
    if not all_rows:
        return {"factors": {}, "correlation": {}, "summary": {}}

    merged = pd.concat(all_rows, ignore_index=True)

    # 单因子诊断
    factor_results = {}
    for name in factor_names:
        if name not in merged.columns:
            continue
        diagnosis = factor_diagnosis(
            merged[["date", "code", name]],
            name,
            industry_map=industry_map,
        )
        factor_results[name] = diagnosis

    # 相关性矩阵
    corr = correlation_matrix(multi_factor, factor_names, tail_rows=200)

    # 汇总
    tiers = {"strong": 0, "moderate": 0, "weak": 0, "ineffective": 0}
    for d in factor_results.values():
        t = d.get("tier", "ineffective")
        tiers[t] = tiers.get(t, 0) + 1

    return {
        "factors": factor_results,
        "correlation": corr,
        "summary": {**tiers, "total": len(factor_results)},
    }

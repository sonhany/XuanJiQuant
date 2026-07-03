"""因子中性化 — 去除行业和市值风格暴露

中性化目的: 把因子值里"因为行业/市值不同造成的差异"剥离掉，
只保留"纯 alpha"部分。否则一个"ROE 高"的因子可能只是在选白酒行业，
一个"波动低"的因子可能只是在选大盘股——这不是真正的选股能力。

方法:
  1. 行业中性化: 因子值减去同行业当日均值 (去行业 beta)
  2. 市值中性化: 对去行业后的残差，用 log(成交额) 回归取残差 (去市值 beta)
  3. 双重中性化 = 先行业后市值

数据需求:
  - 行业: cache.get('stock:industry:<code>') → 'C|C39计算机...' (证监会分类)
  - 市值代理: log(20日平均成交额) (amount 字段，已有)

用法 (在 evaluate_all 的 IC 计算前调用):
    from quant.factor.neutralize import neutralize_cross_section
    neutralized = neutralize_cross_section(factor_series, codes, dates, industry_map, log_mktcap_series)
"""
import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("quant.factor.neutralize")


def get_industry_map(codes, cache) -> dict:
    """获取 {code: 行业大类} 映射。无行业的标'未知'。"""
    if cache is None:
        return {c: '未知' for c in codes}
    ind_map = {}
    for code in codes:
        raw = cache.get(f'stock:industry:{code}')
        if raw:
            # 'C|C39计算机...' → 取 'C' (大类字母) 用于分组
            ind_map[code] = raw.split('|')[0] if '|' in raw else raw[:1]
        else:
            ind_map[code] = '未知'
    return ind_map


def compute_log_mktcap_proxy(klines_dict: dict, window: int = 20) -> dict:
    """计算市值代理: log(20日平均成交额) per code

    真实流通市值数据需付费源，用成交额代理能捕获大/小盘风格。
    返回 {code: pd.DataFrame(date → log_avg_amount)}
    """
    out = {}
    for code, df in klines_dict.items():
        if df is None or df.empty or 'amount' not in df.columns:
            continue
        s = pd.to_numeric(df['amount'], errors='coerce').fillna(0)
        # 20日均值, log 变换
        avg = s.rolling(window, min_periods=5).mean()
        log_amt = np.log1p(avg)  # log(1+amount), 避免 0
        out[code] = pd.DataFrame({'date': df['date'].astype(str), 'log_mktcap': log_amt})
    return out


def mktcap_to_long(log_mktcap_dict: dict) -> pd.DataFrame:
    """把 {code: df[date, log_mktcap]} 拼成单张长表 [date, code, log_mktcap]。
    预先拼好可避免在多因子循环里重复 concat (47× 提速)。
    """
    parts = []
    for code, mdf in log_mktcap_dict.items():
        mdf = mdf.copy()
        mdf['code'] = code
        parts.append(mdf)
    if not parts:
        return pd.DataFrame(columns=['date', 'code', 'log_mktcap'])
    return pd.concat(parts, ignore_index=True)


def neutralize_cross_section(
    factor_df: pd.DataFrame,
    industry_map: dict,
    log_mktcap: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """对一个截面长表做行业+市值中性化 (向量化实现)

    Args:
        factor_df: 长表 [date, code, factor_value] (单因子)
        industry_map: {code: 行业大类}
        log_mktcap: 预拼好的长表 [date, code, log_mktcap] 或 None (只做行业中性化)
                    兼容旧接口: 传 {code: df} 也会自动拼 (慢，不推荐多因子循环用)

    Returns: [date, code, factor_value_neutralized], 行数/顺序与输入一致
             (注意: 若 log_mktcap merge 改变了行数, 输出长度会相应变化)
    """
    df = factor_df[['date', 'code', 'factor_value']].copy()
    df['_orig_pos'] = np.arange(len(df))
    df['industry'] = df['code'].map(industry_map).fillna('未知')

    # 合并市值代理 (注意: merge 可能改变行数)
    merged_mktcap = False
    if log_mktcap is not None:
        if isinstance(log_mktcap, dict):
            log_mktcap = mktcap_to_long(log_mktcap)
        if not log_mktcap.empty:
            df = df.merge(log_mktcap, on=['date', 'code'], how='left')
            med = df['log_mktcap'].median()
            if pd.notna(med):
                df['log_mktcap'] = df['log_mktcap'].fillna(med)
            merged_mktcap = True

    # 转成 numpy 做向量化中性化 (避免逐日 pandas groupby 开销)
    dates_arr = df['date'].to_numpy()
    industries = df['industry'].to_numpy()
    vals = df['factor_value'].to_numpy(dtype=float)
    n = len(df)
    result = vals.copy()

    # 把 date 和 industry 编码成整数, 用 groupby 一次性算行业均值
    unique_dates, date_codes = np.unique(dates_arr, return_inverse=True)
    unique_inds, ind_codes = np.unique(industries, return_inverse=True)
    # (date, industry) 复合 key
    composite = date_codes.astype(np.int64) * len(unique_inds) + ind_codes.astype(np.int64)

    valid = ~np.isnan(vals)
    if valid.sum() >= 5:
        # 行业均值: 对每个 (date, industry) 组, 用 nan-safe 均值
        # 用 np.add.at 累加, 再除以计数
        n_groups = int(composite.max()) + 1
        group_sum = np.zeros(n_groups)
        group_cnt = np.zeros(n_groups)
        np.add.at(group_sum, composite[valid], vals[valid])
        np.add.at(group_cnt, composite[valid], 1)
        # 避免除零: 无有效值的组保持 NaN
        safe_cnt = np.where(group_cnt > 0, group_cnt, np.nan)
        group_mean = group_sum / safe_cnt
        industry_means = group_mean[composite]  # 广播回每行
        residual = vals - industry_means  # NaN 处仍为 NaN

        # 市值中性化 (向量化): 对每个 date 做一次 OLS
        if merged_mktcap and 'log_mktcap' in df.columns:
            x = df['log_mktcap'].to_numpy(dtype=float)
            xv_ok = valid & ~np.isnan(x)
            if xv_ok.sum() >= 5:
                # 按 date 分组做 OLS: 残差 = y - (a_d + b_d * x)
                # 用 np.add.at 累加每个 date 的 Σx, Σy, Σx², Σxy, n
                n_dates = len(unique_dates)
                sum_x = np.zeros(n_dates); sum_y = np.zeros(n_dates)
                sum_xx = np.zeros(n_dates); sum_xy = np.zeros(n_dates)
                cnt_d = np.zeros(n_dates)
                xi = x[xv_ok]; yi = residual[xv_ok]; di = date_codes[xv_ok]
                np.add.at(sum_x, di, xi)
                np.add.at(sum_y, di, yi)
                np.add.at(sum_xx, di, xi * xi)
                np.add.at(sum_xy, di, xi * yi)
                np.add.at(cnt_d, di, 1)
                # 每 date 的 OLS 斜率/截距
                # b = (n*Σxy - Σx*Σy) / (n*Σxx - Σx²)
                denom = cnt_d * sum_xx - sum_x * sum_x
                b = np.where(np.abs(denom) > 1e-10,
                             (cnt_d * sum_xy - sum_x * sum_y) / np.where(np.abs(denom) > 1e-10, denom, 1),
                             0.0)
                a = (sum_y - b * sum_x) / np.where(cnt_d > 0, cnt_d, 1)
                # 广播回每行: 残差 = residual - (a[d] + b[d] * x)
                a_row = a[date_codes]
                b_row = b[date_codes]
                fit = a_row + b_row * x
                new_residual = residual.copy()
                # 只在 xv_ok 处覆盖
                new_residual[xv_ok] = residual[xv_ok] - fit[xv_ok]
                result = new_residual
            else:
                result = residual
        else:
            result = residual
    else:
        result = vals  # 样本太少，原样返回

    df['factor_neutralized'] = result
    out = df[['date', 'code', 'factor_neutralized']].rename(
        columns={'factor_neutralized': 'factor_value'}
    )
    return out

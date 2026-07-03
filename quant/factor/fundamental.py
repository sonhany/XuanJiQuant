"""基本面因子 — 从 AKShare 财务数据生成

财务数据按季度报告期，而量价因子按交易日。接入方式: 前向填充 (forward-fill)，
把"截至该交易日的最近一期财务数据"对齐到每个交易日，使财务因子能与量价因子
在同一张表里做截面分析。

数据来源: SQLite key `fin:abstract:<code>` (由 akshare_source.fetch_core_financials 写入)
字段: roe, roa, gross_margin, net_margin, revenue_growth, profit_growth,
      debt_ratio, current_ratio, inventory_turnover, receivable_turnover, asset_turnover

注意:
- 财务因子在财报发布前是"未来信息"，严格回测需用 发布日期 而非 报告期。
  本模块用报告期近似 (PIT 假设)，实盘需加发布日滞后。这里明确标注此假设，
  供研究者知晓回测可能的"前视偏差"风险。
"""
import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("quant.factor.fundamental")


def _add_days_to_int(date_int: int, days: int) -> int:
    """YYYYMMDD 整数 + N天 → 新的 YYYYMMDD 整数 (用于 PIT 发布滞后)

    例: _add_days_to_int(20260331, 45) → 20260515 (报告期后45天才可用)
    """
    try:
        from datetime import datetime, timedelta
        s = str(date_int)
        if len(s) != 8:
            return int(date_int)
        d = datetime.strptime(s, '%Y%m%d') + timedelta(days=days)
        return int(d.strftime('%Y%m%d'))
    except (ValueError, TypeError):
        return int(date_int)

# 基本面因子字段 (与 akshare_source.CORE_FINANCIAL_FIELDS 对应)
FUNDAMENTAL_FACTORS = [
    'roe', 'roa', 'gross_margin', 'net_margin',
    'revenue_growth', 'profit_growth',
    'debt_ratio', 'current_ratio',
    'inventory_turnover', 'receivable_turnover', 'asset_turnover',
]


def load_financials(code: str, cache) -> pd.DataFrame:
    """从缓存读取某股票的核心财务数据 (长表: report_date 为行)

    Returns:
        DataFrame[report_date(str YYYYMMDD), code, roe, roa, ...] 或空 df
    """
    raw = cache.get(f'fin:abstract:{code}') if cache else None
    if not raw:
        return pd.DataFrame()
    df = pd.DataFrame(raw)
    if 'report_date' not in df.columns:
        return pd.DataFrame()
    return df


def compute_fundamental(df: pd.DataFrame, code: str, cache=None) -> pd.DataFrame:
    """把财务数据前向填充对齐到 K 线交易日

    Args:
        df: K 线 DataFrame，必须含 'date' 列 (YYYYMMDD)
        code: 股票代码 (用于从缓存读财务)
        cache: create_cache() 实例

    Returns:
        在 df 基础上追加 11 个财务因子列 (前向填充)。无财务数据时追加 NaN 列。
    """
    if df.empty:
        return df
    df = df.copy()

    # 读财务数据
    fin = load_financials(code, cache)
    has_fin = (not fin.empty) and any(c in fin.columns for c in FUNDAMENTAL_FACTORS)

    if not has_fin:
        # 无财务数据: 追加全 NaN 列，保持列结构一致 (便于下游统一处理)
        for col in FUNDAMENTAL_FACTORS:
            df[col] = np.nan
        return df

    # 构造 report_date -> 各指标 的查找表，按日期升序
    fin = fin.copy()
    fin['report_date'] = fin['report_date'].astype(str)
    # 仅保留有意义的指标列
    metric_cols = [c for c in FUNDAMENTAL_FACTORS if c in fin.columns]
    fin = fin[['report_date'] + metric_cols].sort_values('report_date').drop_duplicates('report_date', keep='last')

    # 对齐: 对每个交易日，取 报告期+发布滞后 <= 该交易日的最近一期
    # PIT (point-in-time): 财报不会在报告期当天就公开，通常有30-90天发布滞后。
    # 这里用 +45天 近似 (季报45天/年报90天的折中)，避免前视偏差。
    df['date'] = df['date'].astype(str)

    # merge_asof 要求数值/datetime 类型的 key，把 YYYYMMDD 字符串转 int
    df_sorted = df.sort_values('date').reset_index(drop=True).copy()
    fin_sorted = fin.sort_values('report_date').reset_index(drop=True).copy()
    df_sorted['_date_int'] = df_sorted['date'].astype('int64')
    # 报告期 + 45天 作为 PIT 可用日 (近似财报发布日)
    fin_sorted['_rep_int'] = fin_sorted['report_date'].apply(_add_days_to_int, args=(45,))

    # merge_asof: left=交易日, right=PIT可用日, direction='backward' 取最近一期
    merged = pd.merge_asof(
        df_sorted,
        fin_sorted,
        left_on='_date_int',
        right_on='_rep_int',
        direction='backward',
    )
    # 清理临时列和 join 引入的多余列
    for drop_col in ('_date_int', '_rep_int', 'report_date'):
        if drop_col in merged.columns:
            merged = merged.drop(columns=[drop_col])
    if 'code_y' in merged.columns:
        merged = merged.drop(columns=['code_y'])
    if 'code_x' in merged.columns:
        merged = merged.rename(columns={'code_x': 'code'})

    # 确保所有 FUNDAMENTAL_FACTORS 列都存在 (缺失补 NaN)
    for col in FUNDAMENTAL_FACTORS:
        if col not in merged.columns:
            merged[col] = np.nan
        else:
            merged[col] = pd.to_numeric(merged[col], errors='coerce')

    return merged


def list_fundamental() -> list:
    return list(FUNDAMENTAL_FACTORS)

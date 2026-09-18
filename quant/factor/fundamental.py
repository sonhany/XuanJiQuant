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

    自动兼容两种 fin:abstract:<code> 格式:
      A) 平铺格式: [{report_date, code, roe, roa, ...}] (fetch_core_financials / seed_financials)
      B) 嵌套格式: [{code, name, period, source, tables:{performance,income,balance,cashflow}}]
         (rebuild_financials_bulk / akshare_em_bulk) — 中文字段需换算为英文因子

    Returns:
        DataFrame[report_date(str YYYYMMDD), code, roe, roa, ...] 或空 df
    """
    raw = cache.get(f'fin:abstract:{code}') if cache else None
    if not raw:
        return pd.DataFrame()
    df = pd.DataFrame(raw)

    # 格式 A: 已有 report_date 列, 直接返回
    if 'report_date' in df.columns:
        return df

    # 格式 B: 嵌套 tables → 平铺英文因子
    # 同时尝试从 fin:supplement:<code> 补充 current_ratio 等字段
    supplement = cache.get(f'fin:supplement:{code}') if cache else None
    rows = []
    for rec in raw:
        tables = rec.get('tables') or {}
        period = str(rec.get('period') or '').replace('-', '')
        if len(period) != 8:
            continue
        flat = _flatten_bulk_tables(tables)
        if not flat:
            continue
        # 用补充数据补齐 current_ratio (来自 stock_financial_abstract 80 项指标)
        if supplement:
            cr = flat.get('current_ratio')
            if cr is None or (isinstance(cr, float) and cr != cr):  # None 或 NaN
                cr_val = supplement.get(period)
                if cr_val is not None:
                    flat['current_ratio'] = float(cr_val)
        flat['report_date'] = period
        flat['code'] = rec.get('code') or code
        rows.append(flat)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _flatten_bulk_tables(tables: dict) -> dict:
    """把 akshare_em_bulk 的嵌套 tables 换算为 11 个英文基本面因子。

    字段口径 (基于实测 akshare stock_yjbb_em/lrb_em/zcfz_em 列名):
      roe      ← performance['净资产收益率']
      roa      ← income['净利润'] / balance['资产-总资产'] × 100
      gross_margin ← performance['销售毛利率']
      net_margin   ← income['净利润'] / income['营业总收入'] × 100
      revenue_growth ← performance['营业总收入-同比增长']
      profit_growth  ← performance['净利润-同比增长']
      debt_ratio     ← balance['资产负债率']
      asset_turnover ← income['营业总收入'] / balance['资产-总资产'] × 100
      receivable_turnover ← income['营业总收入'] / balance['资产-应收账款']
      current_ratio / inventory_turnover: bulk 表无流动资产/营业成本字段, 留 NaN

    数值来自单期报表, 周转率用期末值近似 (无期初均值), 作为截面排序因子已足够。
    """
    perf = tables.get('performance') or {}
    inc = tables.get('income') or {}
    bal = tables.get('balance') or {}

    def num(d, *keys):
        """从 dict 里按候选 key 取第一个有限数值。"""
        for k in keys:
            v = d.get(k)
            if v is None:
                continue
            try:
                f = float(v)
                if f == f and f != 0:  # 非 NaN 且非 0 (避免除零/缺值)
                    return f
            except (TypeError, ValueError):
                continue
        return None

    out = {col: np.nan for col in FUNDAMENTAL_FACTORS}

    # 直接字段
    roe = num(perf, '净资产收益率')
    if roe is not None:
        out['roe'] = roe
    gm = num(perf, '销售毛利率')
    if gm is not None:
        out['gross_margin'] = gm
    rg = num(perf, '营业总收入-同比增长', '营业总收入同比增长')
    if rg is not None:
        out['revenue_growth'] = rg
    pg = num(perf, '净利润-同比增长', '净利润同比增长', '归属母公司净利润同比增长')
    if pg is not None:
        out['profit_growth'] = pg
    dr = num(bal, '资产负债率')
    if dr is not None:
        out['debt_ratio'] = dr

    # 换算字段
    net_profit = num(inc, '净利润', '归属母公司股东的净利润')
    revenue = num(inc, '营业总收入', '营业收入')
    total_asset = num(bal, '资产-总资产', '资产总计')
    receivable = num(bal, '资产-应收账款', '应收账款')
    inventory = num(bal, '资产-存货', '存货')
    # 营业成本近似: 东财快报 income 表无"营业成本"列, 用"营业支出"代理
    # (营业总支出含期间费用, 会略高于纯营业成本, 作为截面排序因子可接受)
    operating_cost = num(inc, '营业总支出-营业支出', '营业支出', '营业成本')

    if net_profit is not None and revenue and abs(revenue) > 1e-6:
        out['net_margin'] = net_profit / revenue * 100
    if net_profit is not None and total_asset and abs(total_asset) > 1e-6:
        out['roa'] = net_profit / total_asset * 100
    if revenue is not None and total_asset and abs(total_asset) > 1e-6:
        out['asset_turnover'] = revenue / total_asset * 100
    if revenue is not None and receivable and abs(receivable) > 1e-6:
        out['receivable_turnover'] = revenue / receivable
    if operating_cost is not None and inventory and abs(inventory) > 1e-6:
        out['inventory_turnover'] = operating_cost / inventory

    # current_ratio: bulk 表无流动资产合计/流动负债合计字段, 保持 NaN
    return out


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

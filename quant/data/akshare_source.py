"""A 股特色数据源 — AKShare (免费免 key)

定位: 补充腾讯日 K 数据源没有的维度，重点是【基本面/财务】数据。
腾讯源擅长量价 (日 K + 实时行情)，但不提供财务指标、行业归属等基本面信息。
AKShare 的 stock_financial_abstract 接口稳定且数据丰富 (80 项财务指标)，
是构建基本面因子的核心原料。

设计原则 (基于实测):
  - 只封装经过实测稳定可用的接口，不堆砌一堆不稳定的桩
  - 所有调用带重试 + 超时，失败返回空 DataFrame 而非抛异常
  - 数据落 SQLite (通过 cache)，与 K 线同库

实测可用接口:
  stock_financial_abstract(symbol)     — 单股 80 项财务指标 (26 季度) ✅ 稳定
  stock_financial_analysis_indicator   — 单股财务分析指标 (PE/PB/ROE 时序) ✅ 稳定

实测不稳定/不采用 (避免给用户添堵):
  stock_zh_a_spot_em    — 东财全市场快照, 反爬严重 ❌
  stock_zt_pool_em      — 涨停池, 经常返回空 ❌
  stock_individual_info_em — 东财个股信息, 反爬 ❌
  stock_hsgt_*          — 北向资金, 2024后实时数据停更, 接口极慢 ❌
"""
import logging
import time
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger("akshare_source")

# 重试参数
_MAX_RETRIES = 3
_RETRY_DELAY = 1.5  # 秒


def _retry(fn, *, retries: int = _MAX_RETRIES, delay: float = _RETRY_DELAY):
    """带重试的调用包装。失败返回 None，由调用方决定如何降级。"""
    last_err = None
    for i in range(retries):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if i < retries - 1:
                time.sleep(delay)
    logger.debug(f"_retry failed after {retries} attempts: {last_err}")
    return None


def _import_akshare():
    """延迟导入 akshare (不装也能用其他源)"""
    import akshare as ak
    return ak


# ═══════════════════════════════════════════════════════════
#  财务摘要 — 单股 80 项财务指标
# ═══════════════════════════════════════════════════════════
def fetch_financial_abstract(code: str) -> pd.DataFrame:
    """拉取单只股票的财务摘要 (80 项指标 × ~26 季度)

    原始返回是"宽表": 每行一个指标, 每列一个季度报告期。
    本函数转置为"长表": date(报告期) 为行, 指标为列, 便于时序因子计算。

    Args:
        code: 6 位股票代码

    Returns:
        DataFrame, 列 = [report_date, ROE, ROA, 毛利率, 营收增速, ...]
        失败返回空 DataFrame
    """
    ak = _import_akshare()
    raw = _retry(lambda: ak.stock_financial_abstract(symbol=code))
    if raw is None or raw.empty:
        return pd.DataFrame()

    # 原始: index=指标, columns=报告期 (20260331, 20251231, ...)
    # 指标列可能在 '指标' 字段
    ind_col = '指标' if '指标' in raw.columns else raw.columns[1]
    raw = raw.set_index(ind_col)
    # 关键: akshare 原始数据存在重复指标行 (不同会计准则版本)，
    # 转置后会变成重复列名导致 to_numeric 失败。去重，保留第一个。
    raw = raw[~raw.index.duplicated(keep='first')]
    # 删除非日期列 (如 '选项')
    date_cols = [c for c in raw.columns if str(c).replace('.', '').isdigit() and len(str(c)) == 8]
    if not date_cols:
        return pd.DataFrame()
    raw = raw[date_cols]
    # 转置: 报告期为行, 指标为列
    df = raw.T.reset_index()
    df = df.rename(columns={'index': 'report_date'})
    df['report_date'] = df['report_date'].astype(str)
    df['code'] = code
    # 去除转置后仍可能残留的重复列名 (防御性)
    df = df.loc[:, ~df.columns.duplicated()]
    return df


# ─── 核心财务因子原料 (从 80 项里挑最常用的) ───────────────
CORE_FINANCIAL_FIELDS = {
    '净资产收益率(ROE)': 'roe',
    '总资产报酬率(ROA)': 'roa',
    '毛利率': 'gross_margin',
    '销售净利率': 'net_margin',
    '营业总收入增长率': 'revenue_growth',
    '归属母公司净利润增长率': 'profit_growth',
    '资产负债率': 'debt_ratio',
    '流动比率': 'current_ratio',
    '存货周转率': 'inventory_turnover',
    '应收账款周转率': 'receivable_turnover',
    '总资产周转率': 'asset_turnover',
}


def fetch_core_financials(code: str) -> pd.DataFrame:
    """提取核心财务指标 (英文名)，适合直接做基本面因子

    Returns:
        DataFrame[report_date, code, roe, roa, gross_margin, net_margin,
                  revenue_growth, profit_growth, debt_ratio, current_ratio,
                  inventory_turnover, receivable_turnover, asset_turnover]
    """
    df = fetch_financial_abstract(code)
    if df.empty:
        return df

    # 中文指标名 -> 英文
    rename = {cn: en for cn, en in CORE_FINANCIAL_FIELDS.items() if cn in df.columns}
    keep = ['report_date', 'code'] + list(rename.values())
    out = df.rename(columns=rename)[keep] if rename else df[['report_date', 'code']]

    # 数值化
    for col in rename.values():
        out[col] = pd.to_numeric(out[col], errors='coerce')
    return out.sort_values('report_date').reset_index(drop=True)


# ═══════════════════════════════════════════════════════════
#  财务分析指标 — 单股 PE/PB/ROE 时序 (含历史日频)
# ═══════════════════════════════════════════════════════════
def fetch_analysis_indicator(code: str) -> pd.DataFrame:
    """单股财务分析指标 (含 PE/PB/ROE 等，按报告期时序)

    与 financial_abstract 互补: abstract 偏"财务三表",
    analysis_indicator 偏"估值与回报"。两者结合覆盖完整基本面。

    Returns:
        DataFrame[日期, 代码, 每股收益, 每股净资产, 每股公积金,
                  每股未分配利润, 每股经营现金流, 销售毛利率(%),
                  净资产收益率(%), 净资产收益率-摊薄(%), 营业周期, ...]
        失败返回空 DataFrame
    """
    ak = _import_akshare()
    # symbol 带 .SH / .SZ 后缀
    sym = _with_exchange_suffix(code)
    raw = _retry(lambda: ak.stock_financial_analysis_indicator(symbol=sym, start_year='2018'))
    if raw is None or raw.empty:
        return pd.DataFrame()
    raw = raw.copy()
    raw['代码'] = code
    raw['日期'] = raw['日期'].astype(str)
    return raw


def _with_exchange_suffix(code: str) -> str:
    """6 位代码 -> 带交易所后缀 (600519 -> 600519.SH)"""
    c = code.split('.')[0]
    if c.startswith('6') or c.startswith('9'):
        return f'{c}.SH'
    if c.startswith('0') or c.startswith('3') or c.startswith('2'):
        return f'{c}.SZ'
    if c.startswith('8') or c.startswith('4'):
        return f'{c}.BJ'
    return f'{c}.SH'


# ═══════════════════════════════════════════════════════════
#  批量采集 — 写入 SQLite
# ═══════════════════════════════════════════════════════════
def seed_financials(codes: List[str], cache, *, limit: Optional[int] = None,
                    prefix: str = 'fin:abstract') -> Dict[str, int]:
    """批量采集财务摘要并写入缓存

    Args:
        codes: 股票代码列表
        cache: create_cache() 返回的实例
        limit: 只处理前 N 只 (调试用)
        prefix: 缓存 key 前缀 (fin:abstract:<code>)

    Returns:
        {'ok': N, 'err': N, 'skip': N}
    """
    if limit:
        codes = codes[:limit]
    ok = err = skip = 0
    for i, code in enumerate(codes, 1):
        try:
            df = fetch_core_financials(code)
            if df.empty:
                skip += 1
            else:
                cache.set(f'{prefix}:{code}', df.to_dict(orient='records'))
                ok += 1
        except Exception as e:
            logger.warning(f'[{code}] financial fetch failed: {e}')
            err += 1
        if i % 50 == 0:
            logger.info(f'financial seed progress: {i}/{len(codes)} (ok={ok} skip={skip} err={err})')
            time.sleep(0.5)  # 礼貌限速
    logger.info(f'financial seed done: ok={ok} skip={skip} err={err} / total={len(codes)}')
    return {'ok': ok, 'skip': skip, 'err': err}


def list_financial_fields() -> List[str]:
    """返回核心财务字段英文名列表"""
    return list(CORE_FINANCIAL_FIELDS.values())

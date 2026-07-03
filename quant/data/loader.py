"""K 线 DataFrame 加载器 — 假设数据已通过 schema 校验

输入: list[dict] 来自 Redis kline:<code>:d
输出: pandas DataFrame，列固定为 [date, open, high, low, close, volume, amount]
"""
import pandas as pd
from quant.data.schema import REQUIRED_FIELDS


def load_kline_df(records: list) -> pd.DataFrame:
    """规范化 K 线 list 转 DataFrame

    所有数据应已通过 schema.validate_series 校验，字段名固定为完整英文。
    如果数据格式异常，返回空 DataFrame。
    """
    if not records:
        return pd.DataFrame(columns=list(REQUIRED_FIELDS))

    df = pd.DataFrame(records)
    if df.empty:
        return df

    # 兜底：缺字段则补
    for col in REQUIRED_FIELDS:
        if col not in df.columns:
            df[col] = 0 if col in ('volume',) else 0.0

    # 数值列转 numeric
    for col in ('open', 'high', 'low', 'close', 'amount'):
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
    df['volume'] = pd.to_numeric(df['volume'], errors='coerce').fillna(0).astype('int64')
    df['date'] = df['date'].astype(str)

    # 按日期升序
    return df[list(REQUIRED_FIELDS)].sort_values('date').reset_index(drop=True)

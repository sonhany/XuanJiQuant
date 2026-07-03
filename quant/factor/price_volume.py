"""28 个量价因子

| 类别 | 数量 | 因子 |
|------|------|------|
| 动量    | 5  | ret_1, ret_5, ret_10, ret_20, ret_60 |
| 反转    | 3  | reversal_3, reversal_5, reversal_10 |
| 波动    | 4  | volatility_5, volatility_20, volatility_60, range_pct |
| 量价相关 | 4  | pvcorr_5, pvcorr_10, pvcorr_20, pvbeta_20 |
| 资金流  | 4  | mfi_14, obv_slope_10, ad_slope_10, vwap_dev_20 |
| 换手/成交 | 4 | turnover_5, turnover_20, vol_ratio_5, amt_ratio_5 |
| 趋势/形态 | 4 | trend_strength, gap_pct, intraday_ret, overnight_ret |
+───── | ─── |
合计 28
"""
import numpy as np
import pandas as pd


def compute_price_volume(df: pd.DataFrame) -> pd.DataFrame:
    """追加 28 个量价因子列到 df"""
    if df.empty:
        return df
    df = df.copy()
    for col in ('open', 'high', 'low', 'close', 'volume', 'amount'):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    close = df['close']
    high = df['high']
    low = df['low']
    open_ = df['open']
    volume = df['volume'].fillna(0)
    amount = df['amount'].fillna(0)

    close_safe = close.clip(lower=1e-6)
    prev_close = close_safe.shift(1).replace(0, np.nan)

    # 动量 5
    for p in [1, 5, 10, 20, 60]:
        df[f'ret_{p}'] = close.pct_change(p)

    # 反转 3: 取 ret 的负值 (与动量方向相反)
    for p in [3, 5, 10]:
        df[f'reversal_{p}'] = -close.pct_change(p)

    # 波动 4
    log_ret = np.log(close_safe / prev_close)
    for p in [5, 20, 60]:
        df[f'volatility_{p}'] = log_ret.rolling(p, min_periods=2).std()
    df['range_pct'] = (high - low) / close_safe  # 当日振幅

    # 量价相关 4
    for p in [5, 10, 20]:
        rolling_corr = close.pct_change().rolling(p, min_periods=2).corr(volume.pct_change())
        df[f'pvcorr_{p}'] = rolling_corr
    # pvbeta_20: 20 日 close 对 volume 的回归斜率 (用协方差/方差近似)
    ret_1 = close.pct_change()
    vol_1 = volume.replace(0, np.nan).pct_change()
    cov_20 = ret_1.rolling(20, min_periods=5).cov(vol_1)
    var_20 = vol_1.rolling(20, min_periods=5).var()
    df['pvbeta_20'] = cov_20 / var_20.replace(0, np.nan)

    # 资金流 4
    # MFI 14: 类似 RSI 但用 amount
    typical_price = (high + low + close) / 3
    money_flow = typical_price * amount
    delta_tp = typical_price.diff()
    pos_flow = money_flow.where(delta_tp > 0, 0.0).rolling(14, min_periods=1).sum()
    neg_flow = money_flow.where(delta_tp < 0, 0.0).rolling(14, min_periods=1).sum()
    mf_ratio = pos_flow / neg_flow.replace(0, np.nan)
    df['mfi_14'] = 100 - 100 / (1 + mf_ratio)

    # OBV slope 10: OBV 10 日回归斜率
    obv = [0.0]
    for i in range(1, len(df)):
        if close.iloc[i] > close.iloc[i - 1]:
            obv.append(obv[-1] + volume.iloc[i])
        elif close.iloc[i] < close.iloc[i - 1]:
            obv.append(obv[-1] - volume.iloc[i])
        else:
            obv.append(obv[-1])
    obv_s = pd.Series(obv, index=df.index)
    # 斜率: 末日 OBV - 起点 OBV / 10
    df['obv_slope_10'] = (obv_s - obv_s.shift(10)) / 10
    # A/D line slope 10
    ad = ((close - low) - (high - close)) / (high - low).replace(0, np.nan) * volume
    ad = ad.fillna(0).cumsum()
    df['ad_slope_10'] = (ad - ad.shift(10)) / 10
    # VWAP deviation 20
    vwap = amount / volume.replace(0, np.nan)
    vwap_ma20 = vwap.rolling(20, min_periods=1).mean()
    df['vwap_dev_20'] = (close - vwap_ma20) / vwap_ma20.replace(0, np.nan)

    # 换手/成交 4
    df['turnover_5'] = volume.rolling(5, min_periods=1).mean()
    df['turnover_20'] = volume.rolling(20, min_periods=1).mean()
    vol_ma5 = volume.rolling(5, min_periods=1).mean()
    vol_ma20 = volume.rolling(20, min_periods=1).mean()
    df['vol_ratio_5'] = volume / vol_ma20.replace(0, np.nan)
    df['amt_ratio_5'] = amount / amount.rolling(5, min_periods=1).mean().replace(0, np.nan)

    # 趋势/形态 4
    # trend_strength: (MA20 - MA60) / MA60
    ma20 = close.rolling(20, min_periods=1).mean()
    ma60 = close.rolling(60, min_periods=1).mean()
    df['trend_strength'] = (ma20 - ma60) / ma60.replace(0, np.nan)
    # gap_pct: 今开 - 昨收 / 昨收
    df['gap_pct'] = (open_ - prev_close) / prev_close
    # intraday_ret: (今收 - 今开) / 今开
    df['intraday_ret'] = (close - open_) / open_.replace(0, np.nan)
    # overnight_ret: (今开 - 昨收) / 昨收 (== gap_pct, 重复保留, 用于语义)
    df['overnight_ret'] = df['gap_pct']

    return df


PRICE_VOLUME_FACTORS = [
    'ret_1', 'ret_5', 'ret_10', 'ret_20', 'ret_60',
    'reversal_3', 'reversal_5', 'reversal_10',
    'volatility_5', 'volatility_20', 'volatility_60', 'range_pct',
    'pvcorr_5', 'pvcorr_10', 'pvcorr_20', 'pvbeta_20',
    'mfi_14', 'obv_slope_10', 'ad_slope_10', 'vwap_dev_20',
    'turnover_5', 'turnover_20', 'vol_ratio_5', 'amt_ratio_5',
    'trend_strength', 'gap_pct', 'intraday_ret', 'overnight_ret',
]


def list_price_volume() -> list[str]:
    return list(PRICE_VOLUME_FACTORS)

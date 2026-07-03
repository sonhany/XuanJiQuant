"""19 个技术指标

| 指标 | 数量 | 因子 |
|------|------|------|
| EMA  | 2    | ema_12, ema_26 |
| MACD | 3    | macd_dif, macd_dea, macd_hist |
| RSI  | 3    | rsi_6, rsi_12, rsi_24 |
| KDJ  | 3    | kdj_k, kdj_d, kdj_j |
| BOLL | 3    | boll_upper, boll_mid, boll_lower |
| ATR  | 1    | atr_14 |
| WR   | 1    | williams_r_14 |
| ROC  | 1    | roc_10 |
| CCI  | 1    | cci_20 |
| BIAS | 1    | bias_20 |
+───── | ──── |
合计    19
"""
import numpy as np
import pandas as pd


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def compute_technical(df: pd.DataFrame) -> pd.DataFrame:
    """追加 19 个技术指标列到 df"""
    if df.empty:
        return df
    df = df.copy()
    for col in ('open', 'high', 'low', 'close'):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    close = df['close']
    high = df['high']
    low = df['low']
    open_ = df['open']

    # EMA 12/26
    df['ema_12'] = _ema(close, 12)
    df['ema_26'] = _ema(close, 26)

    # MACD: DIF=EMA12-EMA26, DEA=EMA(DIF,9), HIST=(DIF-DEA)*2
    dif = df['ema_12'] - df['ema_26']
    dea = _ema(dif, 9)
    df['macd_dif'] = dif
    df['macd_dea'] = dea
    df['macd_hist'] = (dif - dea) * 2

    # RSI N: 100 - 100/(1 + avg_gain_N / avg_loss_N)
    def _rsi(series: pd.Series, period: int) -> pd.Series:
        delta = series.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.rolling(period, min_periods=1).mean()
        avg_loss = loss.rolling(period, min_periods=1).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        return 100 - 100 / (1 + rs)

    df['rsi_6'] = _rsi(close, 6)
    df['rsi_12'] = _rsi(close, 12)
    df['rsi_24'] = _rsi(close, 24)

    # KDJ: RSV=(C-LL9)/(HH9-LL9)*100, K=RSV*1/3+K*2/3, D=K*1/3+D*2/3, J=3K-2D
    low9 = low.rolling(9, min_periods=1).min()
    high9 = high.rolling(9, min_periods=1).max()
    rsv = (close - low9) / (high9 - low9).replace(0, np.nan) * 100
    rsv = rsv.fillna(50.0)
    k_vals = [50.0]
    for v in rsv.iloc[1:]:
        k_vals.append(v / 3 + k_vals[-1] * 2 / 3)
    df['kdj_k'] = pd.Series(k_vals, index=df.index)
    d_vals = [50.0]
    for v in df['kdj_k'].iloc[1:]:
        d_vals.append(v / 3 + d_vals[-1] * 2 / 3)
    df['kdj_d'] = pd.Series(d_vals, index=df.index)
    df['kdj_j'] = 3 * df['kdj_k'] - 2 * df['kdj_d']

    # BOLL: MID=MA20, UPPER=MID+2*STD20, LOWER=MID-2*STD20
    mid = close.rolling(20, min_periods=1).mean()
    std20 = close.rolling(20, min_periods=1).std()
    df['boll_mid'] = mid
    df['boll_upper'] = mid + 2 * std20
    df['boll_lower'] = mid - 2 * std20

    # ATR 14: TR=MAX(H-L, |H-prevC|, |L-prevC|), ATR=MA(TR,14)
    prev_c = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_c).abs(),
        (low - prev_c).abs()
    ], axis=1).max(axis=1)
    df['atr_14'] = tr.rolling(14, min_periods=1).mean()

    # Williams %R 14: (HH14-C)/(HH14-LL14)*-100
    high14 = high.rolling(14, min_periods=1).max()
    low14 = low.rolling(14, min_periods=1).min()
    df['williams_r_14'] = (high14 - close) / (high14 - low14).replace(0, np.nan) * -100

    # ROC 10: (C - C[10]) / C[10] * 100
    prev10 = close.shift(10)
    df['roc_10'] = (close - prev10) / prev10.replace(0, np.nan) * 100

    # CCI 20: (TP - MA20TP) / (0.015 * MD20TP)
    tp = (high + low + close) / 3
    ma_tp = tp.rolling(20, min_periods=1).mean()
    md_tp = tp.rolling(20, min_periods=1).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    df['cci_20'] = (tp - ma_tp) / (0.015 * md_tp.replace(0, np.nan))

    # BIAS 20: (C - MA20) / MA20 * 100
    df['bias_20'] = (close - mid) / mid.replace(0, np.nan) * 100

    return df


TECHNICAL_FACTORS = [
    'ema_12', 'ema_26',
    'macd_dif', 'macd_dea', 'macd_hist',
    'rsi_6', 'rsi_12', 'rsi_24',
    'kdj_k', 'kdj_d', 'kdj_j',
    'boll_mid', 'boll_upper', 'boll_lower',
    'atr_14', 'williams_r_14', 'roc_10', 'cci_20', 'bias_20',
]


def list_technical() -> list[str]:
    return list(TECHNICAL_FACTORS)

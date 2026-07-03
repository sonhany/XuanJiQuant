"""FactorEngine: 因子引擎主类

功能:
- 批量计算单只股票的 47 个因子
- 多股票批量计算 (并行可选)
- IC 评估 (调用 ic.py)
- 因子排名 (按 |IC Mean|)
- Redis 缓存 (key: factor:{code}:{date})

使用:
    engine = FactorEngine()
    df_with_factors = engine.compute_all(klines_df)
    factor_list = engine.list_factors()  # ['ret_1', 'macd_dif', ...]
    rankings = engine.rank_factors(multi_stock_factor_dict, fwd_returns_dict)
"""
import logging
import json
import time
import warnings
from typing import Optional, List, Dict, Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


# ─── 向量化 IC 辅助函数 (替代逐次 spearmanr，提速 20-50 倍) ───
def _rank_1d(arr: np.ndarray) -> np.ndarray:
    """1D 数组的平均秩 (处理 NaN 和并列值)。NaN 保持 NaN。"""
    arr = np.asarray(arr, dtype=float)
    result = np.full_like(arr, np.nan)
    valid = ~np.isnan(arr)
    if valid.sum() == 0:
        return result
    v = arr[valid]
    order = v.argsort()
    ranks = np.empty_like(v)
    # 平均秩处理并列
    sv = v[order]
    n = len(v)
    i = 0
    while i < n:
        j = i
        while j < n and sv[j] == sv[i]:
            j += 1
        avg_rank = (i + j + 1) / 2.0  # 1-indexed average
        ranks[order[i:j]] = avg_rank
        i = j
    result[valid] = ranks
    return result


def _pearson(x: np.ndarray, y: np.ndarray) -> float:
    """两个等长向量的 Pearson 相关系数 (向量化，无 scipy 开销)"""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mx, my = x.mean(), y.mean()
    dx, dy = x - mx, y - my
    denom = np.sqrt((dx * dx).sum() * (dy * dy).sum())
    if denom < 1e-15:
        return float('nan')
    return float((dx * dy).sum() / denom)

from .technical import compute_technical, TECHNICAL_FACTORS
from .price_volume import compute_price_volume, PRICE_VOLUME_FACTORS
from .fundamental import compute_fundamental, FUNDAMENTAL_FACTORS
from .ic import rank_ic, ic_summary, compute_ic_series, ic_decay

logger = logging.getLogger("quant.factor")


FACTOR_CATEGORIES = {
    "technical": {
        "name": "技术指标",
        "count": len(TECHNICAL_FACTORS),
        "factors": TECHNICAL_FACTORS,
    },
    "price_volume": {
        "name": "量价因子",
        "count": len(PRICE_VOLUME_FACTORS),
        "factors": PRICE_VOLUME_FACTORS,
    },
    "fundamental": {
        "name": "基本面因子",
        "count": len(FUNDAMENTAL_FACTORS),
        "factors": FUNDAMENTAL_FACTORS,
    },
}

ALL_FACTORS = TECHNICAL_FACTORS + PRICE_VOLUME_FACTORS + FUNDAMENTAL_FACTORS


class FactorEngine:
    """因子计算 + IC 评估 + 排名 + 缓存"""

    def __init__(self, cache=None):
        """Args:
            cache: 可选 RedisCache 实例, 不传则不缓存
        """
        self._cache = cache

    # ── 单股计算 ──────────────────────────────────────
    def compute_all(self, df: pd.DataFrame, code: str = None) -> pd.DataFrame:
        """计算全部因子 (量价 + 技术 + 基本面)

        Args:
            df: DataFrame with [date, open, high, low, close, volume, amount]
            code: 股票代码；传入时会从缓存读财务数据生成基本面因子。
                  不传则跳过基本面因子 (保持与旧行为兼容)。

        Returns:
            追加了因子列 + 基础列的 DataFrame
        """
        if df.empty:
            return df
        df = df.copy()
        # 标准化列
        for col in ('open', 'high', 'low', 'close', 'volume', 'amount'):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        if 'date' in df.columns:
            df['date'] = df['date'].astype(str)
        df = compute_technical(df)
        df = compute_price_volume(df)
        # 基本面因子 (需 code 才能从缓存读财务数据)
        if code and self._cache:
            try:
                df = compute_fundamental(df, code, self._cache)
            except Exception as e:
                logger.debug(f"compute_fundamental {code} failed (non-fatal): {e}")
                from .fundamental import FUNDAMENTAL_FACTORS as _FF
                import numpy as _np
                for col in _FF:
                    if col not in df.columns:
                        df[col] = _np.nan
        return df

    def compute_one(self, df: pd.DataFrame, factor_name: str, code: str = None) -> pd.Series:
        """计算单只股票的单个因子 (返回 Series)"""
        if factor_name in TECHNICAL_FACTORS:
            return compute_technical(df)[factor_name]
        elif factor_name in PRICE_VOLUME_FACTORS:
            return compute_price_volume(df)[factor_name]
        elif factor_name in FUNDAMENTAL_FACTORS:
            # 基本面因子需 code 读缓存
            fdf = compute_fundamental(df, code or '', self._cache)
            return fdf[factor_name] if factor_name in fdf.columns else pd.Series(dtype=float)
        else:
            raise ValueError(f"Unknown factor: {factor_name}")

    # ── 多股批量 ──────────────────────────────────────
    def compute_multi(self, klines_dict: Dict[str, pd.DataFrame],
                      codes: Optional[List[str]] = None,
                      use_cache: bool = True) -> Dict[str, pd.DataFrame]:
        """多股票批量因子计算

        Args:
            klines_dict: {code: klines_df}
            codes: 指定计算的股票列表, None=全部
            use_cache: 是否写 Redis 缓存

        Returns:
            {code: factor_df}
        """
        if codes is None:
            codes = list(klines_dict.keys())
        out = {}
        for code in codes:
            df = klines_dict.get(code)
            if df is None or df.empty:
                continue
            t0 = time.time()
            try:
                # 传入 code 以便计算基本面因子 (若有缓存财务数据)
                factor_df = self.compute_all(df, code=code)
                out[code] = factor_df
                if use_cache and self._cache:
                    self._cache_factors(code, factor_df)
                logger.debug(f"compute_factors {code}: {len(factor_df)} rows, {time.time()-t0:.2f}s")
            except Exception as e:
                logger.warning(f"compute_factors {code}: {e}")
        return out

    # ── IC 评估 ──────────────────────────────────────
    def evaluate_factor(self, multi_factor: Dict[str, pd.DataFrame],
                        multi_klines: Dict[str, pd.DataFrame],
                        factor_name: str,
                        fwd_horizons: List[int] = [1, 5, 10, 20]) -> dict:
        """评估单个因子的 IC

        Args:
            multi_factor: {code: factor_df} (包含 factor_name 列)
            multi_klines: {code: klines_df} (用于计算 fwd_returns)
            factor_name: 因子名
            fwd_horizons: 评估的持有期列表

        Returns:
            dict {factor_name, summary (1d), decay ({h: summary}), n_stocks}
        """
        # 收集所有股票的 (date, factor, fwd_ret) 拼接成长表
        long_rows = []
        for code, fdf in multi_factor.items():
            if code not in multi_klines:
                continue
            kdf = multi_klines[code]
            if 'date' not in fdf.columns or 'date' not in kdf.columns:
                continue
            # 找到下期收益 (用 kdf 排序)
            kdf_sorted = kdf.sort_values('date').reset_index(drop=True)
            fdf_sorted = fdf.sort_values('date').reset_index(drop=True)
            # 取因子名
            if factor_name not in fdf_sorted.columns:
                continue
            # 合并
            merged = pd.DataFrame({
                'date': fdf_sorted['date'],
                'factor': pd.to_numeric(fdf_sorted[factor_name], errors='coerce'),
            })
            # 算每个日期的 1d fwd return
            kdf_sorted['fwd_ret_1'] = kdf_sorted['close'].pct_change().shift(-1)
            for h in fwd_horizons:
                col = f'fwd_ret_{h}'
                kdf_sorted[col] = kdf_sorted['close'].pct_change(h).shift(-h)
            # merge back
            merged = merged.merge(
                kdf_sorted[['date'] + [f'fwd_ret_{h}' for h in fwd_horizons]],
                on='date', how='left'
            )
            merged['code'] = code
            long_rows.append(merged)
        if not long_rows:
            return {"factor_name": factor_name, "summary": None, "decay": {}, "n_stocks": 0}
        long_df = pd.concat(long_rows, ignore_index=True)

        # 1d summary
        ic_s_1d = compute_ic_series(
            long_df.rename(columns={'factor': factor_name}),
            long_df.rename(columns={'fwd_ret_1': 'fwd_ret'}),
            factor_name, fwd_col='fwd_ret', date_col='date'
        )
        summary_1d = ic_summary(ic_s_1d)

        # decay
        decay = {}
        for h in fwd_horizons:
            ic_s_h = compute_ic_series(
                long_df.rename(columns={'factor': factor_name}),
                long_df.rename(columns={f'fwd_ret_{h}': 'fwd_ret'}),
                factor_name, fwd_col='fwd_ret', date_col='date'
            )
            decay[f"{h}d"] = ic_summary(ic_s_h)

        return {
            "factor_name": factor_name,
            "summary": summary_1d,
            "decay": decay,
            "n_stocks": len(multi_factor),
        }

    def evaluate_all(self, multi_factor: Dict[str, pd.DataFrame],
                     multi_klines: Dict[str, pd.DataFrame],
                     factor_names: Optional[List[str]] = None,
                     fwd_horizons: List[int] = [1, 5, 10, 20],
                     neutralize: bool = False) -> List[dict]:
        """评估所有因子的 IC, 返回按 |IC Mean| 排序的结果

        Args:
            neutralize: 是否做行业+市值中性化 (去除风格暴露后的纯 alpha IC)
                        需要 cache 里有 stock:industry:* 数据
        """
        if factor_names is None:
            factor_names = list(ALL_FACTORS)

        # ── Step 1: Build long_df with fwd_returns pre-computed ──
        stock_rows = []
        for code, fdf in multi_factor.items():
            if code not in multi_klines:
                continue
            kdf = multi_klines[code]
            if 'date' not in fdf.columns or 'date' not in kdf.columns:
                continue
            kdf_s = kdf.sort_values('date').reset_index(drop=True)
            fdf_s = fdf.sort_values('date').reset_index(drop=True)
            for h in fwd_horizons:
                kdf_s[f'fwd_{h}'] = kdf_s['close'].pct_change(h).shift(-h)
            drop = {'open', 'high', 'low', 'close', 'volume', 'amount', 'date'}
            factor_cols = [c for c in fdf_s.columns if c not in drop]
            # Merge factor cols with fwd_returns
            merged = fdf_s[['date'] + factor_cols].merge(
                kdf_s[['date'] + [f'fwd_{h}' for h in fwd_horizons]],
                on='date', how='left'
            )
            merged['code'] = code
            stock_rows.append(merged)

        if not stock_rows:
            return []

        long_df = pd.concat(stock_rows, ignore_index=True)

        # 确定有效因子列 (中性化和 IC 计算共用)
        drop = {'open', 'high', 'low', 'close', 'volume', 'amount', 'date', 'code'}
        valid_factor_cols = [c for c in factor_names if c in long_df.columns and c not in drop]
        for col in valid_factor_cols:
            long_df[col] = pd.to_numeric(long_df[col], errors='coerce')

        # ── Step 1.5: 因子中性化 (可选) ──────────────
        # 去除行业+市值风格暴露，只保留纯 alpha。需 cache 里有 stock:industry:*。
        # 优化: 把 mktcap 一次性 merge 进 long_df，对每个因子列只做纯 numpy 中性化，
        # 避免 47× 重复 merge (1.3M 行 × 47 = 极慢)。
        if neutralize and self._cache:
            try:
                from quant.factor.neutralize import (
                    get_industry_map, compute_log_mktcap_proxy, mktcap_to_long,
                )
                codes = list(multi_factor.keys())
                ind_map = get_industry_map(codes, self._cache)
                mcp_long = mktcap_to_long(compute_log_mktcap_proxy(multi_klines))
                logger.info(f"市值代理长表构建: {len(mcp_long)} 行")

                # 一次性把 industry + log_mktcap 合并进 long_df
                long_df['_ind'] = long_df['code'].map(ind_map).fillna('未知')
                if not mcp_long.empty:
                    long_df = long_df.merge(mcp_long, on=['date', 'code'], how='left')
                    med = long_df['log_mktcap'].median()
                    if pd.notna(med):
                        long_df['log_mktcap'] = long_df['log_mktcap'].fillna(med)

                # 编码 date / industry 为整数 (供 groupby 累加)
                dates_arr = long_df['date'].to_numpy()
                inds_arr = long_df['_ind'].to_numpy()
                _, date_codes = np.unique(dates_arr, return_inverse=True)
                _, ind_codes = np.unique(inds_arr, return_inverse=True)
                n_inds = int(ind_codes.max()) + 1 if len(ind_codes) else 1
                composite = date_codes.astype(np.int64) * n_inds + ind_codes.astype(np.int64)
                n_groups = int(composite.max()) + 1 if len(composite) else 1
                has_mktcap = 'log_mktcap' in long_df.columns
                x_mkt = (long_df['log_mktcap'].to_numpy(dtype=float)
                         if has_mktcap else np.zeros(len(long_df)))
                n_dates = len(np.unique(dates_arr))

                # 预计算每 date 的 OLS 统计量 (所有因子共用)
                # Σx, Σx², n per date
                x_valid = ~np.isnan(x_mkt) if has_mktcap else np.zeros(len(long_df), dtype=bool)
                sum_x = np.zeros(n_dates); sum_xx = np.zeros(n_dates); cnt_x = np.zeros(n_dates)
                if has_mktcap:
                    np.add.at(sum_x, date_codes[x_valid], x_mkt[x_valid])
                    np.add.at(sum_xx, date_codes[x_valid], x_mkt[x_valid] ** 2)
                    np.add.at(cnt_x, date_codes[x_valid], 1)
                denom_x = cnt_x * sum_xx - sum_x * sum_x

                t_neu = time.time()
                for col in valid_factor_cols:
                    if col not in long_df.columns:
                        continue
                    vals = pd.to_numeric(long_df[col], errors='coerce').to_numpy(dtype=float)
                    valid = ~np.isnan(vals)
                    if valid.sum() < 5:
                        continue
                    # 1. 行业去均值: per (date, industry)
                    g_sum = np.zeros(n_groups); g_cnt = np.zeros(n_groups)
                    np.add.at(g_sum, composite[valid], vals[valid])
                    np.add.at(g_cnt, composite[valid], 1)
                    safe = np.where(g_cnt > 0, g_cnt, np.nan)
                    g_mean = g_sum / safe
                    resid = vals - g_mean[composite]

                    # 2. 市值 OLS 残差: per date
                    if has_mktcap:
                        xv_ok = valid & x_valid
                        if xv_ok.sum() >= 5:
                            sum_y = np.zeros(n_dates); sum_xy = np.zeros(n_dates)
                            np.add.at(sum_y, date_codes[xv_ok], resid[xv_ok])
                            np.add.at(sum_xy, date_codes[xv_ok], resid[xv_ok] * x_mkt[xv_ok])
                            b = np.where(np.abs(denom_x) > 1e-10,
                                         (cnt_x * sum_xy - sum_x * sum_y) /
                                         np.where(np.abs(denom_x) > 1e-10, denom_x, 1),
                                         0.0)
                            a = (sum_y - b * sum_x) / np.where(cnt_x > 0, cnt_x, 1)
                            fit = a[date_codes] + b[date_codes] * x_mkt
                            resid = np.where(xv_ok, resid - fit, resid)
                    long_df[col] = resid
                logger.info(f"因子中性化完成 (行业+市值, {len(codes)}只, {len(valid_factor_cols)}因子, "
                            f"{time.time()-t_neu:.1f}s)")
            except Exception as e:
                logger.warning(f"中性化失败(非致命, 用原始因子): {e}")

        # ── Step 2: Per-horizon IC — 向量化计算 ──
        # 按 (date, horizon) groupby 一次，对当日所有因子列一次性算秩相关。
        horizon_ic: dict[int, dict[str, list]] = {h: {} for h in fwd_horizons}

        for h in fwd_horizons:
            fwd_col = f'fwd_{h}'
            long_df[fwd_col] = pd.to_numeric(long_df[fwd_col], errors='coerce')
            for date, grp in long_df.groupby('date'):
                fwd_vals = grp[fwd_col].to_numpy(dtype=float)
                fwd_valid = ~np.isnan(fwd_vals)
                if fwd_vals.size < 3:
                    continue
                # 前向收益的秩 (当日所有股票共用)
                fwd_ranks = _rank_1d(fwd_vals)
                for col in valid_factor_cols:
                    fv = grp[col].to_numpy(dtype=float)
                    valid = (~np.isnan(fv)) & fwd_valid
                    n = int(valid.sum())
                    if n < 2:
                        continue
                    fv_v = fv[valid]
                    fr_v = fwd_ranks[valid]
                    if np.std(fv_v) < 1e-10 or np.std(fr_v) < 1e-10:
                        continue
                    # 向量化 Spearman: 两个秩向量的 Pearson 相关
                    f_ranks = _rank_1d(fv_v)
                    rc = _pearson(f_ranks, fr_v)
                    if not (np.isnan(rc) or np.isinf(rc)):
                        horizon_ic[h].setdefault(col, []).append(float(rc))

        # ── Step 3: Summarize ──
        out = []
        for name in factor_names:
            summaries = {}
            primary_summary = None
            for h in fwd_horizons:
                vals_list = horizon_ic[h].get(name, [])
                if vals_list:
                    vals = np.array(vals_list)
                    mean = float(vals.mean())
                    std = float(vals.std(ddof=1)) if len(vals) > 1 else 0.0
                    s = {
                        "mean": round(mean, 6),
                        "std": round(std, 4),
                        "ir": round(mean / (std + 1e-9), 4),
                        "positive_ratio": round(float((vals > 0).sum() / len(vals)), 4),
                        "abs_mean": round(float(np.abs(vals).mean()), 6),
                        "n_periods": len(vals),
                    }
                else:
                    s = {"mean": None, "std": None, "ir": 0.0,
                         "positive_ratio": 0.0, "abs_mean": 0.0, "n_periods": 0}
                if h == 1:
                    primary_summary = s
                summaries[f"{h}d"] = s

            if primary_summary and primary_summary.get('mean') is not None:
                out.append({
                    "factor_name": name,
                    "summary": primary_summary,
                    "decay": summaries,
                    "n_stocks": len(multi_factor),
                })

        out.sort(key=lambda x: abs(x["summary"]["mean"]) if x.get("summary") else 0, reverse=True)
        return out

    # ── 缓存 ──────────────────────────────────────────
    def _cache_factors(self, code: str, factor_df: pd.DataFrame,
                       ttl: Optional[int] = None):
        """写因子到 Redis (key: factor:{code})"""
        if not self._cache:
            return
        try:
            records = factor_df.to_dict(orient='records')
            self._cache.set(f"factor:{code}", records, ttl=ttl)
        except Exception as e:
            logger.debug(f"cache_factors {code}: {e}")

    def get_cached_factors(self, code: str) -> Optional[pd.DataFrame]:
        if not self._cache:
            return None
        records = self._cache.get(f"factor:{code}")
        if not records:
            return None
        return pd.DataFrame(records)

    # ── 工具方法 ──────────────────────────────────────
    def list_factors(self) -> List[str]:
        return list(ALL_FACTORS)

    def list_categories(self) -> dict:
        return FACTOR_CATEGORIES

    def factor_meta(self) -> dict:
        """返回所有因子的元信息 (类别/数量/列表)"""
        return {
            "total": len(ALL_FACTORS),
            "categories": [
                {
                    "id": "technical",
                    "name": "技术指标",
                    "count": len(TECHNICAL_FACTORS),
                    "factors": TECHNICAL_FACTORS,
                },
                {
                    "id": "price_volume",
                    "name": "量价因子",
                    "count": len(PRICE_VOLUME_FACTORS),
                    "factors": PRICE_VOLUME_FACTORS,
                },
                {
                    "id": "fundamental",
                    "name": "基本面因子",
                    "count": len(FUNDAMENTAL_FACTORS),
                    "factors": FUNDAMENTAL_FACTORS,
                },
            ]
        }

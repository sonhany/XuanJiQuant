"""策略引擎核心类

基于 Layer 2 因子计算结果，生成交易信号并评估策略表现。
不重复因子计算逻辑，不重复回测引擎。

4 种内置策略，均支持单股和多股模式:
- factor_rank: 按因子 Z-Score 的绝对值排序 (多股) 或阈值 (单股)
- multi_factor: 多因子 Z-Score 加权求和
- ma_cross: 均线交叉
- bb_reversion: 布林带回归
"""
import logging
import time
from typing import Optional, List, Dict

import numpy as np
import pandas as pd

from quant.factor import FactorEngine
from quant.backtest import BacktestSimulator

logger = logging.getLogger("quant.strategy")

# ── 内置策略元信息 ──────────────────────────────────────
STRATEGY_META = {
    "factor_rank": {
        "name": "单因子排名",
        "desc": "按因子 Z-Score 方向交易。多股: 每天排序选 top_n; 单股: |Z|>0.5 时交易",
        "params": [
            {"name": "factor_name", "type": "string", "default": "rsi_6", "desc": "因子名称"},
            {"name": "top_n", "type": "int", "default": 3, "desc": "选股数量(仅多股有效)"},
            {"name": "hold_days", "type": "int", "default": 5, "desc": "持有天数"},
            {"name": "threshold", "type": "float", "default": 0.5, "desc": "Z-Score 阈值(单股)"},
        ],
    },
    "multi_factor": {
        "name": "多因子加权",
        "desc": "多个因子 Z-Score 加权求和，正信号做多，负信号做空",
        "params": [
            {"name": "factors", "type": "string", "default": "rsi_6,macd_hist,bias_20", "desc": "因子名逗号分隔"},
            {"name": "weights", "type": "string", "default": "0.4,0.3,0.3", "desc": "权重逗号分隔"},
            {"name": "hold_days", "type": "int", "default": 5, "desc": "持有天数"},
        ],
    },
    "ma_cross": {
        "name": "均线交叉",
        "desc": "短期均线上穿长期均线时买入，下穿时卖出",
        "params": [
            {"name": "fast", "type": "int", "default": 5, "desc": "短期均线周期"},
            {"name": "slow", "type": "int", "default": 20, "desc": "长期均线周期"},
            {"name": "hold_days", "type": "int", "default": 5, "desc": "持有天数"},
        ],
    },
    "bb_reversion": {
        "name": "布林带回归",
        "desc": "价格触及下轨买入，触及上轨卖出",
        "params": [
            {"name": "period", "type": "int", "default": 20, "desc": "布林带周期"},
            {"name": "std_dev", "type": "float", "default": 2.0, "desc": "标准差倍数"},
            {"name": "hold_days", "type": "int", "default": 5, "desc": "持有天数"},
        ],
    },
}

ALL_STRATEGIES = list(STRATEGY_META.keys())


class StrategyEngine:
    """策略引擎: 因子→信号→回测"""

    def __init__(self, factor_engine: Optional[FactorEngine] = None, cache=None):
        self._factor = factor_engine or FactorEngine(cache=cache)
        self._cache = cache

    def strategy_meta(self) -> dict:
        return STRATEGY_META

    # ── 策略执行 ────────────────────────────────────────
    def run_strategy(self, name: str, params: dict,
                     klines_dict: Dict[str, pd.DataFrame]) -> dict:
        handler = {
            "factor_rank": self._run_factor_rank,
            "multi_factor": self._run_multi_factor,
            "ma_cross": self._run_ma_cross,
            "bb_reversion": self._run_bb_reversion,
        }.get(name)
        if not handler:
            raise ValueError(f"未知策略: {name}")

        t0 = time.time()
        signals = handler(params, klines_dict)
        elapsed = time.time() - t0

        # Event-driven backtest via BacktestSimulator
        sim = BacktestSimulator(
            initial_cash=1_000_000,
            commission_rate=0.0003,
            slippage_rate=0.0001,
            position_size_pct=0.2,
        )
        sim.add_signals(signals)
        sim.add_klines(klines_dict)
        bt = sim.run()

        return {"signals": signals, "backtest": bt, "elapsed": round(elapsed, 2)}

    # ── 单因子排名策略 (截面排名) ──────────────────────────────
    def _run_factor_rank(self, params: dict,
                         klines_dict: Dict[str, pd.DataFrame]) -> dict:
        factor_name = params.get("factor_name", "rsi_6")
        top_n = int(params.get("top_n", 3))
        threshold = float(params.get("threshold", 0.5))  # z-score threshold (single-stock fallback)

        factor_dfs = self._factor.compute_multi(klines_dict, use_cache=False)
        n_stocks = len(factor_dfs)

        # ── Multi-stock: cross-sectional ranking per date ──
        if n_stocks >= 2:
            # Stack all stocks into long_df: date | code | factor_value
            rows = []
            for code, fdf in factor_dfs.items():
                if factor_name not in fdf.columns:
                    continue
                sub = fdf[['date', factor_name]].copy()
                sub['code'] = code
                rows.append(sub)
            if not rows:
                return {code: [] for code in klines_dict}

            long_df = pd.concat(rows, ignore_index=True)
            long_df[factor_name] = pd.to_numeric(long_df[factor_name], errors='coerce')
            long_df = long_df.dropna(subset=[factor_name])

            # Cross-sectional z-score + rank per date (vectorized via transform)
            grp = long_df.groupby('date')[factor_name]
            mean_map = grp.transform('mean')
            std_map = grp.transform(lambda x: x.std(ddof=0) if x.std(ddof=0) > 1e-10 else 1.0)
            long_df['z'] = (long_df[factor_name] - mean_map) / std_map
            long_df['rank'] = grp.transform(lambda x: x.rank(ascending=False, method='min').astype(int))

            # Assign signals: one pass over dates, track prev_state
            all_dates = sorted(long_df['date'].unique())
            n_codes = long_df['code'].nunique()
            long_n = min(top_n, n_codes // 2)
            short_n = min(top_n, n_codes // 2)
            long_cut = long_n          # rank <= long_n -> long
            short_cut = n_codes - short_n  # rank > short_cut -> short

            signals = {code: [] for code in klines_dict}
            prev_state = {code: 0 for code in klines_dict}
            # prev_state: 1=long, -1=short, 0=neutral

            for date in all_dates:
                grp = long_df[long_df['date'] == date].copy()
                grp_sorted = grp.sort_values('rank')
                code_rank = dict(zip(grp_sorted['code'], grp_sorted['rank']))
                code_z = dict(zip(grp_sorted['code'], grp_sorted['z']))
                code_fv = dict(zip(grp_sorted['code'], grp_sorted[factor_name]))

                new_state = {}
                for code in klines_dict:
                    r = code_rank.get(code, None)
                    if r is None:
                        new_state[code] = 0  # no data -> neutral
                    elif r <= long_cut:
                        new_state[code] = 1  # long
                    elif r > short_cut:
                        new_state[code] = -1  # short
                    else:
                        new_state[code] = 0   # neutral

                for code, new_s in new_state.items():
                    prev_s = prev_state[code]
                    if new_s != prev_s:
                        signals[code].append({
                            "date": str(date), "signal": new_s,
                            "factor_value": round(float(code_fv.get(code, 0)), 4),
                            "z_score": round(float(code_z.get(code, 0)), 3),
                            "rank": int(code_rank.get(code, 0)),
                            "total": n_codes,
                        })
                        prev_state[code] = new_s
            return signals

        # ── Single stock: time-series z-score threshold ──
        signals = {}
        for code, fdf in factor_dfs.items():
            if factor_name not in fdf.columns:
                signals[code] = []
                continue
            df = fdf[['date', factor_name]].dropna().sort_values('date')
            vals = df[factor_name].values
            mean, std = np.nanmean(vals), np.nanstd(vals)
            df['z'] = (df[factor_name] - mean) / (std if std > 0 else 1)
            df['signal'] = df['z'].apply(
                lambda z: 1 if z > threshold else (-1 if z < -threshold else 0)
            )
            signals[code] = [
                {"date": str(r['date']), "signal": int(r['signal']),
                 "factor_value": round(float(r[factor_name]), 4), "z_score": round(float(r['z']), 3)}
                for _, r in df.iterrows() if r['signal'] != 0
            ]
        return signals

    # ── 多因子加权策略 ──────────────────────────────────
    def _run_multi_factor(self, params: dict,
                          klines_dict: Dict[str, pd.DataFrame]) -> dict:
        factor_names = [f.strip() for f in params.get("factors", "rsi_6,macd_hist,bias_20").split(",")]
        weights = [float(w.strip()) for w in params.get("weights", "0.4,0.3,0.3").split(",")]
        if len(factor_names) != len(weights):
            weights = [1.0 / len(factor_names)] * len(factor_names)
        w = np.array(weights) / sum(weights)

        factor_dfs = self._factor.compute_multi(klines_dict, use_cache=False)
        threshold = 0.3

        signals = {}
        for code, fdf in factor_dfs.items():
            cols = [c for c in factor_names if c in fdf.columns]
            if not cols:
                signals[code] = []
                continue
            df = fdf[['date'] + cols].dropna().sort_values('date')
            for col in cols:
                vals = df[col].values
                m, s = np.nanmean(vals), np.nanstd(vals)
                df[f'z_{col}'] = (df[col] - m) / (s if s > 0 else 1)

            df['score'] = sum(w[i] * df[f'z_{cols[i]}'] for i in range(len(cols)))
            df['signal'] = df['score'].apply(lambda s: 1 if s > threshold else (-1 if s < -threshold else 0))

            signals[code] = [
                {"date": str(r['date']), "signal": int(r['signal']), "score": round(float(r['score']), 4)}
                for _, r in df.iterrows() if r['signal'] != 0
            ]
        return signals

    # ── 均线交叉策略 ────────────────────────────────────
    def _run_ma_cross(self, params: dict,
                      klines_dict: Dict[str, pd.DataFrame]) -> dict:
        fast = int(params.get("fast", 5))
        slow = int(params.get("slow", 20))

        signals = {}
        for code, kdf in klines_dict.items():
            df = kdf[['date', 'close']].copy().sort_values('date')
            df['close'] = pd.to_numeric(df['close'], errors='coerce')
            df['ma_fast'] = df['close'].rolling(fast).mean()
            df['ma_slow'] = df['close'].rolling(slow).mean()
            df['signal_raw'] = 0
            df.loc[df['ma_fast'] > df['ma_slow'], 'signal_raw'] = 1
            df.loc[df['ma_fast'] < df['ma_slow'], 'signal_raw'] = -1

            prev = None
            signal_list = []
            for _, row in df.iterrows():
                s = int(row['signal_raw'])
                if s != prev:
                    signal_list.append({
                        "date": str(row['date']), "signal": s,
                        "ma_fast": round(float(row['ma_fast']), 2) if pd.notna(row['ma_fast']) else None,
                        "ma_slow": round(float(row['ma_slow']), 2) if pd.notna(row['ma_slow']) else None,
                    })
                    prev = s
            signals[code] = signal_list
        return signals

    # ── 布林带回归策略 ──────────────────────────────────
    def _run_bb_reversion(self, params: dict,
                          klines_dict: Dict[str, pd.DataFrame]) -> dict:
        period = int(params.get("period", 20))
        std_dev = float(params.get("std_dev", 2.0))

        signals = {}
        for code, kdf in klines_dict.items():
            df = kdf[['date', 'close']].copy().sort_values('date')
            df['close'] = pd.to_numeric(df['close'], errors='coerce')
            df['mid'] = df['close'].rolling(period).mean()
            df['std'] = df['close'].rolling(period).std()
            df['upper'] = df['mid'] + std_dev * df['std']
            df['lower'] = df['mid'] - std_dev * df['std']
            df['signal_raw'] = 0
            df.loc[df['close'] <= df['lower'], 'signal_raw'] = 1
            df.loc[df['close'] >= df['upper'], 'signal_raw'] = -1

            prev = None
            signal_list = []
            for _, row in df.iterrows():
                s = int(row['signal_raw'])
                if s != prev:
                    signal_list.append({
                        "date": str(row['date']), "signal": s,
                        "close": round(float(row['close']), 2) if pd.notna(row['close']) else None,
                        "upper": round(float(row['upper']), 2) if pd.notna(row['upper']) else None,
                        "lower": round(float(row['lower']), 2) if pd.notna(row['lower']) else None,
                    })
                    prev = s
            signals[code] = signal_list
        return signals

    # ── 回测 ────────────────────────────────────────────
    def _backtest(self, signals: dict, klines_dict: Dict[str, pd.DataFrame],
                  hold_days: int = 5) -> dict:
        total_trades = []
        code_results = {}

        for code, sig_list in signals.items():
            if not sig_list or code not in klines_dict:
                continue
            kdf = klines_dict[code].copy()
            kdf['close'] = pd.to_numeric(kdf['close'], errors='coerce')
            kdf = kdf[kdf['date'] != ''].sort_values('date')
            price_map = dict(zip(kdf['date'], kdf['close']))
            dates = sorted(price_map.keys())

            trades = []
            for s in sig_list:
                d = s['date']
                sig = s['signal']
                if d not in price_map or sig == 0:
                    continue
                entry_p = price_map[d]
                idx = dates.index(d) if d in dates else -1
                exit_idx = min(idx + hold_days, len(dates) - 1) if idx >= 0 else -1
                exit_d = dates[exit_idx] if exit_idx >= 0 else d
                exit_p = price_map.get(exit_d, entry_p)
                pnl = (exit_p - entry_p) / entry_p * sig
                trades.append({
                    "entry_date": d, "exit_date": exit_d,
                    "entry_price": round(float(entry_p), 2),
                    "exit_price": round(float(exit_p), 2),
                    "pnl_pct": round(float(pnl) * 100, 2),
                    "holding_days": hold_days,
                })

            if trades:
                returns = [t['pnl_pct'] for t in trades]
                win = [r for r in returns if r > 0]
                code_results[code] = {
                    "trade_count": len(trades),
                    "total_return_pct": round(float(sum(returns)), 2),
                    "win_rate_pct": round(len(win) / len(returns) * 100, 1) if returns else 0,
                    "avg_return_pct": round(float(np.mean(returns)), 2) if returns else 0,
                }
                total_trades.extend(trades)

        all_returns = [t['pnl_pct'] for t in total_trades]
        return {
            "summary": {
                "total_trades": len(total_trades),
                "total_return_pct": round(float(sum(all_returns)), 2),
                "avg_return_pct": round(float(np.mean(all_returns)), 2) if all_returns else 0,
                "win_rate_pct": round(len([r for r in all_returns if r > 0]) / max(len(all_returns), 1) * 100, 1),
                "stock_count": len(code_results),
            },
            "details": total_trades,
            "per_stock": code_results,
        }

"""多频率回测引擎 — 支持日线/分钟/Tick 三级频率。

设计目标:
  补齐 BacktestSimulator 只支持日线的短板，
  提供 minute_bar / tick_bar 级别的向量化回测。

用法:
    engine = MultiFreqBacktest()
    result = engine.run(
        signals_df=signals,        # [timestamp, code, weight]
        bars_dict=bars,            # {code: DataFrame(timestamp, open, high, low, close, volume)}
        frequency='1m',           # '1d' / '1m' / 'tick'
    )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger("quant.backtest.multi_freq")


# ── 频率配置 ──────────────────────────────────────────────

FREQ_CONFIG = {
    "1d":  {"bars_per_year": 252,   "label": "日线", "min_interval": "1D"},
    "1m":  {"bars_per_year": 252 * 240, "label": "分钟", "min_interval": "1min"},
    "tick": {"bars_per_year": 252 * 240 * 240, "label": "Tick", "min_interval": "0s"},
}


@dataclass(frozen=True, slots=True)
class MultiFreqConfig:
    """多频率回测配置。"""
    initial_cash: float = 1_000_000.0
    commission_rate: float = 0.0003
    stamp_tax_rate: float = 0.0005
    slippage_rate: float = 0.0001
    lot_size: int = 100
    enforce_t1: bool = True       # 日线级别 T+1
    enforce_limit: bool = True    # 涨跌停限制
    version: str = "multi-freq-v1"


@dataclass(slots=True)
class MultiFreqResult:
    """多频率回测结果。"""
    equity_curve: pd.Series
    daily_returns: pd.Series
    total_return: float
    annual_return: float
    sharpe: float
    max_drawdown: float
    win_rate: float
    turnover: float
    total_fees: float
    n_bars: int
    frequency: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "total_return": round(self.total_return, 6),
            "annual_return": round(self.annual_return, 6),
            "sharpe": round(self.sharpe, 4),
            "max_drawdown": round(self.max_drawdown, 6),
            "win_rate": round(self.win_rate, 4),
            "turnover": round(self.turnover, 6),
            "total_fees": round(self.total_fees, 6),
            "n_bars": self.n_bars,
            "frequency": self.frequency,
        }


class MultiFreqBacktest:
    """多频率向量化回测引擎。"""

    def __init__(self, config: MultiFreqConfig | None = None):
        self._config = config or MultiFreqConfig()

    def run(
        self,
        signals_df: pd.DataFrame,
        bars_dict: dict[str, pd.DataFrame],
        *,
        frequency: str = "1d",
    ) -> MultiFreqResult:
        """运行多频率回测。

        Args:
            signals_df: 信号表 [timestamp, code, weight]
            bars_dict: {code: DataFrame(timestamp, open, high, low, close, volume, ...)}
            frequency: '1d' / '1m' / 'tick'
        """
        if frequency not in FREQ_CONFIG:
            raise ValueError(f"Unsupported frequency: {frequency}. Use {list(FREQ_CONFIG.keys())}")
        if signals_df is None or signals_df.empty:
            return self._empty_result(frequency)

        freq_cfg = FREQ_CONFIG[frequency]
        bars_per_year = freq_cfg["bars_per_year"]
        ts_col = "timestamp" if "timestamp" in signals_df.columns else "date"

        # 构建价格面板
        price_panel = self._build_price_panel(bars_dict, ts_col)
        if price_panel.empty:
            return self._empty_result(frequency)

        # 对齐信号和价格
        all_ts = sorted(set(signals_df[ts_col].unique()) & set(price_panel.index))
        if not all_ts:
            return self._empty_result(frequency)

        signals_df = signals_df[signals_df[ts_col].isin(all_ts)]
        price_panel = price_panel.loc[all_ts]

        # 构建权重面板
        weight_panel = self._build_weight_panel(signals_df, price_panel.columns, all_ts, ts_col)

        # 向量化收益计算
        daily_returns = price_panel.pct_change().fillna(0)
        weight_prev = weight_panel.shift(1).fillna(0)
        portfolio_returns = (weight_prev * daily_returns).sum(axis=1)

        # 成本
        turnover = weight_panel.diff().abs().sum(axis=1).fillna(0)
        cost_rate = self._config.commission_rate + self._config.stamp_tax_rate + self._config.slippage_rate
        net_returns = portfolio_returns - turnover * cost_rate

        # 权益曲线
        equity = (1 + net_returns).cumprod() * self._config.initial_cash
        equity_series = pd.Series(equity, index=all_ts)

        # 绩效指标
        n_bars = len(net_returns)
        total_return = float(equity.iloc[-1] / self._config.initial_cash - 1) if n_bars > 0 else 0.0
        annual_factor = bars_per_year / n_bars if n_bars > 0 else 1.0
        annual_return = float((1 + total_return) ** annual_factor - 1) if total_return > -1 else -1.0
        sharpe = float(net_returns.mean() / net_returns.std() * np.sqrt(bars_per_year)) if net_returns.std() > 0 else 0.0
        peak = equity.cummax()
        drawdown = ((peak - equity) / peak).fillna(0)
        max_dd = float(drawdown.max())
        win_rate = float((net_returns > 0).sum() / max(n_bars, 1))

        return MultiFreqResult(
            equity_curve=equity_series,
            daily_returns=net_returns,
            total_return=total_return,
            annual_return=annual_return,
            sharpe=sharpe,
            max_drawdown=max_dd,
            win_rate=win_rate,
            turnover=float(turnover.sum()),
            total_fees=float(turnover.sum() * cost_rate),
            n_bars=n_bars,
            frequency=frequency,
            metadata={"bars_per_year": bars_per_year, "label": freq_cfg["label"]},
        )

    def run_daily(self, signals_df: pd.DataFrame, klines_dict: dict[str, pd.DataFrame]) -> MultiFreqResult:
        """日线回测快捷方式。"""
        return self.run(signals_df, klines_dict, frequency="1d")

    def run_minute(self, signals_df: pd.DataFrame, minute_dict: dict[str, pd.DataFrame]) -> MultiFreqResult:
        """分钟回测快捷方式。"""
        return self.run(signals_df, minute_dict, frequency="1m")

    def run_tick(self, signals_df: pd.DataFrame, tick_dict: dict[str, pd.DataFrame]) -> MultiFreqResult:
        """Tick 回测快捷方式。"""
        return self.run(signals_df, tick_dict, frequency="tick")

    def batch_run(
        self,
        signals_dict: dict[str, pd.DataFrame],
        bars_dict: dict[str, pd.DataFrame],
        *,
        frequency: str = "1d",
    ) -> dict[str, MultiFreqResult]:
        """批量回测。"""
        results = {}
        for name, signals in signals_dict.items():
            try:
                results[name] = self.run(signals, bars_dict, frequency=frequency)
            except Exception as e:
                logger.warning(f"Multi-freq backtest failed for '{name}': {e}")
        return results

    def _build_price_panel(self, bars_dict: dict[str, pd.DataFrame], ts_col: str) -> pd.DataFrame:
        panels = []
        for code, df in bars_dict.items():
            if df is None or df.empty or "close" not in df.columns or ts_col not in df.columns:
                continue
            s = df.set_index(ts_col)["close"].rename(code)
            panels.append(s)
        if not panels:
            return pd.DataFrame()
        return pd.concat(panels, axis=1).sort_index()

    def _build_weight_panel(
        self, signals_df: pd.DataFrame, codes: pd.Index, timestamps: list, ts_col: str,
    ) -> pd.DataFrame:
        pivot = signals_df.pivot_table(
            index=ts_col, columns="code", values="weight", aggfunc="first",
        )
        pivot = pivot.reindex(index=timestamps, columns=codes, fill_value=0.0)
        row_sums = pivot.sum(axis=1)
        mask = row_sums > 0
        pivot.loc[mask] = pivot.loc[mask].div(row_sums[mask], axis=0)
        return pivot

    def _empty_result(self, frequency: str) -> MultiFreqResult:
        return MultiFreqResult(
            equity_curve=pd.Series(dtype=float),
            daily_returns=pd.Series(dtype=float),
            total_return=0.0, annual_return=0.0, sharpe=0.0,
            max_drawdown=0.0, win_rate=0.0, turnover=0.0,
            total_fees=0.0, n_bars=0, frequency=frequency,
        )

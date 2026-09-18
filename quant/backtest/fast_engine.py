"""极速回测引擎 — 向量化回测用于大规模策略筛选

设计目标:
  参考 BigQuant "极速模式"，用向量化计算替代逐笔撮合，
  适合需要同时回测数百个因子/策略组合的场景。

与标准 BacktestSimulator 的区别:
  - 极速: 向量化 pandas 操作，不逐笔撮合
  - 精度: 不做逐单成交量限制/T+1/涨跌停检测
  - 用途: 大规模筛选 + IC 回测验证
  - 验证: 筛选后的最优策略仍需 BacktestSimulator 精确回测

用法:
    engine = VectorizedBacktest()
    result = engine.run(
        signals_df=signals,     # [date, code, weight]
        klines_dict=klines,     # {code: DataFrame}
        initial_cash=1_000_000,
    )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger("quant.backtest.fast")


@dataclass(frozen=True, slots=True)
class FastBacktestConfig:
    """极速回测配置。"""
    initial_cash: float = 1_000_000.0
    commission_rate: float = 0.0003
    stamp_tax_rate: float = 0.0005
    slippage_rate: float = 0.0001
    lot_size: int = 100
    version: str = "fast-backtest-v1"


@dataclass(slots=True)
class FastBacktestResult:
    """极速回测结果。"""
    equity_curve: pd.Series
    daily_returns: pd.Series
    total_return: float
    annual_return: float
    sharpe: float
    max_drawdown: float
    win_rate: float
    turnover: float
    total_fees: float
    n_trades: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "total_return": round(self.total_return, 6),
            "annual_return": round(self.annual_return, 6),
            "sharpe": round(self.sharpe, 4),
            "max_drawdown": round(self.max_drawdown, 6),
            "win_rate": round(self.win_rate, 4),
            "turnover": round(self.turnover, 6),
            "total_fees": round(self.total_fees, 2),
            "n_trades": self.n_trades,
        }


class VectorizedBacktest:
    """向量化极速回测引擎。"""

    def __init__(self, config: FastBacktestConfig | None = None):
        self._config = config or FastBacktestConfig()

    def run(
        self,
        signals_df: pd.DataFrame,
        klines_dict: dict[str, pd.DataFrame],
        *,
        benchmark_returns: pd.Series | None = None,
    ) -> FastBacktestResult:
        """运行向量化回测。

        Args:
            signals_df: 信号表 [date, code, weight]
                        weight > 0 表示目标权重, =0 表示平仓
            klines_dict: {code: DataFrame(date, close, ...)}
            benchmark_returns: 基准日收益率 (可选)

        Returns:
            FastBacktestResult
        """
        if signals_df is None or signals_df.empty:
            return self._empty_result()

        # 构建收盘价面板: [date x code]
        price_panel = self._build_price_panel(klines_dict)
        if price_panel.empty:
            return self._empty_result()

        # 对齐信号和价格
        all_dates = sorted(set(signals_df["date"].unique()) & set(price_panel.index))
        if not all_dates:
            return self._empty_result()

        signals_df = signals_df[signals_df["date"].isin(all_dates)]
        price_panel = price_panel.loc[all_dates]

        # 构建权重面板: [date x code]
        weight_panel = self._build_weight_panel(signals_df, price_panel.columns, all_dates)

        # 向量化计算日收益率
        daily_returns = price_panel.pct_change().fillna(0)

        # 组合收益 = sum(weight_prev * return_today)
        weight_prev = weight_panel.shift(1).fillna(0)
        portfolio_returns = (weight_prev * daily_returns).sum(axis=1)

        # 成本: 换手 * 成本率
        turnover = weight_panel.diff().abs().sum(axis=1).fillna(0)
        cost_rate = self._config.commission_rate + self._config.stamp_tax_rate + self._config.slippage_rate
        daily_costs = turnover * cost_rate
        net_returns = portfolio_returns - daily_costs

        # 权益曲线
        equity = (1 + net_returns).cumprod() * self._config.initial_cash
        equity_series = pd.Series(equity, index=all_dates)

        # 绩效指标
        total_return = float(equity.iloc[-1] / self._config.initial_cash - 1) if len(equity) > 0 else 0.0
        n_days = len(net_returns)
        annual_factor = 252 / n_days if n_days > 0 else 1.0
        annual_return = float((1 + total_return) ** annual_factor - 1) if total_return > -1 else -1.0
        sharpe = float(net_returns.mean() / net_returns.std() * np.sqrt(252)) if net_returns.std() > 0 else 0.0
        peak = equity.cummax()
        drawdown = ((peak - equity) / peak).fillna(0)
        max_dd = float(drawdown.max())
        win_rate = float((net_returns > 0).sum() / max(n_days, 1))

        return FastBacktestResult(
            equity_curve=equity_series,
            daily_returns=net_returns,
            total_return=total_return,
            annual_return=annual_return,
            sharpe=sharpe,
            max_drawdown=max_dd,
            win_rate=win_rate,
            turnover=float(turnover.sum()),
            total_fees=float(daily_costs.sum()),
            n_trades=int(turnover.sum() * len(price_panel.columns) / 2),
        )

    def batch_run(
        self,
        signals_dict: dict[str, pd.DataFrame],
        klines_dict: dict[str, pd.DataFrame],
    ) -> dict[str, FastBacktestResult]:
        """批量回测多个信号集, 返回 {name: result}。"""
        results = {}
        for name, signals in signals_dict.items():
            try:
                results[name] = self.run(signals, klines_dict)
            except Exception as e:
                logger.warning(f"Fast backtest failed for '{name}': {e}")
        return results

    def _build_price_panel(self, klines_dict: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """构建收盘价面板 [date x code]。"""
        panels = []
        for code, df in klines_dict.items():
            if df is None or df.empty or "close" not in df.columns or "date" not in df.columns:
                continue
            s = df.set_index("date")["close"].rename(code)
            panels.append(s)
        if not panels:
            return pd.DataFrame()
        return pd.concat(panels, axis=1).sort_index()

    def _build_weight_panel(
        self, signals_df: pd.DataFrame, codes: pd.Index, dates: list
    ) -> pd.DataFrame:
        """从信号表构建权重面板 [date x code]。"""
        pivot = signals_df.pivot_table(
            index="date", columns="code", values="weight", aggfunc="first",
        )
        # 对齐到完整日期和股票列表
        pivot = pivot.reindex(index=dates, columns=codes, fill_value=0.0)
        # 归一化: 每天权重之和 = 1 (如有多头)
        row_sums = pivot.sum(axis=1)
        mask = row_sums > 0
        pivot.loc[mask] = pivot.loc[mask].div(row_sums[mask], axis=0)
        return pivot

    def _empty_result(self) -> FastBacktestResult:
        return FastBacktestResult(
            equity_curve=pd.Series(dtype=float),
            daily_returns=pd.Series(dtype=float),
            total_return=0.0, annual_return=0.0, sharpe=0.0,
            max_drawdown=0.0, win_rate=0.0, turnover=0.0,
            total_fees=0.0, n_trades=0,
        )

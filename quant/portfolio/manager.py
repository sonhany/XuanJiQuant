"""多策略组合管理器

设计目标:
  支持多个策略独立运行，组合层做资金分配和风险预算，
  组合级归因分析 (Brinson 风格)。

核心概念:
  StrategySlot — 单个策略的配置 (名称/权重/参数/状态)
  PortfolioManager — 组合层管理 (注册策略/分配资金/归因/汇总)

与 BacktestSimulator 的关系:
  BacktestSimulator 是单策略回测引擎；
  PortfolioManager 在其上层，管理多个策略的组合。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd

logger = logging.getLogger("quant.portfolio")


# ── 值对象 ──────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class StrategySlot:
    """单个策略在组合中的配置。"""
    name: str
    weight: float = 0.0
    capital: float = 0.0
    params: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    max_weight: float = 0.5
    min_weight: float = 0.0

    def to_dict(self) -> dict:
        return {
            "name": self.name, "weight": self.weight,
            "capital": self.capital, "params": self.params,
            "enabled": self.enabled,
        }


@dataclass(slots=True)
class StrategyResult:
    """单策略回测结果摘要。"""
    name: str
    total_return: float = 0.0
    annual_return: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    equity_curve: pd.Series | None = None
    daily_returns: pd.Series | None = None
    fills: list[dict] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name, "total_return": self.total_return,
            "annual_return": self.annual_return, "sharpe": self.sharpe,
            "max_drawdown": self.max_drawdown, "win_rate": self.win_rate,
            "n_fills": len(self.fills),
        }


@dataclass(slots=True)
class PortfolioSnapshot:
    """组合级快照。"""
    date: str
    total_equity: float
    cash: float
    weights: dict[str, float]
    daily_return: float = 0.0
    cumulative_return: float = 0.0
    drawdown: float = 0.0


@dataclass(slots=True)
class AttributionResult:
    """Brinson 归因结果。"""
    strategy_name: str
    weight_effect: float = 0.0
    selection_effect: float = 0.0
    interaction_effect: float = 0.0
    total_contribution: float = 0.0


# ── 组合管理器 ──────────────────────────────────────────────

class PortfolioManager:
    """多策略组合管理器。

    用法:
        pm = PortfolioManager(total_capital=1_000_000)
        pm.register(StrategySlot("momentum", weight=0.4))
        pm.register(StrategySlot("mean_revert", weight=0.6))
        pm.allocate()

        # 运行各策略后...
        pm.update_result("momentum", momentum_result)
        pm.update_result("mean_revert", mean_revert_result)

        summary = pm.summary()
        attribution = pm.brinson_attribution(benchmark_returns)
    """

    def __init__(self, total_capital: float = 1_000_000.0):
        self._total_capital = total_capital
        self._slots: dict[str, StrategySlot] = {}
        self._results: dict[str, StrategyResult] = {}
        self._snapshots: list[PortfolioSnapshot] = []

    # ── 策略注册 ─────────────────────────────────────────

    def register(self, slot: StrategySlot) -> None:
        """注册策略到组合。"""
        if slot.name in self._slots:
            logger.warning(f"Strategy '{slot.name}' already registered, overwriting")
        self._slots[slot.name] = slot

    def unregister(self, name: str) -> None:
        self._slots.pop(name, None)
        self._results.pop(name, None)

    def list_strategies(self) -> list[StrategySlot]:
        return list(self._slots.values())

    # ── 资金分配 ─────────────────────────────────────────

    def allocate(self) -> dict[str, float]:
        """按权重分配资金到各策略。返回 {strategy_name: capital}。"""
        enabled = {n: s for n, s in self._slots.items() if s.enabled}
        if not enabled:
            return {}
        total_weight = sum(s.weight for s in enabled.values())
        if total_weight <= 0:
            # 等权分配
            per = self._total_capital / len(enabled)
            for name, slot in enabled.items():
                self._slots[name] = StrategySlot(
                    name=slot.name, weight=1.0 / len(enabled),
                    capital=per, params=slot.params, enabled=slot.enabled,
                    max_weight=slot.max_weight, min_weight=slot.min_weight,
                )
            return {n: per for n in enabled}
        allocations = {}
        for name, slot in enabled.items():
            normalized = slot.weight / total_weight
            cap = self._total_capital * normalized
            self._slots[name] = StrategySlot(
                name=slot.name, weight=slot.weight,
                capital=cap, params=slot.params, enabled=slot.enabled,
                max_weight=slot.max_weight, min_weight=slot.min_weight,
            )
            allocations[name] = cap
        return allocations

    def optimize_equal_risk(self, volatilities: dict[str, float]) -> dict[str, float]:
        """等风险贡献 (ERC) 优化: 各策略风险贡献相等。

        Args:
            volatilities: {strategy_name: annualized_vol}

        Returns:
            {strategy_name: optimized_weight}
        """
        enabled = [n for n, s in self._slots.items() if s.enabled and n in volatilities]
        if not enabled:
            return {}
        vols = np.array([volatilities[n] for n in enabled])
        inv_vols = 1.0 / np.maximum(vols, 1e-8)
        weights = inv_vols / inv_vols.sum()
        result = {}
        for n, w in zip(enabled, weights):
            slot = self._slots[n]
            self._slots[n] = StrategySlot(
                name=slot.name, weight=float(w),
                capital=self._total_capital * float(w),
                params=slot.params, enabled=slot.enabled,
                max_weight=slot.max_weight, min_weight=slot.min_weight,
            )
            result[n] = float(w)
        return result

    # ── 结果输入 ─────────────────────────────────────────

    def update_result(self, name: str, result: StrategyResult) -> None:
        """输入单策略回测结果。"""
        self._results[name] = result

    # ── 组合汇总 ─────────────────────────────────────────

    def summary(self) -> dict:
        """组合级汇总: 加权收益/夏普/最大回撤。

        优先从 daily_returns 计算真实组合指标；
        若无 daily_returns 则用各策略 total_return 的加权近似
        (需各策略时间窗口一致才精确)。
        """
        if not self._results:
            return {"total_capital": self._total_capital, "strategies": {}}

        strategies = {}
        for name, result in self._results.items():
            slot = self._slots.get(name)
            weight = slot.weight if slot else 0.0
            strategies[name] = {
                **result.to_dict(),
                "allocated_weight": weight,
                "allocated_capital": slot.capital if slot else 0.0,
            }

        # 组合级加权指标
        total_weight = sum(
            slot.weight for name, slot in self._slots.items()
            if name in self._results and slot.enabled
        )
        if total_weight <= 0:
            return {"total_capital": self._total_capital, "strategies": strategies}

        # 优先: 从 daily_returns 计算真实组合收益
        has_daily = any(
            self._results[n].daily_returns is not None
            and not (self._results[n].daily_returns is not None
                     and getattr(self._results[n].daily_returns, "empty", True))
            for n in self._results if n in self._slots
        )
        if has_daily:
            # 对齐所有策略的 daily_returns，加权合成组合收益
            all_returns = {}
            for name in self._results:
                if name not in self._slots:
                    continue
                dr = self._results[name].daily_returns
                if dr is not None and not getattr(dr, "empty", True):
                    all_returns[name] = dr
            if all_returns:
                ret_df = pd.DataFrame(all_returns)
                weights_dict = {n: self._slots[n].weight for n in ret_df.columns}
                weights_arr = np.array([weights_dict.get(c, 0.0) for c in ret_df.columns])
                w_sum = weights_arr.sum()
                if w_sum > 0:
                    weights_arr = weights_arr / w_sum
                combo_daily = (ret_df * weights_arr).sum(axis=1)
                combo_daily = combo_daily.dropna()
                if len(combo_daily) > 0:
                    n_days = len(combo_daily)
                    combo_cum = float((1 + combo_daily).prod() - 1)
                    annual_factor = 252 / n_days
                    combo_annual = float((1 + combo_cum) ** annual_factor - 1) if combo_cum > -1 else -1.0
                    combo_sharpe = float(
                        combo_daily.mean() / combo_daily.std() * np.sqrt(252)
                    ) if combo_daily.std() > 0 else 0.0
                    peak = (1 + combo_daily).cumprod()
                    dd = ((peak.cummax() - peak) / peak.cummax()).fillna(0)
                    combo_dd = float(dd.max())
                    return {
                        "total_capital": self._total_capital,
                        "combo_return": round(combo_cum, 6),
                        "combo_annual_return": round(combo_annual, 6),
                        "combo_sharpe": round(combo_sharpe, 4),
                        "combo_max_drawdown": round(combo_dd, 6),
                        "n_strategies": len(strategies),
                        "strategies": strategies,
                        "calc_method": "daily_returns",
                    }

        # 回退: 各策略 total_return 加权近似 (需各策略时间窗口一致)
        combo_return = sum(
            self._results[name].total_return * self._slots[name].weight
            for name in self._results if name in self._slots
        ) / total_weight
        combo_sharpe = sum(
            self._results[name].sharpe * self._slots[name].weight
            for name in self._results if name in self._slots
        ) / total_weight
        max_dd = max(
            (self._results[name].max_drawdown for name in self._results if name in self._slots),
            default=0.0,
        )
        return {
            "total_capital": self._total_capital,
            "combo_return": round(combo_return, 6),
            "combo_sharpe": round(combo_sharpe, 4),
            "combo_max_drawdown": round(max_dd, 6),
            "n_strategies": len(strategies),
            "strategies": strategies,
            "calc_method": "weighted_approximation",
        }

    # ── Brinson 归因 ────────────────────────────────────

    def brinson_attribution(
        self,
        benchmark_daily_returns: pd.Series,
        strategy_weights: dict[str, float] | None = None,
    ) -> list[AttributionResult]:
        """Brinson 归因: 量化各策略对组合超额收益的贡献。

        简化 Brinson 模型:
          weight_effect = (w_s - w_b) * (R_b)
          selection_effect = w_b * (R_s - R_b)
          interaction_effect = (w_s - w_b) * (R_s - R_b)
        """
        if benchmark_daily_returns is None or benchmark_daily_returns.empty:
            return []

        bm = benchmark_daily_returns.mean() * 252  # 年化
        results = []

        for name, result in self._results.items():
            if result.daily_returns is None or result.daily_returns.empty:
                continue
            slot = self._slots.get(name)
            w_s = slot.weight if slot else 0.0
            w_b = 1.0 / len(self._results) if self._results else 0.0
            r_s = result.annual_return

            we = (w_s - w_b) * bm
            se = w_b * (r_s - bm)
            ie = (w_s - w_b) * (r_s - bm)

            results.append(AttributionResult(
                strategy_name=name,
                weight_effect=round(we, 6),
                selection_effect=round(se, 6),
                interaction_effect=round(ie, 6),
                total_contribution=round(we + se + ie, 6),
            ))
        return results

    # ── 组合权重快照 ─────────────────────────────────────

    def snapshot(self, date: str = "") -> PortfolioSnapshot:
        """生成当前组合权重快照。"""
        weights = {n: s.weight for n, s in self._slots.items()}
        return PortfolioSnapshot(
            date=date,
            total_equity=self._total_capital,
            cash=0.0,
            weights=weights,
        )

    def to_dict(self) -> dict:
        return {
            "total_capital": self._total_capital,
            "strategies": [s.to_dict() for s in self._slots.values()],
            "summary": self.summary(),
        }

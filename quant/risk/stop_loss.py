"""组合级止损引擎 — 主动平仓而非仅熔断。

设计目标:
  现有 risk/gateway.py 的 max_drawdown_fuse 只是阻止新买入，
  不会主动卖出已有仓位。stop_loss 模块补全这个缺口:
    1. 个股止损: 持仓亏损达到阈值 → 卖出信号
    2. 组合止损: 总权益回撤达到阈值 → 全部清仓
    3. 移动止盈: 浮盈回吐达到阈值 → 卖出锁定利润
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger("quant.risk.stop_loss")


@dataclass(frozen=True, slots=True)
class StopLossConfig:
    """止损配置。"""
    # 个股止损
    stock_stop_loss_pct: float = 0.08     # 单股亏损 8% 触发止损
    stock_stop_profit_pct: float = 0.20   # 单股盈利 20% 触发止盈
    # 组合止损
    portfolio_stop_loss_pct: float = 0.12  # 组合回撤 12% 触发全部清仓
    portfolio_daily_loss_pct: float = 0.05 # 单日亏损 5% 触发全部清仓
    # 移动止盈
    trailing_stop_pct: float = 0.10       # 从最高点回撤 10% 触发


@dataclass(slots=True)
class StopLossSignal:
    """止损信号。"""
    code: str
    reason: str  # 'stock_stop_loss' / 'stock_stop_profit' / 'trailing_stop' / 'portfolio_stop_loss'
    urgency: str = 'high'  # 'high' = 立即卖出, 'medium' = 下一 Bar 卖出
    quantity_pct: float = 1.0  # 卖出比例 (1.0 = 全部清仓)
    metadata: dict[str, Any] | None = None


class StopLossEngine:
    """止损引擎: 监控持仓和组合权益，生成止损信号。"""

    def __init__(self, config: StopLossConfig | None = None):
        self._config = config or StopLossConfig()
        self._peak_equity: float = 0.0
        self._position_highs: dict[str, float] = {}  # code → 历史最高价

    def check(
        self,
        positions: dict[str, dict],
        current_equity: float,
        daily_pnl: float = 0.0,
    ) -> list[StopLossSignal]:
        """检查是否触发止损条件。

        Args:
            positions: {code: {quantity, avg_price, current_price, ...}}
            current_equity: 当前总权益
            daily_pnl: 当日盈亏金额

        Returns:
            止损信号列表 (可能为空)
        """
        signals: list[StopLossSignal] = []

        # 更新最高权益
        if current_equity > self._peak_equity:
            self._peak_equity = current_equity

        # 1. 组合止损
        if self._peak_equity > 0:
            drawdown = (self._peak_equity - current_equity) / self._peak_equity
            if drawdown >= self._config.portfolio_stop_loss_pct:
                logger.warning(f"Portfolio stop-loss triggered: drawdown={drawdown:.2%}")
                signals.append(StopLossSignal(
                    code="__PORTFOLIO__",
                    reason="portfolio_stop_loss",
                    urgency="high",
                    quantity_pct=1.0,
                    metadata={"drawdown_pct": round(drawdown, 4), "peak_equity": self._peak_equity},
                ))
                return signals  # 组合止损优先级最高，直接清仓

        # 单日亏损止损
        if current_equity > 0 and daily_pnl < 0:
            daily_loss_pct = abs(daily_pnl) / current_equity
            if daily_loss_pct >= self._config.portfolio_daily_loss_pct:
                logger.warning(f"Daily loss stop triggered: {daily_loss_pct:.2%}")
                signals.append(StopLossSignal(
                    code="__PORTFOLIO__",
                    reason="daily_loss_stop",
                    urgency="high",
                    quantity_pct=1.0,
                    metadata={"daily_loss_pct": round(daily_loss_pct, 4)},
                ))
                return signals

        # 2. 个股止损/止盈
        for code, pos in positions.items():
            avg_price = float(pos.get("avg_price", 0))
            current_price = float(pos.get("current_price", 0))
            quantity = int(pos.get("quantity", 0))
            if avg_price <= 0 or current_price <= 0 or quantity <= 0:
                continue

            # 更新个股最高价
            if current_price > self._position_highs.get(code, 0):
                self._position_highs[code] = current_price

            # 个股止损
            loss_pct = (avg_price - current_price) / avg_price
            if loss_pct >= self._config.stock_stop_loss_pct:
                logger.info(f"Stock stop-loss: {code} loss={loss_pct:.2%}")
                signals.append(StopLossSignal(
                    code=code,
                    reason="stock_stop_loss",
                    urgency="high",
                    quantity_pct=1.0,
                    metadata={"loss_pct": round(loss_pct, 4), "avg_price": avg_price, "current_price": current_price},
                ))
                continue

            # 个股止盈
            profit_pct = (current_price - avg_price) / avg_price
            if profit_pct >= self._config.stock_stop_profit_pct:
                logger.info(f"Stock stop-profit: {code} profit={profit_pct:.2%}")
                signals.append(StopLossSignal(
                    code=code,
                    reason="stock_stop_profit",
                    urgency="medium",
                    quantity_pct=0.5,  # 止盈卖一半
                    metadata={"profit_pct": round(profit_pct, 4)},
                ))
                continue

            # 移动止盈
            high = self._position_highs.get(code, current_price)
            if high > 0:
                trailing_drawdown = (high - current_price) / high
                if trailing_drawdown >= self._config.trailing_stop_pct and profit_pct > 0:
                    logger.info(f"Trailing stop: {code} from_high={trailing_drawdown:.2%}")
                    signals.append(StopLossSignal(
                        code=code,
                        reason="trailing_stop",
                        urgency="medium",
                        quantity_pct=1.0,
                        metadata={"trailing_drawdown": round(trailing_drawdown, 4), "high_price": high},
                    ))

        return signals

    def reset(self) -> None:
        """重置引擎状态 (新回测/新交易日开始时调用)。"""
        self._peak_equity = 0.0
        self._position_highs.clear()

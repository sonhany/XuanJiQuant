"""统一策略回调框架 — 参考 BigQuant "模块化策略回调" 设计。

核心设计:
  StrategyCallback 协议定义 5 个生命周期钩子:
    on_init      — 策略初始化 (加载数据/参数)
    on_bar       — 每根 K 线到达时触发
    on_order     — 订单状态变化时触发
    on_fill      — 成交时触发
    on_stop      — 策略结束时触发

  StrategyEngine 负责调度回调；BacktestSimulator 在事件循环中触发回调。

与现有代码的关系:
  - 现有 5 种内置策略 (factor_rank 等) 保持不变
  - 新回调框架用于: 自定义策略编写、回测事件监听、实时策略扩展
  - 不修改现有 StrategyEngine 的公共接口
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger("quant.strategy.callbacks")


# ── 回调协议 ──────────────────────────────────────────────

@runtime_checkable
class StrategyCallback(Protocol):
    """策略回调接口 — 实现任一方法即可。"""

    def on_init(self, ctx: StrategyContext) -> None:
        """策略初始化: 加载数据、设置参数。"""
        ...

    def on_bar(self, ctx: StrategyContext, bar: BarEvent) -> None:
        """每根 K 线到达: 生成信号、下单。"""
        ...

    def on_order(self, ctx: StrategyContext, event: OrderEvent) -> None:
        """订单状态变化: pending → filled / rejected / cancelled。"""
        ...

    def on_fill(self, ctx: StrategyContext, event: FillEvent) -> None:
        """成交回报: 更新仓位、计算费用。"""
        ...

    def on_stop(self, ctx: StrategyContext) -> None:
        """策略结束: 清理资源、输出报告。"""
        ...


# ── 事件定义 ──────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class BarEvent:
    """K 线事件。"""
    code: str
    date: str
    frequency: str  # '1d', '1m', 'tick'
    open: float
    high: float
    low: float
    close: float
    volume: int = 0
    amount: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OrderEvent:
    """订单事件。"""
    order_id: str
    code: str
    direction: str  # 'buy' / 'sell'
    quantity: int
    price: float
    status: str  # 'pending' / 'filled' / 'rejected' / 'cancelled'
    reject_reason: str | None = None
    timestamp: str = ""


@dataclass(frozen=True, slots=True)
class FillEvent:
    """成交事件。"""
    fill_id: str
    order_id: str
    code: str
    direction: str
    quantity: int
    price: float
    commission: float = 0.0
    slippage: float = 0.0
    stamp_tax: float = 0.0
    timestamp: str = ""


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    """仓位快照。"""
    code: str
    quantity: int
    avg_price: float
    market_value: float
    unrealized_pnl: float = 0.0


# ── 策略上下文 ────────────────────────────────────────────

@dataclass(slots=True)
class StrategyContext:
    """策略运行上下文 — 在回调间共享状态。"""

    # 市场数据
    current_date: str = ""
    current_bar: BarEvent | None = None

    # 仓位
    positions: dict[str, PositionSnapshot] = field(default_factory=dict)

    # 现金
    cash: float = 0.0
    equity: float = 0.0

    # 交易日历
    trade_dates: list[str] = field(default_factory=list)
    bar_index: int = 0

    # 自定义状态 (策略可自由读写)
    state: dict[str, Any] = field(default_factory=dict)

    # 下单接口 (由引擎注入)
    _order_func: Any = field(default=None, repr=False)

    def order(self, code: str, direction: str, quantity: int, price: float = 0.0) -> str:
        """下单。返回 order_id。"""
        if self._order_func is None:
            logger.warning("order_func not injected, order ignored")
            return ""
        return self._order_func(code, direction, quantity, price)

    def get_position(self, code: str) -> PositionSnapshot | None:
        return self.positions.get(code)

    def get_state(self, key: str, default: Any = None) -> Any:
        return self.state.get(key, default)

    def set_state(self, key: str, value: Any) -> None:
        self.state[key] = value


# ── 空回调 (默认实现) ────────────────────────────────────

class NullCallback:
    """空回调 — 所有方法默认 no-op。"""

    def on_init(self, ctx: StrategyContext) -> None:
        pass

    def on_bar(self, ctx: StrategyContext, bar: BarEvent) -> None:
        pass

    def on_order(self, ctx: StrategyContext, event: OrderEvent) -> None:
        pass

    def on_fill(self, ctx: StrategyContext, event: FillEvent) -> None:
        pass

    def on_stop(self, ctx: StrategyContext) -> None:
        pass


# ── 回调调度器 ────────────────────────────────────────────

class CallbackDispatcher:
    """管理多个回调监听器，按注册顺序分发事件。"""

    def __init__(self) -> None:
        self._listeners: list[StrategyCallback] = []

    def register(self, callback: StrategyCallback) -> None:
        self._listeners.append(callback)

    def unregister(self, callback: StrategyCallback) -> None:
        self._listeners = [c for c in self._listeners if c is not callback]

    def dispatch_init(self, ctx: StrategyContext) -> None:
        for cb in self._listeners:
            try:
                cb.on_init(ctx)
            except Exception as e:
                logger.warning(f"on_init failed: {e}")

    def dispatch_bar(self, ctx: StrategyContext, bar: BarEvent) -> None:
        for cb in self._listeners:
            try:
                cb.on_bar(ctx, bar)
            except Exception as e:
                logger.warning(f"on_bar failed for {bar.code}: {e}")

    def dispatch_order(self, ctx: StrategyContext, event: OrderEvent) -> None:
        for cb in self._listeners:
            try:
                cb.on_order(ctx, event)
            except Exception as e:
                logger.warning(f"on_order failed: {e}")

    def dispatch_fill(self, ctx: StrategyContext, event: FillEvent) -> None:
        for cb in self._listeners:
            try:
                cb.on_fill(ctx, event)
            except Exception as e:
                logger.warning(f"on_fill failed: {e}")

    def dispatch_stop(self, ctx: StrategyContext) -> None:
        for cb in self._listeners:
            try:
                cb.on_stop(ctx)
            except Exception as e:
                logger.warning(f"on_stop failed: {e}")

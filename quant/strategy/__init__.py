"""quant/strategy - 策略引擎 + 统一回调框架"""
from .engine import StrategyEngine, ALL_STRATEGIES, STRATEGY_META
from .callbacks import (
    StrategyCallback, NullCallback, CallbackDispatcher,
    StrategyContext, BarEvent, OrderEvent, FillEvent, PositionSnapshot,
)

__all__ = [
    "StrategyEngine", "ALL_STRATEGIES", "STRATEGY_META",
    "StrategyCallback", "NullCallback", "CallbackDispatcher",
    "StrategyContext", "BarEvent", "OrderEvent", "FillEvent", "PositionSnapshot",
]

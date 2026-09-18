"""Phase 2: Event-Driven Backtest Engine

模块结构:
  engine:       标准事件驱动回测 (精确撮合, 逐笔验证)
  fast_engine:  极速向量化回测 (大规模筛选, 不逐笔撮合)
"""
from .engine import BacktestSimulator, PerformanceTracker, EventType
from .engine import PriceBar, Signal, Order, Fill, Position, PortfolioSnapshot
from .fast_engine import VectorizedBacktest, FastBacktestConfig, FastBacktestResult

__all__ = [
    "BacktestSimulator",
    "PerformanceTracker",
    "EventType",
    "PriceBar",
    "Signal",
    "Order",
    "Fill",
    "Position",
    "PortfolioSnapshot",
    "VectorizedBacktest",
    "FastBacktestConfig",
    "FastBacktestResult",
]

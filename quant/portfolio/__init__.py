"""多策略组合管理 — 策略级资金分配 + 组合级归因。

模块结构:
  manager:  组合管理器 (策略注册/资金分配/权重优化/归因)
  risk:     组合风险预算 (VaR/CVaR/相关性约束)
"""
from .manager import PortfolioManager, StrategySlot, PortfolioSnapshot

__all__ = ["PortfolioManager", "StrategySlot", "PortfolioSnapshot"]

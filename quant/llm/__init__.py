"""LLM 深度集成 — 策略辅助生成/因子挖掘/回测解读。

模块结构:
  advisor:    LLM 策略顾问 (因子建议/代码生成/回测解读)
  prompts:    提示词模板
"""
from .advisor import LLMBridge, StrategyAdvisor

__all__ = ["LLMBridge", "StrategyAdvisor"]

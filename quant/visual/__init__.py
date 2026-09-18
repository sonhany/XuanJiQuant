"""可视化策略开发 — 低代码因子构建 + 策略流程编排。

模块结构:
  builder:   因子/策略可视化构建器 (输出 JSON DAG 描述)
  compiler:  DAG 描述 → Python 代码编译器
"""
from .builder import VisualBuilder, Node, Pipeline

__all__ = ["VisualBuilder", "Node", "Pipeline"]

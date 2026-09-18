"""分布式计算抽象 — 参考 FAI 设计的本地并行执行。

模块结构:
  executor:  本地并行执行器 (multiprocessing / concurrent.futures)
  scheduler: 任务调度器 (优先级/依赖/重试)
"""
from .executor import LocalExecutor, TaskResult

__all__ = ["LocalExecutor", "TaskResult"]

"""本地并行执行器 — 参考 BigQuant FAI 的轻量版。

设计目标:
  在单机上用多进程/线程并行加速因子计算、批量回测等 CPU 密集任务。
  不依赖 Ray/Dask，用 Python 标准库 concurrent.futures。

用法:
    executor = LocalExecutor(max_workers=4)
    results = executor.map(compute_factor, codes)
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

logger = logging.getLogger("quant.distributed")


@dataclass(slots=True)
class TaskResult:
    """单任务执行结果。"""
    task_id: str
    success: bool
    result: Any = None
    error: str = ""
    duration_ms: float = 0.0
    worker_id: int = 0


@dataclass(slots=True)
class ExecutionSummary:
    """批量执行汇总。"""
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    total_duration_ms: float = 0.0
    avg_duration_ms: float = 0.0
    results: list[TaskResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total": self.total, "succeeded": self.succeeded,
            "failed": self.failed,
            "total_duration_ms": round(self.total_duration_ms, 1),
            "avg_duration_ms": round(self.avg_duration_ms, 1),
        }


class LocalExecutor:
    """本地并行执行器。

    Args:
        max_workers: 最大并行数 (默认 CPU 核数)
        mode: 'process' (CPU 密集) 或 'thread' (IO 密集)
    """

    def __init__(self, max_workers: int | None = None, mode: str = "process"):
        self._max_workers = max_workers
        self._mode = mode

    def map(
        self,
        fn: Callable,
        items: Sequence,
        *,
        progress_label: str = "",
    ) -> ExecutionSummary:
        """并行执行 fn(item) for item in items。

        Returns:
            ExecutionSummary
        """
        start = time.time()
        executor_cls = ProcessPoolExecutor if self._mode == "process" else ThreadPoolExecutor
        results: list[TaskResult] = []

        with executor_cls(max_workers=self._max_workers) as executor:
            future_to_idx = {
                executor.submit(fn, item): i
                for i, item in enumerate(items)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                task_start = time.time()
                task_id = str(idx)
                try:
                    result = future.result()
                    elapsed = (time.time() - task_start) * 1000
                    results.append(TaskResult(
                        task_id=task_id, success=True, result=result,
                        duration_ms=round(elapsed, 1),
                    ))
                except Exception as e:
                    elapsed = (time.time() - task_start) * 1000
                    results.append(TaskResult(
                        task_id=task_id, success=False, error=str(e),
                        duration_ms=round(elapsed, 1),
                    ))

        elapsed = (time.time() - start) * 1000
        succeeded = sum(1 for r in results if r.success)
        failed = len(results) - succeeded
        avg = elapsed / max(len(results), 1)

        logger.info(
            f"Parallel execution: {succeeded}/{len(results)} succeeded, "
            f"{elapsed:.0f}ms total, {avg:.0f}ms avg"
        )

        return ExecutionSummary(
            total=len(results), succeeded=succeeded, failed=failed,
            total_duration_ms=elapsed, avg_duration_ms=avg,
            results=results,
        )

    def map_with_progress(
        self,
        fn: Callable,
        items: Sequence,
        *,
        batch_size: int = 100,
    ) -> ExecutionSummary:
        """分批并行执行 (大数据量友好)。"""
        all_results: list[TaskResult] = []
        for start in range(0, len(items), batch_size):
            batch = items[start:start + batch_size]
            batch_result = self.map(fn, batch)
            all_results.extend(batch_result.results)
            logger.info(f"Batch {start // batch_size + 1}: {batch_result.succeeded}/{batch_result.total}")

        succeeded = sum(1 for r in all_results if r.success)
        return ExecutionSummary(
            total=len(all_results), succeeded=succeeded,
            failed=len(all_results) - succeeded,
            results=all_results,
        )

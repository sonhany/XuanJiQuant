"""可视化策略构建器 — 低代码因子构建 + 策略流程编排。

设计目标:
  提供 Node/Pipeline 抽象，让用户通过 JSON 描述因子计算流程，
  而不需要手写 Python 代码。前端可拖拽编排，后端编译执行。

核心概念:
  Node — 单步计算单元 (数据源/因子/筛选/排序/输出)
  Pipeline — 有向无环图 (DAG)，描述完整的因子/策略流程
  VisualBuilder — 从 JSON 描述构建并执行 Pipeline

用法:
    builder = VisualBuilder()
    pipeline = builder.from_dict({
        "nodes": [
            {"id": "src", "type": "data_source", "params": {"source": "daily_bar"}},
            {"id": "momentum", "type": "factor", "params": {"func": "ret_5"}},
            {"id": "filter", "type": "filter", "params": {"field": "volume", "op": ">", "value": 0}},
            {"id": "rank", "type": "rank", "params": {"field": "momentum", "top_n": 10}},
            {"id": "out", "type": "output", "params": {"format": "signal"}},
        ],
        "edges": [
            ["src", "momentum"], ["momentum", "filter"],
            ["filter", "rank"], ["rank", "out"],
        ]
    })
    result = pipeline.execute(data_accessor)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd

logger = logging.getLogger("quant.visual")


# ── 节点定义 ──────────────────────────────────────────────

@dataclass(slots=True)
class Node:
    """DAG 计算节点。"""
    id: str
    type: str
    params: dict[str, Any] = field(default_factory=dict)
    inputs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"id": self.id, "type": self.type, "params": self.params, "inputs": self.inputs}


# ── 内置节点处理器 ────────────────────────────────────────

def _process_data_source(params: dict, inputs: list[pd.DataFrame], ctx: dict) -> pd.DataFrame:
    """数据源节点: 从 DataAccessor 加载数据。

    返回单只股票的 DataFrame 或所有股票拼接的长表。
    """
    source = params.get("source", "daily_bar")
    dao = ctx.get("dao")
    if dao is None:
        return pd.DataFrame()
    if source == "daily_bar":
        codes = params.get("codes", dao.universe()[:100])
        batch = dao.kline_batch(codes, tail_rows=params.get("tail_rows", 300))
        if not batch:
            return pd.DataFrame()
        # 拼接为长表: 每行带 code 列
        parts = []
        for code, df in batch.items():
            sub = df.copy()
            sub["code"] = code
            parts.append(sub)
        return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if source == "universe":
        return pd.DataFrame({"code": dao.universe()})
    return pd.DataFrame()


def _process_factor(params: dict, inputs: list[pd.DataFrame], ctx: dict) -> pd.DataFrame:
    """因子计算节点。"""
    func_name = params.get("func", "")
    if not inputs or not isinstance(inputs[0], pd.DataFrame):
        return pd.DataFrame()
    df = inputs[0].copy()
    # 内置因子函数映射
    factor_funcs = {
        "ret_1": lambda d: d["close"].pct_change(1),
        "ret_5": lambda d: d["close"].pct_change(5),
        "ret_20": lambda d: d["close"].pct_change(20),
        "volatility_20": lambda d: d["close"].pct_change().rolling(20).std(),
        "ma_5": lambda d: d["close"].rolling(5).mean(),
        "ma_20": lambda d: d["close"].rolling(20).mean(),
        "ma_cross": lambda d: (d["close"].rolling(5).mean() - d["close"].rolling(20).mean()) / d["close"],
        "volume_ratio": lambda d: d["volume"] / d["volume"].rolling(20).mean(),
    }
    if func_name in factor_funcs:
        df[f"factor_{func_name}"] = factor_funcs[func_name](df)
    elif func_name:
        # 尝试从 FactorEngine 获取
        try:
            from quant.factor.technical import compute_technical
            from quant.factor.price_volume import compute_price_volume
            df = compute_technical(df)
            df = compute_price_volume(df)
        except Exception:
            pass
    return df


def _process_filter(params: dict, inputs: list[pd.DataFrame], ctx: dict) -> pd.DataFrame:
    """筛选节点: 按条件过滤行。"""
    if not inputs or not isinstance(inputs[0], pd.DataFrame):
        return pd.DataFrame()
    df = inputs[0].copy()
    field_name = params.get("field", "")
    op = params.get("op", ">")
    value = params.get("value", 0)
    if field_name and field_name in df.columns:
        col = pd.to_numeric(df[field_name], errors="coerce")
        if op == ">":
            df = df[col > value]
        elif op == "<":
            df = df[col < value]
        elif op == ">=":
            df = df[col >= value]
        elif op == "<=":
            df = df[col <= value]
        elif op == "==":
            df = df[df[field_name] == value]
    return df


def _process_rank(params: dict, inputs: list[pd.DataFrame], ctx: dict) -> pd.DataFrame:
    """排名节点: 按字段排序取 Top N。"""
    if not inputs or not isinstance(inputs[0], pd.DataFrame):
        return pd.DataFrame()
    df = inputs[0].copy()
    field_name = params.get("field", "")
    top_n = params.get("top_n", 10)
    ascending = params.get("ascending", False)
    if field_name and field_name in df.columns:
        df = df.sort_values(field_name, ascending=ascending).head(top_n)
    return df


def _process_weight(params: dict, inputs: list[pd.DataFrame], ctx: dict) -> pd.DataFrame:
    """权重分配节点: 给排名后的股票分配权重。"""
    if not inputs or not isinstance(inputs[0], pd.DataFrame):
        return pd.DataFrame()
    df = inputs[0].copy()
    method = params.get("method", "equal")
    if method == "equal" and len(df) > 0:
        df["weight"] = 1.0 / len(df)
    elif method == "score" and "score" in df.columns:
        total = df["score"].sum()
        df["weight"] = df["score"] / total if total > 0 else 0.0
    return df


def _process_output(params: dict, inputs: list[pd.DataFrame], ctx: dict) -> pd.DataFrame:
    """输出节点: 格式化最终结果。"""
    if not inputs or not isinstance(inputs[0], pd.DataFrame):
        return pd.DataFrame()
    return inputs[0].copy()


_NODE_PROCESSORS: dict[str, Callable] = {
    "data_source": _process_data_source,
    "factor": _process_factor,
    "filter": _process_filter,
    "rank": _process_rank,
    "weight": _process_weight,
    "output": _process_output,
}


# ── Pipeline (DAG) ────────────────────────────────────────

class Pipeline:
    """有向无环图 (DAG) 执行引擎。"""

    def __init__(self, nodes: list[Node], edges: list[tuple[str, str]]):
        self._nodes = {n.id: n for n in nodes}
        self._edges = edges
        self._adj: dict[str, list[str]] = {n.id: [] for n in nodes}
        for src, dst in edges:
            if src in self._adj:
                self._adj[src].append(dst)

    def topological_order(self) -> list[str]:
        """拓扑排序。"""
        in_degree = {n: 0 for n in self._nodes}
        for src, dst in self._edges:
            in_degree[dst] = in_degree.get(dst, 0) + 1
        queue = [n for n, d in in_degree.items() if d == 0]
        order = []
        while queue:
            node = queue.pop(0)
            order.append(node)
            for child in self._adj.get(node, []):
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)
        return order

    def execute(self, ctx: dict | None = None) -> pd.DataFrame | dict[str, pd.DataFrame]:
        """按拓扑序执行 DAG。"""
        ctx = ctx or {}
        results: dict[str, pd.DataFrame] = {}
        order = self.topological_order()

        for node_id in order:
            node = self._nodes[node_id]
            processor = _NODE_PROCESSORS.get(node.type)
            if processor is None:
                logger.warning(f"Unknown node type: {node.type}")
                results[node_id] = pd.DataFrame()
                continue
            input_dfs = [results[inp] for inp in node.inputs if inp in results]
            try:
                result = processor(node.params, input_dfs, ctx)
                results[node_id] = result if isinstance(result, pd.DataFrame) else pd.DataFrame()
            except Exception as e:
                logger.warning(f"Node '{node_id}' failed: {e}")
                results[node_id] = pd.DataFrame()

        # 返回最后一个输出节点的结果
        output_nodes = [n for n in self._nodes.values() if n.type == "output"]
        if output_nodes:
            return results.get(output_nodes[-1].id, pd.DataFrame())
        return results


# ── VisualBuilder ─────────────────────────────────────────

class VisualBuilder:
    """从 JSON 描述构建 Pipeline。"""

    def from_dict(self, spec: dict) -> Pipeline:
        """从 dict 构建 Pipeline。

        spec 格式:
            {
                "nodes": [{"id": ..., "type": ..., "params": ..., "inputs": [...]}],
                "edges": [[src_id, dst_id], ...]
            }
        """
        nodes = [
            Node(
                id=n["id"], type=n["type"],
                params=n.get("params", {}),
                inputs=n.get("inputs", []),
            )
            for n in spec.get("nodes", [])
        ]
        edges = [tuple(e) for e in spec.get("edges", [])]
        return Pipeline(nodes, edges)

    def factor_pipeline(self, factor_names: list[str], top_n: int = 10) -> Pipeline:
        """快速构建因子选股 Pipeline。"""
        nodes = [
            Node(id="src", type="data_source", params={"source": "daily_bar"}),
            Node(id="factors", type="factor", params={"func": factor_names[0] if factor_names else "ret_5"}, inputs=["src"]),
            Node(id="filter", type="filter", params={"field": "volume", "op": ">", "value": 0}, inputs=["factors"]),
            Node(id="rank", type="rank", params={"field": f"factor_{factor_names[0] if factor_names else 'ret_5'}", "top_n": top_n}, inputs=["filter"]),
            Node(id="weight", type="weight", params={"method": "equal"}, inputs=["rank"]),
            Node(id="out", type="output", params={"format": "signal"}, inputs=["weight"]),
        ]
        edges = [("src", "factors"), ("factors", "filter"), ("filter", "rank"), ("rank", "weight"), ("weight", "out")]
        return Pipeline(nodes, edges)

    def to_dict(self, pipeline: Pipeline) -> dict:
        """Pipeline → JSON 描述 (可序列化存储/传输)。"""
        return {
            "nodes": [n.to_dict() for n in pipeline._nodes.values()],
            "edges": list(pipeline._edges),
        }

"""受限的确定性因子 DSL 解释器。

该模块属于普通因子计算域，不生成候选、不调用大模型，也不拥有任何
策略晋升或交易权限。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


ALLOWED_FUNCTIONS = {
    "rolling_mean",
    "rolling_std",
    "rolling_min",
    "rolling_max",
    "rolling_sum",
    "pct_change",
    "rank",
    "zscore",
    "delay",
    "abs_val",
    "log_val",
}
ALLOWED_COLUMNS = {
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "vwap",
    "returns",
    "return",
    "ret",
    "turnover",
    "amplitude",
    "log_close",
    "price",
    "vol",
    "amt",
}
ALLOWED_OPERATORS = {"+", "-", "*", "/"}


def compute_factor(df: pd.DataFrame, dsl: dict) -> pd.Series:
    """解释受限 DSL 并返回与输入索引对齐的因子序列。"""

    if not isinstance(dsl, dict):
        raise ValueError(f"DSL 节点必须是 dict，实际为 {type(dsl)}")
    node_type = dsl.get("type")

    if node_type == "column":
        name = str(dsl.get("name") or "")
        if name not in ALLOWED_COLUMNS:
            raise ValueError(f"不支持的列名: {name}")
        if name in {"vwap", "price"}:
            if "amount" in df.columns and "volume" in df.columns:
                return df["amount"] / df["volume"].replace(0, np.nan)
            return df["close"]
        if name in {"returns", "return", "ret"}:
            return df["close"].pct_change()
        if name in {"turnover", "vol"}:
            return df["volume"] if "volume" in df.columns else pd.Series(0, index=df.index)
        if name == "amt":
            return df["amount"] if "amount" in df.columns else pd.Series(0, index=df.index)
        if name == "amplitude":
            if {"high", "low", "close"}.issubset(df.columns):
                return (df["high"] - df["low"]) / df["close"].replace(0, np.nan)
            return pd.Series(0, index=df.index)
        if name == "log_close":
            return np.log(df["close"].clip(lower=0.0001))
        return df[name]

    if node_type == "number":
        return pd.Series(float(dsl.get("value", 0)), index=df.index)

    if node_type == "func":
        name = str(dsl.get("name") or "")
        if name not in ALLOWED_FUNCTIONS:
            raise ValueError(f"不允许的函数: {name}")
        args = [compute_factor(df, arg) for arg in dsl.get("args", [])]
        if not args:
            raise ValueError(f"函数缺少参数: {name}")
        window = max(2, min(int(dsl.get("window", 20)), 120))
        if name == "rolling_mean":
            return args[0].rolling(window, min_periods=1).mean()
        if name == "rolling_std":
            return args[0].rolling(window, min_periods=1).std()
        if name == "rolling_min":
            return args[0].rolling(window, min_periods=1).min()
        if name == "rolling_max":
            return args[0].rolling(window, min_periods=1).max()
        if name == "rolling_sum":
            return args[0].rolling(window, min_periods=1).sum()
        if name == "pct_change":
            return args[0].pct_change(periods=window)
        if name == "rank":
            return args[0].rank(pct=True)
        if name == "zscore":
            mean = args[0].rolling(window, min_periods=1).mean()
            std = args[0].rolling(window, min_periods=1).std()
            return (args[0] - mean) / std.replace(0, np.nan)
        if name == "delay":
            return args[0].shift(window)
        if name == "abs_val":
            return args[0].abs()
        if name == "log_val":
            return np.log(args[0].clip(lower=0.0001))

    if node_type == "op":
        operator = str(dsl.get("operator") or "")
        if operator not in ALLOWED_OPERATORS:
            raise ValueError(f"不允许的运算符: {operator}")
        left = compute_factor(df, dsl.get("left", {}))
        right = compute_factor(df, dsl.get("right", {}))
        if operator == "+":
            return left + right
        if operator == "-":
            return left - right
        if operator == "*":
            return left * right
        return left / right.replace(0, np.nan)

    raise ValueError(f"未知的 DSL 节点类型: {node_type}")

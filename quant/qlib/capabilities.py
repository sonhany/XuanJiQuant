"""将运行证据归一化为 Qlib 第一阶段的真实能力目录。"""
from __future__ import annotations

from typing import Any


CAPABILITY_STATES = {"可用", "受限", "运行中", "失败", "未接入"}


def _workflow_state(workflow: dict[str, Any] | None) -> str:
    if not workflow:
        return "未接入"
    status = str(workflow.get("status") or "").lower()
    if status in {"running", "queued", "cancelling"}:
        return "运行中"
    if status in {"failed", "incomplete", "partial_failed", "interrupted"}:
        return "失败"
    if status == "succeeded" and workflow.get("artifacts_complete") is True:
        return "可用"
    return "受限"


def _data_state(quality: dict[str, Any] | None) -> str:
    if not quality:
        return "受限"
    return "可用" if quality.get("passed") is True else "失败"


def build_capability_catalog(
    environment: dict[str, Any] | None,
    quality_report: dict[str, Any] | None,
    latest_workflow: dict[str, Any] | None,
    dependencies: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """只根据环境、质量、Recorder 和依赖证据声明能力状态。"""
    environment = environment or {}
    dependencies = dependencies or {}
    data_state = _data_state(quality_report)
    workflow_state = _workflow_state(latest_workflow)
    available_handlers = set((latest_workflow or {}).get("available_handlers") or [])
    available_models = set((latest_workflow or {}).get("available_models") or [])

    def evidenced(value: str, available: set[str]) -> str:
        return "可用" if workflow_state == "可用" and value in available else "受限"

    alpha158_state = evidenced("Alpha158", available_handlers)
    alpha360_state = evidenced("Alpha360", available_handlers)
    lightgbm_state = evidenced("LightGBM", available_models)
    xgboost_state = (
        evidenced("XGBoost", available_models)
        if dependencies.get("xgboost") is True
        else "受限"
    )
    linear_state = evidenced("Linear", available_models)

    catalog = [
        {
            "id": "environment",
            "name": "隔离研究环境",
            "status": "可用" if environment.get("ready") is True else "受限",
            "items": ["pyqlib", "LightGBM", "XGBoost", "本地 SQLite Recorder"],
        },
        {
            "id": "data",
            "name": "六年日频 A 股数据",
            "status": data_state,
            "items": ["PIT 数据", "质量门禁", "Qlib bin", "版本与哈希"],
        },
        {
            "id": "workflow",
            "name": "官方 Workflow 与 Recorder",
            "status": workflow_state,
            "items": ["SignalRecord", "SigAnaRecord", "PortAnaRecord", "八项必需产物"],
        },
        {
            "id": "alpha158",
            "name": "Alpha158",
            "status": alpha158_state,
            "items": ["固定处理器", "固定标签", "时间顺序切分"],
        },
        {
            "id": "alpha360",
            "name": "Alpha360",
            "status": alpha360_state,
            "items": ["季度固定矩阵", "时间顺序切分"],
        },
        {
            "id": "lightgbm",
            "name": "LightGBM",
            "status": lightgbm_state,
            "items": ["周基线", "月度滚动", "季度矩阵"],
        },
        {
            "id": "xgboost",
            "name": "XGBoost",
            "status": xgboost_state,
            "items": ["季度固定矩阵"],
        },
        {
            "id": "linear",
            "name": "线性基线",
            "status": linear_state,
            "items": ["季度固定矩阵", "基准对照"],
        },
        {
            "id": "deep_learning",
            "name": "深度学习模型",
            "status": "未接入",
            "items": ["第二阶段评估"],
        },
        {
            "id": "meta",
            "name": "Meta 学习",
            "status": "未接入",
            "items": ["第二阶段评估"],
        },
        {
            "id": "rl",
            "name": "强化学习",
            "status": "未接入",
            "items": ["第二阶段评估"],
        },
        {
            "id": "high_frequency",
            "name": "高频研究",
            "status": "未接入",
            "items": ["第二阶段评估"],
        },
    ]
    if any(item["status"] not in CAPABILITY_STATES for item in catalog):
        raise ValueError("invalid Qlib capability state")
    return catalog

"""Strict, independent GLM valuation track."""
from __future__ import annotations

import json
from typing import Any, Callable

from .contracts import model_result, safe_number


PROMPT_VERSION = "valuation-v2"
_ARRAY_FIELDS = (
    "assumptions",
    "drivers",
    "risks",
    "invalidation_conditions",
)


def _error(message: str) -> dict:
    return model_result(
        "glm",
        "error",
        error=message,
        details={"prompt_version": PROMPT_VERSION},
    )


def validate_glm_output(
    payload: Any,
    *,
    current_price: float | None,
) -> dict:
    """Validate GLM output without repairing or guessing invalid fields."""
    if not isinstance(payload, dict):
        return _error("GLM返回值不是JSON对象")

    low = safe_number(payload.get("target_low"))
    mid = safe_number(payload.get("target_mid"))
    high = safe_number(payload.get("target_high"))
    confidence = safe_number(payload.get("confidence"))
    if low is None or mid is None or high is None:
        return _error("GLM目标价格字段缺失或不是有限数值")
    if not (0 < low <= mid <= high):
        return _error("GLM目标价格必须为正数且按低中高排序")
    if confidence is None or not (0 <= confidence <= 1):
        return _error("GLM置信度必须位于0到1之间")

    price = safe_number(current_price)
    if price is None or price <= 0:
        return _error("缺少有效当前价格，无法校验GLM估值边界")
    for label, value in (("low", low), ("mid", mid), ("high", high)):
        ratio = max(value / price, price / value)
        if ratio > 5:
            return _error(f"GLM {label}价格偏离当前价格超过5倍")

    arrays: dict[str, list[str]] = {}
    for field in _ARRAY_FIELDS:
        raw = payload.get(field)
        if (
            not isinstance(raw, list)
            or not raw
            or any(not isinstance(item, str) or not item.strip() for item in raw)
        ):
            return _error(f"GLM字段{field}必须是非空字符串数组")
        arrays[field] = [item.strip()[:300] for item in raw[:20]]

    model_version = payload.get("model_version")
    prompt_version = payload.get("prompt_version")
    if not isinstance(model_version, str) or not model_version.strip():
        return _error("GLM缺少model_version")
    if not isinstance(prompt_version, str) or not prompt_version.strip():
        return _error("GLM缺少prompt_version")
    if prompt_version.strip() != PROMPT_VERSION:
        return _error(f"GLM prompt_version必须为{PROMPT_VERSION}")

    return model_result(
        "glm",
        "success",
        low=low,
        mid=mid,
        high=high,
        confidence=confidence,
        details={
            **arrays,
            "model_version": model_version.strip()[:120],
            "prompt_version": prompt_version.strip()[:120],
            "safety_boundary": "independent_research_only_no_order_action",
        },
    )


def glm_valuation(
    structured_input: dict,
    *,
    current_price: float | None,
    chat_json_fn: Callable[..., dict] | None = None,
    provider: str = "glm",
    model: str | None = None,
) -> tuple[dict, dict]:
    """Call the configured LLM client and return validation plus call metadata."""
    if chat_json_fn is None:
        from scripts.llm_client import chat_json

        chat_json_fn = chat_json
    system_prompt = (
        "你是中国A股估值研究员。只做研究估值，不生成交易指令。"
        "根据给定的规则估值、财务、行情、行业和市场状态输出严格JSON。"
        "不得修改或覆盖规则估值，不得省略风险和失效条件。"
        "规则共识的唯一正确口径是：绝对估值与相对估值先按置信度、数据质量和历史校准加权，"
        "市场状态随后只调整一次。严禁描述为绝对、相对、市场三轨共同加权或再次平均。"
        "GLM目标区间是独立研究意见，不得写回规则共识。"
    )
    user_prompt = (
        "输出字段必须且只能按以下语义提供："
        "target_low,target_mid,target_high,confidence,"
        "assumptions[],drivers[],risks[],invalidation_conditions[],"
        f"model_version,prompt_version。prompt_version必须为{PROMPT_VERSION}。"
        "assumptions中必须准确说明规则共识的两阶段口径，不能声称市场轨参与基础权重。\n"
        + json.dumps(structured_input, ensure_ascii=False, separators=(",", ":"))
    )
    try:
        response = chat_json_fn(
            provider,
            system_prompt,
            user_prompt,
            temperature=0.2,
            timeout=105,
            max_tokens=3600,
            max_retries=0,
            scene="valuation",
            model=model,
        )
    except Exception as exc:
        return _error(f"GLM调用异常: {str(exc)[:200]}"), {}
    if not isinstance(response, dict) or not response.get("success"):
        message = (
            str(response.get("error") or "GLM调用失败")
            if isinstance(response, dict)
            else "GLM调用返回无效"
        )
        return _error(message[:240]), response if isinstance(response, dict) else {}
    result = validate_glm_output(
        response.get("data"),
        current_price=current_price,
    )
    return result, {
        "usage": response.get("usage") or {},
        "provider": provider,
        "model": response.get("model") or model,
    }

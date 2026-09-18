"""LLM 策略顾问 — 因子挖掘建议/策略代码生成/回测解读。

依赖:
  - quant.llm.prompts: 提示词模板
  - 外部 LLM API (通过 HTTP 或本地模型)

设计原则:
  - LLM 只提供"建议"，不直接执行交易
  - 所有 LLM 输出需人工审核
  - 与现有 FactorEngine / BacktestSimulator 无缝集成
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

from .prompts import (
    FACTOR_DISCOVERY_PROMPT,
    STRATEGY_GENERATION_PROMPT,
    BACKTEST_INTERPRET_PROMPT,
    FACTOR_ADVICE_PROMPT,
)

logger = logging.getLogger("quant.llm.advisor")


@dataclass(slots=True)
class LLMResponse:
    """LLM 响应包装。"""
    content: str
    model: str = ""
    tokens_used: int = 0
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class LLMBridge:
    """LLM 调用桥接层 — 支持多种后端。

    后端:
      1. 本地 HTTP API (如 Ollama, vLLM)
      2. 远程 API (OpenAI/DeepSeek)
      3. Mock (测试/离线)
    """

    def __init__(
        self,
        api_url: str = "",
        api_key: str = "",
        model: str = "",
        timeout: float = 30.0,
    ):
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    def chat(
        self,
        prompt: str,
        *,
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> LLMResponse:
        """调用 LLM。"""
        if not self._api_url:
            return self._mock_response(prompt)
        try:
            try:
                import requests
            except ImportError:
                logger.warning("requests 库未安装, 无法调用 LLM API. 请运行: pip install requests")
                return self._mock_response(prompt)
            headers = {"Content-Type": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            payload = {
                "model": self._model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            resp = requests.post(
                f"{self._api_url}/v1/chat/completions",
                json=payload, headers=headers, timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            tokens = data.get("usage", {}).get("total_tokens", 0)
            return LLMResponse(content=content, model=self._model, tokens_used=tokens)
        except Exception as e:
            logger.warning(f"LLM call failed: {e}")
            return self._mock_response(prompt)

    def _mock_response(self, prompt: str) -> LLMResponse:
        """离线/Mock 响应 (测试用)。"""
        return LLMResponse(
            content="[LLM offline] 请配置 api_url 启用 LLM 功能。",
            model="mock", metadata={"offline": True},
        )


class StrategyAdvisor:
    """策略顾问: 封装 LLM 调用为业务语义。"""

    def __init__(self, bridge: LLMBridge | None = None):
        self._bridge = bridge or LLMBridge()

    def discover_factors(self, existing_factors: Sequence[str]) -> LLMResponse:
        """建议新因子方向。"""
        prompt = FACTOR_DISCOVERY_PROMPT.format(
            n_factors=len(existing_factors),
            factor_list="\n".join(f"  - {f}" for f in existing_factors),
        )
        return self._bridge.chat(prompt, temperature=0.8, max_tokens=3000)

    def generate_strategy(
        self,
        factor_names: Sequence[str],
        hold_days: int = 5,
    ) -> LLMResponse:
        """生成策略代码。"""
        prompt = STRATEGY_GENERATION_PROMPT.format(
            factor_names=", ".join(factor_names),
            hold_days=hold_days,
        )
        return self._bridge.chat(prompt, temperature=0.7, max_tokens=2000)

    def interpret_backtest(self, result: dict, strategy_name: str = "策略") -> LLMResponse:
        """解读回测结果。"""
        extra = ""
        if "sharpe_by_month" in result:
            extra = f"月度夏普分布: {result['sharpe_by_month']}"
        prompt = BACKTEST_INTERPRET_PROMPT.format(
            strategy_name=strategy_name,
            total_return=result.get("total_return", 0),
            annual_return=result.get("annual_return", 0),
            sharpe=result.get("sharpe", 0),
            max_drawdown=result.get("max_drawdown", 0),
            win_rate=result.get("win_rate", 0),
            turnover=result.get("turnover", 0),
            extra_metrics=extra,
        )
        return self._bridge.chat(prompt, temperature=0.5, max_tokens=1000)

    def analyze_factors(self, factor_report: dict) -> LLMResponse:
        """分析因子评估报告。"""
        prompt = FACTOR_ADVICE_PROMPT.format(
            factor_report=json.dumps(factor_report, ensure_ascii=False, indent=2)[:3000],
        )
        return self._bridge.chat(prompt, temperature=0.5, max_tokens=800)

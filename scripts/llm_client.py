"""LLM client - multi-provider (stdlib, no SDK dependency).

Supported providers:
  - glm: GLM OpenAI-compatible chat completions endpoint.
  - opencode: OpenCode.ai Zen free/paid models.

Design:
  - Uses urllib.request directly; no requests/openai SDK.
  - Reads API keys from .env or environment variables.
  - Returns {"success": False} on failures instead of raising to callers.
  - chat_json() extracts JSON from chat() text.

Usage:
  from scripts.llm_client import chat, chat_json, get_api_key
  r = chat("glm", "system", "hello", timeout=15)
  if r["success"]:
      print(r["text"])
"""
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from contextvars import ContextVar

from scripts.llm_registry import (
    default_model,
    load_registry,
    normalize_model,
    provider_definition,
)

logger = logging.getLogger("llm_client")

# ── 项目根目录 (.env 所在位置) ──────────────────────────────
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 供应商配置 ──────────────────────────────────────────────
PROVIDERS = {
    "glm": {
        "endpoint": None,
        "default_endpoint": "https://api.ifanr.work/v1/chat/completions",
        "model": None,
        "default_model": default_model("glm"),
        "key_env": "GLM_API_KEY",
        "base_url_env": "GLM_BASE_URL",
        "model_env": "GLM_MODEL",
        "label": provider_definition("glm")["client_label"],
    },
    "opencode": {
        "endpoint": "https://opencode.ai/zen/v1/chat/completions",
        "default_endpoint": "https://opencode.ai/zen/v1/chat/completions",
        "model": None,
        "default_model": default_model("opencode"),
        "key_env": "OPENCODE_API_KEY",
        "base_url_env": None,
        "model_env": "OPENCODE_MODEL",
        "label": provider_definition("opencode")["client_label"],
    },
}

# 默认供应商 (主力模型)
DEFAULT_PROVIDER = "glm"

_MODEL_REGISTRY = load_registry()
SUPPORTED_MODELS = {
    provider: {item["id"] for item in definition["models"]}
    for provider, definition in _MODEL_REGISTRY["providers"].items()
}
MODEL_MIGRATIONS = {
    provider: dict(definition.get("aliases") or {})
    for provider, definition in _MODEL_REGISTRY["providers"].items()
}
_MODEL_OVERRIDES = ContextVar("llm_model_overrides", default={})

# ── .env 加载 (模块级缓存, 首次调用时读取) ─────────────────
_env_loaded = False
_env_cache = {}


def _load_env():
    """从项目根 .env 读取 KEY=VALUE, 合并到 os.environ (不覆盖已有值)。"""
    global _env_loaded
    if _env_loaded:
        return
    env_path = os.path.join(_PROJECT_ROOT, ".env")
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
                    _env_cache[key] = val
    except FileNotFoundError:
        logger.debug(".env not found, relying on OS environment variables")
    except Exception as e:
        logger.debug(f".env parse error: {e}")
    _env_loaded = True


def get_api_key(provider: str) -> str:
    """获取指定供应商的 API Key, 无则返回空字符串。"""
    _load_env()
    cfg = PROVIDERS.get(provider)
    if not cfg:
        return ""
    return os.environ.get(cfg["key_env"], "")


def _resolve_endpoint(cfg: dict) -> str:
    """解析供应商 endpoint。GLM 支持从环境变量读取自建端点。"""
    base_url_env = cfg.get("base_url_env")
    if base_url_env:
        base = os.environ.get(base_url_env, "").strip().rstrip("/")
        if base:
            if base.endswith("/chat/completions"):
                return base
            if base.endswith("/v1"):
                return f"{base}/chat/completions"
            return f"{base}/v1/chat/completions"
    return cfg.get("endpoint") or cfg.get("default_endpoint", "")


def _resolve_model(cfg: dict, model_override: str = None, provider: str = "") -> str:
    """解析供应商 model。GLM 支持从环境变量读取模型名。"""
    if model_override:
        selected = model_override
    else:
        selected = ""
        model_env = cfg.get("model_env")
        if model_env:
            selected = os.environ.get(model_env, "")
        selected = selected or cfg.get("model") or cfg.get("default_model", "")
    return normalize_model(provider, selected)


@contextmanager
def model_override(provider: str, model: str = ""):
    """Apply one configured model to all nested LLM calls in this context."""
    normalized_provider = str(provider or "").strip().lower()
    current = dict(_MODEL_OVERRIDES.get() or {})
    if normalized_provider and model:
        current[normalized_provider] = str(model).strip()
    token = _MODEL_OVERRIDES.set(current)
    try:
        yield
    finally:
        _MODEL_OVERRIDES.reset(token)


def get_provider_label(provider: str) -> str:
    cfg = PROVIDERS.get(provider, {})
    return cfg.get("label", provider)


# ── 核心调用 ────────────────────────────────────────────────
# 重试配置: 网络/超时错误重试, 4xx 鉴权错误不重试
_MAX_RETRIES = 2
_RETRY_BACKOFF = [1, 3]  # 第1次重试等1s, 第2次等3s


def _is_retryable(err: Exception) -> bool:
    """判断错误是否值得重试 (网络/超时/5xx 服务端错误)。4xx 不重试。"""
    if isinstance(err, urllib.error.HTTPError):
        return err.code >= 500  # 5xx 服务端错误重试, 4xx 客户端错误不重试
    # URLError (连接拒绝/DNS失败/超时) 都可重试
    return isinstance(err, (urllib.error.URLError, TimeoutError, ConnectionError, OSError))


def _single_call(endpoint: str, api_key: str, payload: dict, timeout: int) -> dict:
    """单次 HTTP 调用, 返回解析后的 result dict。失败抛异常 (由上层重试逻辑捕获)。"""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "OpenCode/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body)


def chat(provider: str, system: str, user: str,
         temperature: float = 0.3, timeout: int = 25,
         max_tokens: int = 800, scene: str = "", max_retries: int = None, model: str = None) -> dict:
    """调用 LLM 聊天接口, 返回纯文本。

    Args:
        scene: 调用场景标签 (test/operator/data/factor/strategy/execution/risk/
               report/alert/paper 等), 用于 token 使用量统计按场景分类。
               留空则记为 "unknown", 不影响主流程。

    内置重试: 网络/超时/5xx 错误重试 2 次 (指数退避 1s→3s), 4xx 不重试。

    Returns:
        {"success": True, "text": "...", "usage": {...}} 或
        {"success": False, "error": "...", "text": ""}
    """
    cfg = PROVIDERS.get(provider)
    if not cfg:
        _record_usage_safe(provider, scene, None, False)
        return {"success": False, "error": f"未知供应商: {provider}", "text": ""}

    api_key = get_api_key(provider)
    if not api_key:
        _record_usage_safe(provider, scene, None, False)
        return {"success": False, "error": f"未配置 {cfg['key_env']}", "text": ""}

    endpoint = _resolve_endpoint(cfg)
    configured_model = model or (_MODEL_OVERRIDES.get() or {}).get(provider, "")
    if not configured_model:
        try:
            from scripts.llm_registry import resolve_llm_selection

            effective = resolve_llm_selection(scene=scene or "default")
            if effective.get("provider") == provider:
                configured_model = str(effective.get("model") or "")
        except Exception:
            configured_model = ""
    resolved_model = _resolve_model(cfg, model_override=configured_model, provider=provider)

    payload = {
        "model": resolved_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }

    last_err = None
    retries = _MAX_RETRIES if max_retries is None else max(0, int(max_retries))
    for attempt in range(retries + 1):  # 1次初始 + N次重试
        try:
            result = _single_call(endpoint, api_key, payload, timeout)
            msg = result.get("choices", [{}])[0].get("message", {})
            # GLM-5.2 等推理模型: 实际内容在 content, 推理过程在 reasoning_content
            # content 为空时回退到 reasoning_content
            text = msg.get("content") or msg.get("reasoning_content") or ""
            # 剥离推理模型可能内嵌的推理过程
            text = strip_reasoning(text)
            usage = result.get("choices", [{}])[0].get("usage") or result.get("usage") or {}
            _record_usage_safe(provider, scene, usage, True, resolved_model)
            return {
                "success": True,
                "text": text.strip(),
                "usage": usage,
                "provider": provider,
                "model": resolved_model,
                "requested_model": configured_model or resolved_model,
            }
        except Exception as e:
            last_err = e
            if attempt < retries and _is_retryable(e):
                wait = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
                logger.debug(f"chat({provider}) attempt {attempt+1} failed ({e}), retry in {wait}s")
                time.sleep(wait)
                continue
            # 不可重试的错误 或 重试次数用尽
            break

    err = str(last_err)[:200]
    logger.debug(f"chat({provider}) failed after {attempt+1} attempts: {err}")
    _record_usage_safe(provider, scene, None, False, resolved_model)
    return {
        "success": False,
        "error": err,
        "text": "",
        "provider": provider,
        "model": resolved_model,
        "requested_model": configured_model or resolved_model,
    }


def _record_usage_safe(provider: str, scene: str, usage, success: bool, model: str = "") -> None:
    """记录 token 使用量, 任何异常都吞掉 (统计不能影响主流程)。"""
    try:
        from scripts.llm_usage import record_usage
        record_usage(provider, scene, usage, success=success, model=model)
    except Exception as e:
        logger.debug(f"record_usage skipped: {e}")
    try:
        from quant.data.audit import write_model_call
        from quant.data.cache import create_cache
        write_model_call(create_cache(), {
            "provider": provider,
            "scene": scene or "unknown",
            "model": model,
            "success": bool(success),
            "usage": usage or {},
        })
    except Exception as e:
        logger.debug(f"model_call audit skipped: {e}")


# ── JSON 提取 ───────────────────────────────────────────────
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)

# 推理模型 (如 GLM-5.2) 的推理步骤标题, 用于识别并剥离推理过程
_REASONING_MARKERS = [
    "分析请求", "分析数据", "分析输入", "理解任务", "理解请求",
    "草拟", "起草", "草稿", "draft",
    "约束条件", "输出限制", "输出格式", "格式化输出",
    "角色设定", "角色：",
    "数据概览", "数据回顾", "回顾数据",
    "风险考量", "风险评估",
    "策略制定", "策略选择", "组合构建",
    "验证检查", "最终确认",
    "步骤", "思路", "思考过程",
    "markdown", "反引号",
]


def strip_reasoning(text: str) -> str:
    """从推理模型输出中提取最终答案, 剥离推理过程。

    GLM-5.2 等推理模型会将完整推理链放入 content。模型通常经历:
    分析请求 → 分析数据 → 草拟要点(多轮) → 最终要点。
    最终答案特征: 最后一个连续的编号段落, 常含 **加粗标题**。

    策略:
    1. 按顶层编号 (1. 2. 3.) 切分成段落
    2. 过滤掉推理标题段落 (含 分析/草拟/约束 等标记)
    3. 取最后一批连续的内容段落作为答案
    """
    if not text:
        return text
    has_reasoning = any(m in text for m in _REASONING_MARKERS)
    if not has_reasoning:
        return text.strip()

    lines = text.split("\n")

    # 把文本切成 "块": 每个顶层编号 (如 "3. xxx") 开始一个新块
    blocks = []  # [(header_line_idx, [lines])]
    current_block = []
    for line in lines:
        stripped = line.strip()
        # 顶层编号行: "1. " "2. " "10. " (非缩进)
        if re.match(r"^\d+[\.\)]\s+\S", stripped):
            if current_block:
                blocks.append(current_block)
            current_block = [line]
        else:
            if current_block:
                current_block.append(line)
    if current_block:
        blocks.append(current_block)

    if not blocks:
        return text.strip()

    # 把每个 block 的文本合并, 判断是否推理段落
    block_texts = []
    for blk in blocks:
        block_text = "\n".join(blk).strip()
        first_line = blk[0].strip()
        is_reasoning = any(m in first_line for m in _REASONING_MARKERS)
        block_texts.append({"text": block_text, "is_reasoning": is_reasoning, "header": first_line})

    # 从后往前找: 最后一个非推理块就是答案起点
    answer_start = None
    for i in range(len(block_texts) - 1, -1, -1):
        if not block_texts[i]["is_reasoning"]:
            answer_start = i
            break

    if answer_start is None:
        # 全是推理? 取最后 2-3 个块
        answer_start = max(0, len(block_texts) - 3)

    # 从 answer_start 到末尾, 但可能混入推理块, 只取连续的内容块
    answer_blocks = [block_texts[answer_start]["text"]]
    for i in range(answer_start + 1, len(block_texts)):
        if block_texts[i]["is_reasoning"]:
            break
        answer_blocks.append(block_texts[i]["text"])

    result = "\n".join(answer_blocks).strip()
    return result if result else text.strip()


def _extract_json(text: str):
    """从 LLM 响应文本中提取 JSON 对象, 支持代码块和裸 JSON。

    针对 GLM-5.2 等推理模型的鲁棒处理:
    - 推理过程可能包含 ```json 代码块示例, 需要取最后一个 (真正的输出)
    - JSON 可能被 max_tokens 截断, 尝试修复不完整的尾部
    """
    if not text:
        return None
    # 1. 尝试所有 ```json ... ``` 代码块, 取最后一个完整的
    fences = _JSON_FENCE_RE.findall(text)
    for fence in reversed(fences):
        candidate = fence.strip()
        parsed = _try_parse_json_lenient(candidate)
        if parsed is not None:
            return parsed
    # 2. 提取所有括号平衡的裸 JSON 对象。不能使用 rfind("{")，否则
    #    嵌套对象会被误截成最内层对象，顶层业务字段随之丢失。
    candidates = []
    depth = 0
    start = None
    in_string = False
    escape = False
    for index, char in enumerate(text):
        if escape:
            escape = False
            continue
        if char == "\\" and in_string:
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                candidates.append(text[start:index + 1])
                start = None
    for candidate in reversed(candidates):
        parsed = _try_parse_json_lenient(candidate.strip())
        if parsed is not None:
            return parsed
    # 3. 有未闭合的最外层对象时，尝试修复截断输出。
    if depth > 0 and start is not None:
        candidate = _repair_truncated_json(text[start:])
        if candidate:
            parsed = _try_parse_json_lenient(candidate)
            if parsed is not None:
                return parsed
    # 4. 整体尝试
    return _try_parse_json_lenient(text.strip())


def _try_parse_json_lenient(text: str):
    """宽松 JSON 解析: 支持尾逗号、单引号、注释。"""
    if not text:
        return None
    # 直接解析
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    # 移除尾逗号 (JSON 不允许, 但 LLM 常加)
    cleaned = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        pass
    # 移除单行注释 (// ...)
    cleaned = re.sub(r"//[^\n]*", "", text)
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return None


def _repair_truncated_json(text: str) -> str:
    """尝试修复被 max_tokens 截断的 JSON。

    策略: 从末尾往前找到最后一个完整的 }, 补齐缺少的 ] 和 }
    """
    if not text or "{" not in text:
        return ""
    # 找到最后一个完整的值/键位置
    # 简单策略: 统计未闭合的 { 和 [, 补齐
    open_braces = 0
    open_brackets = 0
    in_string = False
    escape = False
    last_complete_pos = 0
    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            open_braces += 1
        elif ch == "}":
            open_braces -= 1
            if open_braces >= 0 and open_brackets == 0:
                last_complete_pos = i
        elif ch == "[":
            open_brackets += 1
        elif ch == "]":
            open_brackets -= 1
    # 截到最后一个可能的完整位置, 然后补齐
    # 先尝试去掉最后一个不完整的键值对 (如果有逗号或冒号没值)
    cut = text
    # 去掉末尾的不完整片段: 找最后一个逗号/引号位置
    for marker in ['",', '", ', "',", "}", "]", "{\"", "\""]:
        pos = cut.rfind(marker)
        if pos > len(cut) * 0.5:  # 只在后半段找
            candidate = cut[:pos + len(marker)]
            # 补齐
            candidate += "]" * max(0, open_brackets) + "}" * max(0, open_braces)
            return candidate
    # fallback: 直接补齐
    return text.rstrip().rstrip(",") + "]" * max(0, open_brackets) + "}" * max(0, open_braces)


def chat_json(provider: str, system: str, user: str, **kwargs) -> dict:
    """调用 LLM 并提取 JSON 响应。

    Returns:
        {"success": True, "data": {...}, "usage": {...}} 或
        {"success": False, "error": "...", "data": {}}
    """
    # 在 system prompt 中追加 JSON 格式要求
    json_instruction = "\n\n[输出要求] 你必须只返回一个合法 JSON 对象, 不要包含任何额外文字或解释。"
    full_system = system + json_instruction

    r = chat(provider, full_system, user, **kwargs)
    if not r["success"]:
        return {
            "success": False,
            "error": r.get("error", ""),
            "data": {},
            "provider": r.get("provider"),
            "model": r.get("model"),
            "requested_model": r.get("requested_model"),
        }

    data = _extract_json(r["text"])
    if data is None:
        return {"success": False, "error": "LLM 响应无法解析为 JSON", "data": {},
                "raw": r["text"][:300]}
    return {
        "success": True,
        "data": data,
        "usage": r.get("usage", {}),
        "provider": r.get("provider"),
        "model": r.get("model"),
        "requested_model": r.get("requested_model"),
    }


# ── CLI 测试入口 ────────────────────────────────────────────
def main():
    """命令行测试: python scripts/llm_client.py --provider glm"""
    import argparse
    parser = argparse.ArgumentParser(description="LLM 客户端测试")
    parser.add_argument("--provider", default=DEFAULT_PROVIDER, choices=list(PROVIDERS.keys()))
    parser.add_argument("--json", action="store_true", help="测试 JSON 模式")
    args = parser.parse_args()

    key = get_api_key(args.provider)
    print(f"供应商: {args.provider} ({get_provider_label(args.provider)})")
    print(f"API Key: {'已配置 (' + key[:8] + '...)' if key else '未配置'}")
    cfg = PROVIDERS.get(args.provider, {})
    print(f"Endpoint: {_resolve_endpoint(cfg)}")
    print(f"Model: {_resolve_model(cfg)}")

    if args.json:
        r = chat_json(args.provider, "你是交易助手",
                      "请返回: {\"status\": \"ok\", \"stocks\": 3}")
    else:
        r = chat(args.provider, "你是简洁的助手", "用一句话介绍A股T+1规则")

    if r["success"]:
        print(f"成功: {r.get('text', '') or r.get('data', '')}")
    else:
        print(f"失败: {r.get('error')}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()

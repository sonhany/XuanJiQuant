"""LLM Token 使用量统计 — 记录、聚合、查询

设计:
  - 每次调用 LLM 成功后, 把 usage (prompt/completion/total_tokens) 写入 SQLite
  - 同时记录 provider (glm/deepseek/qwen/gemini) 和 scene (调用场景)
  - 统计维度: 实时单次 / 按天累计 / 按 provider / 按 scene
  - 零依赖, 复用 quant.data.cache 的 SQLite 单例

存储键约定 (cache):
  llm:usage:log              -> list  最近 N 条调用记录 (实时单次用量, 环形缓冲)
  llm:usage:daily:<YYYYMMDD> -> dict  按天聚合 {providers:{}, scenes:{}, totals:{}}
  llm:usage:total            -> dict  全局累计 {providers:{}, scenes:{}, totals:{}}

每条记录结构:
  {
    "ts": "2026-07-03T11:30:00",     # ISO 时间戳
    "date": "2026-07-03",             # 日期 (便于按天筛选)
    "provider": "glm",                # 供应商
    "scene": "operator",              # 调用场景
    "model": "glm-5.2",               # 模型名 (可能为空)
    "prompt_tokens": 120,             # 输入 token
    "completion_tokens": 80,          # 输出 token
    "total_tokens": 200,              # 总 token
    "success": True                   # 是否成功
  }
"""
import logging
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger("llm_usage")

# 实时日志环形缓冲最大条数 (避免无限增长)
_LOG_MAX = 200


def _cache():
    """延迟导入 cache 单例, 避免 llm_client <-> cache 循环依赖。"""
    from quant.data.cache import create_cache
    return create_cache()


def _safe_int(v: Any, default: int = 0) -> int:
    """安全转 int, 容错 None / 字符串 / 异常值。"""
    try:
        n = int(v)
        return n if n > 0 else default
    except (TypeError, ValueError):
        return default


def record_usage(
    provider: str,
    scene: str,
    usage: Optional[dict],
    success: bool = True,
    model: str = "",
) -> None:
    """记录一次 LLM 调用的 token 使用量。

    Args:
        provider: 供应商 (glm/deepseek/qwen/gemini)
        scene:    调用场景 (test/operator/data/factor/strategy/execution/risk/report/alert/paper)
        usage:    供应商返回的 usage dict (含 prompt_tokens/completion_tokens/total_tokens)
                  为空或缺失时记 0, 不阻塞调用方
        success:  本次调用是否成功
        model:    模型名 (可选)

    任何异常都被吞掉 (统计不能影响主流程), 仅记日志。
    """
    try:
        now = datetime.now()
        usage = usage or {}
        rec = {
            "ts": now.isoformat(timespec="seconds"),
            "date": now.strftime("%Y-%m-%d"),
            "provider": provider or "unknown",
            "scene": scene or "unknown",
            "model": model or "",
            "prompt_tokens": _safe_int(usage.get("prompt_tokens")),
            "completion_tokens": _safe_int(usage.get("completion_tokens")),
            "total_tokens": _safe_int(usage.get("total_tokens")),
            "success": bool(success),
        }

        c = _cache()

        # 1. 追加到实时日志 (环形缓冲)
        log_list = c.get("llm:usage:log") or []
        log_list.append(rec)
        if len(log_list) > _LOG_MAX:
            log_list = log_list[-_LOG_MAX:]
        c.set("llm:usage:log", log_list)

        # 2. 按天聚合
        day_key = f"llm:usage:daily:{now.strftime('%Y-%m-%d')}"
        _bump_aggregate(c, day_key, rec)

        # 3. 全局累计
        _bump_aggregate(c, "llm:usage:total", rec)
    except Exception as e:
        logger.debug(f"record_usage failed (non-fatal): {e}")


def _bump_aggregate(c, key: str, rec: dict) -> None:
    """把一条记录累加进聚合 dict (按天或全局)。"""
    agg = c.get(key) or {
        "providers": {},
        "scenes": {},
        "totals": {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "success": 0, "fail": 0},
    }
    p = rec["provider"]
    s = rec["scene"]

    prov = agg["providers"].setdefault(p, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    prov["calls"] += 1
    prov["prompt_tokens"] += rec["prompt_tokens"]
    prov["completion_tokens"] += rec["completion_tokens"]
    prov["total_tokens"] += rec["total_tokens"]

    sc = agg["scenes"].setdefault(s, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    sc["calls"] += 1
    sc["prompt_tokens"] += rec["prompt_tokens"]
    sc["completion_tokens"] += rec["completion_tokens"]
    sc["total_tokens"] += rec["total_tokens"]

    agg["totals"]["calls"] += 1
    agg["totals"]["prompt_tokens"] += rec["prompt_tokens"]
    agg["totals"]["completion_tokens"] += rec["completion_tokens"]
    agg["totals"]["total_tokens"] += rec["total_tokens"]
    if rec["success"]:
        agg["totals"]["success"] += 1
    else:
        agg["totals"]["fail"] += 1

    c.set(key, agg)


def get_usage_stats(days: int = 7) -> dict:
    """查询 token 使用量统计。

    Returns:
        {
          "total":   {...},                 # 全局累计聚合
          "today":   {...},                 # 今日聚合
          "daily":   {"2026-07-03": {...}}, # 最近 N 天每天的聚合
          "recent":  [...],                 # 最近若干条实时记录
          "last":    {...} | None,          # 最近一次调用
        }
    """
    try:
        c = _cache()
        today = datetime.now().strftime("%Y-%m-%d")

        # 最近 N 天
        daily = {}
        for i in range(days):
            d = datetime.now().strftime("%Y-%m-%d") if i == 0 else None
            if d is None:
                # 往前推 i 天
                from datetime import timedelta
                d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            v = c.get(f"llm:usage:daily:{d}")
            if v:
                daily[d] = v

        recent = c.get("llm:usage:log") or []
        last = recent[-1] if recent else None

        return {
            "total": c.get("llm:usage:total") or _empty_aggregate(),
            "today": c.get(f"llm:usage:daily:{today}") or _empty_aggregate(),
            "daily": daily,
            "recent": recent[-20:],  # 最近 20 条给前端展示
            "last": last,
        }
    except Exception as e:
        logger.warning(f"get_usage_stats failed: {e}")
        return {"total": _empty_aggregate(), "today": _empty_aggregate(),
                "daily": {}, "recent": [], "last": None}


def _empty_aggregate() -> dict:
    return {
        "providers": {},
        "scenes": {},
        "totals": {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
                   "total_tokens": 0, "success": 0, "fail": 0},
    }


def reset_usage() -> bool:
    """清空所有 token 统计 (调试用)。"""
    try:
        c = _cache()
        c.delete("llm:usage:log")
        c.delete("llm:usage:total")
        # 清掉所有按天的键
        for k in c.keys("llm:usage:daily:*"):
            c.delete(k)
        return True
    except Exception as e:
        logger.warning(f"reset_usage failed: {e}")
        return False

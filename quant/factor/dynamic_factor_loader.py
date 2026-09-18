"""加载经研究门禁批准的动态因子。

这里只解释已持久化的受限 DSL；不生成因子、不调用大模型，也不自动晋升。
"""

from __future__ import annotations

import logging

from quant.adaptive.health import model_health_key, normalize_model_id, runtime_eligible, validate_health_record
from quant.factor.dsl import compute_factor

logger = logging.getLogger("dynamic_factor_loader")


def _cache():
    from quant.data.cache import create_cache
    return create_cache()


def _active_cache(cache_obj=None):
    return cache_obj or _cache()


def is_dynamic_factor_enabled(cache_obj=None) -> bool:
    try:
        config = _active_cache(cache_obj).get("factor:runtime:config") or {}
        return bool(config.get("use_dynamic_factors", False))
    except Exception:
        return False


def get_approved_factors(cache_obj=None) -> list[dict]:
    """读取普通研究域中已人工批准且健康的动态因子。"""
    try:
        cache = _active_cache(cache_obj)
        approved = []
        for row in cache.get("research:factor:approved") or []:
            if not isinstance(row, dict):
                continue
            state = row.get("promotion_state") or (row.get("promotion") or {}).get("state")
            if state != "approved":
                continue
            try:
                name = normalize_model_id(row.get("name"))
                value = cache.get(model_health_key(name))
                health = validate_health_record(value, allow_missing=value is None)
            except ValueError:
                continue
            if health["health_state"] == "quarantined" or not runtime_eligible(
                "approved",
                health["health_state"],
                artifact_valid=health["artifact_valid"],
                data_fresh=health["data_fresh"],
            ):
                continue
            approved.append(row)
        return approved
    except Exception:
        return []


def compute_dynamic_factor(df, factor_name: str, cache_obj=None):
    for factor in get_approved_factors(cache_obj):
        if factor.get("name") == factor_name and factor.get("dsl"):
            return compute_factor(df, factor["dsl"])
    return None


def compute_dynamic_factors(df, cache_obj=None):
    if df is None or len(df) == 0:
        return df
    for factor in get_approved_factors(cache_obj)[:10]:
        name, dsl = factor.get("name"), factor.get("dsl")
        if not name or not dsl or name in df.columns:
            continue
        try:
            series = compute_factor(df, dsl)
            if series is not None and len(series) == len(df):
                df[name] = series
        except Exception as error:
            logger.debug("动态因子 %s 计算失败，已跳过: %s", name, error)
    return df


def get_dynamic_factor_summary() -> dict:
    approved = get_approved_factors()
    return {
        "enabled": is_dynamic_factor_enabled(),
        "approved_count": len(approved),
        "factor_names": [row.get("name", "") for row in approved[:10]],
    }

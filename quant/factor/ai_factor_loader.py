"""AI 因子加载器 — 把 ai:factor:approved 里批准的 AI 因子接入生产 FactorEngine

设计:
  - load_approved_factors() 从 cache 读已批准因子的 DSL 列表
  - compute_ai_factors(df) 对单只股票的 K 线 DataFrame 计算所有 AI 因子值
  - 默认不启用: 仅当 paper:config.use_ai_factors=True 时才接入策略
  - 复用 ai_factor_agent.compute_factor (安全 DSL 解释器), 不重复造轮子

接入点:
  策略层在 multi_factor 打分时, 可选调用 compute_ai_factors(df) 把 AI 因子
  并入因子打分。具体接入逻辑在 quant.strategy 的 multi_factor 策略里。

用法:
  from quant.factor.ai_factor_loader import is_ai_factor_enabled, compute_ai_factors
  if is_ai_factor_enabled():
      df = compute_ai_factors(df)  # 追加 AI 因子列
"""
import logging

logger = logging.getLogger("ai_factor_loader")


def _cache():
    from quant.data.cache import create_cache
    return create_cache()


def is_ai_factor_enabled() -> bool:
    """是否启用 AI 因子 (默认关闭, 需 paper:config.use_ai_factors=True)。"""
    try:
        cfg = _cache().get("paper:config") or {}
        return bool(cfg.get("use_ai_factors", False))
    except Exception:
        return False


def get_approved_factors() -> list:
    """获取已批准的 AI 因子列表 (含 DSL)。返回 [{name, desc, direction, dsl}, ...]。"""
    try:
        return _cache().get("ai:factor:approved") or []
    except Exception:
        return []


def compute_ai_factors(df) -> "pd.DataFrame":
    """对单只股票的 K 线 DataFrame 计算 AI 因子, 追加因子列。

    Args:
        df: 含 date/open/high/low/close/volume/amount 列的 DataFrame
    Returns:
        原 df 追加 AI 因子列 (列名 = 因子名)。失败因子跳过不阻塞。
    """
    if df is None or len(df) == 0:
        return df
    approved = get_approved_factors()
    if not approved:
        return df

    from scripts.ai_factor_agent import compute_factor

    for f in approved[:10]:  # 最多接入 10 个, 避免拖慢
        name = f.get("name")
        dsl = f.get("dsl")
        if not name or not dsl:
            continue
        try:
            series = compute_factor(df, dsl)
            if series is not None and len(series) == len(df):
                df[name] = series
        except Exception as e:
            logger.debug(f"AI 因子 {name} 计算失败 (跳过): {e}")
            continue
    return df


def get_ai_factor_summary() -> dict:
    """返回 AI 因子接入状态摘要 (供驾驶舱显示)。"""
    approved = get_approved_factors()
    return {
        "enabled": is_ai_factor_enabled(),
        "approved_count": len(approved),
        "factor_names": [f.get("name", "") for f in approved[:10]],
    }

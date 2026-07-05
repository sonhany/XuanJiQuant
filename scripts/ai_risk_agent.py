"""Layer 5: AI 风控监控 — 事前风控 + 自我验证 + 经验沉淀

职责:
  - 判断今日是否允许交易 (数据stale/严重告警 → 禁止)
  - 每日生成五层自我验证报告
  - AI 建议命中率统计
  - 经验写入 ai:memory:lessons

安全边界: 硬规则不可被 AI 覆盖
持久化: ai:risk:latest, ai:selfverify:<date>, ai:memory:lessons
"""
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache

cache = create_cache()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _live_data_stale() -> bool:
    """实时计算数据是否过期 — 统一入口。"""
    try:
        from scripts.data_freshness import is_data_stale
        return is_data_stale()
    except Exception:
        return True  # 无法判断时保守处理


def check_pre_trade() -> dict:
    """事前风控: 判断是否允许交易。硬规则, 不可被AI覆盖。

    只看硬规则 (数据新鲜度 + 严重告警), 不回看 operator 的 LLM 策略判断。
    原因: ai_loop Step7 里 operator 策略会与风控结果合并 (最保守胜出),
    若风控本身又依赖 operator 判断, 会形成循环依赖 → 一旦 operator 输出
    no_new_position 就永远锁死。operator 策略合并应只在 ai_loop Step7 做。
    """
    # 数据新鲜度 — 实时计算, 不用缓存
    data_stale = _live_data_stale()

    # 告警
    alerts = cache.get("alerts:records") or []
    active = [a for a in alerts if a.get("status") == "active"]
    critical = [a for a in active if a.get("level") == "critical"]

    # 硬规则 (仅数据 + 告警, 不依赖 operator)
    trade_allowed = True
    block_reasons = []
    objective = cache.get("ai:objective:latest") or {}
    objective_pressure = objective.get("objective_pressure")
    risk_mode = objective.get("risk_mode")
    if data_stale:
        trade_allowed = False
        block_reasons.append("数据过期: K线不是最新交易日")
    if len(critical) > 0:
        trade_allowed = False
        block_reasons.append(f"存在{len(critical)}条严重告警")
    if risk_mode == "no_new_position":
        trade_allowed = False
        block_reasons.append("目标周期已结束或目标风控要求禁止新开仓")

    # operator 策略仅作信息展示, 不参与硬门阻断 (避免循环依赖)
    operator = cache.get("ai:operator:latest") or {}
    operator_policy = operator.get("trade_policy") or (operator.get("plan") or {}).get("trade_policy")

    return {
        "trade_allowed": trade_allowed,
        "trade_policy": "normal" if trade_allowed else "no_new_position",
        "block_reasons": block_reasons,
        "data_stale": data_stale,
        "critical_alerts": len(critical),
        "active_alerts": len(active),
        "operator_policy": operator_policy,  # 仅供参考, 不阻断
        "objective_pressure": objective_pressure,
        "objective_risk_mode": risk_mode,
        "objective_progress_pct": objective.get("progress_pct"),
        "checked_at": _now(),
    }


def self_verification() -> dict:
    """每日五层自我验证报告。"""
    day = _today()
    report = {
        "date": day,
        "verified_at": _now(),
        "layers": {},
    }

    # Layer 1 数据
    data_agent = cache.get("ai:data:latest") or {}
    integrity = data_agent.get("integrity", {}).get("summary", {}) if data_agent else {}
    report["layers"]["data"] = {
        "status": "pass" if not data_agent.get("data_stale", True) else "fail",
        "detail": f"ok={integrity.get('ok',0)} stale={integrity.get('stale',0)} missing={integrity.get('missing',0)}",
    }

    # Layer 2 因子
    approved_factors = cache.get("ai:factor:approved") or []
    candidates = cache.get("ai:factor:candidates") or []
    report["layers"]["factor"] = {
        "status": "pass" if len(approved_factors) > 0 or len(candidates) > 0 else "pending",
        "detail": f"approved={len(approved_factors)} candidates={len(candidates)}",
    }

    # Layer 3 策略
    approved_strategies = cache.get("ai:strategy:approved") or []
    strategy_candidates = cache.get("ai:strategy:candidates") or []
    report["layers"]["strategy"] = {
        "status": "pass" if len(strategy_candidates) > 0 else "pending",
        "detail": f"approved={len(approved_strategies)} candidates={len(strategy_candidates)}",
    }

    # Layer 4 执行
    exec_latest = cache.get("ai:execution:latest") or {}
    report["layers"]["execution"] = {
        "status": "pass" if exec_latest else "pending",
        "detail": f"orders={exec_latest.get('today_order_count',0)} rejections={exec_latest.get('risk_rejection_count',0)}",
    }

    # Layer 5 风控
    pre_trade = check_pre_trade()
    report["layers"]["risk"] = {
        "status": "pass" if pre_trade["trade_allowed"] else "blocked",
        "detail": f"policy={pre_trade['trade_policy']} critical={pre_trade['critical_alerts']}",
    }

    # 整体
    failed_layers = [l for l, v in report["layers"].items() if v["status"] == "fail"]
    report["overall"] = "fail" if failed_layers else ("blocked" if any(v["status"] == "blocked" for v in report["layers"].values()) else "pass")

    cache.set(f"ai:selfverify:{day}", report)
    cache.set("ai:selfverify:latest", report)
    return report


def accumulate_lessons(provider: str = "glm") -> dict:
    """从当日运行结果中提取经验, 写入经验库。"""
    day = _today()
    lessons = cache.get("ai:memory:lessons") or []
    
    # 从自我验证提取
    selfverify = cache.get("ai:selfverify:latest") or {}
    if selfverify.get("overall") != "pass":
        failed = [l for l, v in selfverify.get("layers", {}).items() if v["status"] in ("fail", "blocked")]
        if failed:
            lessons.append({
                "date": day,
                "type": "self_verify_failure",
                "content": f"自我验证未通过: {','.join(failed)}层异常",
            })

    # 从执行复盘提取
    exec_review = cache.get(f"ai:execution:review:{day}") or {}
    if exec_review.get("latest", {}).get("ai_advice"):
        lessons.append({
            "date": day,
            "type": "execution_lesson",
            "content": exec_review["latest"]["ai_advice"][:200],
        })

    # 去重 (同日同类型)
    seen = set()
    deduped = []
    for l in reversed(lessons):
        key = f"{l.get('date')}_{l.get('type')}"
        if key not in seen:
            seen.add(key)
            deduped.append(l)
    deduped.reverse()
    deduped = deduped[-50:]

    cache.set("ai:memory:lessons", deduped)
    return {"success": True, "total_lessons": len(deduped), "lessons": deduped[-5:]}


def run_risk_monitor(provider: str = "glm") -> dict:
    """运行 AI 风控监控全流程。"""
    pre_trade = check_pre_trade()
    selfverify = self_verification()
    lessons = accumulate_lessons(provider)
    
    result = {
        "success": True,
        "generated_at": _now(),
        "pre_trade": pre_trade,
        "self_verification": selfverify,
        "recent_lessons": lessons.get("lessons", []),
        "total_lessons": lessons.get("total_lessons", 0),
    }
    cache.set("ai:risk:latest", result)
    return result


def get_status() -> dict:
    return cache.get("ai:risk:latest") or {
        "success": True,
        "pre_trade": check_pre_trade(),
        "self_verification": cache.get("ai:selfverify:latest"),
        "lessons": (cache.get("ai:memory:lessons") or [])[-5:],
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AI 风控监控")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--provider", default="glm")
    args = parser.parse_args()
    if args.run:
        out = run_risk_monitor(args.provider)
    else:
        out = get_status()
    print(json.dumps({"success": True, "data": out}, ensure_ascii=False, default=str))

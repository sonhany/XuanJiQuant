"""Layer 4: AI 执行增强 — 执行建议生成 + 风控审核 + 模拟盘执行后复盘

职责:
  - 根据策略信号 + 持仓 + 风控约束生成执行建议 (不直接下单)
  - 调用 GLM 解释为什么成交/拒单
  - 生成执行复盘报告

安全边界: 只生成建议 JSON, 下单仍由 paper_trader + execution_runner + 风控网关负责
持久化: ai:execution:latest, ai:execution:review:<date>
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


def generate_execution_advice(provider: str = "glm") -> dict:
    """生成执行建议 (不下单, 只建议)。"""
    cfg = cache.get("paper:config") or {}
    exec_state = cache.get("execution:state") or {}
    paper_status = cache.get("paper:status") or {}
    last_result = paper_status.get("last_result") or {}

    positions = exec_state.get("positions", {}) or {}
    pos_list = []
    for code, p in positions.items():
        qty = int(p.get("quantity", 0) or 0)
        if qty > 0:
            pos_list.append({
                "code": code,
                "qty": qty,
                "available": int(p.get("available_qty", 0) or 0),
                "avg_price": float(p.get("avg_price", 0) or 0),
            })

    signals = last_result.get("signals", [])
    risk_rejections = last_result.get("risk_rejections", [])
    orders = last_result.get("orders", [])

    # GLM 生成执行建议 (结构化: summary + proposed_orders)
    ai_advice = ""
    proposed_orders = []
    try:
        from scripts.llm_client import chat, _extract_json
        compact = {
            "positions": pos_list[:10],
            "today_signals": signals[:10],
            "risk_rejections": risk_rejections[:5],
            "today_orders": [{"code": o.get("code"), "dir": o.get("direction"),
                              "qty": o.get("qty"), "success": o.get("success")}
                             for o in orders[:10]],
            "risk_config": cfg.get("risk", {}),
        }
        system = (
            "你是A股模拟盘执行AI助手。分析今日信号和持仓状态, 输出结构化建议。"
            "只返回JSON: {\"summary\":\"2-3句总结\",\"proposed_orders\":[{\"code\":\"股票代码\",\"action\":\"buy或sell或hold\",\"target_weight\":0.2,\"priority\":\"high或medium或low\",\"reason\":\"一句话理由\"}],\"risk_notes\":\"风控提示\"}。"
            "action只能是buy/sell/hold。target_weight是0~1的小数。不要编造不存在的股票代码。"
        )
        user = json.dumps(compact, ensure_ascii=False, default=str)
        r = chat(provider, system, user, temperature=0.2, timeout=45, max_tokens=500, scene="execution")
        if r.get("success"):
            ai_advice = r["text"][:600]
            # 尝试解析结构化建议
            parsed = _extract_json(r["text"])
            if isinstance(parsed, dict):
                if parsed.get("summary"):
                    ai_advice = str(parsed["summary"])[:600]
                po = parsed.get("proposed_orders")
                if isinstance(po, list):
                    proposed_orders = [{
                        "code": str(o.get("code", "")),
                        "action": o.get("action", "hold"),
                        "target_weight": float(o.get("target_weight", 0) or 0),
                        "priority": o.get("priority", "low"),
                        "reason": str(o.get("reason", ""))[:120],
                    } for o in po[:10] if isinstance(o, dict) and o.get("code")]
    except Exception:
        pass

    result = {
        "success": True,
        "generated_at": _now(),
        "provider": provider,
        "positions": pos_list,
        "today_signal_count": len(signals),
        "today_order_count": len(orders),
        "order_success_count": len([o for o in orders if o.get("success")]),
        "risk_rejection_count": len(risk_rejections),
        "ai_advice": ai_advice,
        "proposed_orders": proposed_orders,
    }
    cache.set("ai:execution:latest", result)
    return result


def execution_review(provider: str = "glm") -> dict:
    """执行复盘: GLM 分析成交/拒单模式, 总结经验。"""
    latest = cache.get("ai:execution:latest") or {}
    day = _today()
    review = {"date": day, "reviewed_at": _now(), "latest": latest}

    # 写入经验库
    lessons = cache.get("ai:memory:lessons") or []
    if latest.get("ai_advice"):
        lessons.append({
            "date": day,
            "type": "execution_review",
            "content": latest["ai_advice"][:200],
            "order_count": latest.get("today_order_count", 0),
            "rejection_count": latest.get("risk_rejection_count", 0),
        })
        lessons = lessons[-50:]  # 保留最近 50 条经验
        cache.set("ai:memory:lessons", lessons)

    cache.set(f"ai:execution:review:{day}", review)
    return {"success": True, "review": review, "total_lessons": len(lessons)}


def get_status() -> dict:
    return cache.get("ai:execution:latest") or {"success": True, "latest": None}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AI 执行增强")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--review", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--provider", default="glm")
    args = parser.parse_args()
    if args.review:
        out = execution_review(args.provider)
    elif args.run:
        out = generate_execution_advice(args.provider)
    else:
        out = get_status()
    print(json.dumps({"success": True, "data": out}, ensure_ascii=False, default=str))

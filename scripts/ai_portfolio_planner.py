"""AI 目标组合规划器 — ultra thinking 多角色委员会。

LLM 只输出结构化组合计划；本模块负责裁剪到硬风控范围，不直接下单。
"""
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache

cache = create_cache()

PORTFOLIO_KEY = "ai:portfolio:latest"
COMMITTEE_KEY = "ai:committee:latest"
VALID_POLICIES = {"normal", "reduce_only", "no_new_position"}
VALID_ACTIONS = {"buy", "sell", "hold"}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _collect_context(candidate_pool: list, objective: dict, loop_results: dict = None) -> dict:
    exec_state = cache.get("execution:state") or {}
    positions = exec_state.get("positions", {}) or {}
    holdings = []
    for code, p in positions.items():
        qty = int(p.get("quantity", 0) or 0)
        if qty <= 0:
            continue
        holdings.append({
            "code": str(code).split(".")[0],
            "quantity": qty,
            "avg_price": _safe_float(p.get("avg_price")),
            "current_price": _safe_float(p.get("current_price", p.get("avg_price"))),
            "market_value": _safe_float(p.get("market_value")),
        })
    screen = cache.get("ai:screen:latest") or {}
    risk = cache.get("ai:risk:latest") or {}
    global_ctx = cache.get("global:context:latest") or {}
    operator = cache.get("ai:operator:latest") or {}
    return {
        "date": _today(),
        "objective": objective,
        "candidate_pool": [str(c).split(".")[0] for c in (candidate_pool or [])][:50],
        "screen_top": (screen.get("top") or [])[:20] if isinstance(screen, dict) else [],
        "holdings": holdings,
        "account": {
            "cash": _safe_float(exec_state.get("cash")),
            "initial_capital": _safe_float(exec_state.get("initial_capital"), 1_000_000.0),
            "total_equity": objective.get("current_equity"),
        },
        "risk": (risk.get("pre_trade") or {}) if isinstance(risk, dict) else {},
        "global": {
            "risk_level": global_ctx.get("risk_level"),
            "trade_policy": global_ctx.get("trade_policy"),
            "risk_signals": global_ctx.get("risk_signals", []),
        },
        "operator": {
            "trade_policy": operator.get("trade_policy"),
            "paper_trade_allowed": operator.get("paper_trade_allowed"),
            "summary": operator.get("summary"),
        },
        "loop_final": (loop_results or {}).get("final", {}),
    }


def _role_prompt(role: str, context: dict) -> tuple[str, str]:
    base = json.dumps(context, ensure_ascii=False, default=str, indent=2)[:12000]
    system = (
        "你是A股量化模拟盘的AI委员会成员。只输出合法JSON对象，不输出Markdown，不输出推理过程。"
        "目标是辅助模拟盘组合规划，但不得建议绕过硬风控、不得建议实盘交易。"
    )
    if role == "opportunity":
        user = base + "\n\n请作为机会分析师输出JSON: {\"summary\":\"...\",\"opportunities\":[{\"code\":\"股票代码\",\"score\":0.8,\"reason\":\"一句话\"}],\"risk_notes\":[\"...\"]}。只允许使用candidate_pool或当前持仓中的股票。"
    elif role == "risk":
        user = base + "\n\n请作为风险审查员输出JSON: {\"summary\":\"...\",\"risk_level\":\"low|medium|high\",\"trade_policy\":\"normal|reduce_only|no_new_position\",\"blocked_codes\":[\"...\"],\"risk_notes\":[\"...\"]}。目标很激进但不能覆盖风控。"
    elif role == "execution":
        user = base + "\n\n请作为执行审查员输出JSON: {\"summary\":\"...\",\"max_orders\":20,\"cash_target_pct\":5,\"execution_notes\":[\"...\"],\"constraints\":[\"T+1/涨跌停/现金/整手/费用\"]}。"
    else:
        user = base + "\n\n请作为最终组合经理输出JSON: {\"summary\":\"...\",\"trade_policy\":\"normal|reduce_only|no_new_position\",\"cash_target_pct\":5,\"target_weights\":[{\"code\":\"股票代码\",\"target_weight\":0.1,\"confidence\":0.7,\"reason\":\"一句话\"}],\"rebalance_plan\":[{\"code\":\"股票代码\",\"action\":\"buy|sell|hold\",\"target_weight\":0.1,\"priority\":\"high|medium|low\",\"reason\":\"一句话\"}],\"risk_budget\":{\"max_position_pct\":0.2,\"max_gross_exposure_pct\":95,\"max_orders\":20},\"objective_note\":\"...\",\"risk_notes\":[\"...\"]}。目标权重总和不能超过95%，单股不超过20%。"
    return system, user


def _call_role(provider: str, role: str, context: dict) -> dict:
    try:
        from scripts.llm_client import chat_json
        system, user = _role_prompt(role, context)
        r = chat_json(provider, system, user, temperature=0.15, timeout=75, max_tokens=3000, scene=f"portfolio_{role}")
        if not r.get("success"):
            return {"success": False, "role": role, "error": r.get("error", "LLM失败")}
        data = r.get("data") or {}
        if not isinstance(data, dict):
            return {"success": False, "role": role, "error": "LLM未返回对象"}
        return {"success": True, "role": role, "data": data}
    except Exception as e:
        return {"success": False, "role": role, "error": str(e)[:300]}


def _fallback_plan(context: dict, reason: str = "") -> dict:
    cfg = (context.get("objective") or {}).get("config", {}) or {}
    risk_cfg = cfg.get("risk", {}) or {}
    max_pos = int(risk_cfg.get("max_position_count", 10) or 10)
    max_weight = float(risk_cfg.get("max_position_pct", 0.2) or 0.2)
    max_gross = float(risk_cfg.get("max_gross_exposure_pct", 95) or 95) / 100
    pool = list(dict.fromkeys(context.get("candidate_pool") or []))[:max_pos]
    if not pool:
        pool = [h.get("code") for h in context.get("holdings", []) if h.get("code")]
    if not pool:
        return {
            "summary": "无候选股票，目标组合保持空仓/观望。",
            "trade_policy": "no_new_position",
            "cash_target_pct": 100,
            "target_weights": [],
            "rebalance_plan": [],
            "risk_budget": {"max_position_pct": max_weight, "max_gross_exposure_pct": max_gross * 100, "max_orders": 0},
            "objective_note": "目标激进但无可执行候选，不强行交易。",
            "risk_notes": [reason] if reason else [],
            "fallback": True,
        }
    weight = min(max_weight, max_gross / max(1, len(pool)))
    target_weights = [{"code": c, "target_weight": round(weight, 4), "confidence": 0.5, "reason": "规则兜底等权目标组合"} for c in pool]
    return {
        "summary": "LLM委员会不可用，使用候选池等权兜底组合。",
        "trade_policy": "normal" if pool else "no_new_position",
        "cash_target_pct": max(5, round((1 - weight * len(pool)) * 100, 2)),
        "target_weights": target_weights,
        "rebalance_plan": [{"code": x["code"], "action": "buy", "target_weight": x["target_weight"], "priority": "medium", "reason": x["reason"]} for x in target_weights],
        "risk_budget": {"max_position_pct": max_weight, "max_gross_exposure_pct": max_gross * 100, "max_orders": len(target_weights)},
        "objective_note": "目标权益极激进，兜底计划仍严格遵守仓位上限。",
        "risk_notes": [reason] if reason else [],
        "fallback": True,
    }


def normalize_portfolio_plan(plan: dict, context: dict) -> dict:
    cfg = (context.get("objective") or {}).get("config", {}) or {}
    risk_cfg = cfg.get("risk", {}) or {}
    max_weight = float(risk_cfg.get("max_position_pct", 0.2) or 0.2)
    max_gross = float(risk_cfg.get("max_gross_exposure_pct", 95) or 95) / 100
    max_count = int(risk_cfg.get("max_position_count", 10) or 10)
    allowed = set(context.get("candidate_pool") or []) | {h.get("code") for h in context.get("holdings", []) if h.get("code")}
    out_weights = []
    total = 0.0
    for row in plan.get("target_weights") or []:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code", "")).split(".")[0].strip()
        if not code or code not in allowed:
            continue
        weight = max(0.0, min(max_weight, _safe_float(row.get("target_weight"))))
        if weight <= 0:
            continue
        if total + weight > max_gross:
            weight = max(0.0, max_gross - total)
        if weight <= 0:
            break
        out_weights.append({
            "code": code,
            "target_weight": round(weight, 4),
            "confidence": round(max(0.0, min(1.0, _safe_float(row.get("confidence"), 0.5))), 4),
            "reason": str(row.get("reason") or "目标组合建议")[:160],
        })
        total += weight
        if len(out_weights) >= max_count:
            break
    plan["target_weights"] = out_weights
    plan["trade_policy"] = plan.get("trade_policy") if plan.get("trade_policy") in VALID_POLICIES else "no_new_position"
    if not out_weights and plan["trade_policy"] == "normal":
        plan["trade_policy"] = "no_new_position"
    plan["cash_target_pct"] = round(max(0.0, min(100.0, _safe_float(plan.get("cash_target_pct"), max(0.0, 100 - total * 100)))), 2)
    plan["rebalance_plan"] = _normalize_rebalance(plan.get("rebalance_plan"), out_weights, allowed)
    plan["risk_budget"] = {
        "max_position_pct": max_weight,
        "max_gross_exposure_pct": max_gross * 100,
        "max_orders": int((cfg.get("execution") or {}).get("max_rebalance_orders", 20) or 20),
    }
    plan.setdefault("summary", "目标组合计划已生成")
    plan.setdefault("objective_note", "目标权益 1 亿/1 年仅作为模拟盘目标跟踪，不覆盖硬风控。")
    plan.setdefault("risk_notes", [])
    return plan


def _normalize_rebalance(rows, weights, allowed):
    weight_map = {w["code"]: w["target_weight"] for w in weights}
    out = []
    seen = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code", "")).split(".")[0].strip()
        if not code or code not in allowed or code in seen:
            continue
        action = str(row.get("action", "hold")).lower()
        if action not in VALID_ACTIONS:
            action = "hold"
        out.append({
            "code": code,
            "action": action,
            "target_weight": round(_safe_float(row.get("target_weight"), weight_map.get(code, 0.0)), 4),
            "priority": str(row.get("priority", "medium"))[:20],
            "reason": str(row.get("reason") or "目标组合调仓")[:160],
        })
        seen.add(code)
    for w in weights:
        if w["code"] not in seen:
            out.append({"code": w["code"], "action": "buy", "target_weight": w["target_weight"], "priority": "medium", "reason": w.get("reason", "目标组合补足")})
    return out


def run_portfolio_committee(provider: str = "glm", candidate_pool: list = None, objective: dict = None, loop_results: dict = None) -> dict:
    if objective is None:
        from scripts.ai_objective import compute_objective_status
        objective = compute_objective_status()
    context = _collect_context(candidate_pool or [], objective, loop_results)
    cfg = objective.get("config", {}) or {}
    ultra = cfg.get("ultra_thinking", {}) or {}
    roles = ultra.get("roles") or ["opportunity", "risk", "execution", "portfolio_manager"]

    committee = {"success": True, "provider": provider, "generated_at": _now(), "date": _today(), "roles": []}
    context_with_roles = dict(context)
    for role in roles:
        if not ultra.get("enabled", True) and role != "portfolio_manager":
            continue
        result = _call_role(provider, role, context_with_roles)
        committee["roles"].append(result)
        context_with_roles.setdefault("committee", {})[role] = result.get("data") if result.get("success") else {"error": result.get("error")}

    final_role = next((r for r in reversed(committee["roles"]) if r.get("role") == "portfolio_manager" and r.get("success")), None)
    if final_role:
        raw_plan = dict(final_role.get("data") or {})
    else:
        errors = [r.get("error") for r in committee["roles"] if not r.get("success")]
        raw_plan = _fallback_plan(context, "; ".join([e for e in errors if e])[:240])
        committee["success"] = False
        committee["fallback"] = True
    plan = normalize_portfolio_plan(raw_plan, context)
    plan.update({
        "success": True,
        "provider": provider,
        "generated_at": _now(),
        "date": _today(),
        "plan_id": f"portfolio-{_today()}-{int(datetime.now().timestamp())}",
        "objective": objective,
        "committee_summary": [
            {"role": r.get("role"), "success": r.get("success"), "summary": (r.get("data") or {}).get("summary", "") if r.get("success") else r.get("error", "")}
            for r in committee["roles"]
        ],
    })
    cache.set(COMMITTEE_KEY, committee)
    cache.set(PORTFOLIO_KEY, plan)
    return plan


def get_status() -> dict:
    return {"success": True, "committee": cache.get(COMMITTEE_KEY), "portfolio": cache.get(PORTFOLIO_KEY)}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AI 目标组合规划器")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--provider", default="glm")
    args = parser.parse_args()
    out = run_portfolio_committee(args.provider) if args.run else get_status()
    print(json.dumps({"success": True, "data": out}, ensure_ascii=False, default=str))

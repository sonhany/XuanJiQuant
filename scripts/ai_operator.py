"""AI Quant Operator — 五层量化系统 AI 总控 MVP

职责:
  - 读取当前数据层/因子层/策略层/执行层/风控层状态
  - 调用 GLM-5.2 生成结构化的每日操作计划
  - 写入 ai:operator:latest / ai:operator:daily:<YYYYMMDD> / ai:tasks:<YYYYMMDD>

安全边界:
  - 本模块不直接下单、不直接修改策略配置、不执行 AI 生成代码
  - 只生成建议/任务/风险判断
  - 交易仍由 paper_trader + risk gateway + execution_runner 负责

用法:
  python scripts/ai_operator.py --run
  python scripts/ai_operator.py --status
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant.data.cache import create_cache

cache = create_cache()

LATEST_KEY = "ai:operator:latest"
TASK_KEY_PREFIX = "ai:tasks"
DAILY_KEY_PREFIX = "ai:operator:daily"
LESSONS_KEY = "ai:memory:lessons"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST_PATH = os.path.join(ROOT, "ai_manifest.json")
TOOLS_PATH = os.path.join(ROOT, "ai_tools.json")


def _load_json(path: str, fallback):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return fallback


def _tool_config() -> tuple[dict, dict, dict]:
    manifest = _load_json(MANIFEST_PATH, {})
    cfg = _load_json(TOOLS_PATH, {"tools": [], "action_aliases": {}})
    tools = {t.get("name"): t for t in cfg.get("tools", []) if t.get("name")}
    aliases = cfg.get("action_aliases", {}) or {}
    return manifest, tools, aliases


def _normalize_actions(actions: list) -> list:
    """兼容旧 action 格式, 补齐 tool/risk 字段。"""
    _manifest, tools, aliases = _tool_config()
    out = []
    for action in actions or []:
        if not isinstance(action, dict):
            continue
        row = dict(action)
        tool = row.get("tool") or aliases.get(row.get("action"), "")
        if tool:
            row["tool"] = aliases.get(tool, tool)
        meta = tools.get(row.get("tool"), {})
        row.setdefault("risk", meta.get("risk", "low" if not row.get("tool") else "medium"))
        row.setdefault("auto_allowed", meta.get("auto_allowed", False))
        out.append(row)
    return out


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _latest_kline_date(limit: int = 80) -> str:
    """委托给统一入口 data_freshness。"""
    try:
        from scripts.data_freshness import get_latest_kline_date
        return get_latest_kline_date()
    except Exception:
        return ""


def _collect_state() -> dict:
    """采集五层状态, 尽量只读缓存/已有状态, 不访问外部服务。"""
    cfg = cache.get("paper:config") or {}
    paper_status = cache.get("paper:status") or {}
    exec_state = cache.get("execution:state") or {}
    report = cache.get("paper:report:latest") or {}
    alerts = cache.get("alerts:records") or []
    active_alerts = [a for a in alerts if a.get("status") == "active"]
    # 统一入口: 不再自己算 stale
    from scripts.data_freshness import is_data_stale, get_latest_kline_date, get_expected_date
    latest_date = get_latest_kline_date()
    data_stale = is_data_stale()
    expected_latest = get_expected_date()

    # 账户概览
    cash = float(exec_state.get("cash", 0) or 0)
    positions = exec_state.get("positions", {}) or {}
    position_count = len([p for p in positions.values() if int(p.get("quantity", 0) or 0) > 0])
    market_value = 0.0
    for p in positions.values():
        qty = int(p.get("quantity", 0) or 0)
        price = float(p.get("current_price", p.get("avg_price", 0)) or 0)
        market_value += qty * price
    total_equity = cash + market_value

    # 基准/日报
    bm = report.get("benchmark", {}) if isinstance(report, dict) else {}
    account = report.get("account", {}) if isinstance(report, dict) else {}

    manifest, tools, _aliases = _tool_config()
    memory_summary = cache.get("ai:memory:summary") or {}

    return {
        "timestamp": _now(),
        "date": _today(),
        "manifest": {
            "mission": manifest.get("mission"),
            "primary_goals": manifest.get("primary_goals", [])[:5],
            "hard_limits": manifest.get("hard_limits", [])[:8],
            "metrics": manifest.get("metrics", {}),
        },
        "available_tools": [
            {"name": name, "risk": meta.get("risk"), "auto_allowed": meta.get("auto_allowed")}
            for name, meta in tools.items()
        ],
        "memory_summary": memory_summary,
        "config": {
            "strategy_name": cfg.get("strategy_name"),
            "universe_size": len(cfg.get("universe", []) or []),
            "max_positions": cfg.get("max_positions"),
            "llm": cfg.get("llm", {}),
            "risk": cfg.get("risk", {}),
        },
        "data_layer": {
            "latest_kline_date": latest_date,
            "today": _today(),
            "data_stale": data_stale,
            "status": "stale" if data_stale else ("ok" if latest_date else "missing"),
        },
        "alpha_factory": {
            "factor_snapshot_exists": bool(cache.get("factor:snapshot")) or os.path.exists(os.path.join(ROOT, "data", "factor_snapshot.pkl")),
            "approved_ai_factors": len(cache.get("ai:factor:approved") or []),
            "candidate_ai_factors": len(cache.get("ai:factor:candidates") or []),
        },
        "strategy_layer": {
            "last_strategy": cfg.get("strategy_name"),
            "last_run": paper_status.get("last_run"),
            "last_result": paper_status.get("last_result"),
        },
        "execution_layer": {
            "cash": round(cash, 2),
            "market_value": round(market_value, 2),
            "total_equity": round(total_equity, 2),
            "position_count": position_count,
            "orders": len(exec_state.get("orders", []) or []),
            "trades": len(exec_state.get("trades", []) or []),
        },
        "risk_monitor": {
            "active_alerts": len(active_alerts),
            "critical_alerts": len([a for a in active_alerts if a.get("level") == "critical"]),
            "latest_report_date": report.get("report_date") if isinstance(report, dict) else None,
            "benchmark": bm,
            "account": account,
        },
        "lessons": cache.get(LESSONS_KEY) or [],
    }


def _fallback_plan(state: dict, reason: str = "") -> dict:
    """LLM 不可用时的确定性保守计划。"""
    data = state.get("data_layer", {})
    risk = state.get("risk_monitor", {})
    trade_allowed = not data.get("data_stale") and risk.get("critical_alerts", 0) == 0
    tasks = []
    if data.get("data_stale"):
        tasks.append({"layer": "data", "action": "run_daily_update", "priority": "high", "reason": "K线数据过期"})
    if risk.get("critical_alerts", 0) > 0:
        tasks.append({"layer": "risk", "action": "review_critical_alerts", "priority": "high", "reason": "存在严重告警"})
    tasks.extend([
        {"layer": "factor", "action": "evaluate_factor_ic", "priority": "medium", "reason": "每日因子稳定性检查"},
        {"layer": "strategy", "action": "review_signal_quality", "priority": "medium", "reason": "检查策略信号与基准偏差"},
    ])
    return {
        "success": False,
        "fallback": True,
        "error": reason,
        "date": state.get("date"),
        "generated_at": _now(),
        "summary": "AI 总控降级为规则模式。" + (f"原因: {reason}" if reason else ""),
        "paper_trade_allowed": trade_allowed,
        "trade_policy": "normal" if trade_allowed else "no_new_position",
        "risk_notes": ["数据过期或严重告警时禁止新开仓"] if not trade_allowed else [],
        "actions": _normalize_actions(tasks),
        "self_verification": [
            "检查数据最新日期是否等于当前交易日",
            "运行因子IC评估并保存结果",
            "运行策略回测并与沪深300对比",
            "核对模拟盘订单是否全部通过风控网关",
        ],
        "state": state,
    }


def _build_prompt(state: dict) -> str:
    compact = {
        "date": state.get("date"),
        "mission": state.get("manifest", {}).get("mission"),
        "hard_limits": state.get("manifest", {}).get("hard_limits"),
        "available_tools": state.get("available_tools"),
        "memory_summary": state.get("memory_summary"),
        "data_layer": state.get("data_layer"),
        "strategy": state.get("strategy_layer", {}).get("last_strategy"),
        "last_result": state.get("strategy_layer", {}).get("last_result"),
        "execution": state.get("execution_layer"),
        "risk_monitor": state.get("risk_monitor"),
        "config": state.get("config"),
    }
    return json.dumps(compact, ensure_ascii=False, default=str, indent=2)


def _rule_actions(state: dict) -> list:
    """基于硬规则生成任务列表。用于兜底, 也用于 LLM 非JSON时补齐结构。"""
    data = state.get("data_layer", {})
    risk = state.get("risk_monitor", {})
    tasks = []
    if data.get("data_stale"):
        tasks.append({"layer": "data", "action": "run_daily_update", "priority": "high", "reason": "K线数据过期"})
    if risk.get("critical_alerts", 0) > 0:
        tasks.append({"layer": "risk", "action": "review_critical_alerts", "priority": "high", "reason": "存在严重告警"})
    tasks.extend([
        {"layer": "factor", "action": "evaluate_factor_ic", "priority": "medium", "reason": "每日因子稳定性检查"},
        {"layer": "strategy", "action": "review_signal_quality", "priority": "medium", "reason": "检查策略信号与基准偏差"},
    ])
    return tasks


def _plan_from_ai_text(state: dict, provider: str, text: str) -> dict:
    """LLM 有响应但不是 JSON 时, 用文本作为 summary, 结构字段由硬规则补齐。"""
    data = state.get("data_layer", {})
    risk = state.get("risk_monitor", {})
    trade_allowed = not data.get("data_stale") and risk.get("critical_alerts", 0) == 0
    return {
        "success": True,
        "fallback": False,
        "json_repaired": True,
        "date": state.get("date"),
        "generated_at": _now(),
        "provider": provider,
        "summary": (text or "AI 已返回非JSON文本, 已由系统补齐结构化字段。")[:800],
        "paper_trade_allowed": trade_allowed,
        "trade_policy": "normal" if trade_allowed else "no_new_position",
        "risk_notes": ["数据过期或严重告警时禁止新开仓"] if not trade_allowed else [],
        "actions": _normalize_actions(_rule_actions(state)),
        "self_verification": [
            "检查数据最新日期是否等于当前交易日",
            "运行因子IC评估并保存结果",
            "运行策略回测并与沪深300对比",
            "核对模拟盘订单是否全部通过风控网关",
        ],
        "next_iteration": ["优化AI总控JSON输出稳定性", "补充全球动态与板块资金流上下文"],
        "state": state,
    }


def run_operator(provider: str = None) -> dict:
    """运行 AI 总控, 返回结构化计划并持久化。"""
    state = _collect_state()
    llm_cfg = state.get("config", {}).get("llm", {}) or {}
    provider = provider or llm_cfg.get("provider") or "glm"

    system = (
        "你是A股量化模拟盘系统的AI总控 Operator。你要根据五层状态生成今日操作计划。"
        "你不能直接下单、不能绕过风控、不能要求执行任意代码。"
        "你只能从 available_tools 里选择 tool, 不能发明工具名。"
        "你必须输出一个JSON对象,不要输出Markdown,不要输出推理过程。"
        "JSON schema如下:"
        "{\"summary\":\"简短中文摘要\","
        "\"paper_trade_allowed\":false,"
        "\"trade_policy\":\"normal|reduce_only|no_new_position\","
        "\"risk_notes\":[\"...\"],"
        "\"actions\":[{\"layer\":\"data|factor|strategy|execution|risk|memory|update\",\"tool\":\"available_tools中的name\",\"action\":\"...\",\"priority\":\"high|medium|low\",\"risk\":\"low|medium|high\",\"reason\":\"...\"}],"
        "\"self_verification\":[\"...\"],"
        "\"next_iteration\":[\"...\"]}。"
    )
    user = "以下是系统五层状态,请只返回JSON总控计划:\n" + _build_prompt(state)

    try:
        from scripts.llm_client import chat, _extract_json
        r = chat(provider, system, user, temperature=0.1, timeout=60, max_tokens=1800, scene="operator")
        if not r.get("success"):
            plan = _fallback_plan(state, r.get("error", "LLM失败"))
        else:
            raw_text = r.get("text", "")
            data = _extract_json(raw_text)
            if data is None:
                plan = _plan_from_ai_text(state, provider, raw_text)
            else:
                plan = {
                    "success": True,
                    "fallback": False,
                    "date": state.get("date"),
                    "generated_at": _now(),
                    "provider": provider,
                    "summary": data.get("summary", ""),
                    "paper_trade_allowed": bool(data.get("paper_trade_allowed", False)),
                    "trade_policy": data.get("trade_policy", "no_new_position"),
                    "risk_notes": data.get("risk_notes", []),
                    "actions": _normalize_actions(data.get("actions", [])),
                    "self_verification": data.get("self_verification", []),
                    "next_iteration": data.get("next_iteration", []),
                    "state": state,
                }
    except Exception as e:
        plan = _fallback_plan(state, str(e)[:200])

    # 硬安全兜底: 数据过期或严重告警时禁止新开仓
    if state.get("data_layer", {}).get("data_stale") or state.get("risk_monitor", {}).get("critical_alerts", 0) > 0:
        plan["paper_trade_allowed"] = False
        plan["trade_policy"] = "no_new_position"
        notes = plan.setdefault("risk_notes", [])
        notes.append("硬规则: 数据过期或存在严重告警,禁止新开仓")

    cache.set(LATEST_KEY, plan)
    cache.set(f"{DAILY_KEY_PREFIX}:{state.get('date')}", plan)
    cache.set(f"{TASK_KEY_PREFIX}:{state.get('date')}", plan.get("actions", []))
    return plan


def get_status() -> dict:
    latest = cache.get(LATEST_KEY)
    live_state = _collect_state()
    # 关键: 如果有缓存的 plan, 用实时 state 覆盖缓存里的 state
    # 这样前端读 latest.state.data_layer.data_stale 永远是实时值
    if latest and isinstance(latest, dict):
        latest["state"] = live_state
    return {
        "success": True,
        "latest": latest,
        "tasks": cache.get(f"{TASK_KEY_PREFIX}:{_today()}") or [],
        "state": live_state,
    }


def main():
    parser = argparse.ArgumentParser(description="AI Quant Operator")
    parser.add_argument("--run", action="store_true", help="运行AI总控")
    parser.add_argument("--status", action="store_true", help="读取AI总控状态")
    parser.add_argument("--provider", default=None, help="LLM provider, default from paper config")
    args = parser.parse_args()

    if args.run:
        out = run_operator(args.provider)
    else:
        out = get_status()
    print(json.dumps({"success": True, "data": out}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()

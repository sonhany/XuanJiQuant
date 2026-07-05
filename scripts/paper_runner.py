"""Paper 路由持久化 Runner — 高频只读 action 的常驻进程

设计 (复用 data_runner.py 的 stdin/stdout JSON-RPC 协议):
  - 常驻进程, 避免每次 status 查询都启动新 Python (~300ms → ~20ms)
  - 只承接高频只读 action (status/progress/log/ai_all_status 等)
  - 写操作 / 长任务 (run_now/set_config/test_llm/ai_*_run) 仍走 paper.mjs 的 spawnSync/spawn

协议:
  - stdin: 每行一个 JSON 请求 {"action": "...", ...}
  - stdout: 每行一个 JSON 响应 (确保 flush)
  - 错误也输出为 JSON {"success": false, "error": "..."}

接入: server/routes/paper.mjs 顶部
  const runner = new PersistentRunner('paper_runner.py');
  runner.ensure();
  高频 action 改用 await runner.call(body)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def j(obj):
    """JSON 序列化 (ensure_ascii=False, 容错非序列化对象)。"""
    return json.dumps(obj, ensure_ascii=False, default=str)


def _cache():
    from quant.data.cache import create_cache
    return create_cache()


def _merge_dict(base: dict, override: dict) -> dict:
    out = dict(base or {})
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge_dict(out[k], v)
        else:
            out[k] = v
    return out


def _default_paper_config() -> dict:
    return {
        "strategy_name": "ma_cross",
        "strategy_params": {"fast": 5, "slow": 20},
        "universe": ["600519", "000858", "600036", "000333", "601318"],
        "position_size_pct": 0.2,
        "max_positions": 5,
        "trade_time": "15:05",
        "enabled": True,
        "skip_data_stale": True,
        "risk": {
            "kill_switch": False,
            "max_position_pct": 0.2,
            "max_gross_exposure_pct": 95,
            "max_position_count": 10,
            "max_orders_per_run": 20,
            "min_cash_buffer_pct": 2,
            "max_daily_loss_pct": 5,
            "capital_cap": 0,
            "allow_buy_st": False,
            "allow_buy_limit_up": False,
            "allow_sell_limit_down": False,
        },
        "llm": {
            "enabled": True,
            "provider": "glm",
            "mode": "review",
            "timeout": 45,
            "max_new_positions": 3,
            "confidence_threshold": 0.6,
            "interpret_alerts": True,
        },
    }


def _paper_config(c=None) -> dict:
    c = c or _cache()
    return _merge_dict(_default_paper_config(), c.get("paper:config") or {})


# ── 高频只读 actions ─────────────────────────────────────
def action_status(req):
    """读 paper:config + paper:status + daemon meta。"""
    c = _cache()
    return {
        "success": True,
        "data": {
            "config": _paper_config(c),
            "status": c.get("paper:status") or {},
            "log": (c.get("paper:log") or [])[-30:][::-1],
        },
    }


def action_progress(req):
    """读运行进度。"""
    c = _cache()
    return {"success": True, "data": {
        "events": c.get("paper:progress") or [],
        "running": bool(c.get("paper:run_active")),
        "result": c.get("paper:run_result"),
        "daemon_running": (c.get("paper:status") or {}).get("running", False),
    }}


def action_log(req):
    """读运行日志。"""
    c = _cache()
    limit = int(req.get("limit", 50))
    logs = c.get("paper:log") or []
    return {"success": True, "data": logs[-limit:][::-1]}


def action_ai_all_status(req):
    """一次读全部5层+全球+闭环+operator+lessons+选股+决策 (驾驶舱主数据源)。"""
    c = _cache()
    try:
        from quant.ai.layer_contracts import contract_summary
        layer_contracts = contract_summary()
    except Exception:
        layer_contracts = {}
    now = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data_default = {"success": True, "generated_at": now, "data_stale": False, "trade_allowed": True, "integrity": {"summary": {}}}
    risk_default = {"success": True, "generated_at": now, "pre_trade": {"trade_allowed": True, "trade_policy": "normal", "block_reasons": []}}
    global_default = {"success": True, "generated_at": now, "risk_level": "unknown", "trade_policy": "normal", "risk_signals": []}
    operator_default = {"success": True, "generated_at": now, "trade_policy": None, "paper_trade_allowed": False, "summary": "尚未运行AI总控", "skipped": True}
    loop_default = {"started_at": None, "finished_at": None, "final": {"trade_allowed": False, "trade_policy": None}, "skipped": True}
    out = {
        "L1_data": c.get("ai:data:latest") or data_default,
        "L2_factor": {"approved": c.get("ai:factor:approved") or [], "candidates": c.get("ai:factor:candidates") or []},
        "L3_strategy": {"approved": c.get("ai:strategy:approved") or [], "candidates": c.get("ai:strategy:candidates") or []},
        "L4_execution": c.get("ai:execution:latest"),
        "L5_risk": c.get("ai:risk:latest") or risk_default,
        "global": c.get("global:context:latest") or global_default,
        "operator": c.get("ai:operator:latest") or operator_default,
        "loop": {"latest": c.get("ai:loop:latest") or loop_default, "progress": c.get("ai:loop:progress") or []},
        "lessons": (c.get("ai:memory:lessons") or [])[-5:],
        "memory": {"stats": c.get("ai:memory:stats"), "summary": c.get("ai:memory:summary"), "recent": (c.get("ai:memory:lessons") or [])[-10:]},
        "verifier": c.get("ai:verifier:latest"),
        "tool_executor": c.get("ai:tool_executor:latest"),
        "updates": c.get("ai:updates:latest"),
        "decision": c.get("ai:decision:latest"),   # 含 candidate_pool, trade_policy, risk_ok
        "screen": c.get("ai:screen:latest"),         # 选股 Top + AI置信度 + 理由
        "objective": c.get("ai:objective:latest"),
        "committee": c.get("ai:committee:latest"),
        "portfolio": c.get("ai:portfolio:latest"),
        "autonomous_config": c.get("ai:autonomous:config"),
        "layer_contracts": layer_contracts,
    }
    return {"success": True, "data": out}


def action_ai_memory_status(req):
    from scripts.ai_memory import get_memory_status
    return {"success": True, "data": get_memory_status()}


def action_ai_verifier_status(req):
    from scripts.ai_verifier import get_status
    return {"success": True, "data": get_status()}


def action_ai_tool_executor_status(req):
    from scripts.ai_action_executor import get_status
    return {"success": True, "data": get_status()}


def action_ai_updates_status(req):
    from scripts.ai_self_improver import get_status
    return {"success": True, "data": get_status()}


def action_ai_screen_status(req):
    """读取全市场选股结果 (供驾驶舱选股流展示)。"""
    c = _cache()
    return {"success": True, "data": c.get("ai:screen:latest") or {"top": []}}


def action_ai_autonomous_status(req):
    from scripts.ai_objective import get_status, compute_objective_status
    data = get_status()
    data["objective"] = compute_objective_status()
    return {"success": True, "data": data}


def action_ai_autonomous_get_config(req):
    from scripts.ai_objective import load_autonomous_config
    return {"success": True, "data": load_autonomous_config()}


def action_ai_screen_run(req):
    """手动触发一次全市场选股。"""
    from scripts.ai_stock_screener import screen_market
    provider = (req or {}).get("provider", "glm")
    top_n = int((req or {}).get("top_n", 20))
    return {"success": True, "data": screen_market(top_n=top_n, provider=provider)}


def action_ai_operator_status(req):
    from scripts.ai_operator import get_status
    return {"success": True, "data": get_status()}


def action_ai_loop_status(req):
    from scripts.ai_loop import get_status
    return {"success": True, "data": get_status()}


def action_ai_scheduler_status(req):
    from scripts.ai_scheduler import get_status
    return {"success": True, "data": get_status()}


def action_watchdog_status(req):
    c = _cache()
    return {"success": True, "data": c.get("ai:watchdog:latest") or {
        "last_check": None, "paper_alive": False, "scheduler_alive": False, "events": []}}


def action_llm_usage(req):
    from scripts.llm_usage import get_usage_stats
    days = int(req.get("days", 7))
    return {"success": True, "data": get_usage_stats(days)}


def action_global_context_status(req):
    c = _cache()
    return {"success": True, "data": c.get("global:context:latest") or {"success": True, "latest": None}}


def action_report(req):
    """读已有日报。"""
    c = _cache()
    report = c.get("paper:report:latest")
    if report and isinstance(report, dict):
        data = report.get("data", {})
        try:
            from scripts.data_freshness import is_data_stale
            data["is_stale"] = is_data_stale()
        except Exception:
            pass
    return {"success": True, "data": report}


def action_get_config(req):
    c = _cache()
    return {"success": True, "data": _paper_config(c)}


def action_benchmark(req):
    """读基准 (不主动刷新, 刷新走 paper.mjs 的 spawnSync)。"""
    c = _cache()
    return {"success": True, "data": c.get("paper:benchmark:latest")}


# ── action 注册表 ────────────────────────────────────────
ACTIONS = {
    "status": action_status,
    "progress": action_progress,
    "log": action_log,
    "ai_all_status": action_ai_all_status,
    "ai_screen_status": action_ai_screen_status,
    "ai_autonomous_status": action_ai_autonomous_status,
    "ai_autonomous_get_config": action_ai_autonomous_get_config,
    "ai_operator_status": action_ai_operator_status,
    "ai_loop_status": action_ai_loop_status,
    "ai_scheduler_status": action_ai_scheduler_status,
    "ai_memory_status": action_ai_memory_status,
    "ai_verifier_status": action_ai_verifier_status,
    "ai_tool_executor_status": action_ai_tool_executor_status,
    "ai_updates_status": action_ai_updates_status,
    "watchdog_status": action_watchdog_status,
    "llm_usage": action_llm_usage,
    "global_context_status": action_global_context_status,
    "report": action_report,
    "get_config": action_get_config,
    "benchmark": action_benchmark,
}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            print(j({"success": False, "error": "invalid JSON"}))
            sys.stdout.flush()
            continue
        action = req.get("action", "status")
        handler = ACTIONS.get(action)
        if not handler:
            print(j({"success": False, "error": f"paper_runner 无此 action: {action} (走 paper.mjs spawnSync)"}))
            sys.stdout.flush()
            continue
        req_id = req.get("__id")
        try:
            out = handler(req)
        except Exception as e:
            import traceback
            traceback.print_exc()
            out = {"success": False, "error": str(e)[:500]}
        if req_id and isinstance(out, dict):
            out["__id"] = req_id
        print(j(out))
        sys.stdout.flush()


if __name__ == "__main__":
    main()

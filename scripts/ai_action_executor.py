"""AI 工具执行器 — 只执行白名单工具, 不接受 LLM 任意命令。"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache

cache = create_cache()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST_PATH = os.path.join(ROOT, "ai_manifest.json")
TOOLS_PATH = os.path.join(ROOT, "ai_tools.json")
LATEST_KEY = "ai:tool_executor:latest"
LOG_KEY = "ai:tool_executor:log"
PROGRESS_KEY = "ai:tool_executor:progress"
COUNT_PREFIX = "ai:tool_executor:count"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _load_json(path: str, fallback):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return fallback


def _load_config() -> tuple[dict, dict, dict]:
    manifest = _load_json(MANIFEST_PATH, {})
    tools_cfg = _load_json(TOOLS_PATH, {"tools": [], "action_aliases": {}})
    tools = {t.get("name"): t for t in tools_cfg.get("tools", []) if t.get("name")}
    aliases = tools_cfg.get("action_aliases", {}) or {}
    return manifest, tools, aliases


def normalize_tool(action: dict, aliases: dict) -> str:
    if not isinstance(action, dict):
        return ""
    tool = action.get("tool") or action.get("name")
    if tool:
        return aliases.get(tool, tool)
    raw = action.get("action") or action.get("type") or ""
    return aliases.get(raw, "")


def _log(event: dict):
    log = cache.get(LOG_KEY) or []
    row = {"time": _now(), **event}
    log.append(row)
    cache.set(LOG_KEY, log[-80:])
    cache.set(PROGRESS_KEY, log[-20:])


def _count_key(tool: str) -> str:
    return f"{COUNT_PREFIX}:{_today()}:{tool}"


def _parse_time(value: str):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(value).replace("+08:00", ""), fmt)
        except Exception:
            continue
    return None


def _fresh_record(record: dict, max_age_hours: int = 8) -> tuple[bool, str]:
    if not record:
        return False, "缺少记录"
    rec_date = str(record.get("date") or "")
    if not rec_date:
        return False, "缺少记录日期"
    if rec_date != _today():
        return False, f"记录日期过期: {rec_date}"
    raw_ts = record.get("generated_at") or record.get("finished_at") or record.get("updated_at")
    if not raw_ts:
        return False, "缺少记录时间戳"
    ts = _parse_time(raw_ts)
    if not ts:
        return False, "记录时间戳格式无效"
    if datetime.now() - ts > timedelta(hours=max_age_hours):
        return False, "记录已超过时效"
    return True, "记录有效"


def _can_execute(tool: str, cfg: dict, decision: dict, verifier: dict, dry_run: bool) -> tuple[bool, str]:
    if not cfg:
        return False, "工具不在白名单"
    if not cfg.get("auto_allowed", False):
        return False, "工具未允许自动执行"
    count = int(cache.get(_count_key(tool)) or 0)
    max_per_day = int(cfg.get("max_per_day") or 0)
    if max_per_day and count >= max_per_day:
        return False, f"超过每日次数限制 {max_per_day}"
    needs_decision = cfg.get("requires_data_fresh") or cfg.get("requires_risk_pass") or cfg.get("risk") == "high"
    if needs_decision:
        fresh, reason = _fresh_record(decision, max_age_hours=8)
        if not fresh:
            return False, f"ai:decision:latest 不可用: {reason}"
    if cfg.get("requires_data_fresh"):
        if not bool(decision.get("data_ok", False)):
            return False, "数据新鲜度未通过"
    if cfg.get("requires_risk_pass"):
        if not (decision.get("trade_allowed") and decision.get("risk_ok") and decision.get("operator_allowed") and decision.get("trade_policy") == "normal"):
            return False, "最终交易决策未允许"
    if cfg.get("risk") == "high":
        fresh, reason = _fresh_record(verifier, max_age_hours=8)
        if not fresh:
            return False, f"自我验证不可用: {reason}"
        if verifier.get("overall") != "pass":
            return False, "自我验证未通过, 禁止高风险工具"
    return True, "dry-run" if dry_run else "允许执行"


def _run_subprocess(args: list, timeout: int) -> dict:
    r = subprocess.run(args, cwd=ROOT, timeout=timeout, capture_output=True, text=True,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8", "QUANT_SKIP_NODE_PROXY": "1"})
    data = None
    if r.stdout:
        try:
            data = json.loads(r.stdout.strip().split("\n")[-1])
        except Exception:
            data = None
    return {"success": r.returncode == 0, "returncode": r.returncode, "data": data,
            "stdout": (r.stdout or "")[-1000:], "stderr": (r.stderr or "")[-1000:]}


def _execute_tool(tool: str, cfg: dict, source: str, provider: str = "glm") -> dict:
    timeout = int(cfg.get("timeout_sec") or 120)
    if tool == "run_verifier":
        from scripts.ai_verifier import run_verifier
        return run_verifier("quick")
    if tool == "verify_portfolio_plan":
        from scripts.ai_verifier import run_verifier
        return run_verifier("quick")
    if tool == "generate_portfolio_plan":
        from scripts.ai_objective import compute_objective_status
        from scripts.ai_portfolio_planner import run_portfolio_committee
        decision = cache.get("ai:decision:latest") or {}
        objective = compute_objective_status()
        return run_portfolio_committee(provider, candidate_pool=decision.get("candidate_pool") or [], objective=objective)
    if tool == "memory_compact":
        from scripts.ai_memory import compact_memory
        return compact_memory()
    if tool == "run_stock_screener":
        from scripts.ai_stock_screener import screen_market
        return screen_market(top_n=20, provider=provider)
    if tool == "run_risk_monitor":
        from scripts.ai_risk_agent import run_risk_monitor
        return run_risk_monitor(provider)
    if tool == "run_factor_factory":
        from scripts.ai_factor_agent import run_factor_factory
        return run_factor_factory(provider)
    if tool == "run_strategy_factory":
        from scripts.ai_strategy_agent import run_strategy_factory
        return run_strategy_factory(provider)
    if tool == "refresh_data":
        from scripts.daily_update import incremental_klines, sync_universe
        codes = sync_universe()
        return incremental_klines(codes, cache)
    if tool == "evaluate_factors":
        return _run_subprocess([sys.executable, os.path.join(ROOT, "scripts", "evaluate_factors.py"), "--no-cache"], timeout)
    if tool in ("paper_trade_once", "paper_rebalance_once"):
        paper_source = "scheduler" if source == "scheduler" else "ai_loop"
        return _run_subprocess([sys.executable, os.path.join(ROOT, "scripts", "paper_trader.py"), "--once", "--source", paper_source], timeout)
    if tool == "self_improve_propose":
        from scripts.ai_self_improver import propose_update
        return propose_update(provider)
    return {"success": False, "error": f"未实现工具: {tool}"}


def _actions_from_operator(aliases: dict) -> list:
    operator = cache.get("ai:operator:latest") or {}
    actions = []
    for action in operator.get("actions", []) or []:
        tool = normalize_tool(action, aliases)
        if tool:
            actions.append({"tool": tool, "raw": action, "reason": action.get("reason", "")})
    return actions


def run_executor(source: str = "manual", allowed_tools: list = None, dry_run: bool = False, provider: str = "glm") -> dict:
    """执行白名单动作。allowed_tools 为空时消费 operator actions。"""
    _manifest, tools, aliases = _load_config()
    decision = cache.get("ai:decision:latest") or {}
    verifier = cache.get("ai:verifier:latest") or {}
    actions = [{"tool": t, "raw": {"tool": t}, "reason": "explicit"} for t in (allowed_tools or [])]
    if not actions:
        actions = _actions_from_operator(aliases)
    if not actions:
        actions = [{"tool": "run_verifier", "raw": {"tool": "run_verifier"}, "reason": "default safety check"}]

    result = {"success": True, "source": source, "dry_run": dry_run, "started_at": _now(), "actions": []}
    cache.set(LATEST_KEY, {**result, "running": True, "status": "running"})
    seen = set()
    for action in actions:
        tool = action.get("tool")
        if tool in seen:
            continue
        seen.add(tool)
        cfg = tools.get(tool)
        ok, reason = _can_execute(tool, cfg, decision, verifier, dry_run)
        row = {"tool": tool, "risk": (cfg or {}).get("risk"), "allowed": ok, "reason": reason, "started_at": _now()}
        if ok and not dry_run:
            try:
                out = _execute_tool(tool, cfg, source, provider=provider)
                row["result"] = out
                row["success"] = bool(out.get("success", True)) if isinstance(out, dict) else True
                cache.set(_count_key(tool), int(cache.get(_count_key(tool)) or 0) + 1, ttl=3 * 86400)
            except Exception as e:
                row["success"] = False
                row["error"] = str(e)[:300]
        else:
            row["success"] = bool(ok)
            row["skipped"] = not ok or dry_run
        row["finished_at"] = _now()
        result["actions"].append(row)
        _log({"event": "execute" if ok and not dry_run else "skip", **row})
    result["finished_at"] = _now()
    result["success"] = all(a.get("success", False) for a in result["actions"])
    result["status"] = "done" if result["success"] else "error"
    result["running"] = False
    cache.set(LATEST_KEY, result)
    return result


def get_status() -> dict:
    return {"success": True, "latest": cache.get(LATEST_KEY), "progress": cache.get(PROGRESS_KEY) or [], "log": (cache.get(LOG_KEY) or [])[-30:]}


def main():
    parser = argparse.ArgumentParser(description="AI 工具执行器")
    parser.add_argument("--run", action="store_true", help="执行工具")
    parser.add_argument("--status", action="store_true", help="读取状态")
    parser.add_argument("--dry-run", action="store_true", help="只做门禁检查")
    parser.add_argument("--source", default="manual")
    parser.add_argument("--provider", default="glm")
    parser.add_argument("--tool", action="append", help="显式允许执行的工具, 可重复")
    args = parser.parse_args()
    if args.run or args.dry_run:
        out = run_executor(args.source, allowed_tools=args.tool, dry_run=args.dry_run, provider=args.provider)
    else:
        out = get_status()
    print(json.dumps(out, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()

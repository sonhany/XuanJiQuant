"""AI 自我验证器 — 决策一致性、风控和工具白名单校验。"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.ai.contracts import DecisionValidationError, validate_ai_decision
from quant.data.cache import create_cache

cache = create_cache()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_PATH = os.path.join(ROOT, "ai_tools.json")
LATEST_KEY = "ai:verifier:latest"
LOG_KEY = "ai:verifier:log"
VALID_POLICIES = {"normal", "reduce_only", "no_new_position"}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


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


def _load_tools() -> tuple[dict, dict]:
    try:
        with open(TOOLS_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {"tools": [], "action_aliases": {}}
    tools = {t.get("name"): t for t in cfg.get("tools", []) if t.get("name")}
    aliases = cfg.get("action_aliases", {}) or {}
    return tools, aliases


def normalize_tool(action: dict, aliases: dict) -> str:
    if not isinstance(action, dict):
        return ""
    tool = action.get("tool") or action.get("name")
    if tool:
        return aliases.get(tool, tool)
    raw = action.get("action") or action.get("type") or ""
    return aliases.get(raw, "")


def _check_data() -> dict:
    try:
        from scripts.data_freshness import is_data_stale, get_latest_kline_date, get_expected_date
        stale = bool(is_data_stale())
        return {
            "name": "data_freshness",
            "status": "pass" if not stale else "fail",
            "stale": stale,
            "latest_date": get_latest_kline_date(),
            "expected_date": get_expected_date(),
        }
    except Exception as e:
        return {"name": "data_freshness", "status": "fail", "error": str(e)[:200]}


def _check_operator(tools: dict, aliases: dict) -> dict:
    plan = cache.get("ai:operator:latest") or {}
    errors = []
    warnings = []
    policy = plan.get("trade_policy")
    if plan and policy not in VALID_POLICIES:
        errors.append(f"非法 trade_policy: {policy}")
    actions = plan.get("actions") or []
    for i, action in enumerate(actions):
        tool = normalize_tool(action, aliases)
        if not tool:
            warnings.append(f"action[{i}] 未映射到自动工具, 将作为人工建议保留")
        elif tool not in tools:
            errors.append(f"action[{i}] 工具不在白名单: {tool}")
    return {
        "name": "operator_plan",
        "status": "pass" if not errors else "fail",
        "policy": policy,
        "actions": len(actions),
        "errors": errors,
        "warnings": warnings,
    }


def _check_decision() -> dict:
    decision = cache.get("ai:decision:latest") or {}
    errors = []
    warnings = []
    try:
        if decision:
            decision = validate_ai_decision(decision)
    except DecisionValidationError as e:
        errors.append(f"AI决策协议无效: {e}")
    policy = decision.get("trade_policy")
    if decision and policy not in VALID_POLICIES:
        errors.append(f"非法 trade_policy: {policy}")
    data_ok = bool(decision.get("data_ok", False))
    risk_ok = bool(decision.get("risk_ok", False))
    trade_allowed = bool(decision.get("trade_allowed", False))
    operator_allowed = bool(decision.get("operator_allowed", False))
    expected_allowed = policy == "normal" and data_ok and risk_ok and operator_allowed
    if decision and trade_allowed != expected_allowed:
        errors.append("trade_allowed 与 trade_policy/data_ok/risk_ok/operator_allowed 不一致")
    if decision:
        fresh, reason = _fresh_record(decision, max_age_hours=8)
        if not fresh:
            errors.append(f"ai:decision:latest 过期或不可用: {reason}")
    else:
        warnings.append("暂无 ai:decision:latest")
    return {
        "name": "decision_consistency",
        "status": "pass" if not errors else "fail",
        "trade_policy": policy,
        "trade_allowed": trade_allowed,
        "data_ok": data_ok,
        "risk_ok": risk_ok,
        "operator_allowed": operator_allowed,
        "errors": errors,
        "warnings": warnings,
    }


def _check_portfolio_plan() -> dict:
    """校验 AI 目标组合计划不会突破本地硬风控边界。"""
    decision = cache.get("ai:decision:latest") or {}
    portfolio = cache.get("ai:portfolio:latest") or {}
    cfg = ((decision.get("objective") or {}).get("config") or {}) or ((portfolio.get("objective") or {}).get("config") or {})
    risk_cfg = cfg.get("risk", {}) if isinstance(cfg, dict) else {}
    max_pos = float(risk_cfg.get("max_position_pct", 0.2) or 0.2)
    max_gross = float(risk_cfg.get("max_gross_exposure_pct", 95) or 95) / 100
    max_count = int(risk_cfg.get("max_position_count", 10) or 10)
    target_weights = decision.get("target_weights") or portfolio.get("target_weights") or []
    candidate_pool = {str(c).split(".")[0] for c in (decision.get("candidate_pool") or []) if c}
    positions = (cache.get("execution:state") or {}).get("positions", {}) or {}
    held = {str(c).split(".")[0] for c, p in positions.items() if int((p or {}).get("quantity", 0) or 0) > 0}
    allowed_codes = candidate_pool | held
    errors, warnings = [], []
    if target_weights and not isinstance(target_weights, list):
        errors.append("target_weights 必须是数组")
        target_weights = []
    total = 0.0
    seen = set()
    for i, row in enumerate(target_weights):
        if not isinstance(row, dict):
            errors.append(f"target_weights[{i}] 不是对象")
            continue
        code = str(row.get("code", "")).split(".")[0].strip()
        weight = row.get("target_weight")
        try:
            weight = float(weight)
        except Exception:
            errors.append(f"{code or i} target_weight 非数字")
            continue
        if not code:
            errors.append(f"target_weights[{i}] 缺少 code")
        elif allowed_codes and code not in allowed_codes:
            errors.append(f"{code} 不在候选池或当前持仓中")
        if code in seen:
            errors.append(f"{code} 重复出现在 target_weights")
        seen.add(code)
        if weight < 0 or weight > max_pos + 1e-9:
            errors.append(f"{code} 权重 {weight:.4f} 超过单票上限 {max_pos:.4f}")
        total += max(0.0, weight)
    if len(seen) > max_count:
        errors.append(f"目标持仓数 {len(seen)} 超过上限 {max_count}")
    if total > max_gross + 1e-9:
        errors.append(f"目标总权重 {total:.4f} 超过总暴露上限 {max_gross:.4f}")
    policy = decision.get("trade_policy")
    if policy != "normal":
        buys = [r for r in (decision.get("rebalance_plan") or []) if isinstance(r, dict) and str(r.get("action", "")).lower() == "buy"]
        if buys:
            errors.append("trade_policy 非 normal 时不得包含新增买入计划")
    if decision and decision.get("trade_allowed") and not target_weights and portfolio:
        warnings.append("存在 portfolio 但 decision 未携带 target_weights")
    return {
        "name": "portfolio_plan",
        "status": "pass" if not errors else "fail",
        "targets": len(target_weights),
        "total_weight": round(total, 4),
        "max_position_pct": max_pos,
        "max_gross_exposure_pct": round(max_gross * 100, 2),
        "errors": errors,
        "warnings": warnings,
    }


def _check_risk() -> dict:
    risk = cache.get("ai:risk:latest") or {}
    selfverify = cache.get("ai:selfverify:latest") or {}
    pre = risk.get("pre_trade", {}) if isinstance(risk, dict) else {}
    return {
        "name": "risk_gate",
        "status": "pass" if pre.get("trade_allowed", False) or pre.get("trade_policy") in ("reduce_only", "no_new_position") else "warn",
        "trade_allowed": pre.get("trade_allowed"),
        "trade_policy": pre.get("trade_policy"),
        "block_reasons": pre.get("block_reasons", []),
        "selfverify_overall": selfverify.get("overall") or (risk.get("self_verification", {}) if isinstance(risk, dict) else {}).get("overall"),
    }


def _check_full_rules() -> dict:
    script = os.path.join(ROOT, "scripts", "verify_paper_rules.py")
    try:
        r = subprocess.run([sys.executable, script], cwd=ROOT, timeout=120, capture_output=True, text=True,
                           env={**os.environ, "PYTHONIOENCODING": "utf-8", "QUANT_SKIP_NODE_PROXY": "1"})
        return {
            "name": "paper_rules",
            "status": "pass" if r.returncode == 0 else "fail",
            "returncode": r.returncode,
            "stdout": (r.stdout or "")[-1000:],
            "stderr": (r.stderr or "")[-1000:],
        }
    except Exception as e:
        return {"name": "paper_rules", "status": "fail", "error": str(e)[:200]}


def run_verifier(mode: str = "quick") -> dict:
    """运行验证。quick 不跑耗时规则测试; full 会跑 verify_paper_rules.py。"""
    tools, aliases = _load_tools()
    checks = [_check_data(), _check_operator(tools, aliases), _check_decision(), _check_portfolio_plan(), _check_risk()]
    if mode == "full":
        checks.append(_check_full_rules())
    failed = [c for c in checks if c.get("status") == "fail"]
    result = {
        "success": not failed,
        "mode": mode,
        "overall": "pass" if not failed else "fail",
        "generated_at": _now(),
        "date": _today(),
        "checks": checks,
        "failed": [c.get("name") for c in failed],
        "tools_count": len(tools),
    }
    cache.set(LATEST_KEY, result)
    log = cache.get(LOG_KEY) or []
    log.append({"time": _now(), "mode": mode, "overall": result["overall"], "failed": result["failed"]})
    cache.set(LOG_KEY, log[-50:])
    return result


def get_status() -> dict:
    return {
        "success": True,
        "latest": cache.get(LATEST_KEY),
        "log": (cache.get(LOG_KEY) or [])[-20:],
    }


def main():
    parser = argparse.ArgumentParser(description="AI 自我验证器")
    parser.add_argument("--run", action="store_true", help="运行验证")
    parser.add_argument("--status", action="store_true", help="读取状态")
    parser.add_argument("--mode", choices=["quick", "full"], default="quick")
    args = parser.parse_args()
    out = run_verifier(args.mode) if args.run else get_status()
    print(json.dumps(out, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()

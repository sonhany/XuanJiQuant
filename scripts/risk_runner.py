"""Risk 风控与监控引擎 API

Actions:
  portfolio_risk → 组合风险指标 (VaR/集中度/波动率)
  system_health   → 各层健康状态
  system_log      → 最近系统事件
"""
import sys, json, os, math
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.risk import RiskEngine
from quant.data.cache import create_cache
from quant.data.audit import latest_audit_replays, get_audit_replay

cache = create_cache()
engine = RiskEngine(cache=cache)


def to_py(val):
    if isinstance(val, dict): return {k: to_py(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)): return [to_py(v) for v in val]
    if isinstance(val, (np.integer,)): return int(val)
    if isinstance(val, (float, np.floating)):
        return None if (math.isnan(val) or math.isinf(val)) else round(float(val), 6)
    return val


def action_portfolio_risk(req=None):
    state = cache.get("execution:state") or {}
    r = engine.portfolio_risk(state)
    return {"success": True, "data": r}


def action_system_health(req=None):
    r = engine.system_health()
    return {"success": True, "data": r}


def action_system_log(req):
    r = engine.system_log(lines=req.get("lines", 20))
    return {"success": True, "data": r}


def action_audit_replays(req=None):
    req = req or {}
    return {"success": True, "data": latest_audit_replays(cache, limit=int(req.get("limit", 20)))}


def action_audit_replay(req=None):
    req = req or {}
    return {"success": True, "data": get_audit_replay(
        cache,
        run_id=str(req.get("run_id") or ""),
        decision_id=str(req.get("decision_id") or ""),
        limit=int(req.get("limit", 100)),
    )}


ACTIONS = {
    "portfolio_risk": action_portfolio_risk,
    "system_health": action_system_health,
    "check": action_system_health,  # 兼容 scripts/web_verify.mjs 旧 action
    "system_log": action_system_log,
    "audit_replays": action_audit_replays,
    "audit_replay": action_audit_replay,
}

if __name__ == "__main__":
    for line in sys.stdin:
        line = line.strip()
        if not line: continue
        try:
            req = json.loads(line)
        except Exception:
            print(json.dumps({"success": False, "error": "invalid JSON"}))
            sys.stdout.flush(); continue
        req_id = req.get("__id")
        action = req.get("action", "system_health")
        handler = ACTIONS.get(action)
        if not handler:
            out = {"success": False, "error": f"unknown action: {action}"}
            if req_id: out["__id"] = req_id
            print(json.dumps(out))
            sys.stdout.flush(); continue
        try:
            result = handler(req)
            result = to_py(result)
            if req_id and isinstance(result, dict): result["__id"] = req_id
            if req_id and isinstance(result, dict): result["__id"] = req_id
            print(json.dumps(result))
        except Exception as e:
            import traceback
            out = {"success": False, "error": str(e)[:500]}
            if req_id: out["__id"] = req_id
            print(json.dumps(out))
        sys.stdout.flush()

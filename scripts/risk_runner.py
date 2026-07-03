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


ACTIONS = {
    "portfolio_risk": action_portfolio_risk,
    "system_health": action_system_health,
    "check": action_system_health,  # 兼容 scripts/web_verify.mjs 旧 action
    "system_log": action_system_log,
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
        action = req.get("action", "system_health")
        handler = ACTIONS.get(action)
        if not handler:
            print(json.dumps({"success": False, "error": f"unknown action: {action}"}))
            sys.stdout.flush(); continue
        try:
            result = handler(req)
            print(json.dumps(to_py(result)))
        except Exception as e:
            import traceback
            print(json.dumps({"success": False, "error": str(e)[:500]}))
        sys.stdout.flush()

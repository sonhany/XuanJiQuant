"""Risk 风控与监控引擎 API

Actions:
  portfolio_risk → 组合风险指标 (VaR/集中度/波动率)
  system_health   → 各层健康状态
  system_log      → 最近系统事件
"""
import sys, json, os, math
from datetime import datetime
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.risk import RiskEngine
from quant.risk.config import load_risk_config
from quant.data.cache import create_cache
from quant.data.audit import latest_audit_logs, latest_audit_replays, get_audit_replay
from quant.health import load_f4_projection, load_research_publication, project_four_layer_health
from quant.paper_execution.reporting import status_projection
from quant.paper_execution.runtime import build_runtime_service, load_active_account_projection
from scripts.data_freshness import assess_market_kline_coverage, get_expected_date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
    projection = load_active_account_projection()
    account = dict(projection.get("account") or {})
    positions = {
        str(row.get("code") or ""): dict(row)
        for row in projection.get("positions") or []
        if isinstance(row, dict) and str(row.get("code") or "")
    }
    state = {
        "cash": account.get("cash", 0),
        "initial_capital": account.get(
            "initial_capital", 1_000_000.0
        ),
        "positions": positions,
    }
    r = engine.portfolio_risk(state, risk_limits=load_risk_config(cache))
    r["ledger_authority"] = "f5"
    r["ledger"] = projection.get("ledger")
    r["account_as_of"] = account.get("updated_at")
    r["market_snapshot_id"] = account.get("market_snapshot_id")
    r["valuation_as_of"] = account.get("valuation_as_of")
    r["calculated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    return {"success": True, "data": r}


def action_system_health(req=None):
    expected = get_expected_date()
    coverage = assess_market_kline_coverage(cache=cache, expected_date=expected)
    service = build_runtime_service()
    ledger = service.ledger
    paper = status_projection(
        ledger, current_readiness=service.intraday_readiness(datetime.now())
    )
    latest = paper.get("latest_run") or {}
    if latest:
        orders = ledger.list_orders(latest.get("run_id"), 1000)
        fills = ledger.list_fills(latest.get("run_id"), 1000)
        reconciliations = ledger.list_reconciliations(latest.get("run_id"), 1000)
        paper["latest_run"] = {
            **latest,
            "order_count": len(orders),
            "fill_count": len(fills),
        }
        paper["reconciliation_failed"] = any(
            int(row.get("passed") or 0) != 1 for row in reconciliations
        )
    r = project_four_layer_health(
        expected_date=expected,
        data_coverage=coverage,
        publication=load_research_publication(ROOT),
        f4=load_f4_projection(ROOT),
        paper=paper,
    )
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
        order_id=str(req.get("order_id") or ""),
        limit=int(req.get("limit", 100)),
    )}


def action_decision_trace(req=None):
    return action_audit_replay(req or {})


def action_audit_logs(req=None):
    req = req or {}
    return {"success": True, "data": latest_audit_logs(
        cache,
        limit=int(req.get("limit", 100)),
        event_type=str(req.get("event_type") or ""),
        source=str(req.get("source") or ""),
    )}


ACTIONS = {
    "portfolio_risk": action_portfolio_risk,
    "system_health": action_system_health,
    "system_log": action_system_log,
    "audit_replays": action_audit_replays,
    "audit_replay": action_audit_replay,
    "decision_trace": action_decision_trace,
    "audit_logs": action_audit_logs,
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

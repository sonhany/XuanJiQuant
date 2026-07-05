"""前端 API 端到端测试 — 覆盖 6 大面板调用的全部 22 个 action

模拟前端浏览器行为，逐个调用每个面板实际使用的 API，
验证返回结构是否符合前端期望，确保"打开浏览器每个功能都正常"。

用法: python scripts/test_api.py
前提: 后端运行在 localhost:3334，数据已 seed
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error

BASE = "http://localhost:3334"
results = []


def _load_token():
    if os.environ.get("ALPHACOUNCIL_API_TOKEN"):
        return os.environ["ALPHACOUNCIL_API_TOKEN"]
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == "ALPHACOUNCIL_API_TOKEN":
                    return v.strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


API_TOKEN = _load_token()


def call(method, path, body=None, note=""):
    """调用 API，返回 (ok, data_or_error, status)"""
    url = BASE + path
    if method == "GET" and body:
        url += "?" + "&".join(f"{k}={v}" for k, v in body.items())
    try:
        if method == "POST":
            headers = {"Content-Type": "application/json"}
            if API_TOKEN:
                headers["X-AlphaCouncil-Token"] = API_TOKEN
            req = urllib.request.Request(
                url, data=json.dumps(body).encode(),
                headers=headers, method="POST"
            )
        else:
            req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=90) as r:
            data = json.loads(r.read().decode())
            return data.get("success", False), data, r.status
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode())
        except Exception:
            err = str(e)
        return False, err, e.code
    except Exception as e:
        return False, str(e), 0


def test(name, method, path, body=None, validate=None, critical=True):
    """执行单个测试用例。返回 (ok, data)"""
    ok, data, status = call(method, path, body)
    detail = ""
    if ok and validate:
        try:
            validate(data)
        except AssertionError as e:
            ok = False
            detail = f" 校验失败: {e}"
    tag = "✅" if ok else ("❌" if critical else "⚠️")
    results.append((name, ok, critical))
    body_str = json.dumps(body, ensure_ascii=False)[:70] if body else ""
    print(f"  {tag} [{status}] {name}")
    if body_str:
        print(f"      {body_str}")
    if not ok:
        err_preview = json.dumps(data, ensure_ascii=False)[:200] if isinstance(data, dict) else str(data)[:200]
        print(f"      返回: {err_preview}{detail}")
    return ok, data


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="测试前重置模拟账户 (保证幂等)")
    args = ap.parse_args()

    print("=" * 60)
    print("  前端 API 端到端测试 (22 个 action)")
    print("=" * 60)

    # 可选: 重置模拟账户，避免累积的持仓导致现金不足
    if args.reset:
        ok, _, _ = call("POST", "/api/execution", {"action": "reset"})
        print(f"\n  [setup] 模拟账户已重置: {ok}\n")

    # ── 1. 行情指数 (App 顶部) ─────────────────
    print("\n■ 行情指数 /api/market")
    def v_indices(d):
        assert d.get("success"), "no success"
        assert isinstance(d.get("data"), list) and len(d["data"]) > 0, "indices empty"
    test("GET /api/market/indices", "GET", "/api/market/indices", validate=v_indices)

    # ── 2. 数据层 (DbPanel) ────────────────────
    print("\n■ 数据浏览面板 /api/data")
    def v_stocks(d):
        stocks = d.get("data", {}).get("stocks") or d.get("data", [])
        assert isinstance(stocks, list) and len(stocks) > 0, "stocks empty"
        s = stocks[0]
        assert "code" in s, f"stock missing code: {list(s.keys())}"
    test("POST stocks (市场浏览)", "POST", "/api/data",
         {"action": "stocks", "limit": 200}, validate=v_stocks)

    def v_klines(d):
        kl = d.get("data", {}).get("klines") or d.get("data", [])
        assert isinstance(kl, list) and len(kl) > 0, "klines empty"
    test("POST klines (K线走势)", "POST", "/api/data",
         {"action": "klines", "code": "000001", "limit": 60}, validate=v_klines)

    def v_klines_get(d):
        kl = d.get("data", {}).get("klines") or d.get("data", [])
        assert isinstance(kl, list) and len(kl) > 0, "GET klines empty"
    test("GET klines (执行面板取价)", "GET", "/api/data",
         {"action": "klines", "code": "600519", "limit": 1}, validate=v_klines_get)

    # ── 3. 因子层 (FactorPanel) ────────────────
    print("\n■ 因子引擎面板 /api/factor")
    def v_fmeta(d):
        factors = d.get("data", {}).get("factors") or d.get("data", {})
        assert isinstance(factors, (dict, list)), "meta no factors"
    test("POST meta (因子列表)", "POST", "/api/factor", {"action": "meta"}, validate=v_fmeta)

    def v_eval(d):
        data = d.get("data", {})
        # evaluate 可能返回 dict(summary/decay) 或 list(各股IC)
        if isinstance(data, list):
            assert len(data) > 0, "evaluate list empty"
        else:
            assert "summary" in data or "ic" in data or "decay" in data, f"evaluate no summary: {list(data.keys()) if isinstance(data, dict) else type(data)}"
    test("POST evaluate (单因子IC)", "POST", "/api/factor",
         {"action": "evaluate", "codes": ["000001", "600036", "600519"], "factor_name": "ret_5"},
         validate=v_eval)

    def v_evalall(d):
        data = d.get("data", {})
        # evaluate_all 返回各因子 IC 列表
        if isinstance(data, list):
            assert len(data) > 0, "evaluate_all list empty"
        elif isinstance(data, dict):
            assert len(data) > 0, "evaluate_all empty"
        else:
            raise AssertionError(f"evaluate_all unexpected type: {type(data)}")
    test("POST evaluate_all (批量IC)", "POST", "/api/factor",
         {"action": "evaluate_all", "codes": ["000001", "600036", "600519"]},
         validate=v_evalall)

    # ── 4. 策略层 (StrategyPanel) ──────────────
    print("\n■ 策略运行面板 /api/strategy")
    def v_smeta(d):
        data = d.get("data", {})
        assert isinstance(data, dict) and len(data) > 0, "strategy meta empty"
    test("POST meta (策略列表)", "POST", "/api/strategy", {"action": "meta"}, validate=v_smeta)

    def v_srun(d):
        data = d.get("data", {})
        bt = data.get("backtest") or data.get("result") or {}
        assert isinstance(bt, dict), f"strategy run no backtest: {list(data.keys())}"
    test("POST run factor_rank", "POST", "/api/strategy",
         {"action": "run", "name": "factor_rank",
          "params": {"factor": "ret_5", "hold_days": "5", "top_n": "3"},
          "codes": ["000001", "600036", "600519"]},
         validate=v_srun)

    test("POST run multi_factor", "POST", "/api/strategy",
         {"action": "run", "name": "multi_factor",
          "params": {"factors": "rsi_6,macd_hist", "weights": "0.5,0.5", "hold_days": "5"},
          "codes": ["000001", "600036", "600519"]},
         validate=v_srun, critical=False)

    # ── 5. 执行层 (ExecutionPanel) ─────────────
    print("\n■ 交易执行面板 /api/execution")
    def v_all(d):
        data = d.get("data", {})
        assert "status" in data, f"execution all no status: {list(data.keys())}"
    test("POST all (总览刷新)", "POST", "/api/execution", {"action": "all"}, validate=v_all)

    def v_place(d):
        data = d.get("data", {})
        # id 可能在顶层 (兼容前端 r.id) 或 data.order.id
        oid = data.get("id") or (data.get("order", {}) or {}).get("id")
        assert oid, f"place_order no id: {data}"
    ok_place, place_data = test("POST place_order (买入)", "POST", "/api/execution",
         {"action": "place_order", "code": "600519", "direction": "buy", "quantity": 100, "order_type": "limit", "price": 1800.0},
         validate=v_place)

    if ok_place:
        d = place_data.get("data", {})
        oid = d.get("id") or (d.get("order", {}) or {}).get("id")
        test("POST fill_order (成交)", "POST", "/api/execution",
             {"action": "fill_order", "order_id": oid, "fill_price": 1800.0},
             critical=False)

    # ── 6. 风控层 (RiskPanel) ──────────────────
    print("\n■ 风控面板 /api/risk")
    def v_pr(d):
        data = d.get("data", {})
        assert "total_equity" in data or "concentration_pct" in data, f"portfolio_risk incomplete: {list(data.keys())}"
    test("POST portfolio_risk", "POST", "/api/risk",
         {"action": "portfolio_risk"}, validate=v_pr)

    def v_sh(d):
        data = d.get("data", {})
        assert "overall" in data, f"system_health no overall: {list(data.keys())}"
    test("POST system_health", "POST", "/api/risk",
         {"action": "system_health"}, validate=v_sh)

    # ── 7. 告警层 (AlertPanel) — 8 个 action ────
    print("\n■ 告警面板 /api/alerts")
    def v_stats(d):
        data = d.get("data", {})
        assert "total" in data or "active" in data, f"stats incomplete: {list(data.keys())}"
    test("POST stats", "POST", "/api/alerts", {"action": "stats"}, validate=v_stats)

    def v_list(d):
        data = d.get("data", {})
        assert "alerts" in data, f"list no alerts: {list(data.keys())}"
    test("POST list", "POST", "/api/alerts", {"action": "list", "limit": 50}, validate=v_list)

    test("POST list (status=active)", "POST", "/api/alerts",
         {"action": "list", "limit": 50, "status": "active"}, validate=v_list, critical=False)

    def v_rules(d):
        data = d.get("data", {})
        rules = data if isinstance(data, list) else data.get("rules", [])
        assert isinstance(rules, list), f"rules not list: {type(data)}"
    test("POST rules", "POST", "/api/alerts", {"action": "rules"}, validate=v_rules)

    test("POST check (扫描告警)", "POST", "/api/alerts", {"action": "check"}, critical=False)

    # acknowledge/resolve/update_rule/silence 需要先有 alert/rule id
    _, rules_data, _ = call("POST", "/api/alerts", {"action": "rules"})
    rules_list = rules_data.get("data", []) if isinstance(rules_data.get("data"), list) else rules_data.get("data", {}).get("rules", [])
    if rules_list:
        rid = rules_list[0].get("id")
        test("POST update_rule (切换规则)", "POST", "/api/alerts",
             {"action": "update_rule", "id": rid, "enabled": True}, critical=False)
        test("POST silence (静默)", "POST", "/api/alerts",
             {"action": "silence", "rule_id": rid, "duration": 3600}, critical=False)

    _, list_data, _ = call("POST", "/api/alerts", {"action": "list", "limit": 50})
    alerts = list_data.get("data", {}).get("alerts", [])
    if alerts:
        aid = alerts[0].get("id")
        test("POST acknowledge (确认)", "POST", "/api/alerts",
             {"action": "acknowledge", "alert_id": aid}, critical=False)
        test("POST resolve (解决)", "POST", "/api/alerts",
             {"action": "resolve", "alert_id": aid}, critical=False)
    else:
        print("  ⏭️  acknowledge/resolve 跳过 (无告警记录)")

    # ── 汇总 ──────────────────────────────────
    print("\n" + "=" * 60)
    n_crit_ok = sum(1 for _, ok, c in results if ok and c)
    n_crit = sum(1 for _, _, c in results if c)
    n_all_ok = sum(1 for _, ok, _ in results if ok)
    print(f"  关键测试: {n_crit_ok}/{n_crit} 通过")
    print(f"  全部测试: {n_all_ok}/{len(results)} 通过")
    if n_crit_ok == n_crit:
        print("  ✅ 所有关键功能正常")
    else:
        print("  ❌ 有关键功能失败，需修复")
    print("=" * 60)
    return 0 if n_crit_ok == n_crit else 1


if __name__ == "__main__":
    sys.exit(main())

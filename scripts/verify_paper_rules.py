"""专项验证: A股模拟执行规则 + 回测清仓信号。

不访问外部数据源，不清空生产数据库。通过 monkeypatch 使用内存态验证核心规则。
运行: python scripts/verify_paper_rules.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scripts.execution_runner as ex
from quant.backtest.engine import BacktestSimulator
import pandas as pd


def assert_true(cond, msg):
    if not cond:
        raise AssertionError(msg)


def fresh_state():
    return {
        "initial_capital": 1_000_000.0,
        "cash": 1_000_000.0,
        "positions": {},
        "orders": [],
        "trades": [],
        "order_counter": 0,
        "trade_counter": 0,
    }


def verify_execution_rules():
    state = fresh_state()
    saved = []

    ex._save_state = lambda s: saved.append(dict(s))
    ex._load_stops = lambda: {}
    ex._save_stops = lambda stops: None
    ex.fetch_live_price = lambda code: 10.0
    ex._kline_price = lambda code: 10.0
    ex._latest_bar_info = lambda code: {}

    bad = {"id": "O1", "code": "000001", "direction": "buy", "quantity": 50, "status": "pending", "filled_qty": 0}
    state["orders"].append(bad)
    r = ex._auto_fill_market_order(bad, state)
    assert_true(not r["success"] and r["reason"] == "not_board_lot", "非整手买入应拒单")

    buy = {"id": "O2", "code": "000001", "direction": "buy", "quantity": 100, "status": "pending", "filled_qty": 0}
    state["orders"].append(buy)
    r = ex._auto_fill_market_order(buy, state)
    assert_true(r["success"], "合法买入应成交")
    assert_true(state["positions"]["000001"]["quantity"] == 100, "买入后持仓数量错误")
    assert_true(state["positions"]["000001"].get("available_qty") == 0, "当日买入应不可卖")

    sell = {"id": "O3", "code": "000001", "direction": "sell", "quantity": 100, "status": "pending", "filled_qty": 0}
    state["orders"].append(sell)
    r = ex._auto_fill_market_order(sell, state)
    assert_true(not r["success"] and r["reason"] == "t1_restricted", "当日卖出应触发T+1限制")

    state["positions"]["000001"]["entry_date"] = "2000-01-01"
    state["positions"]["000001"]["available_qty"] = 100
    sell2 = {"id": "O4", "code": "000001", "direction": "sell", "quantity": 100, "status": "pending", "filled_qty": 0}
    state["orders"].append(sell2)
    r = ex._auto_fill_market_order(sell2, state)
    assert_true(r["success"], "隔日可卖持仓应成交")
    assert_true("000001" not in state["positions"], "清仓后持仓应删除")


def verify_backtest_flatten():
    df = pd.DataFrame([
        {"date": "20240102", "open": 10, "high": 10.5, "low": 9.8, "close": 10, "volume": 1000000, "amount": 10000000},
        {"date": "20240103", "open": 10.2, "high": 10.6, "low": 10.0, "close": 10.4, "volume": 1000000, "amount": 10400000},
        {"date": "20240104", "open": 10.3, "high": 10.7, "low": 10.1, "close": 10.5, "volume": 1000000, "amount": 10500000},
    ])
    sim = BacktestSimulator(initial_cash=100000, enforce_limit=False)
    sim.add_klines({"000001": df})
    sim.add_signals({"000001": [{"date": "20240102", "signal": 1}, {"date": "20240103", "signal": 0}]})
    result = sim.run()
    sells = [f for f in result["fills"] if f["direction"] == "sell"]
    assert_true(len(sells) >= 1, "signal=0 应触发清仓卖出")


def verify_fees():
    """验证 A 股费用模型：买入只有佣金(最低5元)，卖出有佣金+印花税。"""
    fees_buy = ex._calc_fees("buy", 1000.0)
    assert_true(fees_buy["commission"] == 5.0, "1000元买入佣金应为最低5元")
    assert_true(fees_buy["stamp_tax"] == 0.0, "买入无印花税")

    fees_sell = ex._calc_fees("sell", 100000.0)
    assert_true(fees_sell["commission"] == 30.0, "10万元买入佣金应为30元")
    assert_true(fees_sell["stamp_tax"] == 50.0, "10万元卖出印花税应为50元")
    assert_true(fees_sell["total_fee"] == fees_sell["commission"] + fees_sell["stamp_tax"] + fees_sell["transfer_fee"],
                "费用总额应等于各项之和")


def verify_report():
    """验证每日日报能生成且包含关键字段。"""
    from scripts.daily_report import generate_report
    report = generate_report()
    assert_true("account" in report, "日报应包含 account")
    assert_true("benchmark" in report, "日报应包含 benchmark")
    assert_true("data" in report, "日报应包含 data")
    assert_true("positions" in report, "日报应包含 positions")
    assert_true(report["report_date"], "日报应有日期")


def verify_data_stale_alert():
    """验证 data_stale 告警规则能正常执行。"""
    import scripts.alert_runner as ar
    result = ar._eval_data_stale({"threshold": 0})
    assert_true(isinstance(result, list), "data_stale 评估应返回列表")


def verify_calendar():
    """验证交易日历能从已有K线推导并查询。"""
    from scripts.trading_calendar import build_trading_calendar, is_trade_date, prev_trade_date, calendar_info
    dates = build_trading_calendar()
    assert_true(isinstance(dates, list), "交易日历应返回列表")
    info = calendar_info()
    assert_true(info["total"] > 0 or len(dates) > 0, "交易日历应有数据或可构建")


def verify_benchmark_metrics():
    """验证回测能输出基准对比字段。"""
    df = pd.DataFrame([
        {"date": "20240102", "open": 10, "high": 10.5, "low": 9.8, "close": 10, "volume": 1000000, "amount": 10000000},
        {"date": "20240103", "open": 10.2, "high": 10.6, "low": 10.0, "close": 10.4, "volume": 1000000, "amount": 10400000},
        {"date": "20240104", "open": 10.3, "high": 10.7, "low": 10.1, "close": 10.5, "volume": 1000000, "amount": 10500000},
    ])
    sim = BacktestSimulator(initial_cash=100000, enforce_limit=False)
    sim.add_klines({"000001": df})
    sim.add_signals({"000001": [{"date": "20240102", "signal": 1}]})
    result = sim.run()
    bm = result["metrics"].get("benchmark")
    assert_true(bm is not None and "total_return_pct" in bm, "回测应输出基准对比字段")
    assert_true("excess_return_pct" in bm, "基准对比应包含超额收益")


def verify_llm_client():
    """验证 LLM 客户端: JSON 解析、无 key 降级、超时降级。全程 mock, 不真调 API。"""
    import scripts.llm_client as lc
    import json as _json

    # ── 1. _extract_json 解析逻辑 ──────────────────────────
    # 裸 JSON
    d = lc._extract_json('{"a": 1, "b": 2}')
    assert_true(d is not None and d["a"] == 1, "裸 JSON 应正确解析")

    # ```json 代码块
    d = lc._extract_json('以下是结果:\n```json\n{"status": "ok", "n": 3}\n```\n完毕')
    assert_true(d is not None and d["status"] == "ok", "```json 代码块应正确解析")

    # 带前后文字的裸 JSON
    d = lc._extract_json('好的，这是我的决策 {"action": "buy", "code": "600519"} 谢谢')
    assert_true(d is not None and d["code"] == "600519", "夹在文字中的 JSON 应提取成功")

    # 无效输入
    assert_true(lc._extract_json("没有JSON的纯文本") is None, "无 JSON 文本应返回 None")
    assert_true(lc._extract_json("") is None, "空字符串应返回 None")

    # ── 2. 无 key 时 chat() 应返回 success=False ───────────
    # 临时清除 key, 确保不真调 API
    orig = os.environ.pop("DEEPSEEK_API_KEY", None)
    lc._env_loaded = True  # 防止重新加载 .env
    try:
        r = lc.chat("deepseek", "test", "test")
        assert_true(not r["success"], "无 API Key 时 chat 应返回 success=False")
        assert_true("DEEPSEEK_API_KEY" in r["error"], "错误信息应提示缺少 key")
    finally:
        if orig:
            os.environ["DEEPSEEK_API_KEY"] = orig
        lc._env_loaded = False  # 恢复, 让后续测试能正常加载

    # ── 3. 未知供应商 ──────────────────────────────────────
    r = lc.chat("unknown_provider", "test", "test")
    assert_true(not r["success"] and "未知供应商" in r["error"], "未知供应商应返回错误")

    # ── 4. mock urlopen 模拟成功响应 + chat_json 解析 ──────
    import urllib.request
    mock_response_body = _json.dumps({
        "choices": [{"message": {"content": '```json\n{"decisions": [{"code": "600519", "action": "hold"}]}\n```'}}]
    }).encode("utf-8")

    class _MockResp:
        def __init__(self, body):
            self._body = body
        def read(self):
            return self._body
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    orig_urlopen = urllib.request.urlopen
    os.environ["DEEPSEEK_API_KEY"] = "sk-test-mock-key"
    lc._env_loaded = True
    try:
        urllib.request.urlopen = lambda req, timeout=25: _MockResp(mock_response_body)
        r = lc.chat_json("deepseek", "你是交易助手", "请给出决策")
        assert_true(r["success"], "mock urlopen 时 chat_json 应成功")
        assert_true("decisions" in r["data"], "chat_json 应解析出 decisions 字段")
        assert_true(r["data"]["decisions"][0]["code"] == "600519", "应正确解析决策内容")
    finally:
        urllib.request.urlopen = orig_urlopen
        os.environ.pop("DEEPSEEK_API_KEY", None)
        lc._env_loaded = False

    # ── 5. mock urlopen 抛异常 → 降级 ─────────────────────
    orig_urlopen = urllib.request.urlopen
    os.environ["DEEPSEEK_API_KEY"] = "sk-test-mock-key"
    lc._env_loaded = True
    try:
        def _boom(req, timeout=25):
            raise TimeoutError("模拟超时")
        urllib.request.urlopen = _boom
        r = lc.chat("deepseek", "test", "test")
        assert_true(not r["success"], "网络异常时 chat 应返回 success=False")
        assert_true("超时" in r["error"], "错误信息应包含超时原因")
    finally:
        urllib.request.urlopen = orig_urlopen
        os.environ.pop("DEEPSEEK_API_KEY", None)
        lc._env_loaded = False


def verify_alert_ai_hint():
    """验证告警的 AI 解读: 启用时加 ai_hint, 未启用时正常工作。"""
    import scripts.alert_runner as ar

    # _interpret_alert 在 LLM 未启用时应返回空字符串 (不崩溃)
    hint = ar._interpret_alert({"title": "测试告警", "message": "数据过期", "level": "critical"})
    assert_true(isinstance(hint, str), "_interpret_alert 应返回字符串")

    # mock chat 返回文本, 验证 _interpret_alert 能提取
    orig_chat = None
    try:
        from scripts import llm_client as lc
        orig_chat = lc.chat
        lc.chat = lambda provider, system, user, **kw: {"success": True, "text": "数据源连接异常,建议检查网络后重试更新。"}
        # 临时启用 LLM 配置
        ar.cache.set("paper:config", {"llm": {"enabled": True, "provider": "deepseek", "interpret_alerts": True, "timeout": 5}})
        hint2 = ar._interpret_alert({"title": "行情数据过期", "message": "K线数据落后3天", "level": "critical"})
        assert_true("数据源" in hint2 or len(hint2) > 0, "mock chat 后 _interpret_alert 应返回解读文本")
    finally:
        if orig_chat:
            lc.chat = orig_chat
        ar.cache.set("paper:config", {"llm": {"enabled": False}})

    # _emit 对 warning/critical 告警应含 ai_hint 字段
    record = ar._emit({"title": "验证告警", "message": "测试用", "level": "warning", "rule_id": "test"})
    assert_true("ai_hint" in record, "_emit 对 warning 告警应含 ai_hint 字段")

    # info 级别不应有 ai_hint
    record_info = ar._emit({"title": "信息", "message": "info", "level": "info"})
    assert_true("ai_hint" not in record_info, "info 级告警不应触发 AI 解读")


def verify_llm_trading_decisions():
    """验证 LLM 决策增强层: review 模式否决、decide 模式合并、失败降级、风控硬约束。"""
    import scripts.paper_trader as pt

    cfg = {
        "risk": {"max_position_pct": 0.2, "max_gross_exposure_pct": 95,
                 "max_position_count": 10, "max_orders_per_run": 20,
                 "min_cash_buffer_pct": 2, "allow_buy_st": False},
        "llm": {"enabled": True, "provider": "deepseek", "mode": "review",
                "timeout": 5, "max_new_positions": 3, "confidence_threshold": 0.6},
        "max_positions": 5, "position_size_pct": 0.2,
    }
    latest = {
        "600519": (1, 0.82),
        "000858": (1, 0.45),
        "600036": (0, -0.3),
    }

    # ── 1. review 模式: LLM 高置信度 reject 600519 → 应被移除 ──
    desired = ["600519", "000858"]
    llm_ok = {"success": True, "mode": "review", "provider": "deepseek",
              "decisions": [
                  {"code": "600519", "action": "reject", "confidence": 0.85, "reason": "估值过高"},
                  {"code": "000858", "action": "hold", "confidence": 0.7},
              ]}
    result = pt._apply_llm_decisions(desired, latest, llm_ok, cfg)
    assert_true("600519" not in result, "review 模式高置信度 reject 应移除该股")
    assert_true("000858" in result, "review 模式未 reject 的应保留")

    # ── 2. review 模式: 低置信度 reject 不生效 ──────────────
    llm_low = {"success": True, "mode": "review", "decisions": [
        {"code": "600519", "action": "reject", "confidence": 0.3}]}
    result2 = pt._apply_llm_decisions(["600519", "000858"], latest, llm_low, cfg)
    assert_true("600519" in result2, "review 模式低置信度 reject 不应移除")

    # ── 3. decide 模式: LLM buy 建议合并到 desired_long ─────
    cfg_decide = dict(cfg)
    cfg_decide["llm"] = {**cfg["llm"], "mode": "decide"}
    llm_decide = {"success": True, "mode": "decide", "decisions": [
        {"code": "600036", "action": "buy", "confidence": 0.75},
        {"code": "000333", "action": "buy", "confidence": 0.65},
        {"code": "000858", "action": "sell", "confidence": 0.8},
    ]}
    result3 = pt._apply_llm_decisions(["600519", "000858"], latest, llm_decide, cfg_decide)
    assert_true("600036" in result3, "decide 模式 LLM buy 建议应加入")
    assert_true("000858" not in result3, "decide 模式 LLM sell 建议应移除")
    assert_true("600519" in result3, "decide 模式未被 sell 的量化信号应保留")

    # ── 4. decide 模式: max_new_positions 限制 ──────────────
    llm_many = {"success": True, "mode": "decide", "decisions": [
        {"code": "600036", "action": "buy", "confidence": 0.9},
        {"code": "000333", "action": "buy", "confidence": 0.8},
        {"code": "601318", "action": "buy", "confidence": 0.7},
        {"code": "000001", "action": "buy", "confidence": 0.65},
        {"code": "600000", "action": "buy", "confidence": 0.62},
    ]}
    result4 = pt._apply_llm_decisions([], latest, llm_many, cfg_decide)
    assert_true(len(result4) <= 3, f"decide 模式新增不应超过 max_new_positions=3, got {len(result4)}")

    # ── 5. LLM 失败 → _summarize_llm 标记 inactive ─────────
    s = pt._summarize_llm(None, {"enabled": True, "mode": "review"})
    assert_true(s["active"] is False, "LLM 失败时 summary 应标记 inactive")
    s2 = pt._summarize_llm(llm_ok, {"enabled": True, "mode": "review"})
    assert_true(s2["active"] is True and s2["decisions_count"] == 2, "LLM 成功时 summary 应记录决策数")


def verify_ai_contract_and_gateway():
    """验证标准 AI 决策协议和独立风控网关。"""
    from datetime import datetime, timedelta
    from quant.ai.contracts import DecisionValidationError, validate_ai_decision
    from quant.risk.gateway import check_order

    valid = {
        "trade_policy": "normal",
        "trade_allowed": True,
        "target_weights": [{"code": "600519", "target_weight": 0.1, "confidence": 0.8}],
        "rebalance_plan": [{"code": "600519", "action": "buy", "target_weight": 0.1}],
        "risk_budget": {
            "max_position_pct": 0.2,
            "max_gross_exposure_pct": 95,
            "max_position_count": 10,
            "max_daily_turnover_pct": 35,
        },
        "confidence": 0.8,
        "valid_until": (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
        "model_version": "test-model",
        "prompt_version": "test.v1",
        "reason_codes": ["unit_test"],
    }
    normalized = validate_ai_decision(valid)
    assert_true(normalized["schema_version"] == "ai_decision.v1", "决策协议应补 schema_version")
    try:
        bad = dict(valid)
        bad.pop("valid_until")
        validate_ai_decision(bad)
        raise AssertionError("缺少 required field 应拒绝")
    except DecisionValidationError:
        pass

    portfolio = {"cash": 100000, "total_equity": 100000, "positions": {}}
    cfg = {"risk": {"max_position_pct": 0.2, "max_gross_exposure_pct": 95,
                    "max_position_count": 10, "min_cash_buffer_pct": 2}}
    ok = check_order({"code": "600519", "direction": "buy", "quantity": 100,
                      "price": 100, "decision": normalized}, portfolio, {}, cfg)
    assert_true(ok["approved"], "合规订单应通过风控网关")
    reject = check_order({"code": "600519", "direction": "buy", "quantity": 50,
                          "price": 100, "decision": normalized}, portfolio, {}, cfg)
    assert_true(not reject["approved"] and "not_board_lot" in reject["reasons"], "非整手买入应被网关拒绝")
    fuse = check_order({"code": "600519", "direction": "buy", "quantity": 100,
                        "price": 100, "decision": normalized},
                       {**portfolio, "daily_pnl": -6000},
                       {}, {"risk": {**cfg["risk"], "max_daily_loss_pct": 5}})
    assert_true(not fuse["approved"] and "daily_loss_fuse" in fuse["reasons"], "daily loss fuse should block")
    t1 = check_order({"code": "600519", "direction": "sell", "quantity": 200,
                      "price": 100, "decision": normalized},
                     {"cash": 0, "total_equity": 100000, "positions": {"600519": {"quantity": 300, "available_qty": 100, "avg_price": 90}}},
                     {}, cfg)
    assert_true(not t1["approved"] and "t1_available_qty" in t1["reasons"], "T+1 available qty should block sell")
    limit_up = check_order({"code": "600519", "direction": "buy", "quantity": 100,
                            "price": 100, "decision": normalized}, portfolio,
                           {"limit_state": "up"}, cfg)
    assert_true(not limit_up["approved"] and "limit_up_blocked" in limit_up["reasons"], "limit-up buy should block by default")


def verify_structured_audit_and_live_guard():
    """验证结构化审计表和实盘默认保护边界。"""
    from quant.data.cache import create_cache
    from quant.data.audit import ensure_audit_schema, write_audit_event, write_order_event, write_risk_event, get_audit_replay
    from quant.execution.broker import LiveBrokerAdapter

    cache = create_cache()
    assert_true(ensure_audit_schema(cache), "SQLite 审计 schema 应创建成功")
    conn = getattr(cache, "_conn", None)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    for t in ("ai_decisions", "orders", "trades", "positions_snapshots", "risk_events", "model_calls", "audit_events"):
        assert_true(t in tables, f"缺少结构化审计表: {t}")
    run_id = "unit-run-001"
    decision_id = "unit-decision-001"
    write_audit_event(cache, "paper_run", {"run_id": run_id, "decision_id": decision_id}, source="unit")
    write_risk_event(cache, {"run_id": run_id, "decision_id": decision_id, "code": "600519", "direction": "buy", "reason": "unit", "approved": False})
    write_order_event(cache, {"run_id": run_id, "decision_id": decision_id, "order_id": "O-unit", "code": "600519", "direction": "buy", "quantity": 100, "status": "rejected"})
    replay = get_audit_replay(cache, run_id=run_id, decision_id=decision_id)
    assert_true(replay["success"] and replay["risk_events"] and replay["orders"], "audit replay should join run records")

    live = LiveBrokerAdapter()
    r = live.submit_order({"code": "600519", "direction": "buy", "quantity": 100})
    assert_true(not r["success"] and r["mode"] == "manual_approve_required", "实盘适配器默认必须禁止自动下单")


def verify_promotion_and_shadow_signals():
    """验证晋升连续窗口和新闻/宏观 shadow-only 信号。"""
    from quant.ai.promotion import apply_promotion_state
    from quant.ai.shadow_signals import build_shadow_signals
    from quant.data.cache import MemoryCache

    c = MemoryCache()
    entry = {"name": "f1", "eval": {"passed": True, "best_abs_ic": 0.04, "best_ir": 0.4, "n_records": 120}}
    states = [apply_promotion_state("factor", entry, c)["promotion_state"] for _ in range(3)]
    assert_true(states[0] == "shadow" and states[-1] == "paper_active", "promotion should require consecutive passes")
    strong = {"name": "f1", "eval": {"passed": True, "best_abs_ic": 0.07, "best_ir": 0.7, "n_records": 240}}
    states2 = [apply_promotion_state("factor", strong, c)["promotion_state"] for _ in range(5)]
    assert_true(states2[-1] == "production_candidate", "production candidate should require strong streak")
    shadow = build_shadow_signals(c, source="unit")
    assert_true(shadow["mode"] == "shadow_only" and not shadow["can_trigger_order"], "shadow signals must not trade")


def main():
    verify_execution_rules()
    verify_fees()
    verify_backtest_flatten()
    verify_report()
    verify_data_stale_alert()
    verify_calendar()
    verify_benchmark_metrics()
    verify_llm_client()
    verify_llm_trading_decisions()
    verify_ai_contract_and_gateway()
    verify_structured_audit_and_live_guard()
    verify_promotion_and_shadow_signals()
    verify_alert_ai_hint()
    print("OK verify_paper_rules")


if __name__ == "__main__":
    main()

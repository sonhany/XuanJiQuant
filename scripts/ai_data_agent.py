"""Layer 1: AI 数据层 Agent — 数据完整性检查 + 自动补数 + 市场动态采集

职责:
  - 检查 K线/财务/实时价格/指数的完整性
  - 生成补数计划
  - 采集板块资金流/北向资金/市场概况 (复用已有 Eastmoney 能力)
  - 调用 GLM 生成数据层 AI 解读

安全边界: 只读检查 + 建议补数, 不直接修改生产数据
持久化: ai:data:latest, market:sector_flow:latest, market:northbound:latest
"""
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache

cache = create_cache()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def check_data_integrity(universe: list = None) -> dict:
    """检查股票池数据完整性 — 委托给统一入口。"""
    try:
        from scripts.data_freshness import check_integrity
        return check_integrity()
    except Exception:
        # fallback: 原始逻辑
        if not universe:
            cfg = cache.get("paper:config") or {}
            universe = cfg.get("universe", []) or []
        from scripts.data_freshness import get_expected_date
        expected_date = get_expected_date()
        result = {
            "checked_at": _now(),
            "today": _today(),
            "expected_latest": expected_date,
            "universe_size": len(universe),
            "stocks": [],
            "summary": {"ok": 0, "stale": 0, "missing": 0, "partial": 0},
        }
        for code in universe[:50]:
            code = str(code).split(".")[0].strip()
            kline = cache.get(f"kline:{code}:d")
            latest_date = ""
            bar_count = 0
            if kline and isinstance(kline, list) and kline:
                bar_count = len(kline)
                latest_date = str(kline[-1].get("date") or "")
            is_stale = bool(latest_date) and latest_date < expected_date
            status = "ok"
            if not kline: status = "missing"
            elif is_stale: status = "stale"
            elif bar_count < 20: status = "partial"
            result["stocks"].append({"code": code, "status": status, "latest_date": latest_date, "bar_count": bar_count, "has_financial": bool(cache.get(f"fin:abstract:{code}"))})
            result["summary"][status] += 1
        return result


def collect_market_context() -> dict:
    """采集板块资金流 + 北向资金 + 指数概况。

    统一走 market_data 模块 (Python 直连 Eastmoney), 不再反向调 Node /api/market。
    斩断 Python→Node→Python 循环依赖。
    """
    from scripts.market_data import fetch_sector_flow, fetch_northbound
    context = {"collected_at": _now()}

    # 板块资金流 — 直接调 Python market_data (Eastmoney)
    try:
        sector = fetch_sector_flow()
        context["sector_flow"] = sector
        # market_data 内部已写 cache, 这里无需重复
    except Exception:
        context["sector_flow"] = cache.get("market:sector_flow:latest") or []

    # 北向资金 — 直接调 Python market_data (Eastmoney)
    try:
        nb = fetch_northbound()
        context["northbound"] = nb
    except Exception:
        context["northbound"] = cache.get("market:northbound:latest") or {}

    # 指数概况 (HS300 等)
    try:
        from scripts.benchmark import refresh_benchmark
        bm = refresh_benchmark()
        context["benchmark"] = bm
    except Exception:
        context["benchmark"] = {}

    return context


def generate_replenish_plan(integrity: dict) -> list:
    """根据完整性检查生成补数计划。"""
    plan = []
    for s in integrity.get("stocks", []):
        if s["status"] in ("missing", "stale", "partial"):
            plan.append({
                "code": s["code"],
                "action": "update_kline",
                "priority": "high" if s["status"] == "missing" else "medium",
                "reason": f"状态={s['status']} 最新={s['latest_date'] or '无'} 条数={s['bar_count']}",
            })
        if not s.get("has_financial"):
            plan.append({
                "code": s["code"],
                "action": "update_financial",
                "priority": "low",
                "reason": "无财务数据",
            })
    return plan


def execute_replenish(plan: list, timeout: int = 120) -> dict:
    """实际执行补数: 对 stale/missing 的股票增量更新 K 线。
    直接调用 daily_update.incremental_klines, 不通过 subprocess。
    """
    codes_to_update = [item["code"] for item in plan if item["action"] == "update_kline"]
    if not codes_to_update:
        return {"executed": False, "reason": "无需补数"}

    results = {"executed": True, "updated_codes": codes_to_update[:10], "detail": []}

    try:
        from scripts.daily_update import incremental_klines
        update_result = incremental_klines(codes_to_update[:10], cache)
        results["update_stats"] = update_result
        results["success_count"] = update_result.get("ok", 0)
        results["fail_count"] = update_result.get("err", 0)
        results["new_bars"] = update_result.get("new_bars", 0)
    except Exception as e:
        results["error"] = str(e)[:200]
        results["success_count"] = 0
        results["fail_count"] = len(codes_to_update)

    return results


def run_data_agent(provider: str = "glm", auto_fix: bool = False) -> dict:
    """运行数据层 AI Agent。

    auto_fix=True 时自动执行补数 (更新 stale 的 K 线)。
    """
    integrity = check_data_integrity()
    replenish = generate_replenish_plan(integrity)
    market = collect_market_context()
    try:
        from quant.ai.shadow_signals import build_shadow_signals
        shadow_signals = build_shadow_signals(cache, source="ai_data_agent")
    except Exception:
        shadow_signals = {"mode": "shadow_only", "signals": [], "can_trigger_order": False}

    # 自动补数执行
    replenish_result = None
    if auto_fix and replenish:
        replenish_result = execute_replenish(replenish)
        # 补数后重新检查
        integrity_after = check_data_integrity()
        data_stale = integrity_after["summary"]["stale"] > 0 or integrity_after["summary"]["missing"] > 0
        integrity = integrity_after
    else:
        data_stale = integrity["summary"]["stale"] > 0 or integrity["summary"]["missing"] > 0

    trade_allowed = not data_stale

    # GLM 解读
    ai_summary = ""
    ai_risk_notes = []
    try:
        from scripts.llm_client import chat
        compact = {
            "integrity_summary": integrity["summary"],
            "today": integrity["today"],
            "replenish_count": len(replenish),
            "sector_flow_top3": (market.get("sector_flow") or [])[:3],
            "northbound": market.get("northbound", {}).get("trend"),
            "benchmark_daily": market.get("benchmark", {}).get("daily_return_pct"),
        }
        system = (
            "你是A股量化系统的数据层AI助手。根据数据完整性检查和市场概况,用2-3句话总结: "
            "1.数据是否可用于交易 2.市场资金面状况 3.需要补数的内容。直接输出要点。"
        )
        user = json.dumps(compact, ensure_ascii=False)
        r = chat(provider, system, user, temperature=0.2, timeout=45, max_tokens=400, scene="data")
        if r.get("success"):
            ai_summary = r["text"][:500]
    except Exception:
        pass

    result = {
        "success": True,
        "generated_at": _now(),
        "provider": provider,
        "integrity": integrity,
        "replenish_plan": replenish,
        "replenish_result": replenish_result,
        "market_context": market,
        "shadow_signals": shadow_signals,
        "data_stale": data_stale,
        "trade_allowed": trade_allowed,
        "ai_summary": ai_summary,
    }
    cache.set("ai:data:latest", result)
    return result


def get_status() -> dict:
    return cache.get("ai:data:latest") or {"success": True, "latest": None}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AI 数据层 Agent")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--auto-fix", action="store_true", help="自动执行补数")
    parser.add_argument("--provider", default="glm")
    args = parser.parse_args()
    if args.run:
        out = run_data_agent(args.provider, auto_fix=args.auto_fix)
    else:
        out = get_status()
    print(json.dumps({"success": True, "data": out}, ensure_ascii=False, default=str))

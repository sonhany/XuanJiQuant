"""Daily Report — 每日模拟盘日报

生成一份结构化的当日模拟盘运行报告，包含:
  - 账户快照 (现金/持仓/总权益/当日盈亏)
  - 基准对比 (沪深300当日涨跌 + 总收益对比)
  - 持仓明细 (代码/数量/成本/现价/浮盈)
  - 今日订单 (成交/拒单)
  - 风控结果 (拒单原因)
  - 数据状态 (最新K线日期/是否过期)
  - 告警摘要 (active 数量)

报告存 SQLite KV: paper:report:<YYYYMMDD>
最新报告也存一份: paper:report:latest

用法:
  python scripts/daily_report.py            # 生成当日报告
  python scripts/daily_report.py --json     # 输出 JSON
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler(sys.stderr)])
logger = logging.getLogger("daily_report")

cache = create_cache()


def _safe_float(v, default=0.0):
    try:
        f = float(v)
        import math
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _latest_kline_date() -> str:
    """委托给统一入口 data_freshness。"""
    try:
        from scripts.data_freshness import get_latest_kline_date
        return get_latest_kline_date()
    except Exception:
        return ""


def _active_alerts_summary() -> dict:
    try:
        alerts = cache.get("alerts:records") or []
        active = [a for a in alerts if a.get("status") == "active"]
        return {
            "total": len(alerts),
            "active": len(active),
            "critical": len([a for a in active if a.get("level") == "critical"]),
        }
    except Exception:
        return {"total": 0, "active": 0, "critical": 0}


def _position_details(positions: dict) -> list:
    out = []
    for code, p in positions.items():
        qty = int(p.get("quantity", 0))
        if qty == 0:
            continue
        avg = _safe_float(p.get("avg_price"))
        cur = _safe_float(p.get("current_price"), avg)
        mv = qty * cur
        pnl = (cur - avg) * qty
        pnl_pct = (cur - avg) / avg * 100 if avg > 0 else 0
        out.append({
            "code": code,
            "quantity": qty,
            "avg_price": round(avg, 2),
            "current_price": round(cur, 2),
            "market_value": round(mv, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "available_qty": int(p.get("available_qty", qty)),
        })
    out.sort(key=lambda x: abs(x["market_value"]), reverse=True)
    return out


def generate_report() -> dict:
    """生成当日日报。不依赖外部数据源，只读已有状态。"""
    today = datetime.now().strftime("%Y-%m-%d")
    today_compact = datetime.now().strftime("%Y%m%d")

    # ── 账户快照 ──────────────────────
    exec_state = cache.get("execution:state") or {}
    init_cap = _safe_float(exec_state.get("initial_capital"), 1_000_000)
    cash = _safe_float(exec_state.get("cash"))
    positions = exec_state.get("positions", {})
    pos_list = _position_details(positions)
    total_mv = sum(p["market_value"] for p in pos_list)
    total_equity = cash + total_mv
    total_pnl = total_equity - init_cap
    total_pnl_pct = total_pnl / init_cap * 100 if init_cap else 0

    # ── 基准对比 ──────────────────────
    benchmark = {}
    try:
        from scripts.benchmark import refresh_benchmark
        bm = refresh_benchmark()
        bm_ret = bm.get("total_return_pct", 0)
        excess = total_pnl_pct - bm_ret
        benchmark = {
            "name": bm.get("name", "沪深300"),
            "code": bm.get("code", "sh000300"),
            "equity": round(bm.get("equity", init_cap), 2),
            "daily_return_pct": bm.get("daily_return_pct", 0),
            "total_return_pct": bm_ret,
            "excess_return_pct": round(excess, 4),
        }
    except Exception as e:
        logger.debug(f"benchmark refresh failed: {e}")
        benchmark = {"error": str(e)[:120]}

    # ── 今日订单/风控 ────────────────
    paper_status = cache.get("paper:status") or {}
    last_result = paper_status.get("last_result") or {}
    today_orders = last_result.get("orders", [])
    risk_rejections = last_result.get("risk_rejections", [])
    skipped_orders = last_result.get("skipped_orders", [])
    skip_reason = last_result.get("skip_reason")

    # ── 数据状态 (统一入口) ─────────────
    from scripts.data_freshness import is_data_stale, get_latest_kline_date, get_expected_date
    latest_date = get_latest_kline_date()
    expected_latest = get_expected_date()
    is_stale = is_data_stale()

    # ── 告警 ─────────────────────────
    alerts_summary = _active_alerts_summary()

    report = {
        "report_date": today,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "account": {
            "initial_capital": round(init_cap, 2),
            "cash": round(cash, 2),
            "market_value": round(total_mv, 2),
            "total_equity": round(total_equity, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl_pct, 4),
            "position_count": len(pos_list),
        },
        "benchmark": benchmark,
        "positions": pos_list,
        "today_orders": today_orders,
        "today_orders_count": len(today_orders),
        "risk_rejections": risk_rejections,
        "skipped_orders": skipped_orders,
        "paper_skip_reason": skip_reason,
        "paper_last_run": paper_status.get("last_run"),
        "paper_running": paper_status.get("running", False),
        "data": {
            "latest_kline_date": latest_date,
            "is_stale": is_stale,
            "stale_days": (int(expected_latest[:8]) - int(latest_date)) if is_stale and latest_date else 0,
        },
        "alerts": alerts_summary,
    }
    # ── AI 复盘 (可选, 失败不影响报告) ─────────────────
    report["ai_review"] = _generate_ai_review(report)
    return report


def _generate_ai_review(report: dict) -> dict:
    """调用 LLM 生成每日复盘要点。失败返回空 dict, 不影响报告主体。"""
    # 读取 LLM 配置 (从 paper:config)
    cfg = cache.get("paper:config") or {}
    llm_cfg = cfg.get("llm", {})
    if not llm_cfg.get("enabled"):
        return {"enabled": False}

    try:
        from scripts.llm_client import chat, get_provider_label
        provider = llm_cfg.get("provider", "deepseek")
        timeout = int(llm_cfg.get("timeout", 25))

        # 构建精简上下文
        acc = report.get("account", {})
        bm = report.get("benchmark", {})
        positions = report.get("positions", [])
        data = report.get("data", {})
        alerts = report.get("alerts", {})

        pos_str = "; ".join(
            f"{p['code']} {p['quantity']}股 盈亏{p['pnl_pct']:+.1f}%"
            for p in positions[:6]
        ) or "空仓"

        bm_str = "无基准"
        if bm and not bm.get("error"):
            bm_str = f"{bm.get('name','沪深300')} 当日{bm.get('daily_return_pct',0):+.2f}% 累计{bm.get('total_return_pct',0):+.2f}% 超额{bm.get('excess_return_pct',0):+.2f}%"

        context = (
            f"日期: {report.get('report_date')}\n"
            f"总权益: ¥{acc.get('total_equity',0):,.0f} | 累计盈亏: {acc.get('total_pnl_pct',0):+.2f}%\n"
            f"现金: ¥{acc.get('cash',0):,.0f} | 持仓数: {acc.get('position_count',0)}\n"
            f"持仓: {pos_str}\n"
            f"基准: {bm_str}\n"
            f"数据: 最新K线{data.get('latest_kline_date','N/A')} {'过期' if data.get('is_stale') else '正常'}\n"
            f"告警: 活跃{alerts.get('active',0)} 严重{alerts.get('critical',0)}\n"
            f"风控拒单: {len(report.get('risk_rejections',[]))}笔"
        )

        system = (
            "你是A股量化交易复盘助手。根据日报数据，用3-5条简洁要点总结: "
            "1.今日组合表现 2.与沪深300的偏差原因 3.持仓风险提示。"
            "客观分析，不编造数据，每条不超过50字。直接输出要点，不要展示推理过程。"
        )
        r = chat(provider, system, context, temperature=0.3, timeout=max(timeout, 45), max_tokens=1500, scene="report")
        if r["success"]:
            return {
                "enabled": True,
                "active": True,
                "text": r["text"],
                "provider": provider,
                "provider_label": get_provider_label(provider),
            }
        return {"enabled": True, "active": False, "error": r.get("error", "")}
    except Exception as e:
        logger.debug(f"ai_review failed: {e}")
        return {"enabled": True, "active": False, "error": str(e)[:100]}


def save_report(report: dict):
    today = datetime.now().strftime("%Y%m%d")
    cache.set(f"paper:report:{today}", report)
    cache.set("paper:report:latest", report)


def format_report_text(report: dict) -> str:
    """格式化成可读文本日报。"""
    lines = []
    lines.append("=" * 56)
    lines.append(f"  AlphaCouncil 每日模拟盘日报  {report['report_date']}")
    lines.append("=" * 56)

    acc = report.get("account", {})
    lines.append("")
    lines.append("■ 账户")
    lines.append(f"  总权益:   ¥{acc.get('total_equity', 0):,.2f}  ({acc.get('total_pnl_pct', 0):+.2f}%)")
    lines.append(f"  现金:     ¥{acc.get('cash', 0):,.2f}")
    lines.append(f"  持仓市值: ¥{acc.get('market_value', 0):,.2f}")
    lines.append(f"  持仓数:   {acc.get('position_count', 0)}")

    bm = report.get("benchmark", {})
    if bm and not bm.get("error"):
        lines.append("")
        lines.append("■ 基准对比")
        lines.append(f"  {bm.get('name','沪深300')}: {bm.get('daily_return_pct', 0):+.2f}% (当日)  {bm.get('total_return_pct', 0):+.2f}% (累计)")
        lines.append(f"  超额收益: {bm.get('excess_return_pct', 0):+.2f}%")

    positions = report.get("positions", [])
    if positions:
        lines.append("")
        lines.append("■ 持仓明细")
        lines.append(f"  {'代码':<8} {'数量':>6} {'成本':>8} {'现价':>8} {'市值':>10} {'盈亏%':>8}")
        for p in positions:
            lines.append(f"  {p['code']:<8} {p['quantity']:>6} {p['avg_price']:>8.2f} "
                         f"{p['current_price']:>8.2f} {p['market_value']:>10.0f} {p['pnl_pct']:>+8.2f}")

    orders = report.get("today_orders", [])
    if orders:
        lines.append("")
        lines.append("■ 今日订单")
        for o in orders:
            status = "✅" if o.get("success") else "❌"
            lines.append(f"  {status} {o.get('code')} {o.get('direction')} {o.get('qty')}  {o.get('error') or ''}")

    rej = report.get("risk_rejections", [])
    if rej:
        lines.append("")
        lines.append("■ 风控拒单")
        for r in rej:
            lines.append(f"  ❌ {r.get('code')} {r.get('direction')} {r.get('qty')}: {r.get('reason')}")

    data = report.get("data", {})
    lines.append("")
    lines.append("■ 数据状态")
    stale_mark = "⚠️ 过期" if data.get("is_stale") else "✅ 正常"
    lines.append(f"  最新K线: {data.get('latest_kline_date', 'N/A')}  {stale_mark}")

    alerts = report.get("alerts", {})
    lines.append("")
    lines.append("■ 告警")
    lines.append(f"  活跃: {alerts.get('active', 0)}  严重: {alerts.get('critical', 0)}")

    skip = report.get("paper_skip_reason")
    if skip:
        lines.append("")
        lines.append(f"  模拟盘跳过原因: {skip}")

    ai = report.get("ai_review", {})
    if ai.get("enabled") and ai.get("active"):
        label = ai.get("provider_label", ai.get("provider", "AI"))
        lines.append("")
        lines.append(f"■ AI 复盘 ({label})")
        for ln in ai.get("text", "").split("\n"):
            ln = ln.strip()
            if ln:
                lines.append(f"  {ln}")

    lines.append("")
    lines.append("=" * 56)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="每日模拟盘日报")
    parser.add_argument("--json", action="store_true", help="输出 JSON 到 stdout")
    parser.add_argument("--text", action="store_true", help="输出可读文本到 stdout")
    args = parser.parse_args()

    report = generate_report()
    save_report(report)

    if args.json:
        print(json.dumps({"success": True, "data": report}, ensure_ascii=False, default=str))
    elif args.text:
        print(format_report_text(report))
    else:
        logging.basicConfig(level=logging.INFO)
        logger.info(f"日报已生成: paper:report:{datetime.now().strftime('%Y%m%d')}")
        print(format_report_text(report))


if __name__ == "__main__":
    main()

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
from copy import deepcopy
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache
from quant.paper_execution.runtime import load_active_account_projection

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


def _clean_code(code) -> str:
    c = str(code or "").strip().upper()
    if c.startswith(("SH", "SZ")):
        c = c[2:]
    if c.endswith((".SH", ".SZ")):
        c = c[:-3]
    return c


def _quote_for_code(quotes: dict, code: str) -> dict:
    if not quotes:
        return {}
    pure = _clean_code(code)
    keys = [code, pure, f"sh{pure}", f"sz{pure}", f"{pure}.SH", f"{pure}.SZ"]
    for key in keys:
        if key in quotes and isinstance(quotes[key], dict):
            return quotes[key]
        lower = str(key).lower()
        if lower in quotes and isinstance(quotes[lower], dict):
            return quotes[lower]
    return {}


def _record_time(record: dict) -> str:
    for key in ("timestamp", "created_at", "filled_at", "time"):
        value = record.get(key)
        if value not in (None, ""):
            try:
                numeric = float(value)
                if numeric > 1_000_000_000:
                    return datetime.fromtimestamp(numeric).strftime("%Y-%m-%d %H:%M:%S")
            except (TypeError, ValueError):
                pass
            return str(value)
    return ""


def _same_report_day(record: dict, today: str) -> bool:
    ts = _record_time(record)
    if not ts:
        return True
    return ts.startswith(today) or ts[:10] == today


def _record_qty(record: dict) -> int:
    return int(_safe_float(record.get("quantity", record.get("qty", record.get("filled_qty", 0)))))


def _record_price(record: dict) -> float:
    price = _safe_float(record.get("price"), 0)
    if price > 0:
        return price
    return _safe_float(record.get("filled_price"), 0)


def _position_records(code: str, orders: list | None, trades: list | None, today: str) -> list:
    pure = _clean_code(code)
    rows = []
    for trade in trades or []:
        if _clean_code(trade.get("code")) != pure:
            continue
        rows.append({
            "type": "trade",
            "time": _record_time(trade),
            "direction": trade.get("direction", ""),
            "quantity": _record_qty(trade),
            "price": round(_record_price(trade), 2),
            "status": trade.get("status", "filled"),
        })
    for order in orders or []:
        if _clean_code(order.get("code")) != pure:
            continue
        rows.append({
            "type": "order",
            "time": _record_time(order),
            "direction": order.get("direction", ""),
            "quantity": _record_qty(order),
            "price": round(_record_price(order), 2),
            "status": order.get("status") or ("filled" if order.get("success") else "rejected"),
        })
    rows.sort(key=lambda x: x.get("time") or "", reverse=True)
    same_day = [r for r in rows if str(r.get("time") or "").startswith(today)]
    return (same_day or rows)[:8]


def _position_details(positions: dict, *, quotes: dict | None = None,
                      orders: list | None = None, trades: list | None = None,
                      today: str | None = None) -> list:
    out = []
    today = today or datetime.now().strftime("%Y-%m-%d")
    for code, p in positions.items():
        qty = int(p.get("quantity", 0))
        if qty == 0:
            continue
        quote = _quote_for_code(quotes or {}, code)
        avg = _safe_float(p.get("avg_price"))
        realtime_price = _safe_float(quote.get("price") or quote.get("close"), 0)
        cur = realtime_price or _safe_float(p.get("current_price"), avg)
        mv = qty * cur
        pnl = (cur - avg) * qty
        pnl_pct = (cur - avg) / avg * 100 if avg > 0 else 0
        records = _position_records(code, orders, trades, today)
        name = str(quote.get("name") or p.get("name") or cache.get(f"stock:name:{_clean_code(code)}") or code)
        out.append({
            "code": code,
            "name": name,
            "quantity": qty,
            "avg_price": round(avg, 2),
            "realtime_price": round(cur, 2),
            "current_price": round(cur, 2),
            "amount": round(_safe_float(quote.get("amount")), 2),
            "chg_pct": round(_safe_float(quote.get("chg_pct")), 2),
            "market_value": round(mv, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "available_qty": int(p.get("available_qty", qty)),
            "trade_records": records,
            "trade_count": len([r for r in records if r.get("type") == "trade"]),
            "order_count": len([r for r in records if r.get("type") == "order"]),
        })
    out.sort(key=lambda x: abs(x["market_value"]), reverse=True)
    return out


def reconcile_report_with_execution(report: dict | None, active_cache=None) -> dict | None:
    """Overlay cached report fields with the unique active F5 account."""
    if not isinstance(report, dict):
        return report
    try:
        projection = load_active_account_projection()
    except Exception:
        out = deepcopy(report)
        out["account_source"] = "cached_report"
        out["account_stale"] = True
        return out
    out = deepcopy(report)
    today = datetime.now().strftime("%Y-%m-%d")
    positions = {
        str(row.get("code") or ""): row
        for row in projection.get("positions") or []
        if isinstance(row, dict) and str(row.get("code") or "")
    }
    orders = list(projection.get("orders") or [])
    trades = list(projection.get("trades") or [])
    live_positions = _position_details(
        positions,
        orders=orders,
        trades=trades,
        today=today,
    )
    authoritative = dict(projection.get("account") or {})
    initial_capital = _safe_float(authoritative.get("initial_capital"), 1_000_000.0)
    cash = _safe_float(authoritative.get("cash"))
    market_value = _safe_float(authoritative.get("market_value"))
    total_equity = _safe_float(authoritative.get("total_equity"))
    total_pnl = _safe_float(authoritative.get("total_pnl"), total_equity - initial_capital)
    total_pnl_pct = _safe_float(authoritative.get("total_pnl_pct"))
    reported_account = out.get("account") if isinstance(out.get("account"), dict) else {}
    reported_equity = _safe_float(reported_account.get("total_equity"))
    review = out.get("ai_review")
    if (
        isinstance(review, dict)
        and review.get("active") is True
        and abs(reported_equity - total_equity) > max(1_000.0, initial_capital * 0.01)
    ):
        out["historical_ai_review"] = deepcopy(review)
        out["ai_review"] = {
            **review,
            "active": False,
            "stale": True,
            "error": "account_snapshot_mismatch",
            "text": "",
        }
    out["account"] = {
        "initial_capital": round(initial_capital, 2),
        "cash": round(cash, 2),
        "market_value": round(market_value, 2),
        "total_equity": round(total_equity, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 4),
        "position_count": len(live_positions),
    }
    out["positions"] = live_positions
    out["attribution"] = sorted(
        [
            {
                "code": item.get("code"),
                "name": item.get("name") or item.get("code"),
                "pnl": item.get("pnl", 0),
                "pnl_pct": item.get("pnl_pct", 0),
            }
            for item in live_positions
        ],
        key=lambda item: abs(_safe_float(item.get("pnl"))),
        reverse=True,
    )
    benchmark = out.get("benchmark")
    if isinstance(benchmark, dict) and benchmark.get("comparable"):
        benchmark["excess_return_pct"] = round(
            total_pnl_pct - _safe_float(benchmark.get("total_return_pct")),
            4,
        )
    out["account_source"] = "f5_ledger"
    out["account_as_of"] = authoritative.get("updated_at")
    out["ledger_authority"] = "f5"
    out["account_stale"] = False
    return out


def project_report_data_freshness(
    report: dict | None,
    active_cache=None,
    *,
    now: datetime | None = None,
) -> dict | None:
    """Overlay a cached report with the current full-market daily-bar status."""
    if not isinstance(report, dict):
        return report
    from scripts.data_freshness import assess_market_kline_coverage, get_expected_date

    expected_for_now = get_expected_date(now)
    coverage = assess_market_kline_coverage(
        cache=active_cache or cache,
        expected_date=expected_for_now,
    )
    expected = str(coverage.get("expected_date") or expected_for_now).replace("-", "")[:8]
    latest = str(coverage.get("coverage_date") or "").replace("-", "")[:8]
    stale = not bool(coverage.get("fresh"))
    stale_days = 0
    if stale and expected and latest:
        try:
            stale_days = max(
                0,
                (datetime.strptime(expected, "%Y%m%d") - datetime.strptime(latest, "%Y%m%d")).days,
            )
        except ValueError:
            stale_days = 0

    out = deepcopy(report)
    data = dict(out.get("data") or {})
    data.update({
        "latest_kline_date": latest,
        "expected_latest": expected,
        "is_stale": stale,
        "stale_days": stale_days,
        "market_coverage": coverage,
    })
    out["data"] = data
    return out


def generate_report() -> dict:
    """生成当日日报。不依赖外部数据源，只读已有状态。"""
    today = datetime.now().strftime("%Y-%m-%d")
    today_compact = datetime.now().strftime("%Y%m%d")

    # ── 账户快照 ──────────────────────
    projection = load_active_account_projection()
    authoritative = dict(projection.get("account") or {})
    init_cap = _safe_float(authoritative.get("initial_capital"), 1_000_000)
    cash = _safe_float(authoritative.get("cash"))
    positions = {
        str(row.get("code") or ""): row
        for row in projection.get("positions") or []
        if isinstance(row, dict) and str(row.get("code") or "")
    }
    orders_all = list(projection.get("orders") or [])
    trades_all = list(projection.get("trades") or [])
    pos_list = _position_details(
        positions,
        orders=orders_all,
        trades=trades_all,
        today=today,
    )
    total_mv = _safe_float(authoritative.get("market_value"))
    total_equity = _safe_float(authoritative.get("total_equity"))
    total_pnl = _safe_float(authoritative.get("total_pnl"), total_equity - init_cap)
    total_pnl_pct = _safe_float(authoritative.get("total_pnl_pct"))

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
            "initial_date": bm.get("initial_date"),
            "end_date": today,
            "comparable": bool(bm.get("initial_date") and not bm.get("last_error")),
            "source": "paper:benchmark",
        }
    except Exception as e:
        logger.debug(f"benchmark refresh failed: {e}")
        benchmark = {"error": str(e)[:120]}

    # ── 今日订单/风控 ────────────────
    today_orders = [row for row in orders_all if _same_report_day(row, today)]
    risk_rejections = [
        row for row in today_orders if str(row.get("status") or "") == "rejected"
    ]
    skipped_orders = []
    skip_reason = None

    # ── 数据状态 (统一入口) ─────────────
    # ── 告警 ─────────────────────────
    alerts_summary = _active_alerts_summary()
    from quant.risk.config import load_risk_config
    risk_limits = load_risk_config(cache)

    portfolio_plan = cache.get("ai:portfolio:latest") or {}
    target_rows = portfolio_plan.get("target_weights") or []
    target_map = {str(row.get("code", "")).split(".")[0]: row for row in target_rows if isinstance(row, dict)}
    target_drift = []
    for position in pos_list:
        code = str(position.get("code", "")).split(".")[0]
        target = target_map.get(code, {})
        current_weight = position["market_value"] / total_equity if total_equity > 0 else 0
        target_weight = _safe_float(target.get("target_weight"))
        target_drift.append({
            "code": code,
            "name": position.get("name") or code,
            "current_weight": round(current_weight, 6),
            "target_weight": round(target_weight, 6),
            "difference": round(target_weight - current_weight, 6),
        })
    attribution = sorted([
        {
            "code": position.get("code"),
            "name": position.get("name") or position.get("code"),
            "pnl": position.get("pnl", 0),
            "pnl_pct": position.get("pnl_pct", 0),
        }
        for position in pos_list
    ], key=lambda item: abs(_safe_float(item.get("pnl"))), reverse=True)

    report = {
        "report_date": today,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "account_source": "f5_ledger",
        "account_as_of": authoritative.get("updated_at"),
        "ledger_authority": "f5",
        "account_stale": False,
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
        "risk_limits": {
            "position_stop_loss_pct": risk_limits.get("max_position_loss_pct"),
            "max_daily_loss_pct": risk_limits.get("max_daily_loss_pct"),
            "max_drawdown_pct": risk_limits.get("max_drawdown_pct"),
            "source": risk_limits.get("_hard_limits_source"),
        },
        "target_drift": target_drift,
        "attribution": attribution,
        "skipped_orders": skipped_orders,
        "paper_skip_reason": skip_reason,
        "paper_last_run": paper_status.get("last_run"),
        "paper_running": paper_status.get("running", False),
        "data": {},
        "alerts": alerts_summary,
    }
    report = project_report_data_freshness(report, cache)
    # ── AI 复盘 (可选, 失败不影响报告) ─────────────────
    report["ai_review"] = _generate_ai_review(report)
    return report


def _local_ai_review(report: dict, *, provider: str = "", provider_label: str = "", reason: str = "") -> dict:
    acc = report.get("account", {}) or {}
    data = report.get("data", {}) or {}
    alerts = report.get("alerts", {}) or {}
    positions = report.get("positions", []) or []
    rejections = report.get("risk_rejections", []) or []
    total_pnl = float(acc.get("total_pnl_pct") or 0)
    cash = float(acc.get("cash") or 0)
    equity = float(acc.get("total_equity") or 0)
    cash_pct = (cash / equity * 100) if equity > 0 else 0
    latest = data.get("latest_kline_date", "N/A")
    data_state = "过期" if data.get("is_stale") else "正常"
    top_positions = positions[:3]
    pos_text = "、".join([f"{p.get('code')}({float(p.get('pnl_pct') or 0):+.1f}%)" for p in top_positions]) or "空仓"
    points = [
        f"组合累计收益 {total_pnl:+.2f}%，现金占比约 {cash_pct:.1f}%，当前持仓 {len(positions)} 只。",
        f"最新K线日期 {latest}，数据状态为{data_state}，交易前仍需通过数据新鲜度门禁。",
        f"主要持仓: {pos_text}。",
        f"活跃告警 {alerts.get('active', 0)} 条，严重告警 {alerts.get('critical', 0)} 条，风控拒单 {len(rejections)} 笔。",
    ]
    if reason:
        points.append(f"外部模型复盘暂不可用，已启用本地规则复盘: {reason[:120]}")
    return {
        "enabled": True,
        "active": True,
        "fallback": True,
        "provider": provider or "local_rules",
        "provider_label": provider_label or "本地规则复盘",
        "text": "\n".join(f"- {p}" for p in points),
        "error": reason[:200] if reason else "",
    }


def _ai_review_is_presentable(value) -> bool:
    """Accept concise review bullets and reject model meta-reasoning."""
    text = str(value or "").strip()
    if not text or len(text) > 1200:
        return False
    forbidden = (
        "让我们",
        "精确重数",
        "字数",
        "等等",
        "推理过程",
        "思考过程",
        "重新组织",
    )
    if any(marker in text for marker in forbidden):
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not 3 <= len(lines) <= 8 or any(len(line) > 180 for line in lines):
        return False
    bullet_count = sum(
        1
        for line in lines
        if line.startswith(("- ", "* ", "• "))
        or (len(line) >= 2 and line[0].isdigit() and line[1] in ".、")
        or line.startswith("要点")
    )
    return bullet_count >= 3


def _generate_ai_review(report: dict) -> dict:
    """调用 LLM 生成每日复盘要点。失败返回空 dict, 不影响报告主体。"""
    # 读取 LLM 配置 (从 paper:config)
    cfg = cache.get("paper:config") or {}
    llm_cfg = cfg.get("llm", {})
    if not llm_cfg.get("enabled"):
        return _local_ai_review(report, reason="paper llm disabled")

    try:
        from scripts.llm_client import chat, get_provider_label
        provider = llm_cfg.get("provider", "glm")
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
        if r["success"] and _ai_review_is_presentable(r.get("text")):
            return {
                "enabled": True,
                "active": True,
                "text": r["text"],
                "provider": provider,
                "provider_label": get_provider_label(provider),
            }
        if r["success"]:
            return _local_ai_review(
                report,
                provider=provider,
                provider_label=get_provider_label(provider),
                reason="invalid_ai_review_format",
            )
        return _local_ai_review(
            report,
            provider=provider,
            provider_label=get_provider_label(provider),
            reason=r.get("error", ""),
        )
    except Exception as e:
        logger.debug(f"ai_review failed: {e}")
        return _local_ai_review(report, reason=str(e)[:100])


def save_report(report: dict):
    today = datetime.now().strftime("%Y%m%d")
    cache.set(f"paper:report:{today}", report)
    cache.set("paper:report:latest", report)


def format_report_text(report: dict) -> str:
    """格式化成可读文本日报。"""
    lines = []
    lines.append("=" * 56)
    lines.append(f"  XuanJi 每日模拟盘日报  {report['report_date']}")
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
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
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

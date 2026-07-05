"""全局 AI 自主目标管理 — 目标权益、进度与风险模式。

本模块只做配置和指标计算，不下单、不放宽风控。
"""
import copy
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache

cache = create_cache()

AUTONOMOUS_CFG_KEY = "ai:autonomous:config"
OBJECTIVE_KEY = "ai:objective:latest"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _deep_merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base or {})
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def default_autonomous_config() -> dict:
    return {
        "enabled": True,
        "provider": "glm",
        "target_equity": 100_000_000.0,
        "horizon_days": 365,
        "start_date": _today(),
        "mode": "target_portfolio",
        "intraday_interval_sec": 600,
        "postclose_interval_sec": 1800,
        "idle_interval_sec": 7200,
        "ultra_thinking": {
            "enabled": True,
            "committee": True,
            "roles": ["opportunity", "risk", "execution", "portfolio_manager"],
        },
        "risk": {
            "max_position_pct": 0.2,
            "max_gross_exposure_pct": 95,
            "max_position_count": 10,
            "min_cash_buffer_pct": 2,
            "max_daily_turnover_pct": 35,
            "max_drawdown_pct": 12,
        },
        "execution": {
            "max_rebalance_orders": 20,
            "rebalance_frequency": "daily",
            "allow_intraday_new_positions": False,
        },
    }


def load_autonomous_config() -> dict:
    cfg = cache.get(AUTONOMOUS_CFG_KEY) or {}
    merged = _deep_merge(default_autonomous_config(), cfg)
    if not merged.get("start_date"):
        merged["start_date"] = _today()
    return merged


def save_autonomous_config(patch: dict) -> dict:
    old = load_autonomous_config()
    merged = _deep_merge(old, patch or {})
    if not merged.get("start_date"):
        merged["start_date"] = _today()
    cache.set(AUTONOMOUS_CFG_KEY, merged)
    # 兼容现有 scheduler 配置: 只合并关键字段，不覆盖扩展配置。
    sched = cache.get("ai:scheduler:config") or {}
    sched = _deep_merge(sched, {
        "enabled": bool(merged.get("enabled", True)),
        "provider": merged.get("provider") or "glm",
        "autonomous_enabled": bool(merged.get("enabled", True)),
    })
    cache.set("ai:scheduler:config", sched)
    return merged


def get_current_equity() -> dict:
    state = cache.get("execution:state") or {}
    cash = float(state.get("cash", state.get("initial_capital", 1_000_000.0)) or 0)
    positions = state.get("positions", {}) or {}
    market_value = 0.0
    position_count = 0
    for p in positions.values():
        qty = int(p.get("quantity", 0) or 0)
        if qty <= 0:
            continue
        price = float(p.get("current_price", p.get("avg_price", 0)) or 0)
        market_value += qty * price
        position_count += 1
    total_equity = float(state.get("total_equity") or (cash + market_value))
    initial_capital = float(state.get("initial_capital", 1_000_000.0) or 1_000_000.0)
    return {
        "cash": round(cash, 2),
        "market_value": round(market_value, 2),
        "total_equity": round(total_equity, 2),
        "initial_capital": round(initial_capital, 2),
        "position_count": position_count,
    }


def _parse_date(value: str):
    if not value:
        return datetime.now().date()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(value), fmt).date()
        except Exception:
            continue
    return datetime.now().date()


def _pct(value: float) -> float:
    return round(value * 100, 4)


def compute_objective_status(config: dict = None, persist: bool = True) -> dict:
    cfg = _deep_merge(load_autonomous_config(), config or {})
    account = get_current_equity()
    target_equity = float(cfg.get("target_equity", 100_000_000.0) or 100_000_000.0)
    initial_equity = float(cfg.get("initial_equity") or account.get("initial_capital") or account.get("total_equity") or 1_000_000.0)
    current_equity = float(account.get("total_equity") or initial_equity)
    horizon_days = max(1, int(cfg.get("horizon_days", 365) or 365))
    start_date = _parse_date(cfg.get("start_date"))
    elapsed_days = max(0, (datetime.now().date() - start_date).days)
    remaining_days = max(0, horizon_days - elapsed_days)
    target_gain = max(1.0, target_equity - initial_equity)
    current_gain = current_equity - initial_equity
    progress_pct = max(0.0, min(999.0, current_gain / target_gain * 100))
    expected_progress_pct = min(100.0, elapsed_days / horizon_days * 100)
    target_gap = target_equity - current_equity

    if current_equity <= 0:
        required_total_return_pct = 0.0
        required_annualized_return_pct = 0.0
        required_monthly_return_pct = 0.0
    else:
        required_total_return_pct = (target_equity / current_equity - 1) * 100
        if remaining_days > 0 and target_equity > current_equity:
            required_annualized_return_pct = ((target_equity / current_equity) ** (365 / remaining_days) - 1) * 100
            required_monthly_return_pct = ((target_equity / current_equity) ** (30 / remaining_days) - 1) * 100
        else:
            required_annualized_return_pct = 0.0
            required_monthly_return_pct = 0.0

    on_track = progress_pct + 1e-9 >= expected_progress_pct
    if current_equity >= target_equity:
        risk_mode = "protect_profit"
    elif remaining_days == 0:
        risk_mode = "no_new_position"
    elif required_annualized_return_pct > 300 or required_monthly_return_pct > 20:
        risk_mode = "selective_catch_up"
    elif not on_track:
        risk_mode = "selective_catch_up"
    else:
        risk_mode = "normal"

    objective_pressure = "extreme" if required_annualized_return_pct > 300 or required_monthly_return_pct > 20 else ("high" if required_annualized_return_pct > 80 else "normal")
    result = {
        "success": True,
        "enabled": bool(cfg.get("enabled", True)),
        "generated_at": _now(),
        "date": datetime.now().strftime("%Y%m%d"),
        "target_equity": round(target_equity, 2),
        "initial_equity": round(initial_equity, 2),
        "current_equity": round(current_equity, 2),
        "net_profit": round(current_gain, 2),
        "target_gap": round(target_gap, 2),
        "progress_pct": round(progress_pct, 4),
        "expected_progress_pct": round(expected_progress_pct, 4),
        "on_track": bool(on_track),
        "elapsed_days": elapsed_days,
        "remaining_days": remaining_days,
        "horizon_days": horizon_days,
        "required_total_return_pct": round(required_total_return_pct, 4),
        "required_annualized_return_pct": round(required_annualized_return_pct, 4),
        "required_monthly_return_pct": round(required_monthly_return_pct, 4),
        "risk_mode": risk_mode,
        "objective_pressure": objective_pressure,
        "account": account,
        "config": cfg,
        "warning": "目标权益 1 亿/1 年极激进；本指标只用于模拟盘目标跟踪，不允许覆盖硬风控。",
    }
    if persist:
        cache.set(OBJECTIVE_KEY, result)
    return result


def get_status() -> dict:
    return {
        "config": load_autonomous_config(),
        "objective": cache.get(OBJECTIVE_KEY) or compute_objective_status(),
        "committee": cache.get("ai:committee:latest"),
        "portfolio": cache.get("ai:portfolio:latest"),
        "decision": cache.get("ai:decision:latest"),
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AI 自主目标状态")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--set", dest="patch", help="JSON patch")
    args = parser.parse_args()
    if args.patch:
        out = save_autonomous_config(json.loads(args.patch))
    else:
        out = get_status()
    print(json.dumps({"success": True, "data": out}, ensure_ascii=False, default=str))

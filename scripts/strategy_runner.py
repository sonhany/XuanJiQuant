"""Strategy 引擎 API: 策略执行 + Event-Driven 回测 + 因子批量评估

Actions:
  meta           → 返回策略元信息
  run            → 执行策略并回测 (旧版简单回测)
  backtest       → 事件驱动回测 (新版 BacktestSimulator)
  batch_evaluate → 因子池批量 IC 评估 (58 因子全部跑一遍)
"""
import sys, json, os, math, time, hashlib
from pathlib import Path
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache
from quant.data.loader import load_kline_df
from quant.factor import FactorEngine, ALL_FACTORS
from quant.strategy import StrategyEngine
from quant.backtest import BacktestSimulator
from quant.research.publication import (
    PublicationError,
    read_publication_status,
    resolve_complete_artifact,
)
from quant.strategy.f4_readiness import build_f4_readiness
from scripts.data_freshness import get_expected_date


def _to_py(val):
    if isinstance(val, dict): return {k: _to_py(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)): return [_to_py(v) for v in val]
    if isinstance(val, (np.integer,)): return int(val)
    if isinstance(val, (float, np.floating)):
        v = float(val)
        try:
            if math.isnan(v) or math.isinf(v): return None
        except (TypeError, ValueError):
            # Some np.float 'nan' values raise TypeError with math.isnan
            s = str(val).lower()
            if 'nan' in s or 'inf' in s: return None
            return v
        return round(v, 6)
    return val

def clean(data): return json.dumps(_to_py(data))


cache = create_cache()
engine = FactorEngine(cache=cache)
strategy_engine = StrategyEngine(factor_engine=engine, cache=cache)
STRATEGY_RUN_CACHE_TTL = int(os.environ.get("XUANJI_STRATEGY_RUN_CACHE_TTL", "1800"))
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESEARCH_PUBLICATION_ROOT = Path(ROOT_DIR) / "data" / "research" / "daily"
F4_LATEST_PATH = os.path.join(ROOT_DIR, "data", "research", "f4", "latest.json")
SELECTION_LATEST_PATH = os.path.join(
    ROOT_DIR, "data", "research", "selections", "latest.json"
)


def _strategy_data_version(klines_dict):
    versions = []
    for code in sorted(klines_dict.keys()):
        df = klines_dict.get(code)
        if df is None or df.empty:
            versions.append([code, 0, ""])
            continue
        last_date = str(df.iloc[-1].get("date", ""))
        versions.append([code, int(len(df)), last_date])
    return versions


def _strategy_raw_data_version(codes, start, end):
    start_s = start.replace("-", "")[:8] if start else ""
    end_s = end.replace("-", "")[:8] if end else ""
    versions = []
    has_data = False
    for raw_code in sorted([_norm(c) for c in codes]):
        raw = cache.get(f"kline:{raw_code}:d")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = []
        rows = []
        for row in raw or []:
            d = str((row or {}).get("date") or (row or {}).get("d") or "")
            if start_s and d < start_s:
                continue
            if end_s and d > end_s:
                continue
            rows.append(row)
        if rows:
            has_data = True
            last = rows[-1] or {}
            last_date = str(last.get("date") or last.get("d") or "")
            versions.append([raw_code, len(rows), last_date])
        else:
            versions.append([raw_code, 0, ""])
    return versions, has_data


def _strategy_cache_key(name, params, codes, start, end, data_version):
    payload = {
        "name": name,
        "params": params or {},
        "codes": sorted([_norm(c) for c in codes]),
        "start": start or "",
        "end": end or "",
        "data": data_version,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"strategy:run_cache:{digest}"


def action_meta(req=None):
    return {"success": True, "data": strategy_engine.strategy_meta()}


def _norm(code):
    """去掉 .SZ/.SH/.BJ 后缀。Redis 存纯 6 位代码。"""
    return (code or "").split(".")[0]


def _load_klines(codes, start="", end=""):
    """加载K线数据。自动去掉 .SZ/.SH/.BJ 后缀 — Redis 里是纯 6 位代码。"""
    klines_dict = {}
    for raw_code in codes:
        code = _norm(raw_code)
        raw = cache.get(f"kline:{code}:d")
        if not raw:
            continue
        # cache.get returns list directly in Redis mode
        if isinstance(raw, str):
            raw = json.loads(raw)
        df = load_kline_df(raw)
        df = df[df['date'] != '']
        start_s = start.replace('-', '')[:8] if start else ''
        end_s = end.replace('-', '')[:8] if end else ''
        if start_s:
            df = df[df['date'] >= start_s]
        if end_s:
            df = df[df['date'] <= end_s]
        if not df.empty:
            klines_dict[code] = df
    return klines_dict


def action_run(req):
    """策略运行 + 回测 (返回兼容前端 StrategyPanel 的结构)"""
    name = req.get("name", "")
    params = req.get("params", {})
    codes = req.get("codes", [])
    start = req.get("start", "")
    end = req.get("end", "")
    if not name or not codes:
        return {"success": False, "error": "name and codes required"}
    data_version, has_data = _strategy_raw_data_version(codes, start, end)
    if not has_data:
        return {"success": False, "error": "no data available"}

    cache_key = _strategy_cache_key(name, params, codes, start, end, data_version)
    cached = cache.get(cache_key)
    if cached:
        cached.setdefault("diagnostic_only", True)
        cached.setdefault("promotion_state", "research_only")
        cached.setdefault("execution_authority", False)
        cached["cache"] = {"hit": True, "key": cache_key, "ttl_seconds": STRATEGY_RUN_CACHE_TTL}
        return cached

    klines_dict = _load_klines(codes, start, end)
    if not klines_dict:
        return {"success": False, "error": "no data available"}

    t0 = time.time()
    result = strategy_engine.run_strategy(name, params, klines_dict)
    elapsed = time.time() - t0

    # 把新回测结果 (metrics/fills) 转成前端期望的 summary/per_stock/details
    bt = result.get("backtest") or {}
    metrics = bt.get("metrics", {}) or {}
    fills = bt.get("fills", []) or []

    summary = {
        "total_return_pct": metrics.get("total_return_pct", 0),
        "avg_return_pct": metrics.get("annual_return_pct", 0),
        "win_rate_pct": metrics.get("win_rate_pct", 0),
        "total_trades": metrics.get("total_trades", 0),
        # 额外指标 (前端用不到但有用)
        "sharpe_ratio": metrics.get("sharpe_ratio", 0),
        "max_drawdown_pct": metrics.get("max_drawdown_pct", 0),
        "final_equity": metrics.get("final_equity", 0),
    }

    # fills 配对成 details (买→卖 为一笔完整交易)
    # fills 结构: {date, code, direction, quantity, price}
    details = _fills_to_details(fills)

    # per_stock: 按股票聚合
    per_stock = {}
    for d in details:
        c = d.get("code")
        if c not in per_stock:
            per_stock[c] = {"trade_count": 0, "total_return_pct": 0, "win_count": 0}
        ps = per_stock[c]
        ps["trade_count"] += 1
        ps["total_return_pct"] += d.get("pnl_pct", 0)
        if d.get("pnl_pct", 0) > 0:
            ps["win_count"] += 1
    for c, ps in per_stock.items():
        n = ps["trade_count"]
        ps["win_rate_pct"] = round(ps.pop("win_count", 0) / n * 100, 1) if n else 0
        ps["avg_win_pct"] = round(ps["total_return_pct"] / n, 2) if n else 0

    # 保留原始 backtest 数据 + 兼容字段
    result["backtest"] = {
        **bt,
        "summary": summary,
        "per_stock": per_stock,
        "details": details,
    }
    result["elapsed"] = round(elapsed, 2)
    out = {
        "success": True,
        "data": result,
        "diagnostic_only": True,
        "promotion_state": "research_only",
        "execution_authority": False,
        "cache": {"hit": False, "key": cache_key, "ttl_seconds": STRATEGY_RUN_CACHE_TTL},
    }
    cache.set(cache_key, out, ttl=STRATEGY_RUN_CACHE_TTL)
    return out


def _fills_to_details(fills):
    """把 fill 流 (买/卖交替) 配对成交易明细

    简单配对: 同一股票，一个 buy 后跟最近的 sell 算一笔交易。
    """
    by_code = {}
    for f in fills:
        c = f.get("code")
        by_code.setdefault(c, []).append(f)

    details = []
    for code, flist in by_code.items():
        # 按日期排序
        flist.sort(key=lambda x: x.get("date", ""))
        open_buy = None
        for f in flist:
            d = f.get("direction")
            if d == "buy":
                open_buy = f
            elif d == "sell" and open_buy:
                entry = open_buy.get("price", 0)
                exit_p = f.get("price", 0)
                pnl_pct = round((exit_p - entry) / entry * 100, 2) if entry else 0
                entry_date = str(open_buy.get("date", ""))
                exit_date = str(f.get("date", ""))
                # 估算持有天数 (YYYYMMDD 差)
                holding = _days_between(entry_date, exit_date)
                details.append({
                    "entry_date": entry_date,
                    "code": code,
                    "entry_price": round(entry, 2),
                    "exit_price": round(exit_p, 2),
                    "holding_days": holding,
                    "pnl_pct": pnl_pct,
                })
                open_buy = None
    return details


def _days_between(d1, d2):
    """估算两个 YYYYMMDD 字符串之间的天数"""
    try:
        from datetime import datetime
        a = datetime.strptime(d1[:8], "%Y%m%d")
        b = datetime.strptime(d2[:8], "%Y%m%d")
        return (b - a).days
    except Exception:
        return 0


def action_backtest(req):
    """事件驱动回测 (Phase 2)"""
    name = req.get("name", "")
    params = req.get("params", {})
    codes = req.get("codes", [])
    start = req.get("start", "")
    end = req.get("end", "")
    initial_cash = float(req.get("initial_cash", 1_000_000))
    commission_rate = float(req.get("commission_rate", 0.0003))
    slippage_rate = float(req.get("slippage_rate", 0.0001))
    position_size_pct = float(req.get("position_size_pct", 0.2))

    if not name or not codes:
        return {"success": False, "error": "name and codes required"}
    klines_dict = _load_klines(codes, start, end)
    if not klines_dict:
        return {"success": False, "error": "no data available"}

    # Generate signals via strategy engine
    t0 = time.time()
    strat_result = strategy_engine.run_strategy(name, params, klines_dict)
    signals = strat_result.get("signals", {})

    # Run event-driven backtest
    sim = BacktestSimulator(
        initial_cash=initial_cash,
        commission_rate=commission_rate,
        slippage_rate=slippage_rate,
        position_size_pct=position_size_pct,
    )
    sim.add_signals(signals)
    sim.add_klines(klines_dict)
    bt_result = sim.run()

    elapsed = time.time() - t0
    return {
        "success": True,
        "diagnostic_only": True,
        "promotion_state": "research_only",
        "execution_authority": False,
        "data": {
            "strategy_name": name,
            "params": params,
            "stocks": codes,
            "elapsed": round(elapsed, 2),
            "backtest": bt_result,
        }
    }


def action_batch_evaluate(req):
    """因子池批量 IC 评估 — 一次评估所有 58 因子"""
    codes = req.get("codes", [])
    fwd_horizons = req.get("fwd_horizons", [1, 5, 10, 20])
    start = req.get("start", "")
    end = req.get("end", "")

    if not codes:
        return {"success": False, "error": "codes required"}

    klines_dict = _load_klines(codes, start, end)
    if not klines_dict:
        return {"success": False, "error": "no data available"}

    t0 = time.time()
    multi_factor = engine.compute_multi(klines_dict, use_cache=False)
    results = engine.evaluate_all(multi_factor, klines_dict, fwd_horizons=fwd_horizons)
    elapsed = time.time() - t0

    return {
        "success": True,
        "data": {
            "factors_evaluated": len(results),
            "elapsed": round(elapsed, 2),
            "top_by_ic": results[:10],
            "all_results": results,
        }
    }


def action_factor_ic_detail(req):
    """单因子 IC 衰减详情 (返回 IC 时间序列)"""
    codes = req.get("codes", [])
    factor_name = req.get("factor_name", "")
    start = req.get("start", "")
    end = req.get("end", "")

    if not codes or not factor_name:
        return {"success": False, "error": "codes and factor_name required"}

    klines_dict = _load_klines(codes, start, end)
    if not klines_dict:
        return {"success": False, "error": "no data available"}

    multi_factor = engine.compute_multi(klines_dict, use_cache=False)
    result = engine.evaluate_factor(multi_factor, klines_dict, factor_name)
    return {"success": True, "data": result}


def _safe_float(value, default=None):
    try:
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except Exception:
        return default


_F4_FACTORY_VERSION_V1 = "f4-nested-candidate-factory-v1"
_F4_FACTORY_VERSION_V2 = "f4-multi-alpha-candidate-factory-v2"
_F4_V2_FAMILIES = (
    "momentum",
    "reversal",
    "defensive",
    "liquidity",
    "ensemble",
    "qlib",
)


def _is_finite_number(value):
    return type(value) in (int, float) and math.isfinite(float(value))


def _valid_v2_projection(data):
    if data.get("candidate_count") != 24:
        return False
    diagnostics = data.get("family_diagnostics")
    if not isinstance(diagnostics, dict) or set(diagnostics) != set(_F4_V2_FAMILIES):
        return False
    total_validation_wins = 0
    for family in _F4_V2_FAMILIES:
        row = diagnostics.get(family)
        if not isinstance(row, dict):
            return False
        counts = tuple(row.get(key) for key in ("registered", "available", "unavailable", "validation_wins"))
        if any(type(value) is not int or value < 0 for value in counts):
            return False
        if counts[0] != 4 or counts[1] + counts[2] != counts[0]:
            return False
        total_validation_wins += counts[3]
        reasons = row.get("reason_counts")
        if not isinstance(reasons, dict) or any(
            not isinstance(reason, str)
            or not reason
            or type(count) is not int
            or count < 0
            for reason, count in reasons.items()
        ):
            return False
        if sum(reasons.values()) > counts[2]:
            return False
    candidate_spec = data.get("candidate_spec")
    locks = candidate_spec.get("selection_locks") if isinstance(candidate_spec, dict) else None
    if not isinstance(locks, list) or total_validation_wins != len(locks):
        return False
    lock_windows = [lock.get("window_id") for lock in locks if isinstance(lock, dict)]
    if len(lock_windows) != len(locks) or any(not isinstance(value, str) or not value for value in lock_windows):
        return False
    if len(set(lock_windows)) != len(lock_windows):
        return False
    stress = data.get("stress_metrics")
    if not isinstance(stress, dict) or set(stress) != {"1.0", "1.5", "2.0"}:
        return False
    for multiplier in ("1.0", "1.5", "2.0"):
        summary = stress.get(multiplier)
        if not isinstance(summary, dict):
            return False
        if any(
            not _is_finite_number(summary.get(field))
            for field in ("excess_return", "after_cost_return", "total_cost")
        ):
            return False
        if float(summary["total_cost"]) < 0:
            return False
        if (
            type(summary.get("window_count")) is not int
            or summary["window_count"] != len(locks)
            or type(summary.get("trade_count")) is not int
            or summary["trade_count"] < 0
            or summary.get("promotion_state") != "research_only"
            or summary.get("execution_authority") is not False
        ):
            return False
    report_path = data.get("artifact_path")
    return isinstance(report_path, str) and bool(report_path.strip()) and Path(report_path).is_file()


def _projection_factory_version(data):
    outer = data.get("candidate_spec_version")
    candidate_spec = data.get("candidate_spec")
    inner = candidate_spec.get("version") if isinstance(candidate_spec, dict) else None
    declared = data.get("factory_version")
    if data.get("status") == "f4_blocked" and declared in (None, ""):
        return "blocked_without_factory"
    if (
        outer == _F4_FACTORY_VERSION_V2
        or inner == _F4_FACTORY_VERSION_V2
        or data.get("candidate_count") == 24
        or "family_diagnostics" in data
    ):
        return (
            _F4_FACTORY_VERSION_V2
            if declared == outer == inner == _F4_FACTORY_VERSION_V2
            else None
        )
    if outer == inner == _F4_FACTORY_VERSION_V1 and declared in (None, "", _F4_FACTORY_VERSION_V1):
        return _F4_FACTORY_VERSION_V1
    return None


def action_market_scan(req=None):
    """Return only the integrity-checked F4 latest projection."""
    if not os.path.exists(F4_LATEST_PATH):
        return {
            "success": False,
            "status": "f4_blocked",
            "reason_code": "f4_evidence_missing",
            "error": "尚未生成 F4 策略与组合验证证据",
        }
    try:
        with open(F4_LATEST_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as exc:
        return {
            "success": False,
            "status": "f4_blocked",
            "reason_code": "artifact_integrity_failed",
            "error": str(exc),
        }
    if (
        not isinstance(data, dict)
        or not data.get("validation_id")
        or not data.get("status")
        or data.get("promotion_state") != "research_only"
        or data.get("execution_authority") is not False
    ):
        return {
            "success": False,
            "status": "f4_blocked",
            "reason_code": "artifact_integrity_failed",
            "error": "F4 证据身份或权限边界无效",
        }
    factory_version = _projection_factory_version(data)
    if factory_version is None or (
        factory_version == _F4_FACTORY_VERSION_V2 and not _valid_v2_projection(data)
    ):
        return {
            "success": False,
            "status": "f4_blocked",
            "reason_code": "f4_evidence_integrity_failed",
            "error": "F4 v2 候选族、成本压力或报告证据不完整",
        }
    data["source"] = "f4_latest_projection"
    data["readiness"] = build_f4_readiness(ROOT_DIR)
    return {"success": True, "data": data}


def action_research_selection(req=None):
    """Return only the integrity-checked daily research selection projection."""
    publication_status = {}
    authoritative = False
    pointer_exists = (RESEARCH_PUBLICATION_ROOT / "latest.json").is_file()
    try:
        completed_path = resolve_complete_artifact(
            RESEARCH_PUBLICATION_ROOT, "selection.json"
        )
        with Path(completed_path).open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        publication_status = read_publication_status(RESEARCH_PUBLICATION_ROOT)
        authoritative = True
    except (PublicationError, OSError, json.JSONDecodeError, TypeError, ValueError):
        data = None
    if data is None and (pointer_exists or not os.path.exists(SELECTION_LATEST_PATH)):
        return {
            "success": False,
            "reason_code": (
                "research_selection_integrity_failed"
                if pointer_exists
                else "research_selection_missing"
            ),
            "error": (
                "完成指针对应的研究选股产物完整性校验失败"
                if pointer_exists
                else "尚未生成每日研究选股组合"
            ),
        }
    if data is None:
        try:
            with open(SELECTION_LATEST_PATH, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as exc:
            return {
                "success": False,
                "reason_code": "research_selection_integrity_failed",
                "error": str(exc),
            }
    positions = data.get("positions") if isinstance(data, dict) else None
    position_count = data.get("position_count") if isinstance(data, dict) else None
    position_count_valid = (
        isinstance(position_count, int)
        and not isinstance(position_count, bool)
        and isinstance(positions, list)
        and position_count == len(positions)
    )
    allowed_statuses = {
        "diagnostic_research_portfolio",
        "f4_research_portfolio",
    }
    if (
        not isinstance(data, dict)
        or not data.get("portfolio_id")
        or not data.get("selection_date")
        or not data.get("generated_from_snapshot_id")
        or not data.get("snapshot_data_version")
        or data.get("selection_status") not in allowed_statuses
        or not isinstance(positions, list)
        or not positions
        or not position_count_valid
        or data.get("promotion_state") != "research_only"
        or data.get("execution_authority") is not False
        or data.get("not_a_trade_signal") is not True
    ):
        return {
            "success": False,
            "reason_code": "research_selection_integrity_failed",
            "error": "研究选股证据身份、持仓数量或权限边界无效",
        }
    data["source"] = "research_selection_latest_projection"
    if authoritative:
        target_date = str(publication_status.get("target_date") or "").replace("-", "")[:8]
        selection_date = str(data.get("selection_date") or "").replace("-", "")[:8]
        expected_latest_date = str(get_expected_date() or "").replace("-", "")[:8]
        data["is_current"] = bool(
            target_date
            and selection_date == target_date
            and (not expected_latest_date or selection_date >= expected_latest_date)
        )
        data["expected_latest_date"] = expected_latest_date
        data["freshness_warning"] = (
            f"研究选股已过期：组合日期 {selection_date or '未知'}，"
            f"预期至少 {expected_latest_date}；当前组合仅供历史参考。"
            if not data["is_current"] and expected_latest_date
            else None
        )
        data["research_refresh"] = {
            "state": publication_status.get("state") or "completed",
            "target_date": publication_status.get("target_date"),
            "generation_id": publication_status.get("generation_id")
            or publication_status.get("last_complete_generation_id"),
            "reason_code": publication_status.get("reason_code"),
        }
        data["source"] = "research_generation_pointer"
    return {"success": True, "data": data}


ACTIONS = {
    "meta": action_meta,
    "run": action_run,
    "backtest": action_backtest,
    "batch_evaluate": action_batch_evaluate,
    "factor_ic_detail": action_factor_ic_detail,
    "market_scan": action_market_scan,
    "research_selection": action_research_selection,
}

if __name__ == "__main__":
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            print(clean({"success": False, "error": "invalid JSON"}))
            sys.stdout.flush()
            continue
        req_id = req.get("__id")
        action = req.get("action", "meta")
        handler = ACTIONS.get(action)
        if not handler:
            out = {"success": False, "error": f"unknown action: {action}"}
            if req_id: out["__id"] = req_id
            print(clean(out))
            sys.stdout.flush()
            continue
        try:
            result = handler(req)
            if req_id and isinstance(result, dict): result["__id"] = req_id
            print(clean(result))
        except Exception as e:
            import traceback
            out = {
                "success": False,
                "error": str(e)[:500],
                "traceback": traceback.format_exc()[:500],
            }
            if req_id: out["__id"] = req_id
            print(clean(out))
        sys.stdout.flush()

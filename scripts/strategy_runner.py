"""Strategy 引擎 API: 策略执行 + Event-Driven 回测 + 因子批量评估

Actions:
  meta           → 返回策略元信息
  run            → 执行策略并回测 (旧版简单回测)
  backtest       → 事件驱动回测 (新版 BacktestSimulator)
  batch_evaluate → 因子池批量 IC 评估 (47 因子全部跑一遍)
"""
import sys, json, os, math, time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache
from quant.data.loader import load_kline_df
from quant.factor import FactorEngine, ALL_FACTORS
from quant.strategy import StrategyEngine
from quant.backtest import BacktestSimulator


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
    return {"success": True, "data": result}


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
        "data": {
            "strategy_name": name,
            "params": params,
            "stocks": codes,
            "elapsed": round(elapsed, 2),
            "backtest": bt_result,
        }
    }


def action_batch_evaluate(req):
    """因子池批量 IC 评估 — 一次评估所有 47 因子"""
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


def action_market_scan(req=None):
    """全市场策略扫描结果 — 读取 data/strategy_scan.json (预计算)"""
    scan_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'strategy_scan.json')
    if not os.path.exists(scan_path):
        return {"success": False, "error": "尚未运行策略扫描，请先执行: python scripts/scan_strategies.py"}
    with open(scan_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return {"success": True, "data": data}


ACTIONS = {
    "meta": action_meta,
    "run": action_run,
    "backtest": action_backtest,
    "batch_evaluate": action_batch_evaluate,
    "factor_ic_detail": action_factor_ic_detail,
    "market_scan": action_market_scan,
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

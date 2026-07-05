"""Factor 引擎 API: 因子计算 + IC 评估

被 server/routes/factor.mjs 通过 spawn 调用 (stdin JSON → stdout JSON)

Actions:
  meta         → 返回 47 个因子元信息
  factors      → 对给定股票计算因子值 (code, start, end)
  evaluate     → IC 评估单因子 (factor_name)
  evaluate_all → 评估所有因子 IC, 按 |IC Mean| 排序
"""
import sys, json, os, math
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache
from quant.data.loader import load_kline_df
from quant.factor import FactorEngine

def _to_py(val):
    if isinstance(val, dict): return {k: _to_py(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)): return [_to_py(v) for v in val]
    if isinstance(val, (np.integer,)): return int(val)
    if isinstance(val, (float, np.floating)):
        return None if (math.isnan(val) or math.isinf(val)) else round(float(val), 6)
    return val

def clean(data): return json.dumps(_to_py(data))

cache = create_cache()
engine = FactorEngine(cache=cache)

def _norm(code):
    """去掉 .SZ/.SH/.BJ 后缀。Redis 存纯 6 位代码。"""
    return (code or "").split(".")[0]

def action_meta(req=None):
    """因子元信息 — 返回兼容前端 FactorPanel 的扁平 dict {name: {label,desc,category}}"""
    meta = engine.factor_meta()
    flat = {}
    for cat in meta.get("categories", []):
        cid = cat.get("id", "other")
        cname = cat.get("name", cid)
        for fname in cat.get("factors", []):
            flat[fname] = {
                "label": fname,        # 后端没存 label，用因子名
                "desc": f"{cname} 类因子",
                "category": cid,       # 用英文 id 作 category key，方便前端分组
                "category_name": cname,
            }
    return {"success": True, "data": flat}

def action_factors(req):
    code = _norm(req.get("code", ""))
    start = req.get("start", "")
    end = req.get("end", "")
    if not code: return {"success": False, "error": "code required"}
    raw = cache.get(f"kline:{code}:d")
    if not raw: return {"success": False, "error": f"no data for {code}"}
    df = load_kline_df(raw)
    if start: df = df[df['date'] >= start.replace('-', '')[:8]]
    if end: df = df[df['date'] <= end.replace('-', '')[:8]]
    if df.empty:
        return {"success": False, "error": "no data in range"}
    result = engine.compute_all(df)
    # Clean NaN/Inf
    cleaned = result.to_dict(orient='records')
    return {"success": True, "data": _to_py(cleaned)}

def action_evaluate(req):
    """单因子 IC 评估 (返回兼容前端 FactorPanel: data.summary + data.decay)"""
    codes = [_norm(c) for c in req.get("codes", [])]
    factor_name = req.get("factor_name", "")
    if not factor_name or not codes:
        return {"success": False, "error": "codes and factor_name required"}
    multi_factor = {}
    multi_klines = {}
    for code in codes:
        raw = cache.get(f"kline:{code}:d")
        if not raw: continue
        df = load_kline_df(raw)
        kdf = df.copy()
        pdf = engine.compute_all(df, code=code)
        multi_factor[code] = pdf
        multi_klines[code] = kdf
    if not multi_factor:
        return {"success": False, "error": "no data available"}
    result = engine.evaluate_all(multi_factor, multi_klines,
                                 factor_names=[factor_name] if factor_name else None,
                                 fwd_horizons=[1, 5, 10, 20])
    # evaluate_all 返回 list; 前端期望单个对象 {summary, decay}
    item = result[0] if result else {}
    return {"success": True, "data": _to_py(item)}


def action_evaluate_all(req):
    """批量因子 IC 评估 (返回兼容前端: {因子名: {fwd_1:{mean,ir}, ...}})

    性能保护: 基本面因子截面变化少、IC 意义有限且拖慢，默认排除；
    股票数限制在 15 只内避免长时间计算。
    """
    codes = [_norm(c) for c in req.get("codes", [])]
    if not codes:
        return {"success": False, "error": "codes required"}
    if len(codes) > 15:
        codes = codes[:15]  # 性能保护
    multi_factor = {}
    multi_klines = {}
    for code in codes:
        raw = cache.get(f"kline:{code}:d")
        if not raw: continue
        df = load_kline_df(raw)
        kdf = df.copy()
        pdf = engine.compute_all(df, code=code)
        multi_factor[code] = pdf
        multi_klines[code] = kdf
    # 默认只评估量价+技术因子 (跳过基本面，避免无意义 IC + 提速)
    from quant.factor.technical import TECHNICAL_FACTORS
    from quant.factor.price_volume import PRICE_VOLUME_FACTORS
    eval_factors = TECHNICAL_FACTORS + PRICE_VOLUME_FACTORS
    result = engine.evaluate_all(multi_factor, multi_klines, factor_names=eval_factors)
    # 转换: [{factor_name, summary, decay:{1d,5d,...}}] -> {因子名: {fwd_1:{mean,ir}, fwd_5:...}}
    out = {}
    # decay key 映射: 1d->fwd_1, 5d->fwd_5 ...
    _decay_to_fwd = lambda k: f"fwd_{int(str(k).rstrip('d'))}" if str(k).endswith('d') else k
    for item in result:
        fname = item.get("factor_name", "")
        decay = item.get("decay", {}) or {}
        fwd_dict = {}
        for dk, dv in decay.items():
            if isinstance(dv, dict):
                fwd_dict[_decay_to_fwd(dk)] = {
                    "mean": dv.get("mean", 0),
                    "ir": dv.get("ir", 0),
                    "std": dv.get("std", 0),
                    "positive_ratio": dv.get("positive_ratio", 0),
                }
        out[fname] = fwd_dict
    return {"success": True, "data": _to_py(out)}

def action_market_eval(req=None):
    """全市场因子评估结果 — 读取 data/factor_evaluation.json (5207只股票预计算)

    返回 {factors: [...], evaluated_at, n_stocks}
    每个因子: {factor, ic_1d, ir_1d, positive_1d, ic_5d, ir_5d, abs_ic_1d, n_periods}
    """
    eval_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'factor_evaluation.json')
    if not os.path.exists(eval_path):
        return {"success": False, "error": "尚未运行全市场评估，请先执行: python scripts/evaluate_factors.py"}
    with open(eval_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return {"success": True, "data": data}


def action_factor_stocks(req):
    """按因子值对全市场排序，返回多空选股明细

    性能优化: 首次计算全市场最新截面因子值并缓存(30分钟)，后续点击秒回。
    参数: factor_name (因子名), top_n (默认20), bottom_n (默认20)
    """
    import time as _time
    factor_name = req.get("factor_name", "ret_5")
    top_n = int(req.get("top_n", 20))
    bottom_n = int(req.get("bottom_n", 20))

    def _build_snapshot(limit: int = 300):
        keys = cache.keys('kline:*:d')[:limit]
        rows = []
        fe = FactorEngine(cache=None)
        for k in keys:
            bars = cache.get(k)
            if not bars or len(bars) < 30:
                continue
            code = k.split(':')[1]
            try:
                df = load_kline_df(bars)
                fdf = fe.compute_all(df, code=code)
                if fdf.empty:
                    continue
                latest = fdf.iloc[-1]
                close = float(latest.get('close', 0) or 0)
                prev_close = float(fdf.iloc[-2].get('close', close) or close) if len(fdf) >= 2 else close
                chg = round((close - prev_close) / prev_close * 100, 2) if prev_close else 0
                fvals = {}
                for col in fdf.columns:
                    if col in ('date', 'open', 'high', 'low', 'close', 'volume', 'amount'):
                        continue
                    v = latest.get(col)
                    try:
                        fv = float(v)
                        if not math.isnan(fv):
                            fvals[col] = round(fv, 4)
                    except Exception:
                        pass
                rows.append({
                    'code': code,
                    'name': cache.get(f'stock:name:{code}') or code,
                    'close': round(close, 2),
                    'change_pct': chg,
                    'factors': fvals,
                })
            except Exception:
                continue
        snap = {'rows': rows, '_ts': _time.time(), 'n': len(rows), 'source': 'factor_runner_fallback'}
        if rows:
            cache.set('factor:snapshot', snap, ttl=1800)
        return snap

    # 读截面缓存 (由 scripts/precompute_snapshot.py 预计算)
    snapshot = cache.get('factor:snapshot')
    if not snapshot or not snapshot.get('rows'):
        snapshot = _build_snapshot()
    if not snapshot or not snapshot.get('rows'):
        return {"success": False, "error": "尚未预计算因子截面，且即时构建失败"}

    rows = snapshot['rows']
    # 按指定因子排序
    valid = [r for r in rows if factor_name in r.get('factors', {})]
    if not valid:
        return {"success": False, "error": f"因子 {factor_name} 无有效数据"}

    valid.sort(key=lambda x: x['factors'][factor_name], reverse=True)
    top = [{'code': r['code'], 'name': r['name'], 'factor_value': r['factors'][factor_name],
            'close': r['close'], 'change_pct': r['change_pct']} for r in valid[:top_n]]
    bottom = [{'code': r['code'], 'name': r['name'], 'factor_value': r['factors'][factor_name],
               'close': r['close'], 'change_pct': r['change_pct']} for r in valid[-bottom_n:]]
    bottom.reverse()
    return {
        "success": True,
        "data": {
            "factor": factor_name,
            "top": top,
            "bottom": bottom,
            "n_stocks": len(valid),
        }
    }


ACTIONS = {
    "meta": action_meta,
    "factors": action_factors,
    "evaluate": action_evaluate,
    "evaluate_all": action_evaluate_all,
    "market_eval": action_market_eval,
    "market_evaluation": action_market_eval,  # 兼容 scripts/web_verify.mjs 旧 action
    "factor_stocks": action_factor_stocks,
}

if __name__ == "__main__":
    for line in sys.stdin:
        line = line.strip()
        if not line: continue
        try:
            req = json.loads(line)
        except Exception:
            print(clean({"success": False, "error": "invalid JSON"}))
            sys.stdout.flush(); continue
        req_id = req.get("__id")
        action = req.get("action", "meta")
        handler = ACTIONS.get(action)
        if not handler:
            out = {"success": False, "error": f"unknown action: {action}"}
            if req_id: out["__id"] = req_id
            print(clean(out))
            sys.stdout.flush(); continue
        try:
            result = handler(req)
            if req_id and isinstance(result, dict): result["__id"] = req_id
            print(clean(result))
        except Exception as e:
            out = {"success": False, "error": str(e)[:500]}
            if req_id: out["__id"] = req_id
            print(clean(out))
        sys.stdout.flush()

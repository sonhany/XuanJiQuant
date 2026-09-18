"""Factor 引擎 API: 因子计算 + IC 评估

被 server/routes/factor.mjs 通过 spawn 调用 (stdin JSON → stdout JSON)

Actions:
  meta         → 返回 58 个因子元信息
  factors      → 对给定股票计算因子值 (code, start, end)
  evaluate     → IC 评估单因子 (factor_name)
  evaluate_all → 评估所有因子 IC, 按 |IC Mean| 排序
"""
import sys, json, os, math, hashlib, time
from datetime import datetime
from pathlib import Path
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache
from quant.data.loader import load_kline_df
from quant.factor import FactorEngine
from quant.factor.input_contract import FactorInputContractError, load_factor_input_snapshot
from quant.factor.metadata import factor_chinese_name, factor_description
from quant.research.publication import (
    PublicationError,
    read_publication_status,
    resolve_complete_artifact,
)
from scripts.data_freshness import get_expected_date

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
ROOT_DIR = Path(__file__).resolve().parents[1]
RESEARCH_PUBLICATION_ROOT = ROOT_DIR / "data" / "research" / "daily"
SNAPSHOT_JSON_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "factor_snapshot_latest.json",
)
EVALUATION_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "factor_evaluation.json",
)
FACTOR_EVALUATE_ALL_CACHE_TTL = 1800
FACTOR_EVALUATE_CACHE_TTL = 1800
FACTOR_DATA_VERSION_CACHE_TTL = 60
_FACTOR_DATA_VERSION_CACHE = {}


def _completed_research_artifact(name, legacy_path):
    pointer_exists = (RESEARCH_PUBLICATION_ROOT / "latest.json").is_file()
    try:
        path = resolve_complete_artifact(RESEARCH_PUBLICATION_ROOT, name)
        with Path(path).open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise PublicationError("publication_artifact_schema_invalid")
        return value, True, read_publication_status(RESEARCH_PUBLICATION_ROOT)
    except (PublicationError, OSError, json.JSONDecodeError, TypeError, ValueError):
        if pointer_exists:
            return {}, True, read_publication_status(RESEARCH_PUBLICATION_ROOT)
        if not os.path.exists(legacy_path):
            return {}, False, {}
        try:
            with open(legacy_path, "r", encoding="utf-8") as handle:
                value = json.load(handle)
            return (value if isinstance(value, dict) else {}), False, {}
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return {}, False, {}


def _research_refresh(status, artifact, current_input=None):
    current_snapshot_id = getattr(current_input, "snapshot_id", None)
    current_data_version = getattr(current_input, "data_version", None)
    is_current = bool(
        current_snapshot_id
        and current_data_version
        and artifact.get("snapshot_id") == current_snapshot_id
        and artifact.get("data_version") == current_data_version
    )
    return is_current, {
        "state": status.get("state") or "completed",
        "target_date": status.get("target_date"),
        "generation_id": status.get("generation_id")
        or status.get("last_complete_generation_id"),
        "reason_code": status.get("reason_code"),
    }


def _kline_data_version(code):
    now = time.monotonic()
    cached = _FACTOR_DATA_VERSION_CACHE.get(code)
    if cached and now - cached[0] <= FACTOR_DATA_VERSION_CACHE_TTL:
        return list(cached[1])
    raw = cache.get(f"kline:{code}:d")
    if raw and isinstance(raw, list):
        last = raw[-1] or {}
        version = [code, len(raw), str(last.get("date") or ""), str(last.get("close") or "")]
    else:
        version = [code, 0, "", ""]
    _FACTOR_DATA_VERSION_CACHE[code] = (now, version)
    return list(version)


def _factor_data_version(codes):
    return [_kline_data_version(code) for code in codes]


def _factor_evaluate_all_cache_key(codes):
    payload = json.dumps({"codes": codes, "version": _factor_data_version(codes)}, ensure_ascii=False, sort_keys=True)
    return "factor:evaluate_all:" + hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _factor_evaluate_cache_key(codes, factor_name, fwd_horizons):
    payload = json.dumps({
        "codes": codes,
        "factor_name": factor_name,
        "fwd_horizons": [int(h) for h in fwd_horizons],
        "version": _factor_data_version(codes),
    }, ensure_ascii=False, sort_keys=True)
    return "factor:evaluate:" + hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _compute_single_factor_frame(df, code, factor_name):
    """Build a minimal factor frame for one IC factor instead of computing all factors."""
    try:
        series = engine.compute_one(df.copy(), factor_name, code=code)
        out = df[["date"]].copy()
        out[factor_name] = series.reset_index(drop=True)
        return out
    except Exception:
        fdf = engine.compute_all(df, code=code)
        if factor_name in fdf.columns:
            return fdf[["date", factor_name]].copy()
        return fdf


def _load_snapshot_json():
    if not os.path.exists(SNAPSHOT_JSON_PATH):
        return None
    try:
        with open(SNAPSHOT_JSON_PATH, "r", encoding="utf-8") as f:
            snap = json.load(f)
        return snap if snap.get("rows") else None
    except Exception:
        return None

def _norm(code):
    """去掉 .SZ/.SH/.BJ 后缀。Redis 存纯 6 位代码。"""
    return (code or "").split(".")[0]


def _available_kline_codes():
    out = []
    seen = set()
    for key in cache.keys("kline:*:d"):
        parts = str(key).split(":")
        code = _norm(parts[1] if len(parts) >= 3 else "")
        if code and code not in seen:
            seen.add(code)
            out.append(code)
    return out


def _supplement_codes(codes, min_count=3, max_count=None):
    """补足 IC 评估所需的最小横截面，避免请求里有缺失股票时静默返回空。"""
    out = []
    for code in codes:
        code = _norm(code)
        if code and code not in out:
            out.append(code)
    valid_count = sum(1 for code in out if _kline_data_version(code)[1] > 0)
    if valid_count >= min_count:
        return out[:max_count] if max_count else out
    for code in _available_kline_codes():
        if max_count and len(out) >= max_count:
            break
        if valid_count >= min_count:
            break
        if code in out:
            continue
        out.append(code)
        valid_count += 1
    return out[:max_count] if max_count else out

def action_meta(req=None):
    """Return flat factor metadata for the frontend."""
    meta = engine.factor_meta()
    flat = {}
    for cat in meta.get("categories", []):
        cid = cat.get("id", "other")
        cname = cat.get("name", cid)
        for fname in cat.get("factors", []):
            flat[fname] = {
                "label": factor_chinese_name(fname),
                "chinese_name": factor_chinese_name(fname),
                "desc": factor_description(fname) or f"{cname} 类因子",
                "category": cid,
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
    result = engine.compute_all(df, code=code)
    # Clean NaN/Inf
    cleaned = result.to_dict(orient='records')
    return {
        "success": True,
        "data": _to_py(cleaned),
        "diagnostic_only": True,
        "execution_authority": False,
    }

def action_evaluate(req):
    """单因子 IC 评估 (返回兼容前端 FactorPanel: data.summary + data.decay)"""
    codes = _supplement_codes(req.get("codes", []), min_count=3, max_count=30)
    factor_name = req.get("factor_name", "")
    if not factor_name or not codes:
        return {"success": False, "error": "codes and factor_name required"}
    fwd_horizons = req.get("fwd_horizons") or [1, 5, 10, 20]
    cache_key = _factor_evaluate_cache_key(codes, factor_name, fwd_horizons)
    cached = cache.get(cache_key)
    if isinstance(cached, dict) and cached.get("data"):
        return {"success": True, "data": cached["data"], "cache": {"hit": True, "key": cache_key, "ttl_seconds": FACTOR_EVALUATE_CACHE_TTL}}
    multi_factor = {}
    multi_klines = {}
    for code in codes:
        raw = cache.get(f"kline:{code}:d")
        if not raw: continue
        df = load_kline_df(raw)
        kdf = df.copy()
        pdf = _compute_single_factor_frame(df, code, factor_name)
        multi_factor[code] = pdf
        multi_klines[code] = kdf
    if not multi_factor:
        return {"success": False, "error": "no data available"}
    if len(multi_factor) < 3:
        return {"success": False, "error": "IC evaluation requires at least 3 stocks with kline data"}
    result = engine.evaluate_all(multi_factor, multi_klines,
                                 factor_names=[factor_name] if factor_name else None,
                                 fwd_horizons=fwd_horizons)
    # evaluate_all 返回 list; 前端期望单个对象 {summary, decay}
    # 当因子在所选股票中全 NaN (如基本面因子缺财务数据) 时 result 为空,
    # 此时返回明确的空结构, 而不是 {}, 避免前端访问 summary.mean 崩溃。
    if result:
        item = result[0]
    else:
        empty_summary = {"mean": None, "std": None, "ir": None,
                         "positive_ratio": None, "abs_mean": None, "n_periods": 0}
        item = {
            "factor_name": factor_name,
            "summary": empty_summary,
            "decay": {f"{h}d": dict(empty_summary) for h in fwd_horizons},
            "n_stocks": len(multi_factor),
            "empty_reason": "所选股票中该因子无有效数据 (可能为基本面因子且财务数据缺失)",
        }
    item = _to_py(item)
    cache.set(cache_key, {"data": item}, ttl=FACTOR_EVALUATE_CACHE_TTL)
    return {"success": True, "data": item, "cache": {"hit": False, "key": cache_key, "ttl_seconds": FACTOR_EVALUATE_CACHE_TTL}}


def action_evaluate_segments(req):
    codes = _supplement_codes(req.get("codes", []), min_count=3)
    factor_name = req.get("factor_name", "")
    if not factor_name or not codes:
        return {"success": False, "error": "codes and factor_name required"}
    multi_factor = {}
    multi_klines = {}
    for code in codes[:30]:
        raw = cache.get(f"kline:{code}:d")
        if not raw:
            continue
        df = load_kline_df(raw)
        multi_klines[code] = df.copy()
        multi_factor[code] = engine.compute_all(df, code=code)
    if not multi_factor:
        return {"success": False, "error": "no data available"}
    if len(multi_factor) < 3:
        return {"success": False, "error": "IC segment evaluation requires at least 3 stocks with kline data"}
    result = engine.evaluate_factor_segments(
        multi_factor,
        multi_klines,
        factor_name,
        fwd_horizons=req.get("fwd_horizons") or [1, 5, 10, 20],
    )
    return {"success": True, "data": _to_py(result)}


def action_evaluate_all(req):
    """批量因子 IC 评估 (返回兼容前端: {因子名: {fwd_1:{mean,ir}, ...})

    评估全部 58 因子 (技术+量价+基本面)。
    股票数限制在 15 只内避免长时间计算。
    """
    codes = _supplement_codes(req.get("codes", []), min_count=3, max_count=15)
    if not codes:
        return {"success": False, "error": "codes required"}
    if len(codes) > 15:
        codes = codes[:15]  # 性能保护
    cache_key = _factor_evaluate_all_cache_key(codes)
    cached = cache.get(cache_key)
    if isinstance(cached, dict) and cached.get("data"):
        return {"success": True, "data": cached["data"], "cache": {"hit": True, "key": cache_key, "ttl_seconds": FACTOR_EVALUATE_ALL_CACHE_TTL}}
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
    if len(multi_factor) < 3:
        return {"success": False, "error": "IC evaluation requires at least 3 stocks with kline data"}
    # 评估全部因子 (技术+量价+基本面)
    from quant.factor.technical import TECHNICAL_FACTORS
    from quant.factor.price_volume import PRICE_VOLUME_FACTORS
    from quant.factor.fundamental import FUNDAMENTAL_FACTORS
    eval_factors = TECHNICAL_FACTORS + PRICE_VOLUME_FACTORS + FUNDAMENTAL_FACTORS
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
    out = _to_py(out)
    cache.set(cache_key, {"data": out}, ttl=FACTOR_EVALUATE_ALL_CACHE_TTL)
    return {"success": True, "data": out, "cache": {"hit": False, "key": cache_key, "ttl_seconds": FACTOR_EVALUATE_ALL_CACHE_TTL}}


def _market_eval_snapshot_fallback():
    cached = cache.get('factor:market_eval:fallback')
    if cached and isinstance(cached, dict) and cached.get("factors"):
        return cached

    snapshot = cache.get('factor:snapshot') or _load_snapshot_json() or {}
    rows = snapshot.get("rows") or []
    factor_names = []
    for row in rows:
        for name in (row.get("factors") or {}).keys():
            if name not in factor_names:
                factor_names.append(name)
        if len(factor_names) >= 20:
            break
    preferred = ["volatility_20", "pvbeta_20", "ret_5", "ret_20", "trend_strength"]
    factor_names = [name for name in preferred if name in factor_names] + [
        name for name in factor_names if name not in preferred
    ]
    factors = [{
        "factor": name,
        "ic_1d": 0,
        "ir_1d": 0,
        "positive_1d": 0,
        "ic_5d": 0,
        "ir_5d": 0,
        "abs_ic_1d": 0,
        "n_periods": 0,
        "status": "pending_offline_evaluation",
    } for name in factor_names]
    result = {
        "factors": factors,
        "evaluated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "n_stocks": int(snapshot.get("n") or len(rows) or 0),
        "source": "snapshot_fallback",
        "warning": "factor_evaluation.json missing; run python scripts/evaluate_factors.py to refresh IC metrics",
    }
    cache.set('factor:market_eval:fallback', result, ttl=1800)
    return result


def _stock_name(code: str, snapshot_name: str = "") -> str:
    code = _norm(code)
    cached = cache.get(f"stock:name:{code}") if code else None
    if cached and str(cached).strip() and str(cached).strip() != code:
        return str(cached).strip()
    try:
        conn = getattr(cache, "_conn", None)
        if conn is not None and code:
            row = conn.execute("SELECT name FROM stock_daily_summary WHERE code = ? LIMIT 1", (code,)).fetchone()
            if row and row[0] and str(row[0]).strip() != code:
                return str(row[0]).strip()
    except Exception:
        pass
    name = str(snapshot_name or "").strip()
    return name if name and name != code else code


def _format_snapshot_time(snapshot: dict) -> str:
    ts = snapshot.get("_ts") or snapshot.get("saved_at")
    try:
        if ts:
            return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    try:
        if os.path.exists(SNAPSHOT_JSON_PATH):
            return datetime.fromtimestamp(os.path.getmtime(SNAPSHOT_JSON_PATH)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    return ""


def _latest_data_date(rows: list) -> str:
    latest = ""
    for row in rows:
        for key in ("date", "latest_date", "trade_date"):
            d = str(row.get(key) or "").replace("-", "")[:8]
            if len(d) == 8 and d.isdigit() and d > latest:
                latest = d
    if latest:
        return latest
    for row in rows:
        code = _norm(row.get("code"))
        bars = cache.get(f"kline:{code}:d") if code else None
        if bars and isinstance(bars, list):
            d = str((bars[-1] or {}).get("date") or (bars[-1] or {}).get("d") or "").replace("-", "")[:8]
            if len(d) == 8 and d.isdigit() and d > latest:
                latest = d
    if latest:
        return latest
    try:
        conn = getattr(cache, "_conn", None)
        if conn is not None:
            row = conn.execute("SELECT MAX(latest_date) FROM stock_daily_summary").fetchone()
            d = str(row[0] or "").replace("-", "")[:8] if row else ""
            if len(d) == 8 and d.isdigit():
                return d
    except Exception:
        pass
    return latest


def _factor_definition(factor_name: str) -> str:
    if factor_name == "range_pct":
        return "(high - low) / close"
    return factor_description(factor_name)


def action_market_eval(req=None):
    """全市场因子评估结果 — 读取 data/factor_evaluation.json (5207只股票预计算)

    返回 {factors: [...], evaluated_at, n_stocks}
    每个因子: {factor, ic_1d, ir_1d, positive_1d, ic_5d, ir_5d, abs_ic_1d, n_periods}
    """
    data, authoritative, publication_status = _completed_research_artifact(
        "factor_evaluation.json", EVALUATION_PATH
    )
    if not data:
        return {
            "success": False,
            "reason_code": "factor_evaluation_missing",
            "error": "尚未生成与当前通过快照绑定的全市场因子评估",
        }
    try:
        input_snapshot = load_factor_input_snapshot(
            cache,
            expected_date=get_expected_date(),
        )
    except FactorInputContractError as exc:
        if not authoritative:
            return {"success": False, "reason_code": exc.reason_code, "error": exc.detail}
        input_snapshot = None
    if authoritative:
        is_current, refresh = _research_refresh(publication_status, data, input_snapshot)
        return {
            "success": True,
            "data": {
                **data,
                "is_current": is_current,
                "research_refresh": refresh,
                "source": "research_generation_pointer",
            },
        }
    if (
        data.get("snapshot_id") != input_snapshot.snapshot_id
        or data.get("data_version") != input_snapshot.data_version
    ):
        return {
            "success": False,
            "reason_code": "factor_evaluation_version_mismatch",
            "error": "因子评估与当前通过的数据快照版本不一致，必须重新评估",
        }
    data = {**data, **input_snapshot.metadata(), "is_current": True}
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

    snapshot, authoritative, publication_status = _completed_research_artifact(
        "factor_snapshot_latest.json", SNAPSHOT_JSON_PATH
    )
    try:
        input_snapshot = load_factor_input_snapshot(
            cache,
            expected_date=get_expected_date(),
        )
    except FactorInputContractError as exc:
        if not authoritative:
            return {"success": False, "reason_code": exc.reason_code, "error": exc.detail}
        input_snapshot = None

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

    # 完成指针存在时只读不可变 generation；兼容路径仅服务尚未迁移的历史部署。
    if not authoritative:
        snapshot = cache.get('factor:snapshot')
        if not snapshot or not snapshot.get('rows'):
            snapshot = _load_snapshot_json()
            if snapshot and snapshot.get('rows'):
                cache.set('factor:snapshot', snapshot, ttl=1800)
    if not snapshot or not snapshot.get('rows'):
        return {
            "success": False,
            "reason_code": "factor_projection_missing",
            "error": "尚未生成与当前通过快照绑定的因子截面",
        }

    if not authoritative and (
        snapshot.get("snapshot_id") != input_snapshot.snapshot_id
        or snapshot.get("data_version") != input_snapshot.data_version
    ):
        return {
            "success": False,
            "reason_code": "factor_projection_version_mismatch",
            "error": "因子截面与当前通过的数据快照版本不一致，必须重新计算",
        }

    rows = snapshot['rows']
    # 按指定因子排序
    eligible_codes = set(input_snapshot.eligible_codes) if input_snapshot else set()
    valid = [
        r for r in rows
        if (authoritative or _norm(r.get("code")) in eligible_codes)
        and factor_name in r.get('factors', {})
    ]
    if not valid:
        return {"success": False, "error": f"因子 {factor_name} 无有效数据"}

    valid.sort(key=lambda x: x['factors'][factor_name], reverse=True)
    def _row(r):
        code = _norm(r.get('code'))
        return {
            'code': code,
            'name': _stock_name(code, r.get('name')),
            'factor_value': r['factors'][factor_name],
            'close': r.get('close', 0),
            'change_pct': r.get('change_pct', 0),
        }

    top = [_row(r) for r in valid[:top_n]]
    bottom = [_row(r) for r in valid[-bottom_n:]]
    bottom.reverse()
    data_latest_date = str(snapshot.get("latest_kline_date") or "").replace("-", "")[:8]
    if len(data_latest_date) != 8 or not data_latest_date.isdigit():
        data_latest_date = _latest_data_date(valid)
    expected_latest_date = str(get_expected_date() or "").replace("-", "")[:8]
    is_stale = bool(
        expected_latest_date
        and (not data_latest_date or data_latest_date < expected_latest_date)
    )
    response_metadata = input_snapshot.metadata() if input_snapshot else {}
    if authoritative:
        is_current, refresh = _research_refresh(
            publication_status, snapshot, input_snapshot
        )
        response_metadata = {
            "snapshot_id": snapshot.get("snapshot_id"),
            "data_version": snapshot.get("data_version"),
            "universe_version": snapshot.get("universe_version"),
            "universe_policy": snapshot.get("universe_policy"),
            "promotion_state": snapshot.get("promotion_state", "research_only"),
            "execution_authority": snapshot.get("execution_authority", False),
            "is_current": is_current,
            "research_refresh": refresh,
            "source": "research_generation_pointer",
        }
    return {
        "success": True,
        "data": {
            "factor": factor_name,
            "top": top,
            "bottom": bottom,
            "n_stocks": len(valid),
            "sort_basis": "latest_cross_section_factor_value",
            "sort_direction": "desc_for_top_asc_for_bottom",
            "factor_definition": _factor_definition(factor_name),
            "snapshot_generated_at": _format_snapshot_time(snapshot),
            "data_latest_date": data_latest_date,
            "expected_latest_date": expected_latest_date,
            "is_stale": is_stale,
            "freshness_warning": (
                f"因子截面已过期：数据日期 {data_latest_date or '未知'}，"
                f"预期至少 {expected_latest_date}；当前排名仅供历史参考。"
                if is_stale else None
            ),
            "snapshot_source": snapshot.get("source") or "factor:snapshot",
            **response_metadata,
        }
    }


ACTIONS = {
    "meta": action_meta,
    "factors": action_factors,
    "evaluate": action_evaluate,
    "evaluate_segments": action_evaluate_segments,
    "evaluate_all": action_evaluate_all,
    "market_eval": action_market_eval,
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

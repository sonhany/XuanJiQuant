"""Data 数据层 API: 股票列表 + Kline 查询 + Redis 状态

所有数据已通过 schema 校验，字段名固定为完整英文小写。
"""
import sys, json, os, math
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache
from quant.data.schema import REQUIRED_FIELDS

cache = create_cache()


class NpEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer,)): return int(obj)
        if isinstance(obj, (float, np.floating)):
            return None if (math.isnan(obj) or math.isinf(obj)) else round(float(obj), 6)
        return str(obj)


def j(data): return json.dumps(data, cls=NpEncoder, ensure_ascii=False)


def action_stocks(req=None):
    req = req or {}
    limit = int(req.get('limit', 200))
    universe = cache.get('stock:universe') or []
    codes = universe[:limit] if limit > 0 else universe
    stocks = []
    for code in codes:
        name = cache.get(f'stock:name:{code}') or code
        item = {"code": code, "name": name}
        # 尝试从 K 线尾部取涨跌幅
        raw = cache.get(f'kline:{code}:d')
        if raw and isinstance(raw, list) and len(raw) >= 2:
            try:
                last = raw[-1]
                prev = raw[-2]
                last_c = float(last.get('close', 0) or 0)
                prev_c = float(prev.get('close', 0) or 0)
                pct = ((last_c - prev_c) / prev_c * 100.0) if prev_c else 0.0
                item['change_pct'] = round(pct, 2)
                item['volume'] = int(last.get('volume', 0) or 0)
                item['amount'] = float(last.get('amount', 0) or 0)
            except Exception:
                item['change_pct'] = 0
                item['volume'] = 0
                item['amount'] = 0
        else:
            item['change_pct'] = 0
            item['volume'] = 0
            item['amount'] = 0
        stocks.append(item)
    return {"success": True, "data": {"count": len(stocks), "stocks": stocks}}


def _normalize_code(code: str) -> str:
    if not code:
        return ""
    return code.split(".")[0]


def action_klines(req):
    code = _normalize_code(req.get("code", ""))
    limit = int(req.get("limit", 300))
    if not code:
        return {"success": False, "error": "code required"}
    raw = cache.get(f"kline:{code}:d")
    if not raw:
        return {"success": True, "data": {"code": code, "klines": [], "count": 0}}
    # 数据已由 schema 校验，字段名固定
    rows = raw[-limit:] if limit > 0 else raw
    # 可选 start/end 过滤（YYYYMMDD）
    start = req.get("start")
    end = req.get("end")
    if start or end:
        rows = [r for r in rows
                if (not start or r.get('date', '') >= start.replace('-', ''))
                and (not end or r.get('date', '') <= end.replace('-', ''))]
    return {"success": True, "data": {
        "code": code, "klines": rows, "count": len(rows),
        "dateRange": {"from": rows[0]['date'] if rows else '', "to": rows[-1]['date'] if rows else ''}
    }}


def action_stats(req=None):
    # cache 已统一实现 size()/keys()，无需直连 .client
    dbsize = cache.size() if hasattr(cache, 'size') else 0
    kline_count = len(cache.keys("kline:*:d")) if hasattr(cache, 'keys') else 0
    universe = cache.get('stock:universe') or []
    return {"success": True, "data": {
        "dbsize": int(dbsize),
        "kline_count": kline_count,
        "universe_size": len(universe),
    }}


# ── 统一行情数据 actions (委托给 market_data 模块) ────────
def action_realtime_prices(req):
    """实时行情 — 委托 market_data.fetch_realtime。"""
    from scripts.market_data import fetch_realtime
    codes = req.get("codes") or []
    data = fetch_realtime(codes)
    return {"success": True, "data": data}


def action_indices(req=None):
    """全球指数 + 风险等级 — 委托 market_data.fetch_indices。"""
    from scripts.market_data import fetch_indices
    data = fetch_indices()
    return {"success": True, "data": data}


def action_sector_flow(req=None):
    """板块资金流 — 委托 market_data.fetch_sector_flow。"""
    from scripts.market_data import fetch_sector_flow
    data = fetch_sector_flow()
    return {"success": True, "data": data}


def action_northbound(req=None):
    """北向资金 — 委托 market_data.fetch_northbound。"""
    from scripts.market_data import fetch_northbound
    data = fetch_northbound()
    return {"success": True, "data": data}


WATCHLIST_KEY = "watchlist:default"
DEFAULT_WATCHLIST = ['000001','600519','600036','000858','300750','601318','600276','000333','601398','600030','601166','002594','000651','600887','601012','002475']


def _normalize_watch_code(code: str) -> str:
    """统一自选股代码为 6 位数字。支持 sh600519 / 600519.SH / 000001.SZ。"""
    c = str(code or "").strip().upper()
    c = c.replace(".SH", "").replace(".SZ", "")
    if c.startswith(("SH", "SZ")):
        c = c[2:]
    return c if len(c) == 6 and c.isdigit() else ""


def _load_watchlist() -> list:
    arr = cache.get(WATCHLIST_KEY)
    if not isinstance(arr, list):
        arr = DEFAULT_WATCHLIST
        cache.set(WATCHLIST_KEY, arr)
    out = []
    for code in arr:
        c = _normalize_watch_code(code)
        if c and c not in out:
            out.append(c)
    return out


def action_watchlist_get(req=None):
    return {"success": True, "data": {"codes": _load_watchlist()}}


def action_watchlist_set(req):
    raw = req.get("codes") or []
    if not isinstance(raw, list):
        return {"success": False, "error": "codes must be list"}
    codes = []
    for item in raw:
        c = _normalize_watch_code(item)
        if c and c not in codes:
            codes.append(c)
    cache.set(WATCHLIST_KEY, codes)
    return {"success": True, "data": {"codes": codes}}


def action_watchlist_add(req):
    code = _normalize_watch_code(req.get("code"))
    if not code:
        return {"success": False, "error": "请输入合法的6位A股代码"}
    codes = _load_watchlist()
    if code not in codes:
        codes.append(code)
        cache.set(WATCHLIST_KEY, codes)
    return {"success": True, "data": {"codes": codes}}


def action_watchlist_remove(req):
    code = _normalize_watch_code(req.get("code"))
    if not code:
        return {"success": False, "error": "code required"}
    codes = [c for c in _load_watchlist() if c != code]
    cache.set(WATCHLIST_KEY, codes)
    return {"success": True, "data": {"codes": codes}}


def action_watchlist_reset(req=None):
    cache.set(WATCHLIST_KEY, DEFAULT_WATCHLIST)
    return {"success": True, "data": {"codes": DEFAULT_WATCHLIST}}


ACTIONS = {
    "stocks": action_stocks,
    "klines": action_klines,
    "stats": action_stats,
    "realtime_prices": action_realtime_prices,
    "indices": action_indices,
    "sector_flow": action_sector_flow,
    "northbound": action_northbound,
    "watchlist_get": action_watchlist_get,
    "watchlist_set": action_watchlist_set,
    "watchlist_add": action_watchlist_add,
    "watchlist_remove": action_watchlist_remove,
    "watchlist_reset": action_watchlist_reset,
}

if __name__ == "__main__":
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            print(j({"success": False, "error": "invalid JSON"}))
            sys.stdout.flush()
            continue
        req_id = req.get("__id")
        action = req.get("action", "stats")
        handler = ACTIONS.get(action)
        if not handler:
            out = {"success": False, "error": f"unknown action: {action}"}
            if req_id: out["__id"] = req_id
            print(j(out))
            sys.stdout.flush()
            continue
        try:
            out = handler(req)
            if req_id and isinstance(out, dict): out["__id"] = req_id
            print(j(out))
        except Exception as e:
            import traceback
            traceback.print_exc()
            out = {"success": False, "error": str(e)[:500]}
            if req_id: out["__id"] = req_id
            print(j(out))
        sys.stdout.flush()

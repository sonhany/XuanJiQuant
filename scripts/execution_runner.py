"""Execution 引擎 v3: 通过 Node API 获取实时价格

改进：
- fetch_live_price() 通过 Node API (/api/market) 获取实时价格
- 市价单下单即成交，失败则标记 rejected
- 追踪止损检测
- 自动刷新持仓实时价格
"""
import sys, json, os, math, time, logging
from datetime import datetime
from typing import Optional, Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache
from quant.data.audit import write_order_event, write_trade_event
from quant.backtest.engine import is_limit_bar

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger("execution")

cache = create_cache()
STATE_KEY = "execution:state"
STOP_KEY  = "execution:stops"

COMMISSION_RATE = 0.0003      # 佣金 0.03%
MIN_COMMISSION = 5.0          # A股常见最低佣金
STAMP_TAX_RATE = 0.0005       # 卖出印花税 0.05%
TRANSFER_FEE_RATE = 0.00001   # 过户费近似
SLIPPAGE_RATE = 0.0001        # 模拟市价单滑点 0.01%

# ── Live Price Fetch via Node API ───────────────────────
def fetch_live_price(code: str) -> Optional[float]:
    """通过 Node /api/market 获取个股实时价格"""
    try:
        data = json.dumps({"action": "realtime_prices", "codes": [code]}).encode()
        import urllib.request
        req = urllib.request.Request(
            "http://localhost:3334/api/market",
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            result = json.loads(resp.read())
        if result.get("success") and result["data"]:
            return float(result["data"][code]["price"])
    except Exception as e:
        logger.debug(f"fetch_live_price({code}) failed: {e}")
    return None


def fetch_live_prices(codes: List[str]) -> Dict[str, float]:
    """批量获取实时价格"""
    if not codes:
        return {}
    try:
        data = json.dumps({"action": "realtime_prices", "codes": codes}).encode()
        import urllib.request
        req = urllib.request.Request(
            "http://localhost:3334/api/market",
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
        if result.get("success"):
            return {code: float(v["price"]) for code, v in result["data"].items()}
    except Exception as e:
        logger.warning(f"fetch_live_prices failed: {e}")
    return {}


# ── Redis kline fallback ────────────────────────────────
def _kline_bars(code: str) -> List[dict]:
    """从缓存读取日K，兼容 6 位代码和带后缀代码。"""
    candidates = [str(code).strip(), str(code).split('.')[0].strip()]
    seen = set()
    for c in candidates:
        if not c or c in seen:
            continue
        seen.add(c)
        try:
            raw = cache.get(f"kline:{c}:d")
            if isinstance(raw, list):
                return raw
        except Exception:
            continue
    return []


def _kline_price(code: str) -> Optional[float]:
    """从 Redis kline 获取最新收盘价"""
    try:
        raw = _kline_bars(code)
        if raw:
            bar = raw[-1]
            price = bar.get("close") or bar.get("c")
            if price:
                return float(price)
    except Exception:
        pass
    return None


def _latest_bar_info(code: str) -> dict:
    """返回最近bar和前收盘，用于涨跌停判断。数据不足时返回空 dict。"""
    bars = _kline_bars(code)
    if not bars:
        return {}
    last = bars[-1] or {}
    prev = bars[-2] if len(bars) >= 2 else {}
    try:
        return {
            "date": str(last.get("date") or last.get("d") or ""),
            "high": float(last.get("high") or last.get("h") or 0),
            "low": float(last.get("low") or last.get("l") or 0),
            "close": float(last.get("close") or last.get("c") or 0),
            "prev_close": float(prev.get("close") or prev.get("c") or 0),
            "amount": float(last.get("amount") or last.get("a") or 0),
        }
    except Exception:
        return {}


# ── State ──────────────────────────────────────────────
def _load_state() -> dict:
    raw = cache.get(STATE_KEY)
    if raw:
        return raw
    return {
        "initial_capital": 1_000_000.0, "cash": 1_000_000.0,
        "positions": {}, "orders": [], "trades": [],
        "order_counter": 0, "trade_counter": 0,
    }


def _save_state(s: dict):
    cache.set(STATE_KEY, s)


def _load_stops() -> dict:
    return cache.get(STOP_KEY) or {}


def _save_stops(stops: dict):
    cache.set(STOP_KEY, stops)


def _next_id(prefix: str, s: dict) -> str:
    ts = int(time.time() * 1000) % 1000000
    cnt = s.get(f"{prefix.lower()}_counter", 0) + 1
    s[f"{prefix.lower()}_counter"] = cnt
    return f"{prefix}{ts:06d}{cnt:03d}"


def _now() -> float:
    return time.time()


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _reject(order: Optional[dict], reason: str, message: str, s: Optional[dict] = None) -> dict:
    """标准化拒单返回；若传入订单则同步写入订单状态。"""
    if order is not None:
        order["status"] = "rejected"
        order["reject_reason"] = reason
        order["error"] = message
        order["filled_at"] = _now()
        if s is not None:
            _save_state(s)
        try:
            write_order_event(cache, order, source="execution_reject")
        except Exception:
            pass
    return {"success": False, "error": message, "reason": reason, "data": {"order": order} if order else None}


def _calc_fees(direction: str, notional: float) -> dict:
    commission = max(notional * COMMISSION_RATE, MIN_COMMISSION) if notional > 0 else 0.0
    stamp_tax = notional * STAMP_TAX_RATE if direction == "sell" else 0.0
    transfer_fee = notional * TRANSFER_FEE_RATE if notional > 0 else 0.0
    total = commission + stamp_tax + transfer_fee
    return {
        "commission": round(commission, 2),
        "stamp_tax": round(stamp_tax, 2),
        "transfer_fee": round(transfer_fee, 2),
        "total_fee": round(total, 2),
    }


def _resolve_fill_price(code: str, direction: str) -> Tuple[Optional[float], str]:
    price = fetch_live_price(code)
    source = "live"
    if not price or price <= 0:
        price = _kline_price(code)
        source = "kline"
    if not price or price <= 0:
        return None, "unavailable"
    slip = price * SLIPPAGE_RATE
    fill_price = price + slip if direction == "buy" else price - slip
    return round(fill_price, 4), source


def _is_t1_restricted(pos: dict, qty: int) -> bool:
    available = pos.get("available_qty")
    if available is not None:
        try:
            return int(available) < qty
        except Exception:
            pass
    return pos.get("entry_date") == _today()


def _refresh_available_qty(s: dict):
    """跨日后把持仓变为可卖；保持旧状态兼容。"""
    today = _today()
    changed = False
    for pos in s.get("positions", {}).values():
        qty = int(pos.get("quantity", 0))
        if pos.get("entry_date") != today and int(pos.get("available_qty", qty)) != qty:
            pos["available_qty"] = qty
            pos["today_buy_qty"] = 0
            changed = True
    if changed:
        _save_state(s)


def to_py(val):
    if isinstance(val, dict): return {k: to_py(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)): return [to_py(v) for v in val]
    if isinstance(val, __import__('numpy').integer): return int(val)
    if isinstance(val, (float, __import__('numpy').floating)):
        return None if (math.isnan(val) or math.isinf(val)) else round(float(val), 6)
    return val


# ── Core Fill Logic ────────────────────────────────────
def _do_fill(order_id: str, code: str, direction: str, fill_qty: int,
             fill_price: float, s: dict, *, price_source: str = "manual",
             fees: Optional[dict] = None) -> dict:
    notional = fill_qty * fill_price
    fees = fees or _calc_fees(direction, notional)
    total_fee = float(fees.get("total_fee", 0.0))
    pos = s["positions"].get(code)
    realized_pnl = 0.0

    if direction == "buy":
        total_cost = notional + total_fee
        if total_cost > s["cash"]:
            return {"success": False, "error": "现金不足", "reason": "cash_insufficient"}
        s["cash"] -= total_cost
        if pos:
            old_qty = int(pos.get("quantity", 0))
            new_qty = old_qty + fill_qty
            pos["avg_price"] = (pos["avg_price"] * old_qty + notional) / new_qty
            pos["quantity"] = new_qty
            pos["current_price"] = fill_price
            pos["today_buy_qty"] = int(pos.get("today_buy_qty", 0)) + fill_qty
            if pos.get("entry_date") != _today():
                pos["entry_date"] = _today()
        else:
            s["positions"][code] = {
                "code": code, "quantity": fill_qty,
                "avg_price": fill_price, "current_price": fill_price,
                "entry_date": _today(), "available_qty": 0,
                "today_buy_qty": fill_qty,
            }
    else:  # sell
        if not pos or int(pos.get("quantity", 0)) < fill_qty:
            return {"success": False, "error": "持仓不足", "reason": "position_insufficient"}
        if _is_t1_restricted(pos, fill_qty):
            return {"success": False, "error": "T+1限制：当日买入持仓不可卖出", "reason": "t1_restricted"}
        s["cash"] += notional - total_fee
        realized_pnl = (fill_price - pos["avg_price"]) * fill_qty - total_fee
        pos["quantity"] -= fill_qty
        pos["available_qty"] = max(0, int(pos.get("available_qty", pos["quantity"])) - fill_qty)
        pos["current_price"] = fill_price
        if pos["quantity"] <= 0:
            del s["positions"][code]
            stops = _load_stops()
            stops.pop(code, None)
            _save_stops(stops)

    trade = {
        "id": _next_id("T", s),
        "order_id": order_id,
        "code": code, "direction": direction,
        "quantity": fill_qty, "price": round(fill_price, 2),
        "timestamp": _now(),
        "realized_pnl": round(realized_pnl, 2),
        "notional": round(notional, 2),
        "price_source": price_source,
        **fees,
    }
    order = next((o for o in s["orders"] if o["id"] == order_id), None)
    if order:
        trade["run_id"] = order.get("run_id")
        trade["decision_id"] = order.get("decision_id")
    s["trades"].append(trade)
    try:
        write_trade_event(cache, trade, source="execution_fill")
    except Exception:
        pass

    # 建仓 (新建持仓) 自动设默认 trailing 止损, 不再依赖外部手动调用 set_stop_loss
    # 接通孤岛: 原 _do_fill 买入后从不设止损, 导致 trailing 检测永远不生效
    if direction == "buy" and s["positions"].get(code, {}).get("quantity") == fill_qty:
        # 仅新建仓时设 (加仓不覆盖已有止损线, 避免抬高止损)
        stops = _load_stops()
        if code not in stops or not stops[code].get("trailing_pct"):
            stops[code] = {"trailing_pct": 8.0, "highest_price": fill_price, "activated": False}
            _save_stops(stops)

    if order:
        order["filled_qty"] += fill_qty
        order["filled_price"] = fill_price
        order["filled_at"] = _now()
        order["status"] = "filled" if order["filled_qty"] >= order["quantity"] else "partial"
        order["price_source"] = price_source
        order["notional"] = round(notional, 2)
        order.update(fees)
        try:
            write_order_event(cache, order, source="execution_fill")
        except Exception:
            pass

    _save_state(s)
    return {"success": True, "data": {"order": order, "trade": trade}}


# ── Auto-fill market order ─────────────────────────────
def _auto_fill_market_order(order: dict, s: dict) -> dict:
    """获取价格并按A股模拟规则成交市价单。"""
    code = order["code"]
    direction = order["direction"]
    qty = int(order["quantity"])

    if direction not in ("buy", "sell"):
        return _reject(order, "invalid_direction", f"不支持的方向: {direction}", s)
    if qty <= 0:
        return _reject(order, "invalid_quantity", "数量必须为正数", s)
    if direction == "buy" and qty % 100 != 0:
        return _reject(order, "not_board_lot", "A股买入数量必须为100股整数倍", s)

    price, price_source = _resolve_fill_price(code, direction)
    if not price or price <= 0:
        return _reject(order, "price_unavailable", f"无法获取 {code} 有效价格，下单失败", s)

    bar = _latest_bar_info(code)
    if bar and bar.get("prev_close", 0) > 0:
        flag = is_limit_bar(code, bar["prev_close"], bar.get("high", 0), bar.get("low", 0), price, cache)
        if flag == 1 and direction == "buy":
            return _reject(order, "limit_up_locked", "涨停封板，模拟买入拒单", s)
        if flag == -1 and direction == "sell":
            return _reject(order, "limit_down_locked", "跌停封板，模拟卖出拒单", s)

    notional = qty * price
    fees = _calc_fees(direction, notional)
    if direction == "buy" and notional + fees["total_fee"] > s["cash"]:
        return _reject(order, "cash_insufficient", "现金不足", s)
    if direction == "sell":
        pos = s["positions"].get(code)
        if not pos or int(pos.get("quantity", 0)) < qty:
            return _reject(order, "position_insufficient", "持仓不足", s)
        if _is_t1_restricted(pos, qty):
            return _reject(order, "t1_restricted", "T+1限制：当日买入持仓不可卖出", s)

    result = _do_fill(order["id"], code, direction, qty, price, s, price_source=price_source, fees=fees)
    if result["success"] and direction == "buy":
        stops = _load_stops()
        stops[code] = {"trailing_pct": 0.0, "highest_price": price, "activated": False}
        _save_stops(stops)
    elif not result["success"]:
        return _reject(order, result.get("reason", "fill_failed"), result.get("error", "成交失败"), s)
    return result


# ── Refresh positions ──────────────────────────────────
def _refresh_position_prices(s: dict) -> List[dict]:
    """批量刷新持仓实时价格，检测追踪止损触发"""
    codes = list(s["positions"].keys())
    triggered = []
    if not codes:
        return triggered

    prices = fetch_live_prices(codes)
    stops = _load_stops()

    for code, pos in s["positions"].items():
        price = prices.get(code)
        if not price:
            price = _kline_price(code)
        if price:
            pos["current_price"] = price
            stop = stops.get(code)
            if stop and stop.get("trailing_pct", 0) > 0:
                hp = stop.get("highest_price", price)
                if price > hp:
                    stop["highest_price"] = price
                    stop["activated"] = False
                else:
                    drop_pct = (hp - price) / hp * 100 if hp else 0
                    if drop_pct >= stop["trailing_pct"]:
                        stop["activated"] = True
                        triggered.append({
                            "code": code, "reason": "trailing_stop",
                            "price": price, "highest": hp,
                            "drop_pct": round(drop_pct, 2),
                        })

    _save_stops(stops)
    _save_state(s)
    return triggered


# ── Actions ────────────────────────────────────────────
def action_status(req=None):
    s = _load_state()
    _refresh_available_qty(s)
    _refresh_position_prices(s)
    total_mv = sum(p["quantity"] * p["current_price"] for p in s["positions"].values())
    total_eq = s["cash"] + total_mv
    total_pnl = total_eq - s["initial_capital"]
    return {"success": True, "data": {
        "initial_capital": s["initial_capital"],
        "cash": round(s["cash"], 2),
        "market_value": round(total_mv, 2),
        "total_equity": round(total_eq, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl / s["initial_capital"] * 100, 2),
        "position_count": len(s["positions"]),
        "order_count": len(s["orders"]),
        "trade_count": len(s["trades"]),
    }}


def action_positions(req=None):
    s = _load_state()
    _refresh_available_qty(s)
    _refresh_position_prices(s)
    return {"success": True, "data": [{
        "code": p["code"], "quantity": p["quantity"],
        "available_qty": int(p.get("available_qty", p["quantity"])),
        "today_buy_qty": int(p.get("today_buy_qty", 0)),
        "avg_price": round(p["avg_price"], 2),
        "current_price": round(p.get("current_price", p["avg_price"]), 2),
        "market_value": round(p["quantity"] * p.get("current_price", p["avg_price"]), 2),
        "cost": round(p["quantity"] * p["avg_price"], 2),
        "pnl": round((p.get("current_price", p["avg_price"]) - p["avg_price"]) * p["quantity"], 2),
        "pnl_pct": round((p.get("current_price", p["avg_price"]) - p["avg_price"]) / p["avg_price"] * 100, 2) if p["avg_price"] else 0,
        "entry_date": p.get("entry_date", "-"),
    } for p in s["positions"].values()]}


def action_place_order(req):
    for f in ("code", "direction", "quantity"):
        if f not in req:
            return {"success": False, "error": f"missing: {f}"}
    s = _load_state()
    _refresh_available_qty(s)
    order = {
        "id": _next_id("O", s),
        "code": str(req["code"]).strip(),
        "direction": req["direction"],
        "order_type": req.get("order_type", "market"),
        "quantity": int(req["quantity"]),
        "price": float(req.get("price") or 0),
        "status": "pending",
        "filled_qty": 0, "filled_price": 0.0,
        "created_at": _now(), "filled_at": 0,
        "source": req.get("source", "manual"),
        "run_id": req.get("run_id"),
        "decision_id": req.get("decision_id"),
    }
    s["orders"].append(order)
    _save_state(s)

    if order["order_type"] == "market":
        result = _auto_fill_market_order(order, s)
        if not result["success"]:
            order["status"] = "rejected"
            order["reject_reason"] = result.get("reason")
            order["error"] = result.get("error")
            _save_state(s)
            return result
        # 市价单已自动成交。在 data 顶层补 id/order，
        # 兼容前端 place_order 后读 r.id 的契约 (ExecutionPanel.tsx)
        if isinstance(result.get("data"), dict):
            result["data"]["id"] = order["id"]
            result["data"]["order"] = result["data"].get("order", order)
        return result

    return {"success": True, "data": order}


def action_fill_order(req):
    if "order_id" not in req:
        return {"success": False, "error": "missing: order_id"}
    s = _load_state()
    order = next((o for o in s["orders"] if o["id"] == req["order_id"]), None)
    if not order:
        return {"success": False, "error": "订单不存在"}
    if order.get("status") not in ("pending", "partial"):
        return {
            "success": False,
            "error": f"order status {order.get('status')} cannot be filled",
            "reason": "order_not_fillable",
            "data": {"order": order},
        }
    fill_price = float(req.get("fill_price", 0))
    remaining_qty = int(order.get("quantity", 0)) - int(order.get("filled_qty", 0))
    fill_qty = int(req.get("fill_qty") if req.get("fill_qty") else remaining_qty)
    if fill_qty <= 0:
        return {
            "success": False,
            "error": "no remaining quantity to fill",
            "reason": "no_remaining_quantity",
            "data": {"order": order},
        }
    if fill_qty > remaining_qty:
        return {
            "success": False,
            "error": f"fill_qty {fill_qty} exceeds remaining quantity {remaining_qty}",
            "reason": "fill_qty_exceeds_remaining",
            "data": {"order": order},
        }
    return _do_fill(order["id"], order["code"], order["direction"], fill_qty, fill_price, s)


def action_cancel_order(req):
    if "order_id" not in req:
        return {"success": False, "error": "missing: order_id"}
    s = _load_state()
    order = next((o for o in s["orders"] if o["id"] == req["order_id"]), None)
    if not order:
        return {"success": False, "error": "订单不存在"}
    if order["status"] not in ("pending", "partial"):
        return {"success": False, "error": f"订单状态 {order['status']} 不可撤销"}
    order["status"] = "cancelled"
    _save_state(s)
    return {"success": True, "data": order}


def action_update_price(req=None):
    s = _load_state()
    _refresh_available_qty(s)
    triggered = _refresh_position_prices(s)
    return {"success": True, "data": {"updated": len(s["positions"]), "stop_triggered": triggered}}


def action_set_stop_loss(req):
    code = str(req.get("code", "")).strip()
    trailing_pct = float(req.get("trailing_pct", 0))
    if not code:
        return {"success": False, "error": "missing: code"}
    s = _load_state()
    if code not in s["positions"]:
        return {"success": False, "error": "无持仓"}
    stops = _load_stops()
    current_price = s["positions"][code].get("current_price", 0)
    stops[code] = {"trailing_pct": trailing_pct, "highest_price": current_price, "activated": False}
    _save_stops(stops)
    return {"success": True, "data": stops[code]}


def action_all(req=None):
    s = _load_state()
    _refresh_available_qty(s)
    triggered = _refresh_position_prices(s)
    total_mv = sum(p["quantity"] * p["current_price"] for p in s["positions"].values())
    total_eq = s["cash"] + total_mv
    total_pnl = total_eq - s["initial_capital"]
    stops = _load_stops()
    return {"success": True, "data": {
        "status": {
            "initial_capital": s["initial_capital"],
            "cash": round(s["cash"], 2),
            "market_value": round(total_mv, 2),
            "total_equity": round(total_eq, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl / s["initial_capital"] * 100, 2),
            "position_count": len(s["positions"]),
            "order_count": len(s["orders"]),
            "trade_count": len(s["trades"]),
        },
        "orders": sorted(s["orders"], key=lambda o: o["created_at"], reverse=True)[:50],
        "trades": sorted(s["trades"], key=lambda t: t["timestamp"], reverse=True)[:50],
        "positions": [{
            "code": p["code"], "quantity": p["quantity"],
            "available_qty": int(p.get("available_qty", p["quantity"])),
            "today_buy_qty": int(p.get("today_buy_qty", 0)),
            "avg_price": round(p["avg_price"], 2),
            "current_price": round(p.get("current_price", p["avg_price"]), 2),
            "market_value": round(p["quantity"] * p.get("current_price", p["avg_price"]), 2),
            "cost": round(p["quantity"] * p["avg_price"], 2),
            "pnl": round((p.get("current_price", p["avg_price"]) - p["avg_price"]) * p["quantity"], 2),
            "pnl_pct": round((p.get("current_price", p["avg_price"]) - p["avg_price"]) / p["avg_price"] * 100, 2) if p["avg_price"] else 0,
            "entry_date": p.get("entry_date", "-"),
            "stop": stops.get(p["code"]),
        } for p in s["positions"].values()],
        "stop_triggered": triggered,
    }}


def action_reset(req=None):
    s = {"initial_capital": 1_000_000.0, "cash": 1_000_000.0,
         "positions": {}, "orders": [], "trades": [], "order_counter": 0, "trade_counter": 0,
         "rules": {"commission_rate": COMMISSION_RATE, "min_commission": MIN_COMMISSION,
                   "stamp_tax_rate": STAMP_TAX_RATE, "transfer_fee_rate": TRANSFER_FEE_RATE,
                   "slippage_rate": SLIPPAGE_RATE}}
    _save_state(s)
    _save_stops({})
    return action_status()


def action_orders(req=None):
    """返回订单列表。可选 status=pending/filled/rejected/cancelled 过滤、limit。"""
    s = _load_state()
    orders = list(s.get("orders", []))
    if req:
        st = req.get("status")
        if st:
            orders = [o for o in orders if o.get("status") == st]
        code = req.get("code")
        if code:
            orders = [o for o in orders if o.get("code") == code]
        limit = int(req.get("limit", 200))
        orders = orders[-limit:]
    return {"success": True, "data": orders}


def action_trades(req=None):
    """返回成交列表。可选 code 过滤、limit。"""
    s = _load_state()
    trades = list(s.get("trades", []))
    if req:
        code = req.get("code")
        if code:
            trades = [t for t in trades if t.get("code") == code]
        limit = int(req.get("limit", 200))
        trades = trades[-limit:]
    return {"success": True, "data": trades}


# ── 止盈止损自动检查 (接通孤岛) ───────────────────────────
# 原 _refresh_position_prices 只检测 trailing 触发但不下单, 这里补上下单闭环。
# 硬止损: 个股相对成本跌幅 <= -8% 直接全平 (不经 LLM, 不可被 AI 覆盖)。
# 移动止盈: trailing_pct 回撤达阈值全平 (复用已有 trailing 检测)。
HARD_STOP_PCT = -8.0  # 个股硬止损线 (%)


def action_check_stops(req=None):
    """检查所有持仓的止盈止损, 触发则自动下卖单全平。

    被 ai_scheduler 盘中轻巡检调用 (每 10 分钟一次)。
    硬规则: 不经过 LLM, 直接平仓, 是不可被 AI 覆盖的安全网。
    """
    s = _load_state()
    triggered = _refresh_position_prices(s)  # 已有: trailing 检测 + 价格刷新

    # 硬止损检测: 相对成本跌幅 <= -8%
    extra = []
    for code, pos in s["positions"].items():
        price = float(pos.get("current_price", 0) or 0)
        cost = float(pos.get("avg_price", 0) or 0)
        if cost > 0 and price > 0:
            pnl_pct = (price / cost - 1) * 100
            if pnl_pct <= HARD_STOP_PCT:
                extra.append({"code": code, "reason": "hard_stop",
                              "price": price, "pnl_pct": round(pnl_pct, 2)})

    # 对所有触发项真正下卖单 (全平)
    executed = []
    for t in triggered + extra:
        code = t["code"]
        s = _load_state()  # 重新加载, 避免前一笔卖出导致状态不一致
        pos = s["positions"].get(code)
        if not pos:
            continue
        qty = int(pos.get("quantity", 0) or 0)
        if qty <= 0:
            continue
        r = action_place_order({"code": code, "direction": "sell",
                                "quantity": qty, "order_type": "market",
                                "source": "stop_check"})
        executed.append({"code": code, "reason": t["reason"], "qty": qty,
                         "success": r.get("success"), "pnl_pct": t.get("pnl_pct")})
        logger.info(f"[止损检查] {code} {t['reason']} 平仓 {qty}股 "
                    f"pnl={t.get('pnl_pct', '?')}% success={r.get('success')}")

    return {"success": True, "checked": len(_load_state().get("positions", {})),
            "triggered": len(triggered + extra), "executed": executed}


def action_stop_status(req=None):
    """读取所有持仓的止损状态 (供驾驶舱展示)。"""
    s = _load_state()
    stops = _load_stops()
    out = []
    for code, pos in s["positions"].items():
        st = stops.get(code, {})
        cost = float(pos.get("avg_price", 0) or 0)
        price = float(pos.get("current_price", 0) or 0)
        pnl_pct = (price / cost - 1) * 100 if cost > 0 and price > 0 else 0
        out.append({
            "code": code,
            "qty": int(pos.get("quantity", 0) or 0),
            "cost": cost,
            "current_price": price,
            "pnl_pct": round(pnl_pct, 2),
            "trailing_pct": st.get("trailing_pct", 0),
            "highest_price": st.get("highest_price", cost),
            "activated": st.get("activated", False),
        })
    return {"success": True, "data": out}


ACTIONS = {
    "all": action_all, "status": action_status, "positions": action_positions,
    "orders": action_orders, "trades": action_trades,
    "place_order": action_place_order, "fill_order": action_fill_order,
    "cancel_order": action_cancel_order, "update_price": action_update_price,
    "set_stop_loss": action_set_stop_loss,
    "check_stops": action_check_stops,
    "stop_status": action_stop_status,
    "reset": action_reset,
}


if __name__ == "__main__":
    logger.info("execution_runner v3 started")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            print(json.dumps({"success": False, "error": "invalid JSON"}))
            sys.stdout.flush()
            continue
        req_id = req.get("__id")
        action = req.get("action", "status")
        handler = ACTIONS.get(action)
        if not handler:
            out = {"success": False, "error": f"unknown action: {action}"}
            if req_id: out["__id"] = req_id
            print(json.dumps(out))
            sys.stdout.flush()
            continue
        try:
            result = handler(req)
            result = to_py(result)
            if req_id and isinstance(result, dict): result["__id"] = req_id
            print(json.dumps(result))
        except Exception as e:
            import traceback
            traceback.print_exc()
            out = {"success": False, "error": str(e)[:500]}
            if req_id: out["__id"] = req_id
            print(json.dumps(out))
        sys.stdout.flush()

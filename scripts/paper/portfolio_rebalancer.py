"""Target-portfolio rebalancing for the paper sandbox."""
from __future__ import annotations


def execute_target_portfolio(*, target_weights: list, klines_dict: dict, pos_map: dict,
                             equity: float, cfg: dict, summary: dict,
                             last_close_fn, pretrade_check_fn, place_fn) -> bool:
    """Rebalance toward target weights. Returns True when handled."""
    if not target_weights:
        return False
    weight_map = {x["code"]: float(x["target_weight"]) for x in target_weights}
    target_codes = set(weight_map)
    current_codes = {c for c, p in pos_map.items() if int(p.get("quantity", 0) or 0) > 0}
    all_codes = sorted(target_codes | current_codes)
    orders = []
    for code in all_codes:
        pos = pos_map.get(code)
        pos_qty = int(pos.get("quantity", 0)) if pos else 0
        price = float(pos.get("current_price") or pos.get("avg_price") or 0) if pos else 0.0
        if price <= 0:
            price = last_close_fn(klines_dict, code)
        if price <= 0:
            summary.setdefault("skipped_orders", []).append({"code": code, "reason": "no_price"})
            continue
        target_weight = weight_map.get(code, 0.0)
        target_qty = int(equity * target_weight / price / 100) * 100 if target_weight > 0 else 0
        if target_weight > 0 and target_qty <= 0:
            target_qty = 100
        delta = target_qty - pos_qty
        if delta < 0:
            orders.append((0, code, "sell", abs(delta), price, target_weight))
        elif delta > 0:
            orders.append((1, code, "buy", delta, price, target_weight))

    orders.sort(key=lambda x: x[0])
    summary["portfolio_mode"] = "target_weights"
    summary["target_weights"] = target_weights
    summary["target_vs_actual"] = []
    for _, code, direction, qty, price, target_weight in orders:
        if pretrade_check_fn(code, direction, qty, price):
            ok = place_fn(code, direction, qty)
            if ok:
                summary.setdefault("signals", []).append({
                    "code": code,
                    "signal": 1 if target_weight > 0 else 0,
                    "action": f"target_{direction}",
                    "qty": qty,
                    "price": price,
                    "target_weight": round(target_weight, 4),
                })
        summary["target_vs_actual"].append({
            "code": code,
            "direction": direction,
            "qty": qty,
            "price": price,
            "target_weight": round(target_weight, 4),
        })
    summary["order_count"] = len(summary.get("orders", []))
    return True


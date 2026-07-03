"""执行引擎: 订单管理 + 持仓追踪 + 组合损益

模拟交易执行，不连接真实券商。
状态保存在内存中（重启后重置）。
"""
import logging
import time
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger("quant.execution")


@dataclass
class Order:
    id: str
    code: str
    direction: str  # buy / sell
    order_type: str  # market / limit
    quantity: int
    price: float  # 0 for market orders
    status: str  # pending / filled / cancelled / partial
    filled_qty: int = 0
    filled_price: float = 0.0
    created_at: float = 0.0
    filled_at: float = 0.0


@dataclass
class Position:
    code: str
    quantity: int
    avg_price: float
    current_price: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0


@dataclass
class Trade:
    id: str
    code: str
    direction: str
    quantity: int
    price: float
    pnl: float = 0.0
    timestamp: float = 0.0


class ExecutionEngine:
    """模拟交易执行引擎"""

    def __init__(self, initial_capital: float = 1000000.0):
        self._initial_capital = initial_capital
        self._cash = initial_capital
        self._positions: Dict[str, Position] = {}  # code -> Position
        self._orders: List[Order] = []
        self._trades: List[Trade] = []
        self._order_counter = 0
        self._trade_counter = 0

    # ── 订单管理 ──────────────────────────────────────

    def place_order(self, code: str, direction: str, quantity: int,
                    order_type: str = "market", price: float = 0.0) -> dict:
        """提交订单

        Args:
            code: 股票代码
            direction: buy / sell
            quantity: 数量 (正数)
            order_type: market / limit
            price: limit 价格 (market 时给 0)

        Returns: order dict
        """
        self._order_counter += 1
        order_id = f"O{int(time.time() * 1000)}{self._order_counter}"
        order = Order(
            id=order_id, code=code, direction=direction,
            order_type=order_type, quantity=quantity,
            price=price, status="pending",
            created_at=time.time(),
        )
        self._orders.append(order)
        return self._order_to_dict(order)

    def fill_order(self, order_id: str, fill_price: float,
                   fill_qty: Optional[int] = None) -> dict:
        """手动成交订单（模拟滑点/部分成交）"""
        for order in self._orders:
            if order.id == order_id:
                qty = fill_qty or order.quantity
                cost = qty * fill_price
                if order.direction == "buy" and cost > self._cash:
                    return {"success": False, "error": "现金不足"}
                if order.direction == "sell":
                    pos = self._positions.get(order.code)
                    if not pos or pos.quantity < qty:
                        return {"success": False, "error": "持仓不足"}

                # 更新现金
                if order.direction == "buy":
                    self._cash -= cost
                else:
                    self._cash += cost

                # 更新持仓
                pos = self._positions.get(order.code)
                if order.direction == "buy":
                    if pos:
                        new_qty = pos.quantity + qty
                        pos.avg_price = (pos.avg_price * pos.quantity + cost) / new_qty
                        pos.quantity = new_qty
                    else:
                        self._positions[order.code] = Position(
                            code=order.code, quantity=qty, avg_price=fill_price
                        )
                else:  # sell
                    if pos:
                        pos.pnl += (fill_price - pos.avg_price) * qty
                        pos.quantity -= qty
                        if pos.quantity <= 0:
                            del self._positions[order.code]

                # 记录成交
                self._trade_counter += 1
                trade = Trade(
                    id=f"T{int(time.time() * 1000)}{self._trade_counter}",
                    code=order.code, direction=order.direction,
                    quantity=qty, price=fill_price,
                    pnl=(fill_price - pos.avg_price) * qty if order.direction == "sell" and pos else 0.0,
                    timestamp=time.time(),
                )
                self._trades.append(trade)

                # 更新订单状态
                order.filled_qty += qty
                order.filled_price = (order.filled_price * (order.filled_qty - qty) + fill_price * qty) / order.filled_qty if order.filled_qty else fill_price
                order.filled_at = time.time()
                if order.filled_qty >= order.quantity:
                    order.status = "filled"
                else:
                    order.status = "partial"

                return {"success": True, "order": self._order_to_dict(order), "trade": self._trade_to_dict(trade)}
        return {"success": False, "error": f"订单不存在: {order_id}"}

    def cancel_order(self, order_id: str) -> dict:
        for order in self._orders:
            if order.id == order_id and order.status == "pending":
                order.status = "cancelled"
                return {"success": True}
        return {"success": False, "error": "订单不存在或已成交"}

    # ── 查询 ──────────────────────────────────────────

    def get_portfolio(self) -> dict:
        total_market_value = sum(
            p.quantity * p.current_price for p in self._positions.values()
        )
        total_equity = self._cash + total_market_value
        total_pnl = total_equity - self._initial_capital
        return {
            "initial_capital": self._initial_capital,
            "cash": round(self._cash, 2),
            "market_value": round(total_market_value, 2),
            "total_equity": round(total_equity, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl / self._initial_capital * 100, 2) if self._initial_capital else 0,
            "position_count": len(self._positions),
            "order_count": len(self._orders),
            "trade_count": len(self._trades),
        }

    def get_positions(self) -> list:
        return [self._position_to_dict(p) for p in self._positions.values()]

    def get_orders(self, status: Optional[str] = None, limit: int = 50) -> list:
        orders = self._orders
        if status:
            orders = [o for o in orders if o.status == status]
        orders = sorted(orders, key=lambda o: o.created_at, reverse=True)[:limit]
        return [self._order_to_dict(o) for o in orders]

    def get_trades(self, limit: int = 50) -> list:
        trades = sorted(self._trades, key=lambda t: t.timestamp, reverse=True)[:limit]
        return [self._trade_to_dict(t) for t in trades]

    def update_prices(self, prices: Dict[str, float]):
        """更新持仓市价，重算浮动盈亏"""
        for code, price in prices.items():
            pos = self._positions.get(code)
            if pos:
                pos.current_price = price
                pos.pnl = (price - pos.avg_price) * pos.quantity
                pos.pnl_pct = round((price - pos.avg_price) / pos.avg_price * 100, 2) if pos.avg_price else 0

    def reset(self):
        self.__init__(self._initial_capital)

    # ── 内部转换 ──────────────────────────────────────

    @staticmethod
    def _order_to_dict(o: Order) -> dict:
        return {
            "id": o.id, "code": o.code, "direction": o.direction,
            "order_type": o.order_type, "quantity": o.quantity,
            "price": o.price, "status": o.status,
            "filled_qty": o.filled_qty, "filled_price": round(o.filled_price, 2),
            "created_at": o.created_at,
        }

    @staticmethod
    def _position_to_dict(p: Position) -> dict:
        return {
            "code": p.code, "quantity": p.quantity,
            "avg_price": round(p.avg_price, 2),
            "current_price": round(p.current_price, 2),
            "market_value": round(p.quantity * p.current_price, 2),
            "cost": round(p.quantity * p.avg_price, 2),
            "pnl": round(p.pnl, 2), "pnl_pct": round(p.pnl_pct, 2),
        }

    @staticmethod
    def _trade_to_dict(t: Trade) -> dict:
        return {
            "id": t.id, "code": t.code, "direction": t.direction,
            "quantity": t.quantity, "price": round(t.price, 2),
            "pnl": round(t.pnl, 2), "timestamp": t.timestamp,
        }

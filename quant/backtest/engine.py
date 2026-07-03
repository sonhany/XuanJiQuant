"""Event-Driven Backtest Engine (Phase 2)

核心设计:
- 事件驱动模拟器: 按时间顺序重放K线数据
- 事件类型: PRICE_BAR, SIGNAL, ORDER, FILL, POSITION_UPDATE, PORTFOLIO_UPDATE
- 仓位跟踪: 实时组合状态 (positions, cash, equity)
- 滑点/手续费模型: 可配置
- 绩效指标: 年化收益/夏普/最大回撤/胜率

使用:
    sim = BacktestSimulator(initial_cash=1_000_000)
    sim.add_signals(signal_dict)          # {code: [{"date": "20260601", "signal": 1}, ...]}
    sim.add_klines(klines_dict)           # {code: DataFrame}
    result = sim.run()
"""
import logging
import uuid
import time
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

import numpy as np
import pandas as pd

from quant.data.cache import create_cache

logger = logging.getLogger("quant.backtest")


class EventType(Enum):
    PRICE_BAR = "price_bar"
    SIGNAL = "signal"
    ORDER = "order"
    FILL = "fill"
    POSITION_UPDATE = "position_update"
    PORTFOLIO_UPDATE = "portfolio_update"


@dataclass
class PriceBar:
    code: str
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Signal:
    code: str
    date: str
    signal: int          # 1=long, -1=short, 0=flat
    score: float = 0.0
    metadata: dict = field(default_factory=dict)


@dataclass
class Order:
    id: str
    code: str
    date: str
    direction: str       # "buy" or "sell"
    quantity: int
    price: float = 0.0
    order_type: str = "market"
    status: str = "pending"  # pending / filled / cancelled / rejected


@dataclass
class Fill:
    id: str
    order_id: str
    code: str
    date: str
    direction: str
    quantity: int
    price: float
    commission: float
    slippage: float


@dataclass
class Position:
    code: str
    quantity: int = 0
    avg_entry_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0

    @property
    def market_value(self) -> float:
        return self.quantity * self.avg_entry_price


@dataclass
class PortfolioSnapshot:
    date: str
    total_equity: float
    cash: float
    market_value: float
    net_exposure: float
    gross_exposure: float
    positions: dict
    daily_return: float = 0.0
    drawdown: float = 0.0


class PerformanceTracker:
    """记录每日组合快照，计算绩效指标"""

    def __init__(self, initial_equity: float):
        self.initial_equity = initial_equity
        self.snapshots: list[PortfolioSnapshot] = []
        self.peak_equity = initial_equity

    def add_snapshot(self, snap: PortfolioSnapshot):
        self.snapshots.append(snap)
        if snap.total_equity > self.peak_equity:
            self.peak_equity = snap.total_equity
        # update drawdown
        drawdown = (self.peak_equity - snap.total_equity) / self.peak_equity if self.peak_equity > 0 else 0
        snap.drawdown = drawdown

    def compute_metrics(self) -> dict:
        if not self.snapshots:
            return {}
        snaps = self.snapshots
        equity_series = pd.Series([s.total_equity for s in snaps])
        returns = equity_series.pct_change().dropna()

        # Annualized return
        n_days = len(snaps)
        total_return = (equity_series.iloc[-1] / equity_series.iloc[0]) - 1 if equity_series.iloc[0] > 0 else 0
        annual_return = (1 + total_return) ** (252 / n_days) - 1 if n_days > 0 else 0

        # Sharpe ratio (annualized)
        if returns.std() > 0:
            sharpe = (returns.mean() / returns.std()) * np.sqrt(252)
        else:
            sharpe = 0.0

        # Max drawdown
        max_dd = max((s.drawdown for s in snaps), default=0)

        # Win rate
        daily_pnls = [s.daily_return for s in snaps if s.daily_return != 0]
        win_rate = (sum(1 for r in daily_pnls if r > 0) / len(daily_pnls)) if daily_pnls else 0

        return {
            "initial_equity": round(self.initial_equity, 2),
            "final_equity": round(equity_series.iloc[-1], 2),
            "total_return_pct": round(total_return * 100, 2),
            "annual_return_pct": round(annual_return * 100, 2),
            "sharpe_ratio": round(sharpe, 3),
            "max_drawdown_pct": round(max_dd * 100, 2),
            "win_rate_pct": round(win_rate * 100, 1),
            "trading_days": n_days,
            "volatility_pct": round(returns.std() * 100 * np.sqrt(252), 2) if len(returns) > 1 else 0,
        }


def limit_ratio_for(code: str, cache=None) -> float:
    """根据板块/ST状态返回涨跌停比例 (0.05/0.10/0.20/0.30)。
    模块级函数, 供 BacktestSimulator 和外部脚本 (scan_strategies) 复用。

    code 可以是 '000001' 或 'sz.000001' 形式。
    """
    c = code.split('.')[-1] if '.' in code else code
    c = c.lstrip('sSbBhH')  # 去 sz/sh/bj 前缀遗留
    # ST: 名称含"ST" → 5% (查缓存, miss 则降级)
    if cache is not None:
        try:
            name = cache.get(f'stock:name:{code}') or cache.get(f'stock:name:{c}') or ''
            if 'ST' in str(name):
                return 0.05
        except Exception:
            pass
    # 科创板/创业板 20%
    if c.startswith('688') or c.startswith('300') or c.startswith('301'):
        return 0.20
    # 北交所 30%
    if c.startswith('8') or c.startswith('4') or c.startswith('920'):
        return 0.30
    # 普通主板 10%
    return 0.10


def is_limit_bar(code: str, prev_close: float, high: float, low: float,
                 close: float, cache=None, tol: float = 0.002) -> int:
    """检测一根 K 线是否触及涨跌停 (用于回测真实性)。

    返回:
      1  = 涨停封板 (买不进)
      -1 = 跌停封板 (卖不出)
      0  = 未封板

    封板判定:
      - 一字板 (high==low): 双向封死
      - close 在涨跌停价 ±tol 容差内
    """
    if prev_close <= 0 or high <= 0 or low <= 0:
        return 0
    limit = limit_ratio_for(code, cache)
    # 一字板: 双向封死
    if abs(high - low) < 0.01:
        return 1 if close >= prev_close else -1
    if close <= 0:
        return 0
    if close >= prev_close * (1 + limit - tol):
        return 1
    if close <= prev_close * (1 - limit + tol):
        return -1
    return 0


class BacktestSimulator:
    """事件驱动回测模拟器

    真实性约束 (可选开启):
    - enforce_limit: 涨跌停拒绝成交 (一字板/收盘封板买不进卖不出)
    - max_volume_pct: 单笔订单不超过当日成交量的指定比例 (默认10%)
    """

    def __init__(
        self,
        initial_cash: float = 1_000_000.0,
        commission_rate: float = 0.0003,   # 手续费 0.03%
        slippage_rate: float = 0.0001,       # 滑点 0.01%
        position_size_pct: float = 0.95,     # 最大仓位占比
        allow_short: bool = False,
        enforce_limit: bool = True,          # 涨跌停拒绝成交
        max_volume_pct: float = 0.10,        # 单笔≤当日成交量的10%
    ):
        self.initial_cash = initial_cash
        self.commission_rate = commission_rate
        self.slippage_rate = slippage_rate
        self.position_size_pct = position_size_pct
        self.allow_short = allow_short
        self.enforce_limit = enforce_limit
        self.max_volume_pct = max_volume_pct

        # State
        self._cash = initial_cash
        self._positions: dict[str, Position] = {}   # code -> Position
        self._orders: dict[str, Order] = {}
        self._fills: list[Fill] = []
        self._tracker = PerformanceTracker(initial_cash)
        self._current_date: str = ""
        self._current_prices: dict[str, float] = {}  # code -> close price

        # Input data
        self._signals: dict[str, list[Signal]] = {}  # code -> signals
        self._klines: dict[str, pd.DataFrame] = {}    # code -> kline DataFrame
        self._price_map: dict[str, dict[str, float]] = {}  # code -> {date -> close}
        # 完整 bar 信息 (用于涨跌停检测和成交量限制)
        # {code: {date: {high, low, prev_close, shares}}}
        self._bar_map: dict[str, dict[str, dict]] = {}

        # Event history for debugging
        self._event_log: list[dict] = []

        # 统计: 被涨跌停/流动性拒绝的订单数
        self._stats = {"limit_rejected": 0, "volume_cut": 0, "volume_cancelled": 0}

        # Max position per stock (fraction of equity)
        self._max_position_pct = 0.2  # 单股最大 20%

    def add_signals(self, signals_dict: dict):
        """添加信号 {code: [{date, signal, score, ...}, ...]}"""
        for code, sigs in signals_dict.items():
            if code not in self._signals:
                self._signals[code] = []
            for s in sigs:
                if isinstance(s, dict):
                    self._signals[code].append(Signal(
                        code=code,
                        date=str(s.get("date", "")),
                        signal=int(s.get("signal", 0)),
                        score=float(s.get("score", 0)),
                        metadata={k: v for k, v in s.items() if k not in ("date", "signal", "score")},
                    ))
                elif isinstance(s, Signal):
                    self._signals[code].append(s)

    def add_klines(self, klines_dict: dict):
        """添加K线数据 {code: DataFrame}，构建价格映射和完整 bar 信息"""
        for code, df in klines_dict.items():
            if df is None or df.empty:
                continue
            df = df.copy()
            for col in ('close', 'high', 'low', 'amount'):
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            df['date'] = df['date'].astype(str)
            price_map = dict(zip(df['date'], df['close']))
            self._price_map[code] = price_map

            # 构建完整 bar 信息: high/low/prev_close/真实成交股数
            # baostock volume 单位不统一(手/股混用)，用 amount/close 反推真实股数更可靠
            df_sorted = df.sort_values('date').reset_index(drop=True)
            df_sorted['prev_close'] = df_sorted['close'].shift(1)
            df_sorted['shares'] = df_sorted.apply(
                lambda r: int(r['amount'] / r['close']) if r['close'] and r['close'] > 0 and r.get('amount', 0) > 0 else 0,
                axis=1
            )
            bar_map = {}
            for _, row in df_sorted.iterrows():
                pc = row['prev_close']
                bar_map[row['date']] = {
                    'high': float(row.get('high', 0)),
                    'low': float(row.get('low', 0)),
                    'prev_close': float(pc) if pd.notna(pc) else 0,
                    'shares': int(row['shares']),
                }
            self._bar_map[code] = bar_map
        self._klines = klines_dict

    def run(self) -> dict:
        """执行回测，返回结果"""
        # Collect all unique dates across all klines
        all_dates = set()
        for df in self._klines.values():
            if df is not None and not df.empty:
                all_dates.update(df['date'].astype(str).tolist())

        if not all_dates:
            logger.warning("No dates found in klines data")
            return self._empty_result()

        sorted_dates = sorted(all_dates)
        logger.info(f"Backtest: {len(sorted_dates)} trading days, {len(self._klines)} stocks")

        # Reset state
        self._cash = self.initial_cash
        self._positions = {}
        self._orders = {}
        self._fills = []
        self._tracker = PerformanceTracker(self.initial_cash)
        self._event_log = []

        prev_equity = self.initial_cash

        for date in sorted_dates:
            self._current_date = date

            # 1. 更新当前价格
            for code in self._price_map:
                if date in self._price_map[code]:
                    price = self._price_map[code][date]
                    if not (isinstance(price, float) and np.isnan(price)):
                        self._current_prices[code] = price
                    elif code in self._current_prices:
                        del self._current_prices[code]

            # 2. 更新持仓浮动盈亏
            self._update_positions()

            # 3. 处理当日信号 → 生成订单
            self._process_signals(date)

            # 4. 处理订单 (市价单当日成交)
            self._execute_pending_orders(date)

            # 5. 更新组合快照
            equity = self._compute_equity()
            if np.isnan(equity):
                logger.warning(f"NaN equity at {date}: cash={self._cash}, positions={ {c: (p.quantity, self._current_prices.get(c, 0)) for c, p in self._positions.items()} }")
            daily_return = (equity - prev_equity) / prev_equity if prev_equity > 0 else 0
            prev_equity = equity

            snap = PortfolioSnapshot(
                date=date,
                total_equity=equity,
                cash=self._cash,
                market_value=self._compute_market_value(),
                net_exposure=self._compute_net_exposure(),
                gross_exposure=self._compute_gross_exposure(),
                positions={code: self._positions[code].quantity for code in self._positions},
                daily_return=daily_return,
            )
            self._tracker.add_snapshot(snap)

        # Final metrics
        metrics = self._tracker.compute_metrics()
        metrics["total_trades"] = len(self._fills)
        metrics["fill_count"] = len(self._fills)
        metrics["annual_return_pct"] = metrics.get("annual_return_pct", 0)
        metrics["commission_paid"] = round(sum(f.commission for f in self._fills), 2)
        # 真实性约束统计
        metrics["limit_rejected"] = self._stats["limit_rejected"]
        metrics["volume_cut"] = self._stats["volume_cut"]
        metrics["volume_cancelled"] = self._stats["volume_cancelled"]

        # 基准对比: 用第一只股票的K线作为简易基准代理（不引入新数据源）
        benchmark_metrics = self._compute_benchmark_metrics()
        if benchmark_metrics:
            metrics["benchmark"] = benchmark_metrics

        return {
            "metrics": metrics,
            "daily_snapshots": [
                {
                    "date": s.date,
                    "equity": round(s.total_equity, 2),
                    "cash": round(s.cash, 2),
                    "market_value": round(s.market_value, 2),
                    "daily_return": round(s.daily_return * 100, 4),
                    "drawdown": round(s.drawdown * 100, 4),
                }
                for s in self._tracker.snapshots
            ],
            "fills": [
                {
                    "id": f.id,
                    "date": f.date,
                    "code": f.code,
                    "direction": f.direction,
                    "quantity": f.quantity,
                    "price": round(f.price, 2),
                    "commission": round(f.commission, 2),
                    "slippage": round(f.slippage, 2),
                }
                for f in self._fills
            ],
            "orders": [
                {
                    "id": o.id,
                    "date": o.date,
                    "code": o.code,
                    "direction": o.direction,
                    "quantity": o.quantity,
                    "price": round(o.price, 2),
                    "status": o.status,
                }
                for o in self._orders.values()
            ],
        }

    def _process_signals(self, date: str):
        """处理当日信号，生成市价单"""
        for code, sigs in self._signals.items():
            # Find signal for this date
            sig = next((s for s in sigs if s.date == date), None)
            if sig is None:
                continue

            pos = self._positions.get(code)
            current_qty = pos.quantity if pos else 0

            # Determine target position
            equity = self._compute_equity()
            max_pos_value = equity * self._max_position_pct
            current_price = self._current_prices.get(code, 0)
            if current_price <= 0:
                continue

            if sig.signal > 0:  # Long signal
                target_qty = int(max_pos_value / current_price / 100) * 100  # 整手
                if target_qty > current_qty:
                    self._create_market_order(code, date, "buy", target_qty - current_qty)
                elif target_qty < current_qty:
                    self._create_market_order(code, date, "sell", current_qty - target_qty)
            elif sig.signal < 0 and self.allow_short:  # Short signal
                target_qty = int(max_pos_value / current_price / 100) * 100
                if target_qty > abs(current_qty):
                    self._create_market_order(code, date, "sell_short", target_qty - abs(current_qty))
                elif target_qty < abs(current_qty):
                    self._create_market_order(code, date, "buy_cover", abs(current_qty) - target_qty)
            elif sig.signal == 0 and current_qty > 0:
                # Flatten
                self._create_market_order(code, date, "sell", current_qty)

    def _create_market_order(self, code: str, date: str, direction: str, quantity: int):
        if quantity <= 0:
            return
        oid = str(uuid.uuid4())[:8]
        order = Order(
            id=oid,
            code=code,
            date=date,
            direction=direction,
            quantity=quantity,
            price=0.0,
            order_type="market",
            status="pending",
        )
        self._orders[oid] = order

    def _limit_ratio_for(self, code: str) -> float:
        """根据板块/ST状态返回涨跌停比例 (委托给模块级函数)"""
        return limit_ratio_for(code, self._cache_for_names())

    def _cache_for_names(self):
        """惰性获取缓存 (用于 ST 名称查询)"""
        if not hasattr(self, '_name_cache_obj'):
            try:
                self._name_cache_obj = create_cache()
            except Exception:
                self._name_cache_obj = None
        return self._name_cache_obj

    def _is_limit_locked(self, code: str, date: str, direction: str) -> bool:
        """检测当日是否涨跌停封板 (导致无法成交)

        direction: "buy" → 检测涨停(买不进); "sell"/"sell_short" → 检测跌停(卖不出)
        返回 True 表示被锁定、应拒绝成交。
        """
        if not self.enforce_limit:
            return False
        bars = self._bar_map.get(code, {})
        bar = bars.get(date)
        if not bar:
            return False
        flag = is_limit_bar(
            code, bar['prev_close'], bar['high'], bar['low'],
            self._current_prices.get(code, 0), self._cache_for_names()
        )
        if flag == 1 and direction in ("buy", "buy_cover"):
            return True
        if flag == -1 and direction in ("sell", "sell_short"):
            return True
        return False

    def _execute_pending_orders(self, date: str):
        """执行所有待成交订单 (市价单，当日以收盘价成交)

        真实性约束:
        - 涨跌停封板: 拒绝成交 (买不进涨停/卖不出跌停)
        - 成交量限制: 单笔≤当日成交量*max_volume_pct, 超过则部分成交
        """
        for oid, order in list(self._orders.items()):
            if order.date != date or order.status != "pending":
                continue

            price = self._current_prices.get(order.code, 0)
            if price <= 0:
                order.status = "rejected"
                continue

            # 1. 涨跌停检测
            if self._is_limit_locked(order.code, date, order.direction):
                order.status = "rejected"
                self._stats["limit_rejected"] += 1
                self._event_log.append({"type": "limit_rejected", "date": date, "code": order.code, "dir": order.direction})
                continue

            # 2. 成交量限制 (部分成交)
            quantity = order.quantity
            if self.max_volume_pct < 1.0 and order.direction in ("buy", "buy_cover"):
                bars = self._bar_map.get(order.code, {})
                bar = bars.get(date, {})
                daily_shares = bar.get('shares', 0)
                if daily_shares > 0:
                    max_fillable = int(daily_shares * self.max_volume_pct / 100) * 100
                    if max_fillable < quantity:
                        if max_fillable <= 0:
                            order.status = "cancelled"
                            self._stats["volume_cancelled"] += 1
                            continue
                        quantity = max_fillable
                        self._stats["volume_cut"] += 1

            # 3. 滑点
            slippage = price * self.slippage_rate
            if order.direction in ("buy", "buy_cover"):
                fill_price = price + slippage
            else:
                fill_price = price - slippage

            # 4. 手续费 + 现金检查 (用调整后的 quantity)
            notional = fill_price * quantity
            commission = notional * self.commission_rate

            if order.direction in ("buy",) and self._cash < (notional + commission):
                order.status = "rejected"
                continue

            # 5. 成交
            fill = Fill(
                id=str(uuid.uuid4())[:8],
                order_id=oid,
                code=order.code,
                date=date,
                direction=order.direction,
                quantity=quantity,
                price=round(fill_price, 2),
                commission=round(commission, 2),
                slippage=round(slippage, 4),
            )
            self._fills.append(fill)
            order.status = "filled"
            order.price = fill_price

            # Update position
            self._apply_fill(fill)
            self._event_log.append({"type": "fill", "date": date, "fill": fill})

    def _apply_fill(self, fill: Fill):
        """更新仓位和现金"""
        code = fill.code
        if fill.direction == "buy":
            pos = self._positions.get(code, Position(code=code))
            total_cost = fill.price * fill.quantity + fill.commission
            new_qty = pos.quantity + fill.quantity
            new_avg = (pos.avg_entry_price * pos.quantity + fill.price * fill.quantity) / new_qty
            pos.quantity = new_qty
            pos.avg_entry_price = round(new_avg, 4)
            self._cash -= total_cost
            self._positions[code] = pos
        elif fill.direction == "sell":
            pos = self._positions.get(code)
            if pos and pos.quantity >= fill.quantity:
                realized = (fill.price - pos.avg_entry_price) * fill.quantity - fill.commission
                pos.realized_pnl += realized
                pos.quantity -= fill.quantity
                self._cash += fill.price * fill.quantity - fill.commission
                if pos.quantity == 0:
                    del self._positions[code]
                else:
                    self._positions[code] = pos
        elif fill.direction == "sell_short" and self.allow_short:
            pos = self._positions.get(code, Position(code=code))
            pos.quantity -= fill.quantity
            pos.avg_entry_price = fill.price
            self._cash += fill.price * fill.quantity - fill.commission
            self._positions[code] = pos
        elif fill.direction == "buy_cover" and self.allow_short:
            pos = self._positions.get(code)
            if pos:
                realized = (pos.avg_entry_price - fill.price) * fill.quantity - fill.commission
                pos.realized_pnl += realized
                pos.quantity += fill.quantity  # quantity is negative
                self._cash -= fill.price * fill.quantity + fill.commission
                if abs(pos.quantity) == 0:
                    del self._positions[code]
                else:
                    self._positions[code] = pos

    def _update_positions(self):
        """更新所有持仓的浮动盈亏"""
        for code, pos in self._positions.items():
            price = self._current_prices.get(code, pos.avg_entry_price)
            pos.unrealized_pnl = (price - pos.avg_entry_price) * pos.quantity

    def _compute_equity(self) -> float:
        return self._cash + self._compute_market_value()

    def _compute_market_value(self) -> float:
        mv = 0.0
        for code, pos in self._positions.items():
            price = self._current_prices.get(code, pos.avg_entry_price)
            # Skip NaN prices (last date may have incomplete data)
            if isinstance(price, float) and np.isnan(price):
                continue
            mv += price * pos.quantity
        return mv

    def _compute_gross_exposure(self) -> float:
        return self._compute_market_value()

    def _compute_net_exposure(self) -> float:
        mv = self._compute_market_value()
        short_value = 0.0
        for pos in self._positions.values():
            if pos.quantity < 0:
                short_value += abs(pos.quantity) * self._current_prices.get(pos.code, 0)
        return mv - short_value

    def _empty_result(self) -> dict:
        return {
            "metrics": {},
            "daily_snapshots": [],
            "fills": [],
            "orders": [],
        }

    def _compute_benchmark_metrics(self) -> dict:
        """用回测区间内的等权基准（所有输入股票的平均收益）作为简易基准。
        不引入新数据源，仅用于让回测结果有对比参照。
        """
        if not self._klines or not self._tracker.snapshots:
            return {}
        try:
            # 收集所有日期
            all_dates = set()
            for df in self._klines.values():
                if df is not None and not df.empty:
                    all_dates.update(df['date'].astype(str).tolist())
            sorted_dates = sorted(all_dates)
            if len(sorted_dates) < 2:
                return {}

            # 等权买入持有：每只股票初始等权，到末日计算收益
            n_stocks = len(self._klines)
            bench_returns = []
            for code, df in self._klines.items():
                if df is None or df.empty:
                    continue
                df = df.copy()
                df['date'] = df['date'].astype(str)
                df = df.sort_values('date').reset_index(drop=True)
                closes = pd.to_numeric(df['close'], errors='coerce').dropna()
                if len(closes) >= 2 and closes.iloc[0] > 0:
                    bench_returns.append(closes.iloc[-1] / closes.iloc[0] - 1)

            if not bench_returns:
                return {}
            bench_total = float(np.mean(bench_returns))
            n_days = len(sorted_dates)
            bench_annual = (1 + bench_total) ** (252 / n_days) - 1 if n_days > 0 and bench_total > -1 else 0
            strat_total = self._tracker.compute_metrics().get("total_return_pct", 0) / 100
            excess = (strat_total - bench_total) * 100
            return {
                "method": "equal_weight_hold (universe avg)",
                "n_stocks": n_stocks,
                "total_return_pct": round(bench_total * 100, 2),
                "annual_return_pct": round(bench_annual * 100, 2),
                "excess_return_pct": round(excess, 2),
            }
        except Exception:
            return {}

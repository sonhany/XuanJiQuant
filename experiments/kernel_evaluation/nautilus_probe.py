"""Isolated native-engine experiment. Synthetic data; no project trading imports."""
from decimal import Decimal
import json
from pathlib import Path

import nautilus_trader
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.backtest.models import FixedFeeModel
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import CNY
from nautilus_trader.model.data import QuoteTick, InstrumentStatus
from nautilus_trader.model.enums import AccountType, OmsType, OrderSide, MarketStatusAction
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import Equity
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.model.events import OrderFilled
from nautilus_trader.model.orders.unpacker import OrderUnpacker
from nautilus_trader.trading.strategy import Strategy

FIXTURE = Path(__file__).with_name('scenarios.json')


def instrument():
    return Equity(
        instrument_id=InstrumentId.from_str('600000.XSHG'),
        raw_symbol=Symbol('600000'), currency=CNY,
        price_precision=2, price_increment=Price.from_str('0.01'),
        lot_size=Quantity.from_int(100), ts_event=0, ts_init=0,
        maker_fee=Decimal('0'), taker_fee=Decimal('0'),
    )


class ProbeStrategy(Strategy):
    def __init__(self, mode):
        super().__init__()
        self.mode = mode
        self.tick_count = 0
        self.order = None
        self.snapshots = []

    def on_start(self):
        self.subscribe_quote_ticks(InstrumentId.from_str('600000.XSHG'))

    def on_quote_tick(self, tick):
        self.tick_count += 1
        if self.tick_count == 1:
            qty = 20000 if self.mode == 'insufficient_cash' else 1000
            if self.mode == 'odd_lot':
                qty = 101
            if self.mode in ('partial_complete', 'partial_cancel', 'cash_reservation', 'aggressive_limit'):
                price = '9.00' if self.mode == 'cash_reservation' else '10.01' if self.mode=='aggressive_limit' else '10.00'
                self.order = self.order_factory.limit(tick.instrument_id, OrderSide.BUY, Quantity.from_int(qty), Price.from_str(price))
            else:
                self.order = self.order_factory.market(tick.instrument_id, OrderSide.BUY, Quantity.from_int(qty))
            self.submit_order(self.order)
        if self.tick_count == 2 and self.mode in ('partial_cancel', 'cash_reservation'):
            self.cancel_order(self.order)
        if self.tick_count == 2 and self.mode == 'same_day_roundtrip':
            self.submit_order(self.order_factory.market(tick.instrument_id, OrderSide.SELL, Quantity.from_int(1000)))
        account = self.cache.account_for_venue(Venue('XSHG'))
        self.snapshots.append({'tick':self.tick_count,'cash':str(account.balance_total(CNY).as_decimal()),
                               'locked':str(account.balance_locked(CNY).as_decimal())})


def run_native(mode):
    engine = BacktestEngine(config=BacktestEngineConfig(
        logging=LoggingConfig(bypass_logging=True), run_analysis=False,
    ))
    engine.add_venue(
        venue=Venue('XSHG'), oms_type=OmsType.NETTING,
        account_type=AccountType.CASH, base_currency=CNY,
        starting_balances=[Money(100000, CNY)],
        fee_model=FixedFeeModel(Money(5,CNY), charge_commission_once=False),
        liquidity_consumption=True,
    )
    asset = instrument()
    engine.add_instrument(asset)
    strategy = ProbeStrategy(mode)
    engine.add_strategy(strategy)
    # 2026-09-10T01:35 UTC; four same-session quotes, no production data.
    start = 1789004100000000000
    if mode == 'suspended':
        engine.add_data([InstrumentStatus(asset.id, MarketStatusAction.HALT, start-1, start-1, is_trading=False)])
    engine.add_data([
        QuoteTick(asset.id, Price.from_str('12.00' if mode == 'above_daily_limit' else '10.00'), Price.from_str('12.00' if mode == 'above_daily_limit' else '11.00' if mode == 'partial_cancel' and i > 0 else '10.00'),
                  Quantity.from_int(100000), Quantity.from_int(400 if i == 0 and (mode.startswith('partial') or mode=='aggressive_limit') else 600 if mode.startswith('partial') else 100000),
                  start + i * 1_000_000_000, start + i * 1_000_000_000)
        for i in range(4)
    ])
    try:
        engine.run()
        account = engine.cache.account_for_venue(Venue('XSHG'))
        orders = engine.cache.orders()
        result = {
            'mode': mode,
            'cash': str(account.balance_total(CNY).as_decimal()),
            'open_quantity': sum(int(p.quantity.as_decimal()) for p in engine.cache.positions_open()),
            'orders': [{'status': o.status.name, 'quantity': str(o.quantity), 'filled': str(o.filled_qty)} for o in orders],
            'boundary': 'BacktestEngine -> RiskEngine -> simulated exchange -> native portfolio',
            'fees': 'synthetic fixed CNY 5 per fill; not a production fee schedule',
            'account_observations': strategy.snapshots,
        }
        if mode == 'full':
            fill = next(e for e in orders[0].events if isinstance(e, OrderFilled))
            before = (str(account.balance_total(CNY)), str(orders[0].filled_qty),
                      sum(int(p.quantity.as_decimal()) for p in engine.cache.positions_open()))
            engine.kernel.exec_engine.process(fill)
            after = (str(account.balance_total(CNY)), str(orders[0].filled_qty),
                     sum(int(p.quantity.as_decimal()) for p in engine.cache.positions_open()))
            result['duplicate_engine_event_unchanged'] = before == after
        if orders:
            original = orders[0]
            restored = OrderUnpacker.from_init(original.events[0])
            for event in original.events[1:]:
                restored.apply(event)
            result['event_replay'] = {
                'status': restored.status.name,
                'filled': str(restored.filled_qty),
                'matches': restored.status == original.status and restored.filled_qty == original.filled_qty,
                'scope': 'in-memory order event replay, not process restart recovery',
            }
        return result
    finally:
        engine.dispose()


if __name__ == '__main__':
    print(json.dumps({'engine': 'NautilusTrader', 'version': nautilus_trader.__version__,
                      'results': [run_native(m) for m in ['full', 'partial_complete', 'partial_cancel', 'same_day_roundtrip', 'insufficient_cash', 'cash_reservation', 'suspended', 'above_daily_limit', 'odd_lot']]}))

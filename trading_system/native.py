"""Nautilus adapter: a real engine owns orders, fills, cash and positions."""
from datetime import datetime,timezone
from decimal import Decimal
import hashlib

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.backtest.models import FeeModel
from nautilus_trader.config import BacktestEngineConfig,LoggingConfig
from nautilus_trader.model.currencies import CNY
from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.enums import AccountType,OmsType,OrderSide,TimeInForce
from nautilus_trader.model.identifiers import InstrumentId,Symbol,Venue,ClientOrderId
from nautilus_trader.model.instruments import Equity
from nautilus_trader.model.objects import Money,Price,Quantity
from nautilus_trader.trading.strategy import Strategy

from .contracts import validate_request,amount,money,nanos,instant,ZONE
from .rules import Reservations,fees,market_reason


class OrderFee(FeeModel):
    def __init__(self,costs):
        super().__init__();self.costs=costs

    def get_commission(self,order,fill_qty,fill_px,instrument):
        side='buy' if order.side==OrderSide.BUY else 'sell'
        previous=order.filled_qty.as_decimal()*Decimal(str(order.avg_px or 0))
        current=previous+fill_qty.as_decimal()*fill_px.as_decimal()
        return Money(fees(current,side,self.costs)-fees(previous,side,self.costs),CNY)


class BaselineStrategy(Strategy):
    def __init__(self,req,asset):
        super().__init__();self.req=req;self.asset=asset
        self.frames={nanos(f['timestamp']):f for f in req['frames']}
        self.rules=Reservations(req);self.decisions=[];self.fills=[]
        self.seen=set();self.order_ids={};self.fill_ids=set();self.fault=None
        self.cursor=0

    def on_start(self):
        self.subscribe_quote_ticks(self.asset.id)

    def on_quote_tick(self,tick):
        self.process_through(tick.ts_init)

    def process_through(self,timestamp):
        while self.cursor<len(self.req['frames']):
            frame=self.req['frames'][self.cursor]
            if nanos(frame['timestamp'])>timestamp:break
            self.cursor+=1
            self.process_frame(frame)

    def process_frame(self,frame):
        account=self.cache.account_for_venue(self.asset.id.venue)
        intents=list(frame['orders'])
        day=instant(frame['timestamp']).date().isoformat()
        if day in self.req.get('baseline_targets',{}) and market_reason(frame,self.req) is None:
            quantity=sum(int(p.quantity.as_decimal()) for p in self.cache.positions_open())
            delta=self.req['baseline_targets'][day]-quantity
            if delta:
                side='buy' if delta>0 else 'sell'
                intents.append({'id':f'baseline-{self.cursor}','side':side,'quantity':abs(delta),
                                'limit_price':frame['ask'] if side=='buy' else frame['bid']})
            else:
                self.decisions.append({'id':f'baseline-{self.cursor}','approved':False,'reason':'hold_target_reached'})
        for intent in intents:
            identity=intent['id']
            if identity in self.seen:
                self.decisions.append({'id':identity,'approved':False,'reason':'duplicate_intent'})
                continue
            self.seen.add(identity)
            verdict=self.rules.approve(intent,frame,account.balance_total(CNY).as_decimal())
            self.decisions.append({'id':identity,'approved':verdict['approved'],'reason':verdict['reason']})
            if not verdict['approved']:continue
            client_id='B-'+hashlib.sha256(identity.encode()).hexdigest()[:30]
            self.order_ids[client_id]=identity
            order=self.order_factory.limit(
                self.asset.id,OrderSide.BUY if intent['side']=='buy' else OrderSide.SELL,
                Quantity.from_int(intent['quantity']),Price.from_str(str(verdict['price'])),
                time_in_force=TimeInForce.IOC,client_order_id=ClientOrderId(client_id),
            )
            self.submit_order(order)

    def _release(self,event):
        self.rules.release(self.order_ids[str(event.client_order_id)])

    def on_order_denied(self,event):self._release(event)
    def on_order_rejected(self,event):self._release(event)
    def on_order_canceled(self,event):self._release(event)
    def on_order_expired(self,event):self._release(event)

    def on_order_filled(self,event):
        trade_id=str(event.trade_id)
        if trade_id in self.fill_ids:
            self.fault='duplicate_fill_callback';return
        self.fill_ids.add(trade_id)
        identity=self.order_ids[str(event.client_order_id)]
        day=datetime.fromtimestamp(event.ts_event/10**9,timezone.utc).astimezone(ZONE).date().isoformat()
        side='buy' if event.order_side==OrderSide.BUY else 'sell'
        quantity=int(event.last_qty.as_decimal())
        self.rules.filled(identity,side,quantity,day)
        self.fills.append({'intent_id':identity,'trade_id':trade_id,'day':day,'side':side,
                           'quantity':quantity,'price':money(event.last_px.as_decimal()),
                           'fee':money(event.commission.as_decimal())})
        if self.cache.order(event.client_order_id).is_closed:self._release(event)


def run_replay(raw):
    req=validate_request(raw);spec=req['instrument'];code=spec['code']
    asset=Equity(instrument_id=InstrumentId.from_str(code+'.'+spec['venue']),raw_symbol=Symbol(code),
                 currency=CNY,price_precision=2,price_increment=Price.from_str(spec['tick_size']),
                 lot_size=Quantity.from_int(spec['buy_lot']),ts_event=0,ts_init=0)
    engine=BacktestEngine(config=BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True),run_analysis=False))
    engine.add_venue(venue=Venue(spec['venue']),oms_type=OmsType.NETTING,account_type=AccountType.CASH,
                     base_currency=CNY,starting_balances=[Money(amount(req['initial_cash']),CNY)],
                     fee_model=OrderFee(req['costs']),liquidity_consumption=True)
    engine.add_instrument(asset);strategy=BaselineStrategy(req,asset);engine.add_strategy(strategy)
    ticks=[];lot=spec['buy_lot'];cap=amount(req['participation'])
    trusted=[]
    for f in req['frames']:
        if market_reason(f,req) is not None:continue
        trusted.append(f)
        bid_size=int(amount(f['bid_size'])*cap)//lot*lot
        ask_size=int(amount(f['ask_size'])*cap)//lot*lot
        ticks.append(QuoteTick(asset.id,Price.from_str(f['bid']),Price.from_str(f['ask']),
                               Quantity.from_int(bid_size),Quantity.from_int(ask_size),
                               nanos(f['timestamp']),nanos(f['timestamp'])))
    engine.add_data(ticks)
    try:
        if not ticks:raise ValueError('no_valid_quotes')
        engine.run()
        strategy.process_through(nanos(req['frames'][-1]['timestamp']))
        if strategy.fault:raise ValueError(strategy.fault)
        account=engine.cache.account_for_venue(asset.id.venue)
        cash=account.balance_total(CNY).as_decimal()
        quantity=sum(int(p.quantity.as_decimal()) for p in engine.cache.positions_open())
        positions={code:quantity} if quantity else {}
        orders=[]
        for order in engine.cache.orders():
            orders.append({'id':strategy.order_ids[str(order.client_order_id)],'status':order.status.name,
                           'quantity':int(order.quantity.as_decimal()),'filled_quantity':int(order.filled_qty.as_decimal()),
                           'remaining_quantity':int(order.leaves_qty.as_decimal())})
        expected=amount(req['initial_cash'])
        shares=0
        for fill in strategy.fills:
            sign=1 if fill['side']=='buy' else -1
            expected-=sign*fill['quantity']*amount(fill['price'])+amount(fill['fee'])
            shares+=sign*fill['quantity']
        checks={'cash':money(expected)==money(cash),'positions':shares==quantity,
                'lots':sum(x['quantity'] for x in strategy.rules.lots)==quantity,
                'terminal':all(o['status'] in ('FILLED','CANCELED','REJECTED','DENIED','EXPIRED') for o in orders),
                'reservations_released':strategy.rules.cash==0 and not strategy.rules.pending,
                'nonnegative':cash>=0 and quantity>=0}
        if not all(checks.values()):raise ValueError('reconciliation_failed:'+str(checks))
        day=instant(req['frames'][-1]['timestamp']).date().isoformat()
        return {'schema':'nautilus-baseline-result-v1','engine':'NautilusTrader',
                'cash':money(cash),'positions':positions,'available':{code:strategy.rules.available(day)} if quantity else {},
                'equity':money(cash+quantity*amount(trusted[-1]['bid'])),
                'valuation_timestamp':trusted[-1]['quote_timestamp'],
                'valuation_method':'trusted_best_bid',
                'reserved_cash':money(strategy.rules.cash),'orders':orders,'fills':strategy.fills,
                'settlement_lots':strategy.rules.lots,'decisions':strategy.decisions,
                'reconciliation':{'passed':True,'checks':checks},
                'last_quote_valid':market_reason(req['frames'][-1],req) is None,
                'live_execution_authority':False}
    finally:
        engine.dispose()

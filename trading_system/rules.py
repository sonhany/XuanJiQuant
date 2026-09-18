"""Pre-trade policy and settlement-lot projection, independent of the engine."""
from decimal import Decimal

from .contracts import amount,instant,money


def fees(notional,side,costs):
    if notional<=0:
        return Decimal(0)
    commission=max(notional*amount(costs['commission_rate']),amount(costs['minimum_commission']))
    tax=notional*amount(costs['sell_tax_rate']) if side=='sell' else Decimal(0)
    return amount(money(commission+tax+notional*amount(costs['transfer_rate'])))


def market_reason(frame,req):
    now=instant(frame['timestamp']); quote=instant(frame['quote_timestamp'])
    day=now.date().isoformat()
    minute=now.hour*60+now.minute
    if day not in req['calendar'] or not (570<=minute<690 or 780<=minute<897):
        return 'outside_session'
    if frame['market']['date']!=day:
        return 'market_state_stale'
    if frame['market']['suspended']:
        return 'suspended'
    age=(now-quote).total_seconds()*1000
    if age<0:return 'quote_future'
    if quote.date()!=now.date() or age>req['max_quote_age_ms']:return 'quote_stale'
    if amount(frame['bid'])<amount(frame['market']['lower_limit']) or amount(frame['ask'])>amount(frame['market']['upper_limit']):
        return 'daily_price_limit'
    return None


class Reservations:
    def __init__(self,request):
        self.request=request
        self.pending={}
        self.lots=[]

    def available(self,day):
        matured=sum(lot['quantity'] for lot in self.lots if lot['day']<day)
        reserved=sum(x['quantity'] for x in self.pending.values() if x['side']=='sell')
        return matured-reserved

    @property
    def cash(self):
        return sum((x['cash'] for x in self.pending.values()),Decimal(0))

    def approve(self,order,frame,cash):
        req=self.request
        reason=market_reason(frame,req)
        if reason:return {'approved':False,'reason':reason}
        qty=order['quantity'];side=order['side'];limit=amount(order['limit_price'])
        lot=req['instrument']['buy_lot']
        if side=='buy' and qty%lot:return {'approved':False,'reason':'buy_lot_invalid'}
        if limit%amount(req['instrument']['tick_size']):return {'approved':False,'reason':'price_precision_invalid'}
        state=frame['market'];lower=amount(state['lower_limit']);upper=amount(state['upper_limit'])
        price=amount(frame['ask'] if side=='buy' else frame['bid'])
        if not lower<=limit<=upper or not lower<=price<=upper or (side=='buy' and price>=upper) or (side=='sell' and price<=lower):
            return {'approved':False,'reason':'daily_price_limit'}
        if (side=='buy' and limit<price) or (side=='sell' and limit>price):
            return {'approved':False,'reason':'not_marketable'}
        # The actual IOC limit is pinned to the visible best price, never inferred depth.
        reservation=Decimal(0)
        if side=='buy':
            reservation=qty*price+fees(qty*price,side,req['costs'])
            if reservation>cash-self.cash:return {'approved':False,'reason':'cash_insufficient'}
        else:
            day=instant(frame['timestamp']).date().isoformat()
            available=self.available(day)
            if qty>available:return {'approved':False,'reason':'t1_or_available_quantity'}
            if qty%lot and qty!=available:return {'approved':False,'reason':'sell_odd_lot_not_full_exit'}
        self.pending[order['id']]={'side':side,'quantity':qty,'cash':reservation}
        return {'approved':True,'reason':'approved','price':price}

    def release(self,identity):
        self.pending.pop(identity,None)

    def filled(self,identity,side,quantity,day):
        if side=='buy':
            self.lots.append({'day':day,'quantity':quantity})
        else:
            remaining=quantity
            for lot in self.lots:
                if lot['day']>=day:continue
                sold=min(lot['quantity'],remaining)
                lot['quantity']-=sold;remaining-=sold
            if remaining:raise ValueError('settlement_lot_underflow')
            self.lots=[lot for lot in self.lots if lot['quantity']]
            if identity in self.pending:self.pending[identity]['quantity']-=quantity

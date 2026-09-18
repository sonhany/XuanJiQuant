"""Strict, replayable inputs for the isolated single-equity baseline."""
from copy import deepcopy
from datetime import datetime, date, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import re
from zoneinfo import ZoneInfo

ZONE = ZoneInfo('Asia/Shanghai')


def digest(value):
    encoded=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def amount(value):
    if isinstance(value,bool) or not isinstance(value,(str,int,Decimal)):
        raise ValueError('invalid_decimal')
    try:
        result=Decimal(value)
    except InvalidOperation as exc:
        raise ValueError('invalid_decimal') from exc
    if not result.is_finite():
        raise ValueError('invalid_decimal')
    return result


def money(value):
    return format(Decimal(value).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP),'.2f')


def instant(value):
    result=datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError('timezone_required')
    return result.astimezone(ZONE)


def nanos(value):
    delta=instant(value).astimezone(timezone.utc)-datetime(1970,1,1,tzinfo=timezone.utc)
    return (delta.days*86400+delta.seconds)*10**9+delta.microseconds*1000


def integer(value,minimum=0,maximum=10**9):
    if type(value) is not int or not minimum<=value<=maximum:
        raise ValueError('invalid_integer')
    return value


def validate_request(raw):
    req=deepcopy(raw)
    if req.get('schema')!='nautilus-baseline-v1' or req.get('currency')!='CNY':
        raise ValueError('unsupported_schema_or_currency')
    if req.get('data_kind') not in ('synthetic','historical','observed_realtime'):
        raise ValueError('offline_data_required')
    asset=req['instrument']
    if not re.fullmatch(r'\d{6}',asset['code']) or asset['venue'] not in ('XSHG','XSHE'):
        raise ValueError('instrument_invalid')
    if amount(asset['tick_size'])!=Decimal('0.01') or integer(asset['buy_lot'],1)!=100:
        raise ValueError('unsupported_instrument_profile')
    if amount(req['initial_cash'])<=0 or not 0<amount(req['participation'])<=1:
        raise ValueError('invalid_capital_or_participation')
    integer(req['max_quote_age_ms'],1,60000)
    calendar=req['calendar']
    if not calendar or calendar!=sorted(set(calendar)):
        raise ValueError('calendar_invalid')
    for value in calendar:
        if date.fromisoformat(value).isoformat()!=value:
            raise ValueError('calendar_invalid')
    for key in ('commission_rate','minimum_commission','sell_tax_rate','transfer_rate'):
        if amount(req['costs'][key])<0:
            raise ValueError('negative_cost')
    frames=req['frames']
    if not isinstance(frames,list) or not 1<=len(frames)<=10000:
        raise ValueError('frame_count_invalid')
    targets=req.get('baseline_targets',{})
    if targets:
        if any(day not in calendar for day in targets) or any(f['orders'] for f in frames):
            raise ValueError('baseline_target_contract_invalid')
        for qty in targets.values():
            if integer(qty)%asset['buy_lot']:
                raise ValueError('baseline_target_lot_invalid')
    previous=-1
    identities={}
    for f in frames:
        now=nanos(f['timestamp']);instant(f['quote_timestamp'])
        if now<=previous:
            raise ValueError('unordered_frames')
        previous=now
        if amount(f['bid'])<=0 or amount(f['ask'])<amount(f['bid']):
            raise ValueError('quote_price_invalid')
        for field in ('bid','ask'):
            if amount(f[field])%amount(asset['tick_size']):
                raise ValueError('quote_precision_invalid')
        integer(f['bid_size']);integer(f['ask_size'])
        state=f['market']
        if type(state['suspended']) is not bool or not state.get('version'):
            raise ValueError('market_state_unknown')
        if not 0<amount(state['lower_limit'])<amount(state['upper_limit']):
            raise ValueError('price_band_invalid')
        if not isinstance(f['orders'],list) or len(f['orders'])>20:
            raise ValueError('order_batch_invalid')
        for order in f['orders']:
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',order['id']):
                raise ValueError('intent_id_invalid')
            if order['side'] not in ('buy','sell'):
                raise ValueError('side_invalid')
            integer(order['quantity'],1)
            if amount(order['limit_price'])<=0:
                raise ValueError('order_price_invalid')
            fingerprint=digest(order)
            if order['id'] in identities and identities[order['id']]!=fingerprint:
                raise ValueError('intent_identity_conflict')
            identities[order['id']]=fingerprint
    return req

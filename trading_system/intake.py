"""Observe the existing local data API; never manufacture execution inputs."""
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
import json
import re
import time
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .contracts import ZONE, amount, digest, instant, integer, money
from .rules import market_reason

DATA_URL = 'http://127.0.0.1:8880/api/data'
MAX_RESPONSE = 2_000_000


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _codes(codes):
    if not isinstance(codes, list) or not 1 <= len(codes) <= 20:
        raise ValueError('requested_universe_invalid')
    if len(set(codes)) != len(codes) or any(not isinstance(c, str) or not re.fullmatch(r'\d{6}', c) for c in codes):
        raise ValueError('requested_universe_invalid')
    return list(codes)


def _api_time(value):
    if isinstance(value, str) and re.fullmatch(r'\d{14}', value):
        return datetime.strptime(value, '%Y%m%d%H%M%S').replace(tzinfo=ZONE)
    result = datetime.fromisoformat(value)
    # This specific local API declares its naive timestamps as Shanghai time.
    return result.replace(tzinfo=ZONE) if result.tzinfo is None else result.astimezone(ZONE)


def assess_snapshot(snapshot, codes, checked_at):
    codes = _codes(codes)
    if checked_at.tzinfo is None:
        raise ValueError('timezone_required')
    checked_at = checked_at.astimezone(ZONE)
    raw = deepcopy(snapshot)
    if not isinstance(raw, dict) or not isinstance(raw.get('quotes'), dict):
        raise ValueError('snapshot_contract_invalid')
    quotes = raw['quotes']; reasons = []
    if raw.get('market_phase') not in ('continuous', 'continuous_auction'):
        reasons.append('market_not_continuous')
    if set(quotes) - set(codes): reasons.append('unexpected_symbols')
    if raw.get('stale') is not False: reasons.append('upstream_snapshot_stale')
    if not raw.get('snapshot_id'): reasons.append('snapshot_identity_missing')
    received = None
    try:
        received = _api_time(raw.get('received_at'))
        if received > checked_at: reasons.append('received_time_future')
    except (ValueError, TypeError):
        reasons.append('received_time_invalid')
    calendar = raw.get('calendar', [])
    try:
        if (not isinstance(calendar, list) or not calendar or calendar != sorted(set(calendar))
                or any(date.fromisoformat(day).isoformat() != day for day in calendar)):
            raise ValueError('calendar')
    except (ValueError, TypeError):
        reasons.append('calendar_missing_or_invalid')
        calendar = []
    rows = {}; observed = 0; ready = 0
    for code in codes:
        row = quotes.get(code)
        if not isinstance(row, dict) or not row:
            rows[code] = {'reasons': ['quote_missing'], 'execution_ready': False}
            continue
        observed += 1
        errors = []; age = None; quote_time = None
        if not row.get('source'): errors.append('source_missing')
        expected_venue = 'XSHG' if code.startswith('6') else 'XSHE' if code.startswith(('0', '3')) else None
        if row.get('code') != code or expected_venue is None or row.get('venue') != expected_venue:
            errors.append('instrument_mismatch')
        if row.get('timestamp_kind') != 'exchange': errors.append('event_time_unverified')
        if row.get('size_unit') != 'shares': errors.append('quantity_unit_unknown')
        if row.get('stale') is not False: errors.append('upstream_stale')
        try:
            quote_time = _api_time(row.get('quote_timestamp'))
            if received is not None and quote_time > received: errors.append('quote_after_receipt')
            age = int((checked_at - quote_time).total_seconds() * 1000)
            if age < 0: errors.append('quote_future')
            elif age > 5000 or quote_time.date() != checked_at.date(): errors.append('quote_stale')
        except (ValueError, TypeError):
            errors.append('quote_timestamp_invalid')
        try:
            bid, ask = amount(str(row['bid'])), amount(str(row['ask']))
            if bid <= 0 or ask < bid or bid % Decimal('.01') or ask % Decimal('.01'):
                raise ValueError('price')
            integer(row['bid_size'], 1); integer(row['ask_size'], 1)
        except (KeyError, ValueError, TypeError):
            errors.append('book_invalid')
        state = row.get('market')
        try:
            if (not isinstance(state, dict) or type(state.get('suspended')) is not bool
                    or not state.get('version') or not 0 < amount(state['lower_limit']) < amount(state['upper_limit'])):
                raise ValueError('state')
            if state.get('date') != checked_at.date().isoformat(): errors.append('market_state_stale')
            if state['suspended']: errors.append('suspended')
        except (KeyError, ValueError, TypeError):
            errors.append('market_state_unknown')
        if not errors:
            frame = {'timestamp': checked_at.isoformat(), 'quote_timestamp': quote_time.isoformat(),
                     'market': state, 'bid': str(row['bid']), 'ask': str(row['ask'])}
            reason = market_reason(frame, {'calendar': calendar, 'max_quote_age_ms': 5000})
            if reason: errors.append(reason)
        rows[code] = {'source': row.get('source'), 'quote_timestamp': row.get('quote_timestamp'),
                      'age_ms': age, 'reasons': list(dict.fromkeys(errors)), 'execution_ready': not errors}
        ready += int(not errors)
    return {
        'schema': 'data-intake-report-v1', 'checked_at': checked_at.isoformat(),
        'source_endpoint': DATA_URL, 'input_hash': digest(raw), 'raw_snapshot': raw,
        'coverage': {'requested': len(codes), 'observed': observed, 'ready': ready},
        'rows': rows, 'reasons': reasons, 'execution_ready': not reasons and ready == len(codes),
        'live_execution_authority': False,
    }


def build_observed_realtime_request(
    report,
    code,
    *,
    target_quantity,
    initial_cash='100000.00',
    participation='0.10',
):
    """Convert an execution-ready observed quote into one paper replay request."""
    clean = _codes([code])[0]
    if not isinstance(report, dict) or report.get('execution_ready') is not True:
        raise ValueError('snapshot_not_execution_ready')
    row_report = (report.get('rows') or {}).get(clean) or {}
    if row_report.get('execution_ready') is not True:
        raise ValueError('symbol_not_execution_ready')
    raw = deepcopy(report.get('raw_snapshot') or {})
    quote = deepcopy((raw.get('quotes') or {}).get(clean) or {})
    if not quote:
        raise ValueError('quote_missing')
    checked_at = _api_time(report.get('checked_at'))
    quote_time = _api_time(quote.get('quote_timestamp'))
    day = checked_at.date().isoformat()
    qty = integer(target_quantity, 0)
    venue = quote.get('venue')
    if venue not in ('XSHG', 'XSHE'):
        raise ValueError('instrument_mismatch')
    return {
        'schema': 'nautilus-baseline-v1',
        'data_kind': 'observed_realtime',
        'currency': 'CNY',
        'instrument': {'code': clean, 'venue': venue, 'tick_size': '0.01', 'buy_lot': 100},
        'initial_cash': str(initial_cash),
        'participation': str(participation),
        'max_quote_age_ms': 5000,
        'costs': {
            'commission_rate': '0.0003',
            'minimum_commission': '5.00',
            'sell_tax_rate': '0.0005',
            'transfer_rate': '0.00001',
        },
        'calendar': [day],
        'frames': [{
            'timestamp': checked_at.isoformat(),
            'quote_timestamp': quote_time.isoformat(),
            'bid': money(amount(str(quote.get('bid')))),
            'ask': money(amount(str(quote.get('ask')))),
            'bid_size': integer(quote.get('bid_size'), 1),
            'ask_size': integer(quote.get('ask_size'), 1),
            'market': deepcopy(quote.get('market')),
            'orders': [],
        }],
        'baseline_targets': {day: qty},
    }


def capture_snapshot(codes, timeout=10):
    codes = _codes(codes)
    if not 0 < timeout <= 15:
        raise ValueError('timeout_invalid')
    request = Request(DATA_URL, data=json.dumps({'action': 'hot_snapshot', 'codes': codes}).encode(),
                      headers={'Content-Type': 'application/json'}, method='POST')
    started = time.monotonic()
    with build_opener(_NoRedirect).open(request, timeout=timeout) as response:
        payload = response.read(MAX_RESPONSE + 1)
    if len(payload) > MAX_RESPONSE: raise ValueError('response_too_large')
    decoded = json.loads(payload)
    if decoded.get('success') is not True: raise ValueError('data_api_failed')
    report = assess_snapshot(decoded.get('data'), codes, datetime.now(ZONE))
    report['request_ms'] = round((time.monotonic() - started) * 1000, 2)
    return report

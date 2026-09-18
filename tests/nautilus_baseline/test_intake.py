from copy import deepcopy
from datetime import datetime

import pytest


def snapshot():
    return {
        'snapshot_id': 'provider-snapshot-1', 'received_at': '2026-09-10T10:00:01+08:00',
        'market_phase': 'continuous', 'calendar': ['2026-09-10'], 'stale': False,
        'quotes': {'600000': {
            'code': '600000', 'venue': 'XSHG', 'source': 'fixture_provider',
            'quote_timestamp': '20260910100000', 'timestamp_kind': 'exchange',
            'price': 10, 'bid': '10.00', 'ask': '10.01',
            'bid_size': 1000, 'ask_size': 1000, 'size_unit': 'shares', 'stale': False,
            'market': {'date': '2026-09-10', 'version': 'daily-1', 'suspended': False,
                       'lower_limit': '9.00', 'upper_limit': '11.00'},
        }},
    }


def assess(data, codes=None):
    from trading_system.intake import assess_snapshot
    return assess_snapshot(data, codes or ['600000'], datetime.fromisoformat('2026-09-10T10:00:02+08:00'))


def test_complete_quote_can_pass_but_has_no_execution_authority():
    report = assess(snapshot())
    assert report['execution_ready'] is True
    assert report['coverage'] == {'requested': 1, 'observed': 1, 'ready': 1}
    assert report['live_execution_authority'] is False
    assert report['rows']['600000']['age_ms'] == 2000


def test_ready_snapshot_can_build_single_equity_observed_realtime_request():
    from trading_system.contracts import validate_request
    from trading_system.intake import build_observed_realtime_request

    report = assess(snapshot())
    request = build_observed_realtime_request(report, '600000', target_quantity=100)
    validated = validate_request(request)

    assert validated['data_kind'] == 'observed_realtime'
    assert validated['instrument']['code'] == '600000'
    assert validated['instrument']['venue'] == 'XSHG'
    assert validated['baseline_targets'] == {'2026-09-10': 100}
    assert validated['frames'][0]['bid'] == '10.00'
    assert validated['frames'][0]['ask'] == '10.01'


def test_observed_realtime_request_quantizes_source_price_strings_to_tick_precision():
    from trading_system.intake import build_observed_realtime_request

    data = snapshot()
    data['quotes']['600000']['bid'] = '10.000'
    data['quotes']['600000']['ask'] = '10.010'
    report = assess(data)

    request = build_observed_realtime_request(report, '600000', target_quantity=100)

    assert request['frames'][0]['bid'] == '10.00'
    assert request['frames'][0]['ask'] == '10.01'


def test_unready_snapshot_cannot_build_observed_realtime_request():
    from trading_system.intake import build_observed_realtime_request

    data = snapshot()
    data['quotes']['600000']['stale'] = True
    report = assess(data)

    with pytest.raises(ValueError, match='snapshot_not_execution_ready'):
        build_observed_realtime_request(report, '600000', target_quantity=100)


def test_actual_data_api_continuous_phase_is_recognized():
    data=snapshot(); data['market_phase']='continuous_auction'
    assert assess(data)['execution_ready']


@pytest.mark.parametrize('field,value,reason', [
    ('quote_timestamp', '20260910110000', 'quote_future'),
    ('quote_timestamp', '20260910095900', 'quote_stale'),
    ('timestamp_kind', 'received', 'event_time_unverified'),
    ('size_unit', 'lots', 'quantity_unit_unknown'),
    ('ask_size', None, 'book_invalid'),
    ('bid', '0', 'book_invalid'),
    ('stale', True, 'upstream_stale'),
    ('market', {}, 'market_state_unknown'),
    ('code', '000001', 'instrument_mismatch'),
])
def test_untrusted_quote_is_rejected(field, value, reason):
    data = snapshot()
    data['quotes']['600000'][field] = value
    report = assess(data)
    assert not report['execution_ready']
    assert reason in report['rows']['600000']['reasons']


def test_missing_symbol_cannot_hide_behind_snapshot_observed_count():
    data = snapshot(); data['observed'] = 100
    report = assess(data, ['600000', '000001'])
    assert not report['execution_ready']
    assert report['coverage'] == {'requested': 2, 'observed': 1, 'ready': 1}
    assert report['rows']['000001']['reasons'] == ['quote_missing']


def test_api_snapshot_is_not_mutated_and_original_is_preserved():
    data = snapshot(); before = deepcopy(data)
    result = assess(data)
    assert data == before
    data['quotes'].clear()
    assert result['raw_snapshot'] == before


def test_closed_snapshot_cannot_be_execution_ready():
    data = snapshot(); data['market_phase'] = 'closed'
    assert 'market_not_continuous' in assess(data)['reasons']


def test_unexpected_symbol_does_not_expand_authorized_universe():
    data = snapshot(); data['quotes']['000001'] = deepcopy(data['quotes']['600000'])
    result = assess(data)
    assert not result['execution_ready']
    assert 'unexpected_symbols' in result['reasons']


def test_stale_market_state_rejected_despite_fresh_quote():
    data = snapshot(); data['quotes']['600000']['market']['date'] = '2026-09-09'
    assert 'market_state_stale' in assess(data)['rows']['600000']['reasons']


@pytest.mark.parametrize('received', ['2026-09-10T10:00:03+08:00', '2026-09-10T09:00:00+08:00'])
def test_receipt_time_cannot_be_future_or_older_than_quote(received):
    data=snapshot(); data['received_at']=received
    assert not assess(data)['execution_ready']


def test_venue_must_match_security_code():
    data=snapshot(); data['quotes']['600000']['venue']='XSHE'
    assert not assess(data)['execution_ready']


def test_malformed_calendar_is_not_treated_as_trusted():
    data=snapshot(); data['calendar']=['2026-09-10','2026-09-10']
    assert not assess(data)['execution_ready']


@pytest.mark.parametrize('success', [True, False])
def test_capture_uses_data_api_and_preserves_real_http_payload(monkeypatch, success):
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from trading_system import intake
    data=snapshot()
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if request != {'action':'hot_snapshot','codes':['600000']}:
                self.send_error(400); return
            payload=json.dumps({'success':success,'data':data}).encode()
            self.send_response(200); self.send_header('Content-Length',str(len(payload))); self.end_headers()
            self.wfile.write(payload)
        def log_message(self,*args): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    worker=Thread(target=server.serve_forever,daemon=True); worker.start()
    monkeypatch.setattr(intake,'DATA_URL',f'http://127.0.0.1:{server.server_port}/api/data')
    try:
        if success:
            result=intake.capture_snapshot(['600000'])
            assert result['raw_snapshot']==data
            assert result['request_ms']>0
            # Fixture is historic at capture time; HTTP success does not imply readiness.
            assert not result['execution_ready']
        else:
            with pytest.raises(ValueError,match='data_api_failed'): intake.capture_snapshot(['600000'])
    finally:
        server.shutdown(); worker.join(timeout=5); server.server_close()


@pytest.mark.parametrize('kind', ['redirect', 'malformed', 'timeout'])
def test_http_failures_never_become_valid_data_or_follow_redirect(monkeypatch,kind):
    import json
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from urllib.error import HTTPError
    from trading_system import intake
    visited=[]
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            if kind=='redirect':
                self.send_response(302); self.send_header('Location','/other'); self.end_headers(); return
            if kind=='timeout':time.sleep(.15)
            self.send_response(200); self.end_headers()
            try:self.wfile.write(b'not-json')
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
        def do_GET(self):
            visited.append(self.path)
            self.send_response(200); self.end_headers()
            self.wfile.write(json.dumps({'success':True,'data':snapshot()}).encode())
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=Thread(target=server.serve_forever,daemon=True); thread.start()
    monkeypatch.setattr(intake,'DATA_URL',f'http://127.0.0.1:{server.server_port}/api/data')
    try:
        expected={'redirect':HTTPError,'malformed':json.JSONDecodeError,'timeout':TimeoutError}[kind]
        with pytest.raises(expected):intake.capture_snapshot(['600000'],timeout=.05 if kind=='timeout' else 2)
        assert not visited
    finally:
        server.shutdown(); thread.join(timeout=5); server.server_close()

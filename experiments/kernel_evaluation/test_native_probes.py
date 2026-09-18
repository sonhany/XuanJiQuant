"""These assert native observations, not full A-share or production readiness."""
import json
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip('nautilus_trader', reason='isolated kernel evaluation dependency')
from nautilus_probe import run_native

SCENARIOS = json.loads(Path(__file__).with_name('scenarios.json').read_text())


@pytest.mark.parametrize('scenario', SCENARIOS['cases'], ids=lambda x: x['id'])
def test_nautilus_cash_and_quantity(scenario):
    result = run_native(scenario['id'])
    assert Decimal(result['cash']) == Decimal(scenario['expected_cash'])
    assert result['open_quantity'] == scenario['expected_quantity']
    assert result['event_replay']['matches']
    if scenario['id'] == 'partial_cancel':
        assert result['orders'] == [{'status': 'CANCELED', 'quantity': '1000', 'filled': '400'}]
    if scenario['id'] == 'full':
        assert result['duplicate_engine_event_unchanged']


def test_cash_account_does_not_borrow_by_default():
    result = run_native('insufficient_cash')
    assert Decimal(result['cash']) == 100000
    assert result['open_quantity'] == 0
    assert result['orders'][0]['status'] == 'DENIED'


def test_fresh_engine_replay_is_reproducible():
    assert run_native('partial_complete') == run_native('partial_complete')


def test_passive_order_reserves_then_releases_cash():
    result = run_native('cash_reservation')
    locked=[Decimal(x['locked']) for x in result['account_observations']]
    assert max(locked) == 9000
    assert locked[-1] == 0
    assert result['open_quantity'] == 0


@pytest.mark.parametrize('mode,expected_quantity',[
    ('same_day_roundtrip',1000),('suspended',0),('above_daily_limit',0),('odd_lot',0),
])
@pytest.mark.xfail(strict=True, reason='Observed A-share capability gap in this native configuration; adapter required')
def test_native_configuration_meets_ashare_admission(mode,expected_quantity):
    assert run_native(mode)['open_quantity'] == expected_quantity

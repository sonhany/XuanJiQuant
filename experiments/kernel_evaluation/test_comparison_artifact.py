"""Cross-engine assertions against collected native observations."""
from decimal import Decimal
import json
from pathlib import Path

import pytest

REPORT = Path(__file__).resolve().parents[2] / 'data/kernel-evaluation/comparison.json'


@pytest.fixture
def report():
    if not REPORT.is_file():
        pytest.skip('run the isolated native comparison first')
    return json.loads(REPORT.read_text(encoding='utf-8'))


def test_both_native_engines_ran_all_cases(report):
    assert len(report['nautilus']) == len(report['lean']) == 10
    assert {x['mode'] for x in report['nautilus']} == {x['mode'] for x in report['lean']}
    assert all(x['exit_code'] == 0 and x['ticks'] == 4 for x in report['lean'])
    assert report['production_authority'] is False


@pytest.mark.parametrize('mode,quantity,cash',[
    ('full',1000,89995),('insufficient_cash',0,100000),('same_day_roundtrip',0,99990)
])
def test_common_cash_math_includes_unsettled_cash(report,mode,quantity,cash):
    native=next(x for x in report['nautilus'] if x['mode']==mode)
    lean=next(x for x in report['lean'] if x['mode']==mode)
    assert native['open_quantity'] == lean['quantity'] == quantity
    assert Decimal(native['cash']) == cash
    assert Decimal(str(lean['cash'])) + Decimal(str(lean['unsettled_cash'])) == cash


def test_native_accounting_fixture_assertions_completed(report):
    assert report['lean_accounting']['exit_code'] == 0
    results=[x for x in report['lean_accounting']['results'] if 'passed' in x]
    assert len(results)==4
    assert all(x['passed'] for x in results)

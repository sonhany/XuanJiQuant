from datetime import datetime
import json

import pytest


def baseline_result():
    return {
        'schema': 'nautilus-baseline-result-v1',
        'mode': 'continuous_full_replay',
        'batch_id': 'baseline-ctx',
        'account_id': 'demo',
        'revision': 5,
        'cash': '99054.99',
        'equity': '99993.99',
        'positions': {'600000': 100, '000001': 200},
        'orders': [{'id': 'o1', 'quantity': 100, 'filled_quantity': 100}],
        'fills': [{'intent_id': 'o1', 'side': 'buy', 'quantity': 100, 'price': '9.40'}],
        'reconciliation': {'passed': True, 'checks': {'cash': True, 'positions': True}},
        'live_execution_authority': False,
    }


def test_shadow_context_exposes_only_read_only_ai_inputs_and_binds_baseline():
    from trading_system.contracts import digest
    from trading_system.shadow_context import build_shadow_decision_context, validate_shadow_decision_context

    context = build_shadow_decision_context(
        baseline_result=baseline_result(),
        market={'snapshot_id': 'snap-1', 'phase': 'continuous', 'source': 'local_api'},
        risk={'level': 'medium', 'summary': '组合集中度正常。'},
        factor={'version': 'factor-v1', 'top_codes': ['600000', '600519']},
        strategy={'version': 'strategy-v1', 'target_weights': [{'code': '600000', 'weight': 0.08}, {'code': '600519', 'weight': 0.04}]},
        history={'fill_count': 1, 'traded_codes': ['600000']},
        generated_at=datetime.fromisoformat('2026-09-14T14:20:00+08:00'),
    )
    validated = validate_shadow_decision_context(context)

    assert validated['schema'] == 'xuanji-shadow-decision-context-v1'
    assert validated['mode'] == 'shadow_context'
    assert validated['read_only'] is True
    assert validated['execution_authority'] is False
    assert validated['can_trigger_order'] is False
    assert validated['live_execution_authority'] is False
    assert validated['baseline_binding']['baseline_result_hash'] == digest(baseline_result())
    assert validated['baseline_binding']['position_codes'] == ['000001', '600000']
    assert validated['strategy']['target_weights'][1] == {'code': '600519', 'weight': 0.04}

    serialized = json.dumps(validated, ensure_ascii=False).lower()
    for forbidden in ('orders', 'fills', 'side', 'quantity', 'price', 'broker', 'agent_'):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    'section,value,reason',
    [
        ('market', {'snapshot_id': 'snap-1', 'agent_plan': 'old'}, 'execution_field_forbidden'),
        ('strategy', {'target_weights': [{'code': '600000', 'weight': 0.08}], 'orders': []}, 'execution_field_forbidden'),
        ('history', {'fill_count': 1, 'fills': []}, 'execution_field_forbidden'),
    ],
)
def test_shadow_context_rejects_execution_fields_in_ai_visible_sections(section, value, reason):
    from trading_system.shadow_context import build_shadow_decision_context

    kwargs = {
        'baseline_result': baseline_result(),
        'market': {'snapshot_id': 'snap-1'},
        'risk': {'level': 'low'},
        'factor': {'version': 'factor-v1'},
        'strategy': {'target_weights': []},
        'history': {'fill_count': 0},
    }
    kwargs[section] = value
    with pytest.raises(ValueError, match=reason):
        build_shadow_decision_context(**kwargs)


def test_shadow_context_requires_reconciled_paper_baseline():
    from trading_system.shadow_context import build_shadow_decision_context

    bad = baseline_result()
    bad['reconciliation']['passed'] = False
    with pytest.raises(ValueError, match='baseline_not_reconciled'):
        build_shadow_decision_context(baseline_result=bad)

    bad = baseline_result()
    bad['live_execution_authority'] = True
    with pytest.raises(ValueError, match='baseline_must_be_paper_only'):
        build_shadow_decision_context(baseline_result=bad)

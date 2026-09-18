from datetime import datetime
import json

import pytest


def baseline_result():
    return {
        'schema': 'nautilus-baseline-result-v1',
        'mode': 'continuous_full_replay',
        'batch_id': 'baseline-1',
        'account_id': 'demo',
        'revision': 3,
        'cash': '99054.99',
        'equity': '99993.99',
        'positions': {'600000': 100},
        'reconciliation': {'passed': True, 'checks': {'cash': True, 'positions': True}},
        'live_execution_authority': False,
    }


def test_ai_shadow_decision_proposal_is_read_only_and_baseline_bound():
    from trading_system.contracts import digest
    from trading_system.shadow_decision import build_decision_proposal, validate_decision_proposal

    proposal = build_decision_proposal(
        producer={'kind': 'ai_shadow', 'model_id': 'shadow-model-a', 'prompt_version': 'p1'},
        evidence={'market_snapshot_id': 'snap-1', 'account_revision': 3, 'signal_hash': 'a' * 64},
        recommendation={
            'stance': 'rebalance_candidate',
            'target_weights': [{'code': '600000', 'weight': 0.1}],
            'confidence': 0.61,
            'rationale': '基线已成交，影子建议保持小比例观察。',
            'orders': [{'side': 'buy', 'quantity': 100, 'limit_price': '9.40'}],
            'broker': 'forbidden',
        },
        baseline_result=baseline_result(),
        generated_at=datetime.fromisoformat('2026-09-14T13:40:00+08:00'),
    )
    validated = validate_decision_proposal(proposal)

    assert validated['schema'] == 'xuanji-decision-proposal-v1'
    assert validated['mode'] == 'shadow_only'
    assert validated['execution_authority'] is False
    assert validated['can_trigger_order'] is False
    assert validated['can_change_trade_policy'] is False
    assert validated['live_execution_authority'] is False
    assert validated['baseline_comparison']['baseline_result_hash'] == digest(baseline_result())
    assert validated['evidence']['signal_hash'] == 'a' * 64
    assert validated['recommendation']['target_weights'] == [{'code': '600000', 'weight': 0.1}]

    serialized = json.dumps(validated, ensure_ascii=False).lower()
    for forbidden in ('orders', 'side', 'quantity', 'limit_price', 'broker', 'agent_'):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    'mutation,reason',
    [
        (lambda p: p.__setitem__('can_trigger_order', True), 'shadow_authority_required'),
        (lambda p: p['recommendation']['target_weights'].__setitem__(0, {'code': '600000', 'weight': 1.2}), 'weight_invalid'),
        (lambda p: p['recommendation'].__setitem__('target_weights', [{'code': '600000', 'weight': 0.7}, {'code': '000001', 'weight': 0.4}]), 'weight_sum_invalid'),
        (lambda p: p['recommendation'].__setitem__('order', {'side': 'buy'}), 'execution_field_forbidden'),
        (lambda p: p['producer'].__setitem__('kind', 'planner'), 'producer_kind_invalid'),
    ],
)
def test_shadow_decision_validation_rejects_authority_and_execution_leakage(mutation, reason):
    from trading_system.shadow_decision import build_decision_proposal, validate_decision_proposal

    proposal = build_decision_proposal(
        producer={'kind': 'ai_shadow', 'model_id': 'shadow-model-a', 'prompt_version': 'p1'},
        evidence={'market_snapshot_id': 'snap-1'},
        recommendation={'stance': 'hold', 'target_weights': [{'code': '600000', 'weight': 0.1}], 'confidence': 0.5, 'rationale': '只读影子。'},
        baseline_result=baseline_result(),
        generated_at=datetime.fromisoformat('2026-09-14T13:40:00+08:00'),
    )
    mutation(proposal)

    with pytest.raises(ValueError, match=reason):
        validate_decision_proposal(proposal)


def test_shadow_decision_requires_reconciled_paper_baseline_without_live_authority():
    from trading_system.shadow_decision import build_decision_proposal

    bad = baseline_result()
    bad['reconciliation']['passed'] = False
    with pytest.raises(ValueError, match='baseline_not_reconciled'):
        build_decision_proposal(
            producer={'kind': 'ai_shadow', 'model_id': 'shadow-model-a', 'prompt_version': 'p1'},
            evidence={'market_snapshot_id': 'snap-1'},
            recommendation={'stance': 'hold', 'target_weights': [], 'confidence': 0.5, 'rationale': '只读影子。'},
            baseline_result=bad,
        )

    bad = baseline_result()
    bad['live_execution_authority'] = True
    with pytest.raises(ValueError, match='baseline_must_be_paper_only'):
        build_decision_proposal(
            producer={'kind': 'ai_shadow', 'model_id': 'shadow-model-a', 'prompt_version': 'p1'},
            evidence={'market_snapshot_id': 'snap-1'},
            recommendation={'stance': 'hold', 'target_weights': [], 'confidence': 0.5, 'rationale': '只读影子。'},
            baseline_result=bad,
        )

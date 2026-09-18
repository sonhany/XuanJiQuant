from datetime import datetime
import json
import subprocess
import sys


def baseline_result():
    return {
        'schema': 'nautilus-baseline-result-v1',
        'mode': 'continuous_full_replay',
        'batch_id': 'baseline-builder',
        'account_id': 'demo',
        'revision': 8,
        'cash': '99054.99',
        'equity': '99993.99',
        'positions': {'600000': 100, '000001': 200},
        'orders': [{'id': 'o1', 'quantity': 100, 'filled_quantity': 100}],
        'fills': [{'intent_id': 'o1', 'side': 'buy', 'quantity': 100, 'price': '9.40'}],
        'reconciliation': {'passed': True, 'checks': {'cash': True, 'positions': True}},
        'valuation_timestamp': '20260914143000',
        'live_execution_authority': False,
    }


def market_summary():
    return {
        'snapshot_id': 'snap-builder',
        'received_at': '2026-09-14T14:30:01+08:00',
        'market_phase': 'continuous',
        'execution_ready': True,
        'coverage': {'requested': 2, 'observed': 2, 'ready': 2},
        'raw_snapshot': {'quotes': {'600000': {'price': '9.40', 'bid': '9.39'}}},
    }


def test_runtime_context_builder_assembles_read_only_context_from_real_summaries():
    from trading_system.contracts import digest
    from trading_system.shadow_context import validate_shadow_decision_context
    from trading_system.shadow_context_builder import build_runtime_shadow_context

    context = build_runtime_shadow_context(
        baseline_result=baseline_result(),
        market_summary=market_summary(),
        risk_summary={'level': 'medium', 'summary': '组合风险中等', 'computed_at': '2026-09-14T14:30:02+08:00'},
        factor_summary={'version': 'factor-v1', 'factor_count': 58, 'top_codes': ['600000', '600519']},
        strategy_summary={'version': 'strategy-v1', 'status': 'candidate', 'target_weights': [{'code': '600000', 'weight': 0.08}, {'code': '600519', 'weight': 0.04}], 'orders': []},
        generated_at=datetime.fromisoformat('2026-09-14T14:35:00+08:00'),
    )
    validated = validate_shadow_decision_context(context)

    assert validated['account']['baseline_result_hash'] == digest(baseline_result())
    assert validated['account']['cash'] == '99054.99'
    assert validated['account']['equity'] == '99993.99'
    assert validated['account']['position_count'] == 2
    assert validated['account']['position_codes'] == ['000001', '600000']
    assert validated['market']['snapshot_id'] == 'snap-builder'
    assert validated['market']['coverage'] == {'requested': 2, 'observed': 2, 'ready': 2}
    assert validated['factor']['top_codes'] == ['600000', '600519']
    assert validated['strategy']['target_weights'][1] == {'code': '600519', 'weight': 0.04}
    assert validated['history']['fill_count'] == 1

    serialized = json.dumps(validated, ensure_ascii=False).lower()
    for forbidden in ('orders', 'fills', 'side', 'quantity', 'price', 'bid', 'broker', 'agent_'):
        assert forbidden not in serialized


def test_runtime_context_builder_rejects_unreconciled_or_live_baseline():
    from trading_system.shadow_context_builder import build_runtime_shadow_context
    import pytest

    bad = baseline_result()
    bad['reconciliation']['passed'] = False
    with pytest.raises(ValueError, match='baseline_not_reconciled'):
        build_runtime_shadow_context(baseline_result=bad)

    bad = baseline_result()
    bad['live_execution_authority'] = True
    with pytest.raises(ValueError, match='baseline_must_be_paper_only'):
        build_runtime_shadow_context(baseline_result=bad)


def test_shadow_context_build_cli_writes_context_without_touching_execution_journal(tmp_path):
    baseline = tmp_path / 'baseline.json'
    market = tmp_path / 'market.json'
    risk = tmp_path / 'risk.json'
    factor = tmp_path / 'factor.json'
    strategy = tmp_path / 'strategy.json'
    output = tmp_path / 'context.json'
    execution_journal = tmp_path / 'must-not-exist.sqlite3'
    baseline.write_text(json.dumps(baseline_result(), ensure_ascii=False), encoding='utf-8')
    market.write_text(json.dumps(market_summary(), ensure_ascii=False), encoding='utf-8')
    risk.write_text(json.dumps({'level': 'low'}, ensure_ascii=False), encoding='utf-8')
    factor.write_text(json.dumps({'version': 'factor-v1', 'top_codes': ['600000']}, ensure_ascii=False), encoding='utf-8')
    strategy.write_text(json.dumps({'version': 'strategy-v1', 'target_weights': [{'code': '600000', 'weight': 0.08}]}, ensure_ascii=False), encoding='utf-8')

    process = subprocess.run(
        [
            sys.executable,
            '-m',
            'trading_system.cli',
            '--journal',
            str(execution_journal),
            'shadow-context-build',
            '--baseline-result',
            str(baseline),
            '--market-summary',
            str(market),
            '--risk-summary',
            str(risk),
            '--factor-summary',
            str(factor),
            '--strategy-summary',
            str(strategy),
            '--output',
            str(output),
        ],
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=30,
    )

    assert process.returncode == 0, process.stdout + process.stderr
    payload = json.loads(process.stdout)
    assert payload['mode'] == 'shadow_decision'
    assert payload['data']['path'] == str(output)
    context = json.loads(output.read_text(encoding='utf-8'))
    assert context['schema'] == 'xuanji-shadow-decision-context-v1'
    assert context['execution_authority'] is False
    assert not execution_journal.exists()

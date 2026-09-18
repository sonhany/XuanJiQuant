from datetime import datetime
import json
import subprocess
import sys


def context_payload(risk=None):
    from trading_system.shadow_context import build_shadow_decision_context

    baseline = {
        'schema': 'nautilus-baseline-result-v1',
        'mode': 'continuous_full_replay',
        'batch_id': 'baseline-run',
        'account_id': 'demo',
        'revision': 6,
        'cash': '99054.99',
        'equity': '99993.99',
        'positions': {'600000': 100},
        'reconciliation': {'passed': True, 'checks': {'cash': True, 'positions': True}},
        'live_execution_authority': False,
    }
    return build_shadow_decision_context(
        baseline_result=baseline,
        market={'snapshot_id': 'snap-run', 'phase': 'continuous'},
        risk=risk or {'level': 'low'},
        factor={'version': 'factor-v1', 'top_codes': ['600000', '600519']},
        strategy={'version': 'strategy-v1', 'target_weights': [{'code': '600000', 'weight': 0.08}, {'code': '600519', 'weight': 0.04}]},
        history={'fill_count': 1, 'traded_codes': ['600000']},
        generated_at=datetime.fromisoformat('2026-09-14T14:30:00+08:00'),
    )


def test_shadow_runner_generates_valid_proposal_from_fixed_context_and_records(tmp_path):
    from trading_system.contracts import digest
    from trading_system.shadow_decision import validate_decision_proposal
    from trading_system.shadow_decision_store import ShadowDecisionJournal
    from trading_system.shadow_runner import run_shadow_decision

    with ShadowDecisionJournal(tmp_path / 'shadow.sqlite3') as journal:
        result = run_shadow_decision(context_payload(), journal=journal)
        report = journal.report()

    proposal = validate_decision_proposal(result['proposal'])
    assert result['schema'] == 'xuanji-shadow-run-result-v1'
    assert result['mode'] == 'shadow_decision'
    assert result['record_status'] == 'recorded'
    assert result['execution_authority'] is False
    assert proposal['producer']['kind'] == 'local_shadow_model'
    assert proposal['evidence']['context_hash'] == digest(context_payload())
    assert proposal['evidence']['market_snapshot_id'] == 'snap-run'
    assert proposal['recommendation']['stance'] == 'rebalance_candidate'
    assert proposal['recommendation']['target_weights'][1] == {'code': '600519', 'weight': 0.04}
    assert report['summary']['total'] == 1


def test_shadow_runner_high_risk_context_only_proposes_reduce_risk(tmp_path):
    from trading_system.shadow_runner import run_shadow_decision

    context = context_payload(risk={'level': 'high'})
    result = run_shadow_decision(context)

    assert result['proposal']['recommendation']['stance'] == 'reduce_risk'
    assert result['proposal']['recommendation']['target_weights'] == []
    assert result['record_status'] is None


def test_shadow_run_cli_records_context_without_touching_execution_journal(tmp_path):
    source = tmp_path / 'context.json'
    shadow_store = tmp_path / 'shadow.sqlite3'
    execution_journal = tmp_path / 'must-not-exist.sqlite3'
    source.write_text(json.dumps(context_payload(), ensure_ascii=False), encoding='utf-8')

    process = subprocess.run(
        [
            sys.executable,
            '-m',
            'trading_system.cli',
            '--journal',
            str(execution_journal),
            '--shadow-store',
            str(shadow_store),
            'shadow-run',
            '--context',
            str(source),
        ],
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=30,
    )

    assert process.returncode == 0, process.stdout + process.stderr
    payload = json.loads(process.stdout)
    assert payload['mode'] == 'shadow_decision'
    assert payload['data']['record_status'] == 'recorded'
    assert shadow_store.exists()
    assert not execution_journal.exists()

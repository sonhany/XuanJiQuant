from datetime import datetime
import json
import subprocess
import sys


def baseline_result():
    return {
        'schema': 'nautilus-baseline-result-v1',
        'mode': 'continuous_full_replay',
        'batch_id': 'baseline-1',
        'account_id': 'demo',
        'revision': 4,
        'cash': '99054.99',
        'equity': '99993.99',
        'positions': {'600000': 100, '000001': 200},
        'reconciliation': {'passed': True, 'checks': {'cash': True, 'positions': True}},
        'live_execution_authority': False,
    }


def proposal(weights=None, stance='rebalance_candidate', confidence=0.62):
    from trading_system.shadow_decision import build_decision_proposal

    return build_decision_proposal(
        producer={'kind': 'ai_shadow', 'model_id': 'shadow-model-a', 'prompt_version': 'p1'},
        evidence={'market_snapshot_id': 'snap-1', 'account_revision': 4, 'signal_hash': 'b' * 64},
        recommendation={
            'stance': stance,
            'target_weights': weights if weights is not None else [{'code': '600000', 'weight': 0.08}, {'code': '600519', 'weight': 0.04}],
            'confidence': confidence,
            'rationale': '只读影子建议，仅用于和基线对照。',
        },
        baseline_result=baseline_result(),
        generated_at=datetime.fromisoformat('2026-09-14T14:10:00+08:00'),
    )


def test_shadow_store_persists_idempotent_proposals_and_reports_baseline_deltas(tmp_path):
    from trading_system.contracts import digest
    from trading_system.shadow_decision_store import ShadowDecisionJournal

    store = tmp_path / 'shadow.sqlite3'
    with ShadowDecisionJournal(store) as journal:
        first = journal.record(proposal())
        second = journal.record(proposal())
        report = journal.report()

    assert first['status'] == 'recorded'
    assert second['status'] == 'existing'
    assert report['schema'] == 'xuanji-shadow-decision-report-v1'
    assert report['live_execution_authority'] is False
    assert report['summary']['total'] == 1
    assert report['summary']['by_stance'] == {'rebalance_candidate': 1}
    assert report['summary']['baseline_result_hashes'] == [digest(baseline_result())]
    assert report['proposals'][0]['shadow_only_codes'] == ['600519']
    assert report['proposals'][0]['baseline_only_codes'] == ['000001']
    assert report['proposals'][0]['overlap_codes'] == ['600000']
    assert report['proposals'][0]['position_code_delta_count'] == 2


def test_shadow_store_rejects_mutated_duplicate_identity(tmp_path):
    from trading_system.shadow_decision_store import ShadowDecisionJournal

    original = proposal()
    mutated = dict(original)
    mutated['recommendation'] = dict(original['recommendation'])
    mutated['recommendation']['rationale'] = '篡改后的影子建议。'
    with ShadowDecisionJournal(tmp_path / 'shadow.sqlite3') as journal:
        journal.record(original)
        try:
            journal.conn.execute(
                "UPDATE shadow_proposals SET proposal_hash='bad-hash' WHERE proposal_id=?",
                (original['proposal_id'],),
            )
            journal.conn.commit()
            raised = None
            journal.record(original)
        except ValueError as exc:
            raised = str(exc)

    assert raised == 'shadow_proposal_integrity_failed'


def test_shadow_cli_records_and_reports_without_touching_execution_journal(tmp_path):
    source = tmp_path / 'proposal.json'
    shadow_store = tmp_path / 'shadow.sqlite3'
    execution_journal = tmp_path / 'must-not-exist.sqlite3'
    source.write_text(json.dumps(proposal(), ensure_ascii=False), encoding='utf-8')

    common = [
        sys.executable,
        '-m',
        'trading_system.cli',
        '--journal',
        str(execution_journal),
        '--shadow-store',
        str(shadow_store),
    ]
    recorded = subprocess.run(
        common + ['shadow-record', '--input', str(source)],
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=30,
    )
    reported = subprocess.run(
        common + ['shadow-report'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=30,
    )

    assert recorded.returncode == 0, recorded.stdout + recorded.stderr
    assert reported.returncode == 0, reported.stdout + reported.stderr
    assert json.loads(recorded.stdout)['mode'] == 'shadow_decision'
    payload = json.loads(reported.stdout)
    assert payload['data']['summary']['total'] == 1
    assert payload['data']['proposals'][0]['shadow_only_codes'] == ['600519']
    assert shadow_store.exists()
    assert not execution_journal.exists()

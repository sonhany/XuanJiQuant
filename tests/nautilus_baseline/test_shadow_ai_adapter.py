from datetime import datetime
import json
import subprocess
import sys


def context_payload():
    from trading_system.shadow_context import build_shadow_decision_context

    baseline = {
        'schema': 'nautilus-baseline-result-v1',
        'mode': 'continuous_full_replay',
        'batch_id': 'baseline-ai',
        'account_id': 'demo',
        'revision': 7,
        'cash': '99054.99',
        'equity': '99993.99',
        'positions': {'600000': 100},
        'reconciliation': {'passed': True, 'checks': {'cash': True, 'positions': True}},
        'live_execution_authority': False,
    }
    return build_shadow_decision_context(
        baseline_result=baseline,
        market={'snapshot_id': 'snap-ai', 'phase': 'continuous'},
        risk={'level': 'low'},
        factor={'version': 'factor-v1', 'top_codes': ['600000', '600519']},
        strategy={'version': 'strategy-v1', 'target_weights': [{'code': '600000', 'weight': 0.08}]},
        history={'fill_count': 1, 'traded_codes': ['600000']},
        generated_at=datetime.fromisoformat('2026-09-14T14:50:00+08:00'),
    )


def ai_raw_output():
    return json.dumps({
        'recommendation': {
            'stance': 'rebalance_candidate',
            'target_weights': [{'code': '600000', 'weight': 0.06}, {'code': '600519', 'weight': 0.04}],
            'confidence': 0.66,
            'rationale': '外部AI影子建议保留600000并观察600519。',
            'orders': [{'side': 'buy', 'quantity': 100, 'limit_price': '9.40'}],
            'broker': 'forbidden',
        }
    }, ensure_ascii=False)


def test_shadow_ai_adapter_records_raw_sanitized_output_and_valid_proposal(tmp_path):
    from trading_system.shadow_ai_adapter import run_shadow_ai
    from trading_system.shadow_decision_store import ShadowDecisionJournal

    calls = []

    def fake_client(request):
        calls.append(request)
        return ai_raw_output()

    with ShadowDecisionJournal(tmp_path / 'shadow.sqlite3') as journal:
        result = run_shadow_ai(
            context_payload(),
            model_client=fake_client,
            journal=journal,
            producer={'kind': 'ai_shadow', 'model_id': 'fake-ai', 'prompt_version': 'p1'},
            generated_at=datetime.fromisoformat('2026-09-14T14:51:00+08:00'),
        )
        audit = journal.ai_audit_report()

    assert result['schema'] == 'xuanji-shadow-ai-run-result-v1'
    assert result['status'] == 'recorded'
    assert result['proposal']['producer']['kind'] == 'ai_shadow'
    assert result['proposal']['recommendation']['target_weights'][1] == {'code': '600519', 'weight': 0.04}
    assert 'orders' not in json.dumps(result['proposal'], ensure_ascii=False).lower()
    assert calls[0]['schema'] == 'xuanji-shadow-ai-request-v1'
    assert 'orders' not in json.dumps(calls[0], ensure_ascii=False).lower()
    assert audit['summary']['total'] == 1
    assert audit['runs'][0]['status'] == 'recorded'
    assert 'orders' in audit['runs'][0]['raw_output']
    assert 'orders' not in audit['runs'][0]['sanitized_output']
    assert audit['runs'][0]['validation_error'] is None


def test_shadow_ai_adapter_records_validation_failure_without_proposal(tmp_path):
    from trading_system.shadow_ai_adapter import run_shadow_ai
    from trading_system.shadow_decision_store import ShadowDecisionJournal

    with ShadowDecisionJournal(tmp_path / 'shadow.sqlite3') as journal:
        result = run_shadow_ai(
            context_payload(),
            raw_output=json.dumps({'recommendation': {'stance': 'rebalance_candidate', 'target_weights': [{'code': '600000', 'weight': 1.2}], 'confidence': 0.6, 'rationale': 'bad'}}),
            journal=journal,
            producer={'kind': 'ai_shadow', 'model_id': 'fake-ai', 'prompt_version': 'p1'},
        )
        audit = journal.ai_audit_report()

    assert result['status'] == 'validation_failed'
    assert result['proposal'] is None
    assert 'weight_invalid' in result['validation_error']
    assert audit['runs'][0]['status'] == 'validation_failed'
    assert 'weight_invalid' in audit['runs'][0]['validation_error']
    assert audit['runs'][0]['proposal_id'] is None


def test_shadow_ai_cli_raw_output_records_audit_and_does_not_touch_execution_journal(tmp_path):
    context = tmp_path / 'context.json'
    raw = tmp_path / 'raw.json'
    shadow_store = tmp_path / 'shadow.sqlite3'
    execution_journal = tmp_path / 'must-not-exist.sqlite3'
    context.write_text(json.dumps(context_payload(), ensure_ascii=False), encoding='utf-8')
    raw.write_text(ai_raw_output(), encoding='utf-8')

    process = subprocess.run(
        [
            sys.executable,
            '-m',
            'trading_system.cli',
            '--journal',
            str(execution_journal),
            '--shadow-store',
            str(shadow_store),
            'shadow-ai-run',
            '--context',
            str(context),
            '--raw-output',
            str(raw),
        ],
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=30,
    )

    assert process.returncode == 0, process.stdout + process.stderr
    payload = json.loads(process.stdout)
    assert payload['mode'] == 'shadow_decision'
    assert payload['data']['status'] == 'recorded'
    assert shadow_store.exists()
    assert not execution_journal.exists()

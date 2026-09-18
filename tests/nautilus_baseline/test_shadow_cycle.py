from datetime import datetime
import json
import subprocess
import sys


def baseline_result():
    return {
        'schema': 'nautilus-baseline-result-v1',
        'mode': 'continuous_full_replay',
        'batch_id': 'baseline-cycle',
        'account_id': 'demo',
        'revision': 9,
        'cash': '99054.99',
        'equity': '99993.99',
        'positions': {'600000': 100},
        'orders': [{'id': 'o1', 'quantity': 100}],
        'fills': [{'intent_id': 'o1', 'side': 'buy', 'quantity': 100, 'price': '9.40'}],
        'reconciliation': {'passed': True, 'checks': {'cash': True, 'positions': True}},
        'live_execution_authority': False,
    }


def raw_output(weight=0.05):
    return json.dumps({
        'recommendation': {
            'stance': 'rebalance_candidate',
            'target_weights': [{'code': '600000', 'weight': weight}, {'code': '600519', 'weight': 0.04}],
            'confidence': 0.67,
            'rationale': '影子AI仅建议研究组合对照。',
            'orders': [{'side': 'buy', 'quantity': 100, 'limit_price': '9.40'}],
        }
    }, ensure_ascii=False)


def summaries():
    return {
        'market_summary': {'snapshot_id': 'snap-cycle', 'market_phase': 'continuous', 'execution_ready': True, 'coverage': {'requested': 2, 'observed': 2, 'ready': 2}},
        'risk_summary': {'level': 'low', 'summary': '风险低'},
        'factor_summary': {'version': 'factor-v1', 'top_codes': ['600000', '600519']},
        'strategy_summary': {'version': 'strategy-v1', 'target_weights': [{'code': '600000', 'weight': 0.08}]},
    }


def test_shadow_cycle_builds_context_runs_ai_records_reports_and_writes_artifacts(tmp_path):
    from trading_system.shadow_cycle import run_shadow_cycle
    from trading_system.shadow_decision_store import ShadowDecisionJournal

    context_out = tmp_path / 'context.json'
    report_out = tmp_path / 'report.json'
    with ShadowDecisionJournal(tmp_path / 'shadow.sqlite3') as journal:
        result = run_shadow_cycle(
            baseline_result=baseline_result(),
            raw_output=raw_output(),
            journal=journal,
            context_output=context_out,
            report_output=report_out,
            generated_at=datetime.fromisoformat('2026-09-14T15:00:00+08:00'),
            **summaries(),
        )

    assert result['schema'] == 'xuanji-shadow-cycle-result-v1'
    assert result['mode'] == 'shadow_decision'
    assert result['status'] == 'recorded'
    assert result['execution_authority'] is False
    assert result['context']['schema'] == 'xuanji-shadow-decision-context-v1'
    assert result['ai_result']['proposal']['recommendation']['target_weights'][1] == {'code': '600519', 'weight': 0.04}
    assert result['proposal_report']['summary']['total'] == 1
    assert result['proposal_report']['proposals'][0]['shadow_only_codes'] == ['600519']
    assert result['ai_audit_report']['summary']['by_status'] == {'recorded': 1}
    assert json.loads(context_out.read_text(encoding='utf-8'))['context_id'] == result['context']['context_id']
    assert json.loads(report_out.read_text(encoding='utf-8'))['proposal_report']['summary']['total'] == 1


def test_shadow_cycle_records_ai_validation_failure_without_proposal(tmp_path):
    from trading_system.shadow_cycle import run_shadow_cycle
    from trading_system.shadow_decision_store import ShadowDecisionJournal

    with ShadowDecisionJournal(tmp_path / 'shadow.sqlite3') as journal:
        result = run_shadow_cycle(
            baseline_result=baseline_result(),
            raw_output=raw_output(weight=1.2),
            journal=journal,
            **summaries(),
        )

    assert result['status'] == 'validation_failed'
    assert result['ai_result']['proposal'] is None
    assert result['proposal_report']['summary']['total'] == 0
    assert result['ai_audit_report']['summary']['by_status'] == {'validation_failed': 1}


def test_shadow_cycle_cli_does_not_touch_execution_journal(tmp_path):
    baseline = tmp_path / 'baseline.json'
    raw = tmp_path / 'raw.json'
    market = tmp_path / 'market.json'
    risk = tmp_path / 'risk.json'
    factor = tmp_path / 'factor.json'
    strategy = tmp_path / 'strategy.json'
    context_out = tmp_path / 'context.json'
    report_out = tmp_path / 'report.json'
    shadow_store = tmp_path / 'shadow.sqlite3'
    execution_journal = tmp_path / 'must-not-exist.sqlite3'
    baseline.write_text(json.dumps(baseline_result(), ensure_ascii=False), encoding='utf-8')
    raw.write_text(raw_output(), encoding='utf-8')
    values = summaries()
    market.write_text(json.dumps(values['market_summary'], ensure_ascii=False), encoding='utf-8')
    risk.write_text(json.dumps(values['risk_summary'], ensure_ascii=False), encoding='utf-8')
    factor.write_text(json.dumps(values['factor_summary'], ensure_ascii=False), encoding='utf-8')
    strategy.write_text(json.dumps(values['strategy_summary'], ensure_ascii=False), encoding='utf-8')

    process = subprocess.run(
        [
            sys.executable,
            '-m',
            'trading_system.cli',
            '--journal',
            str(execution_journal),
            '--shadow-store',
            str(shadow_store),
            'shadow-cycle',
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
            '--raw-output',
            str(raw),
            '--context-output',
            str(context_out),
            '--report-output',
            str(report_out),
        ],
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=30,
    )

    assert process.returncode == 0, process.stdout + process.stderr
    payload = json.loads(process.stdout)
    assert payload['mode'] == 'shadow_decision'
    assert payload['data']['proposal_report']['summary']['total'] == 1
    assert context_out.exists()
    assert report_out.exists()
    assert shadow_store.exists()
    assert not execution_journal.exists()

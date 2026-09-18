from datetime import datetime
import json
import subprocess
import sys


def baseline_result():
    return {
        'schema': 'nautilus-baseline-result-v1',
        'mode': 'continuous_full_replay',
        'batch_id': 'baseline-runtime',
        'account_id': 'demo',
        'revision': 10,
        'cash': '99054.99',
        'equity': '99993.99',
        'positions': {'600000': 100, '000001': 200},
        'orders': [{'id': 'o1', 'quantity': 100}],
        'fills': [{'intent_id': 'o1', 'side': 'buy', 'quantity': 100, 'price': '9.40'}],
        'reconciliation': {'passed': True, 'checks': {'cash': True, 'positions': True}},
        'live_execution_authority': False,
    }


def summaries():
    return {
        'market_summary': {'snapshot_id': 'snap-runtime', 'market_phase': 'continuous', 'execution_ready': True},
        'risk_summary': {'level': 'low', 'summary': '低风险'},
        'factor_summary': {'version': 'factor-v1', 'top_codes': ['600000', '600519']},
        'strategy_summary': {'version': 'strategy-v1', 'target_weights': [{'code': '600000', 'weight': 0.08}, {'code': '600519', 'weight': 0.04}]},
    }


def raw_output():
    return json.dumps({
        'recommendation': {
            'stance': 'rebalance_candidate',
            'target_weights': [{'code': '600000', 'weight': 0.06}, {'code': '600519', 'weight': 0.04}],
            'confidence': 0.68,
            'rationale': 'runtime summary 影子研究建议。',
        }
    }, ensure_ascii=False)


def test_runtime_summary_exports_controlled_bundle_and_builds_context_without_execution_fields():
    from trading_system.shadow_runtime_summary import build_shadow_runtime_summary, build_context_from_runtime_summary

    runtime = build_shadow_runtime_summary(
        baseline_result=baseline_result(),
        generated_at=datetime.fromisoformat('2026-09-15T09:40:00+08:00'),
        **summaries(),
    )
    context = build_context_from_runtime_summary(runtime)

    assert runtime['schema'] == 'xuanji-shadow-runtime-summary-v1'
    assert runtime['mode'] == 'shadow_runtime_summary'
    assert runtime['live_execution_authority'] is False
    assert runtime['baseline_result']['batch_id'] == 'baseline-runtime'
    assert runtime['source_hashes']['baseline_result']
    assert context['market']['snapshot_id'] == 'snap-runtime'
    assert context['strategy']['target_weights'][1] == {'code': '600519', 'weight': 0.04}
    serialized = json.dumps(context, ensure_ascii=False).lower()
    for forbidden in ('orders', 'fills', 'side', 'quantity', 'price', 'broker', 'agent_'):
        assert forbidden not in serialized


def test_shadow_runtime_summary_cli_and_cycle_runtime_summary_do_not_touch_execution_journal(tmp_path):
    baseline = tmp_path / 'baseline.json'
    market = tmp_path / 'market.json'
    risk = tmp_path / 'risk.json'
    factor = tmp_path / 'factor.json'
    strategy = tmp_path / 'strategy.json'
    raw = tmp_path / 'raw.json'
    runtime = tmp_path / 'runtime_summary.json'
    report = tmp_path / 'report.json'
    shadow_store = tmp_path / 'shadow.sqlite3'
    execution_journal = tmp_path / 'must-not-exist.sqlite3'
    baseline.write_text(json.dumps(baseline_result(), ensure_ascii=False), encoding='utf-8')
    raw.write_text(raw_output(), encoding='utf-8')
    values = summaries()
    market.write_text(json.dumps(values['market_summary'], ensure_ascii=False), encoding='utf-8')
    risk.write_text(json.dumps(values['risk_summary'], ensure_ascii=False), encoding='utf-8')
    factor.write_text(json.dumps(values['factor_summary'], ensure_ascii=False), encoding='utf-8')
    strategy.write_text(json.dumps(values['strategy_summary'], ensure_ascii=False), encoding='utf-8')

    export = subprocess.run(
        [
            sys.executable, '-m', 'trading_system.cli', '--journal', str(execution_journal),
            'shadow-runtime-summary',
            '--baseline-result', str(baseline),
            '--market-summary', str(market),
            '--risk-summary', str(risk),
            '--factor-summary', str(factor),
            '--strategy-summary', str(strategy),
            '--output', str(runtime),
        ],
        capture_output=True, text=True, encoding='utf-8', timeout=30,
    )
    cycle = subprocess.run(
        [
            sys.executable, '-m', 'trading_system.cli', '--journal', str(execution_journal),
            '--shadow-store', str(shadow_store),
            'shadow-cycle',
            '--runtime-summary', str(runtime),
            '--raw-output', str(raw),
            '--report-output', str(report),
        ],
        capture_output=True, text=True, encoding='utf-8', timeout=30,
    )

    assert export.returncode == 0, export.stdout + export.stderr
    assert cycle.returncode == 0, cycle.stdout + cycle.stderr
    assert json.loads(export.stdout)['data']['path'] == str(runtime)
    payload = json.loads(cycle.stdout)
    assert payload['data']['status'] == 'recorded'
    assert payload['data']['proposal_report']['summary']['total'] == 1
    assert runtime.exists()
    assert report.exists()
    assert shadow_store.exists()
    assert not execution_journal.exists()

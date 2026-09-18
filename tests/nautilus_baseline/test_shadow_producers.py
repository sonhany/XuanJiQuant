import json
import subprocess
import sys


def baseline_result():
    return {
        'schema': 'nautilus-baseline-result-v1',
        'mode': 'continuous_full_replay',
        'batch_id': 'producer-baseline',
        'account_id': 'demo',
        'revision': 4,
        'cash': '99054.99',
        'equity': '99993.99',
        'positions': {'600000': 100},
        'orders': [{'id': 'o1', 'quantity': 100}],
        'fills': [{'intent_id': 'o1', 'side': 'buy', 'quantity': 100, 'price': '9.40'}],
        'reconciliation': {'passed': True, 'checks': {'cash': True, 'positions': True}},
        'live_execution_authority': False,
    }


def runtime_summary(baseline):
    from trading_system.shadow_runtime_summary import build_shadow_runtime_summary

    return build_shadow_runtime_summary(
        baseline_result=baseline,
        market_summary={'snapshot_id': 'producer-snapshot', 'execution_ready': True},
        risk_summary={'level': 'low'},
        factor_summary={'version': 'factor-producer', 'top_codes': ['600000']},
        strategy_summary={'version': 'strategy-producer', 'target_weights': [{'code': '600000', 'weight': 0.08}]},
    )


def raw_ai_output(weight=0.06):
    return {
        'recommendation': {
            'stance': 'rebalance_candidate',
            'target_weights': [{'code': '600000', 'weight': weight}],
            'confidence': 0.7,
            'rationale': '受控生产端输出的只读影子建议。',
        }
    }


def test_baseline_export_atomically_publishes_only_reconciled_paper_baseline(tmp_path):
    from trading_system.baseline_export import publish_baseline_result

    source = tmp_path / 'source.json'
    output = tmp_path / 'baseline_result.json'
    metadata = tmp_path / 'baseline_result.meta.json'
    source.write_text(json.dumps(baseline_result(), ensure_ascii=False), encoding='utf-8')

    result = publish_baseline_result(source_path=source, output_path=output)

    published = json.loads(output.read_text(encoding='utf-8'))
    meta = json.loads(metadata.read_text(encoding='utf-8'))
    assert result['status'] == 'published'
    assert result['path'] == str(output)
    assert result['metadata_path'] == str(metadata)
    assert published['batch_id'] == 'producer-baseline'
    assert published['live_execution_authority'] is False
    assert meta['schema'] == 'xuanji-baseline-export-metadata-v1'
    assert meta['baseline_result_hash'] == result['baseline_result_hash']
    assert not (tmp_path / 'data' / 'paper' / 'f5_ledger.db').exists()


def test_baseline_export_rejects_unreconciled_or_live_baseline_without_overwriting(tmp_path):
    from trading_system.baseline_export import publish_baseline_result

    source = tmp_path / 'source.json'
    output = tmp_path / 'baseline_result.json'
    output.write_text('{"existing":true}', encoding='utf-8')
    bad = baseline_result()
    bad['live_execution_authority'] = True
    source.write_text(json.dumps(bad, ensure_ascii=False), encoding='utf-8')

    try:
        publish_baseline_result(source_path=source, output_path=output)
    except ValueError as exc:
        assert 'baseline_must_be_paper_only' in str(exc)
    else:
        raise AssertionError('expected baseline_must_be_paper_only')
    assert json.loads(output.read_text(encoding='utf-8')) == {'existing': True}


def test_shadow_ai_provider_publishes_only_contract_validated_raw_output(tmp_path):
    from trading_system.shadow_ai_provider import publish_shadow_ai_output

    runtime = tmp_path / 'runtime_summary.json'
    raw = tmp_path / 'raw_model_output.json'
    output = tmp_path / 'ai_raw_output.json'
    metadata = tmp_path / 'ai_raw_output.meta.json'
    runtime.write_text(json.dumps(runtime_summary(baseline_result()), ensure_ascii=False), encoding='utf-8')
    raw.write_text(json.dumps(raw_ai_output(), ensure_ascii=False), encoding='utf-8')

    result = publish_shadow_ai_output(runtime_summary_path=runtime, raw_output_path=raw, output_path=output)

    assert result['status'] == 'published'
    assert result['path'] == str(output)
    assert result['metadata_path'] == str(metadata)
    assert json.loads(output.read_text(encoding='utf-8'))['recommendation']['confidence'] == 0.7
    meta = json.loads(metadata.read_text(encoding='utf-8'))
    assert meta['schema'] == 'xuanji-shadow-ai-output-metadata-v1'
    assert meta['validation_status'] == 'validated'
    assert meta['execution_authority'] is False
    assert meta['can_trigger_order'] is False
    assert meta['live_execution_authority'] is False


def test_shadow_ai_provider_rejects_invalid_ai_output_without_overwriting(tmp_path):
    from trading_system.shadow_ai_provider import publish_shadow_ai_output

    runtime = tmp_path / 'runtime_summary.json'
    raw = tmp_path / 'raw_model_output.json'
    output = tmp_path / 'ai_raw_output.json'
    output.write_text('{"existing":true}', encoding='utf-8')
    runtime.write_text(json.dumps(runtime_summary(baseline_result()), ensure_ascii=False), encoding='utf-8')
    raw.write_text(json.dumps(raw_ai_output(weight=1.2), ensure_ascii=False), encoding='utf-8')

    try:
        publish_shadow_ai_output(runtime_summary_path=runtime, raw_output_path=raw, output_path=output)
    except ValueError as exc:
        assert 'shadow_ai_output_validation_failed' in str(exc)
    else:
        raise AssertionError('expected shadow_ai_output_validation_failed')
    assert json.loads(output.read_text(encoding='utf-8')) == {'existing': True}


def test_controlled_producer_cli_commands_do_not_touch_execution_journal(tmp_path):
    source = tmp_path / 'source.json'
    baseline = tmp_path / 'baseline_result.json'
    runtime = tmp_path / 'runtime_summary.json'
    raw = tmp_path / 'raw_model_output.json'
    ai_output = tmp_path / 'ai_raw_output.json'
    execution_journal = tmp_path / 'must-not-exist.sqlite3'
    source.write_text(json.dumps(baseline_result(), ensure_ascii=False), encoding='utf-8')
    raw.write_text(json.dumps(raw_ai_output(), ensure_ascii=False), encoding='utf-8')

    baseline_cmd = subprocess.run(
        [
            sys.executable, '-m', 'trading_system.cli', '--journal', str(execution_journal),
            'baseline-export', '--input', str(source), '--output', str(baseline),
        ],
        capture_output=True, text=True, encoding='utf-8', timeout=30,
    )
    runtime_cmd = subprocess.run(
        [
            sys.executable, '-m', 'trading_system.cli', 'shadow-runtime-summary',
            '--baseline-result', str(baseline), '--output', str(runtime),
        ],
        capture_output=True, text=True, encoding='utf-8', timeout=30,
    )
    ai_cmd = subprocess.run(
        [
            sys.executable, '-m', 'trading_system.cli', '--journal', str(execution_journal),
            'shadow-ai-output', '--runtime-summary', str(runtime), '--raw-output', str(raw), '--output', str(ai_output),
        ],
        capture_output=True, text=True, encoding='utf-8', timeout=30,
    )

    assert baseline_cmd.returncode == 0, baseline_cmd.stdout + baseline_cmd.stderr
    assert runtime_cmd.returncode == 0, runtime_cmd.stdout + runtime_cmd.stderr
    assert ai_cmd.returncode == 0, ai_cmd.stdout + ai_cmd.stderr
    assert json.loads(baseline_cmd.stdout)['data']['status'] == 'published'
    assert json.loads(ai_cmd.stdout)['data']['status'] == 'published'
    assert baseline.exists()
    assert ai_output.exists()
    assert not execution_journal.exists()

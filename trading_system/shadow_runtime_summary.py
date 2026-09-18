"""Controlled runtime summary bundle for read-only shadow cycles."""
from datetime import datetime
import json
from pathlib import Path

from .contracts import digest
from .shadow_context import validate_shadow_decision_context
from .shadow_context_builder import build_runtime_shadow_context
from .shadow_decision import _baseline_comparison


SCHEMA = 'xuanji-shadow-runtime-summary-v1'


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _now_iso():
    return datetime.now().astimezone().isoformat()


def _copy(value):
    return json.loads(json.dumps(value if value is not None else {}, ensure_ascii=False, allow_nan=False))


def validate_shadow_runtime_summary(raw):
    summary = _copy(raw)
    if not isinstance(summary, dict):
        raise ValueError('runtime_summary_invalid')
    if summary.get('schema') != SCHEMA or summary.get('mode') != 'shadow_runtime_summary':
        raise ValueError('runtime_summary_schema_invalid')
    if summary.get('execution_authority') is not False or summary.get('live_execution_authority') is not False:
        raise ValueError('runtime_summary_authority_required')
    baseline = summary.get('baseline_result')
    comparison = _baseline_comparison(baseline)
    if comparison['baseline_result_hash'] != summary.get('baseline_result_hash'):
        raise ValueError('runtime_summary_baseline_hash_mismatch')
    hashes = summary.get('source_hashes')
    if not isinstance(hashes, dict):
        raise ValueError('runtime_summary_hashes_invalid')
    expected = {
        'baseline_result': digest(summary.get('baseline_result')),
        'market_summary': digest(summary.get('market_summary') or {}),
        'risk_summary': digest(summary.get('risk_summary') or {}),
        'factor_summary': digest(summary.get('factor_summary') or {}),
        'strategy_summary': digest(summary.get('strategy_summary') or {}),
        'history_summary': digest(summary.get('history_summary') or {}),
    }
    if hashes != expected:
        raise ValueError('runtime_summary_source_hash_mismatch')
    return summary


def build_shadow_runtime_summary(*, baseline_result, market_summary=None, risk_summary=None,
                                 factor_summary=None, strategy_summary=None,
                                 history_summary=None, generated_at=None):
    comparison = _baseline_comparison(baseline_result)
    summary = {
        'schema': SCHEMA,
        'mode': 'shadow_runtime_summary',
        'generated_at': generated_at.isoformat() if isinstance(generated_at, datetime) else (generated_at or _now_iso()),
        'baseline_result_hash': comparison['baseline_result_hash'],
        'baseline_result': _copy(baseline_result),
        'market_summary': _copy(market_summary),
        'risk_summary': _copy(risk_summary),
        'factor_summary': _copy(factor_summary),
        'strategy_summary': _copy(strategy_summary),
        'history_summary': _copy(history_summary),
        'execution_authority': False,
        'can_trigger_order': False,
        'live_execution_authority': False,
    }
    summary['source_hashes'] = {
        'baseline_result': digest(summary['baseline_result']),
        'market_summary': digest(summary['market_summary']),
        'risk_summary': digest(summary['risk_summary']),
        'factor_summary': digest(summary['factor_summary']),
        'strategy_summary': digest(summary['strategy_summary']),
        'history_summary': digest(summary['history_summary']),
    }
    return validate_shadow_runtime_summary(summary)


def build_context_from_runtime_summary(runtime_summary):
    summary = validate_shadow_runtime_summary(runtime_summary)
    context = build_runtime_shadow_context(
        baseline_result=summary['baseline_result'],
        market_summary=summary['market_summary'],
        risk_summary=summary['risk_summary'],
        factor_summary=summary['factor_summary'],
        strategy_summary=summary['strategy_summary'],
        history_summary=summary['history_summary'],
        generated_at=summary['generated_at'],
    )
    return validate_shadow_decision_context(context)

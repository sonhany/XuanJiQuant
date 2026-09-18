"""Assemble ShadowDecisionContext from controlled runtime summaries."""
from datetime import datetime
import json
from pathlib import Path

from .contracts import digest, money
from .shadow_context import build_shadow_decision_context
from .shadow_decision import _baseline_comparison


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _source_hash(value):
    return digest(value if value is not None else {})


def _codes(values):
    if not isinstance(values, list):
        return []
    result = []
    for value in values:
        code = value.get('code') if isinstance(value, dict) else value
        if isinstance(code, str) and len(code) == 6 and code.isdigit() and code not in result:
            result.append(code)
    return result


def summarize_account(baseline_result):
    comparison = _baseline_comparison(baseline_result)
    positions = baseline_result.get('positions') or {}
    if not isinstance(positions, dict):
        raise ValueError('baseline_positions_invalid')
    return {
        'baseline_result_hash': comparison['baseline_result_hash'],
        'account_id': str(baseline_result.get('account_id') or ''),
        'revision': baseline_result.get('revision'),
        'cash': money(baseline_result.get('cash', '0')),
        'equity': comparison['baseline_equity'],
        'position_count': len(positions),
        'position_codes': comparison['baseline_position_codes'],
        'valuation_timestamp': str(baseline_result.get('valuation_timestamp') or ''),
    }


def summarize_market(summary):
    raw = summary or {}
    if not isinstance(raw, dict):
        raise ValueError('market_summary_invalid')
    snapshot = raw.get('raw_snapshot') if isinstance(raw.get('raw_snapshot'), dict) else raw
    return {
        'snapshot_id': str(raw.get('snapshot_id') or snapshot.get('snapshot_id') or ''),
        'received_at': str(raw.get('received_at') or snapshot.get('received_at') or ''),
        'market_phase': str(raw.get('market_phase') or snapshot.get('market_phase') or ''),
        'execution_ready': bool(raw.get('execution_ready')) if 'execution_ready' in raw else None,
        'coverage': raw.get('coverage') if isinstance(raw.get('coverage'), dict) else {},
        'source_hash': _source_hash(raw),
    }


def summarize_risk(summary):
    raw = summary or {}
    if not isinstance(raw, dict):
        raise ValueError('risk_summary_invalid')
    return {
        'level': str(raw.get('level') or raw.get('risk_level') or ''),
        'summary': str(raw.get('summary') or raw.get('message') or ''),
        'computed_at': str(raw.get('computed_at') or raw.get('updated_at') or ''),
        'source_hash': _source_hash(raw),
    }


def summarize_factor(summary):
    raw = summary or {}
    if not isinstance(raw, dict):
        raise ValueError('factor_summary_invalid')
    top_codes = _codes(raw.get('top_codes') or raw.get('codes') or raw.get('top') or [])
    return {
        'version': str(raw.get('version') or raw.get('factor_version') or ''),
        'evaluated_at': str(raw.get('evaluated_at') or raw.get('updated_at') or ''),
        'factor_count': raw.get('factor_count'),
        'top_codes': top_codes,
        'source_hash': _source_hash(raw),
    }


def summarize_strategy(summary):
    raw = summary or {}
    if not isinstance(raw, dict):
        raise ValueError('strategy_summary_invalid')
    return {
        'version': str(raw.get('version') or raw.get('strategy_version') or ''),
        'status': str(raw.get('status') or ''),
        'target_weights': raw.get('target_weights') if isinstance(raw.get('target_weights'), list) else [],
        'source_hash': _source_hash(raw),
    }


def summarize_history(baseline_result, summary=None):
    raw = summary or {}
    if raw and not isinstance(raw, dict):
        raise ValueError('history_summary_invalid')
    baseline_orders = baseline_result.get('orders') if isinstance(baseline_result.get('orders'), list) else []
    baseline_fills = baseline_result.get('fills') if isinstance(baseline_result.get('fills'), list) else []
    return {
        'order_count': int(raw.get('order_count', len(baseline_orders))) if isinstance(raw, dict) else len(baseline_orders),
        'fill_count': int(raw.get('fill_count', len(baseline_fills))) if isinstance(raw, dict) else len(baseline_fills),
        'traded_codes': _codes(raw.get('traded_codes', [])) if isinstance(raw, dict) else [],
        'source_hash': _source_hash({'baseline_history': {'order_count': len(baseline_orders), 'fill_count': len(baseline_fills)}, 'external': raw}),
    }


def build_runtime_shadow_context(*, baseline_result, market_summary=None, risk_summary=None,
                                 factor_summary=None, strategy_summary=None,
                                 history_summary=None, generated_at=None):
    return build_shadow_decision_context(
        baseline_result=baseline_result,
        account=summarize_account(baseline_result),
        market=summarize_market(market_summary),
        risk=summarize_risk(risk_summary),
        factor=summarize_factor(factor_summary),
        strategy=summarize_strategy(strategy_summary),
        history=summarize_history(baseline_result, history_summary),
        generated_at=generated_at or datetime.now().astimezone(),
    )

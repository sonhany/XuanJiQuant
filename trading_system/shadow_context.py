"""Fixed, read-only input contract for AI shadow decisions."""
from copy import deepcopy
from datetime import datetime
import json
import math
import re

from .contracts import digest, instant
from .shadow_decision import _baseline_comparison, _assert_no_execution_fields


SCHEMA = 'xuanji-shadow-decision-context-v1'
MODE = 'shadow_context'
SECTIONS = ('market', 'risk', 'factor', 'strategy', 'history')


def _now_iso():
    return datetime.now().astimezone().isoformat()


def _assert_json_safe(value):
    json.dumps(value, ensure_ascii=False, allow_nan=False)
    if isinstance(value, dict):
        for item in value.values():
            _assert_json_safe(item)
    elif isinstance(value, list):
        for item in value:
            _assert_json_safe(item)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError('context_value_invalid')


def _section(raw):
    value = deepcopy(raw or {})
    if not isinstance(value, dict):
        raise ValueError('context_section_invalid')
    _assert_no_execution_fields(value)
    _assert_json_safe(value)
    return value


def _validate_weights(weights):
    if weights is None:
        return []
    if not isinstance(weights, list) or len(weights) > 100:
        raise ValueError('target_weights_invalid')
    cleaned = []
    seen = set()
    total = 0.0
    for item in weights:
        if not isinstance(item, dict):
            raise ValueError('target_weight_invalid')
        code = item.get('code')
        weight = item.get('weight')
        if not isinstance(code, str) or not re.fullmatch(r'\d{6}', code):
            raise ValueError('code_invalid')
        if code in seen:
            raise ValueError('duplicate_code')
        if type(weight) not in (int, float) or not math.isfinite(weight) or not 0 <= float(weight) <= 1:
            raise ValueError('weight_invalid')
        seen.add(code)
        total += float(weight)
        cleaned.append({'code': code, 'weight': float(weight)})
    if total > 1.000000001:
        raise ValueError('weight_sum_invalid')
    return cleaned


def _baseline_binding(baseline_result):
    comparison = _baseline_comparison(baseline_result)
    return {
        'baseline_result_hash': comparison['baseline_result_hash'],
        'baseline_mode': comparison['baseline_mode'],
        'baseline_revision': comparison['baseline_revision'],
        'baseline_equity': comparison['baseline_equity'],
        'position_codes': comparison['baseline_position_codes'],
    }


def _normalize_context(raw):
    context = deepcopy(raw)
    if not isinstance(context, dict):
        raise ValueError('context_invalid')
    if context.get('schema') != SCHEMA or context.get('mode') != MODE:
        raise ValueError('context_schema_invalid')
    if context.get('read_only') is not True:
        raise ValueError('context_read_only_required')
    for field in ('execution_authority', 'can_trigger_order', 'live_execution_authority'):
        if context.get(field) is not False:
            raise ValueError('context_authority_required')
    generated_at = context.get('generated_at')
    if not isinstance(generated_at, str):
        raise ValueError('generated_at_invalid')
    instant(generated_at)
    binding = context.get('baseline_binding')
    if not isinstance(binding, dict):
        raise ValueError('baseline_binding_invalid')
    if not re.fullmatch(r'[0-9a-f]{64}', str(binding.get('baseline_result_hash', ''))):
        raise ValueError('baseline_hash_invalid')
    codes = binding.get('position_codes', [])
    if not isinstance(codes, list) or any(not isinstance(code, str) or not re.fullmatch(r'\d{6}', code) for code in codes):
        raise ValueError('position_codes_invalid')
    normalized = {
        'schema': SCHEMA,
        'mode': MODE,
        'context_id': str(context.get('context_id') or ''),
        'generated_at': generated_at,
        'baseline_binding': {
            'baseline_result_hash': binding['baseline_result_hash'],
            'baseline_mode': str(binding.get('baseline_mode') or ''),
            'baseline_revision': binding.get('baseline_revision'),
            'baseline_equity': str(binding.get('baseline_equity') or '0.00'),
            'position_codes': sorted(codes),
        },
        'account': _section(context.get('account')),
        'market': _section(context.get('market')),
        'risk': _section(context.get('risk')),
        'factor': _section(context.get('factor')),
        'strategy': _section(context.get('strategy')),
        'history': _section(context.get('history')),
        'read_only': True,
        'execution_authority': False,
        'can_trigger_order': False,
        'live_execution_authority': False,
    }
    if 'target_weights' in normalized['strategy']:
        normalized['strategy']['target_weights'] = _validate_weights(normalized['strategy']['target_weights'])
    expected = _context_id(normalized, include_existing=False)
    if normalized['context_id'] != expected:
        raise ValueError('context_id_mismatch')
    return normalized


def _context_id(context, include_existing=True):
    payload = deepcopy(context)
    if not include_existing:
        payload.pop('context_id', None)
    return 'ctx_' + digest(payload)[:32]


def build_shadow_decision_context(*, baseline_result, account=None, market=None, risk=None,
                                  factor=None, strategy=None, history=None,
                                  generated_at=None):
    context = {
        'schema': SCHEMA,
        'mode': MODE,
        'context_id': 'pending',
        'generated_at': generated_at.isoformat() if isinstance(generated_at, datetime) else (generated_at or _now_iso()),
        'baseline_binding': _baseline_binding(baseline_result),
        'account': _section(account),
        'market': _section(market),
        'risk': _section(risk),
        'factor': _section(factor),
        'strategy': _section(strategy),
        'history': _section(history),
        'read_only': True,
        'execution_authority': False,
        'can_trigger_order': False,
        'live_execution_authority': False,
    }
    if 'target_weights' in context['strategy']:
        context['strategy']['target_weights'] = _validate_weights(context['strategy']['target_weights'])
    context['context_id'] = _context_id(context, include_existing=False)
    return validate_shadow_decision_context(context)


def validate_shadow_decision_context(raw):
    return _normalize_context(raw)

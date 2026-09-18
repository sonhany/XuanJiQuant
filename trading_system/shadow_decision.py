"""Read-only AI shadow decision contract.

This module is deliberately outside F5 and outside the retired Agent control
plane.  It converts an AI or local shadow-model opinion into a verifiable
DecisionProposal that can be compared with a deterministic paper baseline, but
cannot request orders or change execution policy.
"""
from copy import deepcopy
from datetime import datetime
import math
import re

from .contracts import digest, instant, money


SCHEMA = 'xuanji-decision-proposal-v1'
MODE = 'shadow_only'
PRODUCER_KINDS = {'ai_shadow', 'local_shadow_model'}
STANCES = {'hold', 'rebalance_candidate', 'reduce_risk', 'no_action'}
FORBIDDEN_EXECUTION_KEYS = {
    'order', 'orders', 'order_type', 'side', 'quantity', 'qty', 'shares',
    'price', 'limit_price', 'market_order', 'broker', 'broker_account',
    'account_write', 'trade_allowed', 'execution_request', 'executable',
    'place_order', 'submit_order', 'cancel_order',
    'fill', 'fills', 'trade', 'trades', 'filled_quantity', 'remaining_quantity',
}
AUTHORITY_FIELDS = (
    'execution_authority',
    'can_trigger_order',
    'can_change_trade_policy',
    'live_execution_authority',
)


def _now_iso():
    return datetime.now().astimezone().isoformat()


def _is_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _sanitize(value):
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in FORBIDDEN_EXECUTION_KEYS or normalized.startswith('agent_'):
                continue
            cleaned[key] = _sanitize(item)
        return cleaned
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _assert_no_execution_fields(value):
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in FORBIDDEN_EXECUTION_KEYS or normalized.startswith('agent_'):
                raise ValueError('execution_field_forbidden')
            _assert_no_execution_fields(item)
        return
    if isinstance(value, list):
        for item in value:
            _assert_no_execution_fields(item)
        return
    if isinstance(value, str) and 'agent_' in value.lower():
        raise ValueError('execution_field_forbidden')


def _validated_text(value, reason, maximum=512):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(reason)
    return value.strip()


def _baseline_comparison(baseline_result):
    baseline = deepcopy(baseline_result)
    if not isinstance(baseline, dict):
        raise ValueError('baseline_invalid')
    if baseline.get('live_execution_authority') is not False:
        raise ValueError('baseline_must_be_paper_only')
    reconciliation = baseline.get('reconciliation')
    if not isinstance(reconciliation, dict) or reconciliation.get('passed') is not True:
        raise ValueError('baseline_not_reconciled')
    positions = baseline.get('positions') or {}
    if not isinstance(positions, dict):
        raise ValueError('baseline_positions_invalid')
    return {
        'baseline_result_hash': digest(baseline),
        'baseline_mode': str(baseline.get('mode') or ''),
        'baseline_revision': baseline.get('revision'),
        'baseline_equity': money(baseline.get('equity', '0')),
        'baseline_position_codes': sorted(str(code) for code in positions),
        'comparable': True,
    }


def _validate_producer(producer):
    if not isinstance(producer, dict):
        raise ValueError('producer_invalid')
    if producer.get('kind') not in PRODUCER_KINDS:
        raise ValueError('producer_kind_invalid')
    return {
        'kind': producer['kind'],
        'model_id': _validated_text(producer.get('model_id'), 'model_id_invalid', 128),
        'prompt_version': _validated_text(producer.get('prompt_version'), 'prompt_version_invalid', 128),
    }


def _validate_evidence(evidence):
    if not isinstance(evidence, dict):
        raise ValueError('evidence_invalid')
    result = _sanitize(deepcopy(evidence))
    _assert_no_execution_fields(result)
    if not result:
        raise ValueError('evidence_required')
    if 'signal_hash' in result and not re.fullmatch(r'[0-9a-f]{64}', str(result['signal_hash'])):
        raise ValueError('signal_hash_invalid')
    if 'account_revision' in result and type(result['account_revision']) is not int:
        raise ValueError('account_revision_invalid')
    return result


def _validate_recommendation(recommendation):
    if not isinstance(recommendation, dict):
        raise ValueError('recommendation_invalid')
    result = _sanitize(deepcopy(recommendation))
    _assert_no_execution_fields(result)
    if result.get('stance') not in STANCES:
        raise ValueError('stance_invalid')
    weights = result.get('target_weights', [])
    if not isinstance(weights, list) or len(weights) > 100:
        raise ValueError('target_weights_invalid')
    total = 0.0
    cleaned_weights = []
    seen = set()
    for item in weights:
        if not isinstance(item, dict):
            raise ValueError('target_weight_invalid')
        code = item.get('code')
        weight = item.get('weight')
        if not isinstance(code, str) or not re.fullmatch(r'\d{6}', code):
            raise ValueError('code_invalid')
        if code in seen:
            raise ValueError('duplicate_code')
        if not _is_number(weight) or not 0 <= float(weight) <= 1:
            raise ValueError('weight_invalid')
        seen.add(code)
        total += float(weight)
        cleaned_weights.append({'code': code, 'weight': float(weight)})
    if total > 1.000000001:
        raise ValueError('weight_sum_invalid')
    confidence = result.get('confidence')
    if not _is_number(confidence) or not 0 <= float(confidence) <= 1:
        raise ValueError('confidence_invalid')
    return {
        'stance': result['stance'],
        'target_weights': cleaned_weights,
        'confidence': float(confidence),
        'rationale': _validated_text(result.get('rationale'), 'rationale_invalid', 2000),
    }


def validate_decision_proposal(raw):
    proposal = deepcopy(raw)
    if not isinstance(proposal, dict):
        raise ValueError('proposal_invalid')
    _assert_no_execution_fields(proposal)
    if proposal.get('schema') != SCHEMA or proposal.get('mode') != MODE:
        raise ValueError('proposal_schema_invalid')
    for field in AUTHORITY_FIELDS:
        if proposal.get(field) is not False:
            raise ValueError('shadow_authority_required')
    generated_at = proposal.get('generated_at')
    if not isinstance(generated_at, str):
        raise ValueError('generated_at_invalid')
    instant(generated_at)
    producer = _validate_producer(proposal.get('producer'))
    evidence = _validate_evidence(proposal.get('evidence'))
    recommendation = _validate_recommendation(proposal.get('recommendation'))
    comparison = proposal.get('baseline_comparison')
    if not isinstance(comparison, dict):
        raise ValueError('baseline_comparison_invalid')
    if not re.fullmatch(r'[0-9a-f]{64}', str(comparison.get('baseline_result_hash', ''))):
        raise ValueError('baseline_hash_invalid')
    if comparison.get('comparable') is not True:
        raise ValueError('baseline_not_comparable')
    normalized = {
        'schema': SCHEMA,
        'mode': MODE,
        'proposal_id': _validated_text(proposal.get('proposal_id'), 'proposal_id_invalid', 96),
        'generated_at': generated_at,
        'producer': producer,
        'evidence': evidence,
        'recommendation': recommendation,
        'baseline_comparison': {
            'baseline_result_hash': comparison['baseline_result_hash'],
            'baseline_mode': str(comparison.get('baseline_mode') or ''),
            'baseline_revision': comparison.get('baseline_revision'),
            'baseline_equity': money(comparison.get('baseline_equity', '0')),
            'baseline_position_codes': sorted(str(code) for code in comparison.get('baseline_position_codes', [])),
            'comparable': True,
        },
        'execution_authority': False,
        'can_trigger_order': False,
        'can_change_trade_policy': False,
        'live_execution_authority': False,
        'violations': [],
    }
    expected = _proposal_id(normalized, include_existing=False)
    if normalized['proposal_id'] != expected:
        raise ValueError('proposal_id_mismatch')
    return normalized


def _proposal_id(proposal, include_existing=True):
    payload = deepcopy(proposal)
    if not include_existing:
        payload.pop('proposal_id', None)
    return 'shadow_' + digest(payload)[:32]


def build_decision_proposal(*, producer, evidence, recommendation, baseline_result, generated_at=None):
    proposal = {
        'schema': SCHEMA,
        'mode': MODE,
        'proposal_id': 'pending',
        'generated_at': generated_at.isoformat() if isinstance(generated_at, datetime) else (generated_at or _now_iso()),
        'producer': _validate_producer(producer),
        'evidence': _validate_evidence(evidence),
        'recommendation': _validate_recommendation(recommendation),
        'baseline_comparison': _baseline_comparison(baseline_result),
        'execution_authority': False,
        'can_trigger_order': False,
        'can_change_trade_policy': False,
        'live_execution_authority': False,
        'violations': [],
    }
    proposal['proposal_id'] = _proposal_id(proposal, include_existing=False)
    return validate_decision_proposal(proposal)


def build_decision_proposal_from_baseline_binding(*, producer, evidence, recommendation,
                                                  baseline_binding, generated_at=None):
    if not isinstance(baseline_binding, dict):
        raise ValueError('baseline_binding_invalid')
    comparison = {
        'baseline_result_hash': baseline_binding.get('baseline_result_hash'),
        'baseline_mode': str(baseline_binding.get('baseline_mode') or ''),
        'baseline_revision': baseline_binding.get('baseline_revision'),
        'baseline_equity': baseline_binding.get('baseline_equity', '0'),
        'baseline_position_codes': list(baseline_binding.get('position_codes', [])),
        'comparable': True,
    }
    proposal = {
        'schema': SCHEMA,
        'mode': MODE,
        'proposal_id': 'pending',
        'generated_at': generated_at.isoformat() if isinstance(generated_at, datetime) else (generated_at or _now_iso()),
        'producer': _validate_producer(producer),
        'evidence': _validate_evidence(evidence),
        'recommendation': _validate_recommendation(recommendation),
        'baseline_comparison': comparison,
        'execution_authority': False,
        'can_trigger_order': False,
        'can_change_trade_policy': False,
        'live_execution_authority': False,
        'violations': [],
    }
    proposal['proposal_id'] = _proposal_id(proposal, include_existing=False)
    return validate_decision_proposal(proposal)

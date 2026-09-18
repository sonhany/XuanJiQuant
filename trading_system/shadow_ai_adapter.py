"""External AI adapter for read-only shadow decisions.

The adapter is intentionally narrow: it receives a validated
ShadowDecisionContext, obtains raw model text from a supplied client or file,
then builds a DecisionProposal.  Every success or validation failure can be
audited without touching execution journals or F5.
"""
import json

from .contracts import digest
from .shadow_context import validate_shadow_decision_context
from .shadow_decision import (
    _sanitize,
    build_decision_proposal_from_baseline_binding,
)


DEFAULT_AI_PRODUCER = {
    'kind': 'ai_shadow',
    'model_id': 'external-shadow-ai',
    'prompt_version': 'shadow-context-v1',
}


def build_shadow_ai_request(context):
    validated = validate_shadow_decision_context(context)
    return {
        'schema': 'xuanji-shadow-ai-request-v1',
        'mode': 'shadow_decision',
        'instruction': (
            '只基于给定ShadowDecisionContext输出JSON recommendation。'
            '禁止输出订单、方向、数量、价格、券商、执行、调度或agent字段。'
        ),
        'expected_output': {
            'recommendation': {
                'stance': 'hold|rebalance_candidate|reduce_risk|no_action',
                'target_weights': [{'code': '600000', 'weight': 0.0}],
                'confidence': 0.0,
                'rationale': '中文只读研究理由',
            }
        },
        'context': validated,
        'execution_authority': False,
        'can_trigger_order': False,
        'live_execution_authority': False,
    }


def _raw_text(value):
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _parse_output(raw_output):
    parsed = json.loads(_raw_text(raw_output))
    if not isinstance(parsed, dict):
        raise ValueError('ai_output_invalid')
    recommendation = parsed.get('recommendation', parsed)
    if not isinstance(recommendation, dict):
        raise ValueError('ai_recommendation_invalid')
    return recommendation


def _audit_payload(*, context_hash, producer, status, raw_output, sanitized_output,
                   validation_error=None, proposal_id=None):
    return {
        'context_hash': context_hash,
        'producer_kind': producer['kind'],
        'model_id': producer['model_id'],
        'status': status,
        'raw_output': _raw_text(raw_output),
        'sanitized_output': json.dumps(sanitized_output, ensure_ascii=False, separators=(',', ':')),
        'validation_error': validation_error,
        'proposal_id': proposal_id,
    }


def run_shadow_ai(context, *, model_client=None, raw_output=None, journal=None,
                  producer=None, generated_at=None):
    validated = validate_shadow_decision_context(context)
    producer = producer or DEFAULT_AI_PRODUCER
    request = build_shadow_ai_request(validated)
    context_hash = digest(validated)
    if raw_output is None:
        if not callable(model_client):
            raise ValueError('ai_model_output_required')
        try:
            raw_output = model_client(request)
        except Exception as exc:
            audit = _audit_payload(
                context_hash=context_hash,
                producer=producer,
                status='model_failed',
                raw_output='',
                sanitized_output={},
                validation_error=str(exc),
            )
            record_status = journal.record_ai_run(audit)['status'] if journal is not None else None
            return {
                'schema': 'xuanji-shadow-ai-run-result-v1',
                'mode': 'shadow_decision',
                'status': 'model_failed',
                'proposal': None,
                'validation_error': str(exc),
                'audit_status': record_status,
                'execution_authority': False,
                'can_trigger_order': False,
                'live_execution_authority': False,
            }
    try:
        recommendation = _parse_output(raw_output)
        sanitized_recommendation = _sanitize(recommendation)
        proposal = build_decision_proposal_from_baseline_binding(
            producer=producer,
            evidence={
                'context_id': validated['context_id'],
                'context_hash': context_hash,
                'baseline_result_hash': validated['baseline_binding']['baseline_result_hash'],
                'model_output_hash': digest({'raw_output': _raw_text(raw_output)}),
                **({'market_snapshot_id': str(validated['market']['snapshot_id'])} if validated['market'].get('snapshot_id') else {}),
            },
            recommendation=sanitized_recommendation,
            baseline_binding=validated['baseline_binding'],
            generated_at=generated_at,
        )
        record_status = journal.record(proposal)['status'] if journal is not None else None
        audit = _audit_payload(
            context_hash=context_hash,
            producer=producer,
            status='recorded',
            raw_output=raw_output,
            sanitized_output=proposal['recommendation'],
            proposal_id=proposal['proposal_id'],
        )
        audit_status = journal.record_ai_run(audit)['status'] if journal is not None else None
        return {
            'schema': 'xuanji-shadow-ai-run-result-v1',
            'mode': 'shadow_decision',
            'status': record_status or 'validated',
            'proposal': proposal,
            'validation_error': None,
            'audit_status': audit_status,
            'execution_authority': False,
            'can_trigger_order': False,
            'live_execution_authority': False,
        }
    except Exception as exc:
        sanitized = {}
        try:
            sanitized = _sanitize(_parse_output(raw_output))
        except Exception:
            sanitized = {}
        audit = _audit_payload(
            context_hash=context_hash,
            producer=producer,
            status='validation_failed',
            raw_output=raw_output,
            sanitized_output=sanitized,
            validation_error=str(exc),
        )
        audit_status = journal.record_ai_run(audit)['status'] if journal is not None else None
        return {
            'schema': 'xuanji-shadow-ai-run-result-v1',
            'mode': 'shadow_decision',
            'status': 'validation_failed',
            'proposal': None,
            'validation_error': str(exc),
            'audit_status': audit_status,
            'execution_authority': False,
            'can_trigger_order': False,
            'live_execution_authority': False,
        }

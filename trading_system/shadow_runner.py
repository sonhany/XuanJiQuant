"""Read-only shadow runner from fixed context to DecisionProposal."""
from datetime import datetime

from .contracts import digest
from .shadow_context import validate_shadow_decision_context
from .shadow_decision import build_decision_proposal_from_baseline_binding


DEFAULT_PRODUCER = {
    'kind': 'local_shadow_model',
    'model_id': 'xuanji-shadow-context-baseline-v1',
    'prompt_version': 'deterministic-shadow-v1',
}


def _risk_level(context):
    return str((context.get('risk') or {}).get('level') or '').lower()


def _strategy_weights(context):
    weights = (context.get('strategy') or {}).get('target_weights') or []
    return [{'code': item['code'], 'weight': float(item['weight'])} for item in weights]


def _recommendation(context):
    level = _risk_level(context)
    if level in ('high', 'critical', 'severe'):
        return {
            'stance': 'reduce_risk',
            'target_weights': [],
            'confidence': 0.55,
            'rationale': '影子上下文显示风险偏高；只读建议降低暴露，不产生订单。',
        }
    weights = _strategy_weights(context)
    if weights:
        return {
            'stance': 'rebalance_candidate',
            'target_weights': weights,
            'confidence': 0.6,
            'rationale': '影子上下文包含策略目标权重；仅生成研究对照提案，不产生订单。',
        }
    return {
        'stance': 'hold',
        'target_weights': [],
        'confidence': 0.5,
        'rationale': '影子上下文没有可比较的策略权重；只读建议保持观察。',
    }


def _evidence(context):
    market = context.get('market') or {}
    strategy = context.get('strategy') or {}
    factor = context.get('factor') or {}
    result = {
        'context_id': context['context_id'],
        'context_hash': digest(context),
        'baseline_result_hash': context['baseline_binding']['baseline_result_hash'],
    }
    if market.get('snapshot_id'):
        result['market_snapshot_id'] = str(market['snapshot_id'])
    if strategy.get('version'):
        result['strategy_version'] = str(strategy['version'])
    if factor.get('version'):
        result['factor_version'] = str(factor['version'])
    return result


def run_shadow_decision(context, *, journal=None, producer=None, generated_at=None):
    validated = validate_shadow_decision_context(context)
    proposal = build_decision_proposal_from_baseline_binding(
        producer=producer or DEFAULT_PRODUCER,
        evidence=_evidence(validated),
        recommendation=_recommendation(validated),
        baseline_binding=validated['baseline_binding'],
        generated_at=generated_at or datetime.now().astimezone().isoformat(),
    )
    record_status = None
    if journal is not None:
        record_status = journal.record(proposal)['status']
    return {
        'schema': 'xuanji-shadow-run-result-v1',
        'mode': 'shadow_decision',
        'context_id': validated['context_id'],
        'context_hash': digest(validated),
        'proposal': proposal,
        'record_status': record_status,
        'execution_authority': False,
        'can_trigger_order': False,
        'live_execution_authority': False,
    }

"""One-shot read-only shadow research cycle."""
import json
from pathlib import Path

from .shadow_ai_adapter import run_shadow_ai
from .shadow_context_builder import build_runtime_shadow_context
from .shadow_runtime_summary import build_context_from_runtime_summary


def _write_new_json(path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return str(target)


def run_shadow_cycle(*, baseline_result=None, raw_output, journal, runtime_summary=None, market_summary=None,
                     risk_summary=None, factor_summary=None, strategy_summary=None,
                     history_summary=None, context_output=None, report_output=None,
                     generated_at=None):
    if runtime_summary is not None:
        context = build_context_from_runtime_summary(runtime_summary)
    else:
        context = build_runtime_shadow_context(
            baseline_result=baseline_result,
            market_summary=market_summary,
            risk_summary=risk_summary,
            factor_summary=factor_summary,
            strategy_summary=strategy_summary,
            history_summary=history_summary,
            generated_at=generated_at,
        )
    ai_result = run_shadow_ai(
        context,
        raw_output=raw_output,
        journal=journal,
        generated_at=generated_at,
    )
    proposal_report = journal.report()
    ai_audit_report = journal.ai_audit_report()
    artifact_paths = {}
    if context_output is not None:
        artifact_paths['context'] = _write_new_json(context_output, context)
    report_payload = {
        'schema': 'xuanji-shadow-cycle-report-v1',
        'mode': 'shadow_decision',
        'context_id': context['context_id'],
        'ai_status': ai_result['status'],
        'proposal_report': proposal_report,
        'ai_audit_report': ai_audit_report,
        'execution_authority': False,
        'can_trigger_order': False,
        'live_execution_authority': False,
    }
    if report_output is not None:
        artifact_paths['report'] = _write_new_json(report_output, report_payload)
    return {
        'schema': 'xuanji-shadow-cycle-result-v1',
        'mode': 'shadow_decision',
        'status': ai_result['status'],
        'context': context,
        'ai_result': ai_result,
        'proposal_report': proposal_report,
        'ai_audit_report': ai_audit_report,
        'artifact_paths': artifact_paths,
        'execution_authority': False,
        'can_trigger_order': False,
        'live_execution_authority': False,
    }

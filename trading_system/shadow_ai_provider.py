"""Controlled producer for shadow ai_raw_output.json.

The provider validates raw model output against the same read-only shadow
contract used by shadow-cycle before publishing it for the daily pipeline.
"""
from datetime import datetime
import json
from pathlib import Path

from .contracts import digest
from .shadow_ai_adapter import run_shadow_ai
from .shadow_runtime_summary import build_context_from_runtime_summary, load_json


def _metadata_path(output_path):
    target = Path(output_path)
    return target.with_name(target.stem + '.meta' + target.suffix)


def _write_json_atomic(path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(target)


def _load_raw(path):
    text = Path(path).read_text(encoding='utf-8')
    return json.loads(text)


def publish_shadow_ai_output(*, runtime_summary_path, raw_output_path, output_path,
                             generated_at=None):
    runtime_path = Path(runtime_summary_path)
    raw_path = Path(raw_output_path)
    target = Path(output_path)
    runtime_summary = load_json(runtime_path)
    raw_output = _load_raw(raw_path)
    context = build_context_from_runtime_summary(runtime_summary)
    validation = run_shadow_ai(
        context,
        raw_output=json.dumps(raw_output, ensure_ascii=False),
        journal=None,
        generated_at=generated_at,
    )
    if validation.get('status') == 'validation_failed' or validation.get('proposal') is None:
        raise ValueError('shadow_ai_output_validation_failed: ' + str(validation.get('validation_error') or validation.get('status')))
    metadata = {
        'schema': 'xuanji-shadow-ai-output-metadata-v1',
        'mode': 'shadow_ai_output',
        'runtime_summary_path': str(runtime_path),
        'raw_output_source_path': str(raw_path),
        'path': str(target),
        'generated_at': generated_at or datetime.now().astimezone().isoformat(),
        'runtime_summary_hash': digest(runtime_summary),
        'raw_output_hash': digest(raw_output),
        'proposal_id': validation['proposal']['proposal_id'],
        'validation_status': 'validated',
        'execution_authority': False,
        'can_trigger_order': False,
        'live_execution_authority': False,
    }
    _write_json_atomic(target, raw_output)
    meta_path = _metadata_path(target)
    _write_json_atomic(meta_path, metadata)
    return {
        'schema': 'xuanji-shadow-ai-output-result-v1',
        'mode': 'shadow_ai_output',
        'status': 'published',
        'path': str(target),
        'metadata_path': str(meta_path),
        'proposal_id': validation['proposal']['proposal_id'],
        'execution_authority': False,
        'can_trigger_order': False,
        'live_execution_authority': False,
    }

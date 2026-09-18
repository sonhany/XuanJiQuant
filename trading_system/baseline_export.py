"""Controlled producer for daily shadow baseline_result.json.

This module publishes only reconciled paper baseline results.  It is a producer
for read-only shadow research inputs, not an execution bridge.
"""
from datetime import datetime
import json
from pathlib import Path

from .contracts import digest
from .shadow_decision import _baseline_comparison


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _metadata_path(output_path):
    target = Path(output_path)
    return target.with_name(target.stem + '.meta' + target.suffix)


def _write_json_atomic(path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(target)


def validate_baseline_result(raw):
    if not isinstance(raw, dict):
        raise ValueError('baseline_invalid')
    comparison = _baseline_comparison(raw)
    if not str(raw.get('schema') or '').startswith('nautilus-baseline-result'):
        raise ValueError('baseline_schema_invalid')
    return raw, comparison


def publish_baseline_result(*, source_path, output_path, generated_at=None):
    source = Path(source_path)
    target = Path(output_path)
    baseline, comparison = validate_baseline_result(load_json(source))
    baseline_hash = digest(baseline)
    metadata = {
        'schema': 'xuanji-baseline-export-metadata-v1',
        'mode': 'shadow_baseline_export',
        'source_path': str(source),
        'path': str(target),
        'generated_at': generated_at or datetime.now().astimezone().isoformat(),
        'baseline_result_hash': baseline_hash,
        'baseline_comparison': comparison,
        'execution_authority': False,
        'can_trigger_order': False,
        'live_execution_authority': False,
    }
    _write_json_atomic(target, baseline)
    meta_path = _metadata_path(target)
    _write_json_atomic(meta_path, metadata)
    return {
        'schema': 'xuanji-baseline-export-result-v1',
        'mode': 'shadow_baseline_export',
        'status': 'published',
        'path': str(target),
        'metadata_path': str(meta_path),
        'baseline_result_hash': baseline_hash,
        'execution_authority': False,
        'can_trigger_order': False,
        'live_execution_authority': False,
    }

"""Durable, read-only shadow DecisionProposal journal."""
from contextlib import suppress
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3

from .contracts import digest
from .shadow_decision import validate_decision_proposal


class ShadowDecisionJournal:
    def __init__(self, path):
        self.path = Path(path)
        self.conn = None
        self.lock = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = self.path.with_suffix(self.path.suffix + '.lock').open('a+b')
        self.lock.seek(0, 2)
        if not self.lock.tell():
            self.lock.write(b'0')
            self.lock.flush()
        self.lock.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.lock.close()
            self.lock = None
            raise RuntimeError('shadow_writer_busy') from exc
        try:
            self.conn = sqlite3.connect(self.path, timeout=5)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute('PRAGMA journal_mode=WAL')
            self.conn.execute('PRAGMA synchronous=FULL')
            self.conn.execute('''CREATE TABLE IF NOT EXISTS shadow_proposals(
                proposal_id TEXT PRIMARY KEY,
                proposal_hash TEXT NOT NULL,
                baseline_result_hash TEXT NOT NULL,
                producer_kind TEXT NOT NULL,
                model_id TEXT NOT NULL,
                stance TEXT NOT NULL,
                confidence REAL NOT NULL,
                baseline_equity TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                proposal_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )''')
            self.conn.execute('''CREATE TABLE IF NOT EXISTS shadow_ai_runs(
                run_id TEXT PRIMARY KEY,
                context_hash TEXT NOT NULL,
                producer_kind TEXT NOT NULL,
                model_id TEXT NOT NULL,
                status TEXT NOT NULL,
                raw_output TEXT NOT NULL,
                sanitized_output TEXT NOT NULL,
                validation_error TEXT,
                proposal_id TEXT,
                created_at TEXT NOT NULL
            )''')
            self.conn.commit()
            if self.conn.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('shadow_journal_integrity_failed')
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_args):
        if self.conn:
            self.conn.close()
            self.conn = None
        if self.lock:
            self.lock.seek(0)
            if os.name == 'nt':
                import msvcrt
                with suppress(OSError):
                    msvcrt.locking(self.lock.fileno(), msvcrt.LK_UNLCK, 1)
            self.lock.close()
            self.lock = None

    def _read_row(self, row):
        proposal = json.loads(row['proposal_json'])
        validated = validate_decision_proposal(proposal)
        if digest(validated) != row['proposal_hash']:
            raise ValueError('shadow_proposal_integrity_failed')
        if validated['baseline_comparison']['baseline_result_hash'] != row['baseline_result_hash']:
            raise ValueError('shadow_baseline_hash_mismatch')
        return validated

    def record(self, proposal):
        validated = validate_decision_proposal(proposal)
        proposal_hash = digest(validated)
        row = self.conn.execute(
            'SELECT * FROM shadow_proposals WHERE proposal_id=?',
            (validated['proposal_id'],),
        ).fetchone()
        if row:
            existing = self._read_row(row)
            if digest(existing) != proposal_hash:
                raise ValueError('shadow_proposal_identity_conflict')
            return {'status': 'existing', 'proposal': existing, 'live_execution_authority': False}
        comparison = validated['baseline_comparison']
        now = datetime.now(timezone.utc).isoformat()
        with self.conn:
            self.conn.execute(
                '''INSERT INTO shadow_proposals(
                    proposal_id,proposal_hash,baseline_result_hash,producer_kind,model_id,
                    stance,confidence,baseline_equity,generated_at,proposal_json,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                (
                    validated['proposal_id'],
                    proposal_hash,
                    comparison['baseline_result_hash'],
                    validated['producer']['kind'],
                    validated['producer']['model_id'],
                    validated['recommendation']['stance'],
                    validated['recommendation']['confidence'],
                    comparison['baseline_equity'],
                    validated['generated_at'],
                    json.dumps(validated, ensure_ascii=False, separators=(',', ':')),
                    now,
                ),
            )
        return {'status': 'recorded', 'proposal': validated, 'live_execution_authority': False}

    def _proposal_report_row(self, proposal):
        baseline_codes = set(proposal['baseline_comparison'].get('baseline_position_codes', []))
        shadow_codes = {item['code'] for item in proposal['recommendation'].get('target_weights', [])}
        return {
            'proposal_id': proposal['proposal_id'],
            'generated_at': proposal['generated_at'],
            'producer': proposal['producer'],
            'stance': proposal['recommendation']['stance'],
            'confidence': proposal['recommendation']['confidence'],
            'baseline_result_hash': proposal['baseline_comparison']['baseline_result_hash'],
            'baseline_equity': proposal['baseline_comparison']['baseline_equity'],
            'shadow_only_codes': sorted(shadow_codes - baseline_codes),
            'baseline_only_codes': sorted(baseline_codes - shadow_codes),
            'overlap_codes': sorted(baseline_codes & shadow_codes),
            'position_code_delta_count': len(shadow_codes ^ baseline_codes),
        }

    def report(self, limit=100):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('report_limit_invalid')
        rows = self.conn.execute(
            'SELECT * FROM shadow_proposals ORDER BY generated_at DESC, proposal_id DESC LIMIT ?',
            (limit,),
        ).fetchall()
        proposals = [self._read_row(row) for row in rows]
        by_stance = {}
        baseline_hashes = set()
        confidence_total = 0.0
        report_rows = []
        for proposal in proposals:
            stance = proposal['recommendation']['stance']
            by_stance[stance] = by_stance.get(stance, 0) + 1
            baseline_hashes.add(proposal['baseline_comparison']['baseline_result_hash'])
            confidence_total += proposal['recommendation']['confidence']
            report_rows.append(self._proposal_report_row(proposal))
        total = len(proposals)
        return {
            'schema': 'xuanji-shadow-decision-report-v1',
            'mode': 'shadow_decision',
            'summary': {
                'total': total,
                'by_stance': by_stance,
                'average_confidence': round(confidence_total / total, 6) if total else None,
                'baseline_result_hashes': sorted(baseline_hashes),
            },
            'proposals': report_rows,
            'execution_authority': False,
            'can_trigger_order': False,
            'live_execution_authority': False,
        }

    def record_ai_run(self, audit):
        if not isinstance(audit, dict):
            raise ValueError('shadow_ai_audit_invalid')
        required = ('context_hash', 'producer_kind', 'model_id', 'status', 'raw_output', 'sanitized_output')
        for field in required:
            if field not in audit:
                raise ValueError('shadow_ai_audit_invalid')
        if audit['status'] not in ('recorded', 'validation_failed', 'model_failed'):
            raise ValueError('shadow_ai_status_invalid')
        payload = {
            'context_hash': str(audit['context_hash']),
            'producer_kind': str(audit['producer_kind']),
            'model_id': str(audit['model_id']),
            'status': audit['status'],
            'raw_output': str(audit['raw_output']),
            'sanitized_output': str(audit['sanitized_output']),
            'validation_error': audit.get('validation_error'),
            'proposal_id': audit.get('proposal_id'),
        }
        run_id = audit.get('run_id') or 'shadow_ai_' + digest(payload)[:32]
        now = datetime.now(timezone.utc).isoformat()
        row = self.conn.execute('SELECT * FROM shadow_ai_runs WHERE run_id=?', (run_id,)).fetchone()
        if row:
            existing = dict(row)
            for key, value in payload.items():
                if existing.get(key) != value:
                    raise ValueError('shadow_ai_run_identity_conflict')
            return {'status': 'existing', 'run_id': run_id, 'live_execution_authority': False}
        with self.conn:
            self.conn.execute(
                '''INSERT INTO shadow_ai_runs(
                    run_id,context_hash,producer_kind,model_id,status,raw_output,
                    sanitized_output,validation_error,proposal_id,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)''',
                (
                    run_id,
                    payload['context_hash'],
                    payload['producer_kind'],
                    payload['model_id'],
                    payload['status'],
                    payload['raw_output'],
                    payload['sanitized_output'],
                    payload['validation_error'],
                    payload['proposal_id'],
                    now,
                ),
            )
        return {'status': 'recorded', 'run_id': run_id, 'live_execution_authority': False}

    def ai_audit_report(self, limit=100):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('report_limit_invalid')
        rows = [dict(row) for row in self.conn.execute(
            'SELECT * FROM shadow_ai_runs ORDER BY created_at DESC, run_id DESC LIMIT ?',
            (limit,),
        ).fetchall()]
        by_status = {}
        for row in rows:
            by_status[row['status']] = by_status.get(row['status'], 0) + 1
        return {
            'schema': 'xuanji-shadow-ai-audit-report-v1',
            'mode': 'shadow_decision',
            'summary': {'total': len(rows), 'by_status': by_status},
            'runs': rows,
            'execution_authority': False,
            'can_trigger_order': False,
            'live_execution_authority': False,
        }

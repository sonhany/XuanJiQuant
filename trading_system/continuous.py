"""One isolated account, append-only inputs, native full-replay projection.

No broker or active F5 integration. Revisions are cumulative projections, not
new independent accounts and not incremental native snapshots.
"""
from copy import deepcopy
import hashlib
from pathlib import Path

from .contracts import digest, integer, instant, validate_request
from .store import Journal


def _identity(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise ValueError('identity_invalid')
    return value


def _combine(previous, chunk):
    if 'continuity' in chunk:
        raise ValueError('reserved_metadata')
    chunk = validate_request(chunk)
    if previous is None:
        return chunk
    dynamic = {'frames', 'calendar', 'baseline_targets', 'continuity'}
    if ({k: v for k, v in previous.items() if k not in dynamic}
            != {k: v for k, v in chunk.items() if k not in dynamic}):
        raise ValueError('configuration_changed')
    last = instant(previous['frames'][-1]['timestamp'])
    if instant(chunk['frames'][0]['timestamp']) <= last:
        raise ValueError('unordered_append')
    added_days = set(chunk['calendar']) - set(previous['calendar'])
    if any(day <= last.date().isoformat() for day in added_days):
        raise ValueError('past_calendar_changed')
    targets = deepcopy(previous.get('baseline_targets', {}))
    for day, value in chunk.get('baseline_targets', {}).items():
        if (day in targets and targets[day] != value) or (day not in targets and day <= last.date().isoformat()):
            raise ValueError('past_target_changed')
        targets[day] = value
    merged = {k: deepcopy(v) for k, v in previous.items() if k != 'continuity'}
    merged['frames'] += chunk['frames']
    merged['calendar'] = sorted(set(previous['calendar']) | set(chunk['calendar']))
    if targets:
        merged['baseline_targets'] = targets
    return validate_request(merged)


def _prefix(previous, result):
    if previous is None:
        return
    count = len(previous['fills'])
    if result['fills'][:count] != previous['fills']:
        raise ValueError('historical_fill_changed')
    # IOC orders are terminal before a revision is committed.
    orders = {order['id']: order for order in result['orders']}
    if any(orders.get(order['id']) != order for order in previous['orders']):
        raise ValueError('historical_order_changed')


class ContinuousAccount:
    def __init__(self, path, account_id):
        self.account_id = _identity(account_id)
        self.journal = Journal(path, mode='continuous')

    def __enter__(self):
        self.journal.__enter__()
        try:
            self._chain()
        except Exception:
            self.journal.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *args):
        self.journal.__exit__(*args)

    def _chain(self):
        records = []
        rows = self.journal.conn.execute('SELECT * FROM runs ORDER BY id').fetchall()
        previous = None
        previous_result = None
        seen = set()
        adapter_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        for revision, row in enumerate(rows, 1):
            raw, result = self.journal._read(row)
            meta = raw.get('continuity')
            if not isinstance(meta, dict):
                raise ValueError('not_continuous_journal')
            if meta.get('account_id') != self.account_id:
                raise ValueError('account_identity_mismatch')
            if meta.get('adapter_hash') != adapter_hash:
                raise ValueError('account_implementation_changed')
            batch = _identity(meta.get('batch_id'))
            chunk = meta.get('chunk')
            if (revision > 100 or batch in seen or row['id'] != f'account-{revision:06d}'
                    or meta.get('revision') != revision
                    or meta.get('previous_output_hash') != (digest(previous_result) if previous_result else None)
                    or meta.get('chunk_hash') != digest(chunk)):
                raise ValueError('account_chain_invalid')
            reconstructed = _combine(previous, chunk)
            reconstructed['continuity'] = meta
            if digest(reconstructed) != digest(raw):
                raise ValueError('account_prefix_invalid')
            if result is None and revision != len(rows):
                raise ValueError('pending_not_tail')
            if result is not None:
                _prefix(previous_result, result)
            records.append((row['id'], raw, result))
            previous, previous_result = raw, result
            seen.add(batch)
        return records

    def _response(self, raw, result, previous_result):
        return {
            'account_id': self.account_id, 'revision': raw['continuity']['revision'],
            'batch_id': raw['continuity']['batch_id'], 'result': deepcopy(result),
            'new_fill_count': len(result['fills']) - (len(previous_result['fills']) if previous_result else 0),
            'mode': 'continuous_full_replay', 'live_execution_authority': False,
        }

    def append(self, batch_id, chunk, expected_revision, *, checkpoint_hook=None):
        batch_id = _identity(batch_id)
        integer(expected_revision, 0, 100)
        chunk = validate_request(chunk)
        records = self._chain()
        for index, (_, raw, result) in enumerate(records):
            if raw['continuity']['batch_id'] == batch_id:
                if digest(chunk) != raw['continuity']['chunk_hash']:
                    raise ValueError('batch_identity_conflict')
                if result is None:
                    raise ValueError('pending_recovery_required')
                return self._response(raw, result, records[index - 1][2] if index else None)
        if records and records[-1][2] is None:
            raise ValueError('pending_recovery_required')
        if expected_revision != len(records):
            raise ValueError('revision_conflict')
        if len(records) >= 100:
            raise ValueError('account_capacity_reached')
        previous = records[-1][1] if records else None
        previous_result = records[-1][2] if records else None
        merged = _combine(previous, chunk)
        revision = len(records) + 1
        merged['continuity'] = {
            'account_id': self.account_id, 'revision': revision, 'batch_id': batch_id,
            'chunk': chunk, 'chunk_hash': digest(chunk),
            'previous_output_hash': digest(previous_result) if previous_result else None,
            'adapter_hash': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }
        result = self.journal.execute(
            f'account-{revision:06d}', merged, checkpoint_hook=checkpoint_hook,
            validate_result=lambda result: _prefix(previous_result, result),
        )
        return self._response(merged, result, previous_result)

    def status(self):
        records = self._chain()
        completed = [record for record in records if record[2] is not None]
        return {
            'account_id': self.account_id, 'committed_revision': len(completed),
            'pending_revision': len(records) if len(records) != len(completed) else None,
            'result': deepcopy(completed[-1][2]) if completed else None,
            'mode': 'continuous_full_replay', 'live_execution_authority': False,
        }

    def recover(self):
        from .native import run_replay
        records = self._chain()
        previous_result = None
        response = None
        for identity, raw, committed in records:
            if committed is None:
                result = self.journal.execute(identity, raw, validate_result=lambda r: _prefix(previous_result, r))
            else:
                result = run_replay(raw)
                if digest(result) != digest(committed):
                    raise ValueError('replay_reconciliation_failed')
                _prefix(previous_result, result)
            response = self._response(raw, result, previous_result)
            previous_result = result
        return response or self.status()

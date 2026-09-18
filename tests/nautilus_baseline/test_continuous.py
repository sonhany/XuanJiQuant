from copy import deepcopy
import json
import os
import sqlite3
import subprocess
import sys

import pytest
pytest.importorskip('nautilus_trader')
from tests.nautilus_baseline.fixtures import request, frame, intent


def account(path, name='baseline-account'):
    from trading_system.continuous import ContinuousAccount
    return ContinuousAccount(path, name)


def chunk(timestamp, side='buy', identity='buy-1'):
    data = request()
    data['frames'] = [frame(timestamp, [intent(identity, side, 1000)])]
    return data


def test_three_batches_preserve_cash_t1_and_native_account(tmp_path):
    db = tmp_path/'account.sqlite3'
    with account(db) as a:
        one = a.append('b1', chunk('2026-09-10T10:00:00+08:00'), 0)
        assert one['result']['cash'] == '89994.90'
        assert one['result']['available'] == {'600000': 0}
    with account(db) as a:
        two = a.append('b2', chunk('2026-09-10T10:01:00+08:00', 'sell', 'sell-1'), 1)
        assert two['result']['cash'] == '89994.90'
        assert two['new_fill_count'] == 0
        three = a.append('b3', chunk('2026-09-11T10:00:00+08:00', 'sell', 'sell-2'), 2)
        assert three['result']['cash'] == '99984.80'
        assert three['result']['positions'] == {}
        assert len(three['result']['fills']) == 2
        assert three['new_fill_count'] == 1
        assert a.status()['committed_revision'] == 3
        assert a.recover()['result'] == three['result']


def test_duplicate_batch_does_not_append_or_fill_twice(tmp_path):
    data = chunk('2026-09-10T10:00:00+08:00')
    with account(tmp_path/'a.db') as a:
        first = a.append('one', data, 0)
        assert a.append('one', data, 0) == first
        assert a.status()['committed_revision'] == 1
        changed = deepcopy(data); changed['frames'][0]['orders'][0]['quantity'] = 2000
        with pytest.raises(ValueError, match='batch_identity_conflict'):
            a.append('one', changed, 1)


@pytest.mark.parametrize('change,reason', [
    ('capital', 'configuration_changed'), ('old_frame', 'unordered_append'),
    ('revision', 'revision_conflict'), ('calendar', 'past_calendar_changed'),
])
def test_invalid_append_leaves_original_projection_unchanged(tmp_path, change, reason):
    data = chunk('2026-09-10T10:00:00+08:00')
    with account(tmp_path/'a.db') as a:
        first = a.append('one', data, 0)
        next_data = chunk('2026-09-11T10:00:00+08:00', 'sell', 'sell-2')
        revision = 1
        if change == 'capital': next_data['initial_cash'] = '200000'
        if change == 'old_frame': next_data = deepcopy(data)
        if change == 'revision': revision = 0
        if change == 'calendar': next_data['calendar'].insert(0, '2026-09-09')
        with pytest.raises(ValueError, match=reason): a.append('two', next_data, revision)
        assert a.status()['result'] == first['result']


def test_wrong_account_cannot_open_existing_journal(tmp_path):
    path = tmp_path/'a.db'
    with account(path) as a: a.append('one', chunk('2026-09-10T10:00:00+08:00'), 0)
    with pytest.raises(ValueError, match='account_identity_mismatch'):
        with account(path, 'other'): pass


def test_independent_trial_journal_cannot_be_used_as_continuous_account(tmp_path):
    from trading_system.store import Journal
    path = tmp_path/'a.db'
    with Journal(path) as j: j.execute('trial', request())
    with pytest.raises(ValueError, match='not_continuous_journal'):
        with account(path): pass


@pytest.mark.parametrize('operation', ['run', 'recover'])
def test_trial_api_cannot_mutate_or_recover_continuous_journal(tmp_path,operation):
    from trading_system.store import Journal
    path=tmp_path/'a.db'
    with account(path) as a:
        first=a.append('one',chunk('2026-09-10T10:00:00+08:00'),0)
    with pytest.raises(ValueError,match='continuous_journal_requires_account_api'):
        with Journal(path) as journal:
            if operation=='run':journal.execute('unrelated-trial',request())
            else:journal.recover()
    with account(path) as a:
        assert a.status()['committed_revision']==1
        assert a.status()['result']==first['result']


def test_generic_recover_is_disabled_even_in_continuous_mode(tmp_path):
    with account(tmp_path/'a.db') as a:
        a.append('one',chunk('2026-09-10T10:00:00+08:00'),0)
        with pytest.raises(ValueError,match='use_continuous_recovery'):
            a.journal.recover()


@pytest.mark.parametrize('validator',[False,0,'not-callable'])
def test_continuous_validator_must_be_callable(tmp_path,validator):
    with account(tmp_path/'a.db') as a:
        a.append('one',chunk('2026-09-10T10:00:00+08:00'),0)
        raw=a._chain()[0][1]
        with pytest.raises(ValueError,match='continuous_validator_required'):
            a.journal.execute('bypass',raw,validate_result=validator)
        assert a.status()['committed_revision']==1


def test_existing_target_day_cannot_be_rewritten(tmp_path):
    data = request(); data['frames'][0]['orders'] = []
    data['baseline_targets'] = {'2026-09-10': 1000}
    with account(tmp_path/'a.db') as a:
        a.append('one', data, 0)
        second = deepcopy(data)
        second['frames'] = [frame('2026-09-10T10:01:00+08:00', [])]
        second['baseline_targets']['2026-09-10'] = 0
        with pytest.raises(ValueError, match='past_target_changed'):
            a.append('two', second, 1)


@pytest.mark.parametrize('point', ['input_committed', 'output_committed'])
def test_crashed_second_batch_recovers_without_reset_or_duplicate(tmp_path, point):
    path = tmp_path/'a.db'
    with account(path) as a: a.append('one', chunk('2026-09-10T10:00:00+08:00'), 0)
    second = chunk('2026-09-11T10:00:00+08:00', 'sell', 'sell-2')
    source = tmp_path/'chunk.json'; source.write_text(json.dumps(second), encoding='utf-8')
    worker = '''
import json,os,sys
from pathlib import Path
from trading_system.continuous import ContinuousAccount
with ContinuousAccount(sys.argv[1],'baseline-account') as a:
    def stop(stage):
        if stage==sys.argv[3]:os._exit(77)
    a.append('two',json.loads(Path(sys.argv[2]).read_text()),1,checkpoint_hook=stop)
'''
    child = subprocess.run([sys.executable, '-c', worker, str(path), str(source), point], capture_output=True, timeout=30)
    assert child.returncode == 77, child.stderr
    with account(path) as a:
        state = a.status()
        if point == 'input_committed':
            assert state['pending_revision'] == 2
            assert state['result']['positions'] == {'600000': 1000}
            with pytest.raises(ValueError, match='pending_recovery_required'):
                a.append('three', second, 1)
        result = a.recover()
        assert result['result']['cash'] == '99984.80'
        assert len(result['result']['fills']) == 2
        assert a.append('two', second, 1)['result'] == result['result']
        assert a.status()['committed_revision'] == 2


def test_changed_chain_link_is_rejected_even_with_recomputed_row_hash(tmp_path):
    from trading_system.contracts import digest
    path = tmp_path/'a.db'
    with account(path) as a:
        a.append('one', chunk('2026-09-10T10:00:00+08:00'), 0)
        a.append('two', chunk('2026-09-11T10:00:00+08:00', 'sell', 'sell-2'), 1)
    with sqlite3.connect(path) as c:
        row = c.execute('SELECT id,input_json FROM runs ORDER BY id DESC LIMIT 1').fetchone()
        data = json.loads(row[1]); data['continuity']['previous_output_hash'] = 'wrong'
        c.execute('UPDATE runs SET input_json=?,input_hash=? WHERE id=?', (json.dumps(data), digest(data), row[0]))
    with pytest.raises(ValueError, match='account_chain_invalid'):
        with account(path): pass


def test_historical_fill_change_during_append_stays_pending(tmp_path,monkeypatch):
    from trading_system import native
    original=native.run_replay
    with account(tmp_path/'a.db') as a:
        a.append('one',chunk('2026-09-10T10:00:00+08:00'),0)
        def changed(request):
            result=original(request)
            result['fills'][0]['price']='99.00'
            return result
        monkeypatch.setattr(native,'run_replay',changed)
        with pytest.raises(ValueError,match='historical_fill_changed'):
            a.append('two',chunk('2026-09-11T10:00:00+08:00','sell','sell-2'),1)
        state=a.status()
        assert state['pending_revision']==2
        assert state['result']['cash']=='89994.90'

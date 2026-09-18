import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest
pytest.importorskip('nautilus_trader')
from trading_system.store import Journal
from tests.nautilus_baseline.fixtures import request


def test_repeated_request_is_single_committed_result(tmp_path):
    with Journal(tmp_path/'baseline.sqlite3') as journal:
        first=journal.execute('run-1',request())
        assert journal.execute('run-1',request())==first
        assert journal.status()['count']==1


def test_changed_run_identity_is_rejected(tmp_path):
    with Journal(tmp_path/'baseline.sqlite3') as journal:
        journal.execute('run-1',request())
        changed=request();changed['initial_cash']='200000'
        with pytest.raises(ValueError,match='run_identity_conflict'):
            journal.execute('run-1',changed)


def test_failed_result_validation_is_not_committed(tmp_path):
    def reject(result):
        raise ValueError('historical_fill_changed')
    with Journal(tmp_path/'a.db') as journal:
        with pytest.raises(ValueError,match='historical_fill_changed'):
            journal.execute('one',request(),validate_result=reject)
        assert journal.status()['runs'][0]['status']=='pending'


def test_caller_mutation_after_commit_cannot_change_execution(tmp_path):
    original=request()
    def callback(stage):
        if stage=='input_committed':original['frames'][0]['orders'][0]['quantity']=2000
    with Journal(tmp_path/'baseline.sqlite3') as journal:
        result=journal.execute('run-1',original,checkpoint_hook=callback)
        assert result['positions']=={'600000':1000}
        assert journal.recover()['run-1']==result


def test_status_does_not_report_corrupt_result_as_completed(tmp_path):
    db=tmp_path/'baseline.sqlite3'
    with Journal(db) as journal:journal.execute('run-1',request())
    with sqlite3.connect(db) as c:c.execute("update runs set output_json='{}'")
    with Journal(db) as journal:
        with pytest.raises(ValueError,match='integrity'):journal.status()


def test_foreign_database_is_not_modified(tmp_path):
    db=tmp_path/'foreign.sqlite3'
    with sqlite3.connect(db) as c:c.execute('create table other(value text)')
    before=db.read_bytes()
    with pytest.raises(ValueError,match='foreign_database'):
        with Journal(db):pass
    assert db.read_bytes()==before


@pytest.mark.parametrize('point',['input_committed','output_committed'])
def test_external_kill_releases_process_lock_and_recovery_is_idempotent(tmp_path,point):
    db=tmp_path/'baseline.sqlite3'
    source=tmp_path/'input.json';source.write_text(json.dumps(request()),encoding='utf-8')
    worker='''
import json,sys
from pathlib import Path
from trading_system.store import Journal
with Journal(Path(sys.argv[1])) as journal:
    def checkpoint(stage):
        if stage==sys.argv[3]:
            print('READY',flush=True)
            sys.stdin.read(1)
    journal.execute('external-kill',json.loads(Path(sys.argv[2]).read_text()),checkpoint_hook=checkpoint)
'''
    proc=subprocess.Popen([sys.executable,'-c',worker,str(db),str(source),point],
                          stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        assert proc.stdout.readline().strip()=='READY'
        contender=subprocess.run([sys.executable,'-c',
            "from trading_system.store import Journal;import sys\nwith Journal(sys.argv[1]):print('UNEXPECTED')",
            str(db)],capture_output=True,text=True,timeout=20)
        assert contender.returncode!=0 and 'writer_busy' in contender.stderr
        assert 'UNEXPECTED' not in contender.stdout
        proc.kill();proc.communicate(timeout=15)
    finally:
        if proc.poll() is None:proc.kill();proc.communicate(timeout=15)
    with Journal(db) as journal:
        recovered=journal.recover()['external-kill']
        assert recovered['cash']=='89994.90'
        assert recovered['positions']=={'600000':1000}
        assert len(recovered['fills'])==1
        assert journal.execute('external-kill',request())==recovered
        assert journal.status()['count']==1


def test_single_writer_lock(tmp_path):
    with Journal(tmp_path/'baseline.sqlite3'):
        with pytest.raises(RuntimeError,match='writer_busy'):
            with Journal(tmp_path/'baseline.sqlite3'):
                pass


@pytest.mark.parametrize('column',['input_json','output_json'])
def test_tampered_journal_fails_closed(tmp_path,column):
    db=tmp_path/'baseline.sqlite3'
    with Journal(db) as journal:journal.execute('run-1',request())
    with sqlite3.connect(db) as c:c.execute(f"update runs set {column}='{{}}'")
    with Journal(db) as journal:
        with pytest.raises(ValueError,match='integrity'):
            journal.recover()


@pytest.mark.parametrize('point',['input_committed','output_committed'])
def test_process_termination_recovery_matches_uninterrupted_run(tmp_path,point):
    db=tmp_path/'baseline.sqlite3'
    source=tmp_path/'input.json';source.write_text(json.dumps(request()),encoding='utf-8')
    code='''
import json,os,sys
from pathlib import Path
from trading_system.store import Journal
with Journal(Path(sys.argv[1])) as journal:
    def failpoint(stage):
        if stage==sys.argv[3]: os._exit(77)
    journal.execute('crash-run',json.loads(Path(sys.argv[2]).read_text()),checkpoint_hook=failpoint)
'''
    crashed=subprocess.run([sys.executable,'-c',code,str(db),str(source),point],capture_output=True,timeout=30)
    assert crashed.returncode==77,crashed.stderr.decode(errors='replace')
    recover_code='''
import json,sys
from pathlib import Path
from trading_system.store import Journal
with Journal(Path(sys.argv[1])) as journal:
    print(json.dumps(journal.recover()))
'''
    recovered=subprocess.run([sys.executable,'-c',recover_code,str(db)],capture_output=True,text=True,timeout=30)
    assert recovered.returncode==0,recovered.stderr
    result=json.loads(recovered.stdout)['crash-run']
    with Journal(tmp_path/'reference.sqlite3') as journal: reference=journal.execute('crash-run',request())
    assert result==reference
    assert result['cash']=='89994.90'
    assert len(result['fills'])==1
    with Journal(db) as journal:assert journal.status()['count']==1

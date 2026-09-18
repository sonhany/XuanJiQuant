import json
import subprocess
import sys
import pytest
pytest.importorskip('nautilus_trader')
from tests.nautilus_baseline.fixtures import request


def test_cli_run_recover_and_status_share_one_result(tmp_path):
    source=tmp_path/'scenario.json'
    source.write_text(json.dumps(request()),encoding='utf-8')
    common=[sys.executable,'-m','trading_system.cli','--journal',str(tmp_path/'baseline.sqlite3')]
    results=[]
    for args in [['run','--input',str(source),'--id','baseline'],['recover'],['status']]:
        process=subprocess.run(common+args,capture_output=True,text=True,encoding='utf-8',timeout=30)
        assert process.returncode==0,process.stderr
        results.append(json.loads(process.stdout))
    assert results[0]['data']['cash']=='89994.90'
    assert results[0]['data']==results[1]['data']['baseline']
    assert results[2]['data']['count']==1


def test_cli_returns_nonzero_for_identity_conflict(tmp_path):
    source=tmp_path/'scenario.json';data=request()
    source.write_text(json.dumps(data),encoding='utf-8')
    command=[sys.executable,'-m','trading_system.cli','--journal',str(tmp_path/'baseline.sqlite3'),
             'run','--input',str(source),'--id','baseline']
    first=subprocess.run(command,capture_output=True,text=True,timeout=30)
    assert first.returncode==0,first.stderr
    data['initial_cash']='200000';source.write_text(json.dumps(data),encoding='utf-8')
    second=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=30)
    assert second.returncode==1
    assert json.loads(second.stdout)['reason']=='run_identity_conflict'


def test_continuous_cli_preserves_same_account_across_processes(tmp_path):
    from tests.nautilus_baseline.test_continuous import chunk
    source=tmp_path/'chunk.json'
    common=[sys.executable,'-m','trading_system.cli','--journal',str(tmp_path/'continuous.db')]
    for revision, data in enumerate([
        chunk('2026-09-10T10:00:00+08:00'),
        chunk('2026-09-11T10:00:00+08:00','sell','sell-2'),
    ]):
        source.write_text(json.dumps(data),encoding='utf-8')
        process=subprocess.run(common+['account-append','--account','demo','--id',str(revision),
            '--expected-revision',str(revision),'--input',str(source)],capture_output=True,text=True,timeout=30)
        assert process.returncode==0,process.stdout+process.stderr
    for action in ('account-status','account-recover'):
        process=subprocess.run(common+[action,'--account','demo'],capture_output=True,text=True,timeout=30)
        assert process.returncode==0,process.stdout+process.stderr
        result=json.loads(process.stdout)['data']['result']
        assert result['cash']=='99984.80' and not result['positions']
        assert len(result['fills'])==2


def test_continuous_cli_requires_explicit_separate_journal():
    process=subprocess.run([sys.executable,'-m','trading_system.cli','account-status','--account','demo'],
                           capture_output=True,text=True,timeout=30)
    assert process.returncode==1
    assert json.loads(process.stdout)['reason']=='explicit_account_journal_required'

"""Durable replay journal. Native engine results are projections, not new fills."""
from contextlib import suppress
from datetime import datetime,timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import sqlite3

from .contracts import digest,validate_request


def implementation_hash():
    root=Path(__file__).parent
    code={name:hashlib.sha256((root/name).read_bytes()).hexdigest()
          for name in ('contracts.py','rules.py','native.py')}
    return digest({'code':code,'nautilus':version('nautilus_trader')})


class Journal:
    def __init__(self,path,*,mode='trial'):
        if mode not in ('trial','continuous'):
            raise ValueError('journal_mode_invalid')
        self.path=Path(path);self.conn=None;self.lock=None;self.mode=mode

    def _check_mode(self,raw):
        if not isinstance(raw,dict):
            raise ValueError('journal_input_invalid')
        if self.mode=='trial' and 'continuity' in raw:
            raise ValueError('continuous_journal_requires_account_api')
        if self.mode=='continuous' and not isinstance(raw.get('continuity'),dict):
            raise ValueError('not_continuous_journal')

    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.lock=self.path.with_suffix(self.path.suffix+'.lock').open('a+b')
        self.lock.seek(0,2)
        if not self.lock.tell():self.lock.write(b'0');self.lock.flush()
        self.lock.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.lock.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:
            self.lock.close();self.lock=None
            raise RuntimeError('writer_busy') from exc
        try:
            self.conn=sqlite3.connect(self.path,timeout=5)
            self.conn.row_factory=sqlite3.Row
            tables={r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            expected={'id','input_hash','input_json','implementation_hash','status','output_hash',
                      'output_json','attempts','created_at','updated_at'}
            if tables and (tables!={'runs'} or {r[1] for r in self.conn.execute('PRAGMA table_info(runs)')}!=expected):
                raise ValueError('foreign_database')
            if tables:
                for row in self.conn.execute('SELECT input_json FROM runs'):
                    self._check_mode(json.loads(row[0]))
            self.conn.execute('PRAGMA journal_mode=WAL')
            self.conn.execute('PRAGMA synchronous=FULL')
            self.conn.execute('''CREATE TABLE IF NOT EXISTS runs(
                id TEXT PRIMARY KEY,input_hash TEXT NOT NULL,input_json TEXT NOT NULL,
                implementation_hash TEXT NOT NULL,status TEXT NOT NULL,
                output_hash TEXT,output_json TEXT,attempts INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,updated_at TEXT NOT NULL)''')
            self.conn.commit()
            if self.conn.execute('PRAGMA quick_check').fetchone()[0]!='ok':
                raise ValueError('journal_integrity_failed')
        except Exception:
            self.__exit__(None,None,None);raise
        return self

    def __exit__(self,*_args):
        if self.conn:self.conn.close();self.conn=None
        if self.lock:
            self.lock.seek(0)
            if os.name=='nt':
                import msvcrt
                with suppress(OSError):msvcrt.locking(self.lock.fileno(),msvcrt.LK_UNLCK,1)
            self.lock.close();self.lock=None

    def _read(self,row):
        raw=json.loads(row['input_json'])
        self._check_mode(raw)
        if digest(raw)!=row['input_hash']:raise ValueError('input_integrity_failed')
        if row['implementation_hash']!=implementation_hash():raise ValueError('implementation_identity_mismatch')
        if row['status']=='completed':
            result=json.loads(row['output_json'])
            if digest(result)!=row['output_hash']:raise ValueError('output_integrity_failed')
            return raw,result
        if row['status']!='pending':raise ValueError('journal_state_invalid')
        return raw,None

    def execute(self,identity,request,*,checkpoint_hook=None,validate_result=None):
        if not isinstance(identity,str) or not identity or len(identity)>128:
            raise ValueError('run_id_invalid')
        request=validate_request(request)
        self._check_mode(request)
        if self.mode=='continuous' and not callable(validate_result):
            raise ValueError('continuous_validator_required')
        if validate_result is not None and not callable(validate_result):
            raise ValueError('result_validator_invalid')
        now=datetime.now(timezone.utc).isoformat()
        row=self.conn.execute('SELECT * FROM runs WHERE id=?',(identity,)).fetchone()
        if row:
            original,result=self._read(row)
            if digest(request)!=row['input_hash']:raise ValueError('run_identity_conflict')
            if result is not None:return result
        else:
            with self.conn:
                self.conn.execute('INSERT INTO runs(id,input_hash,input_json,implementation_hash,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                                  (identity,digest(request),json.dumps(request,ensure_ascii=False),implementation_hash(),'pending',now,now))
        if checkpoint_hook:checkpoint_hook('input_committed')
        from .native import run_replay
        with self.conn:
            self.conn.execute('UPDATE runs SET attempts=attempts+1 WHERE id=?',(identity,))
        result=run_replay(request)
        if validate_result is not None:
            validate_result(result)
        with self.conn:
            self.conn.execute("UPDATE runs SET status='completed',output_hash=?,output_json=?,updated_at=? WHERE id=?",
                              (digest(result),json.dumps(result,ensure_ascii=False),datetime.now(timezone.utc).isoformat(),identity))
        if checkpoint_hook:checkpoint_hook('output_committed')
        return result

    def recover(self):
        if self.mode=='continuous':
            raise ValueError('use_continuous_recovery')
        from .native import run_replay
        results={}
        for row in self.conn.execute('SELECT * FROM runs ORDER BY created_at,id').fetchall():
            request,committed=self._read(row)
            if committed is None:
                results[row['id']]=self.execute(row['id'],request)
            else:
                replay=run_replay(request)
                if digest(replay)!=row['output_hash']:raise ValueError('replay_reconciliation_failed')
                results[row['id']]=replay
        return results

    def status(self):
        for row in self.conn.execute('SELECT * FROM runs'):
            self._read(row)
        rows=[dict(r) for r in self.conn.execute('SELECT id,status,attempts,created_at,updated_at FROM runs ORDER BY created_at,id')]
        return {'count':len(rows),'runs':rows,'live_execution_authority':False}

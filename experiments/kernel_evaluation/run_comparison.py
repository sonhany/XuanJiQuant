"""Collect machine-readable observations from real, isolated candidate engines."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile

from nautilus_probe import run_native, FIXTURE

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'data' / 'kernel-evaluation'
DOTNET = OUT / 'dotnet' / 'dotnet.exe'
EXPERIMENT = Path(__file__).parent


def command(args, cwd):
    started = time.perf_counter()
    result = subprocess.run(args, cwd=cwd, capture_output=True, encoding='utf-8', errors='replace', timeout=120)
    return result, round(time.perf_counter()-started, 3)


def collect():
    OUT.mkdir(parents=True,exist_ok=True)
    report={'fixture_sha256':hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
            'data_kind':'synthetic_engineering_fixture', 'production_authority':False,
            'nautilus':[], 'lean':[]}
    report['source_sha256']={str(p.relative_to(EXPERIMENT)):hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in EXPERIMENT.rglob('*') if p.suffix in ('.py','.cs','.csproj')
                             and not any(part in ('bin','obj','__pycache__') for part in p.parts)}
    modes=['full','partial_complete','partial_cancel','same_day_roundtrip','insufficient_cash','cash_reservation','suspended','above_daily_limit','odd_lot','aggressive_limit']
    for mode in modes:
        report['nautilus'].append(run_native(mode))
    base=json.loads((EXPERIMENT/'lean_engine'/'backtest.json').read_text())
    for mode in modes:
        # Controlled quote/bar representations of the same flat-price scenario.
        directory=OUT/'lean-data'/'equity'/'xshg'/'minute'/'600000'
        trade=[]
        quote=[]
        for i in range(4):
            price=120000 if mode=='above_daily_limit' else 110000 if mode=='partial_cancel' and i>0 else 100000
            volume=400 if (mode.startswith('partial') or mode=='aggressive_limit') and i==0 else 600 if mode.startswith('partial') else 100000
            milliseconds=34500000+i*60000
            trade.append(f'{milliseconds},{price},{price},{price},{price},{volume}')
            quote.append(f'{milliseconds},{price},{price},{price},{price},{volume},{price},{price},{price},{price},{volume}')
        for name,rows in [('trade',trade),('quote',quote)]:
            with zipfile.ZipFile(directory/f'20260910_{name}.zip','w') as z:
                z.writestr(f'20260910_600000_minute_{name}.csv','\n'.join(rows)+'\n')
        config={**base,'parameters':{'probe_mode':mode},'results-destination-folder':str(OUT/'lean-results'/mode)}
        config_path=OUT/f'lean-{mode}.json'
        config_path.write_text(json.dumps(config,indent=2),encoding='utf-8')
        result,seconds=command([str(DOTNET),str(EXPERIMENT/'lean_engine'/'bin'/'Debug'/'net10.0'/'EngineProbe.dll'),str(config_path)],OUT)
        (OUT/f'lean-{mode}.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
        lines=[line.split('KERNEL_PROBE=',1)[1] for line in result.stdout.splitlines() if 'KERNEL_PROBE=' in line]
        payload=json.loads(lines[-1]) if lines else {'error':'no_native_result'}
        report['lean'].append({**payload,'exit_code':result.returncode,'wall_seconds':seconds,
                               'warning_count':sum('ERROR::' in l for l in result.stdout.splitlines())})
        print(json.dumps({'engine':'lean','mode':mode,'result':payload}),flush=True)
    result,seconds=command([str(DOTNET),str(EXPERIMENT/'lean'/'bin'/'Debug'/'net10.0'/'KernelProbe.dll'),str(FIXTURE)],OUT)
    native=[line for line in result.stdout.splitlines() if line.startswith('{"engine"')]
    report['lean_accounting']=json.loads(native[-1]) if native else {'error':result.stderr}
    report['lean_accounting']['exit_code']=result.returncode
    report['generated_at_utc']=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
    temp=OUT/'comparison.json.tmp'
    temp.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    os.replace(temp,OUT/'comparison.json')
    if any(r.get('exit_code')!=0 or r.get('ticks',0)==0 for r in report['lean']):
        raise SystemExit('LEAN engine observations incomplete; inspect logs')
    print(str(OUT/'comparison.json'))


if __name__=='__main__':
    collect()

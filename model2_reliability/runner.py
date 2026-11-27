"""Scheduled Model 2 operations. Existing engines retain all authority."""
import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from zoneinfo import ZoneInfo
import exchange_calendars as xcals
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
NY = ZoneInfo('America/New_York')
COMMANDS = {
    'execution': ('model2_guarded_execution_command.py', '--execute-paper', '--confirm', 'MODEL2-PAPER'),
    'decision': ('model2_decision_command.py', '--run'),
    'snapshot': ('model2_equity_snapshot.py', '--save'),
    'closing': ('model2_reliability/maintenance.py', '--save'),
    'cleanup': ('model2_auto_expire_stale_orders.py',),
}


def gate(task, now, cal=None):
    if now.tzinfo is None or now.utcoffset() is None: raise ValueError('Timezone required')
    if task == 'cleanup': return None  # existing engine expires past sessions only
    cal = cal if cal is not None else xcals.get_calendar('XNYS')
    day = pd.Timestamp(now.astimezone(NY).date())
    if not cal.is_session(day): return 'Not an NYSE session'
    op, cl = cal.session_open(day), cal.session_close(day)
    if task == 'execution' and not op+timedelta(minutes=15) <= now < cl-timedelta(minutes=30):
        return 'Outside permitted execution window'
    if task == 'snapshot' and not op <= now <= cl+timedelta(minutes=5):
        return 'Outside snapshot window'
    if task in ('decision','closing') and now < cl+timedelta(minutes=15):
        return 'Before close plus 15 minutes'
    return None


def db_path():
    from model2_config import get_model2_paths
    return Path(get_model2_paths().model2_database).resolve()


def precheck(task, day):
    if task not in ('execution','decision'): return None
    from model2_config import MODEL_2_VERSION, MODEL_2_ACCOUNT_ID
    return precheck_db(task,day,db_path(),MODEL_2_VERSION,MODEL_2_ACCOUNT_ID)


def precheck_db(task,day,path,version,account):
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=10)) as c:
        c.execute('PRAGMA query_only=ON')
        if [x[0] for x in c.execute('SELECT account_id FROM paper_accounts')] != [account]: raise ValueError('Unexpected trading account')
        if task == 'execution':
            # Do not bypass preflight on pending orders. No pending orders is a normal skip.
            count = c.execute("SELECT count(*) FROM paper_orders WHERE model_version=? AND execution_session=? AND status='PENDING'",(version,day)).fetchone()[0]
            if not count: return 'No pending orders for today'
        else:
            if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='model2_decision_runs'").fetchone():
                row=c.execute('SELECT status FROM model2_decision_runs WHERE decision_session=? AND model_version=?',(day,version)).fetchone()
                if row and row[0]=='COMPLETED': return 'Decision ledger already completed'
                if row: raise RuntimeError('Decision ledger requires review: '+str(row[0]))
    return None


def prior_execution_block(day, root=ROOT):
    path=root/'logs'/'model2_execution_outcomes.jsonl'
    if not path.exists(): return False
    unfinished=set()
    for line in path.read_text(encoding='utf-8').splitlines():
        entry=json.loads(line)
        if datetime.fromisoformat(entry['started_at']).astimezone(NY).date().isoformat()!=day: continue
        if entry['status']=='BLOCKED_OR_FAILED': return True
        if entry['status']=='STARTED': unfinished.add(entry['started_at'])
        else: unfinished.discard(entry['started_at'])
    return bool(unfinished)


def record(task, status, detail, code, started):
    log=ROOT/'logs'; log.mkdir(exist_ok=True)
    entry=dict(task=task,status=status,detail=detail,exit_code=code,started_at=started.isoformat(),finished_at=None if status=='STARTED' else datetime.now(timezone.utc).isoformat())
    # Separate file per task to avoid concurrent append collisions.
    with (log/f'model2_{task}_outcomes.jsonl').open('a',encoding='utf-8') as f: f.write(json.dumps(entry)+'\n')
    print(json.dumps(entry),flush=True)
    return code


def main():
    p=argparse.ArgumentParser(); p.add_argument('task',choices=COMMANDS); p.add_argument('--apply',action='store_true'); a=p.parse_args()
    now=datetime.now(timezone.utc); day=now.astimezone(NY).date().isoformat()
    try:
        reason=gate(a.task,now)
        if reason is None: reason=precheck(a.task,day)
        if reason is None and a.task=='execution' and prior_execution_block(day): reason='Earlier execution failure or unfinished run today; manual review required'
        if not a.apply:
            print('PREVIEW ONLY:',reason or 'Eligible to invoke existing command'); return 0
        if reason: return record(a.task,'SKIP',reason,0,now)
        cmd=[sys.executable,'-u',*COMMANDS[a.task]]
        if a.task=='execution': cmd.extend(['--session',day])
        if a.task=='closing': cmd=[sys.executable,'-u','-m','model2_reliability.maintenance','--save']
        record(a.task,'STARTED','Invoking existing guarded command',None,now)
        result=subprocess.run(cmd,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace')
        print(result.stdout,flush=True)
        status='SUCCESS' if result.returncode==0 else 'BLOCKED_OR_FAILED'
        if result.returncode==0 and 'SKIPPED:' in result.stdout: status='INCOMPLETE'
        return record(a.task,status,'See task text log',result.returncode,now)
    except Exception as exc:
        if not a.apply: print(type(exc).__name__,str(exc)); return 1
        return record(a.task,'BLOCKED_OR_FAILED',type(exc).__name__+': '+str(exc),1,now)

if __name__=='__main__': raise SystemExit(main())

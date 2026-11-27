"""Recover verified closes from existing safe bars and collect SPY separately."""
import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import csv
import math
import os
import sqlite3
import tempfile
import exchange_calendars as xcals
import pandas as pd
from model2_daily_equity import valuation, save, NY
from .runner import db_path


def recover(source, dest, now, apply=False):
    cal=xcals.get_calendar('XNYS'); today=now.astimezone(NY).date()
    if dest.resolve()==source.resolve(): raise ValueError('Overlapping database paths')
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as c:
        c.execute('PRAGMA query_only=ON'); c.execute('BEGIN')
        account=c.execute("SELECT created_at_utc FROM paper_accounts WHERE account_id='model2-paper'").fetchone()
        if not account: raise ValueError('Missing Model 2 account')
        start=datetime.fromisoformat(account[0]).astimezone(NY).date()
        existing=set()
        if dest.exists():
            with closing(sqlite3.connect(dest.as_uri()+'?mode=ro',uri=True)) as d:
                for table in ('daily_equity_snapshots','daily_equity_backfill'):
                    if d.execute("SELECT 1 FROM sqlite_master WHERE name=? AND type='table'",(table,)).fetchone():
                        existing.update(x[0] for x in d.execute(f"SELECT session_date FROM {table} WHERE account_id='model2-paper'"))
        gaps=[]; count=0
        for s in cal.sessions_in_range(str(start),str(today)):
            day=s.date().isoformat(); close=cal.session_close(s).to_pydatetime()
            if day in existing or close+timedelta(minutes=15)>now or close<datetime.fromisoformat(account[0]): continue
            try: row, missing=valuation(c,day,close)
            except ValueError as e:
                gaps.append(day); print(f'SKIPPED: {day}: {e}'); continue
            if missing: gaps.append(day); print(f'SKIPPED: {day}: missing exact post-close marks {missing}'); continue
            if apply: save(dest,row)
            count+=1
        print(f'Eligible verified closes: {count}; unresolved sessions: {len(gaps)}')
        return start,gaps


def benchmark_rows(frame, sessions):
    values={}
    for idx,v in frame.items():
        day=pd.Timestamp(idx).date().isoformat(); v=float(v)
        if day not in sessions: continue
        if day in values or not math.isfinite(v) or v<=0: raise ValueError('Invalid or duplicate SPY close')
        values[day]=v
    if set(values)!=set(sessions): raise ValueError('SPY history incomplete; existing benchmark retained')
    return sorted(values.items())


def collect_spy(dest,start,now):
    import yfinance as yf
    cal=xcals.get_calendar('XNYS'); today=now.astimezone(NY).date()
    sessions={s.date().isoformat() for s in cal.sessions_in_range(str(start),str(today)) if cal.session_close(s)+timedelta(minutes=15)<=now}
    if not sessions: raise ValueError('No completed benchmark sessions')
    frame=yf.Ticker('SPY').history(start=min(sessions),end=(today+timedelta(days=1)).isoformat(),auto_adjust=False,raise_errors=True)
    rows=benchmark_rows(frame['Adj Close'],sessions)
    # Atomic replacement only after all expected sessions validated.
    fd,tmp=tempfile.mkstemp(dir=dest.parent,prefix='spy_',suffix='.tmp')
    try:
        with os.fdopen(fd,'w',newline='',encoding='utf-8') as f:
            w=csv.writer(f); w.writerow(['session_date','adjusted_close']); w.writerows(rows)
        os.replace(tmp,dest)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
    print(f'SPY adjusted-close benchmark: {len(rows)} sessions through {rows[-1][0]}')


def main():
    p=argparse.ArgumentParser(); p.add_argument('--save',action='store_true'); p.add_argument('--skip-benchmark',action='store_true'); a=p.parse_args()
    from model2_config import get_model2_paths
    paths=get_model2_paths(); source=db_path(); dest=source.with_name('model2_performance.db'); now=datetime.now(timezone.utc)
    benchmark=source.with_name('model2_spy_benchmark.csv')
    protected={Path(paths.model1_database).resolve(),Path(paths.observation_database).resolve(),source}
    if dest.resolve() in protected or benchmark.resolve() in protected or benchmark.resolve()==dest.resolve(): raise ValueError('Output overlaps database')
    start,gaps=recover(source,dest,now,a.save)
    if a.save and not a.skip_benchmark: collect_spy(benchmark,start,now)
    if not a.save: print('PREVIEW ONLY: no database writes or market downloads')

if __name__=='__main__': main()

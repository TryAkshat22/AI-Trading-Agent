"""Read-only source valuation; --save writes only the separate performance DB."""
import argparse
import sqlite3
from contextlib import closing
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from collections import defaultdict
from pathlib import Path
import json

ACCOUNT = 'model2-paper'
ZERO = Decimal(0)

def number(value):
    x = Decimal(str(value))
    if not x.is_finite():
        raise ValueError('Nonfinite numeric value')
    return x

def timestamp(value):
    t = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if t.tzinfo is None:
        raise ValueError('Timestamp has no timezone')
    return t.astimezone(timezone.utc)

def read_only(path):
    c = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=10)
    c.execute('PRAGMA query_only=ON')
    c.execute('BEGIN')
    return c

def valuation(trades, observations, now, market_open, market_close):
    accounts = trades.execute('SELECT account_id, starting_cash FROM paper_accounts').fetchall()
    if len(accounts)!=1 or accounts[0][0]!=ACCOUNT:
        raise ValueError('Expected a single Model 2 account')
    starting = cash = number(accounts[0][1])
    if starting <= 0: raise ValueError('Invalid starting capital')
    quantities = defaultdict(Decimal)
    realized = ZERO
    last_fill = {}
    for ticker,side,qty,price,fee,pnl,created in trades.execute('SELECT ticker,side,quantity,fill_price,fees,realized_pnl,created_at_utc FROM paper_fills ORDER BY execution_session,created_at_utc,fill_id'):
        created = timestamp(created)
        if created > now: raise ValueError('Fill is in the future; retry')
        q,p,f = number(qty),number(price),number(fee or 0)
        if q<=0 or p<=0 or f<0: raise ValueError('Invalid fill')
        if side.upper()=='BUY':
            quantities[ticker]+=q; cash-=q*p+f
        elif side.upper()=='SELL':
            quantities[ticker]-=q; cash+=q*p-f; realized+=number(pnl)
        else: raise ValueError('Unknown fill side')
        if quantities[ticker]<0: raise ValueError('Negative holdings')
        last_fill[ticker]=max(created,last_fill.get(ticker,created))
    marks={}; missing=[]; mv=ZERO
    for ticker,q in sorted(quantities.items()):
        if not q: continue
        candidates=observations.execute('SELECT id,close_price,bar_start_utc,retrieved_at_utc,provider FROM intraday_observations WHERE ticker=? AND bar_start_utc>=? ORDER BY bar_start_utc DESC,retrieved_at_utc DESC,id DESC',(ticker,market_open.isoformat())).fetchall()
        for ident,price,bar,retrieved,provider in candidates:
            b,r=timestamp(bar),timestamp(retrieved)
            # Collector stores one-minute bar start; require completed bars and fresh marks.
            if not (market_open<=b and b+timedelta(minutes=1)<=min(now,market_close) and b<=r<=now and now-b<=timedelta(minutes=20) and b+timedelta(minutes=1)>=last_fill[ticker]): continue
            p=number(price)
            if p<=0: continue
            marks[ticker]={'quantity':str(q),'price':str(p),'bar_start_utc':b.isoformat(),'retrieved_at_utc':r.isoformat(),'observation_id':ident,'provider':provider}
            mv+=q*p; break
        else: missing.append(ticker)
    if missing: raise ValueError('Missing fresh completed same-session marks: '+', '.join(missing))
    equity=cash+mv
    return dict(starting_cash=str(starting),cash=str(cash),market_value=str(mv),total_equity=str(equity),realized_pnl=str(realized),unrealized_pnl=str(equity-starting-realized),total_return_pct=str((equity-starting)/starting*100),exposure_pct=str(mv/equity*100) if equity>0 else None,open_positions=len(marks),marks=marks)

def save(path, session, now, data):
    # One observation per 15-minute UTC bucket; repeated calls replace that bucket only.
    bucket=now.replace(minute=now.minute//15*15,second=0,microsecond=0).isoformat()
    with closing(sqlite3.connect(path,timeout=15)) as c, c:
        c.execute('''CREATE TABLE IF NOT EXISTS intraday_equity_snapshots(account_id TEXT NOT NULL,session_date TEXT NOT NULL,bucket_utc TEXT NOT NULL,recorded_at_utc TEXT NOT NULL,starting_cash TEXT NOT NULL,cash TEXT NOT NULL,market_value TEXT NOT NULL,total_equity TEXT NOT NULL,realized_pnl TEXT NOT NULL,unrealized_pnl TEXT NOT NULL,total_return_pct TEXT NOT NULL,exposure_pct TEXT,open_positions INTEGER NOT NULL,marks_json TEXT NOT NULL,PRIMARY KEY(account_id,bucket_utc))''')
        fields=('starting_cash','cash','market_value','total_equity','realized_pnl','unrealized_pnl','total_return_pct','exposure_pct','open_positions')
        c.execute('INSERT OR REPLACE INTO intraday_equity_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(ACCOUNT,session,bucket,now.isoformat(),*(data[k] for k in fields),json.dumps(data['marks'],sort_keys=True)))

def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--save',action='store_true'); args=parser.parse_args()
    from model2_config import get_model2_paths
    from zoneinfo import ZoneInfo
    import pandas_market_calendars as mcal
    now=datetime.now(timezone.utc)
    day=now.astimezone(ZoneInfo('America/New_York')).date().isoformat()
    schedule=mcal.get_calendar('NYSE').schedule(start_date=day,end_date=day)
    if schedule.empty:
        print('SKIPPED: no NYSE session'); return
    op=schedule.iloc[0]['market_open'].to_pydatetime(); cl=schedule.iloc[0]['market_close'].to_pydatetime()
    if not op<=now<=cl+timedelta(minutes=5):
        print('SKIPPED: outside regular session and closing grace period'); return
    paths=get_model2_paths(); source=Path(paths.model2_database).resolve(); obs=Path(paths.observation_database).resolve(); dest=source.with_name('model2_performance.db')
    if dest.resolve() in (source,obs): raise ValueError('Performance database overlaps source')
    try:
        with closing(read_only(source)) as t,closing(read_only(obs)) as o:
            data=valuation(t,o,now,op,cl)
    except ValueError as exc:
        print('SKIPPED:',exc); raise SystemExit(2)
    print('Session:',day,' | Valuation time:',now.isoformat())
    for k,v in data.items():
        if k!='marks': print(k,':',v)
    for ticker,mark in data['marks'].items(): print(ticker,mark['quantity'],mark['price'],mark['bar_start_utc'])
    if args.save:
        save(dest,day,now,data); print('Saved intraday snapshot to',dest)
    else: print('PREVIEW ONLY: no database writes.')

if __name__=='__main__': main()

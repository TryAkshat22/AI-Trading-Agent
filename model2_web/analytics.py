"""Read-only dashboard analytics; no trading or network calls."""
from contextlib import closing
from pathlib import Path
import sqlite3, json, math
import pandas as pd
import exchange_calendars as xcals
from .data import ACCOUNT

CAL=xcals.get_calendar('XNYS')
PERIODS=['1D','1W','1M','3M','YTD','ALL']

def series(data, period, end):
    end=pd.Timestamp(end).normalize()
    if period=='1D':
        rows=[r for r in data['intraday'] if r['session_date']==str(end.date())]
        points={pd.Timestamp(r['bucket_utc']).tz_convert('America/New_York'):float(r['total_equity']) for r in rows}
        idx=pd.date_range(min(points),max(points),freq='15min') if points else []
    else:
        offsets={'1W':pd.DateOffset(weeks=1),'1M':pd.DateOffset(months=1),'3M':pd.DateOffset(months=3)}
        start=end-offsets[period] if period in offsets else pd.Timestamp(year=end.year,month=1,day=1) if period=='YTD' else pd.Timestamp('1900-01-01')
        points={pd.Timestamp(r['session_date']):float(r['total_equity']) for r in data['daily'] if start<=pd.Timestamp(r['session_date'])<=end}
        idx=CAL.sessions_in_range(min(points),max(points)) if points else []
    return pd.Series(points,dtype=float).reindex(idx).sort_index()

def risk(s):
    observed=s.dropna(); returns=s.pct_change(fill_method=None).dropna()
    dd=(observed/observed.cummax()-1).min() if len(observed) else None
    return {'drawdown':dd,'volatility':returns.std()*math.sqrt(252) if len(returns)>=20 else None,'n_returns':len(returns),'missing':int(s.isna().sum())}

def ro(path):
    p=Path(path).resolve(); c=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=10); c.row_factory=sqlite3.Row; c.execute('PRAGMA query_only=ON'); return c

def positions(path, row):
    if row['source']!='intraday': return []
    with closing(ro(path)) as c:
        found=c.execute('SELECT marks_json FROM intraday_equity_snapshots WHERE account_id=? AND bucket_utc=? AND recorded_at_utc=?',(ACCOUNT,row['bucket_utc'],row['recorded_at_utc'])).fetchone()
    if not found: return []
    marks=json.loads(found[0]); result=[]
    for ticker,m in marks.items():
        q,p=float(m['quantity']),float(m['price']); value=q*p
        result.append(dict(Ticker=ticker,Shares=q,Price=p,Value=value,Weight=value/float(row['total_equity'])*100,Mark=m['bar_start_utc']))
    return sorted(result,key=lambda x:-x['Value'])

def transactions(path):
    with closing(ro(path)) as c:
        if [r[0] for r in c.execute('SELECT account_id FROM paper_accounts')]!=[ACCOUNT]: raise ValueError('Not the Model 2 trading database')
        return [dict(r) for r in c.execute('SELECT execution_session,ticker,side,quantity,fill_price,fees,realized_pnl FROM paper_fills ORDER BY execution_session DESC,created_at_utc DESC,fill_id DESC')]

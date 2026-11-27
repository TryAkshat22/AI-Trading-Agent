"""Model 2 closing equity. Preview by default; --save writes performance DB only."""
import argparse
import sqlite3
from contextlib import closing
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from collections import defaultdict
from zoneinfo import ZoneInfo
import exchange_calendars as xcals
import pandas as pd

ACCOUNT = 'model2-paper'
D = lambda x: Decimal(str(x))
ZERO = Decimal(0)
NY = ZoneInfo('America/New_York')


def valuation(conn, day, close_utc):
    account = conn.execute('SELECT starting_cash,created_at_utc FROM paper_accounts WHERE account_id=?', (ACCOUNT,)).fetchone()
    if account is None or conn.execute('SELECT COUNT(*) FROM paper_accounts').fetchone()[0] != 1:
        raise ValueError('Expected exactly one Model 2 account')
    starting = D(account[0])
    if not starting.is_finite() or starting <= 0:
        raise ValueError('Invalid starting cash')
    if datetime.fromisoformat(account[1]) > close_utc:
        raise ValueError('Account did not exist at session close')
    cash, realized = starting, ZERO
    positions = defaultdict(Decimal)
    for ticker, side, qty, price, fee, pnl, stamp in conn.execute('''SELECT ticker,side,quantity,fill_price,fees,realized_pnl,created_at_utc FROM paper_fills WHERE execution_session<=? ORDER BY execution_session,created_at_utc,fill_id''', (day,)):
        if datetime.fromisoformat(stamp) > close_utc:
            # A late persistence timestamp is not proof of execution time;
            # refuse instead of guessing whether this fill belongs at close.
            raise ValueError(f'Fill recorded after requested close: {ticker}; inspect execution lineage')
        qty, price, fee = D(qty), D(price), D(fee or 0)
        if not all(x.is_finite() for x in (qty,price,fee)) or qty<=0 or price<=0 or fee<0:
            raise ValueError(f'Invalid fill: {ticker}')
        if side.upper()=='BUY':
            cash -= qty*price+fee
            positions[ticker] += qty
        elif side.upper()=='SELL':
            if positions[ticker]<qty or pnl is None or not D(pnl).is_finite():
                raise ValueError(f'Invalid sell: {ticker}')
            cash += qty*price-fee
            positions[ticker] -= qty
            realized += D(pnl)
        else:
            raise ValueError(f'Unknown side: {side}')
    held = {t:q for t,q in positions.items() if q>0}
    marks = {}
    for ticker, price, stamp, bar_id in conn.execute('''SELECT b.ticker,b.close,r.retrieved_at_utc,b.id FROM market_bars b JOIN ingestion_runs r ON b.run_id=r.run_id AND b.ticker=r.ticker WHERE b.session_date=? AND r.safe_to_use=1 ORDER BY r.retrieved_at_utc DESC,b.id DESC''',(day,)):
        if ticker not in held or ticker in marks:
            continue
        if datetime.fromisoformat(stamp) < close_utc:
            continue
        if price is None or not D(price).is_finite() or D(price)<=0:
            raise ValueError(f'Invalid latest eligible close: {ticker}')
        marks[ticker] = (D(price),bar_id)
    missing = sorted(set(held)-set(marks))
    if missing:
        return None, missing
    mv = sum((q*marks[t][0] for t,q in held.items()),ZERO)
    equity = cash+mv
    return (ACCOUNT,day,str(starting),str(cash),str(mv),str(equity),str(realized),str(equity-starting-realized),str(equity-starting),str((equity-starting)/starting*100),len(held)), []


def save(path,row):
    with closing(sqlite3.connect(path,timeout=30)) as conn, conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS daily_equity_snapshots (
        account_id TEXT NOT NULL, session_date TEXT NOT NULL,
        starting_cash TEXT NOT NULL,cash TEXT NOT NULL,market_value TEXT NOT NULL,
        total_equity TEXT NOT NULL,realized_pnl TEXT NOT NULL,unrealized_pnl TEXT NOT NULL,
        total_pnl TEXT NOT NULL,total_return_pct TEXT NOT NULL,open_positions INTEGER NOT NULL,
        recorded_at_utc TEXT NOT NULL, PRIMARY KEY(account_id,session_date))''')
        conn.execute('''INSERT INTO daily_equity_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(account_id,session_date) DO NOTHING''', (*row,datetime.now(timezone.utc).isoformat()))
        return conn.execute('SELECT changes()').fetchone()[0]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--save',action='store_true')
    parser.add_argument('--session',help='Explicit historical session YYYY-MM-DD; defaults to today ET')
    args=parser.parse_args()
    from model2_config import get_model2_paths
    now=datetime.now(timezone.utc)
    day=args.session or now.astimezone(NY).date().isoformat()
    session=pd.Timestamp(day)
    if session.date().isoformat()!=day:
        raise ValueError('Use YYYY-MM-DD')
    cal=xcals.get_calendar('XNYS')
    if not cal.is_session(session):
        print(f'SKIPPED: {day} is not a trading session'); return
    close=cal.session_close(session).to_pydatetime().astimezone(timezone.utc)
    if now<close+timedelta(minutes=15):
        print(f'SKIPPED: {day} has not reached close plus 15 minutes'); return
    source=Path(get_model2_paths().model2_database).resolve()
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as conn:
        conn.execute('PRAGMA query_only=ON'); conn.execute('BEGIN')
        row,missing=valuation(conn,day,close)
    if missing:
        print('SKIPPED: Missing exact-session post-close retrieved marks: '+', '.join(missing)); return
    print(f'Session: {day}')
    for name,value in zip(('starting_cash','cash','market_value','total_equity','realized_pnl','unrealized_pnl','total_pnl','total_return_pct'),row[2:10]):
        print(f'{name}: {D(value):.2f}')
    print(f'open_positions: {row[10]}')
    if args.save:
        dest=source.with_name('model2_performance.db')
        print(('Saved closing snapshot to ' if save(dest,row) else 'Closing snapshot already exists in ')+str(dest))
    else:
        print('PREVIEW ONLY: no database writes.')

if __name__=='__main__':
    main()

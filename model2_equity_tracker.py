"""Model 2 daily equity backfill. Preview by default; --save writes only performance DB."""
import argparse
import sqlite3
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone

ACCOUNT = 'model2-paper'
D = lambda x: Decimal(str(x))
ZERO = Decimal(0)


def reconstruct(conn):
    account = conn.execute('SELECT starting_cash, created_at_utc FROM paper_accounts WHERE account_id=?', (ACCOUNT,)).fetchone()
    if account is None or conn.execute('SELECT COUNT(*) FROM paper_accounts').fetchone()[0] != 1:
        raise ValueError('Expected exactly one Model 2 account')
    starting = D(account[0])
    fills = conn.execute('SELECT execution_session,ticker,side,quantity,fill_price,fees,realized_pnl FROM paper_fills ORDER BY execution_session,created_at_utc,fill_id').fetchall()
    by_day = defaultdict(list)
    for f in fills:
        by_day[f[0]].append(f)
    prices = defaultdict(dict)
    # Select newest safe ingestion for each ticker/date; deterministic tie-break.
    for day,ticker,price in conn.execute('''
        WITH ranked AS (
          SELECT b.session_date,b.ticker,b.close,
          ROW_NUMBER() OVER (PARTITION BY b.session_date,b.ticker
            ORDER BY r.retrieved_at_utc DESC,b.id DESC) AS rn
          FROM market_bars b JOIN ingestion_runs r ON b.run_id=r.run_id AND b.ticker=r.ticker
          WHERE r.safe_to_use=1 AND b.session_date>=?
        ) SELECT session_date,ticker,close FROM ranked WHERE rn=1
    ''', (account[1][:10],)):
        if price is not None and D(price).is_finite() and D(price)>0:
            prices[day][ticker]=D(price)
    cash=starting
    positions=defaultdict(Decimal)
    realized=ZERO
    rows=[]
    gaps=[]
    for day in sorted(set(prices)|set(by_day)):
        for _,ticker,side,qty,price,fee,pnl in by_day[day]:
            qty,price,fee=D(qty),D(price),D(fee or 0)
            if not all(x.is_finite() for x in (qty,price,fee)) or qty<=0 or price<=0 or fee<0:
                raise ValueError(f'Invalid fill: {day} {ticker}')
            if side.upper()=='BUY':
                cash-=qty*price+fee
                positions[ticker]+=qty
            elif side.upper()=='SELL':
                if positions[ticker]<qty:
                    raise ValueError(f'Sell exceeds holdings: {day} {ticker}')
                cash+=qty*price-fee
                positions[ticker]-=qty
                if pnl is None:
                    raise ValueError(f'Missing realized P/L: {day} {ticker}')
                realized+=D(pnl)
            else:
                raise ValueError(f'Unknown side: {side}')
        held={t:q for t,q in positions.items() if q>0}
        missing=sorted(set(held)-set(prices[day]))
        if missing:
            gaps.append((day,missing))
            continue
        mv=sum((q*prices[day][t] for t,q in held.items()),ZERO)
        equity=cash+mv
        rows.append((day,starting,cash,mv,equity,realized,equity-starting,(equity-starting)/starting*100 if starting else ZERO,len(held)))
    return rows,gaps


def save(path,rows):
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS daily_equity_backfill (
          account_id TEXT NOT NULL, session_date TEXT NOT NULL,
          starting_cash TEXT NOT NULL,cash TEXT NOT NULL,market_value TEXT NOT NULL,
          total_equity TEXT NOT NULL,realized_pnl TEXT NOT NULL,total_pnl TEXT NOT NULL,
          total_return_pct TEXT NOT NULL,open_positions INTEGER NOT NULL,
          reconstructed_at_utc TEXT NOT NULL,
          PRIMARY KEY(account_id,session_date))''')
        conn.execute('DELETE FROM daily_equity_backfill WHERE account_id=?',(ACCOUNT,))
        now=datetime.now(timezone.utc).isoformat()
        conn.executemany('INSERT INTO daily_equity_backfill VALUES (?,?,?,?,?,?,?,?,?,?,?)',[(ACCOUNT,*map(str,r[:-1]),r[-1],now) for r in rows])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--save',action='store_true')
    args=parser.parse_args()
    from model2_config import get_model2_paths
    source=Path(get_model2_paths().model2_database).resolve()
    dest=source.with_name('model2_performance.db')
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as conn:
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        rows,gaps=reconstruct(conn)
    print(f'Valid daily valuations: {len(rows)}')
    print('DATE          CASH       HOLDINGS       EQUITY      RETURN')
    for day,_,cash,mv,eq,_,__,ret,___ in rows:
        print(f'{day} {cash:12.2f} {mv:12.2f} {eq:12.2f} {ret:9.2f}%')
    for day,missing in gaps:
        print(f'SKIPPED {day}: missing exact-session prices: {", ".join(missing)}')
    print('Coverage ends at last usable stored daily close; later sessions may be absent.')
    if args.save:
        if not rows: raise ValueError('No valid valuations; refusing to replace history')
        save(dest,rows)
        print(f'Saved reconstructed history to {dest}')
    else:
        print('PREVIEW ONLY: no database writes.')

if __name__=='__main__':
    main()

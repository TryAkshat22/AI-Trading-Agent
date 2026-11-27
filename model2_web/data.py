"""Shared read-only performance reader. No trading imports or writes."""
import sqlite3
from contextlib import closing
from pathlib import Path
from decimal import Decimal
from datetime import datetime, timezone
import json

ACCOUNT = 'model2-paper'
FIELDS = ('session_date','starting_cash','cash','market_value','total_equity','realized_pnl','total_return_pct','open_positions')

def load_local(path):
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError('Performance database not found; no demo fallback.')
    daily, intraday = {}, []
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=10)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table,stamp,source in [('daily_equity_backfill','reconstructed_at_utc','backfill'),('daily_equity_snapshots','recorded_at_utc','verified close'),('intraday_equity_snapshots','recorded_at_utc','intraday')]:
            if table not in tables: continue
            extra = ',bucket_utc' if source=='intraday' else ''
            for row in db.execute(f'SELECT {",".join(FIELDS)},{stamp}{extra} FROM {table} WHERE account_id=?',(ACCOUNT,)):
                item = dict(zip(FIELDS,row)); item.update(recorded_at_utc=row[8],source=source)
                if source=='intraday':
                    item['bucket_utc']=row[9]; intraday.append(item)
                else: daily[item['session_date']]=item
    return {'mode':'local','daily':sorted(daily.values(),key=lambda r:r['session_date']),'intraday':sorted(intraday,key=lambda r:r['bucket_utc'])}

def load_demo():
    data=json.loads(Path(__file__).with_name('demo.json').read_text(encoding='utf-8'))
    if data['mode']!='demo': raise ValueError('Invalid demo dataset')
    return data

def latest(data):
    # Daily snapshot recording time can be much later than its valuation date.
    candidates=[*data['daily'],*data['intraday']]
    return max(candidates,key=lambda r:(r['session_date'],r['source']!='intraday',r.get('bucket_utc','')),default=None)

def period_return(rows):
    if len(rows)<2: return None
    a,b=Decimal(str(rows[0]['total_equity'])),Decimal(str(rows[-1]['total_equity']))
    return (b/a-1)*100 if a>0 else None

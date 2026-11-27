import sqlite3
from model2_web.data import load_local,load_demo,latest,period_return

def test_demo():
    data=load_demo(); assert data['mode']=='demo'; assert latest(data)['session_date']=='2026-01-15'; assert period_return(data['daily']) is not None

def test_missing(tmp_path):
    import pytest
    p=tmp_path/'absent.db'
    with pytest.raises(FileNotFoundError): load_local(p)
    assert not p.exists()

def test_daily_precedence(tmp_path):
    p=tmp_path/'performance.db'
    fields='account_id TEXT,session_date TEXT,starting_cash TEXT,cash TEXT,market_value TEXT,total_equity TEXT,realized_pnl TEXT,total_return_pct TEXT,open_positions INTEGER'
    with sqlite3.connect(p) as c:
        c.execute(f'CREATE TABLE daily_equity_backfill({fields},reconstructed_at_utc TEXT)')
        c.execute(f'CREATE TABLE daily_equity_snapshots({fields},recorded_at_utc TEXT)')
        for table,val in [('daily_equity_backfill','100'),('daily_equity_snapshots','101')]:
            c.execute(f'INSERT INTO {table} VALUES (?,?,?,?,?,?,?,?,?,?)',('model2-paper','2026-11-19','100','100','1',val,'0','1',1,'2026-11-25T20:00:00+00:00'))
    before=p.read_bytes(); data=load_local(p); assert len(data['daily'])==1; assert latest(data)['total_equity']=='101'; assert p.read_bytes()==before

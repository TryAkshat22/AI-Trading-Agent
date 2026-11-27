from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import json
import pandas as pd
import pytest
from model2_reliability.runner import gate, prior_execution_block
from model2_reliability.maintenance import benchmark_rows, recover
from model2_reliability.health import audit, closing_coverage


def t(s): return datetime.fromisoformat(s+'-05:00')

@pytest.mark.parametrize('task,stamp,allowed',[
 ('execution','2026-11-27T09:44:00',False),('execution','2026-11-27T09:45:00',True),
 ('execution','2026-11-27T12:29:59',True),('execution','2026-11-27T12:30:00',False),
 ('execution','2026-11-25T15:30:00',False),('execution','2026-11-26T10:00:00',False),
 ('decision','2026-11-27T13:14:59',False),('decision','2026-11-27T13:15:00',True),
 ('closing','2026-11-25T16:15:00',True),('snapshot','2026-11-27T13:06:00',False),
 ('cleanup','2026-11-26T20:00:00',True)])
def test_gate(task,stamp,allowed): assert (gate(task,t(stamp)) is None)==allowed


def test_benchmark_coverage():
    s=pd.Series([100,101,999],index=pd.to_datetime(['2026-11-25','2026-11-27','2026-11-28']))
    assert benchmark_rows(s,{'2026-11-25','2026-11-27'})==[('2026-11-25',100),('2026-11-27',101)]
    with pytest.raises(ValueError): benchmark_rows(s,{'2026-11-24','2026-11-25'})


def test_failure_hold(tmp_path):
    logs=tmp_path/'logs'; logs.mkdir(); f=logs/'model2_execution_outcomes.jsonl'
    f.write_text(json.dumps({'started_at':'2026-11-27T15:00:00+00:00','status':'BLOCKED_OR_FAILED'})+'\n')
    assert prior_execution_block('2026-11-27',tmp_path)
    assert not prior_execution_block('2026-11-30',tmp_path)


def test_health_cutoff(tmp_path):
    db=tmp_path/'trade.db'
    with sqlite3.connect(db) as c:
        c.executescript("CREATE TABLE paper_accounts(account_id TEXT); INSERT INTO paper_accounts VALUES ('model2-paper'); CREATE TABLE paper_orders(order_id TEXT,execution_session TEXT,ticker TEXT,side TEXT,quantity INT,status TEXT,model_version TEXT); CREATE TABLE order_rejections(order_id TEXT,rejection_code TEXT); INSERT INTO paper_orders VALUES('a','2026-11-27','AVGO','SELL',2,'PENDING','model-2-flexible');")
    assert not audit(db,t('2026-11-27T12:29:00'),tmp_path)['unfilled_past_window']
    assert len(audit(db,t('2026-11-27T12:30:00'),tmp_path)['unfilled_past_window'])==1
    with sqlite3.connect(db) as c:
        c.executescript("UPDATE paper_orders SET status='REJECTED'; INSERT INTO order_rejections VALUES('a','EXECUTION_WINDOW_EXPIRED');")
    assert audit(db,t('2026-11-27T12:30:00'),tmp_path)['unfilled_past_window'][0]['rejection_code']=='EXECUTION_WINDOW_EXPIRED'


def test_recovery_non_destructive(tmp_path):
    source=tmp_path/'trade.db'; dest=tmp_path/'performance.db'
    with sqlite3.connect(source) as c:
        c.executescript("""CREATE TABLE paper_accounts(account_id TEXT,starting_cash TEXT,created_at_utc TEXT);
        INSERT INTO paper_accounts VALUES ('model2-paper','10000','2026-11-25T14:00:00+00:00');
        CREATE TABLE paper_fills(execution_session TEXT,ticker TEXT,side TEXT,quantity INT,fill_price TEXT,fees TEXT,realized_pnl TEXT,created_at_utc TEXT,fill_id TEXT);
        CREATE TABLE market_bars(ticker TEXT,close TEXT,id INT,run_id TEXT,session_date TEXT);
        CREATE TABLE ingestion_runs(run_id TEXT,ticker TEXT,retrieved_at_utc TEXT,safe_to_use INT);""")
    before=source.read_bytes(); now=t('2026-11-27T14:00:00')
    recover(source,dest,now,False); assert not dest.exists()
    recover(source,dest,now,True); original=dest.read_bytes()
    recover(source,dest,now,True); assert dest.read_bytes()==original and source.read_bytes()==before
    with sqlite3.connect(dest) as c: assert c.execute('SELECT count(*) FROM daily_equity_snapshots').fetchone()[0]==2


def test_closing_coverage_includes_trailing_gaps():
    result=closing_coverage([{'session_date':'2026-11-25'}],t('2026-11-27T13:16:00'))
    assert result['missing_sessions']==['2026-11-27']
    assert result['last_expected_close']=='2026-11-27'


def test_interrupted_execution_hold(tmp_path):
    logs=tmp_path/'logs'; logs.mkdir(); f=logs/'model2_execution_outcomes.jsonl'
    entry={'started_at':'2026-11-27T15:00:00+00:00','status':'STARTED'}
    f.write_text(json.dumps(entry)+'\n')
    assert prior_execution_block('2026-11-27',tmp_path)
    with f.open('a') as out: out.write(json.dumps(dict(entry,status='SUCCESS'))+'\n')
    assert not prior_execution_block('2026-11-27',tmp_path)


def test_precheck_existing_schema(tmp_path):
    from model2_reliability import runner
    db=tmp_path/'trade.db'
    with sqlite3.connect(db) as c:
        c.executescript("""CREATE TABLE paper_accounts(account_id TEXT); INSERT INTO paper_accounts VALUES ('model2-paper');
        CREATE TABLE paper_orders(model_version TEXT,execution_session TEXT,status TEXT);
        INSERT INTO paper_orders VALUES('model-2-flexible','2026-11-27','PENDING');
        CREATE TABLE model2_decision_runs(decision_session TEXT,model_version TEXT,status TEXT);
        INSERT INTO model2_decision_runs VALUES('2026-11-25','model-2-flexible','COMPLETED');
        INSERT INTO model2_decision_runs VALUES('2026-11-26','model-2-flexible','FAILED');""")
    def precheck(task,day): return runner.precheck_db(task,day,db,'model-2-flexible','model2-paper')
    before=db.read_bytes()
    assert precheck('execution','2026-11-27') is None
    assert precheck('execution','2026-11-30')=='No pending orders for today'
    assert precheck('decision','2026-11-25')=='Decision ledger already completed'
    with pytest.raises(RuntimeError): precheck('decision','2026-11-26')
    assert db.read_bytes()==before

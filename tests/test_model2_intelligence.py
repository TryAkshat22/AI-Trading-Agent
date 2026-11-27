import json
import sqlite3
import pandas as pd
import pytest
from model2_intelligence.metrics import risk_metrics,compare
from model2_intelligence.benchmark import read_benchmark
from model2_intelligence.service import Intelligence
from model2_web.analytics import series


def test_demo_separation():
    svc=Intelligence('demo', performance_path='nonexistent.db',benchmark_path='nonexistent.csv',benchmark_label='SPY')
    p=svc.get_portfolio(); assert p['synthetic'] and p['holdings'] is None
    perf=svc.get_performance(); assert perf['metrics']['last_session']=='2026-01-14'
    assert p['valuation']['session_date']=='2026-01-15'
    assert perf['metrics']['period_return']==pytest.approx(.021)
    assert svc.get_benchmark()['status']=='unavailable'
    assert svc.get_trade_history()['status']=='unavailable'
    assert svc.get_signals()['status']=='unavailable'
    json.dumps(perf,allow_nan=False)


def test_gaps_not_daily_returns():
    s=pd.Series([100.,None,110.,99.],index=pd.date_range('2026-01-05',periods=4))
    r=risk_metrics(s,0)
    assert r['n_returns']==1 and r['missing']==1
    assert r['drawdown']==pytest.approx(-.1)
    assert r['volatility'] is None and r['sharpe'] is None
    assert r['period_return']==pytest.approx(-.01)


def test_risk_known_returns():
    returns=pd.Series([.02,-.01]*12)
    s=pd.Series([100.,*(100*(1+returns).cumprod())],index=pd.date_range('2026-01-01',periods=25))
    r=risk_metrics(s,0)
    assert r['volatility']==pytest.approx(returns.std()*252**.5)
    assert r['sharpe']==pytest.approx(returns.mean()/returns.std()*252**.5)
    assert r['sortino']==pytest.approx(returns.mean()/((returns.clip(upper=0)**2).mean()**.5)*252**.5)
    assert risk_metrics(s)['sharpe'] is None


def test_benchmark_alignment():
    b=pd.Series([100.,*(100*(1+pd.Series([.01,-.005]*12)).cumprod())],index=pd.date_range('2026-01-01',periods=25))
    p=pd.Series([100.,*(100*(1+pd.Series([.02,-.01]*12)).cumprod())],index=b.index)
    result=compare(p,b,0)
    assert result['beta']==pytest.approx(2.) and result['annualized_alpha']==pytest.approx(0.,abs=1e-10)
    b.iloc[5]=float('nan'); assert compare(p,b)['paired_daily_returns']==22


def test_benchmark_csv_validation(tmp_path):
    f=tmp_path/'b.csv'; f.write_text('session_date,adjusted_close\n2026-01-05,100\n2026-01-06,101\n')
    assert len(read_benchmark(f))==2
    f.write_text('session_date,adjusted_close\n2026-01-05,100\n2026-01-05,101\n')
    with pytest.raises(ValueError): read_benchmark(f)


def test_missing_no_fallback(tmp_path):
    p=tmp_path/'absent.db'; svc=Intelligence('local',p)
    with pytest.raises(FileNotFoundError): svc.get_portfolio()
    assert not p.exists()


def test_read_only(tmp_path):
    p=tmp_path/'performance.db'
    with sqlite3.connect(p) as c:
        c.execute('CREATE TABLE daily_equity_snapshots(account_id TEXT,session_date TEXT,starting_cash TEXT,cash TEXT,market_value TEXT,total_equity TEXT,realized_pnl TEXT,total_return_pct TEXT,open_positions INTEGER,recorded_at_utc TEXT)')
        for day,val in [('2026-01-05','100'),('2026-01-07','101')]:
            c.execute('INSERT INTO daily_equity_snapshots VALUES (?,?,?,?,?,?,?,?,?,?)',('model2-paper',day,'100',val,'0',val,'0','0',0,day+'T22:00:00+00:00'))
    before=p.read_bytes(); svc=Intelligence('local',p)
    assert svc.get_portfolio()['synthetic'] is False
    assert svc.get_performance()['metrics']['missing']==1
    assert svc.get_risk_metrics()['metrics']['n_returns']==0
    assert p.read_bytes()==before


def test_empty_and_bad_input():
    s=series({'daily':[],'intraday':[]},'ALL','2026-01-15')
    assert risk_metrics(s)['drawdown'] is None
    with pytest.raises(ValueError): Intelligence().get_performance('1D')
    with pytest.raises(ValueError): Intelligence().get_trade_history(-1)
    with pytest.raises(ValueError): risk_metrics(pd.Series([0.],index=pd.date_range('2026-01-01',periods=1)))


def test_wrong_trading_account(tmp_path):
    p=tmp_path/'wrong.db'
    with sqlite3.connect(p) as c:
        c.execute('CREATE TABLE paper_accounts(account_id TEXT)'); c.execute("INSERT INTO paper_accounts VALUES ('model1-paper')")
    with pytest.raises(ValueError): Intelligence('local',tmp_path/'other.db',p).get_trade_history()

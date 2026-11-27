"""Metrics on an exchange-session-indexed closing equity series.
Returns and volatility are decimal fractions, not percentage points.
"""
import math
import pandas as pd


def finite(value):
    return float(value) if value is not None and math.isfinite(float(value)) else None


def risk_metrics(s, annual_rf=None):
    if annual_rf is not None and (not math.isfinite(annual_rf) or annual_rf <= -1):
        raise ValueError('Invalid annual risk-free rate')
    s = s.astype(float).sort_index()
    obs = s.dropna()
    if not obs.map(lambda x: math.isfinite(x) and x > 0).all():
        raise ValueError('Nonpositive or invalid equity')
    r = s.pct_change(fill_method=None).dropna()
    n = len(r)
    vol = r.std(ddof=1) if n >= 20 else None
    sharpe = sortino = None
    if n >= 20 and annual_rf is not None:
        rf = (1 + annual_rf)**(1/252)-1
        excess = r-rf
        downside = math.sqrt((excess.clip(upper=0)**2).mean())
        if vol and vol > 0: sharpe = excess.mean()/vol*math.sqrt(252)
        if downside > 0: sortino = excess.mean()/downside*math.sqrt(252)
    return dict(drawdown=finite((obs/obs.cummax()-1).min()) if len(obs) else None,
                volatility=finite(vol*math.sqrt(252)) if vol is not None else None,
                n_returns=n, missing=int(s.isna().sum()),
                sharpe=finite(sharpe), sortino=finite(sortino), annual_rf=annual_rf,
                period_return=finite(obs.iloc[-1]/obs.iloc[0]-1) if len(obs)>1 else None,
                first_session=str(obs.index[0].date()) if len(obs) else None,
                last_session=str(obs.index[-1].date()) if len(obs) else None,
                observations=len(obs),
                method='252 sessions; sample SD; adjacent returns only; observed drawdown may miss intervening losses; minimum 20 returns for volatility and ratios')


def compare(s, benchmark, annual_rf=None):
    """Benchmark is a positive level series on the same session index."""
    if annual_rf is not None and (not math.isfinite(annual_rf) or annual_rf <= -1):
        raise ValueError('Invalid annual risk-free rate')
    b = benchmark.reindex(s.index)
    for v in (s,b):
        if not v.dropna().map(lambda x: math.isfinite(x) and x>0).all():
            raise ValueError('Invalid equity or benchmark level')
    common = pd.concat([s.rename('p'),b.rename('b')],axis=1).dropna()
    pairs = pd.concat([s.pct_change(fill_method=None).rename('p'),b.pct_change(fill_method=None).rename('b')],axis=1).dropna()
    beta = alpha = None
    if len(pairs)>=20 and pairs.b.var(ddof=1)>0:
        beta = finite(pairs.p.cov(pairs.b)/pairs.b.var(ddof=1))
        if annual_rf is not None and beta is not None:
            rf=(1+annual_rf)**(1/252)-1
            alpha=finite(252*((pairs.p-rf).mean()-beta*(pairs.b-rf).mean()))
    p=bret=None
    if len(common)>=2:
        p=finite(common.p.iloc[-1]/common.p.iloc[0]-1)
        bret=finite(common.b.iloc[-1]/common.b.iloc[0]-1)
    return dict(portfolio_return=p, benchmark_return=bret, excess_return=finite(p-bret) if p is not None and bret is not None else None,
                beta=beta, annualized_alpha=alpha, annual_rf=annual_rf, paired_daily_returns=len(pairs),
                common_observations=len(common), first_session=str(common.index[0].date()) if len(common) else None,
                last_session=str(common.index[-1].date()) if len(common) else None,
                method='Common endpoints for cumulative returns; adjacent paired daily returns for beta; arithmetic annualized Jensen alpha; minimum 20 paired returns')

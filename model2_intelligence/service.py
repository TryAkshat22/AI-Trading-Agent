"""Fixed, read-only analytical interface for local UI and MCP.
No caller-provided paths, SQL, commands, or trading operations.
"""
import os
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
import math
from model2_web.data import load_local,load_demo,latest
from model2_web.analytics import series,positions,transactions
from model2_universe import MODEL2_GROUPS
from .metrics import risk_metrics,compare
from .benchmark import read_benchmark


class Intelligence:
    def __init__(self, mode='demo', performance_path=None, trading_path=None, benchmark_path=None, benchmark_label=None, annual_rf=None):
        if mode not in ('demo','local'): raise ValueError('Invalid mode')
        if mode=='local' and not performance_path: raise ValueError('Set MODEL2_PERFORMANCE_DB')
        self.mode=mode; self.path=performance_path; self.trading_path=trading_path
        self.benchmark_path=benchmark_path; self.benchmark_label=benchmark_label; self.annual_rf=annual_rf

    @classmethod
    def from_env(cls):
        mode=os.getenv('MODEL2_WEB_MODE','demo'); path=os.getenv('MODEL2_PERFORMANCE_DB')
        trading=os.getenv('PAPER_TRADING_MODEL2_DB_PATH') or (str(Path(path).with_name('trading_agent_model2.db')) if path else None)
        rf=os.getenv('MODEL2_ANNUAL_RF')
        benchmark=os.getenv('MODEL2_BENCHMARK_CSV'); label=os.getenv('MODEL2_BENCHMARK_LABEL')
        if mode=='local' and trading and not benchmark:
            candidate=Path(trading).with_name('model2_spy_benchmark.csv')
            if candidate.is_file(): benchmark=str(candidate); label='SPY adjusted close (Yahoo Finance)'
        return cls(mode,path,trading,benchmark,label,float(rf) if rf is not None else None)

    def data(self):
        return load_demo() if self.mode=='demo' else load_local(self.path)

    def envelope(self, payload):
        return dict(mode=self.mode,synthetic=self.mode=='demo',generated_at_utc=datetime.now(timezone.utc).isoformat(),**payload)

    def get_portfolio(self):
        row=latest(self.data())
        if row is None: return self.envelope(dict(status='unavailable',reason='No saved valuations'))
        equity=Decimal(str(row['total_equity'])); invested=Decimal(str(row['market_value']))
        if equity<=0 or not equity.is_finite(): raise ValueError('Invalid equity')
        holdings=None; groups=None; reason='Position marks unavailable for this valuation'
        if self.mode=='local' and row['source']=='intraday':
            found=positions(self.path,row)
            if len(found)==int(row['open_positions']) and abs(sum(x['Value'] for x in found)-float(invested))<=0.02:
                holdings=found; groups={}; reason=None
                for x in holdings:
                    group=MODEL2_GROUPS.get(x['Ticker'],'Unclassified')
                    groups[group]=groups.get(group,0)+x['Weight']
        return self.envelope(dict(status='ok',valuation=row, exposure_pct=float(invested/equity*100),holdings=holdings,group_weights_pct=groups,holdings_note=reason,
                                  note='Saved valuation, not a live quote; group weights are percentages of equity'))

    def _closing(self, period):
        if period not in ('1W','1M','3M','YTD','ALL'): raise ValueError('Closing periods only')
        d=self.data(); row=latest(d)
        return d,series(d,period,row['session_date']) if row else series(d,period,'2000-01-01')

    def get_performance(self, period='ALL'):
        d,s=self._closing(period); obs=s.dropna(); r=risk_metrics(s,self.annual_rf)
        sources={x['session_date']:x['source'] for x in d['daily']}
        points=[dict(session_date=str(k.date()),equity=float(v),source=sources[str(k.date())]) for k,v in obs.items()]
        return self.envelope(dict(status='ok' if points else 'unavailable',period=period,metrics=r,points=points[-260:],points_truncated=len(points)>260,
                                  latest_valuation_session=(latest(d) or {}).get('session_date'),note='Closing observations only; metrics cover full selected period, not just returned points'))

    def get_risk_metrics(self, period='ALL'):
        d,s=self._closing(period)
        return self.envelope(dict(status='ok' if s.notna().any() else 'unavailable',period=period,metrics=risk_metrics(s,self.annual_rf)))

    def get_benchmark(self, period='ALL'):
        if self.mode=='demo' or not self.benchmark_path or not self.benchmark_label:
            return self.envelope(dict(status='unavailable',reason='No separately labeled actual benchmark configured; demo never mixes with actual prices'))
        _,s=self._closing(period); b=read_benchmark(self.benchmark_path)
        # Match calendar timezone convention used by the installed calendar library.
        if s.index.tz is not None: b.index=b.index.tz_localize(s.index.tz)
        result=compare(s,b,self.annual_rf)
        return self.envelope(dict(status='ok' if result['common_observations']>=2 else 'unavailable',benchmark=self.benchmark_label,metrics=result,note='Adjusted-close series; provider or user-supplied provenance not independently verified'))

    def get_trade_history(self, limit=25):
        if type(limit) is not int or not 1<=limit<=100: raise ValueError('Limit must be 1–100')
        if self.mode!='local' or not self.trading_path: return self.envelope(dict(status='unavailable',reason='No local trade ledger configured'))
        return self.envelope(dict(status='ok',fills=transactions(self.trading_path,limit=limit),note='Executed fills only; not pending signals'))

    def get_system_health(self):
        d=self.data(); row=latest(d)
        ops=None
        if self.mode=='local' and self.trading_path:
            try:
                from model2_reliability.health import audit, closing_coverage
                ops=audit(self.trading_path)
                ops['closing_coverage']=closing_coverage(d['daily'])
            except Exception as exc: ops={'status':'unavailable','reason':type(exc).__name__}
        return self.envelope(dict(status='ok' if row else 'unavailable',latest_valuation=row,daily_count=len(d['daily']),intraday_count=len(d['intraday']),operations=ops,note='Saved record coverage and local outcome logs do not prove scheduler uptime'))

    def get_signals(self):
        return self.envelope(dict(status='unavailable',reason='No persisted signal export integrated. No strategy scan invoked.'))

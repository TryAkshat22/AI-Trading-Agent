"""Read-only local operational diagnostics; no task launching."""
import json
from contextlib import closing
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sqlite3
import exchange_calendars as xcals
import pandas as pd
from .runner import ROOT, NY, COMMANDS


def audit(path, now=None, root=ROOT):
    now=now or datetime.now(timezone.utc); today=now.astimezone(NY).date().isoformat()
    cal=xcals.get_calendar('XNYS'); session=pd.Timestamp(today)
    past_cutoff=not cal.is_session(session) or now>=cal.session_close(session)-timedelta(minutes=30)
    cutoff=today if past_cutoff else (pd.Timestamp(today)-pd.Timedelta(days=1)).date().isoformat()
    outcomes={}
    for task in COMMANDS:
        file=root/'logs'/f'model2_{task}_outcomes.jsonl'
        if not file.exists(): outcomes[task]={'status':'UNAVAILABLE'}; continue
        try:
            rows=[json.loads(line) for line in file.read_text(encoding='utf-8').splitlines() if line.strip()]
            last=rows[-1] if rows else None
            meaningful=next((r for r in reversed(rows) if r['status']!='SKIP'),None)
            outcomes[task]={'status':last['status'] if last else 'UNAVAILABLE','last_outcome':last,'last_non_skip':meaningful}
        except (ValueError,KeyError,IndexError,OSError): outcomes[task]={'status':'UNREADABLE'}
    path=Path(path).resolve()
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=10)) as c:
        c.execute('PRAGMA query_only=ON')
        if [x[0] for x in c.execute('SELECT account_id FROM paper_accounts')]!=['model2-paper']: raise ValueError('Not Model 2 account')
        rows=c.execute("SELECT o.execution_session,o.ticker,o.side,o.quantity,o.status,r.rejection_code FROM paper_orders o LEFT JOIN order_rejections r ON o.order_id=r.order_id WHERE o.model_version='model-2-flexible' AND o.execution_session<=? AND (o.status='PENDING' OR (o.status='REJECTED' AND r.rejection_code='EXECUTION_WINDOW_EXPIRED')) ORDER BY o.execution_session DESC,o.ticker LIMIT 100",(cutoff,)).fetchall()
    return {'as_of':now.isoformat(),'task_outcomes':outcomes,'unfilled_past_window':[dict(zip(('execution_session','ticker','side','quantity','status','rejection_code'),r)) for r in rows],'note':'Pending/expired orders past execution cutoff, up to 100. Logs indicate recorded outcomes, not proof of scheduler uptime.'}


def closing_coverage(daily, now=None):
    now=now or datetime.now(timezone.utc); today=now.astimezone(NY).date()
    if not daily: return {'status':'unavailable','reason':'No closing history'}
    cal=xcals.get_calendar('XNYS'); existing={row['session_date'] for row in daily}
    expected=[s.date().isoformat() for s in cal.sessions_in_range(min(existing),str(today)) if cal.session_close(s)+timedelta(minutes=15)<=now]
    missing=[d for d in expected if d not in existing]
    return {'status':'incomplete' if missing else 'ok','last_expected_close':expected[-1] if expected else None,'last_recorded_close':max(existing),'missing_sessions':missing}

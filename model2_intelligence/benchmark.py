"""Explicit, offline benchmark import; no quote fetching or writes."""
import csv
from pathlib import Path
import math
import pandas as pd
from datetime import date


def read_benchmark(path):
    levels={}
    with Path(path).open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        if reader.fieldnames != ['session_date','adjusted_close']:
            raise ValueError('Expected session_date,adjusted_close CSV')
        for row in reader:
            day=date.fromisoformat(row['session_date']); v=float(row['adjusted_close'])
            if day in levels or not math.isfinite(v) or v<=0: raise ValueError('Duplicate date or invalid benchmark level')
            levels[day]=v
    return pd.Series(list(levels.values()),index=pd.DatetimeIndex(list(levels)),dtype=float).sort_index()

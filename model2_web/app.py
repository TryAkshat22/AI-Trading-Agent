import os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from model2_web.data import load_local,load_demo,latest
from model2_web.analytics import PERIODS,series,risk,positions,transactions

st.set_page_config(page_title='Model 2 | Portfolio Intelligence',page_icon='📈',layout='wide')
st.markdown('''<style>
.stApp {background:#0b1220;color:#e5edf8} [data-testid="stSidebar"] {background:#101a2b} .block-container {padding-top:2rem;max-width:1450px} [data-testid="stMetric"] {background:#121e30;border:1px solid #26364c;border-radius:12px;padding:16px} [data-testid="stMetricLabel"] {color:#a4b4ca} h1,h2,h3 {letter-spacing:-.035em} [data-testid="stSidebar"] h1 {font-size:1.45rem} </style>''',unsafe_allow_html=True)
mode=os.environ.get('MODEL2_WEB_MODE','demo'); path=os.environ.get('MODEL2_PERFORMANCE_DB')
try:
    if mode=='local':
        if not path: raise ValueError('Set MODEL2_PERFORMANCE_DB')
        data=load_local(path)
    elif mode=='demo': data=load_demo()
    else: raise ValueError('Unknown mode')
except Exception as e: st.error(f'Data unavailable: {e}'); st.stop()
row=latest(data)
if not row: st.warning('No saved valuations'); st.stop()
trade_path=Path(path).with_name('trading_agent_model2.db') if mode=='local' else None
st.sidebar.title('MODEL 2')
st.sidebar.caption('PORTFOLIO INTELLIGENCE')
page=st.sidebar.radio('Workspace',['Overview','Portfolio','Markets','Signals','Analytics','Transactions','AI Analyst','System Health'],label_visibility='collapsed')
st.sidebar.divider(); st.sidebar.caption('PAPER TRADING / READ ONLY'); st.sidebar.button('Refresh data')
st.title(page)
if mode=='demo': st.warning('DEMO · Synthetic data only. Not actual portfolio results.')
else: st.caption('LOCAL WORKSPACE · Saved paper-trading valuations · Read only')
def money(x): return f'${float(x):,.2f}'
def stamp(x): return pd.Timestamp(x).tz_convert('America/New_York').strftime('%b %d, %Y · %I:%M %p ET')
def metrics():
    a,b,c,d=st.columns(4); a.metric('Portfolio equity',money(row['total_equity']),f"{float(row['total_return_pct']):+.2f}% all time"); b.metric('Cash',money(row['cash'])); c.metric('Invested',money(row['market_value'])); d.metric('Open positions',row['open_positions']); st.caption(f"Saved {row['source']} | Session {row['session_date']} | Recorded {stamp(row['recorded_at_utc'])}")
def chart(period):
    s=series(data,period,row['session_date']); obs=s.dropna()
    if obs.empty: st.info('No saved valuations in this period.'); return
    change=(obs.iloc[-1]/obs.iloc[0]-1)*100 if len(obs)>1 and obs.iloc[0]>0 else None
    st.metric('Recorded period change',f'{change:+.2f}%' if change is not None else 'N/A')
    color='#35d5a0' if change is None or change>=0 else '#fb7185'
    fig=go.Figure(go.Scatter(x=s.index,y=s,mode='lines+markers',connectgaps=False,line=dict(color=color,width=2.5),marker=dict(size=5),hovertemplate='%{x}<br>$%{y:,.2f}<extra></extra>'))
    fig.update_layout(height=360,paper_bgcolor='#0b1220',plot_bgcolor='#0b1220',font_color='#a4b4ca',margin=dict(l=10,r=15,t=12,b=15),yaxis=dict(tickprefix='$',tickformat=',.0f',gridcolor='#26364c'),xaxis=dict(showgrid=False),showlegend=False)
    if period!='1D': fig.update_xaxes(rangebreaks=[dict(bounds=['sat','mon'])])
    st.plotly_chart(fig,use_container_width=True,config={'displaylogo':False,'displayModeBar':False})
    st.caption(f'{len(obs)} saved points · {int(s.isna().sum())} missing internal intervals · No fabricated prices. Lines connect adjacent recorded intervals only.')
    if period!='1D' and obs.index[-1].date().isoformat()<row['session_date']: st.warning(f"Closing history ends {obs.index[-1].date()}; latest valuation is {row['session_date']}. Current intraday equity is not a closing value.")
    if period=='1D': st.caption('Intraday chart uses 15-minute bucket times in Eastern Time, not exact recording times.')
def allocation():
    st.subheader('Capital allocation'); fig=go.Figure(go.Pie(labels=['Invested','Cash'],values=[float(row['market_value']),float(row['cash'])],hole=.72,marker_colors=['#36bfae','#334765'],textinfo='percent')); fig.update_layout(height=260,margin=dict(l=0,r=0,t=10,b=10),paper_bgcolor='#0b1220',font_color='#a4b4ca',legend=dict(orientation='h')); st.plotly_chart(fig,use_container_width=True,config={'displayModeBar':False})
def local_agent_data():
    if mode!='local': st.info('This workspace requires local Model 2 data. Demo mode does not invent market signals.'); return None
    try:
        import model2_agent_data as a
        return a
    except Exception as e: st.warning(f'Local integration unavailable: {e}'); return None
if page=='Overview':
    metrics(); left,right=st.columns([2.4,1]);
    with left:
        st.subheader('Equity curve'); period=st.radio('Period',PERIODS,index=5,horizontal=True); chart(period)
    with right: allocation()
    st.subheader('Latest closing records'); st.dataframe(pd.DataFrame(data['daily'][-5:])[['session_date','total_equity','source']] if data['daily'] else pd.DataFrame(),hide_index=True,use_container_width=True)
elif page=='Portfolio':
    metrics(); allocation()
    if mode=='local':
        try:
            rows=positions(path,row)
            if rows: st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True,column_config={'Price':st.column_config.NumberColumn(format='$%.2f'),'Value':st.column_config.NumberColumn(format='$%.2f'),'Weight':st.column_config.NumberColumn(format='%.2f%%')})
            else: st.info('Position-level marks are available only for a saved intraday valuation.')
        except Exception as e: st.warning(f'Position details unavailable: {e}')
    else: st.info('Demo dataset contains account totals only.')
elif page=='Markets':
    a=local_agent_data()
    if a:
        try:
            m=a.market_movers(); st.caption(m['message']); x,y,z=st.columns(3); x.metric('Advancing',m['positive']); y.metric('Declining',m['negative']); z.metric('Coverage',f"{m['covered']}/{m['universe_count']}")
            for col,key in zip(st.columns(2),['gainers','losers']):
                with col:
                    st.subheader(key.title()); st.dataframe(pd.DataFrame(m[key]),hide_index=True,use_container_width=True) if m[key] else st.info('No eligible records.')
        except Exception as e: st.warning(f'Market data unavailable: {e}')
elif page=='Signals':
    st.info('Strategy signal scan is not automatically invoked by the web app. This page will show persisted signal rankings once a read-only signal export is available. No orders are created here.')
elif page=='Analytics':
    st.subheader('Historical risk'); s=series(data,'ALL',row['session_date']); r=risk(s); a,b,c=st.columns(3); a.metric('Observed max drawdown',f"{r['drawdown']:.2%}" if r['drawdown'] is not None else 'N/A'); b.metric('Annualized volatility',f"{r['volatility']:.2%}" if r['volatility'] is not None else 'N/A'); c.metric('Adjacent daily returns',r['n_returns']); st.caption('Volatility requires at least 20 adjacent daily returns; drawdown uses observed closes and may understate losses during missing sessions.'); chart('ALL'); st.info('Benchmark comparison and risk-adjusted ratios require aligned benchmark and risk-free data; not yet connected.')
elif page=='Transactions':
    if mode=='local':
        try: st.dataframe(pd.DataFrame(transactions(trade_path)),hide_index=True,use_container_width=True)
        except Exception as e: st.warning(f'Transactions unavailable: {e}')
    else: st.info('No synthetic trade ledger supplied.')
elif page=='AI Analyst':
    st.info('Local scripted analyst · Not an LLM. GitHub Copilot profile is separate; authenticated remote access is not configured.')
    q=st.selectbox('Ask about your account',['Portfolio summary','Historical performance','Risk and coverage'])
    if q=='Portfolio summary': st.write(f"Saved equity {money(row['total_equity'])}, cash {money(row['cash'])}, {row['open_positions']} open positions. Recorded {stamp(row['recorded_at_utc'])}.")
    elif q=='Historical performance': chart('ALL')
    else: st.write(risk(series(data,'ALL',row['session_date'])))
    st.markdown('[Open GitHub Copilot Agents](https://github.com/copilot/agents)')
else:
    metrics(); st.write(f"Daily records: {len(data['daily'])} | Intraday records: {len(data['intraday'])}")
    st.caption('Saved valuation timestamps are evidence of data collection, not proof of task health.')
    if mode=='local' and st.button('Inspect Windows scheduled tasks'):
        a=local_agent_data()
        if a:
            try: st.dataframe(pd.DataFrame([{'task':k,**(v or {'State':'UNKNOWN'})} for k,v in a.all_task_statuses().items()]),hide_index=True)
            except Exception as e: st.warning(str(e))
    with st.expander('Valuation records'): st.dataframe(pd.DataFrame(data['daily']),hide_index=True); st.dataframe(pd.DataFrame(data['intraday']),hide_index=True)

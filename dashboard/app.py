"""
Dashboard Streamlit — Panel de control del Trading Agent.
Muestra portfolio, trades, señales e IA analysis.
Ejecutar: streamlit run dashboard/app.py --server.port 8501
"""
import os
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

sys.path.insert(0, '/opt/trading')
load_dotenv('/opt/trading/config/.env')

st.set_page_config(page_title='Trading Agent', layout='wide', page_icon='📈')


@st.cache_resource
def get_engine():
    url = (
        f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
        f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT', '5432')}"
        f"/{os.getenv('POSTGRES_DB')}"
    )
    return create_engine(url)


engine = get_engine()

# ── Sidebar ──
st.sidebar.title('Trading Agent v1.0')
st.sidebar.markdown(f"**Env:** `{os.getenv('ENVIRONMENT', 'dev')}`")
st.sidebar.markdown(f"**Mode:** `{'PAPER' if os.getenv('PAPER_TRADING','true')=='true' else 'LIVE'}`")
st.sidebar.markdown('---')
if st.sidebar.button('🔄 Refresh'):
    st.rerun()

# ── Tabs ──
tab1, tab2, tab3, tab4 = st.tabs(['📊 Portfolio', '💹 Trades', '📡 Signals', '🤖 AI Analysis'])

with tab1:
    st.subheader('Portfolio Overview')
    with engine.connect() as conn:
        pf = pd.read_sql(
            text('SELECT * FROM portfolio ORDER BY timestamp DESC LIMIT 1'), conn
        )
    if not pf.empty:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric('Total Balance', f'${pf["total_balance"].iloc[0]:,.2f}')
        col2.metric('Daily P&L', f'${pf["pnl_day"].iloc[0]:,.2f}')
        col3.metric('Drawdown', f'{pf["drawdown_pct"].iloc[0] * 100:.2f}%')
        col4.metric('Exposure', f'{pf["exposure_pct"].iloc[0] * 100:.2f}%')

        # Equity curve
        with engine.connect() as conn:
            eq = pd.read_sql(
                text('SELECT timestamp, total_balance FROM portfolio ORDER BY timestamp'),
                conn,
            )
        if len(eq) > 1:
            fig = go.Figure(
                go.Scatter(x=eq['timestamp'], y=eq['total_balance'], mode='lines')
            )
            fig.update_layout(title='Equity Curve', height=300)
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info('No portfolio data yet. Run the system to generate data.')

    # Market data summary
    st.subheader('Market Data')
    with engine.connect() as conn:
        md = pd.read_sql(
            text("""
                SELECT asset, timeframe, COUNT(*) as candles,
                       MIN(timestamp) as oldest, MAX(timestamp) as newest
                FROM market_data GROUP BY asset, timeframe
                ORDER BY asset, timeframe
            """),
            conn,
        )
    if not md.empty:
        st.dataframe(md, use_container_width=True)

with tab2:
    st.subheader('Trade History')
    with engine.connect() as conn:
        trades_df = pd.read_sql(
            text('SELECT * FROM trades ORDER BY timestamp_open DESC LIMIT 100'), conn
        )
    if not trades_df.empty:
        # Summary metrics
        n_open = len(trades_df[trades_df['status'] == 'OPEN'])
        n_closed = len(trades_df[trades_df['status'] != 'OPEN'])
        col1, col2, col3 = st.columns(3)
        col1.metric('Open Trades', n_open)
        col2.metric('Closed Trades', n_closed)
        col3.metric('Paper Trades', len(trades_df[trades_df['paper_trade'] == True]))
        st.dataframe(trades_df, use_container_width=True)
    else:
        st.info('No trades yet.')

with tab3:
    st.subheader('Recent Signals')
    with engine.connect() as conn:
        signals_df = pd.read_sql(
            text('SELECT * FROM signals ORDER BY timestamp DESC LIMIT 200'), conn
        )
    if not signals_df.empty:
        # Filter
        asset_filter = st.multiselect(
            'Filter by asset',
            signals_df['asset'].unique(),
            default=signals_df['asset'].unique(),
        )
        filtered = signals_df[signals_df['asset'].isin(asset_filter)]

        # Signal type distribution
        col1, col2 = st.columns(2)
        with col1:
            type_counts = filtered['signal_type'].value_counts()
            fig_types = go.Figure(go.Pie(labels=type_counts.index, values=type_counts.values))
            fig_types.update_layout(title='Signal Types', height=300)
            st.plotly_chart(fig_types, use_container_width=True)
        with col2:
            dir_counts = filtered['direction'].value_counts()
            fig_dirs = go.Figure(go.Bar(x=dir_counts.index, y=dir_counts.values))
            fig_dirs.update_layout(title='Directions', height=300)
            st.plotly_chart(fig_dirs, use_container_width=True)

        st.dataframe(filtered, use_container_width=True)
    else:
        st.info('No signals yet. Run MarketScanner first.')

with tab4:
    st.subheader('Claude AI Analysis')
    with engine.connect() as conn:
        expl = pd.read_sql(
            text("""
                SELECT task_type, asset, confidence, reasoning, timestamp
                FROM claude_explanations
                ORDER BY timestamp DESC LIMIT 50
            """),
            conn,
        )
    if not expl.empty:
        st.dataframe(expl, use_container_width=True)
    else:
        st.info('No AI analysis yet. Claude will generate analysis when credits are active.')

"""
Dashboard Streamlit — Panel de control del Trading Agent.
Versión 2.0: Portfolio inteligente, trades detallados, señales con contexto,
AI analysis mejorado y panel educativo.

Ejecutar: streamlit run dashboard/app.py --server.port 8501
"""
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

sys.path.insert(0, '/opt/trading')
load_dotenv('/opt/trading/config/.env')

st.set_page_config(page_title='Trading Agent', layout='wide', page_icon='📈')

# ── Helpers ──

SIGNAL_EXPLANATIONS = {
    'EMA_CROSS_BULL': ('📈 Cruce EMA Alcista',
        'La media móvil rápida (20 períodos) cruzó por encima de la lenta (50). '
        'Indica que el impulso a corto plazo supera la tendencia a largo plazo → posible tendencia alcista.'),
    'EMA_CROSS_BEAR': ('📉 Cruce EMA Bajista',
        'La media rápida (20) cruzó por debajo de la lenta (50). '
        'El impulso a corto plazo es menor que la tendencia → posible tendencia bajista.'),
    'RSI_OVERSOLD': ('🟢 RSI Sobrevendido',
        'El RSI (Relative Strength Index) bajó de 30. '
        'Indica que el activo ha sido vendido en exceso y podría rebotar → señal de compra.'),
    'RSI_OVERBOUGHT': ('🔴 RSI Sobrecomprado',
        'El RSI superó 70. El activo puede estar sobrecomprado y podría corregir → señal de venta.'),
    'BB_LOWER_TOUCH': ('🟢 Toque Banda Inferior',
        'El precio tocó la Banda de Bollinger inferior (2 desviaciones estándar bajo la media de 20 períodos). '
        'Estadísticamente, el precio tiende a volver hacia la media → posible rebote.'),
    'BB_UPPER_TOUCH': ('🔴 Toque Banda Superior',
        'El precio tocó la Banda de Bollinger superior. '
        'Puede indicar sobreextensión del precio → posible corrección a la baja.'),
    'VOLUME_SPIKE': ('⚡ Pico de Volumen',
        'El volumen superó 2× su promedio de 20 períodos. '
        'Un volumen inusual suele preceder movimientos fuertes del precio.'),
}

GLOSSARY = {
    'Stop Loss (SL)': 'Precio al que se cierra automáticamente un trade para **limitar la pérdida**. Es tu red de seguridad. Si compras BTC a $80,000 y tu SL es $78,800, lo máximo que puedes perder es $1,200 por unidad.',
    'Take Profit (TP)': 'Precio al que se cierra automáticamente un trade para **asegurar la ganancia**. Si compras a $80,000 y tu TP es $82,000, se cierra solo cuando ganas $2,000 por unidad.',
    'Trailing Stop': 'Un SL dinámico que **sube cuando el precio sube** (en compras). Si el precio sube mucho, el SL se mueve para proteger parte de la ganancia. Nunca baja, solo sube.',
    'Drawdown': 'La **caída desde el punto más alto** del balance. Si tu balance llegó a $11,000 y ahora es $10,000, el drawdown es 9.1%. Nuestro límite es 10% — si se alcanza, el sistema se detiene.',
    'R Múltiple': 'Mide la ganancia o pérdida **en unidades de riesgo**. Si arriesgas $100 (1R) y ganas $250, tu trade fue +2.5R. Un trade de -1R significa que perdiste exactamente lo que arriesgaste.',
    'Win Rate': 'El **porcentaje de trades ganadores** sobre el total. Un win rate del 40% con trades que ganan 2.5R y pierden 1R es rentable. No necesitas ganar siempre, sino ganar más cuando ganas.',
    'Profit Factor': 'La **suma de ganancias dividida entre la suma de pérdidas**. Si ganaste $500 en total y perdiste $300, tu profit factor es 1.67. Mayor a 1.0 = sistema rentable.',
    'ATR (Average True Range)': 'Mide la **volatilidad** promedio de un activo en los últimos 14 períodos. Si BTC tiene ATR=$1,500, significa que se mueve ~$1,500 por período. Se usa para calcular SL y TP.',
    'EMA (Exponential Moving Average)': 'Una **media del precio** que da más peso a los datos recientes. EMA20 reacciona rápido, EMA50 es más suave. Cuando EMA20 cruza sobre EMA50 → tendencia alcista.',
    'RSI (Relative Strength Index)': 'Oscilador 0-100 que mide el **impulso**. <30 = sobrevendido (posible rebote). >70 = sobrecomprado (posible caída). Entre 40-60 = neutral.',
    'Bollinger Bands': 'Tres líneas alrededor del precio: media de 20 períodos ± 2 desviaciones estándar. El precio tiende a **mantenerse dentro de las bandas** (~95% del tiempo). Tocar una banda es señal de posible reversión.',
    'Position Sizing': 'Cuántas unidades comprar. Se calcula para que si pierdes (precio llega a SL), **pierdas máximo 1% del balance**. Balance $10,000 → riesgo máximo $100 por trade.',
    'Exposición': 'El **riesgo total activo** como porcentaje del balance. Con 3 trades abiertos al 1% cada uno = 3% de exposición. Nuestro límite es 5%.',
    'Paper Trading': 'Operar con **dinero ficticio** para probar el sistema sin riesgo real. Todas las mecánicas son iguales, pero no se ejecuta en el exchange real.',
}

RISK_REJECTION_EXPLANATIONS = {
    'TRADING_HALTED': '⛔ El sistema está detenido porque el drawdown superó el 10%. Es una protección para evitar pérdidas mayores.',
    'DRAWDOWN_LIMIT_REACHED': '⛔ El drawdown alcanzó el 10%. Toda operación nueva queda bloqueada hasta revisión manual.',
    'MAX_EXPOSURE_REACHED': '⚠️ La exposición total (riesgo de todos los trades abiertos) ya alcanzó el 5% del balance.',
    'MAX_CONCURRENT_TRADES': '⚠️ Ya hay 3 trades abiertos (el máximo permitido). Hay que esperar a que cierre alguno.',
    'DUPLICATE_ASSET': '⚠️ Ya existe un trade abierto de este activo. Solo se permite 1 trade por activo para diversificar.',
    'SL_COOLDOWN': '⏳ Este activo fue cerrado por Stop Loss recientemente. Hay un cooldown de 30 minutos para evitar re-entradas impulsivas.',
    'MAX_EXPOSURE_WITH_NEW_TRADE': '⚠️ Abrir este trade llevaría la exposición total por encima del 5%.',
    'INSUFFICIENT_RR': '⚠️ La relación riesgo/recompensa es menor a 1.5. No vale la pena arriesgar $1 para ganar menos de $1.50.',
    'CLAUDE_CRITICAL_ANOMALY': '🤖 La IA detectó una anomalía crítica con alta confianza. Trade bloqueado por precaución.',
}


@st.cache_resource
def get_engine():
    url = (
        f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
        f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT', '5432')}"
        f"/{os.getenv('POSTGRES_DB')}"
    )
    return create_engine(url)


engine = get_engine()


def query(sql):
    """Execute a SQL query and return a DataFrame."""
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn)


# ── Data loading ──
pf = query('SELECT * FROM portfolio ORDER BY timestamp DESC LIMIT 1')
pf_history = query('SELECT timestamp, total_balance, peak_balance, drawdown_pct, exposure_pct FROM portfolio ORDER BY timestamp')
trades_df = query('SELECT * FROM trades ORDER BY timestamp_open DESC LIMIT 500')
signals_df = query('SELECT * FROM signals ORDER BY timestamp DESC LIMIT 500')
claude_df = query('SELECT * FROM claude_explanations ORDER BY timestamp DESC LIMIT 100')

# ── Polymarket data loading ──
poly_sessions_df = query('SELECT * FROM poly_sessions ORDER BY started_at DESC')
poly_positions_df = query('SELECT * FROM poly_positions ORDER BY timestamp_open DESC LIMIT 200')
btcd_df = query('SELECT * FROM btc_direction_trades ORDER BY timestamp_open DESC LIMIT 200')

# ── Options data loading ──
try:
    options_sessions_df = query('SELECT * FROM options_sessions ORDER BY started_at DESC')
    options_positions_df = query('SELECT * FROM options_positions ORDER BY opened_at DESC LIMIT 200')
except Exception:
    options_sessions_df = pd.DataFrame()
    options_positions_df = pd.DataFrame()

# ── Stocks data loading ──
try:
    stocks_sessions_df = query('SELECT * FROM stocks_sessions ORDER BY started_at DESC')
    stocks_trades_df = query('SELECT * FROM stocks_trades ORDER BY opened_at DESC LIMIT 500')
except Exception:
    stocks_sessions_df = pd.DataFrame()
    stocks_trades_df = pd.DataFrame()

closed_trades = trades_df[trades_df['status'] == 'CLOSED'].copy() if not trades_df.empty else pd.DataFrame()
open_trades = trades_df[trades_df['status'] == 'OPEN'].copy() if not trades_df.empty else pd.DataFrame()

# ── Computed KPIs ──
balance = float(pf['total_balance'].iloc[0]) if not pf.empty else 10000.0
dd_pct = float(pf['drawdown_pct'].iloc[0]) * 100 if not pf.empty else 0.0
exposure = float(pf['exposure_pct'].iloc[0]) * 100 if not pf.empty else 0.0

n_wins = len(closed_trades[closed_trades['pnl'] > 0]) if not closed_trades.empty else 0
n_losses = len(closed_trades[closed_trades['pnl'] <= 0]) if not closed_trades.empty else 0
n_total = n_wins + n_losses
win_rate = (n_wins / n_total * 100) if n_total > 0 else 0.0

if not closed_trades.empty:
    gross_profit = float(closed_trades[closed_trades['pnl'] > 0]['pnl'].sum())
    gross_loss = abs(float(closed_trades[closed_trades['pnl'] <= 0]['pnl'].sum()))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float('inf')
    avg_win = gross_profit / n_wins if n_wins > 0 else 0
    avg_loss = gross_loss / n_losses if n_losses > 0 else 0
    total_pnl = float(closed_trades['pnl'].sum())
else:
    gross_profit = gross_loss = profit_factor = avg_win = avg_loss = total_pnl = 0

# Streak
streak_val = 0
streak_type = ''
if not closed_trades.empty:
    for _, t in closed_trades.iterrows():
        p = float(t['pnl'])
        if streak_val == 0:
            streak_type = 'wins' if p > 0 else 'losses'
            streak_val = 1
        elif (p > 0 and streak_type == 'wins') or (p <= 0 and streak_type == 'losses'):
            streak_val += 1
        else:
            break

# ── Sidebar ──
st.sidebar.title('🤖 Trading Agent v2.1')
st.sidebar.markdown(f"**Entorno:** `{os.getenv('ENVIRONMENT', 'dev')}`")
st.sidebar.markdown(f"**Modo:** `{'📝 PAPER' if os.getenv('PAPER_TRADING','true')=='true' else '🔴 LIVE'}`")
st.sidebar.markdown('**Estrategias activas (6):**')
st.sidebar.markdown(
    '`TREND_MOMENTUM` `MEAN_REVERSION`\n\n'
    '`BTC_DIP_BUYER` `BREAKOUT`\n\n'
    '`SMC_ORDER_BLOCKS` `BTC_MICROSTRUCTURE`'
)
st.sidebar.markdown('---')

# Risk semaphore
if dd_pct >= 8:
    st.sidebar.error(f'🔴 RIESGO ALTO — Drawdown {dd_pct:.1f}%')
elif dd_pct >= 5:
    st.sidebar.warning(f'🟡 PRECAUCIÓN — Drawdown {dd_pct:.1f}%')
else:
    st.sidebar.success(f'🟢 NORMAL — Drawdown {dd_pct:.1f}%')

st.sidebar.caption('DD < 5% = Normal | 5-8% = Precaución | > 8% = Alto')
st.sidebar.markdown('---')
st.sidebar.metric('Balance', f'${balance:,.2f}')
st.sidebar.metric('P&L Total', f'${total_pnl:,.2f}', delta=f'{total_pnl:+,.2f}')
st.sidebar.metric('Win Rate', f'{win_rate:.1f}%')
st.sidebar.markdown('---')
if st.sidebar.button('🔄 Actualizar datos'):
    st.rerun()

# ══════════════════════════════════════════════════════════════════
# ── TABS ──
# ══════════════════════════════════════════════════════════════════
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    '📊 Portfolio', '💹 Trades', '📡 Señales', '🤖 IA', '🔮 Polymarket', '📣 Options', '📈 Stocks', '📚 Aprende'
])

# ══════════════════════════════════════════════════════════════════
# TAB 1 — PORTFOLIO INTELIGENTE
# ══════════════════════════════════════════════════════════════════
with tab1:
    st.subheader('Resumen del Portfolio')

    if not pf.empty:
        # Row 1: Main KPIs
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric('💰 Balance', f'${balance:,.2f}')
        c2.metric('📈 Win Rate', f'{win_rate:.1f}%', help='Porcentaje de trades cerrados con ganancia')
        c3.metric('📊 Profit Factor', f'{profit_factor:.2f}' if profit_factor != float('inf') else '∞',
                  help='Ganancias brutas / Pérdidas brutas. >1 = rentable')
        c4.metric('📉 Drawdown', f'{dd_pct:.2f}%',
                  help='Caída desde el balance más alto. Límite: 10%')
        c5.metric('⚡ Exposición', f'{exposure:.2f}%',
                  help='Riesgo total de trades abiertos. Límite: 5%')
        c6.metric('🔢 Trades', f'{n_total}',
                  help=f'{n_wins} ganados / {n_losses} perdidos')

        # Row 2: Detailed KPIs
        c1, c2, c3, c4 = st.columns(4)
        c1.metric('✅ Ganancia Promedio', f'${avg_win:,.2f}', help='Promedio de $ ganado en trades positivos')
        c2.metric('❌ Pérdida Promedio', f'${avg_loss:,.2f}', help='Promedio de $ perdido en trades negativos')
        c3.metric('💵 P&L Total', f'${total_pnl:,.2f}', delta=f'{total_pnl:+,.2f}')
        streak_icon = '🔥' if streak_type == 'wins' else '❄️' if streak_type == 'losses' else '—'
        c4.metric(f'{streak_icon} Racha Actual', f'{streak_val} {streak_type}',
                  help='Trades consecutivos del mismo resultado')

        # Equity curve with drawdown zones
        st.markdown('#### Curva de Equity')
        with st.expander('ℹ️ ¿Qué es la curva de equity?', expanded=False):
            st.markdown(
                'La curva de equity muestra **cómo ha evolucionado tu balance** a lo largo del tiempo. '
                'La línea azul es tu balance, la línea punteada gris es el **peak (máximo histórico)**, '
                'y la zona roja muestra el **drawdown** (diferencia entre peak y balance actual).'
            )

        if len(pf_history) > 1:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=pf_history['timestamp'], y=pf_history['total_balance'],
                mode='lines', name='Balance', line=dict(color='#2196F3', width=2),
            ))
            fig.add_trace(go.Scatter(
                x=pf_history['timestamp'], y=pf_history['peak_balance'],
                mode='lines', name='Peak Balance', line=dict(color='gray', width=1, dash='dot'),
            ))
            # Drawdown fill
            fig.add_trace(go.Scatter(
                x=pf_history['timestamp'], y=pf_history['peak_balance'],
                mode='lines', line=dict(width=0), showlegend=False,
            ))
            fig.add_trace(go.Scatter(
                x=pf_history['timestamp'], y=pf_history['total_balance'],
                mode='lines', line=dict(width=0), showlegend=False,
                fill='tonexty', fillcolor='rgba(255,0,0,0.1)',
            ))
            fig.update_layout(
                height=350, margin=dict(l=0, r=0, t=30, b=0),
                legend=dict(orientation='h', y=1.02),
                yaxis_title='USD', xaxis_title='',
            )
            st.plotly_chart(fig, use_container_width=True)

        # Drawdown chart
        if len(pf_history) > 1:
            fig_dd = go.Figure()
            fig_dd.add_trace(go.Scatter(
                x=pf_history['timestamp'],
                y=pf_history['drawdown_pct'].astype(float) * 100,
                mode='lines', fill='tozeroy',
                line=dict(color='#f44336'), fillcolor='rgba(244,67,54,0.2)',
                name='Drawdown %',
            ))
            fig_dd.add_hline(y=10, line_dash='dash', line_color='red',
                             annotation_text='⛔ Halt (10%)', annotation_position='top right')
            fig_dd.add_hline(y=5, line_dash='dash', line_color='orange',
                             annotation_text='⚠️ Precaución (5%)', annotation_position='top right')
            fig_dd.update_layout(
                height=200, margin=dict(l=0, r=0, t=10, b=0),
                yaxis_title='Drawdown %', xaxis_title='',
            )
            st.plotly_chart(fig_dd, use_container_width=True)

    else:
        st.info('No hay datos de portfolio aún. El sistema generará datos cuando opere.')

    # Market data
    st.markdown('#### 📡 Datos de Mercado')
    md = query("""
        SELECT asset, timeframe, COUNT(*) as candles,
               MIN(timestamp) as desde, MAX(timestamp) as hasta
        FROM market_data GROUP BY asset, timeframe
        ORDER BY asset, timeframe
    """)
    if not md.empty:
        st.dataframe(md, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════
# TAB 2 — TRADES DETALLADOS
# ══════════════════════════════════════════════════════════════════
with tab2:
    # ── Open trades as cards ──
    st.subheader(f'🔓 Trades Abiertos ({len(open_trades)})')
    if not open_trades.empty:
        cols = st.columns(min(len(open_trades), 3))
        for i, (_, trade) in enumerate(open_trades.iterrows()):
            with cols[i % 3]:
                entry = float(trade['entry_price'])
                sl = float(trade['stop_loss'])
                tp = float(trade['take_profit'])
                side = trade['side']
                risk = abs(entry - sl)
                reward = abs(tp - entry)
                rr = reward / risk if risk > 0 else 0

                # Trailing info from metadata
                meta = trade.get('metadata', {}) or {}
                trailing_level = meta.get('trailing_level', 0)
                trailing_active = trailing_level > 0

                st.markdown(f"**{trade['asset']}** {'🟢 BUY' if side == 'BUY' else '🔴 SELL'}")
                st.caption(f"Estrategia: {trade.get('strategy', '—')}")
                st.markdown(f"""
                | | Precio |
                |---|---|
                | 🎯 TP | ${tp:,.2f} |
                | ➡️ Entry | ${entry:,.2f} |
                | 🛡️ SL | ${sl:,.2f} |
                """)
                st.markdown(f"**R:R** {rr:.1f} | **Size** {float(trade['position_size']):.4f}")
                if trailing_active:
                    st.success(f'🔄 Trailing activo — Nivel {trailing_level}')
                else:
                    st.caption('Trailing: pendiente')

                # Progress bar: SL ← current position → TP
                progress = 0.5  # neutral (no live price)
                st.progress(progress, text='SL ◄━━━━━━━━━━► TP')
    else:
        st.info('No hay trades abiertos en este momento.')

    st.markdown('---')

    # ── Closed trades ──
    st.subheader(f'🔒 Trades Cerrados ({len(closed_trades)})')
    if not closed_trades.empty:
        # KPIs row
        c1, c2, c3, c4, c5 = st.columns(5)
        n_sl = len(closed_trades[closed_trades['close_reason'] == 'STOP_LOSS'])
        n_tp = len(closed_trades[closed_trades['close_reason'] == 'TAKE_PROFIT'])
        n_trail = len(closed_trades[closed_trades['close_reason'] == 'TRAILING_STOP'])
        c1.metric('🎯 Take Profit', n_tp)
        c2.metric('🔄 Trailing Stop', n_trail)
        c3.metric('🛑 Stop Loss', n_sl)
        c4.metric('✅ Win Rate', f'{win_rate:.1f}%')
        c5.metric('📊 Profit Factor', f'{profit_factor:.2f}' if profit_factor != float('inf') else '∞')

        # Close reason distribution
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown('##### ¿Cómo se cierran los trades?')
            reason_counts = closed_trades['close_reason'].value_counts()
            colors = {'TAKE_PROFIT': '#4CAF50', 'TRAILING_STOP': '#2196F3', 'STOP_LOSS': '#f44336'}
            fig_reason = go.Figure(go.Pie(
                labels=reason_counts.index, values=reason_counts.values,
                marker=dict(colors=[colors.get(r, '#999') for r in reason_counts.index]),
                hole=0.4,
            ))
            fig_reason.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig_reason, use_container_width=True)
            with st.expander('ℹ️ ¿Qué significa cada cierre?'):
                st.markdown(
                    '- **TAKE_PROFIT**: El precio alcanzó el objetivo de ganancias 🎯\n'
                    '- **TRAILING_STOP**: El trailing protegió ganancias parciales y se activó 🔄\n'
                    '- **STOP_LOSS**: El precio llegó al límite de pérdida original 🛑'
                )

        with col_b:
            st.markdown('##### P&L por Activo')
            pnl_asset = closed_trades.groupby('asset')['pnl'].sum().reset_index()
            pnl_asset['color'] = pnl_asset['pnl'].apply(lambda x: '#4CAF50' if x > 0 else '#f44336')
            fig_pnl = go.Figure(go.Bar(
                x=pnl_asset['asset'], y=pnl_asset['pnl'],
                marker_color=pnl_asset['color'],
                text=pnl_asset['pnl'].apply(lambda x: f'${x:+,.2f}'),
                textposition='outside',
            ))
            fig_pnl.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0),
                                  yaxis_title='P&L (USD)')
            st.plotly_chart(fig_pnl, use_container_width=True)

        # P&L por estrategia
        if 'strategy' in closed_trades.columns:
            st.markdown('##### P&L por Estrategia')
            pnl_strat = closed_trades.groupby('strategy').agg(
                trades=('pnl', 'count'),
                pnl_total=('pnl', 'sum'),
                wins=('pnl', lambda x: (x > 0).sum()),
            ).reset_index()
            pnl_strat['win_rate'] = (pnl_strat['wins'] / pnl_strat['trades'] * 100).round(1)
            pnl_strat['pnl_total'] = pnl_strat['pnl_total'].apply(lambda x: f'${x:+,.2f}')
            pnl_strat['win_rate'] = pnl_strat['win_rate'].apply(lambda x: f'{x:.1f}%')
            st.dataframe(
                pnl_strat[['strategy', 'trades', 'pnl_total', 'win_rate']].rename(columns={
                    'strategy': 'Estrategia', 'trades': 'Trades',
                    'pnl_total': 'P&L Total', 'win_rate': 'Win Rate',
                }),
                use_container_width=True, hide_index=True,
            )
            # Nuevas estrategias desplegadas sin trades aún
            active_in_db = set(closed_trades['strategy'].unique())
            new_strats = [s for s in ['SMC_ORDER_BLOCKS', 'BTC_MICROSTRUCTURE'] if s not in active_in_db]
            if new_strats:
                st.info(
                    f"🆕 Estrategias nuevas en producción (sin trades cerrados aún): "
                    f"{', '.join(f'`{s}`' for s in new_strats)} — "
                    "Activas desde 2026-04-25, esperando condiciones de mercado (ATR suficiente)."
                )

        # Formatted trade table
        st.markdown('##### Historial Completo')
        display_df = closed_trades[['asset', 'side', 'strategy', 'entry_price', 'exit_price',
                                     'stop_loss', 'take_profit', 'pnl', 'pnl_pct', 'close_reason',
                                     'timestamp_open', 'timestamp_close']].copy()
        display_df['pnl'] = display_df['pnl'].apply(lambda x: f'${float(x):+,.2f}')
        display_df['pnl_pct'] = display_df['pnl_pct'].apply(lambda x: f'{float(x):+.2f}%')
        display_df.columns = ['Asset', 'Side', 'Estrategia', 'Entry', 'Exit', 'SL', 'TP',
                              'P&L', 'P&L %', 'Cierre', 'Abierto', 'Cerrado']
        st.dataframe(display_df, use_container_width=True, hide_index=True)
    else:
        st.info('No hay trades cerrados aún.')


# ══════════════════════════════════════════════════════════════════
# TAB 3 — SEÑALES CON CONTEXTO
# ══════════════════════════════════════════════════════════════════
with tab3:
    st.subheader('📡 Señales del Mercado')

    if not signals_df.empty:
        # Signal pipeline funnel
        st.markdown('##### Pipeline: De Señal a Trade')
        n_signals = len(signals_df)
        n_opportunities = len(claude_df[claude_df['task_type'] == 'signal_interpretation']) if not claude_df.empty else 0
        n_executed = len(trades_df) if not trades_df.empty else 0
        fc1, fc2, fc3 = st.columns(3)
        fc1.metric('📡 Señales generadas', n_signals, help='Señales técnicas detectadas por el scanner')
        fc2.metric('🔍 Evaluadas por IA', n_opportunities, help='Señales con score ≥65 evaluadas por GPT')
        fc3.metric('✅ Trades ejecutados', n_executed, help='Trades que pasaron todas las reglas de riesgo')

        with st.expander('ℹ️ ¿Cómo funciona el pipeline?'):
            st.markdown(
                '1. **Scanner** detecta señales técnicas (EMA, RSI, Bollinger, Volumen)\n'
                '2. **Estrategias** combinan señales y generan oportunidades con score ≥ 65\n'
                '3. **IA (GPT)** evalúa consistencia de la señal\n'
                '4. **Risk Manager** aplica 10 reglas de riesgo\n'
                '5. Solo los trades aprobados se ejecutan'
            )

        st.markdown('---')

        # Filter
        asset_filter = st.multiselect(
            'Filtrar por activo', signals_df['asset'].unique(),
            default=list(signals_df['asset'].unique()), key='sig_filter',
        )
        filtered = signals_df[signals_df['asset'].isin(asset_filter)]

        # Heatmap: asset × signal_type
        st.markdown('##### Mapa de Calor: Señales por Activo')
        with st.expander('ℹ️ ¿Cómo leer el heatmap?'):
            st.markdown(
                'Cada celda muestra **cuántas veces** se ha detectado una señal para un activo. '
                'Colores más intensos = más señales. Te ayuda a ver de un vistazo qué activos '
                'tienen más actividad técnica.'
            )
        pivot = filtered.pivot_table(index='asset', columns='signal_type', values='id',
                                     aggfunc='count', fill_value=0)
        if not pivot.empty:
            fig_heat = go.Figure(go.Heatmap(
                z=pivot.values, x=pivot.columns, y=pivot.index,
                colorscale='YlOrRd', text=pivot.values, texttemplate='%{text}',
            ))
            fig_heat.update_layout(height=250, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig_heat, use_container_width=True)

        # Charts
        col1, col2 = st.columns(2)
        with col1:
            st.markdown('##### Distribución de Señales')
            type_counts = filtered['signal_type'].value_counts()
            fig_types = go.Figure(go.Pie(labels=type_counts.index, values=type_counts.values, hole=0.3))
            fig_types.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig_types, use_container_width=True)
        with col2:
            st.markdown('##### Dirección BUY vs SELL')
            dir_counts = filtered['direction'].value_counts()
            fig_dirs = go.Figure(go.Bar(
                x=dir_counts.index, y=dir_counts.values,
                marker_color=['#4CAF50' if d == 'BUY' else '#f44336' if d == 'SELL' else '#999'
                              for d in dir_counts.index],
            ))
            fig_dirs.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig_dirs, use_container_width=True)

        # Signal explanations
        st.markdown('##### ¿Qué significa cada señal?')
        for sig_type in filtered['signal_type'].unique():
            if sig_type in SIGNAL_EXPLANATIONS:
                title, desc = SIGNAL_EXPLANATIONS[sig_type]
                with st.expander(f'{title} ({sig_type})'):
                    st.markdown(desc)

        # Recent signals table
        st.markdown('##### Señales Recientes')
        sig_display = filtered[['asset', 'timeframe', 'signal_type', 'direction', 'strength',
                                'price_at_signal', 'timestamp']].head(50).copy()
        sig_display['strength'] = sig_display['strength'].apply(lambda x: f'{float(x):.2f}' if pd.notna(x) else '—')
        sig_display.columns = ['Asset', 'Timeframe', 'Tipo', 'Dirección', 'Fuerza', 'Precio', 'Timestamp']
        st.dataframe(sig_display, use_container_width=True, hide_index=True)
    else:
        st.info('No hay señales aún. El MarketScanner las generará cuando el sistema opere.')


# ══════════════════════════════════════════════════════════════════
# TAB 4 — AI ANALYSIS MEJORADO
# ══════════════════════════════════════════════════════════════════
with tab4:
    st.subheader('🤖 Análisis de IA (GPT-4o-mini)')

    if not claude_df.empty:
        # Summary metrics
        c1, c2, c3, c4 = st.columns(4)
        avg_conf = float(claude_df['confidence'].mean())
        total_tokens = int(claude_df['tokens_used'].sum()) if 'tokens_used' in claude_df.columns else 0
        avg_latency = float(claude_df['latency_ms'].mean()) if 'latency_ms' in claude_df.columns else 0
        # Cost estimate: gpt-4o-mini $0.15/1M input + $0.60/1M output, approx $0.375/1M avg
        cost_est = total_tokens * 0.000000375

        c1.metric('🎯 Confianza Promedio', f'{avg_conf:.0f}%',
                  help='Promedio de confianza del LLM en sus decisiones')
        c2.metric('🪙 Tokens Totales', f'{total_tokens:,}',
                  help='Tokens consumidos por el LLM (input + output)')
        c3.metric('💰 Costo Estimado', f'${cost_est:.4f}',
                  help='Costo estimado del uso de GPT-4o-mini')
        c4.metric('⚡ Latencia Promedio', f'{avg_latency:.0f}ms',
                  help='Tiempo promedio de respuesta del LLM')

        with st.expander('ℹ️ ¿Qué hace la IA en el sistema?'):
            st.markdown(
                'La IA (GPT-4o-mini) tiene **3 funciones** en el pipeline:\n\n'
                '1. **Signal Interpretation**: Evalúa si las señales técnicas son consistentes entre sí\n'
                '2. **Anomaly Check**: Busca condiciones anómalas antes de aprobar un trade\n'
                '3. **Explain Trade**: Genera una explicación legible de por qué se ejecutó el trade\n\n'
                'La IA **NO decide** si comprar o vender — solo valida o alerta. '
                'Las decisiones las toman las estrategias + el Risk Manager.'
            )

        # Last decision expanded
        st.markdown('##### Última Decisión')
        last = claude_df.iloc[0]
        result_data = last.get('result', {}) or {}
        st.markdown(f"**Tipo:** {last['task_type']} | **Asset:** {last['asset']} | "
                    f"**Confianza:** {last['confidence']}%")
        if last.get('reasoning'):
            st.info(f"💬 {last['reasoning']}")

        # Anomalies
        anomalies = claude_df[claude_df['task_type'] == 'anomaly_check']
        if not anomalies.empty:
            st.markdown('##### 🚨 Historial de Anomaly Checks')
            anom_display = anomalies[['asset', 'confidence', 'reasoning', 'timestamp']].copy()
            anom_display.columns = ['Asset', 'Confianza', 'Razonamiento', 'Timestamp']
            st.dataframe(anom_display, use_container_width=True, hide_index=True)

        # Confidence over time
        if len(claude_df) > 2:
            st.markdown('##### Confianza del LLM en el tiempo')
            fig_conf = go.Figure(go.Scatter(
                x=claude_df['timestamp'], y=claude_df['confidence'],
                mode='markers+lines', marker=dict(size=6),
                line=dict(color='#9C27B0'),
            ))
            fig_conf.add_hline(y=85, line_dash='dash', line_color='red',
                               annotation_text='Umbral anomalía crítica (85%)')
            fig_conf.update_layout(height=250, margin=dict(l=0, r=0, t=10, b=0),
                                   yaxis_title='Confianza %')
            st.plotly_chart(fig_conf, use_container_width=True)

        # Full table
        st.markdown('##### Historial Completo')
        ai_display = claude_df[['task_type', 'asset', 'confidence', 'reasoning',
                                'tokens_used', 'latency_ms', 'timestamp']].copy()
        ai_display.columns = ['Tipo', 'Asset', 'Confianza', 'Razonamiento', 'Tokens', 'Latencia (ms)', 'Timestamp']
        st.dataframe(ai_display, use_container_width=True, hide_index=True)
    else:
        st.info('No hay análisis de IA aún. Se generarán cuando el sistema evalúe señales.')


# ══════════════════════════════════════════════════════════════════# TAB 6 — OPTIONS (Theta Farming Deribit)
# ════════════════════════════════════════════════════════════════
with tab6:
    st.subheader('📣 Options — Theta Farming (Deribit)')
    st.caption('Vendemos PUTs semanales de BTC OTM. Si BTC no cae hasta el strike, la prima es ganancia pura.')

    if options_sessions_df.empty and options_positions_df.empty:
        st.info('⏳ Sin datos de opciones todavía. Inicia el agente: `python3 scripts/run_options.py`')
    else:
        # ── Señión activa ───────────────────────────────────────────────
        st.markdown('### 📋 Sesión Activa')
        if not options_sessions_df.empty:
            active_opt = options_sessions_df[options_sessions_df['status'] == 'ACTIVE']
            if not active_opt.empty:
                s = active_opt.iloc[0]
                initial = float(s['initial_balance_usd'])
                current = float(s['current_balance_usd'])
                pnl_total = float(s['total_pnl_usd'])
                pnl_pct = pnl_total / initial * 100 if initial > 0 else 0
                premium_colectado = float(s.get('total_premium_usd', 0) or 0)
                max_dd = float(s.get('max_drawdown_pct', 0) or 0)
                total_c = int(s.get('total_contracts', 0) or 0)
                winning_c = int(s.get('winning_contracts', 0) or 0)
                wr_opt = winning_c / total_c * 100 if total_c > 0 else 0

                c1, c2, c3, c4, c5, c6 = st.columns(6)
                c1.metric('💰 Balance', f'${current:,.2f}', delta=f'{pnl_total:+.2f}')
                c2.metric('📈 PnL Total', f'${pnl_total:+.2f}', delta=f'{pnl_pct:+.2f}%')
                c3.metric('✅ Prima Cobrada', f'${premium_colectado:.2f}')
                c4.metric('🎯 Win Rate Contratos', f'{wr_opt:.0f}%', help=f'{winning_c}/{total_c} contratos')
                c5.metric('📉 Max Drawdown', f'{max_dd:.1f}%')
                c6.metric('📊 Contratos Totales', total_c)

                # Status badge
                mode = str(s.get('mode', 'paper')).upper()
                badge = '📝 PAPER' if mode == 'PAPER' else '🔴 LIVE'
                st.caption(f'Sesión: **{s["session_name"]}** | Modo: {badge} | Inicio: {str(s["started_at"])[:10]}')
            else:
                st.info('Sin sesión options activa.')

        # ── Posiciones abiertas ────────────────────────────────────────────
        st.markdown('### 🔐 Posiciones Abiertas')
        if not options_positions_df.empty:
            open_opt = options_positions_df[options_positions_df['status'] == 'OPEN'].copy()
            if not open_opt.empty:
                display_cols = [
                    'instrument_name', 'strike', 'dte_at_entry',
                    'entry_premium_usd', 'margin_required_usd',
                    'iv_at_entry', 'iv_rank_at_entry', 'delta_at_entry',
                    'expiration_date', 'opened_at',
                ]
                cols_available = [c for c in display_cols if c in open_opt.columns]
                st.dataframe(
                    open_opt[cols_available].rename(columns={
                        'instrument_name': 'Instrumento',
                        'strike': 'Strike $',
                        'dte_at_entry': 'DTE',
                        'entry_premium_usd': 'Prima $',
                        'margin_required_usd': 'Margen $',
                        'iv_at_entry': 'IV%',
                        'iv_rank_at_entry': 'IV Rank%',
                        'delta_at_entry': 'Delta',
                        'expiration_date': 'Expira',
                        'opened_at': 'Abierta',
                    }),
                    use_container_width=True,
                    height=200,
                )
            else:
                st.info('Sin posiciones abiertas actualmente.')

        # ── Historial de posiciones cerradas ────────────────────────────
        st.markdown('### 📜 Historial')
        if not options_positions_df.empty:
            closed_opt = options_positions_df[options_positions_df['status'] != 'OPEN'].copy()
            if not closed_opt.empty:
                # Colorear por resultado
                if 'pnl_usd' in closed_opt.columns:
                    closed_opt['pnl_usd'] = pd.to_numeric(closed_opt['pnl_usd'], errors='coerce')
                    hist_cols = [
                        'instrument_name', 'strike', 'dte_at_entry',
                        'entry_premium_usd', 'exit_premium_usd', 'pnl_usd', 'pnl_pct',
                        'exit_reason', 'iv_rank_at_entry', 'closed_at',
                    ]
                    hist_available = [c for c in hist_cols if c in closed_opt.columns]
                    st.dataframe(
                        closed_opt[hist_available].rename(columns={
                            'instrument_name': 'Instrumento',
                            'strike': 'Strike $',
                            'dte_at_entry': 'DTE',
                            'entry_premium_usd': 'Prima Entrada $',
                            'exit_premium_usd': 'Prima Salida $',
                            'pnl_usd': 'PnL $',
                            'pnl_pct': 'PnL %',
                            'exit_reason': 'Razón',
                            'iv_rank_at_entry': 'IV Rank%',
                            'closed_at': 'Cerrada',
                        }),
                        use_container_width=True,
                        height=300,
                    )

                    # Gráfico PnL acumulado
                    if len(closed_opt) > 1:
                        closed_sorted = closed_opt.sort_values('closed_at')
                        closed_sorted['pnl_acum'] = closed_sorted['pnl_usd'].cumsum()
                        fig = px.area(
                            closed_sorted,
                            x='closed_at',
                            y='pnl_acum',
                            title='PnL Acumulado Options',
                            labels={'closed_at': 'Fecha', 'pnl_acum': 'PnL USD'},
                            color_discrete_sequence=['#00CC96'],
                        )
                        st.plotly_chart(fig, use_container_width=True)
            else:
                st.info('Sin contratos cerrados todavía.')

        # ── Explicación didáctica ─────────────────────────────────────────
        with st.expander('ℹ️ Cómo funciona el Theta Farming'):
            st.markdown("""
            **Vendemos PUTs OTM (out-of-the-money) de BTC en Deribit.**

            | Término | Significado |
            |---------|-------------|
            | **PUT** | Opción que le da al comprador el derecho a vendernos BTC a un precio fijo |
            | **OTM (Out-of-the-Money)** | El strike está por debajo del precio actual de BTC |
            | **Strike** | El precio al que el comprador puede ejercer la opción |
            | **Prima** | Lo que cobramos al vender la opción |
            | **DTE** | Días hasta el vencimiento |
            | **IV Rank** | Qué tan cara está la prima relativa a su historia (0-100%) |
            | **Delta** | Probabilidad aproximada de que la opción sea ejercida (queremos ≤ 0.15) |
            | **Theta** | Dólars/día que pierde la prima por el paso del tiempo (a nuestro favor) |

            **Escenario ganador (80% del tiempo):**
            BTC se mantiene por encima del strike → la opción vence sin valor → nos quedamos la prima.

            **Escenario perdedor:**
            BTC cae por debajo del strike → la opción tiene valor intrínseco → compramos de vuelta si supera 2× la prima.
            """)

# ════════════════════════════════════════════════════════════════# TAB 5 — POLYMARKET
# ══════════════════════════════════════════════════════════════════
with tab5:
    st.subheader('🔮 Polymarket — Mercados de Predicción')

    # ── Sección 1: Sesiones ──────────────────────────────────────
    st.markdown('### 📋 Sesiones')

    if not poly_sessions_df.empty:
        # Sesión activa
        active_sess = poly_sessions_df[poly_sessions_df['status'] == 'ACTIVE']
        if not active_sess.empty:
            s = active_sess.iloc[0]
            init_bal  = float(s['initial_balance'])
            curr_bal  = float(s['current_balance'])
            total_pnl_poly = float(s['total_pnl'])
            win_trades = int(s['winning_trades'] or 0)
            total_tr  = int(s['total_trades'] or 0)
            wr_poly   = (win_trades / total_tr * 100) if total_tr > 0 else 0.0
            pf_poly   = float(s['profit_factor'] or 0)
            dd_poly   = float(s['max_drawdown'] or 0)

            st.success(f"🟢 **{s['session_name']}** — Activa desde {pd.to_datetime(s['started_at']).strftime('%d/%m/%Y %H:%M')}")
            c1, c2, c3, c4, c5, c6 = st.columns(6)
            c1.metric('💰 Balance', f'${curr_bal:,.2f}',
                      delta=f'{curr_bal - init_bal:+,.2f}')
            c2.metric('📈 P&L Total', f'${total_pnl_poly:+,.2f}')
            c3.metric('🎯 Win Rate', f'{wr_poly:.1f}%')
            c4.metric('📊 Profit Factor', f'{pf_poly:.2f}')
            c5.metric('📉 Max Drawdown', f'${dd_poly:.2f}')
            c6.metric('🔢 Trades', f'{total_tr}', help=f'{win_trades} ganados')
        else:
            st.info('No hay sesión de Polymarket activa.')

        # Historial de sesiones
        st.markdown('##### Historial de Sesiones')
        sess_display = poly_sessions_df.copy()
        sess_display['initial_balance'] = sess_display['initial_balance'].apply(lambda x: f'${float(x):,.2f}')
        sess_display['current_balance'] = sess_display['current_balance'].apply(lambda x: f'${float(x):,.2f}')
        sess_display['total_pnl'] = sess_display['total_pnl'].apply(lambda x: f'${float(x):+,.2f}')
        sess_display['max_drawdown'] = sess_display['max_drawdown'].apply(lambda x: f'${float(x):.2f}')
        sess_display['status_icon'] = sess_display['status'].map({
            'ACTIVE': '🟢 ACTIVE', 'COMPLETED': '✅ COMPLETED', 'FAILED': '❌ FAILED'
        }).fillna(sess_display['status'])
        st.dataframe(
            sess_display[['session_name', 'status_icon', 'initial_balance', 'current_balance',
                          'total_pnl', 'total_trades', 'winning_trades', 'max_drawdown', 'started_at']].rename(columns={
                'session_name': 'Sesión', 'status_icon': 'Estado',
                'initial_balance': 'Balance Inicial', 'current_balance': 'Balance Actual',
                'total_pnl': 'P&L', 'total_trades': 'Trades', 'winning_trades': 'Ganados',
                'max_drawdown': 'Max DD', 'started_at': 'Inicio',
            }),
            use_container_width=True, hide_index=True,
        )
    else:
        st.info('No hay sesiones de Polymarket registradas.')

    st.markdown('---')

    # ── Sección 2: Posiciones de Predicción ─────────────────────
    st.markdown('### 🎯 Posiciones de Predicción (POLY_SESSION)')

    if not poly_positions_df.empty:
        open_poly  = poly_positions_df[poly_positions_df['status'] == 'OPEN']
        closed_poly = poly_positions_df[poly_positions_df['status'] == 'CLOSED']

        # ── Alerta: máximo concurrente alcanzado ──
        if len(open_poly) >= 8:
            st.warning(f'⚠️ **MAX_CONCURRENT alcanzado** — {len(open_poly)} posiciones abiertas. '
                       'El agente detecta señales pero no puede abrir más hasta que resuelvan algunas.')

        # ── Breakdown por estrategia ──
        st.markdown('#### 📊 Performance por Estrategia')
        strat_breakdown = poly_positions_df.groupby('strategy').agg(
            total=('pnl', 'count'),
            abiertas=('status', lambda x: (x == 'OPEN').sum()),
            cerradas=('status', lambda x: (x == 'CLOSED').sum()),
            wins=('pnl', lambda x: (x.fillna(0).astype(float) > 0).sum()),
            pnl_total=('pnl', lambda x: x.fillna(0).astype(float).sum()),
        ).reset_index()
        strat_breakdown['win_rate'] = strat_breakdown.apply(
            lambda r: f"{r['wins']/r['cerradas']*100:.0f}%" if r['cerradas'] > 0 else '—', axis=1
        )
        strat_breakdown['pnl_fmt'] = strat_breakdown['pnl_total'].apply(lambda x: f'${x:+.2f}')
        strat_breakdown['estado'] = strat_breakdown['strategy'].map({
            'PREDICTION_LLM': '❌ Descartada (LLM)',
            'SIGNAL_BASED':   '✅ Activa',
            'combinatorial':  '🟡 En prueba',
            'legged_arb':     '🟡 En prueba',
            'tail_end':       '🟡 En prueba',
        }).fillna('🟡 En prueba')

        st.dataframe(
            strat_breakdown[['strategy', 'estado', 'total', 'abiertas', 'cerradas', 'win_rate', 'pnl_fmt']].rename(columns={
                'strategy': 'Estrategia', 'estado': 'Estado', 'total': 'Total',
                'abiertas': 'Abiertas', 'cerradas': 'Cerradas',
                'win_rate': 'Win Rate', 'pnl_fmt': 'P&L',
            }),
            use_container_width=True, hide_index=True,
        )

        with st.expander('ℹ️ ¿Qué hace cada estrategia Polymarket?'):
            st.markdown("""
| Estrategia | Lógica | Estado |
|---|---|---|
| **PREDICTION_LLM** | LLM (OpenAI) estimaba probabilidades → entró en eventos de 2.2% de prob | ❌ Descartada (-$581 paper) |
| **SIGNAL_BASED** | BtcDirection + MarketRegime → apuesta cuando señal técnica contradice precio Polymarket | ✅ Activa |
| **combinatorial** | Arbitraje de monotonicity: P(BTC>$75k) debe ser ≥ P(BTC>$80k) | 🟡 Filtrando oportunidades |
| **legged_arb** | Arbitraje correlacionado entre dos mercados relacionados | 🟡 En prueba |
""")

        # KPIs globales cerradas (solo sesión activa)
        if not closed_poly.empty:
            # Filtrar solo sesión activa, excluir SESSION_RESET
            active_sess_name = active_sess.iloc[0]['session_name'] if not active_sess.empty else None
            if active_sess_name:
                mask = (closed_poly['session_name'] == active_sess_name) & (closed_poly['close_reason'] != 'SESSION_RESET')
            else:
                mask = closed_poly['close_reason'] != 'SESSION_RESET'
            session_closed = closed_poly[mask].copy()

            pnl_series = session_closed['pnl'].astype(float) if not session_closed.empty else pd.Series(dtype=float)
            gross_gains   = pnl_series[pnl_series > 0].sum()
            gross_losses  = abs(pnl_series[pnl_series <= 0].sum())
            pf_closed     = (gross_gains / gross_losses) if gross_losses > 0 else float('inf')
            wr_closed     = (len(pnl_series[pnl_series > 0]) / len(pnl_series) * 100) if len(pnl_series) > 0 else 0

            st.markdown('#### 📈 KPIs Globales (sesión activa)')
            c1, c2, c3, c4 = st.columns(4)
            c1.metric('🔒 Cerradas', len(session_closed))
            c2.metric('🔓 Abiertas', len(open_poly))
            c3.metric('🎯 Win Rate', f'{wr_closed:.1f}%')
            c4.metric('📊 Profit Factor', f'{pf_closed:.2f}' if pf_closed != float('inf') else '∞')

        # Posiciones abiertas
        if not open_poly.empty:
            st.markdown(f'##### 🔓 Abiertas ({len(open_poly)})')
            open_disp = open_poly[['question', 'side', 'entry_price', 'shares',
                                   'cost_basis', 'session_name', 'timestamp_open']].copy()
            open_disp['entry_price'] = open_disp['entry_price'].apply(lambda x: f'{float(x):.3f}')
            open_disp['cost_basis']  = open_disp['cost_basis'].apply(lambda x: f'${float(x):.2f}')
            open_disp.columns = ['Mercado', 'Lado', 'Entrada', 'Shares', 'Costo', 'Sesión', 'Abierto']
            st.dataframe(open_disp, use_container_width=True, hide_index=True)

        # Posiciones cerradas
        if not closed_poly.empty:
            st.markdown(f'##### 🔒 Cerradas ({len(closed_poly)})')

            # P&L por close_reason
            col_a, col_b = st.columns(2)
            with col_a:
                reason_counts = closed_poly['close_reason'].value_counts()
                colors_map = {
                    'RESOLVED_WIN': '#4CAF50', 'RESOLVED_LOSS': '#f44336',
                    'EXPIRED': '#FF9800', 'MANUAL': '#9E9E9E',
                }
                fig_pr = go.Figure(go.Pie(
                    labels=reason_counts.index, values=reason_counts.values,
                    marker=dict(colors=[colors_map.get(r, '#999') for r in reason_counts.index]),
                    hole=0.4,
                ))
                fig_pr.update_layout(height=260, margin=dict(l=0, r=0, t=20, b=0),
                                     title_text='Motivo de cierre')
                st.plotly_chart(fig_pr, use_container_width=True)

            with col_b:
                # P&L acumulado por día
                cd = closed_poly.copy()
                cd['fecha'] = pd.to_datetime(cd['timestamp_close']).dt.date
                daily_pnl = cd.groupby('fecha')['pnl'].sum().reset_index()
                daily_pnl['pnl'] = daily_pnl['pnl'].astype(float)
                fig_dpnl = go.Figure(go.Bar(
                    x=daily_pnl['fecha'], y=daily_pnl['pnl'],
                    marker_color=['#4CAF50' if v >= 0 else '#f44336' for v in daily_pnl['pnl']],
                    text=daily_pnl['pnl'].apply(lambda x: f'${x:+.2f}'),
                    textposition='outside',
                ))
                fig_dpnl.update_layout(height=260, margin=dict(l=0, r=0, t=20, b=0),
                                       title_text='P&L por día', yaxis_title='USD')
                st.plotly_chart(fig_dpnl, use_container_width=True)

            # Tabla
            closed_disp = closed_poly[['question', 'side', 'entry_price',
                                       'pnl', 'pnl_pct', 'close_reason',
                                       'session_name', 'timestamp_close']].copy()
            closed_disp['entry_price'] = closed_disp['entry_price'].apply(lambda x: f'{float(x):.3f}')
            closed_disp['pnl']     = closed_disp['pnl'].apply(lambda x: f'${float(x):+.2f}')
            closed_disp['pnl_pct'] = closed_disp['pnl_pct'].apply(lambda x: f'{float(x):+.1f}%')
            closed_disp.columns = ['Mercado', 'Lado', 'Entrada', 'P&L', 'P&L %',
                                   'Cierre', 'Sesión', 'Cerrado']
            st.dataframe(closed_disp, use_container_width=True, hide_index=True)
    else:
        st.info('No hay posiciones de Polymarket registradas.')

    st.markdown('---')

    # ── Sección 3: BTC Direction ─────────────────────────────────
    st.markdown('### ₿ BTC Direction — Multi-Timeframe')

    if not btcd_df.empty:
        btcd_open   = btcd_df[btcd_df['status'] == 'OPEN']
        btcd_closed = btcd_df[btcd_df['status'] == 'CLOSED']

        # KPIs
        pnl_btcd   = btcd_closed['pnl_usdc'].astype(float).sum() if not btcd_closed.empty else 0.0
        wins_btcd  = int((btcd_closed['pnl_usdc'].astype(float) > 0).sum()) if not btcd_closed.empty else 0
        total_btcd = len(btcd_closed)
        wr_btcd    = (wins_btcd / total_btcd * 100) if total_btcd > 0 else 0.0

        # Calcular balance actual
        init_btcd = 500.0  # initial_paper_balance del config
        locked    = btcd_open['cost_usdc'].astype(float).sum() if not btcd_open.empty else 0.0
        bal_btcd  = init_btcd + pnl_btcd - locked

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric('💰 Balance', f'${bal_btcd:,.2f}', delta=f'{bal_btcd - init_btcd:+,.2f}')
        c2.metric('📈 P&L Total', f'${pnl_btcd:+,.2f}')
        c3.metric('🎯 Win Rate', f'{wr_btcd:.1f}%')
        c4.metric('🔓 Abiertas', len(btcd_open))
        c5.metric('🔒 Cerradas', total_btcd)

        # P&L por timeframe
        if not btcd_closed.empty and 'timeframe' in btcd_closed.columns:
            tf_avail = btcd_closed['timeframe'].dropna()
            if not tf_avail.empty:
                st.markdown('##### P&L por Timeframe')
                pnl_tf = btcd_closed.groupby('timeframe').agg(
                    trades=('pnl_usdc', 'count'),
                    pnl=('pnl_usdc', lambda x: float(x.astype(float).sum())),
                    wins=('pnl_usdc', lambda x: int((x.astype(float) > 0).sum())),
                ).reset_index()
                pnl_tf['win_rate'] = (pnl_tf['wins'] / pnl_tf['trades'] * 100).round(1)

                fig_tf = go.Figure(go.Bar(
                    x=pnl_tf['timeframe'], y=pnl_tf['pnl'],
                    marker_color=['#4CAF50' if v >= 0 else '#f44336' for v in pnl_tf['pnl']],
                    text=pnl_tf['pnl'].apply(lambda x: f'${x:+.2f}'),
                    textposition='outside',
                ))
                fig_tf.update_layout(height=250, margin=dict(l=0, r=0, t=10, b=0),
                                     yaxis_title='P&L (USDC)')
                st.plotly_chart(fig_tf, use_container_width=True)

        # Posiciones abiertas
        if not btcd_open.empty:
            st.markdown(f'##### 🔓 Abiertas ({len(btcd_open)})')
            open_btcd = btcd_open[['timeframe', 'direction', 'market_slug',
                                   'entry_price', 'shares', 'cost_usdc',
                                   'btc_5m_pct', 'confidence', 'timestamp_open']].copy()
            open_btcd['entry_price'] = open_btcd['entry_price'].apply(lambda x: f'{float(x):.3f}')
            open_btcd['cost_usdc']   = open_btcd['cost_usdc'].apply(lambda x: f'${float(x):.2f}')
            open_btcd['btc_5m_pct']  = open_btcd['btc_5m_pct'].apply(lambda x: f'{float(x):+.3f}%' if pd.notna(x) else '—')
            open_btcd['confidence']  = open_btcd['confidence'].apply(lambda x: f'{float(x):.2f}' if pd.notna(x) else '—')
            open_btcd.columns = ['TF', 'Dir', 'Slug', 'Entrada', 'Shares',
                                 'Costo', 'BTC 5m %', 'Conf', 'Abierto']
            st.dataframe(open_btcd, use_container_width=True, hide_index=True)

        # Historial
        st.markdown(f'##### 🔒 Historial ({total_btcd})')
        if not btcd_closed.empty:
            hist_btcd = btcd_closed[['timeframe', 'direction', 'outcome', 'market_slug',
                                     'entry_price', 'pnl_usdc',
                                     'btc_5m_pct', 'timestamp_open', 'timestamp_close']].copy()
            hist_btcd['entry_price'] = hist_btcd['entry_price'].apply(lambda x: f'{float(x):.3f}')
            hist_btcd['pnl_usdc']    = hist_btcd['pnl_usdc'].apply(lambda x: f'${float(x):+.2f}' if pd.notna(x) else '—')
            hist_btcd['btc_5m_pct']  = hist_btcd['btc_5m_pct'].apply(lambda x: f'{float(x):+.3f}%' if pd.notna(x) else '—')
            hist_btcd.columns = ['TF', 'Dirección', 'Outcome', 'Slug', 'Entrada',
                                 'P&L', 'BTC 5m %', 'Abierto', 'Cerrado']
            st.dataframe(hist_btcd, use_container_width=True, hide_index=True)
        else:
            st.info('Sin trades cerrados de BTC Direction aún.')
    else:
        st.info('BTC Direction aún no ha ejecutado trades. El agente está corriendo y esperando señal.')
        st.caption('ℹ️ El agente evalúa mercados 5m/15m/4H/1H/Daily cada 30s. '
                   'Solo entra cuando BTC momentum > 0.15% y el precio Polymarket no lo tiene descontado.')


# ══════════════════════════════════════════════════════════════════
# TAB 7 — STOCKS AGENT (NYSE/NASDAQ Momentum)
# ══════════════════════════════════════════════════════════════════
with tab7:
    st.subheader('📈 Stocks — Momentum NYSE/NASDAQ (Alpaca)')
    st.caption('Universo: NVDA · TSLA · AAPL · META · AMZN · SPY · QQQ · GLD')

    if stocks_sessions_df.empty and stocks_trades_df.empty:
        st.info('⏳ Sin datos de stocks todavía. Inicia el agente: `systemctl start stocks-agent`')
        with st.expander('ℹ️ ¿Cómo funciona el Stocks Agent?'):
            st.markdown("""
            El **Stocks Agent** opera acciones y ETFs en NYSE/NASDAQ usando Alpaca Markets (paper trading).
            
            | Concepto | Detalle |
            |---|---|
            | **Broker** | Alpaca Markets (paper por ahora) |
            | **Universo** | NVDA, TSLA, AAPL, META, AMZN, SPY, QQQ, GLD |
            | **Estrategia** | `STOCKS_MOMENTUM`: Momentum + xsignal boost |
            | **Macro bias** | SPY/QQQ determinan si se permite BUY en acciones individuales |
            | **Riesgo por trade** | 1% del balance (~$2.20 con $220 inicial) |
            | **Exposición máx** | 8% (~$17.60 simultáneos) |
            | **Trades simultáneos** | 3 máximo |
            """)
    else:
        stocks_open = stocks_trades_df[stocks_trades_df['status'] == 'OPEN'].copy() if not stocks_trades_df.empty else pd.DataFrame()
        stocks_closed = stocks_trades_df[stocks_trades_df['status'] == 'CLOSED'].copy() if not stocks_trades_df.empty else pd.DataFrame()

        # ── Sesión activa ──────────────────────────────────────────────
        st.markdown('### 📋 Sesión Activa')
        if not stocks_sessions_df.empty:
            active_stocks = stocks_sessions_df[stocks_sessions_df['status'] == 'ACTIVE']
            if not active_stocks.empty:
                s = active_stocks.iloc[0]
                initial = float(s['initial_balance'])
                current = float(s['current_balance'])
                total_tr_s = int(s.get('total_trades', 0) or 0)
                wins_s = int(s.get('winning_trades', 0) or 0)
                wr_s = wins_s / total_tr_s * 100 if total_tr_s > 0 else 0
                pf_s = float(s.get('profit_factor', 0) or 0)
                dd_s = float(s.get('max_drawdown', 0) or 0)

                # Calculate metrics from trades if session stats are stale
                if not stocks_closed.empty:
                    total_pnl_stocks = float(stocks_closed['pnl'].astype(float).sum())
                    gross_profit_s = float(stocks_closed[stocks_closed['pnl'].astype(float) > 0]['pnl'].astype(float).sum())
                    gross_loss_s = abs(float(stocks_closed[stocks_closed['pnl'].astype(float) <= 0]['pnl'].astype(float).sum()))
                    pf_real = gross_profit_s / gross_loss_s if gross_loss_s > 0 else float('inf')
                    wins_real = int((stocks_closed['pnl'].astype(float) > 0).sum())
                    total_real = len(stocks_closed)
                    wr_real = wins_real / total_real * 100 if total_real > 0 else 0
                    # Real current balance
                    balance_real = initial + total_pnl_stocks
                else:
                    total_pnl_stocks = 0
                    pf_real = float('inf')
                    wr_real = 0
                    wins_real = 0
                    total_real = 0
                    balance_real = initial

                c1, c2, c3, c4, c5, c6 = st.columns(6)
                c1.metric('💰 Balance', f'${balance_real:,.2f}',
                          delta=f'{total_pnl_stocks:+,.2f}')
                c2.metric('📈 P&L Total', f'${total_pnl_stocks:+,.2f}')
                c3.metric('🎯 Win Rate', f'{wr_real:.1f}%' if total_real > 0 else '—',
                          help=f'{wins_real}/{total_real} cerrados')
                c4.metric('📊 Profit Factor',
                          f'{pf_real:.2f}' if pf_real != float('inf') else '∞',
                          help='Ganancias/Pérdidas brutas')
                c5.metric('📉 Max Drawdown', f'${dd_s:.2f}' if dd_s > 0 else '—')
                c6.metric('🔢 Trades', f'{total_real}',
                          help=f'{len(stocks_open)} abiertos')

                # Summary line
                st.caption(
                    f'Sesión: **{s["session_name"]}** | '
                    f'Modo: **📝 PAPER** | '
                    f'Inicio: {pd.to_datetime(s["started_at"]).strftime("%d/%m/%Y %H:%M")}'
                )

                # P&L acumulado chart
                if len(stocks_closed) > 1:
                    closed_sorted = stocks_closed.sort_values('closed_at')
                    closed_sorted['pnl_acum'] = closed_sorted['pnl'].astype(float).cumsum()
                    fig_stocks = px.area(
                        closed_sorted,
                        x='closed_at',
                        y='pnl_acum',
                        title='PnL Acumulado Stocks',
                        labels={'closed_at': 'Fecha', 'pnl_acum': 'PnL USD'},
                        color_discrete_sequence=['#00CC96'],
                    )
                    fig_stocks.update_layout(height=250, margin=dict(l=0, r=0, t=30, b=0))
                    st.plotly_chart(fig_stocks, use_container_width=True)
            else:
                st.info('Sin sesión de stocks activa.')
        else:
            st.info('Sin datos de sesiones de stocks.')

        st.markdown('---')

        # ── Open positions ──────────────────────────────────────────
        st.markdown(f'### 🔓 Posiciones Abiertas ({len(stocks_open)})')
        if not stocks_open.empty:
            open_cols = ['symbol', 'direction', 'entry_price', 'qty', 'notional',
                         'stop_loss', 'take_profit', 'strategy', 'opened_at']
            cols_available = [c for c in open_cols if c in stocks_open.columns]
            open_display = stocks_open[cols_available].copy()
            open_display['entry_price'] = open_display['entry_price'].apply(lambda x: f'${float(x):,.2f}' if pd.notna(x) else '—')
            open_display['notional'] = open_display['notional'].apply(lambda x: f'${float(x):,.2f}' if pd.notna(x) else '—')
            open_display['stop_loss'] = open_display['stop_loss'].apply(lambda x: f'${float(x):,.2f}' if pd.notna(x) else '—')
            open_display['take_profit'] = open_display['take_profit'].apply(lambda x: f'${float(x):,.2f}' if pd.notna(x) else '—')
            st.dataframe(
                open_display.rename(columns={
                    'symbol': 'Símbolo',
                    'direction': 'Dir',
                    'entry_price': 'Entry $',
                    'qty': 'Qty',
                    'notional': 'Notional $',
                    'stop_loss': 'SL $',
                    'take_profit': 'TP $',
                    'strategy': 'Estrategia',
                    'opened_at': 'Abierto',
                }),
                use_container_width=True,
                height=200,
            )
        else:
            st.info('Sin posiciones abiertas actualmente.')

        st.markdown('---')

        # ── Closed positions ────────────────────────────────────────
        st.markdown(f'### 🔒 Historial ({len(stocks_closed)})')
        if not stocks_closed.empty:
            # KPIs row
            n_tp_s = len(stocks_closed[stocks_closed['exit_reason'] == 'TP'])
            n_sl_s = len(stocks_closed[stocks_closed['exit_reason'] == 'SL'])
            n_other_s = len(stocks_closed) - n_tp_s - n_sl_s

            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric('🎯 Take Profit', n_tp_s)
            c2.metric('🛑 Stop Loss', n_sl_s)
            c3.metric('📋 Otros', n_other_s)
            c4.metric('✅ Win Rate', f'{wr_real:.1f}%' if total_real > 0 else '—')
            c5.metric('📊 Profit Factor',
                      f'{pf_real:.2f}' if pf_real != float('inf') else '∞')

            # Charts row
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown('##### P&L por Símbolo')
                pnl_sym = stocks_closed.groupby('symbol')['pnl'].apply(
                    lambda x: x.astype(float).sum()
                ).reset_index()
                pnl_sym.columns = ['symbol', 'pnl_total']
                pnl_sym['color'] = pnl_sym['pnl_total'].apply(
                    lambda x: '#4CAF50' if x > 0 else '#f44336'
                )
                fig_sym = go.Figure(go.Bar(
                    x=pnl_sym['symbol'], y=pnl_sym['pnl_total'],
                    marker_color=pnl_sym['color'],
                    text=pnl_sym['pnl_total'].apply(lambda x: f'${x:+,.2f}'),
                    textposition='outside',
                ))
                fig_sym.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0),
                                      yaxis_title='P&L (USD)')
                st.plotly_chart(fig_sym, use_container_width=True)

            with col_b:
                st.markdown('##### Motivo de Cierre')
                reason_counts_s = stocks_closed['exit_reason'].value_counts()
                colors_rs = {'TP': '#4CAF50', 'SL': '#f44336',
                             'TRAILING_STOP': '#2196F3'}
                fig_rs = go.Figure(go.Pie(
                    labels=reason_counts_s.index, values=reason_counts_s.values,
                    marker=dict(colors=[colors_rs.get(r, '#999') for r in reason_counts_s.index]),
                    hole=0.4,
                ))
                fig_rs.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0))
                st.plotly_chart(fig_rs, use_container_width=True)

            # P&L por estrategia
            st.markdown('##### P&L por Estrategia')
            if 'strategy' in stocks_closed.columns:
                pnl_strat_s = stocks_closed.groupby('strategy').agg(
                    trades=('pnl', 'count'),
                    pnl_total=('pnl', lambda x: x.astype(float).sum()),
                    wins=('pnl', lambda x: (x.astype(float) > 0).sum()),
                ).reset_index()
                pnl_strat_s['win_rate'] = (pnl_strat_s['wins'] / pnl_strat_s['trades'] * 100).round(1)
                st.dataframe(
                    pnl_strat_s.rename(columns={
                        'strategy': 'Estrategia', 'trades': 'Trades',
                        'pnl_total': 'P&L Total', 'wins': 'Ganados',
                        'win_rate': 'Win Rate',
                    }),
                    use_container_width=True, hide_index=True,
                )

            # Full history table
            st.markdown('##### Historial Completo')
            hist_cols_s = ['symbol', 'direction', 'entry_price', 'exit_price',
                           'pnl', 'exit_reason', 'strategy', 'opened_at', 'closed_at']
            hist_available = [c for c in hist_cols_s if c in stocks_closed.columns]
            hist_display = stocks_closed[hist_available].copy()
            hist_display['entry_price'] = hist_display['entry_price'].apply(lambda x: f'${float(x):,.2f}' if pd.notna(x) else '—')
            hist_display['exit_price'] = hist_display['exit_price'].apply(lambda x: f'${float(x):,.2f}' if pd.notna(x) else '—')
            hist_display['pnl'] = hist_display['pnl'].apply(
                lambda x: f'${float(x):+,.2f}' if pd.notna(x) else '—')
            st.dataframe(
                hist_display.rename(columns={
                    'symbol': 'Símbolo', 'direction': 'Dir',
                    'entry_price': 'Entry', 'exit_price': 'Exit',
                    'pnl': 'P&L', 'exit_reason': 'Cierre',
                    'strategy': 'Estrategia',
                    'opened_at': 'Abierto', 'closed_at': 'Cerrado',
                }),
                use_container_width=True, hide_index=True,
                height=300,
            )
        else:
            st.info('Sin trades cerrados todavía.')

        # ── Explanation ─────────────────────────────────────────────
        with st.expander('ℹ️ Cómo funciona el Stocks Agent'):
            st.markdown("""
            **Operamos acciones y ETFs de NYSE/NASDAQ con momentum + xsignals.**

            | Concepto | Detalle |
            |---|---|
            | **Momentum** | Compramos cuando EMA20 > EMA50, RSI en zona 50-65, volumen confirma, y precio por encima de VWAP |
            | **xsignal boost** | Si @aguti00 en X publica una señal alineada para el ticker (conf ≥ 55), el score recibe +15 puntos |
            | **Macro bias** | Si SPY y QQQ están ambos en tendencia bajista, se bloquean BUY en todas las acciones individuales |
            | **Salida** | TP fijo, SL fijo, o cierre manual. El trailing aún no está implementado en stocks. |
            | **Universo** | 8 activos: NVDA, TSLA, AAPL, META, AMZN, SPY, QQQ, GLD |

            **Estrategias:**
            - `STOCKS_MOMENTUM`: Acciones individuales (NVDA, TSLA, AAPL, META, AMZN)
            - `STOCKS_TREND_ETF`: ETFs (SPY, QQQ, GLD) con reglas similares

            **Estado actual:** Paper trading con Alpaca. Se activará live cuando:
            - 4 semanas paper con PF ≥ 1.3
            - 20+ trades cerrados
            - Max DD ≤ 8% en paper
            """)

# ══════════════════════════════════════════════════════════════════
# TAB 8 — PANEL EDUCATIVO
# ══════════════════════════════════════════════════════════════════
with tab8:
    st.subheader('📚 Centro de Aprendizaje')
    st.markdown('Aquí puedes aprender los conceptos clave del trading algorítmico '
                'mientras ves cómo el sistema los aplica en tiempo real.')

    # ── Glossary ──
    st.markdown('#### 📖 Glosario de Términos')
    for term, definition in GLOSSARY.items():
        with st.expander(f'**{term}**'):
            st.markdown(definition)

    st.markdown('---')

    # ── Anatomy of a trade ──
    st.markdown('#### 🔬 Anatomía de un Trade')
    st.markdown(
        'Cada trade del sistema sigue este flujo:\n\n'
        '```\n'
        '1. 📡 SEÑAL      → El scanner detecta un patrón técnico (ej: EMA cruce alcista)\n'
        '2. 🧠 ESTRATEGIA → Combina señales y genera oportunidad con score\n'
        '3. 🤖 IA         → GPT valida consistencia de la señal\n'
        '4. 🛡️ RIESGO     → 10 reglas verifican que es seguro operar\n'
        '5. ✅ EJECUCIÓN  → Se abre el trade con Entry, SL y TP calculados\n'
        '6. 👁️ MONITOR    → Cada 60s revisa precio vs SL/TP/Trailing\n'
        '7. 🔚 CIERRE     → SL (pérdida limitada), TP (ganancia) o Trailing (ganancia parcial)\n'
        '```'
    )

    # Example with real trade
    if not closed_trades.empty:
        st.markdown('##### Ejemplo Real (último trade cerrado)')
        ex = closed_trades.iloc[0]
        entry = float(ex['entry_price'])
        sl = float(ex['stop_loss'])
        tp = float(ex['take_profit'])
        exit_p = float(ex['exit_price']) if pd.notna(ex['exit_price']) else entry
        risk = abs(entry - sl)
        pnl_val = float(ex['pnl'])
        r_multiple = pnl_val / (risk * float(ex['position_size'])) if risk > 0 and float(ex['position_size']) > 0 else 0

        c1, c2 = st.columns([1, 2])
        with c1:
            st.markdown(f"""
            | Concepto | Valor |
            |---|---|
            | **Asset** | {ex['asset']} |
            | **Lado** | {ex['side']} |
            | **Estrategia** | {ex.get('strategy', '—')} |
            | **Entry** | ${entry:,.2f} |
            | **Stop Loss** | ${sl:,.2f} |
            | **Take Profit** | ${tp:,.2f} |
            | **Exit** | ${exit_p:,.2f} |
            | **P&L** | ${pnl_val:+,.2f} |
            | **R Múltiple** | {r_multiple:+.2f}R |
            | **Cierre** | {ex['close_reason']} |
            """)
        with c2:
            # Visual trade diagram
            fig_trade = go.Figure()
            prices = [sl, entry, tp]
            labels = ['🛑 SL', '➡️ Entry', '🎯 TP']
            colors_bar = ['#f44336', '#2196F3', '#4CAF50']
            fig_trade.add_trace(go.Bar(
                x=labels, y=prices, marker_color=colors_bar,
                text=[f'${p:,.2f}' for p in prices], textposition='outside',
            ))
            # Exit marker
            fig_trade.add_hline(y=exit_p, line_dash='dash', line_color='orange',
                                annotation_text=f'Exit ${exit_p:,.2f}')
            fig_trade.update_layout(
                height=280, margin=dict(l=0, r=0, t=10, b=0),
                yaxis_title='Precio (USD)',
                title=f"{'✅ Ganó' if pnl_val > 0 else '❌ Perdió'} ${abs(pnl_val):,.2f} ({r_multiple:+.2f}R)",
            )
            st.plotly_chart(fig_trade, use_container_width=True)

    st.markdown('---')

    # ── Why rejected? ──
    st.markdown('#### ❌ ¿Por qué se rechazan trades?')
    st.markdown(
        'No todas las oportunidades se ejecutan. El **Risk Manager** tiene 10 reglas '
        'que protegen tu capital. Aquí están las razones de rechazo más comunes:'
    )
    for reason, explanation in RISK_REJECTION_EXPLANATIONS.items():
        with st.expander(f'**{reason}**'):
            st.markdown(explanation)

    st.markdown('---')

    # ── System rules summary ──
    st.markdown('#### 🛡️ Reglas del Sistema')
    st.markdown("""
    | Regla | Valor | ¿Por qué? |
    |---|---|---|
    | Riesgo por trade | 1% del balance | Si pierdes, pierdes poco. 100 trades seguidos perdiendo = -63% (no -100%) |
    | Exposición máxima | 5% del balance | Limita el riesgo total en un momento dado |
    | Trades simultáneos | 3 máximo | Diversifica entre activos, no pone todo en uno |
    | Drawdown halt | 10% | Si el sistema pierde mucho seguido, se detiene para revisar |
    | Ratio R:R mínimo | 1.5 | Solo toma trades donde la ganancia potencial > 1.5× la pérdida potencial |
    | Cooldown post SL | 30 minutos | Evita re-entrar al mismo trade impulsivamente |
    | Trailing stop | Progresivo por escalones | Protege ganancias a medida que el precio avanza |
    """)

    st.markdown('---')
    st.caption('💡 Tip: Pasa el mouse sobre los ℹ️ en las métricas de otros tabs para ver explicaciones rápidas.')

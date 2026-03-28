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
trades_df = query('SELECT * FROM trades ORDER BY timestamp_open DESC LIMIT 200')
signals_df = query('SELECT * FROM signals ORDER BY timestamp DESC LIMIT 500')
claude_df = query('SELECT * FROM claude_explanations ORDER BY timestamp DESC LIMIT 100')

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
st.sidebar.title('🤖 Trading Agent v2.0')
st.sidebar.markdown(f"**Entorno:** `{os.getenv('ENVIRONMENT', 'dev')}`")
st.sidebar.markdown(f"**Modo:** `{'📝 PAPER' if os.getenv('PAPER_TRADING','true')=='true' else '🔴 LIVE'}`")
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
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    '📊 Portfolio', '💹 Trades', '📡 Señales', '🤖 IA', '📚 Aprende'
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


# ══════════════════════════════════════════════════════════════════
# TAB 5 — PANEL EDUCATIVO
# ══════════════════════════════════════════════════════════════════
with tab5:
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

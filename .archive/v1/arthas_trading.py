#!/usr/bin/env python3
"""
arthas_trading.py — CLI para que Arthas consulte el Trading Agent via Telegram.
Ejecutar: python3 /opt/trading/scripts/arthas_trading.py <comando>

Comandos:
  status      → Estado general del sistema (balance, trades, señales)
  portfolio   → Detalle del portfolio actual
  trades      → Trades abiertos y últimos cerrados
  signals     → Últimas señales detectadas
  prices      → Precios actuales de todos los activos
  metrics     → Métricas de paper trading (win rate, Sharpe, etc.)
  scan        → Forzar un escaneo de mercado ahora
  report      → Reporte completo (todo junto, ideal para briefing)
  help        → Mostrar esta ayuda
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

sys.path.insert(0, '/opt/trading')
load_dotenv('/opt/trading/config/.env')

_db_url = (
    f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
    f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT', '5432')}"
    f"/{os.getenv('POSTGRES_DB')}"
)
_engine = create_engine(_db_url)


def _get_active_session(conn):
    row = conn.execute(
        text("SELECT * FROM paper_sessions WHERE status = 'ACTIVE' ORDER BY started_at DESC LIMIT 1")
    ).fetchone()
    return row


def cmd_status():
    """Estado general del sistema."""
    with _engine.connect() as conn:
        session = _get_active_session(conn)
        if session is None:
            print('No hay una paper session activa.')
            return
        pf = conn.execute(
            text('SELECT * FROM portfolio WHERE timestamp >= :session_start ORDER BY timestamp DESC LIMIT 1'),
            {'session_start': session.started_at},
        ).fetchone()
        halt_stats = conn.execute(text(
            "SELECT "
            "COALESCE(BOOL_OR(drawdown_pct >= 0.10), false) AS halt_triggered, "
            "COALESCE(MAX(GREATEST(total_balance, COALESCE(peak_balance, total_balance))), 0) AS historical_peak, "
            "COALESCE(MAX(drawdown_pct), 0) AS max_stored_drawdown "
            "FROM portfolio WHERE timestamp >= :session_start"
        ), {'session_start': session.started_at}).fetchone()
        open_trades = conn.execute(text(
            "SELECT COUNT(*) FROM trades WHERE status='OPEN' AND paper_trade=true AND timestamp_open >= :session_start"
        ), {'session_start': session.started_at}).fetchone()
        open_trades = open_trades[0]
        total_trades = conn.execute(text(
            "SELECT COUNT(*) FROM trades WHERE paper_trade=true AND timestamp_open >= :session_start"
        ), {'session_start': session.started_at}).scalar()
        signal_count = conn.execute(text(
            "SELECT COUNT(*) FROM signals WHERE timestamp > NOW() - INTERVAL '1 hour'"
        )).scalar()
        candles = conn.execute(text("SELECT COUNT(*) FROM market_data")).scalar()

    balance = float(pf.total_balance) if pf else 10000.0
    historical_peak = float(halt_stats.historical_peak) if halt_stats and halt_stats.historical_peak else balance
    dd = ((historical_peak - balance) / historical_peak) * 100 if historical_peak > 0 else 0
    exp = float(pf.exposure_pct) * 100 if pf else 0
    halt_triggered = bool(halt_stats.halt_triggered) if halt_stats else False
    max_dd = max(float(halt_stats.max_stored_drawdown) * 100 if halt_stats else 0, dd)
    last_breach = getattr(pf, 'last_halt_breach_at', None) if pf else None
    paper_mode = os.getenv('PAPER_TRADING', 'true').lower() == 'true'
    auto_resume_eta = None
    auto_resume_ready = False
    if halt_triggered and paper_mode:
        with _engine.connect() as conn:
            row = conn.execute(text(
                "SELECT MAX(timestamp) AS ts FROM portfolio "
                "WHERE drawdown_pct >= 0.10 AND timestamp >= :session_start"
            ), {'session_start': session.started_at}).fetchone()
        last_breach = row.ts if row else None
        if last_breach is not None:
            remaining = (last_breach + timedelta(hours=3)) - datetime.now(timezone.utc)
            auto_resume_eta = max(int(remaining.total_seconds() // 60), 0)
            auto_resume_ready = auto_resume_eta == 0 and dd <= 9.0

    if halt_triggered:
        recommendation = 'MANTENER HALT'
        if paper_mode and auto_resume_ready:
            recommendation = 'AUTO-RESUME PAPER ELEGIBLE'
    else:
        recommendation = 'OPERACIÓN NORMAL'

    print("⚔️ ARTHAS TRADING AGENT — STATUS")
    print("═" * 40)
    print(f"🧪 Session:        {session.session_name}")
    print(f"💰 Balance:        ${balance:,.2f}")
    print(f"📉 Drawdown:       {dd:.1f}%")
    print(f"📉 Max DD hist.:   {max_dd:.1f}%")
    print(f"📊 Exposición:     {exp:.1f}%")
    print(f"🔓 Trades abiertos: {open_trades}")
    print(f"📈 Trades totales:  {total_trades}")
    print(f"📡 Señales (1h):    {signal_count}")
    print(f"🕯️ Velas en DB:     {candles:,}")
    print(f"⛔ Halt histórico:  {'SÍ' if halt_triggered else 'NO'}")
    print(f"🤖 Recomendación:   {recommendation}")
    if halt_triggered and paper_mode:
        if auto_resume_ready:
            print("⏳ Auto-resume:     listo")
        elif auto_resume_eta is not None:
            reason = 'esperando cuarentena' if auto_resume_eta > 0 else 'dd todavía demasiado alto'
            suffix = f'en {auto_resume_eta} min' if auto_resume_eta > 0 else 'bloqueado'
            print(f"⏳ Auto-resume:     {suffix} ({reason})")
    print(f"⚙️ Modo:            {'PAPER 📝' if os.getenv('PAPER_TRADING','true')=='true' else 'LIVE 🔴'}")
    print(f"🕐 Hora servidor:   {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")


def cmd_portfolio():
    """Detalle del portfolio."""
    with _engine.connect() as conn:
        session = _get_active_session(conn)
        if session is None:
            print('No hay una paper session activa.')
            return
        rows = conn.execute(text(
            'SELECT timestamp, total_balance, exposure_pct, drawdown_pct, pnl_day '
            'FROM portfolio WHERE timestamp >= :session_start ORDER BY timestamp DESC LIMIT 5'
        ), {'session_start': session.started_at}).fetchall()

    if not rows:
        print("Sin datos de portfolio aún.")
        return

    print("💼 PORTFOLIO — Últimas 5 snapshots")
    print("═" * 55)
    for r in rows:
        ts = r.timestamp.strftime('%m-%d %H:%M') if r.timestamp else '?'
        print(f"  {ts}  |  ${float(r.total_balance):>10,.2f}  |  "
              f"exp {float(r.exposure_pct)*100:>4.1f}%  |  dd {float(r.drawdown_pct)*100:>4.1f}%")


def cmd_trades():
    """Trades abiertos y últimos cerrados."""
    with _engine.connect() as conn:
        session = _get_active_session(conn)
        if session is None:
            print('No hay una paper session activa.')
            return
        open_t = pd.read_sql(text(
            "SELECT asset, side, strategy, entry_price, stop_loss, take_profit, "
            "position_size, timestamp_open FROM trades WHERE status='OPEN' "
            "AND timestamp_open >= :session_start "
            "ORDER BY timestamp_open DESC"
        ), conn, params={'session_start': session.started_at})
        closed_t = pd.read_sql(text(
            "SELECT asset, side, strategy, entry_price, pnl, status, timestamp_open "
            "FROM trades WHERE status != 'OPEN' AND timestamp_open >= :session_start "
            "ORDER BY timestamp_open DESC LIMIT 5"
        ), conn, params={'session_start': session.started_at})

    print("📈 TRADES ABIERTOS")
    print("═" * 55)
    if open_t.empty:
        print("  (ninguno)")
    else:
        for _, t in open_t.iterrows():
            print(f"  {t['asset']} {t['side']} via {t['strategy']}")
            print(f"    Entry: ${float(t['entry_price']):,.2f}  |  "
                  f"SL: ${float(t['stop_loss']):,.2f}  |  TP: ${float(t['take_profit']):,.2f}")
            print(f"    Size: {float(t['position_size']):.6f}  |  Abierto: {t['timestamp_open']}")
            print()

    if not closed_t.empty:
        print("\n📕 ÚLTIMOS TRADES CERRADOS")
        print("═" * 55)
        for _, t in closed_t.iterrows():
            pnl = float(t['pnl']) if t['pnl'] is not None else 0
            emoji = "✅" if pnl > 0 else "❌"
            print(f"  {emoji} {t['asset']} {t['side']} → P&L: ${pnl:+,.2f} ({t['status']})")


def cmd_signals():
    """Últimas señales del scanner."""
    with _engine.connect() as conn:
        sigs = pd.read_sql(text(
            "SELECT asset, timeframe, signal_type, direction, strength, "
            "price_at_signal, timestamp FROM signals "
            "ORDER BY timestamp DESC LIMIT 15"
        ), conn)

    print("📡 ÚLTIMAS 15 SEÑALES")
    print("═" * 60)
    if sigs.empty:
        print("  Sin señales recientes. Ejecuta un scan primero.")
        return
    for _, s in sigs.iterrows():
        d_emoji = "🟢" if s['direction'] == 'BUY' else ("🔴" if s['direction'] == 'SELL' else "⚪")
        ts = s['timestamp']
        if hasattr(ts, 'strftime'):
            ts = ts.strftime('%H:%M')
        else:
            ts = str(ts)[-8:-3]
        print(f"  {d_emoji} {s['asset']:>3}/{s['timeframe']:<3}  "
              f"{s['signal_type']:<18}  str={float(s['strength']):.2f}  "
              f"@ ${float(s['price_at_signal']):>10,.2f}  [{ts}]")


def cmd_prices():
    """Precios actuales de todos los activos."""
    from data.market_feed import ASSET_MAP

    with _engine.connect() as conn:
        for asset in ASSET_MAP:
            row = conn.execute(text(
                "SELECT close, timestamp FROM market_data "
                "WHERE asset = :a ORDER BY timestamp DESC LIMIT 1"
            ), {'a': asset}).fetchone()
            if row:
                ts = row.timestamp.strftime('%H:%M') if hasattr(row.timestamp, 'strftime') else str(row.timestamp)
                print(f"  💲 {asset:<4}  ${float(row.close):>12,.2f}  [{ts} UTC]")
            else:
                print(f"  ❓ {asset:<4}  Sin datos")


def cmd_metrics():
    """Métricas de paper trading."""
    with _engine.connect() as conn:
        session = _get_active_session(conn)
        if session is None:
            print('No hay una paper session activa.')
            return
        closed = conn.execute(text(
            "SELECT COUNT(*) FROM trades WHERE paper_trade=true AND status='CLOSED' AND timestamp_open >= :session_start"
        ), {'session_start': session.started_at}).scalar()
        open_c = conn.execute(text(
            "SELECT COUNT(*) FROM trades WHERE paper_trade=true AND status='OPEN' AND timestamp_open >= :session_start"
        ), {'session_start': session.started_at}).scalar()

    if closed < 10:
        print(f"📊 MÉTRICAS — Aún no hay suficientes trades cerrados")
        print(f"  Trades cerrados: {closed}  (necesita ≥10 para métricas)")
        print(f"  Trades abiertos: {open_c}")
        print(f"  Sigue acumulando trades en paper mode 📝")
        return

    # Delegate to full metrics module
    from tests.paper.metrics import compute_metrics
    compute_metrics(str(session.id))


def cmd_scan():
    """Forzar escaneo de mercado ahora."""
    print("🔍 Escaneando mercados... (esto toma ~30s)")
    from agents.market_scanner import MarketScanner
    scanner = MarketScanner()
    signals = scanner.scan()
    print(f"\n✅ Scan completo: {len(signals)} señales detectadas")
    if signals:
        for s in signals[:10]:
            d_emoji = "🟢" if s['direction'] == 'BUY' else ("🔴" if s['direction'] == 'SELL' else "⚪")
            print(f"  {d_emoji} {s['asset']}/{s['timeframe']}  {s['signal_type']}  "
                  f"str={s['strength']:.2f}")
        if len(signals) > 10:
            print(f"  ... y {len(signals)-10} más")


def cmd_report():
    """Reporte completo."""
    cmd_status()
    print()
    cmd_prices()
    print()
    cmd_trades()
    print()
    cmd_signals()


def cmd_poly():
    """Estado del portfolio Polymarket."""
    with _engine.connect() as conn:
        session = conn.execute(
            text("SELECT * FROM poly_sessions WHERE status = 'ACTIVE' ORDER BY started_at DESC LIMIT 1")
        ).fetchone()
        if session is None:
            print("🔮 POLYMARKET — No hay sesión activa")
            return
        session = dict(session._mapping)

        open_pos = conn.execute(
            text("""
                SELECT question, side, entry_price, shares, cost_basis
                FROM poly_positions
                WHERE status = 'OPEN' AND session_name = :s
                ORDER BY timestamp_open DESC
            """),
            {'s': session['session_name']},
        ).fetchall()

        closed_stats = conn.execute(
            text("""
                SELECT COUNT(*) as total,
                       COUNT(*) FILTER(WHERE pnl > 0) as wins,
                       COALESCE(SUM(pnl), 0) as total_pnl
                FROM poly_positions
                WHERE status = 'CLOSED' AND session_name = :s
            """),
            {'s': session['session_name']},
        ).fetchone()

        market_count = conn.execute(
            text("SELECT COUNT(*) FROM poly_markets WHERE active = true")
        ).scalar()

    balance = float(session['current_balance'])
    initial = float(session['initial_balance'])
    total_pnl = float(session.get('total_pnl', 0))
    total_closed = int(closed_stats[0]) if closed_stats else 0
    wins = int(closed_stats[1]) if closed_stats else 0
    wr = (wins / total_closed * 100) if total_closed > 0 else 0
    exposure = sum(float(p.cost_basis) for p in open_pos)

    print("🔮 POLYMARKET AGENT — STATUS")
    print("═" * 45)
    print(f"📋 Session:         {session['session_name']}")
    print(f"💰 Balance:         ${balance:,.2f} (inicial: ${initial:,.2f})")
    print(f"📊 PnL total:       ${total_pnl:+,.2f}")
    print(f"📈 Exposición:      ${exposure:,.2f} ({exposure/balance*100:.1f}%)" if balance > 0 else "")
    print(f"🔓 Posiciones:      {len(open_pos)} abiertas")
    print(f"📕 Cerradas:        {total_closed} (WR: {wr:.0f}%)")
    print(f"🌐 Mercados activos: {market_count}")
    print(f"⚙️ Modo:            PAPER 📝")

    if open_pos:
        print(f"\n📌 POSICIONES ABIERTAS")
        print("─" * 45)
        for p in open_pos:
            side_emoji = "🟢" if p.side == 'YES' else "🔴"
            q = p.question[:55] if p.question else '?'
            print(f"  {side_emoji} {p.side} — {q}")
            print(f"     Entry: {float(p.entry_price):.3f} | "
                  f"Shares: {float(p.shares):.0f} | "
                  f"Cost: ${float(p.cost_basis):.2f}")


def cmd_polyreport():
    """Reporte completo Polymarket."""
    cmd_poly()
    print()

    with _engine.connect() as conn:
        session = conn.execute(
            text("SELECT * FROM poly_sessions WHERE status = 'ACTIVE' ORDER BY started_at DESC LIMIT 1")
        ).fetchone()
        if session is None:
            return
        session = dict(session._mapping)

        closed = conn.execute(
            text("""
                SELECT question, side, entry_price, exit_price, pnl, pnl_pct, close_reason
                FROM poly_positions
                WHERE status = 'CLOSED' AND session_name = :s
                ORDER BY timestamp_close DESC LIMIT 10
            """),
            {'s': session['session_name']},
        ).fetchall()

    if closed:
        print("📕 ÚLTIMAS POSICIONES CERRADAS")
        print("─" * 50)
        for c in closed:
            pnl = float(c.pnl) if c.pnl else 0
            emoji = "✅" if pnl > 0 else "❌"
            q = c.question[:45] if c.question else '?'
            print(f"  {emoji} {c.side} — {q}")
            print(f"     Entry: {float(c.entry_price):.3f} → "
                  f"Exit: {float(c.exit_price):.3f} | "
                  f"PnL: ${pnl:+.2f} ({float(c.pnl_pct):+.1f}%) | "
                  f"{c.close_reason}")
    else:
        print("📕 Sin posiciones cerradas aún")


def cmd_help():
    """Muestra ayuda."""
    print("⚔️ ARTHAS TRADING AGENT — Comandos disponibles")
    print("═" * 50)
    print("  ── CRYPTO ──")
    print("  status      Estado general (balance, trades, señales)")
    print("  portfolio   Historial de snapshots del portfolio")
    print("  trades      Trades abiertos y últimos cerrados")
    print("  signals     Últimas 15 señales del scanner")
    print("  prices      Precios actuales de BTC/ETH/SOL/XAU/XAG")
    print("  metrics     Métricas de paper trading")
    print("  scan        Forzar un escaneo de mercado ahora")
    print("  report      Reporte completo (todo junto)")
    print("  ── POLYMARKET ──")
    print("  poly / poly_status  Estado del portfolio Polymarket")
    print("  polyreport          Reporte completo Polymarket")
    print("  help        Esta ayuda")
    print()
    print("Uso: python3 /opt/trading/scripts/arthas_trading.py <comando>")


COMMANDS = {
    'status': cmd_status,
    'portfolio': cmd_portfolio,
    'trades': cmd_trades,
    'signals': cmd_signals,
    'prices': cmd_prices,
    'metrics': cmd_metrics,
    'scan': cmd_scan,
    'report': cmd_report,
    'poly': cmd_poly,
    'poly_status': cmd_poly,
    'polyreport': cmd_polyreport,
    'help': cmd_help,
}

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'help'
    fn = COMMANDS.get(cmd)
    if fn:
        fn()
    else:
        print(f"❌ Comando desconocido: '{cmd}'")
        cmd_help()

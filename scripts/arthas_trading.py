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
from datetime import datetime, timezone

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


def cmd_status():
    """Estado general del sistema."""
    with _engine.connect() as conn:
        pf = conn.execute(text('SELECT * FROM portfolio ORDER BY timestamp DESC LIMIT 1')).fetchone()
        open_trades = conn.execute(text("SELECT COUNT(*) FROM trades WHERE status='OPEN'")).scalar()
        total_trades = conn.execute(text("SELECT COUNT(*) FROM trades")).scalar()
        signal_count = conn.execute(text(
            "SELECT COUNT(*) FROM signals WHERE timestamp > NOW() - INTERVAL '1 hour'"
        )).scalar()
        candles = conn.execute(text("SELECT COUNT(*) FROM market_data")).scalar()

    balance = float(pf.total_balance) if pf else 10000.0
    dd = float(pf.drawdown_pct) * 100 if pf else 0
    exp = float(pf.exposure_pct) * 100 if pf else 0

    print("⚔️ ARTHAS TRADING AGENT — STATUS")
    print("═" * 40)
    print(f"💰 Balance:        ${balance:,.2f}")
    print(f"📉 Drawdown:       {dd:.1f}%")
    print(f"📊 Exposición:     {exp:.1f}%")
    print(f"🔓 Trades abiertos: {open_trades}")
    print(f"📈 Trades totales:  {total_trades}")
    print(f"📡 Señales (1h):    {signal_count}")
    print(f"🕯️ Velas en DB:     {candles:,}")
    print(f"⚙️ Modo:            {'PAPER 📝' if os.getenv('PAPER_TRADING','true')=='true' else 'LIVE 🔴'}")
    print(f"🕐 Hora servidor:   {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")


def cmd_portfolio():
    """Detalle del portfolio."""
    with _engine.connect() as conn:
        rows = conn.execute(text(
            'SELECT timestamp, total_balance, exposure_pct, drawdown_pct, pnl_day '
            'FROM portfolio ORDER BY timestamp DESC LIMIT 5'
        )).fetchall()

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
        open_t = pd.read_sql(text(
            "SELECT asset, side, strategy, entry_price, stop_loss, take_profit, "
            "position_size, timestamp_open FROM trades WHERE status='OPEN' "
            "ORDER BY timestamp_open DESC"
        ), conn)
        closed_t = pd.read_sql(text(
            "SELECT asset, side, strategy, entry_price, pnl, status, timestamp_open "
            "FROM trades WHERE status != 'OPEN' ORDER BY timestamp_open DESC LIMIT 5"
        ), conn)

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
        closed = conn.execute(text(
            "SELECT COUNT(*) FROM trades WHERE paper_trade=true AND status='CLOSED'"
        )).scalar()
        open_c = conn.execute(text(
            "SELECT COUNT(*) FROM trades WHERE paper_trade=true AND status='OPEN'"
        )).scalar()

    if closed < 10:
        print(f"📊 MÉTRICAS — Aún no hay suficientes trades cerrados")
        print(f"  Trades cerrados: {closed}  (necesita ≥10 para métricas)")
        print(f"  Trades abiertos: {open_c}")
        print(f"  Sigue acumulando trades en paper mode 📝")
        return

    # Delegate to full metrics module
    from tests.paper.metrics import compute_metrics
    compute_metrics()


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


def cmd_help():
    """Muestra ayuda."""
    print("⚔️ ARTHAS TRADING AGENT — Comandos disponibles")
    print("═" * 50)
    print("  status      Estado general (balance, trades, señales)")
    print("  portfolio   Historial de snapshots del portfolio")
    print("  trades      Trades abiertos y últimos cerrados")
    print("  signals     Últimas 15 señales del scanner")
    print("  prices      Precios actuales de BTC/ETH/SOL/XAU/XAG")
    print("  metrics     Métricas de paper trading")
    print("  scan        Forzar un escaneo de mercado ahora")
    print("  report      Reporte completo (todo junto)")
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

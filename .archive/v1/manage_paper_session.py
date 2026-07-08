#!/usr/bin/env python3
"""Gestión operativa de paper sessions (crypto y polymarket)."""
import os
import sys

sys.path.insert(0, '/opt/trading')

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from core.paper_session_manager import PaperSessionManager
from core.poly_session_manager import PolySessionManager
from tests.paper.metrics import compute_metrics

load_dotenv('/opt/trading/config/.env')


def _db_url() -> str:
    return (
        f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
        f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT', '5432')}"
        f"/{os.getenv('POSTGRES_DB')}"
    )


def cmd_status():
    manager = PaperSessionManager(_db_url())
    session = manager.get_active_session()
    if not session:
        print('No hay sesión activa.')
        return
    print(f"ACTIVE: {session['session_name']} started_at={session['started_at']}")
    compute_metrics(str(session['id']))


def cmd_rollover():
    db_url = _db_url()
    manager = PaperSessionManager(db_url)
    engine = create_engine(db_url)
    session = manager.get_active_session()
    if not session:
        new_session = manager.create_session(initial_balance=10000.0)
        print(f"Nueva sesión creada: {new_session['session_name']}")
        return

    with engine.connect() as conn:
        open_trades = conn.execute(
            text('SELECT COUNT(*) FROM trades WHERE status = \'OPEN\' AND timestamp_open >= :session_start'),
            {'session_start': session['started_at']},
        ).scalar() or 0
    if open_trades:
        raise RuntimeError('No se puede rotar la sesión con trades abiertos.')

    with engine.connect() as conn:
        final_balance = conn.execute(
            text(
                'SELECT total_balance FROM portfolio '
                'WHERE timestamp >= :session_start ORDER BY timestamp DESC LIMIT 1'
            ),
            {'session_start': session['started_at']},
        ).scalar() or float(session['initial_balance'])
        total_trades = conn.execute(
            text(
                'SELECT COUNT(*) FROM trades WHERE paper_trade = true '
                'AND timestamp_open >= :session_start'
            ),
            {'session_start': session['started_at']},
        ).scalar() or 0
        winning_trades = conn.execute(
            text(
                'SELECT COUNT(*) FROM trades WHERE paper_trade = true AND pnl > 0 '
                'AND timestamp_open >= :session_start'
            ),
            {'session_start': session['started_at']},
        ).scalar() or 0

    compute_metrics(str(session['id']))
    new_session = manager.rollover_session(session['id'], status='FAILED', next_initial_balance=10000.0)
    print(f"Sesión cerrada: {session['session_name']} -> FAILED")
    print(f"Nueva sesión creada: {new_session['session_name']}")


# ────────────────────────── POLYMARKET ──────────────────────────

def cmd_poly_status():
    mgr = PolySessionManager(_db_url())
    session = mgr.get_active_session()
    if not session:
        print('No hay sesión Polymarket activa.')
        return
    summary = mgr.summarize_session(str(session['id']))
    s = summary
    open_count = mgr._count_open_positions(str(session['id']))
    dd = mgr.check_drawdown_halt(str(session['id']))
    print(f"POLY ACTIVE: {session['session_name']}  started_at={session['started_at']}")
    print(f"  Balance: ${float(session['current_balance']):.2f}  (initial ${float(session['initial_balance']):.2f})")
    print(f"  Trades: {s['total_trades']}  W={s['winning_trades']}  L={s['losing_trades']}")
    print(f"  WR: {s['win_rate']:.1f}%   PF: {s['profit_factor']:.2f}")
    print(f"  PnL: ${s['total_pnl']:+.2f}   DD: {dd['current_dd']:.1f}%")
    print(f"  Open positions: {open_count}")


def cmd_poly_rollover():
    mgr = PolySessionManager(_db_url())
    session = mgr.get_active_session()
    if not session:
        new = mgr.create_session(initial_balance=1000.0)
        print(f"Nueva sesión Poly creada: {new['session_name']}")
        return

    open_count = mgr._count_open_positions(str(session['id']))
    if open_count > 0:
        raise RuntimeError(f'No se puede rotar con {open_count} posiciones abiertas.')

    summary = mgr.close_session(str(session['id']), status='FAILED')
    print(f"Sesión cerrada: {session['session_name']} -> FAILED")
    print(f"  Trades={summary['total_trades']} WR={summary['win_rate']:.0f}% PnL=${summary['total_pnl']:+.2f}")

    new = mgr.create_session(initial_balance=1000.0)
    print(f"Nueva sesión creada: {new['session_name']}")


def cmd_poly_sessions():
    mgr = PolySessionManager(_db_url())
    sessions = mgr.list_sessions()
    if not sessions:
        print('No hay sesiones Polymarket.')
        return
    for s in sessions:
        bal = float(s['current_balance'])
        pnl = float(s['total_pnl'] or 0)
        dd = float(s['max_drawdown'] or 0)
        status = s['status']
        print(f"  {s['session_name']}  {status:8s}  bal=${bal:.2f}  pnl=${pnl:+.2f}  dd={dd:.1f}%")


if __name__ == '__main__':
    command = sys.argv[1] if len(sys.argv) > 1 else 'status'
    if command == 'status':
        cmd_status()
    elif command == 'rollover':
        cmd_rollover()
    elif command == 'poly_status':
        cmd_poly_status()
    elif command == 'poly_rollover':
        cmd_poly_rollover()
    elif command == 'poly_sessions':
        cmd_poly_sessions()
    else:
        raise SystemExit(
            f'Comando no soportado: {command}\n'
            'Comandos: status | rollover | poly_status | poly_rollover | poly_sessions'
        )
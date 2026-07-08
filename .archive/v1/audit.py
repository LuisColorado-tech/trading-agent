#!/usr/bin/env python3
"""
audit.py — CLI para auditar sesiones de paper trading.

Uso:
    python scripts/audit.py journal                          # Última sesión
    python scripts/audit.py journal PAPER_SESSION_003        # Sesión específica
    python scripts/audit.py journal PAPER_SESSION_003 "Notas sobre mejoras"
    python scripts/audit.py list                             # Listar todas las sesiones
    python scripts/audit.py help
"""
import os
import sys

sys.path.insert(0, '/opt/trading')

from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')


def cmd_journal(args):
    """Genera journal para una sesión."""
    from core.session_journal import generate_journal, _print_journal_summary

    session_name = args[0] if args else None
    notes = args[1] if len(args) > 1 else None
    journal = generate_journal(session_name, notes=notes)
    if 'error' in journal:
        print(f'Error: {journal["error"]}')
        sys.exit(1)
    _print_journal_summary(journal)
    print(f'  Files saved to /opt/trading/reports/')


def cmd_list(args):
    """Lista todas las sesiones con métricas resumidas."""
    from sqlalchemy import create_engine, text

    db_url = (
        f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
        f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT', '5432')}"
        f"/{os.getenv('POSTGRES_DB')}"
    )
    engine = create_engine(db_url)

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT s.session_name, s.status, s.initial_balance, s.final_balance, "
                "s.total_trades, s.winning_trades, s.profit_factor, s.max_drawdown, "
                "s.sharpe_ratio, s.started_at, s.ended_at, "
                "r.created_at AS journal_at "
                "FROM paper_sessions s "
                "LEFT JOIN session_reports r ON r.session_id = s.id AND r.report_type = 'journal' "
                "ORDER BY s.started_at"
            )
        ).fetchall()

    if not rows:
        print('No paper sessions found.')
        return

    print(f'\n{"="*90}')
    print(f'  PAPER SESSIONS')
    print(f'{"="*90}')
    print(f'  {"Session":<22s} {"Status":<10s} {"Trades":>7s} {"P&L":>10s} '
          f'{"WR":>6s} {"PF":>6s} {"Journal":>8s}')
    print(f'  {"─"*22} {"─"*10} {"─"*7} {"─"*10} {"─"*6} {"─"*6} {"─"*8}')

    for r in rows:
        r = dict(r._mapping)
        name = r['session_name']
        status = r['status']
        trades = r.get('total_trades') or 0
        initial = float(r.get('initial_balance') or 0)
        final = float(r.get('final_balance') or 0)
        pnl = final - initial if final else 0
        wr = ''
        if trades and r.get('winning_trades') is not None:
            wr = f'{int(r["winning_trades"]) / trades:.0%}'
        pf = f'{float(r["profit_factor"]):.2f}' if r.get('profit_factor') else ''
        has_journal = '✅' if r.get('journal_at') else '—'

        print(f'  {name:<22s} {status:<10s} {trades:>7d} ${pnl:>+9,.0f} '
              f'{wr:>6s} {pf:>6s} {has_journal:>8s}')

    print(f'{"="*90}\n')


def cmd_help(_args):
    """Muestra ayuda."""
    print(__doc__)


COMMANDS = {
    'journal': cmd_journal,
    'list': cmd_list,
    'help': cmd_help,
}


if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        cmd_help([])
        sys.exit(0)

    command = sys.argv[1]
    COMMANDS[command](sys.argv[2:])

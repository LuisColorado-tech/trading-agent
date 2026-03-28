"""
Paper Trading Metrics — Analiza rendimiento de paper trades.
Calcula win rate, profit factor, Sharpe, drawdown, expectancy.
"""
import os
import sys

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

sys.path.insert(0, '/opt/trading')
load_dotenv('/opt/trading/config/.env')


def _load_session_context(conn, session_id: str = None):
    if session_id:
        row = conn.execute(
            text('SELECT * FROM paper_sessions WHERE id = :id LIMIT 1'),
            {'id': session_id},
        ).fetchone()
    else:
        row = conn.execute(
            text("SELECT * FROM paper_sessions WHERE status = 'ACTIVE' ORDER BY started_at DESC LIMIT 1")
        ).fetchone()
    return dict(row._mapping) if row else None


def compute_metrics(session_id: str = None):
    db_url = (
        f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
        f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT', '5432')}"
        f"/{os.getenv('POSTGRES_DB')}"
    )
    engine = create_engine(db_url)

    with engine.connect() as conn:
        session = _load_session_context(conn, session_id)
        if session is None:
            print('No active paper session found.')
            return None

        trades = pd.read_sql(
            text(
                "SELECT * FROM trades WHERE paper_trade = true AND status = 'CLOSED' "
                "AND timestamp_open >= :session_start "
                "AND (:session_end IS NULL OR timestamp_open <= :session_end) "
                "ORDER BY timestamp_open"
            ),
            conn,
            params={
                'session_start': session['started_at'],
                'session_end': session.get('ended_at'),
            },
        )

    if len(trades) < 10:
        print(f'Insufficient trades for meaningful metrics ({len(trades)} found, need >= 10)')
        # Show open trades count
        with engine.connect() as conn:
            open_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM trades WHERE paper_trade = true AND status = 'OPEN' "
                    "AND timestamp_open >= :session_start"
                ),
                {'session_start': session['started_at']},
            ).scalar()
        print(f'Open paper trades: {open_count}')
        return None

    n = len(trades)
    winners = trades[trades['pnl'] > 0]
    losers = trades[trades['pnl'] <= 0]

    win_rate = len(winners) / n
    avg_win = float(winners['pnl'].mean()) if len(winners) else 0
    avg_loss = float(abs(losers['pnl'].mean())) if len(losers) else 0
    profit_factor = (
        (avg_win * len(winners)) / (avg_loss * len(losers))
        if avg_loss and len(losers)
        else 0
    )

    # Equity curve
    with engine.connect() as conn:
        equity = pd.read_sql(
            text(
                'SELECT timestamp, total_balance FROM portfolio '
                'WHERE timestamp >= :session_start '
                'AND (:session_end IS NULL OR timestamp <= :session_end) '
                'ORDER BY timestamp'
            ),
            conn,
            params={
                'session_start': session['started_at'],
                'session_end': session.get('ended_at'),
            },
        )

    if len(equity) > 1:
        returns = equity['total_balance'].pct_change().dropna()
        sharpe = (
            (returns.mean() / returns.std()) * np.sqrt(365)
            if returns.std() > 0
            else 0
        )
        max_dd = float(
            (equity['total_balance'] / equity['total_balance'].cummax() - 1).min()
        )
    else:
        sharpe, max_dd = 0.0, 0.0

    expectancy = win_rate * avg_win - (1 - win_rate) * avg_loss

    print('=== PAPER TRADING METRICS ===')
    print(f'Session:         {session["session_name"]}')
    print(f'Total trades:    {n}')
    print(f'Win rate:        {win_rate * 100:.1f}%  (target: 55-65%)')
    print(f'Profit factor:   {profit_factor:.2f}  (target: >1.5)')
    print(f'Max drawdown:    {max_dd * 100:.2f}%  (limit: <12%)')
    print(f'Sharpe ratio:    {sharpe:.2f}  (target: >1.5)')
    print(f'Avg win:         ${avg_win:.2f}')
    print(f'Avg loss:        ${avg_loss:.2f}')
    print(f'Expectancy:      ${expectancy:.2f} per trade')

    # Criterios de graduación
    passed = all([
        win_rate >= 0.55,
        profit_factor >= 1.5,
        max_dd >= -0.12,
        n >= 30,
    ])
    print(f'\n>>> READY FOR LIVE TRADING: {"YES ✅" if passed else "NO ❌"}')

    return {
        'session_id': session['id'],
        'session_name': session['session_name'],
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'max_drawdown': max_dd,
        'sharpe': sharpe,
        'expectancy': expectancy,
        'ready': passed,
    }


if __name__ == '__main__':
    compute_metrics()

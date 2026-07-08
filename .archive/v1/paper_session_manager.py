"""
Gestión de sesiones de paper trading.
Permite cerrar una sesión fallida y arrancar una nueva sin mezclar métricas.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text


class PaperSessionManager:
    def __init__(self, db_url: str):
        self.engine = create_engine(db_url)

    def get_active_session(self) -> Optional[dict]:
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT * FROM paper_sessions WHERE status = 'ACTIVE' ORDER BY started_at DESC LIMIT 1"
                )
            ).fetchone()
        return dict(row._mapping) if row else None

    def get_session(self, session_id: str) -> Optional[dict]:
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM paper_sessions WHERE id = :id LIMIT 1"),
                {'id': session_id},
            ).fetchone()
        return dict(row._mapping) if row else None

    def ensure_active_session(self, initial_balance: float = 10000.0) -> dict:
        active = self.get_active_session()
        if active:
            return active
        return self.create_session(initial_balance=initial_balance)

    def create_session(self, initial_balance: float = 10000.0, session_name: str = None) -> dict:
        now = datetime.now(timezone.utc)
        if session_name is None:
            with self.engine.connect() as conn:
                count = conn.execute(text('SELECT COUNT(*) FROM paper_sessions')).scalar() or 0
            session_name = f'PAPER_SESSION_{count + 1:03d}'

        session_id = str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO paper_sessions
                        (id, session_name, initial_balance, final_balance, total_trades,
                         winning_trades, profit_factor, max_drawdown, sharpe_ratio,
                         status, started_at, ended_at)
                    VALUES
                        (:id, :session_name, :initial_balance, NULL, 0,
                         0, NULL, NULL, NULL,
                         'ACTIVE', :started_at, NULL)
                    """
                ),
                {
                    'id': session_id,
                    'session_name': session_name,
                    'initial_balance': initial_balance,
                    'started_at': now,
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO portfolio
                        (id, total_balance, available_cash, exposure_pct, pnl_day,
                         pnl_month, pnl_total, drawdown_pct, peak_balance, positions,
                         timestamp, created_at)
                    VALUES
                        (:id, :balance, :cash, 0, 0,
                         0, 0, 0, :peak, CAST(:positions AS jsonb),
                         :ts, :ts)
                    """
                ),
                {
                    'id': str(uuid.uuid4()),
                    'balance': initial_balance,
                    'cash': initial_balance,
                    'peak': initial_balance,
                    'positions': '{}',
                    'ts': now,
                },
            )
        return self.get_session(session_id)

    def close_session(self, session_id: str, status: str, final_balance: float,
                      total_trades: int, winning_trades: int,
                      profit_factor: float, max_drawdown: float,
                      sharpe_ratio: float, notes: str = None):
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE paper_sessions
                    SET final_balance = :final_balance,
                        total_trades = :total_trades,
                        winning_trades = :winning_trades,
                        profit_factor = :profit_factor,
                        max_drawdown = :max_drawdown,
                        sharpe_ratio = :sharpe_ratio,
                        status = :status,
                        ended_at = :ended_at
                    WHERE id = :id
                    """
                ),
                {
                    'id': session_id,
                    'final_balance': final_balance,
                    'total_trades': total_trades,
                    'winning_trades': winning_trades,
                    'profit_factor': profit_factor,
                    'max_drawdown': max_drawdown,
                    'sharpe_ratio': sharpe_ratio,
                    'status': status,
                    'ended_at': datetime.now(timezone.utc),
                },
            )

        # Auto-generar journal de auditoría
        try:
            from core.session_journal import generate_journal
            generate_journal(session_id, notes=notes)
        except Exception as e:
            # No bloquear el cierre si falla el journal
            from loguru import logger as _journal_logger
            _journal_logger.warning(f'Journal generation failed: {e}')

    def summarize_session(self, session_id: str) -> Optional[dict]:
        session = self.get_session(session_id)
        if session is None:
            return None

        params = {
            'session_start': session['started_at'],
            'session_end': session.get('ended_at'),
        }
        with self.engine.connect() as conn:
            trades = pd.read_sql(
                text(
                    "SELECT pnl FROM trades WHERE paper_trade = true AND status = 'CLOSED' "
                    "AND timestamp_open >= :session_start "
                    "AND (:session_end IS NULL OR timestamp_open <= :session_end) "
                    "ORDER BY timestamp_open"
                ),
                conn,
                params=params,
            )
            equity = pd.read_sql(
                text(
                    'SELECT timestamp, total_balance FROM portfolio '
                    'WHERE timestamp >= :session_start '
                    'AND (:session_end IS NULL OR timestamp <= :session_end) '
                    'ORDER BY timestamp'
                ),
                conn,
                params=params,
            )

        n = len(trades)
        winners = trades[trades['pnl'] > 0]
        losers = trades[trades['pnl'] <= 0]
        avg_win = float(winners['pnl'].mean()) if len(winners) else 0.0
        avg_loss = float(abs(losers['pnl'].mean())) if len(losers) else 0.0
        profit_factor = (
            (avg_win * len(winners)) / (avg_loss * len(losers))
            if avg_loss and len(losers)
            else 0.0
        )
        if len(equity) > 1:
            returns = equity['total_balance'].pct_change().dropna()
            sharpe = (
                (returns.mean() / returns.std()) * np.sqrt(365)
                if returns.std() > 0
                else 0.0
            )
            max_dd = float(
                (equity['total_balance'] / equity['total_balance'].cummax() - 1).min()
            )
            final_balance = float(equity['total_balance'].iloc[-1])
        else:
            sharpe = 0.0
            max_dd = 0.0
            final_balance = float(session['initial_balance'])

        return {
            'session': session,
            'total_trades': int(n),
            'winning_trades': int(len(winners)),
            'profit_factor': float(profit_factor),
            'max_drawdown': float(abs(max_dd)),
            'sharpe_ratio': float(sharpe),
            'final_balance': final_balance,
        }

    def rollover_session(self, session_id: str, status: str = 'FAILED',
                         next_initial_balance: float = 10000.0) -> dict:
        summary = self.summarize_session(session_id)
        if summary is None:
            raise ValueError(f'Session not found: {session_id}')

        session = summary['session']
        self.close_session(
            session_id=session_id,
            status=status,
            final_balance=summary['final_balance'],
            total_trades=summary['total_trades'],
            winning_trades=summary['winning_trades'],
            profit_factor=summary['profit_factor'],
            max_drawdown=summary['max_drawdown'],
            sharpe_ratio=summary['sharpe_ratio'],
        )
        return self.create_session(initial_balance=next_initial_balance)
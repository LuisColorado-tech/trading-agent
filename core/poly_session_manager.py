"""
Gestión de sesiones paper trading para Polymarket.
Equivalente a PaperSessionManager pero para la línea de predicción.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import create_engine, text


class PolySessionManager:
    """Ciclo de vida de sesiones Polymarket: crear, cerrar, rollover."""

    def __init__(self, db_url: str):
        self.engine = create_engine(db_url)

    # ── Consultas ──

    def get_active_session(self) -> Optional[dict]:
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM poly_sessions WHERE status = 'ACTIVE' ORDER BY started_at DESC LIMIT 1")
            ).fetchone()
        return dict(row._mapping) if row else None

    def get_session(self, session_id: str) -> Optional[dict]:
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM poly_sessions WHERE id = :id LIMIT 1"),
                {'id': session_id},
            ).fetchone()
        return dict(row._mapping) if row else None

    def ensure_active_session(self, initial_balance: float = 1000.0) -> dict:
        active = self.get_active_session()
        if active:
            return active
        return self.create_session(initial_balance=initial_balance)

    # ── Crear sesión ──

    def create_session(self, initial_balance: float = 1000.0, session_name: str = None) -> dict:
        now = datetime.now(timezone.utc)
        if session_name is None:
            with self.engine.connect() as conn:
                count = conn.execute(text('SELECT COUNT(*) FROM poly_sessions')).scalar() or 0
            session_name = f'POLY_SESSION_{count + 1:03d}'

        session_id = str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(
                text('''
                    INSERT INTO poly_sessions
                        (id, session_name, initial_balance, current_balance, status,
                         started_at, total_trades, winning_trades, total_pnl,
                         profit_factor, max_drawdown, peak_balance)
                    VALUES
                        (:id, :name, :bal, :bal, 'ACTIVE',
                         :started, 0, 0, 0,
                         0, 0, :bal)
                '''),
                {
                    'id': session_id,
                    'name': session_name,
                    'bal': initial_balance,
                    'started': now,
                },
            )
        logger.info(f'POLY SESSION CREATED: {session_name} balance=${initial_balance:.2f}')
        return self.get_session(session_id)

    # ── Cerrar sesión ──

    def close_session(self, session_id: str, status: str = 'CLOSED') -> dict:
        """Cierra sesión con métricas finales calculadas desde poly_positions."""
        summary = self.summarize_session(session_id)
        if summary is None:
            raise ValueError(f'Session not found: {session_id}')

        with self.engine.begin() as conn:
            conn.execute(
                text('''
                    UPDATE poly_sessions
                    SET status = :status,
                        ended_at = :ended,
                        current_balance = :final_bal,
                        total_trades = :total,
                        winning_trades = :wins,
                        total_pnl = :pnl,
                        profit_factor = :pf,
                        max_drawdown = :dd
                    WHERE id = :id
                '''),
                {
                    'id': session_id,
                    'status': status,
                    'ended': datetime.now(timezone.utc),
                    'final_bal': summary['final_balance'],
                    'total': summary['total_trades'],
                    'wins': summary['winning_trades'],
                    'pnl': summary['total_pnl'],
                    'pf': summary['profit_factor'],
                    'dd': summary['max_drawdown'],
                },
            )
        logger.info(
            f'POLY SESSION CLOSED: {summary["session"]["session_name"]} → {status} '
            f'trades={summary["total_trades"]} WR={summary["win_rate"]:.0f}% '
            f'PnL=${summary["total_pnl"]:+.2f} DD={summary["max_drawdown"]:.1f}%'
        )
        return summary

    # ── Rollover (cerrar + crear nueva) ──

    def rollover_session(self, session_id: str, status: str = 'FAILED',
                         next_initial_balance: float = 1000.0) -> dict:
        """Cierra la sesión actual y crea una nueva."""
        # Verificar que no hay posiciones abiertas
        open_count = self._count_open_positions(session_id)
        if open_count > 0:
            raise RuntimeError(
                f'No se puede rotar con {open_count} posiciones abiertas. Ciérralas primero.'
            )

        summary = self.close_session(session_id, status=status)
        new_session = self.create_session(initial_balance=next_initial_balance)

        logger.info(
            f'POLY ROLLOVER: {summary["session"]["session_name"]} → {status} | '
            f'Nueva: {new_session["session_name"]} ${next_initial_balance:.2f}'
        )
        return new_session

    # ── Resumen de sesión ──

    def summarize_session(self, session_id: str) -> Optional[dict]:
        """Calcula métricas finales de una sesión desde poly_positions."""
        session = self.get_session(session_id)
        if session is None:
            return None

        sess_name = session['session_name']
        with self.engine.connect() as conn:
            closed = conn.execute(
                text('''
                    SELECT pnl, cost_basis, close_reason
                    FROM poly_positions
                    WHERE session_name = :s AND status = 'CLOSED'
                    ORDER BY timestamp_close
                '''),
                {'s': sess_name},
            ).fetchall()

        total = len(closed)
        wins = sum(1 for r in closed if float(r.pnl or 0) > 0)
        losses = total - wins
        total_pnl = sum(float(r.pnl or 0) for r in closed)

        # Profit factor
        gross_profit = sum(float(r.pnl) for r in closed if float(r.pnl or 0) > 0)
        gross_loss = abs(sum(float(r.pnl) for r in closed if float(r.pnl or 0) <= 0))
        pf = (gross_profit / gross_loss) if gross_loss > 0 else 0.0

        # Win rate
        wr = (wins / total * 100) if total > 0 else 0

        # Max drawdown (reconstruir equity curve)
        initial = float(session['initial_balance'])
        balance = initial
        peak = initial
        max_dd = 0.0
        for r in closed:
            balance += float(r.pnl or 0)
            if balance > peak:
                peak = balance
            dd = ((peak - balance) / peak * 100) if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

        return {
            'session': session,
            'total_trades': total,
            'winning_trades': wins,
            'losing_trades': losses,
            'total_pnl': total_pnl,
            'profit_factor': pf,
            'win_rate': wr,
            'max_drawdown': max_dd,
            'final_balance': initial + total_pnl,
            'gross_profit': gross_profit,
            'gross_loss': gross_loss,
        }

    # ── Drawdown check ──

    def check_drawdown_halt(self, session_id: str, max_dd_pct: float = 40.0) -> dict:
        """Verifica si la sesión debe detenerse por drawdown excesivo.

        Args:
            session_id: UUID de la sesión
            max_dd_pct: drawdown máximo permitido (default 40% para Polymarket)

        Returns:
            dict con halt, current_dd, reason
        """
        session = self.get_session(session_id)
        if session is None:
            return {'halt': False, 'reason': 'SESSION_NOT_FOUND'}

        current = float(session['current_balance'])
        peak = float(session['peak_balance'] or session['initial_balance'])
        dd_pct = ((peak - current) / peak * 100) if peak > 0 else 0

        if dd_pct >= max_dd_pct:
            return {
                'halt': True,
                'current_dd': dd_pct,
                'balance': current,
                'peak': peak,
                'reason': f'DD {dd_pct:.1f}% >= {max_dd_pct:.0f}% limit',
            }
        return {
            'halt': False,
            'current_dd': dd_pct,
            'balance': current,
            'peak': peak,
            'reason': 'OK',
        }

    # ── Utilidades ──

    def _count_open_positions(self, session_id: str) -> int:
        session = self.get_session(session_id)
        if session is None:
            return 0
        with self.engine.connect() as conn:
            return conn.execute(
                text("SELECT COUNT(*) FROM poly_positions WHERE session_name = :s AND status = 'OPEN'"),
                {'s': session['session_name']},
            ).scalar() or 0

    def list_sessions(self) -> list[dict]:
        """Lista todas las sesiones Polymarket."""
        with self.engine.connect() as conn:
            rows = conn.execute(
                text('SELECT * FROM poly_sessions ORDER BY started_at DESC')
            ).fetchall()
        return [dict(r._mapping) for r in rows]

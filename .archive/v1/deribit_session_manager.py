"""
deribit_session_manager.py — Ciclo de vida de sesiones de opciones paper/live.

Replica el patrón de PolySessionManager / PaperSessionManager pero
para el sistema de Theta Farming en Deribit.

Tabla principal: options_sessions
Posiciones:      options_positions
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import create_engine, text


class DeribitSessionManager:
    """Gestiona la vida de sesiones OPTIONS_SESSION_NNN.

    Modo paper: todas las métricas se calculan sobre posiciones simuladas.
    El balance es el colateral total disponible para nuevas posiciones.
    """

    def __init__(self, db_url: str):
        self.engine = create_engine(db_url)

    # ── Consultas básicas ──────────────────────────────────────────────────────

    def get_active_session(self) -> Optional[dict]:
        with self.engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT * FROM options_sessions
                    WHERE status = 'ACTIVE'
                    ORDER BY started_at DESC LIMIT 1
                """)
            ).fetchone()
        return dict(row._mapping) if row else None

    def get_session(self, session_id: str) -> Optional[dict]:
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM options_sessions WHERE id = :id LIMIT 1"),
                {'id': session_id},
            ).fetchone()
        return dict(row._mapping) if row else None

    def ensure_active_session(self, initial_balance_usd: float = 2000.0) -> dict:
        active = self.get_active_session()
        if active:
            return active
        return self.create_session(initial_balance_usd=initial_balance_usd)

    # ── Crear sesión ───────────────────────────────────────────────────────────

    def create_session(
        self,
        initial_balance_usd: float = 2000.0,
        session_name: str = None,
        mode: str = 'paper',
    ) -> dict:
        now = datetime.now(timezone.utc)
        if session_name is None:
            with self.engine.connect() as conn:
                count = conn.execute(text('SELECT COUNT(*) FROM options_sessions')).scalar() or 0
            session_name = f'OPTIONS_SESSION_{count + 1:03d}'

        session_id = str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO options_sessions
                        (id, session_name, mode, initial_balance_usd, current_balance_usd,
                         peak_balance_usd, total_contracts, winning_contracts,
                         total_pnl_usd, total_premium_usd, realized_losses_usd,
                         max_drawdown_pct, status, started_at)
                    VALUES
                        (:id, :name, :mode, :bal, :bal,
                         :bal, 0, 0,
                         0, 0, 0,
                         0, 'ACTIVE', :started)
                """),
                {
                    'id': session_id,
                    'name': session_name,
                    'mode': mode,
                    'bal': initial_balance_usd,
                    'started': now,
                },
            )
        logger.info(f'OPTIONS SESSION CREATED: {session_name} | mode={mode} | balance=${initial_balance_usd:.2f}')
        return self.get_session(session_id)

    # ── Abrir posición ─────────────────────────────────────────────────────────

    def open_position(self, session: dict, position_data: dict) -> str:
        """Registra una nueva opción vendida.

        position_data debe incluir:
          instrument_name, strike, expiration_date, dte_at_entry,
          contracts, entry_premium_btc, entry_premium_usd, btc_price_at_entry,
          iv_at_entry, iv_rank_at_entry, delta_at_entry, theta_at_entry,
          margin_required_usd, expires_at, strategy_reasoning, market_conditions,
          iv_rank_signal
        """
        pos_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        session_id = str(session['id'])
        session_name = session['session_name']
        margin = float(position_data.get('margin_required_usd', 0))

        with self.engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO options_positions (
                        id, session_id, session_name,
                        instrument_name, underlying, option_type,
                        strike, expiration_date, dte_at_entry,
                        contracts, entry_premium_btc, entry_premium_usd,
                        btc_price_at_entry, iv_at_entry, iv_rank_at_entry,
                        delta_at_entry, theta_at_entry, margin_required_usd,
                        status, expires_at, opened_at,
                        strategy_reasoning, iv_rank_signal, market_conditions
                    ) VALUES (
                        :id, :session_id, :session_name,
                        :instrument_name, :underlying, :option_type,
                        :strike, :expiration_date, :dte_at_entry,
                        :contracts, :entry_premium_btc, :entry_premium_usd,
                        :btc_price_at_entry, :iv_at_entry, :iv_rank_at_entry,
                        :delta_at_entry, :theta_at_entry, :margin_required_usd,
                        'OPEN', :expires_at, :opened_at,
                        :strategy_reasoning, :iv_rank_signal, :market_conditions
                    )
                """),
                {
                    'id': pos_id,
                    'session_id': session_id,
                    'session_name': session_name,
                    **position_data,
                    'underlying': position_data.get('underlying', 'BTC'),
                    'option_type': position_data.get('option_type', 'PUT'),
                    'opened_at': now,
                },
            )
            # Reservar el margen del balance disponible
            conn.execute(
                text("""
                    UPDATE options_sessions
                    SET current_balance_usd = current_balance_usd - :margin,
                        total_contracts = total_contracts + 1
                    WHERE id = :sid
                """),
                {'margin': margin, 'sid': session_id},
            )

        logger.info(
            f'OPTIONS POSITION OPENED: {position_data["instrument_name"]} '
            f'| premium=${position_data["entry_premium_usd"]:.2f} '
            f'| margin=${margin:.0f}'
        )
        return pos_id

    # ── Cerrar posición ────────────────────────────────────────────────────────

    def close_position(
        self,
        position_id: str,
        exit_premium_btc: float,
        exit_premium_usd: float,
        btc_price_at_exit: float,
        exit_reason: str,
    ) -> dict:
        """Cierra una posición y actualiza métricas de sesión.

        PnL = prima cobrada al entrar - prima pagada al salir.
        Para expiración en 0: exit_premium_btc = 0.0 (la opción no vale nada).
        Para stop loss: exit_premium_btc = precio de recompra.
        Para asignación: exit_premium_btc = valor intrínseco del PUT.
        """
        now = datetime.now(timezone.utc)

        with self.engine.connect() as conn:
            pos = conn.execute(
                text("SELECT * FROM options_positions WHERE id = :id"),
                {'id': position_id},
            ).fetchone()
        if not pos:
            raise ValueError(f'Position not found: {position_id}')
        pos = dict(pos._mapping)

        # PnL: vendiste premium_entry, recompras exit_premium
        pnl_usd = float(pos['entry_premium_usd']) - exit_premium_usd
        margin = float(pos['margin_required_usd'] or 1)
        pnl_pct = pnl_usd / margin * 100 if margin > 0 else 0.0

        # Mapear reason → status de posición
        status_map = {
            'EXPIRED': 'EXPIRED_PROFIT',
            'STOP_LOSS_2X': 'CLOSED_STOP',
            'ASSIGNED': 'ASSIGNED',
            'MANUAL': 'CLOSED_MANUAL',
        }
        pos_status = status_map.get(exit_reason, 'CLOSED_MANUAL')

        with self.engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE options_positions SET
                        status = :status,
                        exit_premium_btc = :exit_btc,
                        exit_premium_usd = :exit_usd,
                        btc_price_at_exit = :btc_exit,
                        pnl_usd = :pnl_usd,
                        pnl_pct = :pnl_pct,
                        exit_reason = :reason,
                        closed_at = :closed_at
                    WHERE id = :id
                """),
                {
                    'status': pos_status,
                    'exit_btc': exit_premium_btc,
                    'exit_usd': exit_premium_usd,
                    'btc_exit': btc_price_at_exit,
                    'pnl_usd': pnl_usd,
                    'pnl_pct': pnl_pct,
                    'reason': exit_reason,
                    'closed_at': now,
                    'id': position_id,
                },
            )
            # Devolver margen + actualizar sesión
            conn.execute(
                text("""
                    UPDATE options_sessions SET
                        current_balance_usd = current_balance_usd + :margin + :pnl,
                        total_pnl_usd = total_pnl_usd + :pnl,
                        total_premium_usd = total_premium_usd + :premium_entry,
                        realized_losses_usd = realized_losses_usd + :loss,
                        winning_contracts = winning_contracts + :win
                    WHERE id = :sid
                """),
                {
                    'margin': float(pos['margin_required_usd'] or 0),
                    'pnl': pnl_usd,
                    'premium_entry': float(pos['entry_premium_usd']),
                    'loss': max(0.0, -pnl_usd),
                    'win': 1 if pnl_usd > 0 else 0,
                    'sid': str(pos['session_id']),
                },
            )
            # Actualizar peak y drawdown (reutilizar la misma conexión para evitar deadlock)
            self._update_peak_and_drawdown(str(pos['session_id']), conn=conn)

        logger.info(
            f'OPTIONS POSITION CLOSED: {pos["instrument_name"]} '
            f'| reason={exit_reason} | PnL=${pnl_usd:+.2f} ({pnl_pct:+.2f}%)'
        )
        return {'position_id': position_id, 'pnl_usd': pnl_usd, 'pnl_pct': pnl_pct, 'status': pos_status}

    # ── Consultar posiciones abiertas ──────────────────────────────────────────

    def get_open_positions(self, session_name: str) -> list[dict]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT * FROM options_positions
                    WHERE session_name = :s AND status = 'OPEN'
                    ORDER BY opened_at ASC
                """),
                {'s': session_name},
            ).fetchall()
        return [dict(r._mapping) for r in rows]

    def get_open_instruments(self, session_name: str) -> set[str]:
        """Retorna los instrument_name actualmente abiertos."""
        positions = self.get_open_positions(session_name)
        return {p['instrument_name'] for p in positions}

    def get_expired_open_positions(self, session_name: str) -> list[dict]:
        """Retorna posiciones abiertas cuya fecha de expiración ya pasó."""
        now = datetime.now(timezone.utc)
        with self.engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT * FROM options_positions
                    WHERE session_name = :s
                      AND status = 'OPEN'
                      AND expires_at <= :now
                    ORDER BY expires_at ASC
                """),
                {'s': session_name, 'now': now},
            ).fetchall()
        return [dict(r._mapping) for r in rows]

    def count_open_positions(self, session_name: str) -> int:
        with self.engine.connect() as conn:
            return conn.execute(
                text("SELECT COUNT(*) FROM options_positions WHERE session_name = :s AND status = 'OPEN'"),
                {'s': session_name},
            ).scalar() or 0

    # ── Guardar snapshot IV ────────────────────────────────────────────────────

    def save_market_snapshot(self, data: dict):
        """Persiste un snapshot de IV/greeks para backtesting."""
        with self.engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO options_market_data (
                        instrument_name, underlying, timestamp,
                        btc_price, strike, expiration_date, dte, option_type,
                        bid_btc, ask_btc, mark_btc, iv_pct,
                        delta, gamma, theta, vega,
                        dvol_current, dvol_rank_30d
                    ) VALUES (
                        :instrument_name, :underlying, :timestamp,
                        :btc_price, :strike, :expiration_date, :dte, :option_type,
                        :bid_btc, :ask_btc, :mark_btc, :iv_pct,
                        :delta, :gamma, :theta, :vega,
                        :dvol_current, :dvol_rank_30d
                    )
                """),
                data,
            )

    # ── Métricas de sesión ─────────────────────────────────────────────────────

    def get_session_summary(self, session_id: str) -> dict:
        session = self.get_session(session_id)
        if not session:
            return {}

        with self.engine.connect() as conn:
            closed = conn.execute(
                text("""
                    SELECT
                        COUNT(*) FILTER (WHERE pnl_usd > 0) AS wins,
                        COUNT(*) FILTER (WHERE pnl_usd <= 0) AS losses,
                        COUNT(*) FILTER (WHERE exit_reason = 'EXPIRED') AS expirations,
                        COUNT(*) FILTER (WHERE exit_reason = 'STOP_LOSS_2X') AS stops,
                        SUM(entry_premium_usd) AS total_premium_collected,
                        SUM(pnl_usd) AS total_pnl,
                        AVG(pnl_pct) AS avg_pnl_pct,
                        AVG(dte_at_entry) AS avg_dte,
                        AVG(iv_at_entry) AS avg_iv_entry
                    FROM options_positions
                    WHERE session_id = :sid AND status != 'OPEN'
                """),
                {'sid': session_id},
            ).fetchone()

        summary = dict(session)
        if closed:
            c = dict(closed._mapping)
            wins = int(c.get('wins') or 0)
            losses = int(c.get('losses') or 0)
            total = wins + losses
            summary['closed_wins'] = wins
            summary['closed_losses'] = losses
            summary['win_rate'] = wins / total if total > 0 else 0.0
            summary['total_premium_collected'] = float(c.get('total_premium_collected') or 0)
            summary['total_pnl_closed'] = float(c.get('total_pnl') or 0)
            summary['avg_pnl_pct'] = float(c.get('avg_pnl_pct') or 0)
            summary['avg_dte'] = float(c.get('avg_dte') or 0)
            summary['avg_iv_entry'] = float(c.get('avg_iv_entry') or 0)
            summary['expirations'] = int(c.get('expirations') or 0)
            summary['stops'] = int(c.get('stops') or 0)
        return summary

    def check_drawdown_halt(self, session_id: str, max_dd_pct: float = 30.0) -> dict:
        session = self.get_session(session_id)
        if not session:
            return {'halt': False}
        # Drawdown basado en PnL realizado, NO en balance de caja.
        # current_balance_usd baja cuando se reserva margen, pero eso NO es pérdida.
        # Solo activamos halt si hay pérdidas reales (total_pnl_usd < 0).
        initial = float(session['initial_balance_usd'])
        total_pnl = float(session['total_pnl_usd'])
        if total_pnl >= 0 or initial <= 0:
            return {'halt': False, 'current_dd': 0.0}
        dd_pct = abs(total_pnl) / initial * 100
        halt = dd_pct >= max_dd_pct
        if halt:
            logger.warning(f'OPTIONS DRAWDOWN HALT: {dd_pct:.1f}% >= {max_dd_pct:.0f}% | PnL=${total_pnl:.2f}')
        return {'halt': halt, 'current_dd': dd_pct, 'initial': initial, 'total_pnl': total_pnl}

    def close_session(self, session_id: str, status: str = 'CLOSED') -> dict:
        now = datetime.now(timezone.utc)
        summary = self.get_session_summary(session_id)
        with self.engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE options_sessions SET
                        status = :status,
                        ended_at = :now
                    WHERE id = :id
                """),
                {'status': status, 'now': now, 'id': session_id},
            )
        logger.info(f'OPTIONS SESSION CLOSED: {summary.get("session_name")} | status={status}')
        return summary

    # ── Internos ───────────────────────────────────────────────────────────────

    def _update_peak_and_drawdown(self, session_id: str, conn=None):
        def _run(c):
            row = c.execute(
                text("SELECT current_balance_usd, peak_balance_usd FROM options_sessions WHERE id = :id"),
                {'id': session_id},
            ).fetchone()
            if not row:
                return
            current = float(row[0])
            peak = float(row[1])
            new_peak = max(peak, current)
            # max_drawdown_pct se calcula sobre PnL, no sobre balance de caja
            # (el balance baja al reservar margen, pero eso no es drawdown real)
            c.execute(
                text("""
                    UPDATE options_sessions SET
                        peak_balance_usd = :peak
                    WHERE id = :id
                """),
                {'peak': new_peak, 'id': session_id},
            )

        if conn is not None:
            _run(conn)
        else:
            with self.engine.begin() as c:
                _run(c)

"""
poly_monitor.py — Monitor de posiciones abiertas en Polymarket.

Detecta resoluciones de mercados, cierra posiciones con PnL,
y permite salida anticipada si el edge se revierte.
"""
import json
import os
import sys
from datetime import datetime, timezone

import requests as _requests

import redis as _redis
import yaml
from loguru import logger
from sqlalchemy import create_engine, text

sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv

load_dotenv('/opt/trading/config/.env')

with open('/opt/trading/config/exchange_config.yaml') as f:
    _CFG = yaml.safe_load(f).get('polymarket', {})

# Salida anticipada si precio alcanza este umbral
EARLY_EXIT_PROFIT = _CFG.get('risk', {}).get('early_exit_profit', 0.85)
# Salida anticipada si precio cae debajo de este umbral
EARLY_EXIT_LOSS = _CFG.get('risk', {}).get('early_exit_loss', 0.10)


def _db_url() -> str:
    return (
        f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
        f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT', '5432')}"
        f"/{os.getenv('POSTGRES_DB')}"
    )


class PolyMonitor:
    """Monitorea posiciones abiertas en Polymarket."""

    def __init__(self, feed):
        """
        Args:
            feed: PolymarketFeed instance para consultar precios.
        """
        self.feed = feed
        self.engine = create_engine(_db_url())
        self.redis = _redis.Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            decode_responses=True,
        )

    def check_positions(self) -> list[dict]:
        """Revisa todas las posiciones abiertas y cierra las que corresponda.

        Returns:
            list de posiciones cerradas en este ciclo.
        """
        open_positions = self._get_open_positions()
        if not open_positions:
            return []

        closed = []
        for pos in open_positions:
            result = self._evaluate_position(pos)
            if result:
                closed.append(result)

        if closed:
            self._update_session_stats(closed)

        return closed

    def _get_open_positions(self) -> list[dict]:
        """Carga posiciones abiertas desde DB."""
        with self.engine.connect() as conn:
            rows = conn.execute(
                text('''
                    SELECT p.id, p.condition_id, p.question, p.side, p.strategy,
                           p.entry_price, p.shares, p.cost_basis, p.session_name,
                           m.token_yes, m.token_no, m.outcome, m.end_date
                    FROM poly_positions p
                    LEFT JOIN poly_markets m ON p.condition_id = m.condition_id
                    WHERE p.status = 'OPEN'
                    ORDER BY p.timestamp_open
                ''')
            ).fetchall()
        return [dict(r._mapping) for r in rows]

    def _evaluate_position(self, pos: dict) -> dict | None:
        """Evalúa si una posición debe cerrarse.

        Casos de cierre:
        1. Mercado resuelto → RESOLVED_WIN / RESOLVED_LOSS
        2. Precio ≥ EARLY_EXIT_PROFIT → TAKE_PROFIT
        3. Precio ≤ EARLY_EXIT_LOSS → STOP_LOSS
        """
        side = pos['side']
        token_id = pos['token_yes'] if side == 'YES' else pos['token_no']

        # Caso 1: Mercado ya resuelto en DB
        if pos.get('outcome'):
            return self._close_resolved(pos, pos['outcome'])

        # Obtener precio actual
        if not token_id:
            return self._handle_no_price(pos)
        current_price = self.feed.get_price(token_id)
        if current_price is None:
            return self._handle_no_price(pos)

        # Caso 1b: Precio indica resolución (≥0.95 o ≤0.05 para YES token)
        price_yes = self.feed.get_price(pos['token_yes']) if pos['token_yes'] else None
        if price_yes is not None:
            if price_yes >= 0.95:
                return self._close_resolved(pos, 'YES')
            elif price_yes <= 0.05:
                return self._close_resolved(pos, 'NO')

        # Caso 2: Take profit — nuestro lado alcanza precio alto
        if current_price >= EARLY_EXIT_PROFIT:
            return self._close_position(pos, current_price, 'TAKE_PROFIT')

        # Caso 3: Stop loss — nuestro lado cae a precio bajo
        if current_price <= EARLY_EXIT_LOSS:
            return self._close_position(pos, current_price, 'STOP_LOSS')

        return None

    def _handle_no_price(self, pos: dict) -> dict | None:
        """Maneja posiciones cuyo token no devuelve precio (404 / token inválido).

        Intenta dos fallbacks en orden:
        1. Gamma API — si el mercado figura como resuelto, cierra con el outcome real.
        2. Fecha de expiración — si end_date ya pasó, fuerza cierre EXPIRED_UNKNOWN.
        """
        # Fallback 1: Gamma API
        gamma_outcome = self._check_gamma_resolved(pos.get('condition_id'))
        if gamma_outcome:
            logger.info(
                f'POLY MONITOR: Gamma fallback resuelto ({gamma_outcome}): '
                f'{pos["question"][:60]}'
            )
            return self._close_resolved(pos, gamma_outcome)

        # Fallback 2: end_date pasado → forzar cierre EXPIRED_UNKNOWN
        end_date = pos.get('end_date')
        if end_date:
            now = datetime.now(timezone.utc)
            if isinstance(end_date, str):
                try:
                    end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                except ValueError:
                    pass
            if hasattr(end_date, 'tzinfo') and end_date.tzinfo and end_date < now:
                logger.warning(
                    f'POLY MONITOR: Token inválido y mercado expirado '
                    f'→ forzando cierre EXPIRED_UNKNOWN: {pos["question"][:60]}'
                )
                return self._close_position(pos, 0.0, 'EXPIRED_UNKNOWN')
            elif isinstance(end_date, datetime) and not end_date.tzinfo and end_date < datetime.now():
                logger.warning(
                    f'POLY MONITOR: Token inválido y mercado expirado (naive) '
                    f'→ forzando cierre EXPIRED_UNKNOWN: {pos["question"][:60]}'
                )
                return self._close_position(pos, 0.0, 'EXPIRED_UNKNOWN')

        return None

    def _check_gamma_resolved(self, condition_id: str | None) -> str | None:
        """Consulta Gamma API para saber si el mercado está resuelto.

        Returns:
            'YES', 'NO', o None si no está resuelto o hubo error.
        """
        if not condition_id:
            return None
        try:
            resp = _requests.get(
                'https://gamma-api.polymarket.com/markets',
                params={'condition_id': condition_id},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if not data or not isinstance(data, list):
                return None
            market = data[0]
            if not (market.get('closed') or market.get('resolved')):
                return None
            outcomes = market.get('outcomes', '[]')
            prices = market.get('outcomePrices', '[]')
            if isinstance(outcomes, str):
                outcomes = json.loads(outcomes)
            if isinstance(prices, str):
                prices = json.loads(prices)
            if outcomes and prices and len(outcomes) == len(prices):
                for i, price in enumerate(prices):
                    if float(price) >= 0.95:
                        return outcomes[i].upper()
        except Exception as e:
            logger.debug(f'POLY MONITOR: Gamma fallback error para {condition_id}: {e}')
        return None

    def _close_resolved(self, pos: dict, outcome: str) -> dict:
        """Cierra posición cuando el mercado se resuelve.

        WIN: shares * $1.00 - cost_basis (cada share vale $1 si acierta)
        LOSS: -cost_basis (cada share vale $0 si falla)
        """
        side = pos['side']
        shares = float(pos['shares'])
        cost = float(pos['cost_basis'])

        if outcome == side:
            # Ganamos — cada share vale $1
            exit_price = 1.0
            pnl = shares - cost
            close_reason = 'RESOLVED_WIN'
        else:
            # Perdemos — cada share vale $0
            exit_price = 0.0
            pnl = -cost
            close_reason = 'RESOLVED_LOSS'

        pnl_pct = (pnl / cost * 100) if cost > 0 else 0

        self._persist_close(pos['id'], exit_price, pnl, pnl_pct, close_reason)
        self._notify(pos, exit_price, pnl, close_reason)

        logger.info(
            f'POLY CLOSE [{close_reason}]: "{pos["question"][:50]}" '
            f'{side} PnL=${pnl:+.2f} ({pnl_pct:+.1f}%)'
        )
        return {
            'position_id': str(pos['id']),
            'close_reason': close_reason,
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'cost_basis': cost,
            'session_name': pos['session_name'],
        }

    def _close_position(self, pos: dict, exit_price: float, close_reason: str) -> dict:
        """Cierra posición con salida anticipada (TP/SL)."""
        shares = float(pos['shares'])
        cost = float(pos['cost_basis'])
        revenue = shares * exit_price
        pnl = revenue - cost
        pnl_pct = (pnl / cost * 100) if cost > 0 else 0

        self._persist_close(pos['id'], exit_price, pnl, pnl_pct, close_reason)
        self._notify(pos, exit_price, pnl, close_reason)

        logger.info(
            f'POLY CLOSE [{close_reason}]: "{pos["question"][:50]}" '
            f'{pos["side"]} exit@{exit_price:.3f} PnL=${pnl:+.2f}'
        )
        return {
            'position_id': str(pos['id']),
            'close_reason': close_reason,
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'cost_basis': cost,
            'session_name': pos['session_name'],
        }

    def _persist_close(self, position_id, exit_price: float,
                       pnl: float, pnl_pct: float, close_reason: str):
        """Actualiza la posición como cerrada en DB."""
        with self.engine.connect() as conn:
            conn.execute(
                text('''
                    UPDATE poly_positions
                    SET status = 'CLOSED',
                        exit_price = :exit,
                        pnl = :pnl,
                        pnl_pct = :pnl_pct,
                        close_reason = :reason,
                        timestamp_close = now()
                    WHERE id = :id
                '''),
                {
                    'exit': exit_price, 'pnl': pnl,
                    'pnl_pct': pnl_pct, 'reason': close_reason,
                    'id': position_id,
                },
            )
            conn.commit()

    def _update_session_stats(self, closed: list[dict]):
        """Actualiza estadísticas de la sesión paper.

        IMPORTANTE: El cost_basis ya se restó del balance al abrir la posición
        (en update_balance_after_execution). Al cerrar:
        - WIN:  devolver el payout (shares * $1 = shares)
        - LOSS: devolver $0 (no se recupera nada)
        - TP/SL: devolver shares * exit_price

        Por eso sumamos payout (= pnl + cost_basis), NO pnl directamente.
        """
        sessions = {}
        for c in closed:
            sess = c['session_name']
            if sess not in sessions:
                sessions[sess] = {'payout': 0, 'pnl': 0, 'wins': 0, 'trades': 0}
            # payout = lo que recuperamos de la posición
            # pnl ya tiene el signo correcto (shares - cost para WIN, -cost para LOSS)
            # cost_basis ya se restó al abrir → devolver payout = pnl + cost_basis
            payout = c['pnl'] + c.get('cost_basis', 0)
            sessions[sess]['payout'] += payout
            sessions[sess]['pnl'] += c['pnl']
            sessions[sess]['trades'] += 1
            if c['pnl'] > 0:
                sessions[sess]['wins'] += 1

        with self.engine.connect() as conn:
            for sess_name, stats in sessions.items():
                conn.execute(
                    text('''
                        UPDATE poly_sessions
                        SET current_balance = current_balance + :payout,
                            winning_trades = winning_trades + :wins,
                            total_pnl = total_pnl + :pnl,
                            peak_balance = GREATEST(peak_balance, current_balance + :payout)
                        WHERE session_name = :sess AND status = 'ACTIVE'
                    '''),
                    {
                        'payout': stats['payout'], 'pnl': stats['pnl'],
                        'wins': stats['wins'], 'sess': sess_name,
                    },
                )
                # Actualizar drawdown
                conn.execute(
                    text('''
                        UPDATE poly_sessions
                        SET max_drawdown = GREATEST(
                            max_drawdown,
                            (peak_balance - current_balance) / NULLIF(peak_balance, 0) * 100
                        )
                        WHERE session_name = :sess AND status = 'ACTIVE'
                    '''),
                    {'sess': sess_name},
                )
            conn.commit()

    def _notify(self, pos: dict, exit_price: float, pnl: float, reason: str):
        """Publica cierre de posición en Redis."""
        self.redis.publish('poly:closed', json.dumps({
            'position_id': str(pos['id']),
            'question': pos.get('question', '')[:80],
            'side': pos['side'],
            'entry_price': float(pos['entry_price']),
            'exit_price': exit_price,
            'pnl': pnl,
            'close_reason': reason,
        }))

    def get_portfolio_summary(self) -> dict:
        """Resumen del portafolio Polymarket activo (solo sesión activa)."""
        with self.engine.connect() as conn:
            # Obtener sesión activa
            sess_row = conn.execute(
                text("SELECT session_name FROM poly_sessions WHERE status = 'ACTIVE' ORDER BY started_at DESC LIMIT 1")
            ).fetchone()
            active_session = sess_row[0] if sess_row else None

            open_r = conn.execute(
                text('''
                    SELECT COUNT(*) as cnt,
                           COALESCE(SUM(cost_basis), 0) as exposure,
                           COALESCE(SUM(shares), 0) as total_shares
                    FROM poly_positions
                    WHERE status = 'OPEN'
                      AND (:sess IS NULL OR session_name = :sess)
                '''),
                {'sess': active_session},
            ).fetchone()
            closed_r = conn.execute(
                text('''
                    SELECT COUNT(*) as cnt,
                           COALESCE(SUM(pnl), 0) as total_pnl,
                           COUNT(*) FILTER(WHERE pnl > 0) as wins
                    FROM poly_positions
                    WHERE status = 'CLOSED'
                      AND close_reason != 'SESSION_RESET'
                      AND (:sess IS NULL OR session_name = :sess)
                '''),
                {'sess': active_session},
            ).fetchone()

        open_data = dict(open_r._mapping) if open_r else {}
        closed_data = dict(closed_r._mapping) if closed_r else {}

        total_closed = int(closed_data.get('cnt', 0))
        wins = int(closed_data.get('wins', 0))

        return {
            'open_positions': int(open_data.get('cnt', 0)),
            'total_exposure': float(open_data.get('exposure', 0)),
            'total_shares': float(open_data.get('total_shares', 0)),
            'closed_trades': total_closed,
            'total_pnl': float(closed_data.get('total_pnl', 0)),
            'win_rate': (wins / total_closed * 100) if total_closed > 0 else 0,
            'active_session': active_session,
        }

"""
TradeMonitor — Monitorea trades abiertos y cierra al alcanzar SL/TP/Trailing.

Ciclo por trade:
  1. Obtener precio actual del activo
  2. Evaluar trailing dinámico (avanzar SL si corresponde)
  3. Evaluar si se alcanzó SL o TP
  4. Cerrar trade: calcular PnL, actualizar DB, ajustar portfolio
  5. Publicar evento en Redis

Trailing dinámico progresivo:
  - Activación: profit ≥ 1.0R → SL a break-even
  - Cada +0.5R de profit → SL avanza +0.5R adicional
  - SL solo avanza, nunca retrocede
  - Ver docs/TRAILING_DINAMICO.md para flujo técnico completo
"""
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import redis
from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

sys.path.insert(0, '/opt/trading')
load_dotenv('/opt/trading/config/.env')

from core.portfolio_utils import calculate_drawdown, calculate_peak_balance, calculate_risk_exposure, calculate_total_notional
from core.asset_profiles import get_profile
from data.market_feed import MarketFeed, ASSET_MAP

# ── Trailing Dinámico: parámetros (v2 — más agresivo) ────────────
TRAILING_ACTIVATION_R = 0.75  # Activar trailing antes para proteger ganancias
TRAILING_STEP_R = 0.3         # Escalones más finos para seguir mejor el precio
TRAILING_OFFSET_R = 0.75      # SL más ceñido al precio


class TradeMonitor:
    """Monitorea trades abiertos contra precios actuales, cierra en SL/TP."""

    def __init__(self):
        db_url = (
            f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
            f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT', '5432')}"
            f"/{os.getenv('POSTGRES_DB')}"
        )
        self.engine = create_engine(db_url)
        self.redis = redis.Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            password=os.getenv('REDIS_PASSWORD') or None,
            decode_responses=True,
        )
        self.feed = MarketFeed()

    def check_open_trades(self, portfolio: dict, session: dict = None) -> list:
        """Revisa todos los trades abiertos y cierra los que alcanzan SL/TP.

        Returns:
            Lista de dicts con trades cerrados en este ciclo.
        """
        self._current_session = session
        open_trades = self._get_open_trades(session)
        if not open_trades:
            return []

        closed = []
        for trade in open_trades:
            result = self._evaluate_trade(trade)
            if result:
                self._close_trade(trade, result['exit_price'],
                                  result['close_reason'], portfolio)
                closed.append({
                    'trade_id': str(trade['id']),
                    'asset': trade['asset'],
                    'side': trade['side'],
                    'entry_price': float(trade['entry_price']),
                    'exit_price': result['exit_price'],
                    'close_reason': result['close_reason'],
                    'pnl': result['pnl'],
                    'pnl_pct': result['pnl_pct'],
                })
                logger.info(
                    f"TRADE CLOSED: {trade['asset']} {result['close_reason']} "
                    f"PnL=${result['pnl']:+.2f} ({result['pnl_pct']:+.2f}%)"
                )

        return closed

    def _get_open_trades(self, session: dict = None) -> list:
        with self.engine.connect() as conn:
            if session:
                rows = conn.execute(
                    text(
                        "SELECT * FROM trades WHERE status = 'OPEN' "
                        "AND timestamp_open >= :session_start ORDER BY timestamp_open"
                    ),
                    {'session_start': session['started_at']},
                ).fetchall()
            else:
                rows = conn.execute(
                    text("SELECT * FROM trades WHERE status = 'OPEN' ORDER BY timestamp_open")
                ).fetchall()
        return [dict(r._mapping) for r in rows]

    def _get_current_price(self, asset: str) -> Optional[float]:
        """Obtiene el último precio de cierre del activo desde market_data."""
        with self.engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT close FROM market_data
                    WHERE asset = :asset
                    ORDER BY timestamp DESC LIMIT 1
                """),
                {'asset': asset},
            ).fetchone()
        if row:
            return float(row.close)
        return None

    def _get_historical_peak_balance(self) -> float:
        session = getattr(self, '_current_session', None)
        with self.engine.connect() as conn:
            if session and session.get('started_at'):
                row = conn.execute(
                    text(
                        "SELECT COALESCE(MAX(GREATEST(total_balance, COALESCE(peak_balance, total_balance))), 0) AS peak "
                        "FROM portfolio WHERE timestamp >= :session_start"
                    ),
                    {'session_start': session['started_at']},
                ).fetchone()
            else:
                row = conn.execute(
                    text(
                        "SELECT COALESCE(MAX(GREATEST(total_balance, COALESCE(peak_balance, total_balance))), 0) AS peak FROM portfolio"
                    )
                ).fetchone()
        return float(row.peak) if row and row.peak is not None else 0.0

    def _evaluate_trade(self, trade: dict) -> Optional[dict]:
        """Evalúa si un trade debe cerrarse.

        Lógica:
          1. Trailing dinámico: avanza SL por escalones de R
          2. BUY: SL si precio ≤ stop_loss, TP si precio ≥ take_profit
          3. SELL: SL si precio ≥ stop_loss, TP si precio ≤ take_profit

        Returns:
            dict con exit_price, close_reason, pnl, pnl_pct si debe cerrar.
            None si el trade debe permanecer abierto.
        """
        asset = trade['asset']
        current_price = self._get_current_price(asset)
        if current_price is None:
            logger.warning(f"No price data for {asset}, skipping trade check")
            return None

        entry_price = float(trade['entry_price'])
        stop_loss = float(trade['stop_loss'])
        take_profit = float(trade['take_profit'])
        position_size = float(trade['position_size'])
        side = trade['side']

        metadata = trade.get('metadata') or {}
        if isinstance(metadata, str):
            metadata = json.loads(metadata)

        # ── Calcular R (initial_risk) ──
        initial_risk = metadata.get('initial_risk')
        if initial_risk is None:
            if metadata.get('trailing_activated') and abs(entry_price - stop_loss) < 1e-8:
                # Legacy: trailing viejo ya movió SL a entry, recalcular desde ATR o skip
                initial_risk = abs(entry_price * 0.015)  # Fallback: 1.5% del precio como proxy de 1.5×ATR
                logger.warning(f'TRAILING FALLBACK: {asset} initial_risk recovered as {initial_risk:.4f} (1.5% proxy)')
            else:
                initial_risk = abs(entry_price - stop_loss)
        # Protección contra division by zero
        if initial_risk < 1e-10:
            logger.warning(f'ZERO_RISK: {asset} initial_risk={initial_risk}, skipping trailing')
            initial_risk = 0

        # ── Trailing Dinámico (price-following) ──
        # Grid Bot usa TP ajustado a un nivel de grid: trailing contraproducente.
        skip_trailing = trade.get('strategy') == 'GRID_BOT'
        if initial_risk > 0 and not skip_trailing:
            profile = get_profile(asset)
            trailing_activation_r = profile.trailing_activation_r
            trailing_step_r = profile.trailing_step_r
            trailing_offset_r = profile.trailing_offset_r  # distancia SL al precio actual

            if side == 'BUY':
                profit_r = (current_price - entry_price) / initial_risk
            else:
                profit_r = (entry_price - current_price) / initial_risk

            if profit_r >= trailing_activation_r:
                steps = max(1, int((profit_r - trailing_activation_r) / trailing_step_r))
                locked_r = steps * trailing_step_r

                # Fórmula price-following: el SL sigue al precio actual con un offset fijo.
                # Esto permite que INJ (offset=0.60R) deje más espacio y no salga a $6
                # cuando el TP debería estar en $18-41.
                # Previamente: new_sl = entry_price ± locked_r × risk (anclado al entry).
                # Ahora: new_sl = current_price ∓ trailing_offset_r × risk (sigue el precio).
                if side == 'BUY':
                    new_sl = current_price - trailing_offset_r * initial_risk
                    should_update = new_sl > stop_loss
                else:
                    new_sl = current_price + trailing_offset_r * initial_risk
                    should_update = new_sl < stop_loss

                if should_update:
                    self._update_trailing(
                        trade['id'], new_sl, initial_risk, steps,
                        locked_r, metadata, asset, side,
                    )
                    stop_loss = new_sl
                    logger.info(
                        f"TRAILING: {asset} Level {steps} "
                        f"SL→{new_sl:.2f} (locked {locked_r:.1f}R)"
                    )

        # ── Determinar si trailing fue activado ──
        trailing_active = (
            metadata.get('trailing_activated', False)
            or stop_loss != float(trade['stop_loss'])
        )

        # ── Check SL / TP ──
        if side == 'BUY':
            if current_price <= stop_loss:
                pnl = (stop_loss - entry_price) * position_size
                pnl_pct = ((stop_loss - entry_price) / entry_price) * 100
                return {
                    'exit_price': stop_loss,
                    'close_reason': 'TRAILING_STOP' if trailing_active else 'STOP_LOSS',
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                }
            if current_price >= take_profit:
                pnl = (take_profit - entry_price) * position_size
                pnl_pct = ((take_profit - entry_price) / entry_price) * 100
                return {
                    'exit_price': take_profit,
                    'close_reason': 'TAKE_PROFIT',
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                }

        elif side == 'SELL':
            if current_price >= stop_loss:
                pnl = (entry_price - stop_loss) * position_size
                pnl_pct = ((entry_price - stop_loss) / entry_price) * 100
                return {
                    'exit_price': stop_loss,
                    'close_reason': 'TRAILING_STOP' if trailing_active else 'STOP_LOSS',
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                }
            if current_price <= take_profit:
                pnl = (entry_price - take_profit) * position_size
                pnl_pct = ((entry_price - take_profit) / entry_price) * 100
                return {
                    'exit_price': take_profit,
                    'close_reason': 'TAKE_PROFIT',
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                }

        return None

    def _update_trailing(self, trade_id, new_sl: float, initial_risk: float,
                         level: int, locked_r: float, existing_metadata: dict,
                         asset: str, side: str):
        """Actualiza SL y metadata de trailing dinámico."""
        now = datetime.now(timezone.utc).isoformat()
        meta = dict(existing_metadata) if existing_metadata else {}

        meta['trailing_activated'] = True
        meta['initial_risk'] = initial_risk
        meta['trailing_level'] = level

        history = meta.get('trailing_history', [])
        history.append({
            'level': level,
            'sl': round(new_sl, 8),
            'locked_r': locked_r,
            'ts': now,
        })
        meta['trailing_history'] = history

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE trades SET stop_loss = :sl, metadata = CAST(:meta AS jsonb) "
                    "WHERE id = :id"
                ),
                {'sl': new_sl, 'meta': json.dumps(meta), 'id': trade_id},
            )

        # Notificar al dashboard
        self.redis.publish('trades:trailing', json.dumps({
            'trade_id': str(trade_id),
            'asset': asset,
            'side': side,
            'level': level,
            'new_sl': round(new_sl, 2),
            'locked_r': locked_r,
            'initial_risk': initial_risk,
        }))

    def _close_trade(self, trade: dict, exit_price: float,
                     close_reason: str, portfolio: dict):
        """Cierra un trade: actualiza DB (trade + portfolio) y publica en Redis."""
        entry_price = float(trade['entry_price'])
        position_size = float(trade['position_size'])
        side = trade['side']

        if side == 'BUY':
            pnl = (exit_price - entry_price) * position_size
        else:
            pnl = (entry_price - exit_price) * position_size

        pnl_pct = (pnl / (entry_price * position_size)) * 100 if entry_price else 0

        now = datetime.now(timezone.utc)

        # 1. Actualizar trade en DB
        with self.engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE trades
                    SET status = 'CLOSED',
                        exit_price = :exit_price,
                        close_reason = :close_reason,
                        pnl = :pnl,
                        pnl_pct = :pnl_pct,
                        timestamp_close = :ts_close
                    WHERE id = :id
                """),
                {
                    'exit_price': exit_price,
                    'close_reason': close_reason,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'ts_close': now,
                    'id': trade['id'],
                },
            )

        # 2. Actualizar portfolio: devolver capital + PnL
        position_value = entry_price * position_size
        new_balance = portfolio['total_balance'] + pnl

        remaining_open = self._get_open_trades(session=getattr(self, '_current_session', None))
        total_risk_exposure = calculate_risk_exposure(remaining_open)
        new_exposure_pct = total_risk_exposure / new_balance if new_balance > 0 else 0
        total_notional = calculate_total_notional(remaining_open)
        new_cash = new_balance - total_notional

        historical_peak = self._get_historical_peak_balance()
        new_peak = calculate_peak_balance(
            new_balance,
            portfolio.get('peak_balance', new_balance),
            historical_peak,
        )
        new_drawdown = calculate_drawdown(new_balance, new_peak)

        portfolio['total_balance'] = new_balance
        portfolio['available_cash'] = new_cash
        portfolio['peak_balance'] = new_peak
        portfolio['drawdown_pct'] = new_drawdown
        portfolio['exposure_pct'] = new_exposure_pct
        portfolio['historical_max_drawdown'] = max(
            float(portfolio.get('historical_max_drawdown', 0.0)),
            new_drawdown,
        )
        portfolio['halt_triggered'] = bool(portfolio.get('halt_triggered', False) or new_drawdown >= 0.10)
        portfolio['recommended_action'] = 'MAINTAIN_HALT' if portfolio['halt_triggered'] else 'NORMAL'

        # 3. Guardar snapshot del portfolio
        with self.engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO portfolio
                        (total_balance, available_cash, exposure_pct, pnl_day,
                         drawdown_pct, peak_balance, positions, timestamp)
                    VALUES (:balance, :cash, :exposure, :pnl_day,
                            :drawdown, :peak, :positions, :ts)
                """),
                {
                    'balance': new_balance,
                    'cash': new_cash,
                    'exposure': new_exposure_pct,
                    'pnl_day': pnl,
                    'drawdown': new_drawdown,
                    'peak': new_peak,
                    'positions': json.dumps({
                        t['asset']: float(t['position_size'])
                        for t in remaining_open
                    }),
                    'ts': now,
                },
            )

        # 4. Publicar evento en Redis
        self.redis.publish('trades:closed', json.dumps({
            'trade_id': str(trade['id']),
            'asset': trade['asset'],
            'side': trade['side'],
            'entry_price': entry_price,
            'exit_price': exit_price,
            'pnl': round(pnl, 2),
            'pnl_pct': round(pnl_pct, 4),
            'close_reason': close_reason,
        }))

        logger.info(
            f"CLOSED {trade['asset']} {trade['side']}: "
            f"entry={entry_price:.2f} exit={exit_price:.2f} "
            f"PnL=${pnl:+.2f} ({pnl_pct:+.2f}%) reason={close_reason} "
            f"New balance=${new_balance:,.2f}"
        )


# ── CLI test ──
if __name__ == '__main__':
    monitor = TradeMonitor()
    portfolio = {
        'total_balance': 10000.0,
        'available_cash': 10000.0,
        'exposure_pct': 0.0,
        'drawdown_pct': 0.0,
        'peak_balance': 10000.0,
    }
    closed = monitor.check_open_trades(portfolio)
    print(f"\nClosed {len(closed)} trades")
    for c in closed:
        print(f"  {c['asset']}: {c['close_reason']} PnL=${c['pnl']:+.2f}")

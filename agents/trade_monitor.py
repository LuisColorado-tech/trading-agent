"""
TradeMonitor — Monitorea trades abiertos y cierra al alcanzar SL/TP/Trailing.

Ciclo por trade:
  1. Obtener precio actual del activo
  2. Evaluar si se alcanzó SL, TP o trailing stop
  3. Cerrar trade: calcular PnL, actualizar DB, ajustar portfolio
  4. Publicar evento en Redis

Trailing stop: cuando el precio supera 1.5×ATR de ganancia desde entry,
mover SL a break-even (entry price).
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

from data.market_feed import MarketFeed, ASSET_MAP


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

    def check_open_trades(self, portfolio: dict) -> list:
        """Revisa todos los trades abiertos y cierra los que alcanzan SL/TP.

        Returns:
            Lista de dicts con trades cerrados en este ciclo.
        """
        open_trades = self._get_open_trades()
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

    def _get_open_trades(self) -> list:
        with self.engine.connect() as conn:
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

    def _evaluate_trade(self, trade: dict) -> Optional[dict]:
        """Evalúa si un trade debe cerrarse.

        Lógica:
          - BUY: SL si precio <= stop_loss, TP si precio >= take_profit
          - SELL: SL si precio >= stop_loss, TP si precio <= take_profit
          - Trailing: si ganancia > 1.5×(entry-SL), mover SL a entry (break-even)

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

        # Trailing stop: mover SL a break-even cuando ganancia > 1.5 × riesgo
        risk_distance = abs(entry_price - stop_loss)
        trailing_threshold = entry_price + (1.5 * risk_distance) if side == 'BUY' \
            else entry_price - (1.5 * risk_distance)

        if side == 'BUY':
            # Trailing: si precio superó threshold, SL sube a entry
            if current_price >= trailing_threshold and stop_loss < entry_price:
                self._update_stop_loss(trade['id'], entry_price)
                stop_loss = entry_price
                logger.info(
                    f"TRAILING STOP: {asset} SL moved to break-even {entry_price:.2f}"
                )

            # Check SL
            if current_price <= stop_loss:
                pnl = (stop_loss - entry_price) * position_size
                pnl_pct = ((stop_loss - entry_price) / entry_price) * 100
                return {
                    'exit_price': stop_loss,
                    'close_reason': 'STOP_LOSS',
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                }

            # Check TP
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
            # Trailing: si precio bajó del threshold, SL baja a entry
            if current_price <= trailing_threshold and stop_loss > entry_price:
                self._update_stop_loss(trade['id'], entry_price)
                stop_loss = entry_price
                logger.info(
                    f"TRAILING STOP: {asset} SL moved to break-even {entry_price:.2f}"
                )

            # Check SL (SELL: SL es precio más alto)
            if current_price >= stop_loss:
                pnl = (entry_price - stop_loss) * position_size
                pnl_pct = ((entry_price - stop_loss) / entry_price) * 100
                return {
                    'exit_price': stop_loss,
                    'close_reason': 'STOP_LOSS',
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                }

            # Check TP (SELL: TP es precio más bajo)
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

    def _update_stop_loss(self, trade_id, new_stop_loss: float):
        """Actualiza el SL de un trade (para trailing stop)."""
        with self.engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE trades SET stop_loss = :sl,
                    metadata = jsonb_set(
                        COALESCE(metadata, '{}'::jsonb),
                        '{trailing_activated}', 'true'::jsonb
                    )
                    WHERE id = :id
                """),
                {'sl': new_stop_loss, 'id': trade_id},
            )

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
        new_cash = portfolio['available_cash'] + position_value + pnl
        new_peak = max(portfolio.get('peak_balance', new_balance), new_balance)
        new_drawdown = (new_peak - new_balance) / new_peak if new_peak > 0 else 0

        # Recalcular exposición basada en trades abiertos restantes
        remaining_open = self._get_open_trades()  # ya sin el recién cerrado
        total_exposure = sum(
            float(t['entry_price']) * float(t['position_size'])
            for t in remaining_open
        )
        new_exposure_pct = total_exposure / new_balance if new_balance > 0 else 0

        portfolio['total_balance'] = new_balance
        portfolio['available_cash'] = new_cash
        portfolio['peak_balance'] = new_peak
        portfolio['drawdown_pct'] = new_drawdown
        portfolio['exposure_pct'] = new_exposure_pct

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

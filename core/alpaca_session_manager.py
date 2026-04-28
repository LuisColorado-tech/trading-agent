"""
alpaca_session_manager.py — Gestión de sesiones de paper/live trading en Alpaca.

Alpaca = broker NYSE/NASDAQ con API REST.  Equivale a Kraken pero para acciones.
Tabla principal: stocks_sessions
Trades:          stocks_trades

Endpoints:
  Paper:  https://paper-api.alpaca.markets
  Live:   https://api.alpaca.markets
  Data:   https://data.alpaca.markets
"""
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import requests
from loguru import logger
from sqlalchemy import create_engine, text


_BASE_URL_PAPER = 'https://paper-api.alpaca.markets'
_BASE_URL_LIVE = 'https://api.alpaca.markets'
_DATA_URL = 'https://data.alpaca.markets'


class AlpacaClient:
    """Wrapper liviano sobre la API REST de Alpaca (v2).

    Instanciar con is_paper=True mientras estemos en exploración.
    Cambia a is_paper=False solo cuando PAPER_TRADING=false en .env.
    """

    def __init__(self, api_key: str, secret_key: str, is_paper: bool = True):
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = _BASE_URL_PAPER if is_paper else _BASE_URL_LIVE
        self.data_url = _DATA_URL
        self._headers = {
            'APCA-API-KEY-ID': api_key,
            'APCA-API-SECRET-KEY': secret_key,
            'Content-Type': 'application/json',
        }

    def _get(self, path: str, base: str = None, params: dict = None):
        url = f"{base or self.base_url}{path}"
        r = requests.get(url, headers=self._headers, params=params or {}, timeout=15)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, payload: dict = None):
        url = f"{self.base_url}{path}"
        r = requests.post(url, headers=self._headers, json=payload or {}, timeout=15)
        if not r.ok:
            logger.error(f"Alpaca API error {r.status_code} {path}: {r.text}")
        r.raise_for_status()
        return r.json()

    def _delete(self, path: str):
        url = f"{self.base_url}{path}"
        r = requests.delete(url, headers=self._headers, timeout=15)
        r.raise_for_status()
        return r.status_code

    # ── Cuenta ────────────────────────────────────────────────────────────────

    def get_account(self) -> dict:
        return self._get('/v2/account')

    def get_clock(self) -> dict:
        return self._get('/v2/clock')

    def is_market_open(self) -> bool:
        try:
            return self.get_clock().get('is_open', False)
        except Exception:
            return False

    # ── Posiciones ────────────────────────────────────────────────────────────

    def get_positions(self) -> list:
        return self._get('/v2/positions')

    def get_position(self, symbol: str) -> Optional[dict]:
        try:
            return self._get(f'/v2/positions/{symbol}')
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise

    # ── Órdenes ───────────────────────────────────────────────────────────────

    def get_orders(self, status: str = 'open') -> list:
        return self._get('/v2/orders', params={'status': status})

    def submit_order(
        self,
        symbol: str,
        qty: float = None,
        notional: float = None,
        side: str = 'buy',
        order_type: str = 'market',
        time_in_force: str = 'day',
        limit_price: float = None,
        stop_price: float = None,
        client_order_id: str = None,
    ) -> dict:
        """Envía una orden a Alpaca.

        Args:
            symbol: ticker (ej: 'NVDA')
            qty: cantidad de acciones (usar qty ó notional, no los dos)
            notional: importe en USD (fractional shares)
            side: 'buy' | 'sell'
            order_type: 'market' | 'limit' | 'stop' | 'stop_limit'
            time_in_force: 'day' | 'gtc' | 'ioc' | 'fok'
            limit_price: solo para limit/stop_limit orders
            stop_price: solo para stop/stop_limit orders
            client_order_id: ID propio para tracking
        """
        payload: dict = {
            'symbol': symbol,
            'side': side,
            'type': order_type,
            'time_in_force': time_in_force,
        }
        if qty is not None:
            payload['qty'] = str(qty)
        elif notional is not None:
            payload['notional'] = str(notional)
        else:
            raise ValueError("submit_order requiere qty ó notional")

        if limit_price is not None:
            payload['limit_price'] = str(limit_price)
        if stop_price is not None:
            payload['stop_price'] = str(stop_price)
        if client_order_id:
            payload['client_order_id'] = client_order_id

        return self._post('/v2/orders', payload)

    def cancel_order(self, order_id: str) -> int:
        return self._delete(f'/v2/orders/{order_id}')

    def cancel_all_orders(self) -> int:
        return self._delete('/v2/orders')

    # ── Market data (free tier) ───────────────────────────────────────────────

    def get_bars(
        self,
        symbol: str,
        timeframe: str = '15Min',
        limit: int = 200,
        start: str = None,
        end: str = None,
    ) -> list:
        """Descarga barras OHLCV de Alpaca Data API.

        timeframe: '1Min', '5Min', '15Min', '1Hour', '1Day'
        """
        from datetime import datetime, timedelta, timezone as tz

        # Calcular start automático para asegurar suficiente historia
        if not start:
            _tf_minutes = {
                '1Min': 1, '5Min': 5, '15Min': 15, '1Hour': 60, '1Day': 1440,
            }
            tf_min = _tf_minutes.get(timeframe, 15)
            # Multiplicar por 2.5 para cubrir fines de semana y festivos
            calendar_minutes = int(tf_min * limit * 2.5)
            start_dt = datetime.now(tz.utc) - timedelta(minutes=calendar_minutes)
            start = start_dt.strftime('%Y-%m-%dT%H:%M:%SZ')

        params = {
            'timeframe': timeframe,
            'limit': limit,
            'adjustment': 'split',
            'feed': 'sip',   # sip: datos históricos completos (paper incluido)
            'start': start,
        }
        if end:
            params['end'] = end

        data = self._get(f'/v2/stocks/{symbol}/bars', base=self.data_url, params=params)
        return data.get('bars', [])

    def get_latest_quote(self, symbol: str) -> dict:
        data = self._get(f'/v2/stocks/{symbol}/quotes/latest', base=self.data_url)
        return data.get('quote', {})

    def get_latest_trade(self, symbol: str) -> dict:
        data = self._get(f'/v2/stocks/{symbol}/trades/latest', base=self.data_url)
        return data.get('trade', {})

    def get_snapshot(self, symbol: str) -> dict:
        data = self._get(f'/v2/stocks/{symbol}/snapshot', base=self.data_url)
        return data


def get_alpaca_client(is_paper: bool = None) -> AlpacaClient:
    """Factorymethod: instancia AlpacaClient con claves del .env.

    is_paper=None → lee PAPER_TRADING del entorno (default True si no está seteado).
    """
    api_key = os.getenv('ALPACA_API_KEY', '')
    secret_key = os.getenv('ALPACA_SECRET_KEY', '')

    if not api_key or api_key == 'CHANGE_ME':
        raise RuntimeError(
            "ALPACA_API_KEY no configurada. "
            "Crea una cuenta en https://alpaca.markets y añade las claves a /opt/trading/config/.env"
        )

    if is_paper is None:
        is_paper = os.getenv('PAPER_TRADING', 'true').lower() == 'true'

    client = AlpacaClient(api_key, secret_key, is_paper=is_paper)
    logger.info(f"AlpacaClient inicializado ({'PAPER' if is_paper else 'LIVE'})")
    return client


# ── Session Manager ───────────────────────────────────────────────────────────

class AlpacaSessionManager:
    """Gestiona la vida de sesiones STOCKS_SESSION_NNN en PostgreSQL.

    Replica el patrón de PaperSessionManager pero para stocks.
    """

    def __init__(self, db_url: str):
        self.engine = create_engine(db_url)

    def get_active_session(self) -> Optional[dict]:
        with self.engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT * FROM stocks_sessions
                    WHERE status = 'ACTIVE'
                    ORDER BY started_at DESC LIMIT 1
                """)
            ).fetchone()
        return dict(row._mapping) if row else None

    def get_session(self, session_id: str) -> Optional[dict]:
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM stocks_sessions WHERE id = :id LIMIT 1"),
                {'id': session_id},
            ).fetchone()
        return dict(row._mapping) if row else None

    def ensure_active_session(self, initial_balance: float = 220.0) -> dict:
        active = self.get_active_session()
        if active:
            return active
        return self.create_session(initial_balance=initial_balance)

    def create_session(self, initial_balance: float = 220.0, session_name: str = None) -> dict:
        now = datetime.now(timezone.utc)
        if session_name is None:
            with self.engine.connect() as conn:
                count = conn.execute(text('SELECT COUNT(*) FROM stocks_sessions')).scalar() or 0
            session_name = f'STOCKS_SESSION_{count + 1:03d}'

        session_id = str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO stocks_sessions
                        (id, session_name, initial_balance, current_balance, total_trades,
                         winning_trades, profit_factor, max_drawdown, status, started_at)
                    VALUES
                        (:id, :name, :bal, :bal, 0, 0, NULL, NULL, 'ACTIVE', :now)
                """),
                {'id': session_id, 'name': session_name, 'bal': initial_balance, 'now': now},
            )

        logger.info(f"Sesión stocks creada: {session_name} | balance={initial_balance}")
        return self.get_session(session_id)

    def close_session(self, session_id: str, final_balance: float, reason: str = 'manual') -> None:
        now = datetime.now(timezone.utc)
        with self.engine.connect() as conn:
            total = conn.execute(
                text("SELECT COUNT(*) FROM stocks_trades WHERE session_id = :id AND status = 'CLOSED'"),
                {'id': session_id},
            ).scalar() or 0
            wins = conn.execute(
                text("SELECT COUNT(*) FROM stocks_trades WHERE session_id = :id AND status = 'CLOSED' AND pnl > 0"),
                {'id': session_id},
            ).scalar() or 0

        with self.engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE stocks_sessions
                    SET status = 'CLOSED', ended_at = :now, final_balance = :bal,
                        total_trades = :total, winning_trades = :wins
                    WHERE id = :id
                """),
                {'now': now, 'bal': final_balance, 'total': total, 'wins': wins, 'id': session_id},
            )
        logger.info(f"Sesión {session_id} cerrada. final={final_balance:.2f} reason={reason}")

    # ── Trades ────────────────────────────────────────────────────────────────

    def open_trade(
        self,
        session_id: str,
        symbol: str,
        direction: str,
        entry_price: float,
        qty: float,
        notional: float,
        stop_loss: float,
        take_profit: float,
        strategy: str,
        alpaca_order_id: str = None,
        xsignal_boost: float = 0.0,
    ) -> str:
        trade_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        with self.engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO stocks_trades
                        (id, session_id, symbol, direction, entry_price, qty, notional,
                         stop_loss, take_profit, strategy, alpaca_order_id,
                         xsignal_boost, status, opened_at)
                    VALUES
                        (:id, :sid, :sym, :dir, :ep, :qty, :notional,
                         :sl, :tp, :strat, :oid,
                         :xboost, 'OPEN', :now)
                """),
                {
                    'id': trade_id, 'sid': session_id, 'sym': symbol,
                    'dir': direction, 'ep': entry_price, 'qty': qty,
                    'notional': notional, 'sl': stop_loss, 'tp': take_profit,
                    'strat': strategy, 'oid': alpaca_order_id,
                    'xboost': xsignal_boost, 'now': now,
                },
            )
        logger.info(f"Trade abierto {symbol} {direction} @ {entry_price:.4f} | id={trade_id}")
        return trade_id

    def close_trade(
        self,
        trade_id: str,
        exit_price: float,
        exit_reason: str = 'manual',
    ) -> Optional[dict]:
        now = datetime.now(timezone.utc)
        with self.engine.connect() as conn:
            trade = conn.execute(
                text("SELECT * FROM stocks_trades WHERE id = :id"),
                {'id': trade_id},
            ).fetchone()

        if not trade:
            logger.error(f"Trade {trade_id} no encontrado")
            return None

        t = dict(trade._mapping)
        if t['direction'] == 'BUY':
            pnl = (exit_price - float(t['entry_price'])) * float(t['qty'])
        else:
            pnl = (float(t['entry_price']) - exit_price) * float(t['qty'])

        with self.engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE stocks_trades
                    SET status = 'CLOSED', exit_price = :ep, pnl = :pnl,
                        exit_reason = :reason, closed_at = :now
                    WHERE id = :id
                """),
                {'ep': exit_price, 'pnl': pnl, 'reason': exit_reason, 'now': now, 'id': trade_id},
            )

        logger.info(f"Trade cerrado {t['symbol']} @ {exit_price:.4f} pnl={pnl:+.2f} reason={exit_reason}")
        return {**t, 'exit_price': exit_price, 'pnl': pnl, 'exit_reason': exit_reason}

    def get_open_trades(self, session_id: str) -> list:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT * FROM stocks_trades
                    WHERE session_id = :id AND status = 'OPEN'
                    ORDER BY opened_at DESC
                """),
                {'id': session_id},
            ).fetchall()
        return [dict(r._mapping) for r in rows]

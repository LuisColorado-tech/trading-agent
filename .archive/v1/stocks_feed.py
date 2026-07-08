"""
StocksFeed — Datos OHLCV para acciones NYSE/NASDAQ.

Primary:  Alpaca Data API (requiere ALPACA_API_KEY en .env)
Fallback: yfinance (libre, sin claves)

Timeframes soportados: 1m, 5m, 15m, 1h, 1d
Activos del portafolio: NVDA, TSLA, AAPL, SPY, QQQ, META, AMZN, GLD

Uso:
  feed = StocksFeed()
  df = feed.get_latest('NVDA', '15m', n=200)
  df = feed.get_latest('SPY', '1d', n=100)
"""
import os
from datetime import datetime, timedelta, timezone

import pandas as pd
from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

load_dotenv('/opt/trading/config/.env')

# Mapeo de timeframes propios → Alpaca API → yfinance interval
_TF_ALPACA = {
    '1m':  '1Min',
    '5m':  '5Min',
    '15m': '15Min',
    '1h':  '1Hour',
    '1d':  '1Day',
}
_TF_YFINANCE = {
    '1m':  '1m',
    '5m':  '5m',
    '15m': '15m',
    '1h':  '1h',
    '1d':  '1d',
}

# Activos del portafolio de acciones
STOCKS_ASSETS = ['NVDA', 'TSLA', 'AAPL', 'SPY', 'QQQ', 'META', 'AMZN', 'GLD']

# Número de barras a descargar por defecto
OHLCV_LIMIT = 500


class StocksFeed:
    """Descarga y persiste OHLCV de acciones.

    Intenta primero Alpaca (si hay claves). Si falla o no hay claves, usa yfinance.
    """

    def __init__(self):
        db_url = (
            f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
            f"@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}"
            f"/{os.getenv('POSTGRES_DB', 'trading_agent')}"
        )
        self.engine = create_engine(db_url)
        self._alpaca = None
        self._alpaca_available = False
        self._init_alpaca()

    def _init_alpaca(self):
        api_key = os.getenv('ALPACA_API_KEY', 'CHANGE_ME')
        secret_key = os.getenv('ALPACA_SECRET_KEY', 'CHANGE_ME')
        if api_key and api_key != 'CHANGE_ME':
            try:
                from core.alpaca_session_manager import AlpacaClient
                is_paper = os.getenv('PAPER_TRADING', 'true').lower() == 'true'
                self._alpaca = AlpacaClient(api_key, secret_key, is_paper=is_paper)
                self._alpaca_available = True
                logger.info("StocksFeed: Alpaca disponible como fuente primaria")
            except Exception as e:
                logger.warning(f"StocksFeed: Alpaca no disponible ({e}) → usando yfinance")
        else:
            logger.info("StocksFeed: claves Alpaca no configuradas → usando yfinance como única fuente")

    # ── API pública ───────────────────────────────────────────────────────────

    def get_latest(self, symbol: str, timeframe: str = '15m', n: int = 200) -> pd.DataFrame:
        """Descarga las últimas n barras OHLCV de symbol en timeframe.

        Intenta Alpaca primero. Si falla o no hay claves, usa yfinance.
        Guarda en PostgreSQL tabla stocks_ohlcv para cache.
        """
        symbol = symbol.upper()

        # Intentar Alpaca
        MIN_BARS = 50  # mínimo para calcular EMA50
        if self._alpaca_available:
            try:
                df = self._fetch_alpaca(symbol, timeframe, n)
                if len(df) >= MIN_BARS:
                    self._persist(symbol, timeframe, df)
                    return df.tail(n)
                elif not df.empty:
                    logger.debug(f"StocksFeed Alpaca insuficiente {symbol}/{timeframe}: {len(df)} barras → fallback yfinance")
            except Exception as e:
                logger.warning(f"StocksFeed Alpaca error {symbol}/{timeframe}: {e} → fallback yfinance")

        # Fallback yfinance
        try:
            df = self._fetch_yfinance(symbol, timeframe, n)
            if not df.empty:
                self._persist(symbol, timeframe, df)
                return df.tail(n)
        except Exception as e:
            logger.error(f"StocksFeed yfinance error {symbol}/{timeframe}: {e}")

        # Último recurso: leer de PostgreSQL
        return self._read_from_db(symbol, timeframe, n)

    def is_market_open(self) -> bool:
        """Verifica si NYSE/NASDAQ está abierto ahora."""
        if self._alpaca_available:
            try:
                return self._alpaca.is_market_open()
            except Exception:
                pass
        # Fallback: horario NYSE 14:30–21:00 UTC (Mon-Fri)
        now = datetime.now(timezone.utc)
        if now.weekday() >= 5:  # Sat=5, Sun=6
            return False
        return (now.hour == 14 and now.minute >= 30) or (15 <= now.hour <= 20)

    def get_price(self, symbol: str) -> float:
        """Precio actual (último trade). Retorna None si el dato es stale o congelado."""
        symbol = symbol.upper()
        
        if self._alpaca_available:
            try:
                trade = self._alpaca.get_latest_trade(symbol)
                price = float(trade.get('p', 0))
                ts = trade.get('t', '')
                
                # Validar frescura del timestamp
                if ts:
                    from datetime import datetime as dt
                    try:
                        trade_time = dt.fromisoformat(ts.replace('Z', '+00:00'))
                        age = (dt.now(timezone.utc) - trade_time).total_seconds()
                        if age > 300:  # 5 minutos → stale
                            logger.warning(f"STOCKS FEED: stale {symbol} last trade {age:.0f}s ago")
                            return None
                    except (ValueError, TypeError):
                        pass
                
                # Detectar precio congelado (mismo precio por >5 min)
                if not hasattr(self, '_last_price'):
                    self._last_price = {}
                last = self._last_price.get(symbol)
                if last and abs(price - last['price']) < 0.01:
                    from datetime import datetime as dt
                    frozen_secs = (dt.now(timezone.utc) - last['ts']).total_seconds()
                    if frozen_secs > 300:
                        logger.warning(f"STOCKS FEED: frozen {symbol} ${price:.2f} for {frozen_secs:.0f}s")
                        return None
                
                self._last_price[symbol] = {'price': price, 'ts': dt.now(timezone.utc)}
                return price
            except Exception as e:
                logger.debug(f"STOCKS FEED: price error {symbol}: {e}")
        return None  # Sin dato fresco → no operar

    def get_macro_bias(self) -> str:
        """Bias macro basado en SPY y QQQ.

        Returns:
            'BULL' | 'BEAR' | 'NEUTRAL'
        """
        try:
            spy = self.get_latest('SPY', '1d', 20)
            qqq = self.get_latest('QQQ', '1d', 20)
            if spy.empty or qqq.empty:
                return 'NEUTRAL'

            spy_trend = spy.iloc[-1]['close'] > spy['close'].rolling(10).mean().iloc[-1]
            qqq_trend = qqq.iloc[-1]['close'] > qqq['close'].rolling(10).mean().iloc[-1]

            if spy_trend and qqq_trend:
                return 'BULL'
            elif not spy_trend and not qqq_trend:
                return 'BEAR'
            return 'NEUTRAL'
        except Exception:
            return 'NEUTRAL'

    def get_macro_severity(self) -> float:
        """Severidad del macro bias: qué tan lejos está el precio de la SMA10.

        Returns porcentaje (0.0 = en la SMA, positivo = bullish, negativo = bearish).
        Usado para el filtro macro con gradiente en vez de binario (v3).
        """
        try:
            spy = self.get_latest('SPY', '1d', 20)
            qqq = self.get_latest('QQQ', '1d', 20)
            if spy.empty or qqq.empty:
                return 0.0

            spy_sma = spy['close'].rolling(10).mean().iloc[-1]
            qqq_sma = qqq['close'].rolling(10).mean().iloc[-1]
            spy_close = spy.iloc[-1]['close']
            qqq_close = qqq.iloc[-1]['close']

            spy_pct = (spy_close - spy_sma) / spy_sma * 100
            qqq_pct = (qqq_close - qqq_sma) / qqq_sma * 100

            return (spy_pct + qqq_pct) / 2  # promedio de ambos
        except Exception:
            return 0.0

    # ── Fuentes de datos ─────────────────────────────────────────────────────

    def _fetch_alpaca(self, symbol: str, timeframe: str, n: int) -> pd.DataFrame:
        tf = _TF_ALPACA.get(timeframe)
        if not tf:
            raise ValueError(f"Timeframe {timeframe} no soportado en Alpaca")

        bars = self._alpaca.get_bars(symbol, timeframe=tf, limit=n)
        if not bars:
            return pd.DataFrame()

        rows = []
        for bar in bars:
            rows.append({
                'timestamp': pd.Timestamp(bar['t']),
                'open':   float(bar['o']),
                'high':   float(bar['h']),
                'low':    float(bar['l']),
                'close':  float(bar['c']),
                'volume': float(bar['v']),
            })

        df = pd.DataFrame(rows).set_index('timestamp').sort_index()
        return df

    def _fetch_yfinance(self, symbol: str, timeframe: str, n: int) -> pd.DataFrame:
        import yfinance as yf

        interval = _TF_YFINANCE.get(timeframe, '15m')
        # yfinance period máximo por interval
        period_map = {'1m': '7d', '5m': '60d', '15m': '60d', '1h': '730d', '1d': '2y'}
        period = period_map.get(timeframe, '60d')

        ticker = yf.Ticker(symbol)
        raw = ticker.history(period=period, interval=interval, auto_adjust=True)
        if raw.empty:
            return pd.DataFrame()

        df = raw.rename(columns={
            'Open': 'open', 'High': 'high', 'Low': 'low',
            'Close': 'close', 'Volume': 'volume',
        })[['open', 'high', 'low', 'close', 'volume']]
        df.index.name = 'timestamp'
        return df.tail(n)

    # ── Persistencia ─────────────────────────────────────────────────────────

    def _persist(self, symbol: str, timeframe: str, df: pd.DataFrame) -> None:
        """Guarda barras en stocks_ohlcv (upsert por timestamp+symbol+timeframe)."""
        if df.empty:
            return
        try:
            rows = []
            for ts, row in df.iterrows():
                rows.append({
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'timestamp': ts,
                    'open':   float(row['open']),
                    'high':   float(row['high']),
                    'low':    float(row['low']),
                    'close':  float(row['close']),
                    'volume': float(row['volume']),
                })
            with self.engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO stocks_ohlcv (symbol, timeframe, timestamp, open, high, low, close, volume)
                        VALUES (:symbol, :timeframe, :timestamp, :open, :high, :low, :close, :volume)
                        ON CONFLICT (symbol, timeframe, timestamp) DO UPDATE
                        SET open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                            close=EXCLUDED.close, volume=EXCLUDED.volume
                    """),
                    rows,
                )
        except Exception as e:
            logger.debug(f"stocks_ohlcv persist error ({e}) — tabla puede no existir aún")

    def _read_from_db(self, symbol: str, timeframe: str, n: int) -> pd.DataFrame:
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT timestamp, open, high, low, close, volume
                        FROM stocks_ohlcv
                        WHERE symbol = :sym AND timeframe = :tf
                        ORDER BY timestamp DESC LIMIT :n
                    """),
                    {'sym': symbol, 'tf': timeframe, 'n': n},
                ).fetchall()
            if not rows:
                return pd.DataFrame()
            df = pd.DataFrame([dict(r._mapping) for r in rows])
            df = df.set_index('timestamp').sort_index()
            return df
        except Exception:
            return pd.DataFrame()


# ── CLI rápido para verificar ─────────────────────────────────────────────────

if __name__ == '__main__':
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else 'NVDA'
    tf  = sys.argv[2] if len(sys.argv) > 2 else '15m'
    n   = int(sys.argv[3]) if len(sys.argv) > 3 else 100

    feed = StocksFeed()
    print(f"\nDescargando {n} barras de {sym}/{tf}...")
    df = feed.get_latest(sym, tf, n)
    if df.empty:
        print("Sin datos — verifica claves Alpaca o conexión")
    else:
        print(f"OK: {len(df)} barras | {df.index[0]} → {df.index[-1]}")
        print(df.tail(5).to_string())
        print(f"\nMacro bias (SPY+QQQ): {feed.get_macro_bias()}")

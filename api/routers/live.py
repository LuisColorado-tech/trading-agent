"""Router: SSE — stream de precios en tiempo real y señales nuevas."""
import asyncio
import json
from datetime import datetime, timezone, timedelta

import yfinance as yf
from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from api.db import q

router = APIRouter()

UNIVERSE = ['TSLA', 'AAPL', 'AMZN', 'NVDA', 'META', 'QQQ', 'GLD', 'EEM', 'FXI', 'EWJ',
            'BTC-USD', 'ETH-USD', 'SOL-USD']

_price_cache: dict = {}
_cache_ts: datetime | None = None
_CACHE_TTL = 30  # segundos


def _fetch_prices() -> dict:
    global _price_cache, _cache_ts
    now = datetime.now(timezone.utc)
    if _cache_ts and (now - _cache_ts).seconds < _CACHE_TTL:
        return _price_cache

    result = {}
    try:
        tickers = yf.download(
            UNIVERSE,
            period='2d',
            interval='1m',
            progress=False,
            auto_adjust=True,
            threads=True,
        )
        closes = tickers['Close']
        for sym in UNIVERSE:
            if sym in closes.columns:
                series = closes[sym].dropna()
                if len(series) >= 2:
                    last = float(series.iloc[-1])
                    prev = float(series.iloc[-2])
                    result[sym] = {
                        'price': round(last, 4),
                        'change_pct': round((last - prev) / prev * 100, 2) if prev > 0 else 0,
                    }
    except Exception:
        pass

    _price_cache = result
    _cache_ts = now
    return result


@router.get('/prices')
def get_prices():
    """Snapshot de precios actuales (REST, con cache 30s)."""
    return _fetch_prices()


@router.get('/stream')
async def price_stream():
    """SSE: emite precios + señales nuevas cada 30 segundos."""
    async def generator():
        last_signal_id = None

        while True:
            payload = {}

            # Precios
            try:
                payload['prices'] = _fetch_prices()
            except Exception:
                payload['prices'] = {}

            # Señales recientes (últimos 5 minutos)
            try:
                cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
                new_signals = q("""
                    SELECT id, asset, signal_type, direction, score, timestamp
                    FROM signals
                    WHERE timestamp > :cutoff
                    ORDER BY timestamp DESC LIMIT 10
                """, {'cutoff': cutoff})
                payload['signals'] = new_signals
            except Exception:
                payload['signals'] = []

            # Stocks trades recientes
            try:
                cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
                new_trades = q("""
                    SELECT id, symbol, direction, entry_price, strategy, opened_at
                    FROM stocks_trades
                    WHERE opened_at > :cutoff
                    ORDER BY opened_at DESC LIMIT 5
                """, {'cutoff': cutoff})
                payload['stocks_trades'] = new_trades
            except Exception:
                payload['stocks_trades'] = []

            yield {
                'event': 'update',
                'data': json.dumps(payload, default=str),
            }
            await asyncio.sleep(30)

    return EventSourceResponse(generator())

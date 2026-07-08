"""
Kraken Futures Data Feed — Cliente de datos para Basis Trade.

Provee:
  - Funding rates actuales e históricos
  - Lista de contratos futuros disponibles
  - Precios spot y futuros para cálculo del basis
  - Cálculo de funding rate anualizado
"""
import time
from datetime import datetime, timezone
from typing import Optional

import ccxt

from core.kraken_futures_session import KrakenFuturesSession


class KrakenFuturesFeed:
    """Feed de datos para estrategia de Basis Trade."""

    # Mapeo: crypto → símbolo Kraken Futures
    FUTURES_SYMBOLS = {
        'BTC': 'PF_XBTUSD',
        'ETH': 'PF_ETHUSD',
    }

    # Mapeo: crypto → par spot en Kraken
    SPOT_PAIRS = {
        'BTC': 'BTC/USDT',
        'ETH': 'ETH/USDT',
    }

    # Funding rate se paga cada 8 horas = 3 veces al día
    FUNDING_INTERVALS_PER_DAY = 3.0

    def __init__(self, paper: bool = True):
        self.paper = paper
        self.session = KrakenFuturesSession(paper=paper)
        self._spot_exchange = ccxt.kraken({'enableRateLimit': True})
        self._funding_cache: dict[str, list] = {}
        self._last_fetch: dict[str, float] = {}

    def get_funding_rate(self, asset: str) -> Optional[float]:
        """Obtiene el funding rate actual para un activo.

        Returns:
            Funding rate como decimal (ej. 0.0001 = 0.01%).
        """
        symbol = self.FUTURES_SYMBOLS.get(asset)
        if not symbol:
            return None
        return self.session.get_funding_rate(symbol)

    def get_funding_rate_annual(self, asset: str) -> Optional[float]:
        """Funding rate anualizado para un activo.

        Returns:
            Porcentaje anual (ej. 10.95 = 10.95% APY).
        """
        rate = self.get_funding_rate(asset)
        if rate is None:
            return None
        return rate * self.FUNDING_INTERVALS_PER_DAY * 365 * 100

    def get_spot_price(self, asset: str) -> Optional[float]:
        """Obtiene precio spot actual desde Kraken."""
        pair = self.SPOT_PAIRS.get(asset)
        if not pair:
            return None
        try:
            ticker = self._spot_exchange.fetch_ticker(pair)
            return float(ticker.get('last', 0)) if ticker else None
        except Exception:
            return None

    def get_futures_price(self, asset: str) -> Optional[float]:
        """Obtiene precio del futuro desde Kraken Futures."""
        symbol = self.FUTURES_SYMBOLS.get(asset)
        if not symbol:
            return None
        result = self.session._request('GET', f'/derivatives/api/v4/tickers')
        if 'error' in result:
            return None
        for ticker in result.get('tickers', []):
            if ticker.get('symbol') == symbol:
                mark = ticker.get('markPrice')
                if mark is not None:
                    return float(mark)
        return None

    def get_basis_pct(self, asset: str) -> Optional[float]:
        """Calcula el basis = (futuro - spot) / spot como porcentaje."""
        spot = self.get_spot_price(asset)
        fut = self.get_futures_price(asset)
        if spot and fut and spot > 0:
            return (fut - spot) / spot * 100
        return None

    def get_funding_history(self, asset: str, limit: int = 90) -> list:
        """Obtiene historial de funding rates. Cachea por 5 minutos."""
        now = time.time()
        if asset in self._last_fetch and (now - self._last_fetch[asset]) < 300:
            return self._funding_cache.get(asset, [])

        symbol = self.FUTURES_SYMBOLS.get(asset)
        if not symbol:
            return []

        history = self.session.get_funding_rate_history(symbol)
        self._funding_cache[asset] = history[-limit:]
        self._last_fetch[asset] = now
        return self._funding_cache[asset]

    def get_avg_funding_rate(self, asset: str, days: int = 30) -> Optional[float]:
        """Funding rate promedio de los últimos N días."""
        history = self.get_funding_history(asset)
        if not history:
            return None
        intervals = days * self.FUNDING_INTERVALS_PER_DAY
        recent = history[-int(intervals):]
        if not recent:
            return None
        avg = sum(h['funding_rate'] for h in recent) / len(recent)
        return avg

    def get_avg_funding_annual(self, asset: str, days: int = 30) -> Optional[float]:
        """Funding rate anualizado promedio de los últimos N días."""
        avg = self.get_avg_funding_rate(asset, days)
        if avg is None:
            return None
        return avg * self.FUNDING_INTERVALS_PER_DAY * 365 * 100

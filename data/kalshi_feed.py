"""
KalshiFeed — Cliente de la API pública de Kalshi para precios de mercados.

Kalshi tiene mercados "BTC above $X at Y:00?" para cada hora.
La API pública no requiere autenticación para leer precios.

Endpoints:
  GET /markets?event_ticker=BTC-* → lista de mercados BTC
  GET /markets/{ticker} → detalle con precios yes/no
"""
import time
from typing import Optional

import requests
from loguru import logger

KALSHI_API_BASE = 'https://api.elections.kalshi.com/trade-api/v2'


class KalshiFeed:
    """Feed de precios de Kalshi para arbitraje."""

    def __init__(self):
        self._cache: dict = {}
        self._cache_time: float = 0
        self._cache_ttl = 30  # 30 segundos de cache

    def _cached(self, key: str):
        now = time.time()
        if (now - self._cache_time) < self._cache_ttl and key in self._cache:
            return self._cache[key]
        return None

    def _set_cache(self, key: str, data):
        self._cache[key] = data
        self._cache_time = time.time()

    def get_btc_hourly_prices(self, target_hour_utc: int) -> Optional[dict]:
        """Busca el mercado BTC de Kalshi para una hora específica.

        Returns:
            Dict con 'yes', 'no', 'yes_ticker', 'no_ticker' si encuentra.
        """
        cache_key = f'btc_{target_hour_utc}'
        cached = self._cached(cache_key)
        if cached is not None:
            return cached

        try:
            # Buscar mercados BTC
            resp = requests.get(
                f'{KALSHI_API_BASE}/markets',
                params={'event_ticker': 'BTC-', 'limit': 50, 'status': 'open'},
                timeout=10,
            )
            if resp.status_code != 200:
                logger.warning(f'Kalshi API error: {resp.status_code}')
                return None

            data = resp.json()
            markets = data.get('markets', [])

            # Buscar mercado que coincida con la hora
            target_str = f'{target_hour_utc:02d}:00'
            for m in markets:
                ticker = m.get('ticker', '')
                title = m.get('title', '')
                if target_str in title or target_str in ticker:
                    yes_bid = float(m.get('yes_bid', 0) or 0)
                    yes_ask = float(m.get('yes_ask', 0) or 0)
                    no_bid = float(m.get('no_bid', 0) or 0)
                    no_ask = float(m.get('no_ask', 0) or 0)

                    if yes_ask <= 0 or no_ask <= 0:
                        continue

                    # Usar mid price (promedio bid/ask)
                    yes_price = round((yes_bid + yes_ask) / 2 / 100, 4)
                    no_price = round((no_bid + no_ask) / 2 / 100, 4)

                    result = {
                        'yes': yes_price,
                        'no': no_price,
                        'yes_ticker': ticker,
                        'no_ticker': ticker,
                        'market_title': title,
                    }
                    self._set_cache(cache_key, result)
                    return result

        except Exception as e:
            logger.debug(f'Kalshi feed error: {e}')

        return None

    def get_prices_for_arbitrage(self, current_hour_utc: int) -> Optional[dict]:
        """Obtiene precios para el arbitraje de la hora actual (en papel)."""
        return self.get_btc_hourly_prices(current_hour_utc)

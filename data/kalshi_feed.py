"""
KalshiFeed — Cliente de la API de Kalshi para precios de mercados BTC.

Kalshi entierra los mercados BTC dentro de contratos multi-juego
(KXMVESPORTSMULTIGAMEEXTENDED). Los encontramos buscando "Target Price"
con valores en rango BTC ($10K-$200K) entre todos los mercados abiertos.
"""
import os
import re
import time
from typing import Optional

import requests
from loguru import logger

KALSHI_API_BASE = 'https://api.elections.kalshi.com/trade-api/v2'
KALSHI_KEY_ID = os.getenv('KALSHI_API_KEY', '')
_private_key = None


def _load_rsa_key():
    global _private_key
    if _private_key is not None:
        return _private_key
    key_path = os.getenv('KALSHI_PRIVATE_KEY_PATH', '')
    if not key_path or not os.path.exists(key_path):
        return None
    try:
        from Crypto.PublicKey import RSA
        with open(key_path) as f:
            _private_key = RSA.import_key(f.read())
        return _private_key
    except Exception as e:
        logger.warning(f'RSA key load failed: {e}')
        return None


def _sign_request(method: str, path: str, body: str = '') -> dict:
    import time as _time, base64
    from Crypto.Signature import pkcs1_15
    from Crypto.Hash import SHA256
    key = _load_rsa_key()
    if key is None:
        return {'KALSHI_API_KEY': KALSHI_KEY_ID} if KALSHI_KEY_ID else {}
    ts = str(int(_time.time() * 1000))
    msg = ts + method + path + body
    h = SHA256.new(msg.encode())
    signature = pkcs1_15.new(key).sign(h)
    sig_b64 = base64.b64encode(signature).decode()
    return {
        'KALSHI_API_KEY': KALSHI_KEY_ID,
        'KALSHI_TIMESTAMP': ts,
        'KALSHI_SIGNATURE': sig_b64,
    }


class KalshiFeed:
    """Feed de precios BTC de Kalshi para arbitraje."""

    def __init__(self):
        self._cache: dict = {}
        self._cache_time: float = 0
        self._cache_ttl = 30

    def _headers(self, method='GET', path='', body=''):
        return _sign_request(method, path, body)

    def _cached(self, key):
        now = time.time()
        if (now - self._cache_time) < self._cache_ttl and key in self._cache:
            return self._cache[key]
        return None

    def _set_cache(self, key, data):
        self._cache[key] = data
        self._cache_time = time.time()

    def _fetch_all_btc_markets(self) -> list[dict]:
        """Pagina todos los mercados abiertos y extrae solo los de BTC."""
        cached = self._cached('all_btc')
        if cached is not None:
            return cached

        btc_markets = []
        cursor = None
        path = '/trade-api/v2/markets'

        for _ in range(6):  # max 6 pages × 500 = 3000 markets
            params = {'limit': 500, 'status': 'open'}
            if cursor:
                params['cursor'] = cursor
            try:
                resp = requests.get(f'{KALSHI_API_BASE}/markets', params=params,
                                    headers=self._headers('GET', path), timeout=15)
                if resp.status_code == 429:
                    time.sleep(2)
                    continue
                if resp.status_code != 200:
                    break
                data = resp.json()
                markets = data.get('markets', [])
                for m in markets:
                    if self._is_btc_market(m):
                        btc_markets.append(m)
                cursor = data.get('cursor')
                if not cursor or len(markets) < 500:
                    break
            except Exception as e:
                logger.debug(f'Kalshi page error: {e}')
                break

        logger.info(f'Kalshi: {len(btc_markets)} BTC markets found out of ~{(len(btc_markets) * 10)} total')
        self._set_cache('all_btc', btc_markets)
        return btc_markets

    def _is_btc_market(self, market: dict) -> bool:
        """Determina si un mercado de Kalshi es de BTC."""
        title = market.get('title', '')
        if 'Target Price' not in title:
            return False
        # Extraer todos los precios del título
        prices = re.findall(r'\$([\d,]+\.?\d*)', title)
        for p in prices:
            try:
                val = float(p.replace(',', ''))
                if 10000 < val < 500000:  # BTC price range
                    return True
            except ValueError:
                pass
        return False

    def _extract_btc_prices(self, market: dict) -> Optional[dict]:
        """Extrae precios YES/NO de un mercado BTC multi-game.

        Kalshi estructura: "yes Target Price: $78,706.68, no Target Price: $88.04, ..."
        Cada segmento "yes/no Target Price: $X" es un contrato independiente.
        El precio en dólares determina si es BTC o no.
        """
        title = market.get('title', '')
        ticker = market.get('ticker', '')

        yes_price = None
        no_price = None
        yes_target = None
        no_target = None

        # Parsear el título: segmentos separados por coma
        segments = title.split(',')
        for seg in segments:
            seg = seg.strip()
            prices_in_seg = re.findall(r'\$([\d,]+\.?\d*)', seg)
            if not prices_in_seg:
                continue
            try:
                val = float(prices_in_seg[0].replace(',', ''))
                if 10000 < val < 500000:  # BTC range
                    if seg.startswith('yes'):
                        yes_price = self._get_yes_mid(market)
                        yes_target = val
                    elif seg.startswith('no'):
                        no_price = self._get_no_mid(market)
                        no_target = val
            except ValueError:
                continue

        if yes_price is None:
            # Try sub_title for "above" style
            sub = market.get('sub_title', '')
            above_match = re.search(r'(\d[\d,]+)', sub)
            if above_match:
                try:
                    yes_target = float(above_match.group(1).replace(',', ''))
                except ValueError:
                    pass
            # Try yes_bid/ask directly (Kalshi provides these per-market)
            yes_price = self._get_yes_mid(market)

        if no_price is None:
            no_price = self._get_no_mid(market)

        if yes_price is None or no_price is None:
            return None
        if yes_price <= 0 or no_price <= 0:
            return None

        return {
            'yes': round(yes_price, 4),
            'no': round(no_price, 4),
            'yes_target': yes_target,
            'no_target': no_target,
            'yes_ticker': ticker,
            'no_ticker': ticker,
            'market_title': f'BTC ~${yes_target:,.0f}' if yes_target else 'BTC',
        }

    def _get_yes_mid(self, market: dict) -> Optional[float]:
        """Mid price para YES a partir de bid/ask."""
        yes_bid = float(market.get('yes_bid', 0) or 0)
        yes_ask = float(market.get('yes_ask', 0) or 0)
        if yes_ask > 0:
            return (yes_bid + yes_ask) / 2 / 100
        return None

    def _get_no_mid(self, market: dict) -> Optional[float]:
        """Mid price para NO a partir de bid/ask."""
        no_bid = float(market.get('no_bid', 0) or 0)
        no_ask = float(market.get('no_ask', 0) or 0)
        if no_ask > 0:
            return (no_bid + no_ask) / 2 / 100
        return None

    def get_btc_hourly_prices(self, target_hour_utc: int) -> Optional[dict]:
        """Busca mercados BTC para la hora objetivo.

        Como Kalshi no expone la hora en el ticker, tomamos el mercado BTC
        más cercano al precio spot actual (el target más próximo a BTC real).
        """
        cache_key = f'btc_hour_{target_hour_utc}'
        cached = self._cached(cache_key)
        if cached is not None:
            return cached

        all_btc = self._fetch_all_btc_markets()
        if not all_btc:
            return None

        # Obtener precio BTC actual para seleccionar el strike más cercano
        btc_spot = self._get_btc_spot()
        best = None
        best_distance = 999999

        for m in all_btc:
            prices = self._extract_btc_prices(m)
            if prices is None:
                continue
            target = prices.get('yes_target') or prices.get('no_target')
            if target is None:
                continue
            dist = abs(target - btc_spot) if btc_spot > 0 else abs(target - 80000)
            if dist < best_distance:
                best_distance = dist
                best = prices

        if best:
            self._set_cache(cache_key, best)
            logger.info(f'Kalshi BTC: yes={best["yes"]:.4f} no={best["no"]:.4f} target={best.get("yes_target","?")}')
            return best

        return None

    def _get_btc_spot(self) -> float:
        """Obtiene precio spot de BTC desde Kalshi o fallback."""
        try:
            # Kalshi might have an index price endpoint
            resp = requests.get(f'{KALSHI_API_BASE}/index/BTCUSD/price',
                                headers=self._headers('GET', '/trade-api/v2/index/BTCUSD/price'),
                                timeout=5)
            if resp.status_code == 200:
                return float(resp.json().get('price', 0))
        except Exception:
            pass
        # Fallback: use a recent known price
        return 81000.0

    def get_prices_for_arbitrage(self, current_hour_utc: int) -> Optional[dict]:
        """Obtiene precios para arbitraje de la hora actual."""
        return self.get_btc_hourly_prices(current_hour_utc)

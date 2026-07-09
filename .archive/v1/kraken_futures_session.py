"""
Kraken Futures Session — Autenticación y sesión para Kraken Futures API.

Kraken Futures usa endpoint distinto al spot: futures.kraken.com
Auth: API Key + nonce + HMAC-SHA256 (mismo esquema que spot).
"""
import os
import time
import hmac
import hashlib
import base64
from urllib.parse import urlencode
from typing import Optional

import requests


KRAKEN_FUTURES_URL = "https://futures.kraken.com"
KRAKEN_FUTURES_DEMO_URL = "https://demo-futures.kraken.com"


class KrakenFuturesSession:
    """Sesión autenticada para Kraken Futures API (paper o live)."""

    def __init__(self, paper: bool = True):
        self.paper = paper
        self.base_url = KRAKEN_FUTURES_DEMO_URL if paper else KRAKEN_FUTURES_URL
        self.api_key = os.getenv('KRAKEN_API_KEY', '')
        self.api_secret = os.getenv('KRAKEN_SECRET', '')
        self._session = requests.Session()
        self._session.headers.update({'Accept': 'application/json'})

    def _sign(self, endpoint: str, data: dict = None) -> dict:
        """Genera firma HMAC-SHA256 para Kraken Futures."""
        nonce = str(int(time.time() * 1000))
        post_data = nonce + endpoint
        if data:
            post_data += urlencode(data)

        signature = hmac.new(
            base64.b64decode(self.api_secret),
            post_data.encode(),
            hashlib.sha256,
        ).digest()
        signed = base64.b64encode(signature).decode()

        return {
            'APIKey': self.api_key,
            'Authent': signed,
            'Nonce': nonce,
        }

    def _request(self, method: str, endpoint: str, params: dict = None, data: dict = None) -> dict:
        """Request autenticado a Kraken Futures."""
        url = f"{self.base_url}{endpoint}"
        headers = self._sign(endpoint, data if method == 'POST' else None)

        try:
            if method == 'GET':
                resp = self._session.get(url, headers=headers, params=params, timeout=15)
            elif method == 'POST':
                headers['Content-Type'] = 'application/x-www-form-urlencoded'
                resp = self._session.post(url, headers=headers, data=data, timeout=15)
            else:
                raise ValueError(f"Unsupported method: {method}")

            if resp.status_code == 200:
                return resp.json()
            return {'error': resp.text, 'status_code': resp.status_code}
        except Exception as e:
            return {'error': str(e)}

    def get_funding_rate(self, symbol: str = "PF_XBTUSD") -> Optional[float]:
        """Obtiene el funding rate actual para un contrato de futuros.

        Args:
            symbol: Símbolo del contrato (PF_XBTUSD, PF_ETHUSD)

        Returns:
            Funding rate actual (decimal) o None si error.
        """
        result = self._request('GET', f'/derivatives/api/v4/tickers')
        if 'error' in result:
            return None

        tickers = result.get('tickers', [])
        for ticker in tickers:
            if ticker.get('symbol') == symbol:
                fr = ticker.get('fundingRate')
                if fr is not None:
                    return float(fr)
        return None

    def get_funding_rate_history(self, symbol: str = "PF_XBTUSD") -> list:
        """Obtiene historial de funding rates de un contrato."""
        result = self._request('GET', f'/derivatives/api/v4/history', params={'symbol': symbol})
        if 'error' in result:
            return []
        history = result.get('history', [])
        return [
            {'timestamp': h.get('timestamp'), 'funding_rate': float(h.get('fundingRate', 0))}
            for h in history if h.get('fundingRate')
        ]

    def get_contracts(self) -> list:
        """Lista contratos futuros disponibles con sus parámetros."""
        result = self._request('GET', '/derivatives/api/v4/instruments')
        if 'error' in result:
            return []
        instruments = result.get('instruments', [])
        return [
            {
                'symbol': i.get('symbol'),
                'type': i.get('type'),
                'contract_size': float(i.get('contractSize', 0)),
                'tick_size': float(i.get('tickSize', 0)),
                'last_trading_time': i.get('lastTradingTime'),
            }
            for i in instruments if i.get('tradeable')
        ]

    def get_open_positions(self) -> list:
        """Obtiene posiciones abiertas en Kraken Futures."""
        result = self._request('GET', '/derivatives/api/v4/openpositions')
        if 'error' in result:
            return []
        positions = result.get('openPositions', [])
        return [
            {
                'symbol': p.get('symbol'),
                'side': p.get('side'),
                'size': float(p.get('size', 0)),
                'avg_entry': float(p.get('price', 0)),
                'mark_price': float(p.get('markPrice', 0)),
                'pnl': float(p.get('upl', 0)),
            }
            for p in positions
        ]

    def place_order(self, symbol: str, side: str, size: float,
                    order_type: str = 'market', limit_price: float = None) -> dict:
        """Coloca orden en Kraken Futures. PAPER TRADING — siempre simulado."""
        if not self.paper:
            return {'error': 'Live trading not enabled. Set paper=True.'}
        return {
            'result': 'success',
            'order_id': f'paper_{int(time.time())}',
            'symbol': symbol,
            'side': side,
            'size': size,
            'type': order_type,
            'status': 'filled',
            'note': 'PAPER TRADING — no real order sent to Kraken Futures',
        }

    def get_account_balance(self) -> dict:
        """Obtiene balance de la cuenta Futures."""
        if self.paper:
            return {'portfolio_value': 0.0, 'available': 0.0, 'note': 'paper'}
        result = self._request('GET', '/derivatives/api/v4/accounts')
        if 'error' in result:
            return {'error': result['error']}
        accounts = result.get('accounts', {})
        cash = accounts.get('cash', {})
        return {
            'portfolio_value': float(cash.get('portfolioValue', 0)),
            'available': float(cash.get('available', 0)),
        }

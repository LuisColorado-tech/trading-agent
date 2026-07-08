"""
fear_greed_feed.py — Fear & Greed Index data source.

Basada en el repo aulekator/Polymarket-BTC-15-Minute-Trading-Bot (168★).

API: https://api.alternative.me/fng/?limit=1
Cache: 1 hora (el índice se actualiza una vez al día)

Valores:
  0-24:  Extreme Fear
  25-49: Fear
  50:    Neutral
  51-74: Greed
  75-100: Extreme Greed
"""
import sys
import time

import requests
from loguru import logger

sys.path.insert(0, '/opt/trading')

_FEAR_GREED_URL = 'https://api.alternative.me/fng/?limit=1&format=json'
_CACHE_TTL = 3600  # 1 hora en segundos

_cache: dict = {'value': None, 'timestamp': 0, 'classification': None}


def get_fear_greed() -> dict:
    """Obtiene el Fear & Greed Index actual.

    Returns:
        dict con:
            value (int): 0-100
            classification (str): 'Extreme Fear', 'Fear', 'Neutral', 'Greed', 'Extreme Greed'
            cached (bool): True si se usó el cache
    """
    now = time.time()

    # Retornar cache si es válido
    if _cache['value'] is not None and (now - _cache['timestamp']) < _CACHE_TTL:
        return {
            'value': _cache['value'],
            'classification': _cache['classification'],
            'cached': True,
        }

    try:
        resp = requests.get(_FEAR_GREED_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if data and 'data' in data and data['data']:
            entry = data['data'][0]
            value = int(entry.get('value', 50))
            classification = entry.get('value_classification', 'Neutral')

            _cache['value'] = value
            _cache['classification'] = classification
            _cache['timestamp'] = now

            logger.debug(f'FEAR_GREED: {value} ({classification})')
            return {
                'value': value,
                'classification': classification,
                'cached': False,
            }
    except Exception as e:
        logger.warning(f'FEAR_GREED: Error fetching index: {e}')

    # Fallback: retornar cache expirado si existe, sino neutral
    if _cache['value'] is not None:
        return {
            'value': _cache['value'],
            'classification': _cache['classification'],
            'cached': True,
            'stale': True,
        }

    return {'value': 50, 'classification': 'Neutral', 'cached': False, 'error': True}


def get_bias(fear_greed_value: int) -> str:
    """Traduce el valor F&G a un sesgo de mercado.

    Returns:
        'BEARISH_STRONG' | 'BEARISH' | 'NEUTRAL' | 'BULLISH' | 'BULLISH_STRONG'
    """
    if fear_greed_value <= 20:
        return 'BEARISH_STRONG'   # Extreme Fear → comprar dips (contrarian)
    elif fear_greed_value <= 40:
        return 'BEARISH'
    elif fear_greed_value <= 60:
        return 'NEUTRAL'
    elif fear_greed_value <= 80:
        return 'BULLISH'
    else:
        return 'BULLISH_STRONG'   # Extreme Greed → cuidado con tops


def get_edge_multiplier(fear_greed_value: int, btc_direction: str) -> float:
    """Calcula el multiplicador de edge basado en F&G y dirección BTC.

    Lógica contrarian:
    - Extreme Fear + BTC DOWN: multiplica el edge por 1.2 (más convicción en el rebote)
    - Extreme Greed + BTC UP: multiplica el edge por 1.2 (más convicción en la caída)
    - Extremos contra la tendencia: 0.8 (reducir exposición)
    - Neutral: 1.0 (sin cambio)

    Args:
        fear_greed_value: 0-100
        btc_direction: 'UP' o 'DOWN'

    Returns:
        float multiplicador (0.8 - 1.2)
    """
    bias = get_bias(fear_greed_value)

    if bias == 'BEARISH_STRONG' and btc_direction == 'DOWN':
        # Extreme Fear + bajada: señal potencialmente exagerada, el rebote puede venir
        return 1.2
    elif bias == 'BULLISH_STRONG' and btc_direction == 'UP':
        # Extreme Greed + subida: el mercado puede estar sobreextendido
        return 1.2
    elif bias in ('BEARISH_STRONG', 'BULLISH_STRONG'):
        # Extremo pero dirección opuesta: no amplificar
        return 0.9
    elif bias == 'NEUTRAL':
        return 1.0
    else:
        return 1.05  # Leve sesgo en zonas intermedias

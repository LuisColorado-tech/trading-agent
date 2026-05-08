"""
poly_value_zone.py — Value Zone Entry Strategy para Polymarket.

Tesis (respaldada por backtest de 144 trades, Abril 2026):

  Los mercados de predicción binarios en la "zona de incertidumbre"
  (YES entre $0.42 y $0.58) tienden a resolverse favorablemente cuando
  son mercados direccionales de crypto con alta liquidez.

  Datos que respaldan la tesis:
    - Zona $0.45-$0.60: 14 trades, 50% WR, EV +$1.79/trade
    - Direccionales only: 12 trades, 58% WR, EV +$3.53/trade
    - Excluyendo "between" markets: 0 RESOLVED_LOSS en zona value
    - Todos los winners salieron por TAKE_PROFIT a ~$0.85

  La estrategia NO analiza señales técnicas. Simplemente compra YES
  cuando el mercado está en la zona de incertidumbre con suficiente
  liquidez y tiempo. El TP/SL lo maneja poly_monitor.py.

Parámetros (desde exchange_config.yaml → polymarket.strategies.value_zone):
  min_volume:      30000   # USD volumen mínimo
  min_liquidity:   5000    # USD liquidez mínima
  min_days_left:   1       # Días mínimos hasta expiración
  max_days_left:   7       # Días máximos hasta expiración
  exclude_between: true    # Excluir mercados "between X and Y"
  exclude_compounds: true  # Excluir preguntas con "and" / multi-condición
"""
import re
import sys
from datetime import datetime, timezone, timedelta

import yaml
from loguru import logger

sys.path.insert(0, '/opt/trading')

with open('/opt/trading/config/exchange_config.yaml') as f:
    _POLY_CFG = yaml.safe_load(f).get('polymarket', {})

NAME = 'value_zone'

_STRAT_CFG = _POLY_CFG.get('strategies', {}).get('value_zone', {})
_RISK_CFG  = _POLY_CFG.get('risk', {})

MIN_VOLUME      = _STRAT_CFG.get('min_volume', 30000)
MIN_LIQUIDITY   = _STRAT_CFG.get('min_liquidity', 5000)
MIN_DAYS_LEFT   = _STRAT_CFG.get('min_days_left', 1)
MAX_DAYS_LEFT   = _STRAT_CFG.get('max_days_left', 7)
EXCLUDE_BETWEEN = _STRAT_CFG.get('exclude_between', True)
EXCLUDE_COMPOUNDS = _STRAT_CFG.get('exclude_compounds', True)
MIN_EDGE_PCT    = _RISK_CFG.get('min_edge_pct', 10.0)
TP_PRICE        = _RISK_CFG.get('early_exit_profit', 0.85)

# Keywords que identifican mercados direccionales válidos
_DIRECTIONAL_UP_PATTERNS = [
    r'\b(above|over|reach|hit|break|cross|exceed|surpass|top)\b',
    r'\b(up to|go up|rise|climb)\b',
]
_DIRECTIONAL_DOWN_PATTERNS = [
    r'\b(below|under|dip|drop|fall|crash|sink|plummet)\b',
    r'\b(go down|decline)\b',
]
_EXCLUDE_PATTERNS = [
    r'\bbetween\b',         # "between X and Y"
    r'\band\b.*\band\b',    # "X and Y and Z" (multi-condición)
    r'\bin\s+the\s+range\b',
    r'\bwithin\b',
    r'\bclose\b.*\bprice\b',  # "closing price" → no es nuestro edge
]


def _is_directional(question: str) -> bool:
    """Verifica si la pregunta es direccional (arriba/abajo) y no compuesta."""
    q = question.lower()

    if EXCLUDE_BETWEEN:
        for pat in _EXCLUDE_PATTERNS:
            if re.search(pat, q):
                return False

    if EXCLUDE_COMPOUNDS:
        # Multi-condición: "if BTC above X AND ETH above Y"
        if q.count(' and ') >= 1:
            return False

    # Debe coincidir con al menos un patrón direccional
    is_up = any(re.search(p, q) for p in _DIRECTIONAL_UP_PATTERNS)
    is_down = any(re.search(p, q) for p in _DIRECTIONAL_DOWN_PATTERNS)
    return is_up or is_down


def _days_until(end_date) -> float:
    """Calcula días hasta expiración del mercado."""
    now = datetime.now(timezone.utc)
    if isinstance(end_date, str):
        try:
            end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return -1
    if not end_date.tzinfo:
        end_date = end_date.replace(tzinfo=timezone.utc)
    return (end_date - now).total_seconds() / 86400


class ValueZonePolyStrategy:
    """Compra YES en la zona de incertidumbre del mercado.

    No analiza señales. Confía en que la zona $0.42-$0.58 en mercados
    direccionales de crypto ofrece edge positivo por reversión a la media
    del precio. TP fijo en 0.85, SL en 25% del capital (poly_monitor).
    """

    NAME = NAME

    def __init__(self):
        self._min_volume = MIN_VOLUME
        self._min_liquidity = MIN_LIQUIDITY
        logger.info(
            f'VALUE_ZONE inicializada | '
            f'edge_min={MIN_EDGE_PCT}% | TP={TP_PRICE} | '
            f'volume≥${MIN_VOLUME} | days={MIN_DAYS_LEFT}-{MAX_DAYS_LEFT}'
        )

    def evaluate(self, market: dict, **kwargs) -> dict:
        """Evalúa si el mercado es candidato para Value Zone entry.

        Args:
            market: dict con question, price_yes, price_no, volume,
                    liquidity, end_date, condition_id, etc.

        Returns:
            dict con opportunity: True/False y campos del signal.
        """
        question     = market.get('question', '')
        price_yes    = float(market.get('price_yes', 0))
        price_no     = float(market.get('price_no', 0))
        volume       = float(market.get('volume', 0))
        liquidity    = float(market.get('liquidity', 0))
        end_date     = market.get('end_date')
        condition_id = market.get('condition_id', '')

        # ── Filtro 1: Mercado direccional ──
        if not _is_directional(question):
            return {'opportunity': False, 'reason': 'NON_DIRECTIONAL'}

        # ── Filtro 2: Tiempo hasta expiración ──
        days_left = _days_until(end_date)
        if days_left < MIN_DAYS_LEFT:
            return {
                'opportunity': False,
                'reason': f'TOO_SOON:{days_left:.1f}d<{MIN_DAYS_LEFT}d',
            }
        if days_left > MAX_DAYS_LEFT:
            return {
                'opportunity': False,
                'reason': f'TOO_FAR:{days_left:.1f}d>{MAX_DAYS_LEFT}d',
            }

        # ── Filtro 3: Volumen y liquidez ──
        if volume < self._min_volume:
            return {
                'opportunity': False,
                'reason': f'LOW_VOLUME:{volume:.0f}<{self._min_volume}',
            }
        if liquidity < self._min_liquidity:
            return {
                'opportunity': False,
                'reason': f'LOW_LIQ:{liquidity:.0f}<{self._min_liquidity}',
            }

        # ── Filtro 4: Edge mínimo ──
        # Edge = (TP_price - entry_price) / entry_price → % de ganancia si llega al TP
        edge_pct = (TP_PRICE - price_yes) / price_yes * 100
        if edge_pct < MIN_EDGE_PCT:
            return {
                'opportunity': False,
                'reason': f'EDGE_TOO_LOW:{edge_pct:.1f}%<{MIN_EDGE_PCT}%',
            }

        # ── Señal de entrada ──
        edge     = TP_PRICE - price_yes  # profit absoluto por share si llega a TP
        prob_est = min(0.90, price_yes + edge * 0.5)

        reasoning = (
            f'VALUE_ZONE | YES @ {price_yes:.3f} | '
            f'Volume=${volume:,.0f} | {days_left:.1f}d left | '
            f'Edge to TP({TP_PRICE}): +{edge_pct:.1f}%'
        )

        logger.info(
            f'SIGNAL_POLY VALUE_ZONE: {reasoning} | '
            f'"{question[:80]}"'
        )

        return {
            'opportunity': True,
            'side': 'YES',
            'edge': round(edge, 4),
            'entry_price': price_yes,
            'estimated_prob': prob_est,
            'confidence': 65,
            'reasoning': reasoning,
            'market': market,
            'strategy': NAME,
            'strategy_tag': 'VALUE_ZONE',
        }

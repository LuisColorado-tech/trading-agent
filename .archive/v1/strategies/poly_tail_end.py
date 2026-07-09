"""
poly_tail_end.py — Tail-End Trading Strategy para Polymarket.

Basada en el repo Anmoldureha/polymarket-trading-bot-strategies (24★).

Estrategia: comprar outcomes casi-ciertos (≥0.93) que están próximos a expirar
(≤7 días). El mercado paga $1.00 en resolución → retorno 2-7% por trade.

Ideal para: yield farming de bajo riesgo en mercados near-resolution.
"""
import sys
from datetime import datetime, timezone

import yaml
from loguru import logger

sys.path.insert(0, '/opt/trading')

with open('/opt/trading/config/exchange_config.yaml') as f:
    _POLY_CFG = yaml.safe_load(f).get('polymarket', {})

NAME = 'tail_end'

_STRAT_CFG = _POLY_CFG.get('strategies', {}).get('tail_end', {})

# Precio mínimo para considerar el outcome como "casi cierto"
MIN_PRICE = _STRAT_CFG.get('min_price', 0.93)
# Precio máximo (si ya es 0.99+ no hay suficiente retorno)
MAX_PRICE = _STRAT_CFG.get('max_price', 0.985)
# Días máximos hasta expiración
MAX_END_DAYS = _STRAT_CFG.get('max_end_days', 7)
# Horas mínimas hasta expiración (evitar mercados que ya resolvieron)
MIN_END_HOURS = _STRAT_CFG.get('min_end_hours', 1)
# Retorno mínimo esperado en porcentaje: (1 - entry_price) / entry_price
MIN_RETURN_PCT = _STRAT_CFG.get('min_return_pct', 2.0)
# Stop-loss: si el precio cae por debajo de este nivel, salir
STOP_LOSS_PRICE = _STRAT_CFG.get('stop_loss_price', 0.88)


class TailEndPolyStrategy:
    """
    Tail-End Trading: comprar outcomes near-resolution con alta probabilidad.

    Lógica:
    - Si price_yes ≥ MIN_PRICE → comprar YES (paga $1 en resolución)
    - Si price_no ≥ MIN_PRICE → comprar NO (paga $1 en resolución)
    - Retorno esperado: (1.00 - entry_price) / entry_price %
    - Stop-loss en poly_monitor.py si precio cae < STOP_LOSS_PRICE
    """

    NAME = NAME

    def evaluate(self, market: dict, **kwargs) -> dict:
        """Evalúa si el mercado es candidato para Tail-End trading.

        Args:
            market: dict con condition_id, question, price_yes, price_no, end_date

        Returns:
            dict con opportunity: True/False y campos del signal.
        """
        question = market.get('question', '')
        price_yes = float(market.get('price_yes', 0))
        price_no = float(market.get('price_no', 0))
        end_date = market.get('end_date')

        # Calcular tiempo hasta expiración
        if end_date is None:
            return {'opportunity': False, 'reason': 'NO_END_DATE'}

        now = datetime.now(timezone.utc)
        if isinstance(end_date, str):
            try:
                end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            except ValueError:
                return {'opportunity': False, 'reason': 'INVALID_END_DATE'}

        # Asegurar timezone
        if not end_date.tzinfo:
            end_date = end_date.replace(tzinfo=timezone.utc)

        hours_left = (end_date - now).total_seconds() / 3600
        days_left = hours_left / 24

        # Filtro de tiempo
        if hours_left < MIN_END_HOURS:
            return {'opportunity': False, 'reason': f'TOO_SOON:{hours_left:.1f}h'}
        if days_left > MAX_END_DAYS:
            return {'opportunity': False, 'reason': f'TOO_FAR:{days_left:.1f}d'}

        # Determinar si algún lado es "casi cierto"
        side = None
        entry_price = None

        if MIN_PRICE <= price_yes <= MAX_PRICE:
            side = 'YES'
            entry_price = price_yes
        elif MIN_PRICE <= price_no <= MAX_PRICE:
            side = 'NO'
            entry_price = price_no

        if side is None:
            return {'opportunity': False, 'reason': f'PRICE_NOT_IN_RANGE:YES={price_yes:.3f},NO={price_no:.3f}'}

        # Calcular retorno esperado
        expected_return_pct = (1.0 - entry_price) / entry_price * 100
        if expected_return_pct < MIN_RETURN_PCT:
            return {'opportunity': False, 'reason': f'LOW_RETURN:{expected_return_pct:.2f}%'}

        # Edge: distancia desde 0.5 hasta el precio de entrada
        edge = abs(entry_price - 0.50)

        # Probabilidad estimada = precio de entrada (mercado ya lo descuenta)
        estimated_prob = min(0.98, entry_price + 0.02)

        reasoning = (
            f'TAIL_END | {side} @ {entry_price:.3f} | '
            f'{days_left:.1f}d left | Return: {expected_return_pct:.1f}% | '
            f'Edge: {edge:.3f}'
        )
        logger.info(f'SIGNAL_POLY TAIL_END: {reasoning} | "{question[:60]}"')

        return {
            'opportunity': True,
            'side': side,
            'edge': edge,
            'entry_price': entry_price,
            'estimated_prob': estimated_prob,
            'confidence': 85,
            'reasoning': reasoning,
            'expected_return_pct': round(expected_return_pct, 2),
            'days_left': round(days_left, 2),
            'market': market,
            'strategy': NAME,
        }

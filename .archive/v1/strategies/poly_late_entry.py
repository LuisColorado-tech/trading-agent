"""
poly_late_entry.py — Late Entry V3 Strategy para Polymarket.

Ingeniería inversa de txbabaxyz/4coinsbot (87★).

Estrategia: entrar en los ÚLTIMOS 4 MINUTOS antes del cierre de mercados
15-min de crypto (BTC, ETH, SOL, XRP). Comprar el lado favorito (el que
tiene precio más alto = consenso del mercado).

Lógica del favorito: en un mercado binario, el lado que más gente compra
sube de precio. Si YES > NO, el mercado cree que el evento va a ocurrir.
El bot entra con el consenso + confianza mínima de 30%.

Ideal para: mercados 15-min con alta actividad antes del cierre.
"""
import sys
import time
from datetime import datetime, timezone

import yaml
from loguru import logger

sys.path.insert(0, '/opt/trading')

with open('/opt/trading/config/exchange_config.yaml') as f:
    _POLY_CFG = yaml.safe_load(f).get('polymarket', {})

NAME = 'late_entry'

_STRAT_CFG = _POLY_CFG.get('strategies', {}).get('late_entry', {})

# Ventana de entrada: últimos N segundos antes del cierre
ENTRY_WINDOW_SEC = _STRAT_CFG.get('entry_window_sec', 240)  # 4 minutos
# Frecuencia mínima entre entradas al mismo mercado (evita dobles)
ENTRY_FREQ_SEC = _STRAT_CFG.get('entry_frequency_sec', 7)
# Confianza mínima: diferencia absoluta entre YES y NO
MIN_CONFIDENCE = _STRAT_CFG.get('min_confidence', 0.30)
# Precio máximo del favorito (evitar mercados casi resueltos)
PRICE_MAX = _STRAT_CFG.get('price_max', 0.92)
# Spread máximo (YES + NO no debe superar 1.05 por slippage)
MAX_SPREAD = _STRAT_CFG.get('max_spread', 1.05)
# Flip-stop: si el lado que compramos cae por debajo de esto → salida
FLIP_STOP = _STRAT_CFG.get('flip_stop_threshold', 0.48)


class LateEntryPolyStrategy:
    """
    Late Entry V3: entrar en los últimos minutos de mercados 15-min.

    Detecta el lado favorito (mayor ask = consenso del mercado) y
    entra si la confianza es suficiente.
    """

    NAME = NAME

    def __init__(self):
        # Tracking de última entrada por mercado (evitar dobles rápidos)
        self._last_entry: dict[str, float] = {}

    def evaluate(self, market: dict, **kwargs) -> dict:
        """Evalúa si el mercado es candidato para Late Entry.

        Args:
            market: dict con condition_id, question, price_yes, price_no, end_date

        Returns:
            dict con opportunity: True/False y campos del signal.
        """
        question = market.get('question', '')
        condition_id = market.get('condition_id', '')
        price_yes = float(market.get('price_yes', 0))
        price_no = float(market.get('price_no', 0))
        end_date = market.get('end_date')

        # Calcular segundos hasta expiración
        if end_date is None:
            return {'opportunity': False, 'reason': 'NO_END_DATE'}

        now = datetime.now(timezone.utc)
        if isinstance(end_date, str):
            try:
                end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            except ValueError:
                return {'opportunity': False, 'reason': 'INVALID_END_DATE'}

        if not end_date.tzinfo:
            end_date = end_date.replace(tzinfo=timezone.utc)

        seconds_left = (end_date - now).total_seconds()

        # Solo en los últimos N segundos
        if seconds_left <= 0:
            return {'opportunity': False, 'reason': 'MARKET_CLOSED'}
        if seconds_left > ENTRY_WINDOW_SEC:
            return {'opportunity': False, 'reason': f'TOO_EARLY:{seconds_left:.0f}s'}

        # Control de frecuencia por mercado
        now_ts = time.time()
        if condition_id in self._last_entry:
            elapsed = now_ts - self._last_entry[condition_id]
            if elapsed < ENTRY_FREQ_SEC:
                return {'opportunity': False, 'reason': f'FREQ_LIMIT:{elapsed:.1f}s'}

        # Filtro de spread (suma YES+NO no debe ser > 1.05)
        spread = price_yes + price_no
        if spread > MAX_SPREAD or spread <= 0:
            return {'opportunity': False, 'reason': f'BAD_SPREAD:{spread:.3f}'}

        # Confianza: diferencia entre ambos lados
        confidence = abs(price_yes - price_no)
        if confidence < MIN_CONFIDENCE:
            return {'opportunity': False, 'reason': f'LOW_CONFIDENCE:{confidence:.3f}'}

        # Favorito: el lado con precio más alto = consenso del mercado
        if price_yes >= price_no:
            side = 'YES'
            entry_price = price_yes
        else:
            side = 'NO'
            entry_price = price_no

        # Precio máximo del favorito
        if entry_price > PRICE_MAX:
            return {'opportunity': False, 'reason': f'PRICE_MAX:{entry_price:.3f}'}

        # Registrar entrada
        self._last_entry[condition_id] = now_ts

        # Edge basado en la confianza del mercado
        edge = confidence / 2  # mitad de la diferencia como medida de edge

        # Probabilidad estimada: el mercado ya la descuenta en el precio
        estimated_prob = min(0.92, entry_price + 0.03)

        # Sizing hint basado en tiempo restante (del repo 4coinsbot)
        if seconds_left > 180:
            time_bucket = 'early'    # ~8 contratos
        elif seconds_left > 120:
            time_bucket = 'mid'      # ~10 contratos
        else:
            time_bucket = 'late'     # ~12 contratos (máxima convicción)

        reasoning = (
            f'LATE_ENTRY_{time_bucket.upper()} | {side} @ {entry_price:.3f} | '
            f'Confidence: {confidence:.3f} | {seconds_left:.0f}s left | '
            f'Spread: {spread:.3f}'
        )
        logger.info(f'SIGNAL_POLY LATE_ENTRY: {reasoning} | "{question[:60]}"')

        return {
            'opportunity': True,
            'side': side,
            'edge': edge,
            'entry_price': entry_price,
            'estimated_prob': estimated_prob,
            'confidence': int(confidence * 100),
            'reasoning': reasoning,
            'seconds_left': int(seconds_left),
            'time_bucket': time_bucket,
            'flip_stop': FLIP_STOP,
            'market': market,
            'strategy': NAME,
        }

    def reset_market(self, condition_id: str):
        """Limpia el tracking de frecuencia para un mercado."""
        self._last_entry.pop(condition_id, None)

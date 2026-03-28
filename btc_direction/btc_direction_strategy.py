"""
btc_direction_strategy.py — Señal de dirección BTC para mercados 15m de Polymarket.

Señal combinada:
  1. Momentum BTC (5 velas de 1m en Kraken/OKX):
       retorno > +0.15%  →  bias Up
       retorno < -0.15%  →  bias Down
       en medio          →  no operar
  2. Edge de precio en Polymarket:
       si precio_del_outcome < 0.50  →  el mercado subvalora nuestra dirección
       edge = 0.50 - precio_polymarket
       Requerido mínimo: 0.03

Solo se genera señal si ambas condiciones se cumplen.
"""
import sys

import ccxt
from loguru import logger

sys.path.insert(0, '/opt/trading')


class BtcDirectionStrategy:
    """Genera señal de dirección BTC para el mercado 15m de Polymarket."""

    def __init__(self, config: dict):
        self.cfg = config

        btc_cfg = config.get('btc_data', {})
        self.exchange_id = btc_cfg.get('exchange', 'kraken')
        self.pair        = btc_cfg.get('pair', 'BTC/USDT')
        self.timeframe   = btc_cfg.get('timeframe', '1m')
        self.lookback    = btc_cfg.get('lookback_candles', 10)
        self.fallback_id = btc_cfg.get('fallback_exchange', 'okx')

        risk_cfg = config.get('risk', {})
        self.momentum_threshold = risk_cfg.get('momentum_threshold_pct', 0.15) / 100.0
        self.min_edge           = risk_cfg.get('min_price_edge', 0.03)

        self._exchange = None
        self._fallback = None

    # ── Acceso a exchange ────────────────────────────────────────────────────

    def _get_exchange(self) -> ccxt.Exchange:
        if self._exchange is None:
            cls = getattr(ccxt, self.exchange_id)
            self._exchange = cls({'enableRateLimit': True})
        return self._exchange

    def _get_fallback(self) -> ccxt.Exchange:
        if self._fallback is None:
            cls = getattr(ccxt, self.fallback_id)
            self._fallback = cls({'enableRateLimit': True})
        return self._fallback

    def _fetch_closes(self) -> list[float] | None:
        """
        Descarga las últimas `lookback` velas de 1m y retorna los cierres.
        Intenta exchange primario, luego fallback.
        """
        for ex in (self._get_exchange(), self._get_fallback()):
            try:
                candles = ex.fetch_ohlcv(self.pair, self.timeframe, limit=self.lookback)
                if candles and len(candles) >= 5:
                    return [float(c[4]) for c in candles]
            except Exception as e:
                logger.warning(f'STRATEGY: Error OHLCV en {ex.id}: {e}')
        return None

    # ── Evaluación ───────────────────────────────────────────────────────────

    def evaluate(self, market: dict) -> dict:
        """
        Evalúa el mercado del slot actual y devuelve señal de trading.

        Args:
            market: dict devuelto por BtcDirectionFeed.get_current_market()

        Returns:
            dict con:
              direction:   'Up' | 'Down' | None
              confidence:  0.0–1.0
              btc_5m_pct:  retorno % de BTC en últimas 5 velas de 1m
              entry_price: precio Polymarket a pagar
              token_id:    token a comprar en Polymarket
              edge:        ventaja de precio (0.50 - entry_price)
              reasoning:   descripción legible de la lógica
        """
        closes = self._fetch_closes()
        if not closes or len(closes) < 5:
            return self._no_signal('No se pudo obtener OHLCV de BTC')

        # Retorno acumulado de las últimas 5 velas de 1m
        btc_5m_pct = (closes[-1] - closes[-5]) / closes[-5] * 100.0

        price_up   = market['price_up']
        price_down = market['price_down']

        # ── 1. Señal de momentum ──────────────────────────────────────────
        threshold_pct = self.momentum_threshold * 100.0

        if btc_5m_pct > threshold_pct:
            momentum_dir = 'Up'
            # Normalizar fuerza de momentum: 1.0 cuando duplica el umbral
            momentum_strength = min(btc_5m_pct / (threshold_pct * 2.0), 1.0)
        elif btc_5m_pct < -threshold_pct:
            momentum_dir = 'Down'
            momentum_strength = min(abs(btc_5m_pct) / (threshold_pct * 2.0), 1.0)
        else:
            return self._no_signal(
                f'Momentum insuficiente: BTC_5m={btc_5m_pct:+.3f}% '
                f'(umbral ±{threshold_pct:.2f}%)'
            )

        # ── 2. Edge de precio en Polymarket ──────────────────────────────
        entry_price = price_up   if momentum_dir == 'Up'   else price_down
        token_id    = market['token_up'] if momentum_dir == 'Up' else market['token_down']

        # Edge positivo → el mercado aún no ha descontado el movimiento
        edge = 0.50 - entry_price

        if edge < self.min_edge:
            return self._no_signal(
                f'Edge insuficiente: precio={entry_price:.3f} edge={edge:.3f} '
                f'(mínimo {self.min_edge:.3f}) dir={momentum_dir}'
            )

        # ── 3. Confianza combinada (50% momentum + 50% edge) ─────────────
        edge_strength = min(edge / 0.15, 1.0)  # normalizar: 1.0 a 15¢ de edge
        confidence    = round(0.5 * momentum_strength + 0.5 * edge_strength, 3)

        reasoning = (
            f'BTC_5m={btc_5m_pct:+.3f}% ({momentum_dir}) | '
            f'precio_poly={entry_price:.3f} edge={edge:+.3f} | '
            f'btc={closes[-1]:.2f}'
        )

        logger.info(f'STRATEGY: SEÑAL {momentum_dir} conf={confidence:.2f} | {reasoning}')

        return {
            'direction':   momentum_dir,
            'confidence':  confidence,
            'btc_5m_pct':  round(btc_5m_pct, 4),
            'entry_price': entry_price,
            'token_id':    token_id,
            'edge':        round(edge, 4),
            'reasoning':   reasoning,
        }

    @staticmethod
    def _no_signal(reason: str) -> dict:
        logger.debug(f'STRATEGY: No signal — {reason}')
        return {
            'direction':   None,
            'confidence':  0.0,
            'btc_5m_pct':  0.0,
            'entry_price': 0.0,
            'token_id':    '',
            'edge':        0.0,
            'reasoning':   reason,
        }

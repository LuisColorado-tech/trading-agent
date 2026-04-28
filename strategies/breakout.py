"""
BreakoutStrategy — Ruptura de resistencia/soporte con volumen.

v2 (2026-04-28):
  - Añadido _score_sell() para breakdowns bajistas.
    Sin esto la estrategia era BUY-only en un sistema SELL-only → nunca ejecutaba.
  - vol_ratio: 2.0 → 1.5. Con 2.0 nunca disparaba (aprox. 2-3% de las velas 15m).
    El MIN_SCORE=70 ya filtra calidad; el doble filtro era redundante.
  - MIN_SCORE: 75 → 70. El umbral más alto del sistema limitaba señales válidas.
"""
import pandas as pd
from agents.indicators import IndicatorSet
from core.asset_profiles import get_profile


class BreakoutStrategy:
    NAME = 'BREAKOUT'
    MIN_SCORE = 70
    PREFERRED_ASSETS = ['BTC', 'ETH']
    LOOKBACK_CANDLES = 20
    MIN_VOL_RATIO = 1.5  # bajado de 2.0: con 2.0 la estrategia nunca disparaba

    def score(self, ind: IndicatorSet, df: pd.DataFrame = None) -> dict:
        buy = self._score_buy(ind, df)
        sell = self._score_sell(ind, df)

        if sell['score'] >= self.MIN_SCORE and sell['score'] >= buy['score']:
            return sell
        if buy['score'] >= self.MIN_SCORE:
            return buy

        best = sell if sell['score'] >= buy['score'] else buy
        return {'direction': 'NEUTRAL', 'score': best['score'], 'reasons': best['reasons']}

    def _score_buy(self, ind: IndicatorSet, df: pd.DataFrame = None) -> dict:
        score = 0
        reasons = []

        # Volumen: condición primaria y no negociable
        if ind.vol_ratio < self.MIN_VOL_RATIO:
            return {'direction': 'NEUTRAL', 'score': 0, 'reasons': ['INSUFFICIENT_VOLUME']}

        score += 30
        reasons.append(f'STRONG_VOLUME:{ind.vol_ratio:.1f}x')

        # Ruptura de resistencia reciente
        if df is not None and len(df) >= self.LOOKBACK_CANDLES:
            recent_high = df['high'].rolling(self.LOOKBACK_CANDLES).max().iloc[-2]
            if ind.close > recent_high * 1.005:
                score += 40
                reasons.append(f'RESISTANCE_BREAK:{recent_high:.2f}')
            else:
                score -= 10
                reasons.append('NO_RESISTANCE_BREAK')

        # ATR: movimiento inicial significativo
        if ind.atr_pct > 0.015:
            score += 15
            reasons.append('SUFFICIENT_ATR')

        # Tendencia alineada
        if ind.trend_direction == 'UP':
            score += 15
            reasons.append('TREND_ALIGNED')

        if ind.asset in self.PREFERRED_ASSETS:
            score += 10

        profile = get_profile(ind.asset)
        stop = ind.close - (1.0 * ind.atr)
        target = ind.close + (3.0 * ind.atr)
        risk = ind.close - stop

        return {
            'direction': 'BUY',
            'score': max(score, 0),
            'reasons': reasons,
            'stop_loss': stop,
            'take_profit': target,
            'rr_ratio': (target - ind.close) / risk if risk > 0 else 0,
        }

    def _score_sell(self, ind: IndicatorSet, df: pd.DataFrame = None) -> dict:
        """Breakdown bajista de soporte con volumen — simétrico al BUY."""
        score = 0
        reasons = []

        # Volumen: condición primaria y no negociable
        if ind.vol_ratio < self.MIN_VOL_RATIO:
            return {'direction': 'NEUTRAL', 'score': 0, 'reasons': ['INSUFFICIENT_VOLUME']}

        score += 30
        reasons.append(f'STRONG_VOLUME:{ind.vol_ratio:.1f}x')

        # Ruptura de soporte reciente
        if df is not None and len(df) >= self.LOOKBACK_CANDLES:
            recent_low = df['low'].rolling(self.LOOKBACK_CANDLES).min().iloc[-2]
            if ind.close < recent_low * 0.995:
                score += 40
                reasons.append(f'SUPPORT_BREAK:{recent_low:.2f}')
            else:
                score -= 10
                reasons.append('NO_SUPPORT_BREAK')

        # ATR: expansión de volatilidad
        if ind.atr_pct > 0.015:
            score += 15
            reasons.append('SUFFICIENT_ATR')

        # Tendencia alineada bajista
        if ind.trend_direction == 'DOWN':
            score += 15
            reasons.append('TREND_ALIGNED')

        if ind.asset in self.PREFERRED_ASSETS:
            score += 10

        profile = get_profile(ind.asset)
        stop = ind.close + (1.0 * ind.atr)
        target = ind.close - (3.0 * ind.atr)
        risk = stop - ind.close

        return {
            'direction': 'SELL',
            'score': max(score, 0),
            'reasons': reasons,
            'stop_loss': stop,
            'take_profit': target,
            'rr_ratio': (ind.close - target) / risk if risk > 0 else 0,
        }

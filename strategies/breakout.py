"""
BreakoutStrategy — Ruptura de resistencia con volumen.
Requiere volumen >2x como condición primaria no negociable.
SL: 1.0 ATR (ajustado), TP: 3.0 ATR (mayor R:R).
"""
import pandas as pd
from agents.indicators import IndicatorSet


class BreakoutStrategy:
    NAME = 'BREAKOUT'
    MIN_SCORE = 75
    PREFERRED_ASSETS = ['BTC', 'ETH']
    LOOKBACK_CANDLES = 20

    def score(self, ind: IndicatorSet, df: pd.DataFrame = None) -> dict:
        score = 0
        reasons = []

        # Volumen: condición primaria y no negociable
        if ind.vol_ratio < 2.0:
            return {
                'direction': 'NEUTRAL',
                'score': 0,
                'reasons': ['INSUFFICIENT_VOLUME'],
                'rr_ratio': 0,
            }

        score += 30
        reasons.append(f'STRONG_VOLUME:{ind.vol_ratio:.1f}x')

        # Detectar resistencia reciente
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

        # Activo preferido
        if ind.asset in self.PREFERRED_ASSETS:
            score += 10

        # Stop loss ajustado para breakouts
        stop = ind.close - (1.0 * ind.atr)
        target = ind.close + (3.0 * ind.atr)
        risk = ind.close - stop

        if score >= self.MIN_SCORE:
            return {
                'direction': 'BUY',
                'score': score,
                'reasons': reasons,
                'stop_loss': stop,
                'take_profit': target,
                'rr_ratio': (target - ind.close) / risk if risk > 0 else 0,
            }

        return {'direction': 'NEUTRAL', 'score': score, 'reasons': reasons}

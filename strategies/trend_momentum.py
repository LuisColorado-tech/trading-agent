"""
TrendMomentumStrategy — Captura momentum en tendencias establecidas.
Entra cuando EMA alineada + RSI en zona de momentum + volumen confirmado.
SL: 1.5 ATR, TP: 2.5 ATR.
"""
from agents.indicators import IndicatorSet


class TrendMomentumStrategy:
    NAME = 'TREND_MOMENTUM'
    MIN_SCORE = 65

    def score(self, ind: IndicatorSet, df=None) -> dict:
        score = 0
        reasons = []
        direction = None

        # ── SELL conditions (evaluadas primero) ──
        if ind.ema20 < ind.ema50 * 0.995 and ind.rsi < 45:
            return {
                'direction': 'SELL',
                'score': 85,
                'reasons': ['EMA_BEAR_CROSS', f'RSI_WEAK:{ind.rsi:.1f}'],
                'stop_loss': ind.close + (1.5 * ind.atr),
                'take_profit': ind.close - (2.5 * ind.atr),
            }

        # ── BUY conditions ──
        if ind.ema20 > ind.ema50 * 1.005:  # EMA20 > EMA50 + 0.5%
            score += 30
            reasons.append('EMA_BULL_CROSS')

        if ind.close > ind.ema20:
            score += 15
            reasons.append('PRICE_ABOVE_EMA20')

        if 50 <= ind.rsi <= 68:
            score += 25
            reasons.append(f'RSI_MOMENTUM_ZONE:{ind.rsi:.1f}')
        elif ind.rsi > 68:
            score -= 20
            reasons.append('RSI_EXTENDED')

        if ind.vol_ratio > 1.2:
            score += 15
            reasons.append(f'VOL_CONFIRM:{ind.vol_ratio:.2f}x')

        if ind.close < ind.bb_upper * 0.98:
            score += 15
            reasons.append('ROOM_TO_BB_UPPER')

        if score >= self.MIN_SCORE:
            direction = 'BUY'

        if direction == 'BUY':
            return {
                'direction': 'BUY',
                'score': score,
                'reasons': reasons,
                'stop_loss': ind.close - (1.5 * ind.atr),
                'take_profit': ind.close + (2.5 * ind.atr),
            }

        return {'direction': 'NEUTRAL', 'score': score, 'reasons': reasons}

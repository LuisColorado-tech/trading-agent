"""
MeanReversionStrategy — Reversión a la media en extremos de Bollinger.
Compra en oversold extremo con volatilidad controlada.
Target: BB_middle. SL: 1.5 ATR.
"""
from agents.indicators import IndicatorSet


class MeanReversionStrategy:
    NAME = 'MEAN_REVERSION'
    MIN_SCORE = 70
    ENABLED_ASSETS = ['XAU', 'XAG']
    INTERNAL_MIN_RR = 1.8

    def score(self, ind: IndicatorSet, df=None) -> dict:
        score = 0
        reasons = []

        if ind.asset not in self.ENABLED_ASSETS:
            return {'direction': 'NEUTRAL', 'score': 0, 'reasons': ['ASSET_NOT_ENABLED']}

        # Precio en extremo inferior
        if ind.bb_pct < 0.05:
            score += 35
            reasons.append(f'BB_LOWER_EXTREME:{ind.bb_pct:.3f}')
        elif ind.bb_pct < 0.10:
            score += 20
            reasons.append('BB_LOWER_ZONE')

        # RSI sobreventa
        if ind.rsi < 25:
            score += 30
            reasons.append(f'RSI_EXTREME_OVERSOLD:{ind.rsi:.1f}')
        elif ind.rsi < 32:
            score += 20
            reasons.append(f'RSI_OVERSOLD:{ind.rsi:.1f}')

        if ind.trend_direction == 'DOWN':
            return {'direction': 'NEUTRAL', 'score': 0, 'reasons': ['DOWN_REGIME_ABORT']}

        # Verificar que no es tendencia bajista estructural
        ema_drop_pct = (ind.ema50 - ind.ema20) / ind.ema50 if ind.ema50 > 0 else 0
        if ema_drop_pct > 0.015:
            return {'direction': 'NEUTRAL', 'score': 0, 'reasons': ['STRONG_DOWNTREND_ABORT']}

        # Volatilidad controlada
        if ind.bb_width < 0.10:
            score += 15
            reasons.append('LOW_VOLATILITY_FAVORABLE')
        elif ind.bb_width > 0.12:
            return {'direction': 'NEUTRAL', 'score': 0, 'reasons': ['HIGH_VOLATILITY_ABORT']}

        score += 10
        reasons.append(f'ENABLED_ASSET:{ind.asset}')

        # Target de salida: reversión a la media
        target = ind.bb_middle
        reward = target - ind.close
        risk = 1.5 * ind.atr
        rr_ratio = reward / risk if risk > 0 else 0

        if rr_ratio < self.INTERNAL_MIN_RR:
            return {
                'direction': 'NEUTRAL',
                'score': max(score - 20, 0),
                'reasons': [*reasons, f'LOW_RR:{rr_ratio:.2f}'],
            }

        if score >= self.MIN_SCORE:
            return {
                'direction': 'BUY',
                'score': score,
                'reasons': reasons,
                'stop_loss': ind.close - risk,
                'take_profit': target,
                'rr_ratio': rr_ratio,
            }

        return {'direction': 'NEUTRAL', 'score': score, 'reasons': reasons}

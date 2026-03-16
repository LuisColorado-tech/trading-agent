"""
MeanReversionStrategy — Reversión a la media en extremos de Bollinger.
Compra en oversold extremo con volatilidad controlada.
Target: BB_middle. SL: 1.5 ATR.
"""
from agents.indicators import IndicatorSet


class MeanReversionStrategy:
    NAME = 'MEAN_REVERSION'
    MIN_SCORE = 70
    PREFERRED_ASSETS = ['XAU', 'XAG', 'ETH']

    def score(self, ind: IndicatorSet, df=None) -> dict:
        score = 0
        reasons = []

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

        # Verificar que no es tendencia bajista estructural
        ema_drop_pct = (ind.ema50 - ind.ema20) / ind.ema50 if ind.ema50 > 0 else 0
        if ema_drop_pct > 0.05:
            score -= 40
            reasons.append('STRONG_DOWNTREND_ABORT')

        # Volatilidad controlada
        if ind.bb_width < 0.10:
            score += 15
            reasons.append('LOW_VOLATILITY_FAVORABLE')
        elif ind.bb_width > 0.20:
            score -= 15
            reasons.append('HIGH_VOLATILITY_RISK')

        # Bonus por activo preferido
        if ind.asset in self.PREFERRED_ASSETS:
            score += 10
            reasons.append(f'PREFERRED_ASSET:{ind.asset}')

        # Target de salida: reversión a la media
        target = ind.bb_middle
        reward = target - ind.close
        risk = 1.5 * ind.atr
        rr_ratio = reward / risk if risk > 0 else 0

        if rr_ratio < 1.5:
            score -= 20
            reasons.append(f'LOW_RR:{rr_ratio:.2f}')

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

"""
StocksMinerviniStrategy — Minervini SEPA momentum investing adaptado a trading algorítmico.

Basado en la metodología de Mark Minervini (SEPA: Specific Entry Point Analysis):
- Solo BUY. Si el mercado no sube, no se opera.
- Trend Template: precio sobre EMAs medias, cerca de máximos
- Volumen de ruptura: confirmación institucional
- SL ceñido: -7% máximo. Cortar rápido si no funciona.
- TP 3:1 mínimo: arriesgar 7% para ganar 20%+

Timeframe: diario (1d). Solo evalúa 1 vez al día en opening de NYSE (14:30 UTC).
Universo: mega-cap tech con momentum real (NVDA, META, TSLA, AMZN, AAPL, QQQ).
"""
from agents.indicators import IndicatorSet


class StocksMinerviniStrategy:
    """Estrategia BUY-only momentum al estilo Minervini SEPA."""

    NAME = 'MINERVINI'
    MIN_SCORE = 70

    # Risk: Minervini usa 7% SL y 20%+ TP (3:1 mínimo)
    SL_PCT = 0.07
    TP_PCT = 0.20

    def score(self, ind: IndicatorSet, df_window=None) -> dict:
        """Evalúa si el activo cumple el Trend Template de Minervini.

        Trend Template (adaptado de Trade Like a Stock Market Wizard):
          1. Precio > EMA150 y EMA200
          2. EMA150 > EMA200 (tendencia alcista confirmada)
          3. Precio cerca del máximo de 52 semanas (dentro del 25%)
          4. Precio > EMA50 (tendencia de corto plazo)
          5. RSI en zona de momentum (50-68, no sobrecomprado >70)
          6. Volumen de ruptura > 1.5× media 50d
        """
        score = 0
        reasons = []

        # 1. Trend Template: precio sobre medias de largo plazo
        if ind.ema150 and ind.ema200:
            if ind.close > ind.ema150 and ind.close > ind.ema200:
                score += 25
                reasons.append('PRICE_ABOVE_EMA150_200')
                # 2. EMAs alineadas (150 > 200 = tendencia alcista)
                if ind.ema150 > ind.ema200:
                    score += 10
                    reasons.append('EMA150_ABOVE_EMA200')
            else:
                return {'direction': 'NEUTRAL', 'score': 0, 'reasons': ['BELOW_LONG_TERM_EMAS']}

        # 3. Precio sobre EMA50 (corto plazo)
        if ind.close > ind.ema50:
            score += 15
            reasons.append('PRICE_ABOVE_EMA50')
        else:
            # Pullback a EMA50 es válido si está sobre EMAs largas
            if ind.close > ind.ema50 * 0.95:
                score += 8
                reasons.append('PULLBACK_TO_EMA50')

        # 4. Proximidad a máximo 52 semanas (dentro del 25%)
        if ind.high_52w and ind.high_52w > 0:
            pct_from_high = (ind.high_52w - ind.close) / ind.high_52w
            if pct_from_high <= 0.25:
                score += 15
                reasons.append(f'NEAR_52W_HIGH:{pct_from_high*100:.0f}%')
            elif pct_from_high <= 0.35:
                score += 7
                reasons.append(f'MODERATE_PULLBACK:{pct_from_high*100:.0f}%')
            else:
                reasons.append(f'FAR_FROM_HIGH:{pct_from_high*100:.0f}%')

        # 5. RSI en zona de momentum (ni sobrecomprado ni débil)
        if 48 <= ind.rsi <= 68:
            score += 15
            reasons.append(f'RSI_MOMENTUM:{ind.rsi:.0f}')
        elif ind.rsi > 68:
            score -= 10
            reasons.append('RSI_OVERBOUGHT')
        elif 40 <= ind.rsi < 48:
            score += 5
            reasons.append(f'RSI_PULLBACK:{ind.rsi:.0f}')

        # 6. Volumen de ruptura
        if ind.vol_ratio and ind.vol_ratio > 1.5:
            score += 15
            reasons.append(f'VOLUME_BREAKOUT:{ind.vol_ratio:.1f}x')
        elif ind.vol_ratio and ind.vol_ratio > 1.2:
            score += 7
            reasons.append(f'VOLUME_ABOVE_AVG:{ind.vol_ratio:.1f}x')

        # 7. MACD bullish
        if ind.macd and ind.macd_signal and ind.macd > ind.macd_signal:
            score += 10
            reasons.append('MACD_BULLISH')

        # 8. Penalización si estamos en zona de sobrecompra extrema
        if ind.rsi > 72:
            score -= 15
            reasons.append('EXTENDED_RSI')

        if score < self.MIN_SCORE:
            return {'direction': 'NEUTRAL', 'score': max(0, score), 'reasons': reasons}

        return {
            'direction': 'BUY',
            'score': max(score, 0),
            'reasons': reasons,
            'stop_loss': ind.close * (1 - self.SL_PCT),
            'take_profit': ind.close * (1 + self.TP_PCT),
        }

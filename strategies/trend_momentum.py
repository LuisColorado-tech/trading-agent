"""
TrendMomentumStrategy — Captura momentum en tendencias establecidas.
Entra BUY o SELL cuando EMA alineada + RSI en zona + volumen + confluencia.
SL adaptativo: 1.2-1.5 ATR. TP: 2.5-3.0 ATR.
"""
from agents.indicators import IndicatorSet


class TrendMomentumStrategy:
    NAME = 'TREND_MOMENTUM'
    MIN_SCORE = 70  # subido de 65 para mayor selectividad

    def score(self, ind: IndicatorSet, df=None) -> dict:
        # Evaluar ambas direcciones con scoring gradual y elegir la mejor
        sell = self._score_sell(ind)
        buy = self._score_buy(ind)

        if sell['score'] >= self.MIN_SCORE and sell['score'] >= buy['score']:
            return sell
        if buy['score'] >= self.MIN_SCORE:
            return buy

        # Devolver la que más puntuó (como NEUTRAL)
        best = sell if sell['score'] >= buy['score'] else buy
        return {'direction': 'NEUTRAL', 'score': best['score'], 'reasons': best['reasons']}

    def _score_sell(self, ind: IndicatorSet) -> dict:
        score = 0
        reasons = []

        # EMA bajista: EMA20 < EMA50
        if ind.ema20 < ind.ema50 * 0.998:
            score += 25
            reasons.append('EMA_BEAR_CROSS')
            if ind.ema20 < ind.ema50 * 0.99:
                score += 10
                reasons.append('STRONG_BEAR_TREND')

        # Precio bajo EMA20 confirma presión vendedora
        if ind.close < ind.ema20:
            score += 15
            reasons.append('PRICE_BELOW_EMA20')

        # RSI en zona de debilidad sin oversold extremo
        if 25 <= ind.rsi <= 45:
            score += 20
            reasons.append(f'RSI_BEAR_ZONE:{ind.rsi:.1f}')
        elif ind.rsi < 25:
            score -= 15  # oversold extremo, rebote probable
            reasons.append('RSI_TOO_LOW_BOUNCE_RISK')

        # MACD bajista
        if ind.macd < ind.macd_signal and ind.macd_hist < 0:
            score += 15
            reasons.append('MACD_BEARISH')

        # Volumen confirma
        if ind.vol_ratio > 1.3:
            score += 10
            reasons.append(f'VOL_CONFIRM:{ind.vol_ratio:.2f}x')

        # Precio cerca de BB superior (buen punto de entrada SELL)
        if ind.bb_pct > 0.7:
            score += 10
            reasons.append('NEAR_BB_UPPER')

        # SL adaptativo: más ceñido en baja volatilidad
        sl_mult = 1.2 if ind.atr_pct < 0.02 else 1.5
        tp_mult = 2.5 if ind.atr_pct < 0.02 else 3.0

        return {
            'direction': 'SELL',
            'score': max(score, 0),
            'reasons': reasons,
            'stop_loss': ind.close + (sl_mult * ind.atr),
            'take_profit': ind.close - (tp_mult * ind.atr),
        }

    def _score_buy(self, ind: IndicatorSet) -> dict:
        score = 0
        reasons = []

        # EMA alcista: EMA20 > EMA50
        # Umbral bajado de 1.005 → 1.002 para igualar la asimetría con SELL (0.998).
        # El umbral anterior bloqueaba tendencias alcistas moderadas.
        if ind.ema20 > ind.ema50 * 1.002:
            score += 25
            reasons.append('EMA_BULL_CROSS')
            if ind.ema20 > ind.ema50 * 1.007:
                score += 10
                reasons.append('STRONG_BULL_TREND')

        # Precio sobre EMA20
        if ind.close > ind.ema20:
            score += 15
            reasons.append('PRICE_ABOVE_EMA20')

        # RSI en zona de momentum.  Ventana ampliada de 50-65 → 45-68:
        # el límite inferior aceptaba solo entradas ya tarde;  el superior
        # cortaba señales válidas en rallies con RSI 65-68.
        # La penalización de sobrecompra se mueve a RSI>72 (antes >70) y se
        # reduce de -20 → -15 para no destruir señales en mercados fuertes.
        if 45 <= ind.rsi <= 68:
            score += 20
            reasons.append(f'RSI_MOMENTUM_ZONE:{ind.rsi:.1f}')
        elif ind.rsi > 72:
            score -= 15
            reasons.append('RSI_OVERBOUGHT')

        # MACD alcista
        if ind.macd > ind.macd_signal and ind.macd_hist > 0:
            score += 15
            reasons.append('MACD_BULLISH')

        # Volumen confirma
        if ind.vol_ratio > 1.3:
            score += 10
            reasons.append(f'VOL_CONFIRM:{ind.vol_ratio:.2f}x')

        # Espacio hasta BB superior
        if ind.close < ind.bb_upper * 0.97:
            score += 10
            reasons.append('ROOM_TO_BB_UPPER')

        # SL adaptativo
        sl_mult = 1.2 if ind.atr_pct < 0.02 else 1.5
        tp_mult = 2.5 if ind.atr_pct < 0.02 else 3.0

        return {
            'direction': 'BUY',
            'score': max(score, 0),
            'reasons': reasons,
            'stop_loss': ind.close - (sl_mult * ind.atr),
            'take_profit': ind.close + (tp_mult * ind.atr),
        }

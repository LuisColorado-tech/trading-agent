"""
StocksMomentumStrategy — Momentum para acciones NYSE/NASDAQ.

Adaptado de TrendMomentumStrategy pero calibrado para stocks:
- Volume ratio threshold: 1.5 (vs 1.2 en crypto — stocks tienen spikes más limpios)
- RSI zones ligeramente ajustadas para mercados con horario
- SL/TP via StocksProfile (más ajustados que crypto)
- Ambas direcciones permitidas (BUY y SELL)
- xsignal_boost: si hay señal alineada en xsignals_signals las últimas 48h,
  se agrega puntos extra al score

MIN_SCORE = 65 (igual que TrendMomentumStrategy)
"""
from agents.indicators import IndicatorSet
from core.stocks_profiles import get_stocks_profile


class StocksMomentumStrategy:
    NAME = 'STOCKS_MOMENTUM'
    MIN_SCORE = 65

    def score(self, ind: IndicatorSet, xsignal_boost: int = 0) -> dict:
        """Evalúa ambas direcciones y devuelve la mejor señal.

        Args:
            ind: indicadores técnicos calculados por IndicatorEngine
            xsignal_boost: puntos extra provenientes de señales X alineadas
        """
        sell = self._score_sell(ind)
        buy = self._score_buy(ind)

        # Aplicar boost de xsignals a la dirección alineada
        if xsignal_boost > 0:
            sell['score'] += xsignal_boost
            sell['reasons'].append(f'XSIGNAL_BOOST:+{xsignal_boost}')
            buy['score'] += xsignal_boost
            buy['reasons'].append(f'XSIGNAL_BOOST:+{xsignal_boost}')

        if sell['score'] >= self.MIN_SCORE and sell['score'] >= buy['score']:
            return sell
        if buy['score'] >= self.MIN_SCORE:
            return buy

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

        # Precio bajo EMA20
        if ind.close < ind.ema20:
            score += 15
            reasons.append('PRICE_BELOW_EMA20')

        # RSI en zona bajista — stocks sobrevendidos a RSI<30 (más conservador que crypto)
        if 28 <= ind.rsi <= 48:
            score += 20
            reasons.append(f'RSI_BEAR_ZONE:{ind.rsi:.1f}')
        elif ind.rsi < 28:
            score -= 15
            reasons.append('RSI_TOO_LOW_BOUNCE_RISK')

        # MACD bajista
        if ind.macd < ind.macd_signal and ind.macd_hist < 0:
            score += 15
            reasons.append('MACD_BEARISH')

        # Volumen: umbral 1.5 para stocks (spikes más limpios que crypto)
        if ind.vol_ratio > 1.5:
            score += 15
            reasons.append(f'VOL_CONFIRM:{ind.vol_ratio:.2f}x')
        elif ind.vol_ratio > 1.2:
            score += 7
            reasons.append(f'VOL_PARTIAL:{ind.vol_ratio:.2f}x')

        # Precio cerca de BB superior
        if ind.bb_pct > 0.7:
            score += 10
            reasons.append('NEAR_BB_UPPER')

        # Precio bajo VWAP confirma presión vendedora intradía
        if ind.close < ind.vwap:
            score += 8
            reasons.append('BELOW_VWAP')

        profile = get_stocks_profile(ind.asset)
        sl_mult = profile.sl_multiplier
        tp_mult = profile.tp_multiplier

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

        # EMA alcista
        if ind.ema20 > ind.ema50 * 1.002:
            score += 25
            reasons.append('EMA_BULL_CROSS')
            if ind.ema20 > ind.ema50 * 1.012:
                score += 10
                reasons.append('STRONG_BULL_TREND')

        # Precio sobre EMA20
        if ind.close > ind.ema20:
            score += 15
            reasons.append('PRICE_ABOVE_EMA20')

        # RSI en zona momentum — igual que crypto pero ligeramente más estrecho
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

        # Volumen: umbral 1.5 para stocks
        if ind.vol_ratio > 1.5:
            score += 15
            reasons.append(f'VOL_CONFIRM:{ind.vol_ratio:.2f}x')
        elif ind.vol_ratio > 1.2:
            score += 7
            reasons.append(f'VOL_PARTIAL:{ind.vol_ratio:.2f}x')

        # Espacio hacia BB superior (precio no sobreextendido)
        if ind.bb_pct < 0.70:
            score += 10
            reasons.append('ROOM_TO_BB_UPPER')

        # Precio sobre VWAP — confirma presión compradora intradía
        if ind.close > ind.vwap:
            score += 8
            reasons.append('ABOVE_VWAP')

        profile = get_stocks_profile(ind.asset)
        sl_mult = profile.sl_multiplier
        tp_mult = profile.tp_multiplier

        return {
            'direction': 'BUY',
            'score': max(score, 0),
            'reasons': reasons,
            'stop_loss': ind.close - (sl_mult * ind.atr),
            'take_profit': ind.close + (tp_mult * ind.atr),
        }

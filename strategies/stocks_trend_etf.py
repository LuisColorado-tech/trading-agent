"""
StocksTrendEtfStrategy — Estrategia para ETFs y activos de baja volatilidad.

Diferencias clave vs StocksMomentumStrategy (diseñada para TSLA/NVDA):

  PROBLEMA que resuelve:
    Con StocksMomentumStrategy, SPY/QQQ/EWJ/EEM generan 0 BUY trades en 2 años
    porque el umbral de volumen (1.5x) es demasiado alto para ETFs índice
    y el rango RSI momentum (45-68) es demasiado estrecho para movimientos lentos.

  AJUSTES:
    - vol_ratio BUY:  1.2x (vs 1.5x) — ETFs tienen spikes de volumen más suaves
    - vol_ratio SELL: 1.3x (vs 1.5x) — algo más exigente en la bajada
    - RSI BUY:   40-65 (vs 45-68)    — zona más amplia para activos lentos
    - RSI SELL:  30-52 (vs 28-48)    — desplazada levemente hacia neutral
    - EMA threshold BUY:  1.001 (vs 1.002) — cruces más suaves en índices
    - EMA threshold SELL: 0.999 (vs 0.998) — ídem
    - bb_pct BUY room: < 0.75 (vs < 0.70) — menos restrictivo
    - VWAP weight: mismo (8 pts) — confirma presión intradía igual de bien

  MIN_SCORE = 60 (vs 65) — algo más permisivo porque los ETFs generan menos
  confluencia de volumen que los singles stocks.

  Activos objetivo: SPY, QQQ, GLD, EWZ, EEM, FXI, EWJ
"""
from agents.indicators import IndicatorSet
from core.stocks_profiles import get_stocks_profile


class StocksTrendEtfStrategy:
    NAME = 'STOCKS_TREND_ETF'
    MIN_SCORE = 65

    def score(self, ind: IndicatorSet, xsignal_boost: int = 0) -> dict:
        sell = self._score_sell(ind)
        buy  = self._score_buy(ind)

        if xsignal_boost > 0:
            sell['score'] += xsignal_boost
            sell['reasons'].append(f'XSIGNAL_BOOST:+{xsignal_boost}')
            buy['score']  += xsignal_boost
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

        # EMA bajista — umbral más suave para índices (cruces lentos)
        if ind.ema20 < ind.ema50 * 0.999:
            score += 25
            reasons.append('EMA_BEAR_CROSS')
            if ind.ema20 < ind.ema50 * 0.992:
                score += 10
                reasons.append('STRONG_BEAR_TREND')

        # Precio bajo EMA20
        if ind.close < ind.ema20:
            score += 15
            reasons.append('PRICE_BELOW_EMA20')

        # RSI zona bajista — desplazada vs momentum (ETFs no van tan oversold)
        if 30 <= ind.rsi <= 52:
            score += 20
            reasons.append(f'RSI_BEAR_ZONE:{ind.rsi:.1f}')
        elif ind.rsi < 30:
            score -= 10
            reasons.append('RSI_TOO_LOW_BOUNCE_RISK')

        # MACD bajista
        if ind.macd < ind.macd_signal and ind.macd_hist < 0:
            score += 15
            reasons.append('MACD_BEARISH')

        # Volumen — ETFs tienen spikes más suaves: umbral 1.3x
        if ind.vol_ratio > 1.3:
            score += 15
            reasons.append(f'VOL_CONFIRM:{ind.vol_ratio:.2f}x')
        elif ind.vol_ratio > 1.1:
            score += 7
            reasons.append(f'VOL_PARTIAL:{ind.vol_ratio:.2f}x')

        # Precio cerca de BB superior (sobreextensión bajista)
        if ind.bb_pct > 0.7:
            score += 10
            reasons.append('NEAR_BB_UPPER')

        # Bajo VWAP confirma presión vendedora intradía
        if ind.close < ind.vwap:
            score += 8
            reasons.append('BELOW_VWAP')

        profile = get_stocks_profile(ind.asset)
        return {
            'direction': 'SELL',
            'score': max(score, 0),
            'reasons': reasons,
            'stop_loss':   ind.close + (profile.sl_multiplier * ind.atr),
            'take_profit': ind.close - (profile.tp_multiplier * ind.atr),
        }

    def _score_buy(self, ind: IndicatorSet) -> dict:
        score = 0
        reasons = []

        # EMA alcista — umbral suave para índices
        if ind.ema20 > ind.ema50 * 1.001:
            score += 25
            reasons.append('EMA_BULL_CROSS')
            if ind.ema20 > ind.ema50 * 1.010:
                score += 10
                reasons.append('STRONG_BULL_TREND')

        # Precio sobre EMA20
        if ind.close > ind.ema20:
            score += 15
            reasons.append('PRICE_ABOVE_EMA20')

        # RSI momentum — rango más amplio para activos lentos (40-65 vs 45-68)
        if 40 <= ind.rsi <= 65:
            score += 20
            reasons.append(f'RSI_MOMENTUM_ZONE:{ind.rsi:.1f}')
        elif ind.rsi > 70:
            score -= 10
            reasons.append('RSI_OVERBOUGHT')

        # MACD alcista
        if ind.macd > ind.macd_signal and ind.macd_hist > 0:
            score += 15
            reasons.append('MACD_BULLISH')

        # Volumen — umbral bajo para ETFs (1.2x vs 1.5x en singles)
        if ind.vol_ratio > 1.2:
            score += 15
            reasons.append(f'VOL_CONFIRM:{ind.vol_ratio:.2f}x')
        elif ind.vol_ratio > 1.0:
            score += 7
            reasons.append(f'VOL_PARTIAL:{ind.vol_ratio:.2f}x')

        # Espacio hacia BB superior
        if ind.bb_pct < 0.75:
            score += 10
            reasons.append('ROOM_TO_BB_UPPER')

        # Sobre VWAP confirma presión compradora intradía
        if ind.close > ind.vwap:
            score += 8
            reasons.append('ABOVE_VWAP')

        profile = get_stocks_profile(ind.asset)
        return {
            'direction': 'BUY',
            'score': max(score, 0),
            'reasons': reasons,
            'stop_loss':   ind.close - (profile.sl_multiplier * ind.atr),
            'take_profit': ind.close + (profile.tp_multiplier * ind.atr),
        }

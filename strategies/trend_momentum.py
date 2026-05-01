"""
TrendMomentumStrategy — Captura momentum en tendencias establecidas.
Entra BUY o SELL cuando EMA alineada + RSI en zona + volumen + confluencia.
SL adaptativo: 1.2-1.5 ATR. TP: 2.5-3.0 ATR.
"""
from agents.indicators import IndicatorSet
from core.asset_profiles import get_profile


class TrendMomentumStrategy:
    NAME = 'TREND_MOMENTUM'
    MIN_SCORE = 75  # Subido de 70→75 (v3): filtrar señales de baja calidad, PF 1.08→meta 1.20

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

        # EMA bajista: EMA20 < EMA50. Umbral 0.995 (0.5% gap) exige tendencia bajista
        # real y evita entradas en mercados choppy donde el cruce EMA revierte en minutos.
        # Con 0.998 se producían rachas de 8-12 SL consecutivos (ver CSV May-Jun 2024).
        if ind.ema20 < ind.ema50 * 0.995:
            score += 25
            reasons.append('EMA_BEAR_CROSS')
            if ind.ema20 < ind.ema50 * 0.99:
                score += 10
                reasons.append('STRONG_BEAR_TREND')

        # Precio bajo EMA20 confirma presión vendedora
        if ind.close < ind.ema20:
            score += 15
            reasons.append('PRICE_BELOW_EMA20')

        # RSI zona de debilidad SELL — asset-specific:
        # ETH usa 25-50 (el rango 25-30 es momentum bajista válido en ETH, no rebote).
        # Backtest v3: RSI 30-50 destruyó TREND_MOMENTUM ETH (-$8,435 vs v2).
        # Resto de assets: 30-50 (evita entrar en oversold extremo con rebote probable).
        if ind.asset == 'ETH':
            rsi_bear_low, rsi_bear_high, rsi_os_guard = 25, 50, 25
        else:
            rsi_bear_low, rsi_bear_high, rsi_os_guard = 30, 50, 30
        if rsi_bear_low <= ind.rsi <= rsi_bear_high:
            score += 20
            reasons.append(f'RSI_BEAR_ZONE:{ind.rsi:.1f}')
        elif ind.rsi < rsi_os_guard:
            score -= 15  # oversold extremo, rebote probable
            reasons.append('RSI_TOO_LOW_BOUNCE_RISK')

        # MACD bajista
        if ind.macd < ind.macd_signal and ind.macd_hist < 0:
            score += 15
            reasons.append('MACD_BEARISH')

        # Volumen confirma (umbral 1.2 en lugar de 1.3: en RANGE el volumen baja)
        if ind.vol_ratio > 1.2:
            score += 10
            reasons.append(f'VOL_CONFIRM:{ind.vol_ratio:.2f}x')

        # Precio cerca de BB superior (buen punto de entrada SELL)
        if ind.bb_pct > 0.7:
            score += 10
            reasons.append('NEAR_BB_UPPER')

        # SL/TP por perfil de asset (sustituye el heurístico generico)
        profile = get_profile(ind.asset)
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

        # SOL tiene win rate 19% en BUY/TREND_UP (backtest 6m):
        # requiere cruce EMA fuerte (1.007) en lugar del umbral suave (1.002).
        ema_bull_threshold = 1.007 if ind.asset == 'SOL' else 1.002

        # EMA alcista
        if ind.ema20 > ind.ema50 * ema_bull_threshold:
            score += 25
            reasons.append('EMA_BULL_CROSS')
            if ind.ema20 > ind.ema50 * 1.012:
                score += 10
                reasons.append('STRONG_BULL_TREND')

        # Precio sobre EMA20
        if ind.close > ind.ema20:
            score += 15
            reasons.append('PRICE_ABOVE_EMA20')

        # RSI en zona de momentum real (50-65). Reducido de 45-68 → 50-65 (v3):
        # 45-50 incluía entradas débiles en rebotes; 65-68 incluía pre-sobrecompra.
        # Penalización sobrecompra bajada a RSI>68 (antes >72) para ser más estrictos.
        if 50 <= ind.rsi <= 65:
            score += 20
            reasons.append(f'RSI_MOMENTUM_ZONE:{ind.rsi:.1f}')
        elif ind.rsi > 68:
            score -= 15
            reasons.append('RSI_OVERBOUGHT')

        # MACD alcista
        if ind.macd > ind.macd_signal and ind.macd_hist > 0:
            score += 15
            reasons.append('MACD_BULLISH')

        # Volumen confirma (umbral 1.2 en lugar de 1.3: en RANGE el volumen baja)
        if ind.vol_ratio > 1.2:
            score += 10
            reasons.append(f'VOL_CONFIRM:{ind.vol_ratio:.2f}x')

        # Espacio hasta BB superior: usando bb_pct en vez de distancia absoluta.
        # La condición original (close < bb_upper * 0.97) nunca se cumplía en
        # bandas estrechas (RANGE) porque bb_upper ya está < 3% sobre el precio.
        if ind.bb_pct < 0.70:
            score += 10
            reasons.append('ROOM_TO_BB_UPPER')

        # SL/TP por perfil de asset (sustituye el heurístico generico)
        profile = get_profile(ind.asset)
        sl_mult = profile.sl_multiplier
        tp_mult = profile.tp_multiplier

        return {
            'direction': 'BUY',
            'score': max(score, 0),
            'reasons': reasons,
            'stop_loss': ind.close - (sl_mult * ind.atr),
            'take_profit': ind.close + (tp_mult * ind.atr),
        }

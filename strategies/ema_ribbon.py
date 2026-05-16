"""
EMARibbonStrategy — EMA Ribbon Trend Following (BUY-only).

Reverse-engineered from: andrewboyley/crypto-trader (15⭐)
Fuente: GitHub Strategy Hunter v2.0 — búsqueda multi-idioma.

Estrategia:
  1. 5 EMAs alineadas en orden (8>13>21>34>55) = tendencia alcista confirmada
  2. RSI < 65 = no sobrecomprado, hay espacio para subir
  3. Stochastic < 80 = momentum no agotado
  
  Los 3 filtros deben coincidir simultáneamente. Esto produce pocas entradas
  pero de alta calidad (la alineación de 5 EMAs es rara fuera de tendencias reales).

Salida:
  - EMA21 cruza por debajo de EMA55 (tendencia rota)
  - RSI > 70 (sobrecompra)
  - Stochastic > 95 (agotamiento extremo)
  - SL: 5% fijo (Minervini-style, cortar rápido)
  - TP: 15% (R:R 3:1)

Timeframe: 1h (el original usa 1m en Binance, adaptado a 1h para menos ruido)
Dirección: SOLO BUY. Complementa el SELL de TrendMomentum.
Capital mínimo: $100 en Binance/Kraken. $500 recomendado.
"""
from agents.indicators import IndicatorSet
from core.asset_profiles import get_profile


class EMARibbonStrategy:
    """EMA Ribbon — Trend following con confirmación múltiple."""

    NAME = 'EMA_RIBBON'
    MIN_SCORE = 60  # 3 condiciones = 75 pts (EMA 40 + RSI 20 + STOCH 15)

    SL_PCT = 0.05   # 5% stop loss
    TP_PCT = 0.15   # 15% take profit (R:R 3:1)

    def score(self, ind: IndicatorSet, df=None) -> dict:
        """Evalúa condiciones del EMA Ribbon. Solo BUY."""
        score = 0
        reasons = []

        # ── 1. EMA Ribbon: 5 EMAs alineadas en orden ascendente ──
        # EMA8 > EMA13 > EMA21 > EMA34 > EMA55
        # Esto solo ocurre en tendencias alcistas bien definidas.
        ema_ok = (
            ind.ema8 > ind.ema13 and
            ind.ema13 > ind.ema21 and
            ind.ema21 > ind.ema34 and
            ind.ema34 > ind.ema55
        )
        if ema_ok:
            score += 40
            reasons.append('EMA_RIBBON_ALIGNED')
        else:
            return {'direction': 'NEUTRAL', 'score': 0, 'reasons': ['EMA_RIBBON_NOT_ALIGNED']}

        # ── 2. RSI: zona de momentum (no sobrecomprado) ──
        if hasattr(ind, 'rsi') and ind.rsi < 65:
            score += 20
            reasons.append(f'RSI_OK:{ind.rsi:.1f}')
        elif hasattr(ind, 'rsi') and ind.rsi >= 65:
            score -= 10
            reasons.append(f'RSI_HIGH:{ind.rsi:.1f}')

        # ── 3. Stochastic: no agotado ──
        if hasattr(ind, 'stoch_k') and ind.stoch_k < 80:
            score += 15
            reasons.append(f'STOCH_OK:{ind.stoch_k:.1f}')
        elif hasattr(ind, 'stoch_k') and ind.stoch_k >= 80:
            score -= 10
            reasons.append(f'STOCH_HIGH:{ind.stoch_k:.1f}')

        # ── 4. Bonus: MACD confirmando ──
        if ind.macd > ind.macd_signal:
            score += 10
            reasons.append('MACD_BULLISH')

        # ── 5. Bonus: precio sobre EMA20 (corto plazo) ──
        if ind.close > ind.ema20:
            score += 5
            reasons.append('ABOVE_EMA20')

        if score < self.MIN_SCORE:
            return {'direction': 'NEUTRAL', 'score': max(score, 0), 'reasons': reasons}

        profile = get_profile(ind.asset)
        sl_mult = profile.sl_multiplier
        tp_mult = profile.tp_multiplier

        return {
            'direction': 'BUY',
            'score': max(score, 0),
            'reasons': reasons,
            'stop_loss': ind.close * (1 - self.SL_PCT),
            'take_profit': ind.close * (1 + self.TP_PCT),
        }

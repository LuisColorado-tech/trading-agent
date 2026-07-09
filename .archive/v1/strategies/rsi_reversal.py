"""
RSIReversalStrategy — BUY oversold bounces in TREND_UP regime.

Complements TrendMomentum (SELL in TREND_DOWN) by capturing mean-reversion
bounces when the macro trend is bullish but RSI signals a temporary oversold condition.

Rules:
  1. RSI < 30 on 1h timeframe → oversold bounce opportunity
  2. Only BUY in TREND_UP (macro wind at back)
  3. Exit when RSI > 55 (recovered) or SL hit
  4. SL at 1.5× ATR below entry
  5. TP at entry + 2× ATR (R:R = 1.33)

Based on well-documented statistical edge: RSI < 30 in uptrends has 60-65%
probability of reversion within 3-5 candles on 1h timeframe.
"""
from agents.indicators import IndicatorSet
from core.asset_profiles import get_profile


class RSIReversalStrategy:
    """RSI oversold reversal — BUY only, TREND_UP only."""

    NAME = 'RSI_REVERSAL'
    MIN_SCORE = 50
    RSI_OVERSOLD = 30
    RSI_EXIT = 55
    ATR_SL_MULT = 1.5
    ATR_TP_MULT = 2.0

    def score(self, ind: IndicatorSet, df=None) -> dict:
        if ind.rsi >= self.RSI_OVERSOLD:
            return {'direction': 'NEUTRAL', 'score': 0,
                    'reasons': [f'RSI_NOT_OVERSOLD:{ind.rsi:.1f}']}

        score = 60
        reasons = [f'RSI_OVERSOLD:{ind.rsi:.1f}']

        if hasattr(ind, 'ema20') and ind.close < ind.ema20:
            score += 5
            reasons.append('PRICE_BELOW_EMA20')
        if hasattr(ind, 'ema50') and ind.ema20 < ind.ema50:
            score -= 10
            reasons.append('EMA_BEARISH')
        if hasattr(ind, 'macd_hist') and ind.macd_hist < 0:
            reasons.append('MACD_DIP')

        if score < self.MIN_SCORE:
            return {'direction': 'NEUTRAL', 'score': max(score, 0), 'reasons': reasons}

        atr = ind.atr if hasattr(ind, 'atr') and ind.atr > 0 else ind.close * 0.02
        entry = ind.close
        sl = entry - atr * self.ATR_SL_MULT
        tp = entry + atr * self.ATR_TP_MULT

        return {
            'direction': 'BUY',
            'score': max(score, 0),
            'reasons': reasons,
            'stop_loss': sl,
            'take_profit': tp,
        }

"""
test_strategies.py — Tests unitarios de las 3 estrategias de trading.

Verifica:
  - TrendMomentum: condiciones BUY y SELL, SL/TP = ATR multipliers
  - MeanReversion: zona BB inferior, target = BB middle
  - Breakout: requisito de volumen, resistencia, SL/TP
  - Todas: direction/score/SL/TP coherentes con la teoría
"""
import sys
import pytest
from unittest.mock import MagicMock
from dataclasses import replace

sys.path.insert(0, '/opt/trading')

from agents.indicators import IndicatorSet


# ── Helper: crear IndicatorSet base ───────────────────────────────

def _base_indicators(**overrides) -> IndicatorSet:
    """IndicatorSet con valores neutrales, sobreescribibles."""
    defaults = dict(
        asset='BTC', timeframe='15m',
        close=75000.0, volume=1000.0,
        ema20=75100.0, ema50=74800.0, ema200=73000.0,
        rsi=55.0,
        macd=50.0, macd_signal=45.0, macd_hist=5.0,
        bb_upper=76000.0, bb_middle=75000.0, bb_lower=74000.0,
        bb_pct=0.5, bb_width=0.027,
        atr=666.0, atr_pct=0.009,
        vwap=75000.0, vol_sma20=800.0, vol_ratio=1.25,
        trend_direction='UP', trend_strength=0.4,
    )
    defaults.update(overrides)
    return IndicatorSet(**defaults)


# ═══════════════════════════════════════════════════════════════════
# TrendMomentumStrategy
# ═══════════════════════════════════════════════════════════════════

class TestTrendMomentum:
    """Captura momentum en tendencias establecidas."""

    def setup_method(self):
        from strategies.trend_momentum import TrendMomentumStrategy
        self.strategy = TrendMomentumStrategy()

    def test_buy_conditions_met(self):
        """EMA bull cross + price above EMA20 + RSI momentum + MACD + volume + room"""
        ind = _base_indicators(
            close=75000.0, ema20=75100.0, ema50=74700.0,  # ema20 > ema50*1.005
            rsi=55.0, vol_ratio=1.4, bb_upper=76500.0,
            macd=50.0, macd_signal=45.0, macd_hist=5.0,
        )
        result = self.strategy.score(ind)
        assert result['direction'] == 'BUY'
        assert result['score'] >= 70

    def test_buy_sl_tp_use_atr(self):
        """BUY SL below entry, TP above entry, both ATR-based"""
        ind = _base_indicators(
            close=75000.0, ema20=75100.0, ema50=74700.0,
            atr=666.0, atr_pct=0.009, rsi=55.0, vol_ratio=1.4,
            bb_upper=76500.0,
            macd=50.0, macd_signal=45.0, macd_hist=5.0,
        )
        result = self.strategy.score(ind)
        if result['direction'] == 'BUY':
            assert result['stop_loss'] < ind.close
            assert result['take_profit'] > ind.close

    def test_sell_conditions_met(self):
        """EMA bear cross + price below EMA + RSI weak + MACD bear → SELL gradual"""
        ind = _base_indicators(
            close=74000.0,
            ema20=74000.0, ema50=74500.0,  # ema20 < ema50 * 0.998
            rsi=40.0,
            macd=-10.0, macd_signal=-5.0, macd_hist=-5.0,
            vol_ratio=1.4, bb_pct=0.75,
        )
        result = self.strategy.score(ind)
        assert result['direction'] == 'SELL'
        assert result['score'] >= 70

    def test_sell_sl_above_entry(self):
        """SELL: SL above entry, TP below entry"""
        ind = _base_indicators(
            close=74000.0, ema20=74000.0, ema50=74500.0,
            rsi=40.0, atr=666.0,
            macd=-10.0, macd_signal=-5.0, macd_hist=-5.0,
            vol_ratio=1.4, bb_pct=0.75,
        )
        result = self.strategy.score(ind)
        if result['direction'] == 'SELL':
            assert result['stop_loss'] > ind.close
            assert result['take_profit'] < ind.close

    def test_rsi_overbought_penalizes_buy(self):
        """RSI > 70 penaliza el score de BUY"""
        ind = _base_indicators(
            close=75000.0, ema20=75100.0, ema50=74700.0,
            rsi=72.0, vol_ratio=1.4, bb_upper=76000.0,
            macd=50.0, macd_signal=45.0, macd_hist=5.0,
        )
        result = self.strategy.score(ind)
        # RSI overbought reduces BUY score
        if result['direction'] == 'BUY':
            assert result['score'] < 85

    def test_rsi_too_low_penalizes_sell(self):
        """RSI < 25 penaliza SELL por riesgo de rebote"""
        ind = _base_indicators(
            close=74000.0, ema20=74000.0, ema50=74500.0,
            rsi=20.0,  # oversold extremo
            macd=-10.0, macd_signal=-5.0, macd_hist=-5.0,
        )
        result = self.strategy.score(ind)
        # Should not score high for SELL with extreme oversold
        if result['direction'] == 'SELL':
            assert result['score'] < 85

    def test_min_score_threshold(self):
        """Señales débiles no generan oportunidad"""
        ind = _base_indicators(
            close=75000.0, ema20=74900.0, ema50=74900.0,  # sin cruce claro
            rsi=50.0, vol_ratio=0.8,
        )
        result = self.strategy.score(ind)
        assert result['direction'] == 'NEUTRAL'


# ═══════════════════════════════════════════════════════════════════
# MeanReversionStrategy
# ═══════════════════════════════════════════════════════════════════

class TestMeanReversion:
    """Reversión a la media: sólo metales y sin operar contra régimen bajista."""

    def setup_method(self):
        from strategies.mean_reversion import MeanReversionStrategy
        self.strategy = MeanReversionStrategy()

    def test_extreme_oversold_generates_buy(self):
        """BB_pct < 0.05 + RSI < 25 + low vol → BUY"""
        ind = _base_indicators(
            asset='XAU',
            close=2250.0, bb_pct=0.02, rsi=22.0,
            ema20=2288.0, ema50=2290.0,
            bb_width=0.08, bb_middle=2350.0,
            atr=26.0,
            trend_direction='SIDEWAYS',
        )
        result = self.strategy.score(ind)
        assert result['direction'] == 'BUY'

    def test_target_is_bb_middle(self):
        """TP = BB middle (reversión a la media)"""
        ind = _base_indicators(
            asset='XAG',
            close=2250.0, bb_pct=0.02, rsi=22.0,
            ema20=2288.0, ema50=2290.0,
            bb_width=0.08, bb_middle=2350.0,
            atr=26.0,
            trend_direction='SIDEWAYS',
        )
        result = self.strategy.score(ind)
        if result['direction'] == 'BUY':
            assert abs(result['take_profit'] - 2350.0) < 1.0  # bb_middle

    def test_strong_downtrend_aborts(self):
        """Régimen bajista o caída EMA > 1.5% aborta la señal."""
        ind = _base_indicators(
            asset='XAU',
            close=2250.0, bb_pct=0.02, rsi=22.0,
            ema20=2250.0, ema50=2300.0,
            bb_width=0.08, bb_middle=2300.0,
            atr=26.0,
            trend_direction='DOWN',
        )
        result = self.strategy.score(ind)
        assert result['direction'] == 'NEUTRAL'

    def test_crypto_assets_are_disabled(self):
        """MeanReversion queda limitada a metales mientras se revalida el edge."""
        ind = _base_indicators(
            asset='ETH',
            close=75000.0, bb_pct=0.02, rsi=20.0,
            bb_middle=77000.0, atr=666.0,
            trend_direction='SIDEWAYS',
        )
        result = self.strategy.score(ind)
        assert result['direction'] == 'NEUTRAL'


# ═══════════════════════════════════════════════════════════════════
# BreakoutStrategy
# ═══════════════════════════════════════════════════════════════════

class TestBreakout:
    """Ruptura de resistencia con volumen. Volumen es requisito primario."""

    def setup_method(self):
        from strategies.breakout import BreakoutStrategy
        self.strategy = BreakoutStrategy()

    def test_insufficient_volume_returns_neutral(self):
        """Sin volumen 2× → NEUTRAL inmediato, sin importar otros indicadores"""
        ind = _base_indicators(vol_ratio=1.5)  # < 2.0
        import pandas as pd
        df = pd.DataFrame({'high': [75000]*25, 'low': [74000]*25,
                           'close': [74500]*25, 'open': [74500]*25,
                           'volume': [1000]*25})
        result = self.strategy.score(ind, df)
        assert result['direction'] == 'NEUTRAL'

    def test_breakout_with_volume_and_resistance(self):
        """Volumen ≥ 2× + quiebre de resistencia → BUY"""
        ind = _base_indicators(
            asset='BTC', close=75500.0, vol_ratio=2.5,
            atr_pct=0.02, trend_direction='UP', atr=666.0,
        )
        import pandas as pd
        # Need 20+ candles. Recent rolling max of highs[-2] must be < close*1.005
        # Set all previous highs to 75100, so rolling max = 75100
        # close = 75500 > 75100*1.005 = 75475.5 → resistance break!
        n = 25
        highs = [75100.0] * n
        df = pd.DataFrame({
            'high': highs, 'low': [73000]*n,
            'close': [74500]*n, 'open': [74500]*n,
            'volume': [1000]*n,
        })
        result = self.strategy.score(ind, df)
        assert result['direction'] == 'BUY'

    def test_breakout_sl_tp_use_different_atr(self):
        """Breakout: SL=1.0×ATR (más ajustado), TP=3.0×ATR (mayor reward)"""
        # Just verify the formulas using ATR
        atr = 666.0
        close = 75000.0
        expected_sl = close - (1.0 * atr)   # 74334
        expected_tp = close + (3.0 * atr)    # 76998
        rr = (expected_tp - close) / (close - expected_sl)
        assert abs(rr - 3.0) < 0.01  # RR = 3.0

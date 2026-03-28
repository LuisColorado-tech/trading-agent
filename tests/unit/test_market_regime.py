"""Tests unitarios para clasificación de régimen de mercado."""
import sys

sys.path.insert(0, '/opt/trading')

from agents.indicators import IndicatorSet
from core.market_regime import classify_market_regime, strategy_allowed_in_regime


def _indicators(**overrides):
    defaults = dict(
        asset='BTC', timeframe='15m', close=100.0, volume=1000.0,
        ema20=101.0, ema50=99.0, ema200=95.0,
        rsi=55.0, macd=1.0, macd_signal=0.8, macd_hist=0.2,
        bb_upper=105.0, bb_middle=100.0, bb_lower=95.0,
        bb_pct=0.5, bb_width=0.08, atr=1.0, atr_pct=0.01,
        vwap=100.0, vol_sma20=800.0, vol_ratio=1.2,
        trend_direction='UP', trend_strength=0.25,
    )
    defaults.update(overrides)
    return IndicatorSet(**defaults)


class TestMarketRegime:
    def test_detects_range_regime(self):
        regime = classify_market_regime(_indicators(trend_strength=0.05, bb_width=0.06, atr_pct=0.008, macd_hist=0.01))
        assert regime.name == 'RANGE'
        assert strategy_allowed_in_regime('MEAN_REVERSION', regime)
        assert not strategy_allowed_in_regime('BREAKOUT', regime)

    def test_detects_trend_up_regime(self):
        regime = classify_market_regime(_indicators(trend_direction='UP', trend_strength=0.3, macd_hist=0.4, vol_ratio=1.4, atr_pct=0.012))
        assert regime.name == 'TREND_UP'
        assert strategy_allowed_in_regime('TREND_MOMENTUM', regime)
        assert not strategy_allowed_in_regime('MEAN_REVERSION', regime)

    def test_detects_breakout_up_regime(self):
        regime = classify_market_regime(_indicators(trend_direction='UP', trend_strength=0.3, macd_hist=0.5, vol_ratio=2.5, atr_pct=0.02))
        assert regime.name == 'BREAKOUT_UP'
        assert strategy_allowed_in_regime('BREAKOUT', regime)

    def test_detects_choppy_regime(self):
        regime = classify_market_regime(_indicators(trend_strength=0.1, bb_width=0.16, atr_pct=0.02, vol_ratio=1.1, macd_hist=0.0, trend_direction='SIDEWAYS'))
        assert regime.name == 'CHOPPY'
        assert not strategy_allowed_in_regime('TREND_MOMENTUM', regime)
        assert not strategy_allowed_in_regime('MEAN_REVERSION', regime)
"""
TrendMomentumStrategy v2 — Migración a BaseStrategy.

Lógica de scoring IDÉNTICA a v1 (strategies/trend_momentum.py).
Envuelta en el contrato BaseStrategy para Etapa 1.

Comparación v1 vs v2: se loguea en INFO si hay divergencia.
"""
from typing import Optional

from agents.indicators import IndicatorSet
from core.asset_profiles import get_profile
from strategies.base import BaseStrategy, Signal, Direction


class TrendMomentumStrategyV2(BaseStrategy):
    name = "trend_momentum"
    default_config = {
        "min_score": 65,
    }

    def detect(self, ind: IndicatorSet, regime=None, macro_bias=None) -> Optional[Signal]:
        """Misma lógica que TrendMomentumStrategy.score() de v1."""
        sell = self._score_sell(ind)
        buy = self._score_buy(ind)

        best = None
        if sell["score"] >= self.config["min_score"] and sell["score"] >= buy["score"]:
            best = sell
        elif buy["score"] >= self.config["min_score"]:
            best = buy
        else:
            return None  # NEUTRAL

        return Signal(
            asset=ind.asset,
            direction=Direction(best["direction"]),
            entry_price=ind.close,
            score=best["score"],
            stop_loss=best["stop_loss"],
            take_profit=best["take_profit"],
            timeframe=ind.timeframe if hasattr(ind, "timeframe") else "1h",
            strategy=self.name,
            reasons=best["reasons"],
        )

    def _score_sell(self, ind: IndicatorSet) -> dict:
        score = 0
        reasons = []

        if ind.ema20 < ind.ema50 * 0.995:
            score += 25
            reasons.append("EMA_BEAR_CROSS")
            if ind.ema20 < ind.ema50 * 0.99:
                score += 10
                reasons.append("STRONG_BEAR_TREND")

        if ind.close < ind.ema20:
            score += 15
            reasons.append("PRICE_BELOW_EMA20")

        if ind.asset == "ETH":
            rsi_bear_low, rsi_bear_high, rsi_os_guard = 25, 50, 25
        else:
            rsi_bear_low, rsi_bear_high, rsi_os_guard = 30, 50, 30
        if rsi_bear_low <= ind.rsi <= rsi_bear_high:
            score += 20
            reasons.append(f"RSI_BEAR_ZONE:{ind.rsi:.1f}")
        elif ind.rsi < rsi_os_guard:
            score -= 15
            reasons.append("RSI_TOO_LOW_BOUNCE_RISK")

        if ind.macd < ind.macd_signal and ind.macd_hist < 0:
            score += 15
            reasons.append("MACD_BEARISH")

        if ind.vol_ratio > 1.2:
            score += 10
            reasons.append(f"VOL_CONFIRM:{ind.vol_ratio:.2f}x")

        if ind.bb_pct > 0.7:
            score += 10
            reasons.append("NEAR_BB_UPPER")

        profile = get_profile(ind.asset)
        sl_mult = profile.sl_multiplier
        tp_mult = profile.tp_multiplier

        return {
            "direction": "SELL",
            "score": max(score, 0),
            "reasons": reasons,
            "stop_loss": ind.close + (sl_mult * ind.atr),
            "take_profit": ind.close - (tp_mult * ind.atr),
        }

    def _score_buy(self, ind: IndicatorSet) -> dict:
        score = 0
        reasons = []

        if ind.ema20 > ind.ema50 * 1.005:
            score += 25
            reasons.append("EMA_BULL_CROSS")
            if ind.ema20 > ind.ema50 * 1.012:
                score += 10
                reasons.append("STRONG_BULL_TREND")

        if ind.close > ind.ema20:
            score += 15
            reasons.append("PRICE_ABOVE_EMA20")

        if 45 <= ind.rsi <= 65:
            score += 20
            reasons.append(f"RSI_MOMENTUM_ZONE:{ind.rsi:.1f}")
        elif ind.rsi > 68:
            score -= 15
            reasons.append("RSI_OVERBOUGHT")

        if ind.macd > ind.macd_signal and ind.macd_hist > 0:
            score += 15
            reasons.append("MACD_BULLISH")

        if ind.vol_ratio > 1.2:
            score += 10
            reasons.append(f"VOL_CONFIRM:{ind.vol_ratio:.2f}x")

        if ind.bb_pct < 0.70:
            score += 10
            reasons.append("ROOM_TO_BB_UPPER")

        if ind.close > ind.vwap:
            score += 8
            reasons.append("ABOVE_VWAP")

        profile = get_profile(ind.asset)
        sl_mult = profile.sl_multiplier
        tp_mult = profile.tp_multiplier

        return {
            "direction": "BUY",
            "score": max(score, 0),
            "reasons": reasons,
            "stop_loss": ind.close - (sl_mult * ind.atr),
            "take_profit": ind.close + (tp_mult * ind.atr),
        }

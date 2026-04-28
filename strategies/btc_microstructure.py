"""
BtcMicrostructureStrategy — BTC Microstructure Multi-indicator v2
==================================================================
Reverse-engineered from: suislanchez/polymarket-kalshi-weather-bot (156*)

v2 tuning (2026-04-25):
  - MIN_SCORE 60 -> 72
  - Convergencia >=3 -> >=4
  - RSI BUY 45-65 -> 50-62 / SELL 35-55 -> 38-52
  - VWAP tolerance 0-1.5% -> 0-0.8%
  - BB% BUY 0.30-0.65 -> 0.35-0.62 / SELL 0.35-0.70 -> 0.38-0.65
"""
from agents.indicators import IndicatorSet
from core.asset_profiles import get_profile


class BtcMicrostructureStrategy:
    NAME = "BTC_MICROSTRUCTURE"
    MIN_SCORE = 72

    def score(self, ind: IndicatorSet, df=None) -> dict:
        buy = self._score_buy(ind, df)
        sell = self._score_sell(ind, df)

        if sell["score"] >= self.MIN_SCORE and sell["score"] >= buy["score"]:
            return sell
        if buy["score"] >= self.MIN_SCORE:
            return buy

        best = sell if sell["score"] >= buy["score"] else buy
        return {"direction": "NEUTRAL", "score": best["score"], "reasons": best["reasons"]}

    def _score_buy(self, ind: IndicatorSet, df=None) -> dict:
        score = 0
        reasons = []
        convergence = 0
        profile = get_profile(ind.asset)

        # Indicador 1: RSI zona alcista 50-62 (v2)
        if 50 <= ind.rsi <= 62:
            score += 20
            reasons.append(f"RSI_BULL_ZONE:{ind.rsi:.1f}")
            convergence += 1
        elif ind.rsi < 35:
            score += 10
            reasons.append(f"RSI_OVERSOLD_BOUNCE:{ind.rsi:.1f}")
            convergence += 1

        # Indicador 2: Momentum multiperiodo 5/15 velas
        if df is not None and len(df) >= 16:
            try:
                mom_short = (df["close"].iloc[-1] - df["close"].iloc[-6]) / df["close"].iloc[-6]
                mom_mid = (df["close"].iloc[-1] - df["close"].iloc[-16]) / df["close"].iloc[-16]
                if mom_short > 0.001 and mom_mid > 0:
                    score += 20
                    reasons.append(f"MOMENTUM_BULL:s={mom_short:.3f},m={mom_mid:.3f}")
                    convergence += 1
                elif mom_short > 0 and mom_mid > -0.01:
                    score += 8
                    reasons.append("MOMENTUM_WEAK_BULL")
                    convergence += 0.5
            except Exception:
                pass
        else:
            if ind.macd > 0 and ind.macd_hist > 0:
                score += 15
                reasons.append("MACD_BULL_PROXY")
                convergence += 1

        # Indicador 3: VWAP Deviation 0-0.8% (v2)
        vwap_dev = (ind.close - ind.ema50) / (ind.ema50 + 1e-9)
        if 0 <= vwap_dev <= 0.008:
            score += 15
            reasons.append(f"VWAP_ABOVE_FAIR:{vwap_dev:.3f}")
            convergence += 1
        elif -0.005 <= vwap_dev < 0:
            score += 6
            reasons.append(f"VWAP_NEAR_FAIR:{vwap_dev:.3f}")
            convergence += 0.5

        # Indicador 4: SMA Crossover EMA20 > EMA50
        if ind.ema20 > ind.ema50:
            score += 15
            reasons.append("SMA_BULL_CROSS")
            convergence += 1

        # Indicador 5: BB 0.35-0.62 (v2)
        if 0.35 <= ind.bb_pct <= 0.62:
            score += 15
            reasons.append(f"SKEW_BULL_BB:{ind.bb_pct:.2f}")
            convergence += 1

        # Bonus convergencia >=4 (v2: mas exigente)
        if convergence >= 4:
            score += 15
            reasons.append(f"CONVERGENCE:{convergence:.0f}/5")
        elif convergence >= 3:
            score += 5
            reasons.append(f"CONVERGENCE_WEAK:{convergence:.0f}/5")

        if ind.vol_ratio > 1.2:
            score += 10
            reasons.append(f"VOL_CONFIRM:{ind.vol_ratio:.2f}x")

        sl_mult = profile.sl_multiplier
        tp_mult = profile.tp_multiplier

        return {
            "direction": "BUY",
            "score": max(score, 0),
            "reasons": reasons,
            "stop_loss": ind.close - (sl_mult * ind.atr),
            "take_profit": ind.close + (tp_mult * ind.atr),
        }

    def _score_sell(self, ind: IndicatorSet, df=None) -> dict:
        score = 0
        reasons = []
        convergence = 0
        profile = get_profile(ind.asset)

        # Indicador 1: RSI zona bajista 38-52 (v2)
        if 38 <= ind.rsi <= 52:
            score += 20
            reasons.append(f"RSI_BEAR_ZONE:{ind.rsi:.1f}")
            convergence += 1
        elif ind.rsi > 65:
            score += 10
            reasons.append(f"RSI_OVERBOUGHT_FADE:{ind.rsi:.1f}")
            convergence += 1

        # Indicador 2: Momentum negativo
        if df is not None and len(df) >= 16:
            try:
                mom_short = (df["close"].iloc[-1] - df["close"].iloc[-6]) / df["close"].iloc[-6]
                mom_mid = (df["close"].iloc[-1] - df["close"].iloc[-16]) / df["close"].iloc[-16]
                if mom_short < -0.001 and mom_mid < 0:
                    score += 20
                    reasons.append(f"MOMENTUM_BEAR:s={mom_short:.3f},m={mom_mid:.3f}")
                    convergence += 1
            except Exception:
                pass
        else:
            if ind.macd < 0 and ind.macd_hist < 0:
                score += 15
                reasons.append("MACD_BEAR_PROXY")
                convergence += 1

        # Indicador 3: VWAP Deviation bajista 0-0.8% (v2)
        vwap_dev = (ind.close - ind.ema50) / (ind.ema50 + 1e-9)
        if -0.008 <= vwap_dev < 0:
            score += 15
            reasons.append(f"VWAP_BELOW_FAIR:{vwap_dev:.3f}")
            convergence += 1

        # Indicador 4: SMA Cross bajista
        if ind.ema20 < ind.ema50:
            score += 15
            reasons.append("SMA_BEAR_CROSS")
            convergence += 1

        # Indicador 5: BB 0.38-0.65 (v2)
        if 0.38 <= ind.bb_pct <= 0.65:
            score += 15
            reasons.append(f"SKEW_BEAR_BB:{ind.bb_pct:.2f}")
            convergence += 1

        # Bonus convergencia >=4 (v2)
        if convergence >= 4:
            score += 15
            reasons.append(f"CONVERGENCE:{convergence:.0f}/5")
        elif convergence >= 3:
            score += 5
            reasons.append(f"CONVERGENCE_WEAK:{convergence:.0f}/5")

        if ind.vol_ratio > 1.2:
            score += 10
            reasons.append(f"VOL_CONFIRM:{ind.vol_ratio:.2f}x")

        sl_mult = profile.sl_multiplier
        tp_mult = profile.tp_multiplier

        return {
            "direction": "SELL",
            "score": max(score, 0),
            "reasons": reasons,
            "stop_loss": ind.close + (sl_mult * ind.atr),
            "take_profit": ind.close - (tp_mult * ind.atr),
        }

"""
SmcOrderBlocksStrategy — Smart Money Concepts (ICT)
====================================================
Reverse-engineered from: joshyattridge/smart-money-concepts (1590⭐)

Lógica:
  - Identifica Break of Structure (BOS) o Change of Character (CHoCH)
  - Detecta Order Blocks (última vela bajista antes de impulso alcista / viceversa)
  - Detecta Fair Value Gaps (FVG): gap de 3 velas sin solapamiento
  - Entra cuando precio vuelve al OB o FVG en dirección del BOS
  - SL debajo/encima del Order Block
  - TP en siguiente nivel de liquidez (~2.5 ATR)

Adaptado para el interfaz estándar IndicatorSet + score().
"""
from agents.indicators import IndicatorSet
from core.asset_profiles import get_profile


class SmcOrderBlocksStrategy:
    NAME = "SMC_ORDER_BLOCKS"
    MIN_SCORE = 60

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
        profile = get_profile(ind.asset)

        # ── 1. Estructura alcista: EMA20 > EMA50 (tendencia mayor BUY) ──
        if ind.ema20 > ind.ema50 * 1.001:
            score += 20
            reasons.append("SMC_BULL_STRUCTURE")

        # ── 2. BOS alcista proxy: precio rompe sobre EMA20 desde abajo ──
        if ind.close > ind.ema20 and ind.close > ind.ema50:
            score += 15
            reasons.append("BOS_BULLISH")

        # ── 3. Fair Value Gap proxy: precio está en zona de inefficiency ──
        # Bullish FVG: vela[-3].high < vela[-1].low (gap entre la primera y la tercera vela del patrón)
        # Se comprueba que el precio actual está cerca del midpoint del FVG.
        if df is not None and len(df) >= 3:
            try:
                prev_high = df["high"].iloc[-3]
                fvg_low = df["low"].iloc[-1]   # tercera vela del patrón FVG (no la del medio)
                # Bullish FVG: gap entre vela[-3].high y vela[-1].low
                if fvg_low > prev_high:
                    fvg_mid = (prev_high + fvg_low) / 2
                    if abs(ind.close - fvg_mid) < ind.atr * 0.5:
                        score += 25
                        reasons.append("FVG_BULLISH_FILL")
            except Exception:
                pass

        # ── 4. Order Block proxy: retroceso a zona de soporte (EMA20 ± 0.5 ATR) ──
        ob_level = ind.ema20
        if ob_level - 0.5 * ind.atr <= ind.close <= ob_level + 0.3 * ind.atr:
            score += 20
            reasons.append("OB_BULLISH_RETEST")

        # ── 5. RSI no en sobrecompra (zona válida de entrada en OB) ──
        if 35 <= ind.rsi <= 60:
            score += 10
            reasons.append(f"RSI_OB_ZONE:{ind.rsi:.1f}")
        elif ind.rsi < 35:
            score += 5
            reasons.append(f"RSI_OVERSOLD_OB:{ind.rsi:.1f}")

        # ── 6. Volumen de confirmación ──
        if ind.vol_ratio > 1.15:
            score += 10
            reasons.append(f"VOL_CONFIRM:{ind.vol_ratio:.2f}x")

        sl_mult = profile.sl_multiplier
        tp_mult = profile.tp_multiplier * 1.2  # SMC apunta a niveles más altos

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
        profile = get_profile(ind.asset)

        # ── 1. Estructura bajista ──
        if ind.ema20 < ind.ema50 * 0.999:
            score += 20
            reasons.append("SMC_BEAR_STRUCTURE")

        # ── 2. BOS bajista ──
        if ind.close < ind.ema20 and ind.close < ind.ema50:
            score += 15
            reasons.append("BOS_BEARISH")

        # ── 3. Bearish FVG proxy ──
        # Bearish FVG: vela[-3].low > vela[-1].high (gap entre la primera y la tercera vela)
        if df is not None and len(df) >= 3:
            try:
                prev_low = df["low"].iloc[-3]
                fvg_high = df["high"].iloc[-1]   # tercera vela del patrón FVG (no la del medio)
                if fvg_high < prev_low:
                    fvg_mid = (prev_low + fvg_high) / 2
                    if abs(ind.close - fvg_mid) < ind.atr * 0.5:
                        score += 25
                        reasons.append("FVG_BEARISH_FILL")
            except Exception:
                pass

        # ── 4. Bearish OB retest ──
        ob_level = ind.ema20
        if ob_level - 0.3 * ind.atr <= ind.close <= ob_level + 0.5 * ind.atr:
            score += 20
            reasons.append("OB_BEARISH_RETEST")

        # ── 5. RSI no en sobreventa ──
        if 40 <= ind.rsi <= 65:
            score += 10
            reasons.append(f"RSI_OB_ZONE:{ind.rsi:.1f}")

        # ── 6. Volumen ──
        if ind.vol_ratio > 1.15:
            score += 10
            reasons.append(f"VOL_CONFIRM:{ind.vol_ratio:.2f}x")

        sl_mult = profile.sl_multiplier
        tp_mult = profile.tp_multiplier * 1.2

        return {
            "direction": "SELL",
            "score": max(score, 0),
            "reasons": reasons,
            "stop_loss": ind.close + (sl_mult * ind.atr),
            "take_profit": ind.close - (tp_mult * ind.atr),
        }

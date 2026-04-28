"""
PullbackStateMachineStrategy — Máquina de estados 4 fases
==========================================================
Reverse-engineered from: ilahuerta-IA/backtrader-pullback-window-xauusd (46⭐)
Resultados reportados: Sharpe 0.89 | PF 1.64 | WR 55.43% | DD 5.81% | +44.75% en 5 años

Lógica de 4 fases:
  FASE 1 - SCAN:    Identificar tendencia dominante via EMA cruzado
  FASE 2 - WAIT:    Esperar retroceso hacia zona EMA / soporte dinámico
  FASE 3 - CONFIRM: Confirmar con momentum y patrón de vela (engulfing/hammer)
  FASE 4 - ENTER:   Entrar con ventana de tiempo (no sobreextendido)

Adaptado para el interfaz estándar IndicatorSet + score().
"""
from agents.indicators import IndicatorSet
from core.asset_profiles import get_profile


class PullbackStateMachineStrategy:
    NAME = "PULLBACK_STATE_MACHINE"
    MIN_SCORE = 80  # Alto threshold — estrategia selectiva, no un scalper

    def score(self, ind: IndicatorSet, df=None) -> dict:
        # Estrategia BUY-only — reverse-engineered de repo XAUUSD que sólo va largo
        buy = self._score_buy(ind, df)
        if buy["score"] >= self.MIN_SCORE:
            return buy
        return {"direction": "NEUTRAL", "score": buy["score"], "reasons": buy["reasons"]}

    def _score_buy(self, ind: IndicatorSet, df=None) -> dict:
        score = 0
        reasons = []
        profile = get_profile(ind.asset)

        # ── FASE 1: SCAN — Tendencia alcista (EMA alineadas) ──────────────────
        if ind.ema20 > ind.ema50:
            score += 25
            reasons.append("PHASE1_BULL_TREND")
            if ind.ema50 > getattr(ind, "ema200", ind.ema50):
                score += 10
                reasons.append("PHASE1_EMA200_BULL")
        else:
            # Sin tendencia → no operar pullback
            return {"direction": "NEUTRAL", "score": 0, "reasons": ["NO_BULL_TREND"]}

        # ── FASE 2: WAIT — Retroceso hacia EMA20 ─────────────────────────────
        # Precio debe haber bajado y estar cerca de EMA20
        ema20_dist = (ind.close - ind.ema20) / (ind.atr + 1e-9)
        if -1.0 <= ema20_dist <= 0.5:
            score += 20
            reasons.append(f"PHASE2_PULLBACK_TO_EMA:{ema20_dist:.2f}atr")
        elif ema20_dist > 2.0:
            # Precio muy extendido — esperar retroceso
            score -= 15
            reasons.append("PHASE2_OVEREXTENDED")

        # ── FASE 3: CONFIRM — Momentum y patrón de vela ──────────────────────
        # RSI recuperando desde zona de sobreventa (40-55)
        if 38 <= ind.rsi <= 55:
            score += 20
            reasons.append(f"PHASE3_RSI_RECOVERY:{ind.rsi:.1f}")
        elif ind.rsi < 35:
            score += 10
            reasons.append(f"PHASE3_RSI_OVERSOLD:{ind.rsi:.1f}")

        # MACD comenzando a recuperar
        if ind.macd_hist > 0 or (ind.macd > ind.macd * 0.98 and ind.macd_hist > -0.001):
            score += 15
            reasons.append("PHASE3_MACD_RECOVERING")

        # Hammer/bullish candle proxy: vela verde con sombra inferior grande
        if df is not None and len(df) >= 2:
            try:
                last = df.iloc[-1]
                body = abs(last["close"] - last["open"])
                lower_shadow = last["open"] - last["low"] if last["close"] > last["open"] else last["close"] - last["low"]
                if lower_shadow > body * 1.5 and last["close"] > last["open"]:
                    score += 10
                    reasons.append("PHASE3_HAMMER_CANDLE")
            except Exception:
                pass

        # ── FASE 4: ENTER — Ventana válida (no sobreextendido en tiempo) ─────
        # BB no en extremo superior
        if ind.bb_pct < 0.75:
            score += 10
            reasons.append(f"PHASE4_BB_OK:{ind.bb_pct:.2f}")

        # Volumen confirma entrada
        if ind.vol_ratio > 1.1:
            score += 10
            reasons.append(f"PHASE4_VOL:{ind.vol_ratio:.2f}x")

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
        profile = get_profile(ind.asset)

        # ── FASE 1: Tendencia bajista ──────────────────────────────────────────
        if ind.ema20 < ind.ema50:
            score += 25
            reasons.append("PHASE1_BEAR_TREND")
        else:
            return {"direction": "NEUTRAL", "score": 0, "reasons": ["NO_BEAR_TREND"]}

        # ── FASE 2: Retroceso hacia EMA20 (desde abajo) ───────────────────────
        ema20_dist = (ind.ema20 - ind.close) / (ind.atr + 1e-9)
        if -0.5 <= ema20_dist <= 1.0:
            score += 20
            reasons.append(f"PHASE2_BEAR_PULLBACK:{ema20_dist:.2f}atr")
        elif ema20_dist > 2.0:
            score -= 15
            reasons.append("PHASE2_OVEREXTENDED_DOWN")

        # ── FASE 3: RSI bajando desde zona de sobrecompra (45-62) ─────────────
        if 45 <= ind.rsi <= 62:
            score += 20
            reasons.append(f"PHASE3_RSI_BEARISH:{ind.rsi:.1f}")
        elif ind.rsi > 65:
            score += 10
            reasons.append(f"PHASE3_RSI_OB:{ind.rsi:.1f}")

        # MACD entrando negativo
        if ind.macd_hist < 0:
            score += 15
            reasons.append("PHASE3_MACD_BEARISH")

        # Shooting star proxy: vela roja con sombra superior grande
        if df is not None and len(df) >= 2:
            try:
                last = df.iloc[-1]
                body = abs(last["close"] - last["open"])
                upper_shadow = last["high"] - last["open"] if last["close"] < last["open"] else last["high"] - last["close"]
                if upper_shadow > body * 1.5 and last["close"] < last["open"]:
                    score += 10
                    reasons.append("PHASE3_SHOOTING_STAR")
            except Exception:
                pass

        # ── FASE 4: BB no en extremo inferior ─────────────────────────────────
        if ind.bb_pct > 0.25:
            score += 10
            reasons.append(f"PHASE4_BB_OK:{ind.bb_pct:.2f}")

        if ind.vol_ratio > 1.1:
            score += 10
            reasons.append(f"PHASE4_VOL:{ind.vol_ratio:.2f}x")

        sl_mult = profile.sl_multiplier
        tp_mult = profile.tp_multiplier

        return {
            "direction": "SELL",
            "score": max(score, 0),
            "reasons": reasons,
            "stop_loss": ind.close + (sl_mult * ind.atr),
            "take_profit": ind.close - (tp_mult * ind.atr),
        }

"""
MeanReversionStrategy — Compra pullbacks técnicos en tendencias alcistas.

Modo 1 — PULLBACK BUY en TREND_UP (principal, cualquier crypto):
    En mercados alcistas (EMA20 > EMA50), compra correcciones donde RSI
    cae a zona de sobreventa (25-45) y precio se acerca al BB_lower.
    Target: BB_middle (reversión a la media). SL: 1.5 ATR.
    Rationale: BTC/ETH/SOL en bull macro tienen correcciones del 5-15%
    que revierten — este modo captura esas entradas que TREND_MOMENTUM
    no puede (porque exige precio sobre EMA20 y RSI>45).

Modo 2 — OVERSOLD BUY en RANGE (secundario, XAU/XAG):
    Para metales tokenizados en mercados laterales sin tendencia clara.
    Exige sobreventa extrema (RSI<32) y baja volatilidad.
"""
from agents.indicators import IndicatorSet


class MeanReversionStrategy:
    NAME = 'MEAN_REVERSION'
    MIN_SCORE = 65
    INTERNAL_MIN_RR = 1.5  # Target corto (BB_middle), RR menor que en TREND_MOMENTUM

    def score(self, ind: IndicatorSet, df=None) -> dict:
        # Modo 1: Pullback BUY cuando la tendencia macro es alcista
        if ind.ema20 > ind.ema50:
            return self._score_pullback_buy(ind)

        # Modo 2: XAU/XAG oversold en RANGE
        if ind.asset in ('XAU', 'XAG'):
            return self._score_metals_oversold(ind)

        return {'direction': 'NEUTRAL', 'score': 0, 'reasons': ['NO_MODE']}

    def _score_pullback_buy(self, ind: IndicatorSet) -> dict:
        """Compra técnica en pullback dentro de tendencia alcista mayor."""
        score = 0
        reasons = []

        # ── Abortar si hay quiebre de tendencia alcista ──
        ema_drop = (ind.ema50 - ind.ema20) / ind.ema50 if ind.ema50 > 0 else 0
        if ema_drop > 0.015:
            return {'direction': 'NEUTRAL', 'score': 0, 'reasons': ['TREND_BREAK_ABORT']}

        # ── RSI: sobreventa (pullback válido) — NO es momentum ──
        if ind.rsi < 30:
            score += 35
            reasons.append(f'RSI_EXTREME_PULLBACK:{ind.rsi:.1f}')
        elif ind.rsi < 38:
            score += 25
            reasons.append(f'RSI_OVERSOLD:{ind.rsi:.1f}')
        elif ind.rsi < 45:
            score += 10
            reasons.append(f'RSI_MILD_PULLBACK:{ind.rsi:.1f}')
        else:
            # RSI alto: es momentum, no pullback — dejar a TREND_MOMENTUM
            return {'direction': 'NEUTRAL', 'score': 0, 'reasons': ['RSI_NOT_PULLBACK']}

        # ── Precio cerca del BB inferior (zona de soporte estadístico) ──
        if ind.bb_pct < 0.10:
            score += 30
            reasons.append(f'AT_BB_LOWER:{ind.bb_pct:.3f}')
        elif ind.bb_pct < 0.25:
            score += 20
            reasons.append(f'NEAR_BB_LOWER:{ind.bb_pct:.3f}')
        elif ind.bb_pct < 0.40:
            score += 8
            reasons.append(f'BB_MID_LOWER:{ind.bb_pct:.3f}')

        # ── Tendencia macro intacta (EMA20 > EMA50 con margen) ──
        ema_gap_pct = (ind.ema20 - ind.ema50) / ind.ema50 if ind.ema50 > 0 else 0
        if ema_gap_pct > 0.005:
            score += 15
            reasons.append('STRONG_MACRO_UP')
        else:
            score += 5
            reasons.append('WEAK_MACRO_UP')

        # ── Precio sobre EMA200 (tendencia estructural de largo plazo) ──
        if ind.close > ind.ema200 * 0.98:
            score += 10
            reasons.append('ABOVE_EMA200')
        else:
            score -= 20
            reasons.append('BELOW_EMA200_RISK')

        # ── Verificar R:R: target = BB_middle, SL = 1.5 ATR ──
        target = ind.bb_middle
        reward = target - ind.close
        risk   = 1.5 * ind.atr

        if risk <= 0 or reward <= 0:
            return {'direction': 'NEUTRAL', 'score': 0, 'reasons': [*reasons, 'NO_REWARD']}

        rr = reward / risk
        if rr < self.INTERNAL_MIN_RR:
            return {
                'direction': 'NEUTRAL',
                'score': max(score - 20, 0),
                'reasons': [*reasons, f'LOW_RR:{rr:.2f}'],
            }

        score += min(int(rr * 5), 10)  # bonus R:R alto, máx +10
        reasons.append(f'RR:{rr:.2f}')

        if score >= self.MIN_SCORE:
            return {
                'direction': 'BUY',
                'score': score,
                'reasons': reasons,
                'stop_loss':   ind.close - risk,
                'take_profit': target,
                'rr_ratio':    rr,
            }
        return {'direction': 'NEUTRAL', 'score': score, 'reasons': reasons}

    def _score_metals_oversold(self, ind: IndicatorSet) -> dict:
        """Lógica original: XAU/XAG en extremo inferior de RANGE."""
        score = 0
        reasons = []

        if ind.trend_direction == 'DOWN':
            return {'direction': 'NEUTRAL', 'score': 0, 'reasons': ['DOWN_ABORT']}

        ema_drop = (ind.ema50 - ind.ema20) / ind.ema50 if ind.ema50 > 0 else 0
        if ema_drop > 0.015:
            return {'direction': 'NEUTRAL', 'score': 0, 'reasons': ['STRONG_DT_ABORT']}

        if ind.bb_pct < 0.05:
            score += 35
            reasons.append(f'BB_LOWER_EXTREME:{ind.bb_pct:.3f}')
        elif ind.bb_pct < 0.10:
            score += 20
            reasons.append('BB_LOWER_ZONE')

        if ind.rsi < 25:
            score += 30
            reasons.append(f'RSI_EXTREME:{ind.rsi:.1f}')
        elif ind.rsi < 32:
            score += 20
            reasons.append(f'RSI_OVERSOLD:{ind.rsi:.1f}')

        if ind.bb_width < 0.10:
            score += 15
            reasons.append('LOW_VOLATILITY_OK')
        elif ind.bb_width > 0.12:
            return {'direction': 'NEUTRAL', 'score': 0, 'reasons': ['HIGH_VOL_ABORT']}

        score += 10
        reasons.append(f'METAL_ASSET:{ind.asset}')

        target = ind.bb_middle
        reward = target - ind.close
        risk   = 1.5 * ind.atr
        rr = reward / risk if risk > 0 else 0

        if rr < self.INTERNAL_MIN_RR:
            return {
                'direction': 'NEUTRAL',
                'score': max(score - 20, 0),
                'reasons': [*reasons, f'LOW_RR:{rr:.2f}'],
            }

        if score >= self.MIN_SCORE:
            return {
                'direction': 'BUY',
                'score': score,
                'reasons': reasons,
                'stop_loss':   ind.close - risk,
                'take_profit': target,
                'rr_ratio':    rr,
            }
        return {'direction': 'NEUTRAL', 'score': score, 'reasons': reasons}

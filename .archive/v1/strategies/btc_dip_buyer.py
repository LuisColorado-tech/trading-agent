"""
BtcDipBuyerStrategy — Compra dips técnicos en activos en bull estructural.

Filosofía: BTC (y activos de alta correlación) en bull macro tiene compradores
estructurales (ETF, instituciones, mineros) que frenan caídas antes del overshooting.
Cada caída del 10-25% dentro de un bull (precio > EMA200) es una oportunidad de compra.

Condiciones de entrada:
1. Precio > EMA200 × 0.98 (macro bull intacto — se verifica en régimen BULL_DIP)
2. RSI < 38 en 15m (capitulación de corto plazo)
3. Precio cerca del BB inferior (bb_pct < 0.25) — soporte estadístico
4. EMA20 acepta divergencia moderada de EMA50 pero NO quiebre estructural

Target: EMA20 o BB_middle (lo que esté más cerca).
SL: 1.5 ATR por debajo del precio de entrada.
RR mínimo: 1.5 (target más corto que TREND_MOMENTUM porque es una reversión).
"""
from agents.indicators import IndicatorSet


class BtcDipBuyerStrategy:
    NAME = 'BTC_DIP_BUYER'
    MIN_SCORE = 60  # umbral menor que TREND_MOMENTUM (65) — reversiones tienen mayor incertidumbre inicial
    INTERNAL_MIN_RR = 1.5

    # Assets de alta correlación con BTC para los que aplica esta lógica
    ELIGIBLE_ASSETS = {'BTC', 'ETH', 'SOL', 'AVAX', 'LINK', 'INJ', 'AAVE', 'POL'}

    def score(self, ind: IndicatorSet, df=None) -> dict:
        if ind.asset not in self.ELIGIBLE_ASSETS:
            return {'direction': 'NEUTRAL', 'score': 0, 'reasons': ['ASSET_NOT_ELIGIBLE']}

        score = 0
        reasons = []

        # ── Filtro duro 1: macro bull estructural ──
        if ind.close < ind.ema200 * 0.96:
            # Si el precio cayó más del 4% bajo EMA200, el bull está roto
            return {'direction': 'NEUTRAL', 'score': 0, 'reasons': ['BELOW_EMA200_STRUCTURAL_BREAK']}

        # ── RSI: sobreventa de corto plazo ──
        if ind.rsi < 28:
            score += 40
            reasons.append(f'RSI_PANIC_SELL:{ind.rsi:.1f}')
        elif ind.rsi < 32:
            score += 30
            reasons.append(f'RSI_EXTREME_OVERSOLD:{ind.rsi:.1f}')
        elif ind.rsi < 38:
            score += 20
            reasons.append(f'RSI_OVERSOLD:{ind.rsi:.1f}')
        else:
            # El régimen BULL_DIP ya exige RSI<38, esto no debería ocurrir
            return {'direction': 'NEUTRAL', 'score': 0, 'reasons': ['RSI_NOT_OVERSOLD']}

        # ── Precio cerca del BB inferior (soporte estadístico) ──
        if ind.bb_pct < 0.08:
            score += 25
            reasons.append(f'AT_BB_LOWER:{ind.bb_pct:.3f}')
        elif ind.bb_pct < 0.20:
            score += 18
            reasons.append(f'NEAR_BB_LOWER:{ind.bb_pct:.3f}')
        elif ind.bb_pct < 0.35:
            score += 8
            reasons.append(f'BB_LOWER_ZONE:{ind.bb_pct:.3f}')

        # ── Profundidad del dip: distancia de la EMA20 a la EMA50 ──
        # Un dip leve (EMA20 apenas bajo EMA50) es más seguro que un quiebre total
        ema_drop_pct = (ind.ema50 - ind.ema20) / ind.ema50 if ind.ema50 > 0 else 0
        if ema_drop_pct < 0.005:
            score += 15
            reasons.append('SHALLOW_DIP_SAFE')
        elif ema_drop_pct < 0.015:
            score += 8
            reasons.append(f'MODERATE_DIP:{ema_drop_pct*100:.1f}%%')
        elif ema_drop_pct > 0.030:
            score -= 15
            reasons.append(f'DEEP_DIP_RISKY:{ema_drop_pct*100:.1f}%%')

        # ── Posición respecto a EMA200: cuanto más cerca, más fuerte el soporte ──
        dist_ema200_pct = (ind.close - ind.ema200) / ind.ema200 if ind.ema200 > 0 else 0
        if 0.0 <= dist_ema200_pct <= 0.05:
            score += 12   # precio muy cerca de EMA200: soporte fuerte, rebote probable
            reasons.append(f'NEAR_EMA200_SUPPORT:{dist_ema200_pct*100:.1f}%%')
        elif dist_ema200_pct > 0.15:
            score += 5
            reasons.append('WELL_ABOVE_EMA200')

        # ── MACD en dip (negativo = momentum bajista agotándose) ──
        if ind.macd_hist < 0 and ind.macd_hist > ind.macd_hist * 1.1:
            # MACD histograma negativo pero reduciéndose = divergencia alcista
            score += 8
            reasons.append('MACD_DIP_DIVERGENCE')
        elif ind.macd_hist < 0:
            score += 4
            reasons.append('MACD_IN_DIP')

        # ── Volumen: spike = capitulación (mejor punto de entrada) ──
        if ind.vol_ratio > 1.8:
            score += 10
            reasons.append(f'CAPITULATION_VOLUME:{ind.vol_ratio:.2f}x')
        elif ind.vol_ratio > 1.3:
            score += 5
            reasons.append(f'ELEVATED_VOLUME:{ind.vol_ratio:.2f}x')

        # ── Target: EMA20 o BB_middle, lo que esté más lejos hacia arriba ──
        target_ema20   = ind.ema20
        target_bb_mid  = ind.bb_middle
        target = max(target_ema20, target_bb_mid)

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

        score += min(int(rr * 5), 12)  # bonus por R:R, máx +12
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

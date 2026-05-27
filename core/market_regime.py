"""
Clasificación simple de régimen de mercado para filtrar estrategias.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class MarketRegime:
    name: str
    bias: str
    allow_trend: bool
    allow_mean_reversion: bool
    allow_breakout: bool
    allow_dip_buy: bool = False   # BTC Dip Buyer: BUY en pullbacks dentro de bull estructural
    allow_grid: bool = False      # Grid Bot: activo en RANGE/CHOPPY (sin tendencia clara)


# Umbral de trend_strength para activar TREND/BREAKOUT.
# Valor previo 0.18 era demasiado restrictivo: en mercados de tendencia moderada
# (ej. BTC en rally sostenido) el régimen caía siempre en CHOPPY y ambas
# estrategias quedaban bloqueadas sin operar.
_TREND_STRENGTH_MIN = 0.08   # v1.1: 0.12→0.08 (Council #2 May 21). 0.12 demasiado restrictivo en baja vol.
_TREND_STRENGTH_MIN_DOWN = 0.20  # reservado — backtest 2Y mostró que 0.20 destruye SOL (+71%→0%). No usar.


def _is_trending(ind) -> bool:
    """True si el TF muestra tendencia clara.

    Usado por el Grid Bot para confirmación multi-timeframe (1h): si el TF superior
    está en tendencia, el mercado 15m en RANGE estadístico es un "rango dentro de
    tendencia" donde el Grid acumularía posiciones en la dirección equivocada.
    Los criterios son los mismos que activan BREAKOUT/TREND en classify_market_regime.
    """
    if (ind.vol_ratio >= 2.0 and ind.atr_pct >= 0.015
            and ind.trend_strength >= _TREND_STRENGTH_MIN):
        return True
    if (ind.trend_direction == 'DOWN' and ind.trend_strength >= _TREND_STRENGTH_MIN
            and ind.macd_hist < 0):
        return True
    if (ind.trend_direction == 'UP' and ind.trend_strength >= _TREND_STRENGTH_MIN
            and ind.macd_hist > 0):
        return True
    return False


def classify_market_regime(ind, ind_htf=None) -> MarketRegime:
    if ind.vol_ratio >= 2.0 and ind.atr_pct >= 0.015 and ind.trend_strength >= _TREND_STRENGTH_MIN:
        if ind.trend_direction == 'UP':
            return MarketRegime('BREAKOUT_UP', 'BULLISH', True, False, True)
        if ind.trend_direction == 'DOWN':
            # allow_trend=False (v3): WR=29% en BREAKOUT_DOWN → -$1,590 en backtest 2Y.
            # En breakdown extremo (vol≥2x, atr≥1.5%) el edge de TREND_MOMENTUM desaparece.
            return MarketRegime('BREAKOUT_DOWN', 'BEARISH', False, False, False)

    if ind.trend_direction == 'UP' and ind.trend_strength >= _TREND_STRENGTH_MIN and ind.macd_hist > 0:
        # Backtest 2Y: TREND_MOMENTUM BUY en TREND_UP pierde -$6,151 → bloqueado.
        # MEAN_REVERSION desactivada: paper 8 trades 0 wins -$569. Pullbacks en bull
        # 15m no tienen edge estadístico suficiente en portfolio actual.
        return MarketRegime('TREND_UP', 'BULLISH', False, False, False)

    if ind.trend_direction == 'DOWN' and ind.trend_strength >= _TREND_STRENGTH_MIN and ind.macd_hist < 0:
        return MarketRegime('TREND_DOWN', 'BEARISH', True, False, False)

    # BULL_DIP deshabilitado: backtest 2Y en 15m → 29% WR, -$4,300 en BTC.
    # En timeframe 15m, RSI<38 indica venta activa que continúa más del 70% de las veces.
    # Para activar este régimen se necesitaría confirmación multi-timeframe (1h/4h) que
    # el sistema actual no implementa. Preservado para futura implementación.
    # if (ind.close > ind.ema200 * 0.98 and ind.rsi < 38
    #         and ind.ema20 >= ind.ema50 * 0.97):
    #     return MarketRegime('BULL_DIP', ...)

    if ind.bb_width <= 0.10 and ind.atr_pct <= 0.012:
        # Backtest 6m: TREND_MOMENTUM en RANGE pierde en BTC (-$880), ETH (-$829), SOL (-$1,157).
        # MEAN_REVERSION también pierde en RANGE. Solución: solo Grid Bot en RANGE.
        # MTF confirmation: si el TF superior (1h) muestra tendencia, el RANGE de 15m
        # es un pullback/consolidación dentro de una tendencia → Grid Bot bloqueado.
        if ind_htf is not None and _is_trending(ind_htf):
            return MarketRegime('CHOPPY', 'NEUTRAL', False, False, False, allow_grid=False)
        return MarketRegime('RANGE', 'NEUTRAL', False, False, False, allow_grid=True)

    # CHOPPY: ni tendencia ni rango definido → Grid Bot puede operar con tamaños reducidos
    return MarketRegime('CHOPPY', 'NEUTRAL', False, False, False, allow_grid=True)


def strategy_allowed_in_regime(strategy_name: str, regime: MarketRegime) -> bool:
    if strategy_name == 'TREND_MOMENTUM':
        return regime.allow_trend
    if strategy_name == 'MEAN_REVERSION':
        return regime.allow_mean_reversion
    if strategy_name == 'BREAKOUT':
        return regime.allow_breakout
    if strategy_name == 'BTC_DIP_BUYER':
        return regime.allow_dip_buy
    # Estrategias reverse-engineered de GitHub
    if strategy_name == 'PULLBACK_STATE_MACHINE':
        # BUY-only pullback strategy — SÓLO en régimen alcista (TREND_UP, BREAKOUT_UP)
        return regime.bias == 'BULLISH'
    if strategy_name == 'SMC_ORDER_BLOCKS':
        # Breakouts y tendencias — no en mercados laterales muy débiles
        return regime.allow_trend or regime.allow_breakout
    if strategy_name == 'BTC_MICROSTRUCTURE':
        # Multi-signal — útil en casi cualquier régimen excepto puro choppy
        return regime.allow_trend or regime.allow_breakout or regime.allow_dip_buy
    return True


def regime_block_reason(strategy_name: str, regime: MarketRegime) -> str:
    return f'REGIME_BLOCK:{strategy_name}:{regime.name}'


# ── Macro Regime — BTC como faro del mercado crypto ──

class MacroBias:
    BULL_RUN = 'BULL_RUN'
    BEAR_TREND = 'BEAR_TREND'
    RANGE = 'RANGE'


def get_macro_bias(btc_df) -> str:
    """Clasifica el régimen macro usando BTC como referencia."""
    import numpy as np
    if btc_df is None or btc_df.empty or len(btc_df) < 200:
        return MacroBias.RANGE

    # Normalizar nombres de columna (market_feed usa 'close', otros usan 'Close')
    col = 'close' if 'close' in btc_df.columns else 'Close'
    closes = btc_df[col].values
    ema200 = np.mean(closes[-200:])

    # También calcular EMA50 para confirmación
    ema50 = np.mean(closes[-50:]) if len(closes) >= 50 else ema200
    current = closes[-1]

    # Estructura de precios: últimos 20 candles
    recent = closes[-20:]
    highs = np.max(recent)
    lows = np.min(recent)
    mid = (highs + lows) / 2

    # BULL_RUN: precio sobre EMA200 + EMA50 sobre EMA200 + precio cerca de máximos
    if current > ema200 and ema50 > ema200 and current > mid:
        return MacroBias.BULL_RUN

    # BEAR_TREND: precio bajo EMA200 + EMA50 bajo EMA200 + precio cerca de mínimos
    if current < ema200 and ema50 < ema200 and current < mid:
        return MacroBias.BEAR_TREND

    return MacroBias.RANGE


def macro_position_multiplier(macro_bias: str, direction: str) -> float:
    """Ajusta el multiplicador de posición según alineación con régimen macro.

    BUY en BULL_RUN  → 1.0× (viento a favor)
    SELL en BEAR_TREND → 1.0× (viento a favor)
    Cualquier otra combinación → reducido
    """
    if macro_bias == MacroBias.BULL_RUN:
        return 1.0 if direction == 'BUY' else 0.25
    elif macro_bias == MacroBias.BEAR_TREND:
        return 1.0 if direction == 'SELL' else 0.0
    else:  # RANGE
        return 0.5 if direction == 'SELL' else 0.0
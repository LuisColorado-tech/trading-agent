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
_TREND_STRENGTH_MIN = 0.12
_TREND_STRENGTH_MIN_DOWN = 0.20  # reservado — backtest 2Y mostró que 0.20 destruye SOL (+71%→0%). No usar.


def classify_market_regime(ind) -> MarketRegime:
    if ind.vol_ratio >= 2.0 and ind.atr_pct >= 0.015 and ind.trend_strength >= _TREND_STRENGTH_MIN:
        if ind.trend_direction == 'UP':
            return MarketRegime('BREAKOUT_UP', 'BULLISH', True, False, True)
        if ind.trend_direction == 'DOWN':
            return MarketRegime('BREAKOUT_DOWN', 'BEARISH', True, False, False)

    if ind.trend_direction == 'UP' and ind.trend_strength >= _TREND_STRENGTH_MIN and ind.macd_hist > 0:
        # Backtest 2Y: TREND_MOMENTUM BUY en TREND_UP pierde -$6,151 → bloqueado.
        # MEAN_REVERSION habilitada: compra pullbacks dentro del bull.
        return MarketRegime('TREND_UP', 'BULLISH', False, True, False)

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
    return True


def regime_block_reason(strategy_name: str, regime: MarketRegime) -> str:
    return f'REGIME_BLOCK:{strategy_name}:{regime.name}'
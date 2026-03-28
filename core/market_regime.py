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


# Umbral de trend_strength para activar TREND/BREAKOUT.
# Valor previo 0.18 era demasiado restrictivo: en mercados de tendencia moderada
# (ej. BTC en rally sostenido) el régimen caía siempre en CHOPPY y ambas
# estrategias quedaban bloqueadas sin operar.
_TREND_STRENGTH_MIN = 0.12


def classify_market_regime(ind) -> MarketRegime:
    if ind.vol_ratio >= 2.0 and ind.atr_pct >= 0.015 and ind.trend_strength >= _TREND_STRENGTH_MIN:
        if ind.trend_direction == 'UP':
            return MarketRegime('BREAKOUT_UP', 'BULLISH', True, False, True)
        if ind.trend_direction == 'DOWN':
            return MarketRegime('BREAKOUT_DOWN', 'BEARISH', True, False, False)

    if ind.trend_direction == 'UP' and ind.trend_strength >= _TREND_STRENGTH_MIN and ind.macd_hist > 0:
        return MarketRegime('TREND_UP', 'BULLISH', True, False, False)

    if ind.trend_direction == 'DOWN' and ind.trend_strength >= _TREND_STRENGTH_MIN and ind.macd_hist < 0:
        return MarketRegime('TREND_DOWN', 'BEARISH', True, False, False)

    if ind.bb_width <= 0.10 and ind.atr_pct <= 0.012:
        # Backtest 6m: TREND_MOMENTUM en RANGE pierde en BTC (-$880), ETH (-$829), SOL (-$1,157).
        # El agente espera a que el mercado salga del rango antes de operar.
        # MEAN_REVERSION sigue disponible en RANGE (aunque está deshabilitada).
        return MarketRegime('RANGE', 'NEUTRAL', False, True, False)

    return MarketRegime('CHOPPY', 'NEUTRAL', False, False, False)


def strategy_allowed_in_regime(strategy_name: str, regime: MarketRegime) -> bool:
    if strategy_name == 'TREND_MOMENTUM':
        return regime.allow_trend
    if strategy_name == 'MEAN_REVERSION':
        return regime.allow_mean_reversion
    if strategy_name == 'BREAKOUT':
        return regime.allow_breakout
    return True


def regime_block_reason(strategy_name: str, regime: MarketRegime) -> str:
    return f'REGIME_BLOCK:{strategy_name}:{regime.name}'
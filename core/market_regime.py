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
_TREND_STRENGTH_MIN_DOWN = 0.20  # reservado — backtest 2Y mostró que 0.20 destruye SOL (+71%→0%). No usar.


def classify_market_regime(ind) -> MarketRegime:
    if ind.vol_ratio >= 2.0 and ind.atr_pct >= 0.015 and ind.trend_strength >= _TREND_STRENGTH_MIN:
        if ind.trend_direction == 'UP':
            return MarketRegime('BREAKOUT_UP', 'BULLISH', True, False, True)
        if ind.trend_direction == 'DOWN':
            return MarketRegime('BREAKOUT_DOWN', 'BEARISH', True, False, False)

    if ind.trend_direction == 'UP' and ind.trend_strength >= _TREND_STRENGTH_MIN and ind.macd_hist > 0:
        # Backtest 2Y: TREND_MOMENTUM BUY en TREND_UP pierde -$6,151 → bloqueado (allow_trend=False).
        # MEAN_REVERSION habilitada: compra pullbacks (RSI<45 + cerca BB_lower) dentro del bull.
        return MarketRegime('TREND_UP', 'BULLISH', False, True, False)

    if ind.trend_direction == 'DOWN' and ind.trend_strength >= _TREND_STRENGTH_MIN and ind.macd_hist < 0:
        return MarketRegime('TREND_DOWN', 'BEARISH', True, False, False)

    if ind.bb_width <= 0.10 and ind.atr_pct <= 0.012:
        # Backtest 6m: TREND_MOMENTUM en RANGE pierde en BTC (-$880), ETH (-$829), SOL (-$1,157).
        # MEAN_REVERSION también pierde en RANGE: la estrategia de pullback dispara porque EMA20>EMA50
        # por historial reciente, pero en RANGE no hay tendencia real que sostenga la reversión.
        # Solución: no operar ninguna estrategia en RANGE (esperar TREND_DOWN/UP).
        return MarketRegime('RANGE', 'NEUTRAL', False, False, False)

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
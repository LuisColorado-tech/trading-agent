"""
GridBotStrategy — Grid trading para régimen RANGE / CHOPPY.

Lógica:
  - Divide el rango reciente (últimas N velas) en niveles equidistantes
  - Niveles por encima del precio → SELL (apuesta a que baje al nivel inferior)
  - Niveles por debajo del precio → BUY (apuesta a que suba al nivel superior)
  - TP = 1.5 × grid_spacing en dirección favorable
  - SL = 0.6 × grid_spacing en dirección contraria
  - RR teórico = 1.5 / 0.6 = 2.5 × por nivel; realizado ~1.6× con slippage
  - Solo activa cuando market_regime ∈ {RANGE, CHOPPY}
  - RR mínimo 1.20 para abrir orden

Sin estado propio: GridAgent (agents/grid_agent.py) maneja el estado de
niveles abiertos y la ejecución.
"""
from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

from agents.indicators import IndicatorSet
from core.cost_model import round_trip_cost_pct, MIN_NET_RR_RATIO

# ── Parámetros ────────────────────────────────────────────────────
GRID_DEFAULT_LEVELS = 6       # niveles dentro del rango
GRID_RANGE_CANDLES  = 30      # velas para calcular el rango
GRID_BUFFER_PCT     = 0.002   # buffer extra arriba/abajo del rango (0.2%)
MIN_RANGE_PCT       = 0.008   # rango mínimo aceptable (0.8%) — si es menos no es RANGE
MAX_RANGE_PCT       = 0.10    # rango máximo aceptable (10%) — si es más es TREND disfrazado
LEVEL_TOLERANCE_PCT = 0.0010  # ±0.10% para considerar que el precio "tocó" un nivel
TP_RATIO            = 1.50    # TP = 1.5 × grid_spacing (capturas más de movimiento)
SL_BUFFER_RATIO     = 0.60    # SL = level_price + 0.60 × grid_spacing (relativo al nivel)
MIN_RR_GRID         = 1.20    # RR mínimo para abrir orden grid
# ─────────────────────────────────────────────────────────────────


@dataclass
class GridLevel:
    """Un nivel de precio dentro de la grid."""
    price: float          # precio del nivel
    direction: str        # 'SELL' (sesgo bear) o 'BUY'
    tp: float             # precio de take profit
    sl: float             # precio de stop loss
    level_idx: int        # índice 0..N dentro de la grid
    rr: float             # ratio riesgo:recompensa calculado


@dataclass
class GridConfig:
    """Configuración completa de la grid para un asset."""
    asset: str
    range_low: float
    range_high: float
    grid_spacing: float
    range_pct: float
    levels: List[GridLevel] = field(default_factory=list)


class GridBotStrategy:
    NAME = 'GRID_BOT'

    def calculate_grid(self, ind: IndicatorSet, df: pd.DataFrame,
                       n_levels: int = GRID_DEFAULT_LEVELS,
                       tp_ratio: float = TP_RATIO,
                       sl_ratio: float = SL_BUFFER_RATIO,
                       min_rr: float = MIN_RR_GRID,
                       range_candles: int = GRID_RANGE_CANDLES,
                       exchange: str = 'kraken') -> Optional[GridConfig]:
        """
        Calcula los niveles de grid basados en el rango de las últimas N velas.

        Los parámetros tp_ratio, sl_ratio, min_rr y range_candles se toman de los
        globales por defecto, pero cada asset puede pasar los valores de su AssetProfile
        (grid_tp_ratio, grid_sl_ratio, grid_min_rr, grid_range_candles) para
        comportamiento personalizado.

        Cada nivel debe además cubrir el costo real del round-trip (fee + slippage
        del exchange, core/cost_model.py): GridAgent inserta trades directo a DB sin
        pasar por RiskManager, así que este es el único gate de costos para GRID_BOT.

        Returns:
            GridConfig con todos los niveles, o None si el rango no es válido.
        """
        if len(df) < range_candles:
            return None

        recent = df.tail(range_candles)
        range_high = float(recent['high'].max())
        range_low  = float(recent['low'].min())

        if range_low <= 0:
            return None

        range_pct = (range_high - range_low) / range_low

        # Validar que el rango sea real (ni microespread ni tendencia)
        if range_pct < MIN_RANGE_PCT or range_pct > MAX_RANGE_PCT:
            return None

        # Añadir buffer para que el SL esté claramente fuera del rango
        buffered_high = range_high * (1 + GRID_BUFFER_PCT)
        buffered_low  = range_low  * (1 - GRID_BUFFER_PCT)

        grid_spacing = (buffered_high - buffered_low) / n_levels
        if grid_spacing <= 0:
            return None

        current_price = ind.close
        levels = []
        cost_pct = round_trip_cost_pct(exchange)

        for i in range(n_levels + 1):
            level_price = buffered_low + i * grid_spacing

            # SELL: niveles por encima del precio actual (apuesta a que baje)
            if level_price > current_price * (1 + LEVEL_TOLERANCE_PCT * 0.5):
                tp  = level_price - grid_spacing * tp_ratio
                sl  = level_price + grid_spacing * sl_ratio
                risk_per_unit   = abs(level_price - sl)
                reward_per_unit = abs(level_price - tp)
                if risk_per_unit < 1e-10:
                    continue
                rr = reward_per_unit / risk_per_unit
                net_rr = (reward_per_unit / level_price - cost_pct) / (risk_per_unit / level_price)
                if rr >= min_rr and net_rr >= MIN_NET_RR_RATIO:
                    levels.append(GridLevel(
                        price=round(level_price, 8),
                        direction='SELL',
                        tp=round(tp, 8),
                        sl=round(sl, 8),
                        level_idx=i,
                        rr=round(rr, 3),
                    ))

            # BUY: niveles por debajo del precio actual (apuesta a que suba)
            elif level_price < current_price * (1 - LEVEL_TOLERANCE_PCT * 0.5):
                tp  = level_price + grid_spacing * tp_ratio    # TP arriba del nivel
                sl  = level_price - grid_spacing * sl_ratio    # SL abajo del nivel
                risk_per_unit   = abs(level_price - sl)
                reward_per_unit = abs(level_price - tp)
                if risk_per_unit < 1e-10:
                    continue
                rr = reward_per_unit / risk_per_unit
                net_rr = (reward_per_unit / level_price - cost_pct) / (risk_per_unit / level_price)
                if rr >= min_rr and net_rr >= MIN_NET_RR_RATIO:
                    levels.append(GridLevel(
                        price=round(level_price, 8),
                        direction='BUY',
                        tp=round(tp, 8),
                        sl=round(sl, 8),
                        level_idx=i,
                        rr=round(rr, 3),
                    ))

        if not levels:
            return None

        return GridConfig(
            asset=ind.asset,
            range_low=buffered_low,
            range_high=buffered_high,
            grid_spacing=round(grid_spacing, 8),
            range_pct=round(range_pct, 6),
            levels=levels,
        )

    def nearest_level(self, grid: GridConfig, current_price: float) -> Optional[GridLevel]:
        """
        Retorna el nivel de grid más cercano al precio actual (dentro de tolerancia).
        None si ningún nivel está suficientemente cerca.
        """
        best_level = None
        best_dist  = float('inf')

        for level in grid.levels:
            dist_pct = abs(current_price - level.price) / level.price
            if dist_pct <= LEVEL_TOLERANCE_PCT and dist_pct < best_dist:
                best_dist  = dist_pct
                best_level = level

        return best_level

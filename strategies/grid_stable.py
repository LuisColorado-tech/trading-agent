"""
GridStableStrategy — Grid trading para pares de baja volatilidad.

Extiende GridBotStrategy con parámetros específicos por par desde
GridStableProfile. Diseñado para ETH/BTC, LINK/BTC donde el rango
es más predecible y las comisiones son menores.

Diferencias clave vs GridBotStrategy:
  - Más niveles (8-10 vs 6): captura micro-oscilaciones
  - TP/SL más ceñidos (1.2×/0.4× vs 1.5×/0.6×): rango más estrecho
  - Rango máximo 3-5% (vs 10%): filtra falsos RANGE en tendencia
  - Mayor exigencia de RR mínimo (1.5 vs 1.2): compensa comisiones
  - Sin buffer de precio (ya que el rango es naturalmente estrecho)
"""
from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

from agents.indicators import IndicatorSet
from strategies.grid_bot import GridLevel


@dataclass
class GridStableConfig:
    """Configuración completa de la grid estable para un par."""
    pair: str
    levels: List[GridLevel] = field(default_factory=list)
    low: float = 0.0
    high: float = 0.0
    spacing: float = 0.0
    range_pct: float = 0.0
    bars_in_range: int = 0


class GridStableStrategy:
    """Estrategia de grid para pares estables."""

    NAME = 'GRID_STABLE'

    def __init__(self, profile):
        """
        Args:
            profile: GridStableProfile con parámetros por par.
        """
        self.profile = profile

    def build_grid(self, df: pd.DataFrame, ind: IndicatorSet) -> Optional[GridStableConfig]:
        """Construye una grid de niveles si el par está en rango.

        Args:
            df: DataFrame con velas OHLCV
            ind: indicadores calculados

        Returns:
            GridStableConfig o None si no hay condiciones de rango.
        """
        p = self.profile
        n = min(p.grid_range_candles, len(df))

        recent = df.iloc[-n:]
        low = float(recent['low'].min())
        high = float(recent['high'].max())
        range_pct = (high - low) / low

        # Filtro: rango debe estar entre min y max
        if range_pct < p.min_range_pct or range_pct > p.max_range_pct:
            return None

        # Verificar que el precio no rompió el rango en las últimas velas
        bars_in_range = int((recent['high'] <= high * 1.002).sum())

        # Contar velas donde el precio se mantuvo dentro del rango
        in_range = (
            (recent['high'] <= high * (1 + p.level_tolerance_pct)) &
            (recent['low'] >= low * (1 - p.level_tolerance_pct))
        ).sum()
        if in_range < p.min_bars_in_range:
            return None

        # Espaciado de niveles
        spacing = (high - low) / (p.grid_levels + 1)

        # Generar niveles
        levels = []
        for i in range(1, p.grid_levels + 1):
            level_price = low + i * spacing

            # Solo SELL (mismo sesgo bear del sistema)
            tp = level_price * (1 - spacing / level_price * p.tp_ratio)
            sl = level_price * (1 + spacing / level_price * p.sl_ratio)
            rr = (level_price - tp) / (sl - level_price) if (sl - level_price) > 0 else 0

            if rr >= p.min_rr:
                levels.append(GridLevel(
                    price=round(level_price, 8),
                    direction='SELL',
                    tp=round(tp, 8),
                    sl=round(sl, 8),
                    level_idx=i,
                    rr=round(rr, 3),
                ))

        if not levels:
            return None

        return GridStableConfig(
            pair=p.pair,
            levels=levels,
            low=round(low, 8),
            high=round(high, 8),
            spacing=round(spacing, 8),
            range_pct=round(range_pct * 100, 3),
            bars_in_range=bars_in_range,
        )

    def find_nearest_level(self, price: float, config: GridStableConfig) -> Optional[GridLevel]:
        """Encuentra el nivel más cercano al precio actual."""
        p = self.profile
        best = None
        best_dist = float('inf')

        for level in config.levels:
            dist = abs(price - level.price) / level.price
            if dist <= p.level_tolerance_pct and dist < best_dist:
                best = level
                best_dist = dist

        return best

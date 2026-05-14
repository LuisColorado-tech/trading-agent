"""
KalshiArbitrageStrategy — Arbitraje cross-platform Polymarket ↔ Kalshi.

Matemática del arbitraje sin riesgo:
  - Polymarket: comprar UP (paga $1 si BTC sube) o DOWN (paga $1 si BTC baja)
  - Kalshi: comprar YES (paga $1 si BTC > strike) o NO (paga $1 si BTC <= strike)
  
  Estrategia A: Poly_Down + Kalshi_Yes
    Si BTC > strike → Kalshi gana $1, Poly pierde $0
    Si BTC <= strike → Poly gana $1, Kalshi pierde $0
    Costo = price_poly_down + price_kalshi_yes
    Profit = 1.0 - costo → garantizado si costo < 1.0

  Estrategia B: Poly_Up + Kalshi_No
    Si BTC > strike → Poly gana $1, Kalshi pierde $0
    Si BTC <= strike → Kalshi gana $1, Poly pierde $0
    Costo = price_poly_up + price_kalshi_no
    Profit = 1.0 - costo → garantizado si costo < 1.0

Condición de entrada: costo total < 0.995 (0.5% profit mínimo después de fees/spread)
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class ArbitrageSignal:
    strategy: str                       # 'A' (Poly Down + Kalshi Yes) o 'B' (Poly Up + Kalshi No)
    poly_event_slug: str
    poly_token: str                     # 'up' o 'down'
    poly_price: float
    kalshi_market_ticker: str
    kalshi_side: str                    # 'yes' o 'no'
    kalshi_price: float
    total_cost: float                   # poly_price + kalshi_price
    profit_per_unit: float              # 1.0 - total_cost
    profit_pct: float                   # (1.0 - total_cost) / total_cost * 100
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def is_arbitrage(self) -> bool:
        return self.total_cost < 0.995  # Al menos 0.5% de profit después de fees


class KalshiArbitrageStrategy:
    """Detecta oportunidades de arbitraje sin riesgo Polymarket ↔ Kalshi."""

    NAME = 'KALSHI_ARBITRAGE'
    MIN_PROFIT_PCT = 0.5        # Profit mínimo 0.5% para ejecutar
    MAX_COST = 0.995            # Costo total máximo (1.0 - 0.005 = 0.995)
    POSITION_SIZE_USD = 50.0    # Tamaño por pierna en USD
    MAX_CONCURRENT = 3          # Máximo arbitrajes simultáneos

    @staticmethod
    def evaluate(poly_prices: dict, kalshi_prices: dict) -> Optional[ArbitrageSignal]:
        """Evalúa ambas estrategias de arbitraje.

        Args:
            poly_prices: {'up': float, 'down': float, 'slug': str}
            kalshi_prices: {'yes': float, 'yes_ticker': str, 'no': float, 'no_ticker': str}
        """
        if not poly_prices or not kalshi_prices:
            return None

        poly_up = poly_prices.get('up', 1.0)
        poly_down = poly_prices.get('down', 1.0)

        # Estrategia A: Poly Down + Kalshi Yes
        k_yes = kalshi_prices.get('yes', 1.0)
        cost_a = poly_down + k_yes
        profit_a = 1.0 - cost_a

        # Estrategia B: Poly Up + Kalshi No
        k_no = kalshi_prices.get('no', 1.0)
        cost_b = poly_up + k_no
        profit_b = 1.0 - cost_b

        # Elegir la mejor
        if profit_a >= profit_b and cost_a < KalshiArbitrageStrategy.MAX_COST:
            return ArbitrageSignal(
                strategy='A',
                poly_event_slug=poly_prices.get('slug', ''),
                poly_token='down',
                poly_price=poly_down,
                kalshi_market_ticker=kalshi_prices.get('yes_ticker', ''),
                kalshi_side='yes',
                kalshi_price=k_yes,
                total_cost=cost_a,
                profit_per_unit=profit_a,
                profit_pct=profit_a / cost_a * 100 if cost_a > 0 else 0,
            )
        elif cost_b < KalshiArbitrageStrategy.MAX_COST:
            return ArbitrageSignal(
                strategy='B',
                poly_event_slug=poly_prices.get('slug', ''),
                poly_token='up',
                poly_price=poly_up,
                kalshi_market_ticker=kalshi_prices.get('no_ticker', ''),
                kalshi_side='no',
                kalshi_price=k_no,
                total_cost=cost_b,
                profit_per_unit=profit_b,
                profit_pct=profit_b / cost_b * 100 if cost_b > 0 else 0,
            )

        return None

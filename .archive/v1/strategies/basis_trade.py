"""
BasisTradeStrategy — Estrategia Spot-Futures Basis Trade.

Compra spot + vende futuro del mismo vencimiento. Captura el funding rate
sin riesgo direccional (market-neutral).

Flujo:
  1. Evaluar funding rate de cada contrato (BTC, ETH)
  2. Si funding_rate_annual > min_funding_rate_annual → señal de entrada
  3. Abrir par: comprar spot + vender futuro (mismo tamaño)
  4. Monitorear funding acumulado
  5. Cerrar cuando: funding baja, rollover, o vencimiento cercano
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class BasisTradeSignal:
    """Señal de entrada para un Basis Trade."""
    asset: str                     # BTC o ETH
    funding_rate: float            # Funding rate actual (decimal)
    funding_annual_pct: float      # Funding rate anualizado (%)
    spot_price: float              # Precio spot
    futures_price: float           # Precio del futuro
    basis_pct: float               # Diferencia spot-futuro (%)
    avg_funding_30d: float         # Funding promedio 30d anualizado
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def is_valid(self) -> bool:
        return self.funding_annual_pct > 0 and self.spot_price > 0 and self.futures_price > 0


@dataclass
class BasisTradePosition:
    """Posición abierta de Basis Trade."""
    asset: str
    spot_size: float               # Tamaño comprado en spot
    futures_size: float            # Tamaño vendido en futuro (debe ser igual)
    spot_entry: float              # Precio de entrada spot
    futures_entry: float           # Precio de entrada futuro
    entry_time: str
    total_funding_collected: float = 0.0  # Funding acumulado en USD
    closed: bool = False
    close_time: Optional[str] = None
    pnl: float = 0.0


class BasisTradeStrategy:
    """Estrategia de Basis Trade (Spot-Futures)."""

    NAME = 'BASIS_TRADE'

    def __init__(self, config: dict):
        """
        Args:
            config: Diccionario con parámetros desde exchange_config.yaml:
                - min_funding_rate_annual: float
                - contracts: list[str]
                - rollover_days_before: int
                - max_capital_pct: float
        """
        self.cfg = config
        self.min_funding = config.get('min_funding_rate_annual', 8.0)
        self.contracts = config.get('contracts', ['BTC', 'ETH'])
        self.rollover_days = config.get('rollover_days_before', 2)
        self.max_capital_pct = config.get('max_capital_pct', 0.30)

    def evaluate(self, asset: str, funding_annual: float, spot_price: float,
                 futures_price: float, basis_pct: float, avg_funding_30d: float = 0) -> Optional[BasisTradeSignal]:
        """Evalúa si conviene entrar en basis trade para un activo.

        Returns:
            BasisTradeSignal si hay señal, None si no.
        """
        if funding_annual < self.min_funding:
            return None
        if spot_price <= 0 or futures_price <= 0:
            return None
        if basis_pct < -1.0 or basis_pct > 3.0:  # Anomalías de precio
            return None
        if funding_annual > 100:  # Rate sospechosamente alto
            return None

        return BasisTradeSignal(
            asset=asset,
            funding_rate=funding_annual / 100 / 365 / 3,  # reverso: anual → por intervalo
            funding_annual_pct=round(funding_annual, 2),
            spot_price=spot_price,
            futures_price=futures_price,
            basis_pct=round(basis_pct, 4),
            avg_funding_30d=round(avg_funding_30d, 2),
        )

    def should_close(self, position: BasisTradePosition,
                     current_funding_annual: float,
                     days_to_expiry: int = 60) -> tuple[bool, str]:
        """Determina si se debe cerrar una posición de basis trade.

        Returns:
            (debe_cerrar, razón)
        """
        if days_to_expiry <= self.rollover_days:
            return True, 'ROLLOVER'

        if current_funding_annual < self.min_funding * 0.5:
            return True, 'FUNDING_DECAY'

        return False, ''

    def calculate_pnl(self, position: BasisTradePosition, current_spot: float,
                      current_futures: float) -> float:
        """Calcula PnL de la posición."""
        spot_pnl = (current_spot - position.spot_entry) * position.spot_size
        futures_pnl = (position.futures_entry - current_futures) * position.futures_size
        return spot_pnl + futures_pnl + position.total_funding_collected

    def estimate_monthly_return(self, funding_annual: float, capital_used: float = 1000) -> float:
        """Estima retorno mensual basado en funding rate anual.

        Retorno mensual ≈ funding_annual / 12 (asumiendo reinversión)
        """
        monthly_rate = (1 + funding_annual / 100) ** (1 / 12) - 1
        return monthly_rate * 100

    def calculate_position_size(self, capital: float, spot_price: float) -> float:
        """Calcula tamaño de posición basado en capital disponible."""
        max_capital = capital * self.max_capital_pct
        max_capital = min(max_capital, capital * 0.10)  # Cap adicional: 10% por posición
        return max_capital / spot_price if spot_price > 0 else 0

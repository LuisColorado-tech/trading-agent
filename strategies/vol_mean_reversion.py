"""
VolMeanReversionStrategy — Mean Reversion de VIX usando productos de volatilidad.

Flujo:
  1. Monitorear VIX spot + percentil + contango
  2. Señal ENTRY cuando VIX > percentil 80: long SVXY (short vol)
  3. Señal EXIT cuando VIX < percentil 50 o TP/SL
  4. Market-neutral: el trade es direccional en VIX, no en SPY

Producto preferido: SVXY (inverso de VIX, decay favorable por contango).
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from core.vol_profiles import VolProfile, get_vol_profile
from data.vol_feed import VolFeed


@dataclass
class VolSignal:
    ticker: str
    signal: str                       # ENTRY, EXIT, HOLD
    vix_spot: Optional[float]
    vix_percentile: Optional[float]
    contango_annual: Optional[float]
    product_price: Optional[float]
    reason: str = ''
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def is_entry(self) -> bool:
        return self.signal == 'ENTRY'

    @property
    def is_exit(self) -> bool:
        return self.signal == 'EXIT'


@dataclass
class VolPosition:
    ticker: str
    entry_price: float
    size: float
    entry_time: str
    vix_at_entry: Optional[float] = None
    pnl: float = 0.0
    closed: bool = False
    close_time: Optional[str] = None
    close_reason: str = ''


class VolMeanReversionStrategy:
    """Estrategia de mean reversion de volatilidad."""

    NAME = 'VOL_MEAN_REVERSION'

    def __init__(self, config: dict):
        self.cfg = config
        self.assets = config.get('assets', ['SVXY'])
        self.entry_percentile = config.get('vix_entry_percentile', 80)
        self.exit_percentile = config.get('vix_exit_percentile', 50)
        self.max_position_pct = config.get('max_position_pct', 0.10)
        self.stop_loss_pct = config.get('stop_loss_pct', 0.15)
        self.min_contango = config.get('min_contango_annual_pct', 20.0)
        self.max_hold_days = config.get('max_hold_days', 60)
        self.feed = VolFeed()

    def evaluate(self, ticker: str) -> Optional[VolSignal]:
        """Evalúa señal de entrada/salida para un producto de vol.

        Returns:
            VolSignal con ENTRY, EXIT o HOLD.
        """
        profile = get_vol_profile(ticker)
        vix_data = self.feed.get_vix_signal(
            entry_percentile=self.entry_percentile,
            exit_percentile=self.exit_percentile,
        )
        product_price = self.feed.get_product_price(ticker)
        contango = vix_data.get('contango_annual_pct')

        # Señal de entrada
        if vix_data['signal'] == 'ENTRY':
            if contango and contango >= self.min_contango:
                return VolSignal(
                    ticker=ticker,
                    signal='ENTRY',
                    vix_spot=vix_data['vix_spot'],
                    vix_percentile=vix_data['vix_percentile'],
                    contango_annual=contango,
                    product_price=product_price,
                    reason=f'VIX alto (p{int(vix_data["vix_percentile"])}%) + contango {contango:.1f}%/yr',
                )
            else:
                return VolSignal(
                    ticker=ticker,
                    signal='HOLD',
                    vix_spot=vix_data['vix_spot'],
                    vix_percentile=vix_data['vix_percentile'],
                    contango_annual=contango,
                    product_price=product_price,
                    reason=f'VIX alto pero contango {contango:.1f}% < {self.min_contango}% mínimo',
                )

        # Señal de salida
        if vix_data['signal'] == 'EXIT':
            return VolSignal(
                ticker=ticker,
                signal='EXIT',
                vix_spot=vix_data['vix_spot'],
                vix_percentile=vix_data['vix_percentile'],
                contango_annual=contango,
                product_price=product_price,
                reason=vix_data['reason'],
            )

        # Hold
        return VolSignal(
            ticker=ticker,
            signal='HOLD',
            vix_spot=vix_data['vix_spot'],
            vix_percentile=vix_data['vix_percentile'],
            contango_annual=contango,
            product_price=product_price,
        )

    def check_sl_tp(self, position: VolPosition, current_price: float) -> tuple[bool, str]:
        """Verifica si la posición llegó a SL o TP."""
        pnl_pct = (current_price - position.entry_price) / position.entry_price

        if pnl_pct <= -self.stop_loss_pct:
            return True, 'STOP_LOSS'

        profile = get_vol_profile(position.ticker)
        if profile.direction == 'LONG' and pnl_pct >= profile.take_profit_pct:
            return True, 'TAKE_PROFIT'

        return False, ''

    def should_close(self, position: VolPosition, current_price: float,
                     current_vix_percentile: Optional[float] = None,
                     hold_days: int = 0) -> tuple[bool, str]:
        """Determina si se debe cerrar la posición."""
        # SL/TP
        sl_tp, reason = self.check_sl_tp(position, current_price)
        if sl_tp:
            return True, reason

        # Exit por percentil de VIX
        if current_vix_percentile is not None and current_vix_percentile <= self.exit_percentile:
            return True, 'VIX_NORMALIZED'

        # Max hold time
        if hold_days >= self.max_hold_days:
            return True, 'MAX_HOLD_TIME'

        return False, ''

    def calculate_position_size(self, capital: float, price: float) -> float:
        """Tamaño de posición basado en % del capital."""
        max_capital = capital * self.max_position_pct
        return max_capital / price if price > 0 else 0

    def estimate_monthly_return(self, entry_percentile: int = 80) -> float:
        """Estima retorno mensual basado en frecuencia de señales históricas."""
        vix_history = self.feed.get_vix_history(days=252 * 5)
        if vix_history.empty:
            return 0.5

        n_entries = (vix_history > vix_history.quantile(entry_percentile / 100)).sum()
        n_trades_per_year = n_entries / 5  # promedio en 5 años
        n_trades_per_month = n_trades_per_year / 12

        avg_return_per_trade = 0.05  # 5% estimado por trade
        monthly_return = n_trades_per_month * avg_return_per_trade * 100

        return min(monthly_return, 5.0)  # Cap 5% mensual

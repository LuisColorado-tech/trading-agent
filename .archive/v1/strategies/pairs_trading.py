"""
PairsTradingStrategy — Estrategia de pares cointegrados market-neutral.

Flujo:
  1. Calcular spread = log(A) - beta * log(B) con beta rodante
  2. Z-score del spread: (spread - media) / desviación
  3. Señal cuando |z| > z_entry → abrir par (long underperformer, short outperformer)
  4. Cerrar cuando z vuelve a 0, o TP/SL en z-score
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from core.pairs_profiles import PairsProfile, get_pairs_profile
from data.pairs_feed import PairsFeed


@dataclass
class PairsSignal:
    pair: str
    signal: str                       # ENTRY_LONG_SPREAD, ENTRY_SHORT_SPREAD, EXIT, HOLD
    direction: str = 'NEUTRAL'         # LONG, SHORT (de la pierna A)
    z_score: Optional[float] = None
    beta: Optional[float] = None
    half_life_days: Optional[float] = None
    reason: str = ''
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def is_entry(self) -> bool:
        return self.signal.startswith('ENTRY')

    @property
    def is_exit(self) -> bool:
        return self.signal == 'EXIT'


@dataclass
class PairsPosition:
    pair: str
    side_a: str                       # LONG o SHORT para pierna A
    entry_price_a: float
    entry_price_b: float
    size_a: float
    size_b: float
    beta_at_entry: float
    z_at_entry: float
    entry_time: str
    pnl: float = 0.0
    closed: bool = False
    close_time: Optional[str] = None
    close_reason: str = ''


class PairsTradingStrategy:
    """Estrategia de pares trading market-neutral."""

    NAME = 'PAIRS_TRADING'

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.enabled_pairs = [
            name for name, pcfg in cfg.get('pairs', {}).items()
        ]
        self.feed = PairsFeed()

    def evaluate(self, pair_name: str, capital: float = 1000.0) -> Optional[PairsSignal]:
        """Evalúa señal para un par.

        Returns:
            PairsSignal con ENTRY, EXIT o HOLD.
        """
        profile = get_pairs_profile(pair_name)
        result = self.feed.evaluate_pair(pair_name, profile)

        if result is None or result.get('z_score') is None:
            return PairsSignal(pair=pair_name, signal='HOLD', reason='no_data')

        signal = result['signal']
        z = result['z_score']
        beta = result['beta']
        hl = result['half_life_days']

        # Validar half-life
        if signal.startswith('ENTRY') and hl is not None:
            if hl < profile.min_half_life or hl > profile.max_half_life:
                return PairsSignal(
                    pair=pair_name, signal='HOLD',
                    z_score=z, beta=beta, half_life_days=hl,
                    reason=f'half_life {hl:.1f}d fuera de [{profile.min_half_life}, {profile.max_half_life}]'
                )

        direction = 'NEUTRAL'
        if signal == 'ENTRY_LONG_SPREAD':
            direction = 'LONG_A'  # long A, short B
        elif signal == 'ENTRY_SHORT_SPREAD':
            direction = 'SHORT_A'  # short A, long B

        return PairsSignal(
            pair=pair_name,
            signal=signal,
            direction=direction,
            z_score=z,
            beta=beta,
            half_life_days=hl,
            reason=result.get('reason', ''),
        )

    def check_exit(self, position: PairsPosition, current_z: float,
                   profile: PairsProfile, hold_days: int = 0) -> tuple[bool, str]:
        """Determina si cerrar la posición."""
        # Reversión a z_exit
        if abs(current_z) <= profile.z_exit:
            return True, 'Z_REVERTED'

        # Stop loss en z-score
        if position.side_a == 'LONG' and current_z <= -profile.stop_loss_z:
            return True, 'STOP_LOSS_Z'
        if position.side_a == 'SHORT' and current_z >= profile.stop_loss_z:
            return True, 'STOP_LOSS_Z'

        # Max hold time
        if hold_days >= profile.max_hold_days:
            return True, 'MAX_HOLD_TIME'

        return False, ''

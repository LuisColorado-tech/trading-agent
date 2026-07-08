"""
PairsProfile — Perfiles de pares cointegrados para Pairs Trading.

Define parámetros por par: ratio de cobertura (beta), half-life,
umbrales z-score de entrada/salida, y gestión de riesgo.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PairsProfile:
    pair_name: str                     # GLD-SLV, BTC-ETH, etc.
    asset_a: str                       # Pierna long cuando el spread está bajo
    asset_b: str                       # Pierna short cuando el spread está bajo
    source: str = 'alpaca'             # alpaca o kraken

    hedge_ratio_window: int = 252      # Días para estimar beta (regresión)
    refit_interval: int = 21           # Días entre recalibraciones de beta

    z_entry: float = 2.0               # z-score > esto → abrir
    z_exit: float = 0.0                # z-score vuelve a esto → cerrar
    stop_loss_z: float = 3.5           # z-score sigue divergiendo → SL

    max_hold_days: int = 60            # Tiempo máximo en el par
    min_half_life: float = 5.0         # Half-life mínimo (días) para operar
    max_half_life: float = 90.0        # Half-life máximo (cointegración débil)

    max_capital_pct: float = 0.10      # % del capital por par

    notes: str = ''


PAIRS_PROFILES: dict[str, PairsProfile] = {

    'GLD-SLV': PairsProfile(
        pair_name='GLD-SLV',
        asset_a='GLD',
        asset_b='SLV',
        source='alpaca',
        hedge_ratio_window=252,
        refit_interval=21,
        z_entry=1.5,                     # May13: 2.0→1.5 (32→163 signal days/year)
        z_exit=0.3,                      # 0.0→0.3 (avoid whipsaw near mean)
        stop_loss_z=3.0,                 # 3.5→3.0 (tighter, z>3.0 is rare)
        max_hold_days=90,                # 60→90 (spread can take months to revert)
        min_half_life=3,                 # Relaxed minimum
        max_half_life=200,               # 60→200 (don't filter by half-life)
        max_capital_pct=0.10,
        notes='Oro vs Plata. z_entry 1.5 → ~30 trades/5Y (vs 7 at z=2.0). '
              'Asymmetric: more short signals (GLD overperformed and reverts).',
    ),

    'BTC-ETH': PairsProfile(
        pair_name='BTC-ETH',
        asset_a='ETH',
        asset_b='BTC',
        source='kraken',
        hedge_ratio_window=90,
        refit_interval=7,
        z_entry=1.5,                     # May13: 2.5→1.5 (was generating 0 trades)
        z_exit=0.3,
        stop_loss_z=3.0,                 # 4.0→3.0
        max_hold_days=60,                # 30→60
        min_half_life=3,
        max_half_life=200,               # hl real ~150d, 30d era demasiado restrictivo
        max_capital_pct=0.08,
        notes='BTC vs ETH. Correlación 0.89. Ventana más corta (90d) por '
              'cambios estructurales en dominance. Half-life más rápida.',
    ),
}


def get_pairs_profile(pair_name: str) -> PairsProfile:
    """Retorna perfil del par o uno conservador por defecto."""
    if pair_name in PAIRS_PROFILES:
        return PAIRS_PROFILES[pair_name]
    return PairsProfile(
        pair_name=pair_name,
        asset_a=pair_name.split('-')[0],
        asset_b=pair_name.split('-')[1],
        notes=f'Perfil genérico no calibrado para {pair_name}.',
    )

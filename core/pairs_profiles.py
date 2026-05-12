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
        z_entry=2.0,
        z_exit=0.0,
        stop_loss_z=3.5,
        max_hold_days=60,
        min_half_life=5,
        max_half_life=60,
        max_capital_pct=0.10,
        notes='Oro vs Plata. Alta correlación 0.82. Cointegrados a largo plazo. '
              'Trade de reversión clásico en commodities.',
    ),

    'BTC-ETH': PairsProfile(
        pair_name='BTC-ETH',
        asset_a='ETH',
        asset_b='BTC',
        source='kraken',
        hedge_ratio_window=90,
        refit_interval=7,
        z_entry=2.5,
        z_exit=0.5,
        stop_loss_z=4.0,
        max_hold_days=30,
        min_half_life=3,
        max_half_life=30,
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

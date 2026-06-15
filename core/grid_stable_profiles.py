"""
GridStableProfile — Perfiles para Grid Bot en pares estables (baja volatilidad).

Pares: ETH/BTC, LINK/BTC
Estos pares tienen ATR/Precio típicamente 0.1-0.5% vs 0.5-2% en crypto/USDT.
Requieren: más niveles, TP/SL más ceñidos, rango más pequeño.
"""
from dataclasses import dataclass, field
from typing import FrozenSet, Optional


@dataclass(frozen=True)
class GridStableProfile:
    pair: str                          # ej: 'ETH/BTC'

    # ── Grid ──
    grid_levels: int = 10              # más niveles = más trades pequeños
    grid_range_candles: int = 50       # más velas para rango estable
    grid_buffer_pct: float = 0.001     # buffer más ceñido (0.1%)
    min_range_pct: float = 0.005       # rango mínimo 0.5%
    max_range_pct: float = 0.030       # rango máximo 3%
    level_tolerance_pct: float = 0.0008  # tolerancia nivel ±0.08%
    tp_ratio: float = 1.20             # TP más ceñido (1.2× spacing)
    sl_ratio: float = 0.40             # SL muy ceñido (0.4× spacing)
    min_rr: float = 1.50               # R:R mínimo exigente para compensar comisiones

    # ── Riesgo ──
    max_per_asset: int = 3             # máximo trades por par
    risk_fraction: float = 0.30        # 30% del riesgo normal (menos volatilidad)
    min_bars_in_range: int = 40        # mínimo velas en rango antes de operar

    # ── Exchange ──
    exchange: str = 'kraken'           # primario
    fallback: str = 'okx'              # secundario

    # ── Hora ──
    blocked_hours_utc: Optional[FrozenSet[int]] = None  # 24h para crypto

    notes: str = ''


# ══════════════════════════════════════════════════════════════════
#  Perfiles calibrados
# ══════════════════════════════════════════════════════════════════

GRID_STABLE_PROFILES: dict[str, GridStableProfile] = {

    # ── ETH/BTC ──────────────────────────────────────────────────
    # Rango típico 2-3%, ATR ~0.15-0.4%. 
    # 10 niveles capturan micro-oscilaciones. SL muy ceñido (0.4×).
    'ETH/BTC': GridStableProfile(
        pair='ETH/BTC',
        grid_levels=10,
        grid_range_candles=50,
        min_range_pct=0.005,
        max_range_pct=0.030,
        tp_ratio=1.80,
        sl_ratio=0.60,
        min_rr=1.50,
        max_per_asset=3,
        risk_fraction=0.20,
        min_bars_in_range=40,
        blocked_hours_utc=None,
        notes='Par más líquido. SL ensanchado 0.40→0.60 (evita noise). Risk reducido 0.30→0.20 (fase validación).',
    ),

    # ── LINK/BTC ─────────────────────────────────────────────────
    # Más volátil que ETH/BTC (~2×), rango 3-6%.
    # Menos niveles (8), TP ligeramente más amplio.
    'LINK/BTC': GridStableProfile(
        pair='LINK/BTC',
        grid_levels=8,
        grid_range_candles=50,
        min_range_pct=0.008,
        max_range_pct=0.050,
        tp_ratio=1.95,
        sl_ratio=0.65,
        min_rr=1.50,
        max_per_asset=2,
        risk_fraction=0.25,
        min_bars_in_range=35,
        blocked_hours_utc=None,
        notes='SL ensanchado 0.50→0.65 para filtrar noise. TP ajustado para mantener RR=3.0.',
    ),

    # ── DAI/USDT — Stablecoin peg ─────────────────────────────────
    # Spread 0.01-0.05%. Movimiento microscópico. Grid ultra-denso.
    'DAI/USDT': GridStableProfile(
        pair='DAI/USDT',
        grid_levels=20,
        grid_range_candles=50,
        min_range_pct=0.0001,
        max_range_pct=0.002,
        tp_ratio=1.50,
        sl_ratio=0.40,
        min_rr=1.30,
        max_per_asset=3,
        risk_fraction=0.10,
        min_bars_in_range=30,
        blocked_hours_utc=None,
        notes='Stablecoin peg: DAI/USDT. Grid ultra-denso (20 niveles). Spread microscopico.',
    ),

    # ── USDC/USDT — Stablecoin peg ─────────────────────────────────
    # Spread 0.005-0.03%. El par mas estable. Grid ultra-denso.
    'USDC/USDT': GridStableProfile(
        pair='USDC/USDT',
        grid_levels=20,
        grid_range_candles=50,
        min_range_pct=0.00005,
        max_range_pct=0.001,
        tp_ratio=1.50,
        sl_ratio=0.40,
        min_rr=1.30,
        max_per_asset=3,
        risk_fraction=0.10,
        min_bars_in_range=30,
        blocked_hours_utc=None,
        notes='Stablecoin peg: USDC/USDT. Grid ultra-denso (20 niveles). El par mas estable del mercado.',
    ),
}


def get_grid_stable_profile(pair: str) -> GridStableProfile:
    """Retorna el perfil del par o un perfil conservador por defecto."""
    if pair in GRID_STABLE_PROFILES:
        return GRID_STABLE_PROFILES[pair]
    return GridStableProfile(
        pair=pair,
        notes=f'Perfil genérico conservador para {pair}.',
    )

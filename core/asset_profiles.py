"""
AssetProfile — Configuración de estrategia por moneda.

Cada asset opera con parámetros propios derivados del análisis de:
  - Backtest 2 años (reports/backtest_15m_24m*.csv)
  - Paper SESSION_007 (99 trades, 2 semanas)

Parámetros por perfil:
  confluence_min       Mínimo de indicadores alineados para validar señal
  sl_multiplier        SL = entry ± (sl_multiplier × ATR)
  tp_multiplier        TP = entry ∓ (tp_multiplier × ATR)
  trailing_activation_r  R a partir del cual se activa el trailing (en unidades de R)
  trailing_step_r      Escalón de avance del trailing (en R)
  trailing_offset_r    Distancia del SL dinámico al pico (en R)
  allowed_hours_utc    Horas UTC donde el WR histórico es positivo. None = sin filtro
  blocked_hours_utc    Horas UTC donde el WR histórico es sistemáticamente <30%. None = sin bloqueo
  require_candle_close Si True, solo entrar en la vela SIGUIENTE al cierre de la vela de señal
                       (evita entrar en el pico de un spike que luego revierte)
  min_atr_pct          ATR mínimo como % del precio para garantizar liquidez mínima
  allowed_directions   Direcciones permitidas: {'BUY'}, {'SELL'} o {'BUY','SELL'}
  grid_tp_ratio        Grid: TP = grid_tp_ratio × spacing debajo del nivel de entrada
  grid_sl_ratio        Grid: SL = grid_sl_ratio × spacing encima del nivel de entrada
  grid_levels          Grid: número de niveles a dividir en el rango
  grid_range_candles   Grid: velas de lookback para identificar el rango
  grid_min_rr          Grid: RR mínimo para abrir orden (filtro de calidad)
  notes                Justificación del perfil basada en datos históricos

Fuente de cada parámetro documentada en los comentarios inline.
"""
from dataclasses import dataclass, field
from typing import FrozenSet, Optional


@dataclass(frozen=True)
class AssetProfile:
    asset: str

    # ── Señal ───────────────────────────────────────────────────────
    confluence_min: int = 3
    allowed_directions: FrozenSet[str] = field(default_factory=lambda: frozenset({'BUY', 'SELL'}))

    # ── SL / TP ─────────────────────────────────────────────────────
    sl_multiplier: float = 1.5
    tp_multiplier: float = 2.5

    # ── Trailing dinámico ───────────────────────────────────────────
    trailing_activation_r: float = 0.75   # R a partir del cual se activa
    trailing_step_r: float = 0.30         # Escalón de avance
    trailing_offset_r: float = 0.75       # Distancia SL al pico

    # ── Filtros de tiempo ───────────────────────────────────────────
    allowed_hours_utc: Optional[FrozenSet[int]] = None   # None = todas las horas
    blocked_hours_utc: Optional[FrozenSet[int]] = None   # None = sin bloqueo

    # ── Filtros de calidad de entrada ───────────────────────────────
    require_candle_close: bool = False   # Esperar cierre de vela de señal antes de entrar
    min_atr_pct: float = 0.002           # ATR mínimo como % del precio

    # ── Grid Bot (por asset) ─────────────────────────────────────────
    # Permite sintonizar el Grid Bot independientemente de la estrategia tendencial.
    # Valores calibrados contra backtest v2 (12 meses, 15m) para acercar PF → 1.20.
    #   PF target: WR/(1-WR) × RR_needed > 1.20
    #   BTC WR=42.1% → RR_needed=1.66  |  INJ WR=37.4% → RR_needed=2.04
    grid_tp_ratio: float = 1.50      # TP = tp_ratio × grid_spacing debajo del nivel
    grid_sl_ratio: float = 0.60      # SL = sl_ratio × grid_spacing encima del nivel
    grid_levels: int = 6             # Divisiones del rango (niveles activos)
    grid_range_candles: int = 30     # Velas lookback para calcular el rango
    grid_min_rr: float = 1.20        # RR mínimo para abrir orden grid

    # ── Grid Bot: Umbrales de régimen RANGE por asset ────────────────
    # bb_width y atr_pct deben estar POR DEBAJO de estos umbrales para
    # considerar el mercado como RANGE y permitir al Grid Bot operar.
    # Más bajo = criterio más estricto = menos falsos positivos de RANGE.
    # Calibrado por volatilidad histórica de cada asset en 15m.
    grid_bb_width_max: float = 0.06   # Ancho máximo de BBands para RANGE
    grid_atr_pct_max: float = 0.012   # ATR/precio máximo para RANGE

    notes: str = ''


# ══════════════════════════════════════════════════════════════════════
#  Perfiles por asset
#  (basados en backtest 2Y + Paper SESSION_007)
# ══════════════════════════════════════════════════════════════════════

ASSET_PROFILES: dict[str, AssetProfile] = {

    # ── BTC ─────────────────────────────────────────────────────────
    # Backtest 2Y SELL: WR=33.2%, PnL=+$2,433 (1,386 trades)
    # Backtest 2Y BUY:  WR=31.9%, PnL=-$1,961 → bloqueado
    # Mejores horas: 4h UTC (51% WR, +$3,050), 16h UTC (47% WR, +$4,357)
    # Peores horas: 0h (19%), 20h (19%), 22h (23%)
    # Movimiento limpio, sin spikes de entrada (require_candle_close=False)
    # Trailing ceñido: movimientos de BTC son grandes pero reversibles
    # Grid v2: WR=42.1%, RR=1.48x, PF=1.08 → RR_needed=1.66 para PF=1.20
    #   +TP_RATIO 1.50→1.80; SL_RATIO 0.60 (intacto, BTC es limpio)
    #   range_candles=35: rango más estable en BTC (movimientos deliberados)
    'BTC': AssetProfile(
        asset='BTC',
        allowed_directions=frozenset({'SELL'}),
        confluence_min=3,  # v3 rollback May 13: 3→5→3 (5 eliminaba 90% de señales BTC. PRE-v3: 32 trades +$3,145)
        sl_multiplier=1.3,
        tp_multiplier=2.8,
        trailing_activation_r=0.75,  # v3: 1.5→0.75 (activar antes, evita reversiones que borran ganancias)
        trailing_step_r=0.40,
        trailing_offset_r=0.80,
        blocked_hours_utc=frozenset({0, 20, 21, 22, 23}),
        require_candle_close=False,
        min_atr_pct=0.002,
        grid_tp_ratio=1.80,
        grid_sl_ratio=0.60,
        grid_levels=6,
        grid_range_candles=35,
        grid_min_rr=1.25,
        grid_bb_width_max=0.05,    # backtest v5→v5b: 0.04 filtraba demasiado (-23% trades), 0.05 = nivel ETH/SOL
        grid_atr_pct_max=0.008,    # BTC trending: ATR sube a 0.5-1.5% → umbral conservador
        notes=(
            'SELL only — BUY pierde $1,961 en 2Y. '
            'Bloqueado en 0h/20-23h UTC (WR <23%). '
            'Trailing más tardío (R×1.5) para capturar movimientos amplios de BTC. '
            'Grid: tp=1.80/sl=0.60 → RR_teo=3.0 para alcanzar PF=1.20 con WR=42%.'
        ),
    ),

    # ── ETH ─────────────────────────────────────────────────────────
    # Backtest 2Y SELL: WR=33.5%, PnL=+$4,965 (1,576 trades)
    # Paper S007: WR=31.3%, PnL=-$107 — único asset con edge NEGATIVO en paper
    # avg_move_favorable=0.248% < avg_move_adverso=0.307% (edge negativo en 15m)
    # 36% de SL ocurren en <5 minutos (falsas entradas)
    # Mejores horas 2Y: 6h-8h UTC (≥42% WR)
    # Peores horas 2Y: 1h (22%), 9h-10h (21-25%)
    # confluencia=4 para filtrar señales de baja calidad en 15m
    # Grid v2: WR=40.1%, RR=1.65x, PF=1.11, DD=10% → RR_needed=1.80 para PF=1.20
    #   +TP_RATIO 1.50→1.80; -SL_RATIO 0.60→0.50 (DD alto, SL más ceñido)
    #   levels=5: menos niveles para mejorar calidad y reducir exposición simultánea
    'ETH': AssetProfile(
        asset='ETH',
        allowed_directions=frozenset({'SELL'}),
        confluence_min=4,
        sl_multiplier=1.4,
        tp_multiplier=2.8,
        trailing_activation_r=1.0,
        trailing_step_r=0.30,
        trailing_offset_r=0.70,
        allowed_hours_utc=frozenset({5, 6, 7, 8, 11, 12, 14, 15, 16, 17, 18, 19}),
        blocked_hours_utc=frozenset({0, 1, 2, 3, 4, 9, 10}),
        require_candle_close=False,
        min_atr_pct=0.002,
        grid_tp_ratio=1.80,
        grid_sl_ratio=0.50,
        grid_levels=5,
        grid_range_candles=30,
        grid_min_rr=1.30,
        grid_bb_width_max=0.05,    # ETH: rango real ≤ 5% bb_width (más volátil que BTC)
        grid_atr_pct_max=0.010,    # ETH: DD=10% en v2 → umbral más conservador
        notes=(
            'SELL only. confluencia=4 por edge negativo en paper 15m. '
            'Filtrado a horas 5-8h y 11-19h UTC (mejores en 2Y). '
            'El edge en 2Y existe (+$4,965) pero paper muestra degradación en 15m con señales débiles. '
            'Grid: sl=0.50 más ceñido para controlar DD=10% observado en v2; levels=5 para calidad.'
        ),
    ),

    # ── SOL ─────────────────────────────────────────────────────────
    # Backtest 2Y SELL: WR=33.5%, PnL=+$2,590 (1,886 trades)
    # Paper S007: WR=37.0%, PnL=-$95
    # 41% de SL ocurren en <5 minutos — mayor tasa de falsas entradas
    # Patrón: spike en la dirección de señal → reversión inmediata (wick noise)
    # Mejores horas 2Y: 7h-8h UTC (40-41% WR), 12h UTC (39%)
    # Peores horas 2Y: 0h (20%), 13h (22%), 20h (27%)
    # require_candle_close=True: esperar cierre de vela para confirmar el movimiento
    # Grid v2: WR=39.4%, RR=1.70x, PF=1.10, racha=17 pérd → RR_needed=1.83 para PF=1.20
    #   +TP_RATIO 1.50→1.90; SL_RATIO 0.60 (intacto)
    #   range_candles=25: SOL cambia de régimen más rápido, rango más fresco
    'SOL': AssetProfile(
        asset='SOL',
        allowed_directions=frozenset({'SELL'}),
        confluence_min=4,  # v3 rollback May 13: 4→5→4 (65→2 trades SOL, -98% actividad)
        sl_multiplier=1.4,
        tp_multiplier=2.8,
        trailing_activation_r=1.0,
        trailing_step_r=0.30,
        trailing_offset_r=1.0,  # v3: 0.75→1.0 (wicks grandes de SOL activan SL prematuro)
        blocked_hours_utc=frozenset({0, 1, 2, 13, 20, 21, 22, 23}),
        require_candle_close=True,
        min_atr_pct=0.003,
        grid_tp_ratio=1.90,
        grid_sl_ratio=0.60,
        grid_levels=6,
        grid_range_candles=25,
        grid_min_rr=1.25,
        grid_bb_width_max=0.05,    # SOL: cambios rápidos de régimen, umbral medio
        grid_atr_pct_max=0.010,    # SOL: racha de 17 pérd en v2 → umbral conservador
        notes=(
            'SELL only. require_candle_close=True para evitar wick noise — '
            '41% de SL ocurren en <5min en paper. '
            'confluencia=4 como filtro adicional. '
            'Bloqueado en horas con WR <28% según 2Y. '
            'Grid: tp=1.90 para RR_needed=1.83 con WR=39.4%; range_candles=25 por cambios rápidos de régimen.'
        ),
    ),

    # ── AVAX ────────────────────────────────────────────────────────
    # Backtest 2Y SELL: WR=34.4%, PnL=+$5,253 (1,516 trades) — mejor asset 2Y
    # Paper S007: WR=47.8%, PnL=+$270 — mejor en paper también
    # 33% de SL ocurren en <2 minutos (entradas en pico de spike)
    # Mejores horas 2Y: 18h UTC (43%), 23h UTC (41%), 14h (39%) — opuesto al resto
    # Peores horas 2Y: 13h (29%), 20h (29%), 16h (29%)
    # Trailing más temprano porque AVAX tiene movimientos amplios y rápidos
    # Grid v2: WR=39.1%, RR=1.76x, PF=1.13, Sharpe=1.97 (mejor) → RR_needed=1.85
    #   +TP_RATIO 1.50→2.00; SL_RATIO 0.55 (ligeramente más ceñido, AVAX es limpio)
    #   levels=7: AVAX tiene rangos más amplios, más niveles = más oportunidades
    #   range_candles=25: movimientos rápidos, rango fresco más relevante
    'AVAX': AssetProfile(
        asset='AVAX',
        allowed_directions=frozenset({'SELL'}),
        confluence_min=3,
        sl_multiplier=1.5,
        tp_multiplier=2.6,
        trailing_activation_r=0.75,  # v3: 1.2→0.75 (activar antes, AVAX tiene movimientos rápidos)
        trailing_step_r=0.35,
        trailing_offset_r=0.70,
        blocked_hours_utc=frozenset({1, 2, 3, 4, 13, 20, 21, 22}),
        require_candle_close=True,
        min_atr_pct=0.003,
        grid_tp_ratio=1.65,
        grid_sl_ratio=0.55,
        grid_levels=6,
        grid_range_candles=25,
        grid_min_rr=1.20,
        grid_bb_width_max=0.06,    # AVAX: más volátil, rango más amplio permitido
        grid_atr_pct_max=0.012,    # AVAX: Sharpe=1.97 en v2, umbral estándar
        notes=(
            'SELL only. El mejor asset en backtest 2Y y paper. '
            'require_candle_close=True para eliminar entradas en pico de spike (33% de SL <2min). '
            'Trailing más agresivo (R×1.2) porque AVAX hace movimientos rápidos y amplios. '
            'Patrón horario distinto al resto: mejor 18h y 23h UTC. '
            'Grid: tp=1.65/sl=0.55 → RR=3.0 conservando WR ~39% de v2 (Sharpe=1.97); '
            'tp=2.0 en v3 destruyó WR a 31% y DD subió a 10.6%.'
        ),
    ),

    # ── INJ ─────────────────────────────────────────────────────────
    # Backtest 2Y SELL: WR=34.1%, PnL=+$4,096 (1,632 trades)
    # Paper S007: WR=48.5%, PnL=+$10 (casi break-even por trailing agresivo)
    # Solo 12% de SL en <5min — el asset más limpio en entradas
    # Problema único: trailing sale a $6 promedio vs $18-41 del TP
    # Mejores horas 2Y: 3h, 5h, 6h UTC (40-43% WR)
    # Peores horas 2Y: 4h (23%), 21h (23%), 18h (27%)
    # trailing_activation_r=2.0 — dejar correr mucho más antes de proteger
    # Grid v2: WR=37.4%, RR=1.82x, PF=1.09 (peor PF) → RR_needed=2.04 para PF=1.20
    #   +TP_RATIO 1.50→2.20; -SL_RATIO 0.60→0.50 (WR más baja, SL ceñido para EV)
    #   levels=5: INJ necesita niveles de resistencia claros y bien separados
    #   range_candles=20: INJ es el más volátil, rango muy fresco
    'INJ': AssetProfile(
        asset='INJ',
        allowed_directions=frozenset({'SELL'}),
        confluence_min=4,  # v3 rollback May 13: 4→5→4 (50→8 trades INJ, -84% actividad)
        sl_multiplier=1.8,  # v3: 1.3→1.8 (SL más amplio → posición más pequeña para mismo riesgo)
        tp_multiplier=3.5,  # v3: 2.6→3.5 (proporcional al SL para mantener R:R ~2:1)
        trailing_activation_r=1.0,  # v3: 2.0→1.0 (activar antes, pero más alto que resto por volatilidad INJ)
        trailing_step_r=0.40,
        trailing_offset_r=0.60,
        blocked_hours_utc=frozenset({4, 21, 22, 23}),
        require_candle_close=False,
        min_atr_pct=0.002,
        grid_tp_ratio=1.80,
        grid_sl_ratio=0.55,
        grid_levels=5,
        grid_range_candles=20,
        grid_min_rr=1.25,
        grid_bb_width_max=0.06,    # INJ: el más volátil, rango más amplio permitido
        grid_atr_pct_max=0.012,    # INJ: PF=1.09 (peor), umbral estándar para no filtrar demasiado
        notes=(
            'SELL only. Señal más limpia (12% falsas <5min). '
            'trailing_activation_r=2.0 — el trailing actual (0.75R) cierra a $6 '
            'cuando el TP daría $18-41. Dejar correr el movimiento antes de proteger. '
            'sin require_candle_close porque las entradas son limpias. '
            'Grid: tp=1.80/sl=0.55 → RR_teo=3.3 equilibrado; '
            'tp=2.20 en v3 destruyó WR a 25% y DD subió a 12.6%; '
            'levels=5 y range_candles=20 por alta volatilidad de INJ.'
        ),
    ),

    # ── XAU ─────────────────────────────────────────────────────────
    # Paper: WR=50%, PnL=+$1,146 (16 trades, semi-inactivo)
    # Precio ~$4,707 → ATR 0.004% — muy baja volatilidad relativa
    # Sin backtest CSV de 2Y. Usar 2Y de comportamiento general del oro.
    # Estrategia: TREND_MOMENTUM SELL (TP en minutos en trades limpios)
    # SL ceñido (×1.2) porque ATR bajo ya implica riesgo pequeño por unidad
    # TP amplio (×3.0) para compensar el ATR bajo con mejor ratio
    'XAU': AssetProfile(
        asset='XAU',
        allowed_directions=frozenset({'SELL'}),
        confluence_min=3,
        sl_multiplier=1.2,
        tp_multiplier=3.0,
        trailing_activation_r=0.75,  # v3: 1.5→0.75 (activar antes)
        trailing_step_r=0.50,
        trailing_offset_r=0.80,
        blocked_hours_utc=frozenset({0, 1, 2, 3, 4}),
        require_candle_close=False,
        min_atr_pct=0.003,
        notes=(
            'SELL only (MEAN_REVERSION BUY como secundaria solo en RANGE extremo). '
            'ATR muy bajo (0.004%) — SL×1.2/TP×3.0 para mantener RR>2. '
            'Bloquear horas 0-4h UTC (liquidez mínima en oro).'
        ),
    ),

    # ── XAG ─────────────────────────────────────────────────────────
    # Paper: WR=78% (inflado por bug de compounding en SESSION_003)
    # Trades limpios (>10min): todos ganadores. Volatilidad 0.057% ATR — mayor que XAU.
    # Comportamiento muy favorable en TREND_MOMENTUM SELL
    # min_atr_pct=0.004: filtro crítico para evitar reentradas en periodos de liquidez 0
    # (el bug de 1-min que inflaba SESSION_003 ocurría con ATR≈0)
    'XAG': AssetProfile(
        asset='XAG',
        allowed_directions=frozenset({'SELL'}),
        confluence_min=3,
        sl_multiplier=1.3,
        tp_multiplier=2.8,
        trailing_activation_r=0.75,  # v3: 1.5→0.75 (activar antes)
        trailing_step_r=0.40,
        trailing_offset_r=0.70,
        blocked_hours_utc=frozenset({0, 1, 2, 3, 4}),
        require_candle_close=False,
        min_atr_pct=0.004,
        notes=(
            'SELL only. min_atr_pct=0.004 crítico para evitar el bug de reentrada '
            'en velas de 1min con ATR≈0 que infló SESSION_003. '
            'Trades limpios (>10min) muestran buena WR y PnL consistente.'
        ),
    ),
}


def get_profile(asset: str) -> AssetProfile:
    """Retorna el perfil del asset o un perfil genérico conservador si no existe."""
    if asset in ASSET_PROFILES:
        return ASSET_PROFILES[asset]
    # Perfil genérico para assets sin perfil específico (LINK, POL, AAVE...)
    return AssetProfile(
        asset=asset,
        allowed_directions=frozenset({'SELL'}),
        confluence_min=4,
        sl_multiplier=1.5,
        tp_multiplier=2.5,
        trailing_activation_r=1.0,
        trailing_step_r=0.30,
        trailing_offset_r=0.75,
        require_candle_close=True,
        min_atr_pct=0.003,
        notes='Perfil genérico conservador — no hay backtest específico para este asset.',
    )


def direction_allowed(asset: str, direction: str) -> bool:
    """Verifica si la dirección está permitida para el asset."""
    return direction in get_profile(asset).allowed_directions


def hour_allowed(asset: str, hour_utc: int) -> bool:
    """Verifica si la hora UTC actual está permitida para el asset."""
    profile = get_profile(asset)
    if profile.blocked_hours_utc and hour_utc in profile.blocked_hours_utc:
        return False
    if profile.allowed_hours_utc and hour_utc not in profile.allowed_hours_utc:
        return False
    return True

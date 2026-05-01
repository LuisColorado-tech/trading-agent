"""
StocksProfile — Configuración de estrategia por acción NYSE/NASDAQ.

Parámetros adaptados del AssetProfile de crypto pero calibrados para stocks:
- Menor volatilidad → SL más ajustado (1.0-1.2 × ATR vs 1.3-1.5)
- Movimientos más lentos → TP más corto (2.0-2.5 × ATR vs 2.5-3.0)
- Horario operativo: solo NYSE open 14:30-21:00 UTC (lunes-viernes)
- Ambas direcciones permitidas (BUY y SELL)
- Volume ratio breakout: 1.5 vs 2.0 en crypto

Fuentes de calibración:
- Backtests yfinance 2024-2025 (60 días 15m para NVDA/TSLA/AAPL)
- Backtest @aguti00 xsignals: WR=71.4% a 48h → boost para swing
"""
from dataclasses import dataclass, field
from typing import FrozenSet, Optional


@dataclass(frozen=True)
class StocksProfile:
    symbol: str

    # ── Señal ─────────────────────────────────────────────────────────────────
    confluence_min: int = 3
    allowed_directions: FrozenSet[str] = field(default_factory=lambda: frozenset({'BUY', 'SELL'}))

    # ── SL / TP ───────────────────────────────────────────────────────────────
    sl_multiplier: float = 1.1        # Stocks menos volátiles → SL más ajustado
    tp_multiplier: float = 2.2        # Movimientos más lentos → TP más corto

    # ── Trailing dinámico ─────────────────────────────────────────────────────
    trailing_activation_r: float = 0.75
    trailing_step_r: float = 0.25
    trailing_offset_r: float = 0.60

    # ── Filtros de tiempo (NYSE: 14:30-21:00 UTC, L-V) ────────────────────────
    # allowed_hours_utc=None → usar horario NYSE por defecto del StocksAgent
    # Sobreescribir aquí solo para activos con horarios extendidos o restricciones
    allowed_hours_utc: Optional[FrozenSet[int]] = None
    blocked_hours_utc: Optional[FrozenSet[int]] = None

    # ── Filtros de calidad ────────────────────────────────────────────────────
    require_candle_close: bool = False
    min_atr_pct: float = 0.001        # Stocks tienen menor ATR/precio que crypto

    # ── xsignals boost ────────────────────────────────────────────────────────
    # xsignal_profiles: cuentas de X relevantes para este ticker
    # Si tienen señal alineada en las últimas 48h, se agrega boost al score
    xsignal_profiles: tuple = ()
    xsignal_boost: int = 15           # puntos extra al score si hay señal alineada

    # ── Macro filter ─────────────────────────────────────────────────────────
    # Si True, bloquear BUY cuando SPY+QQQ están en BEAR (macro_bias='BEAR')
    use_macro_filter: bool = True

    # ── Estrategia de scoring ─────────────────────────────────────────────────
    # 'MOMENTUM'  → StocksMomentumStrategy  (NVDA, TSLA, AAPL, META, AMZN)
    # 'TREND_ETF' → StocksTrendEtfStrategy  (SPY, QQQ, GLD, EWZ, EEM, FXI, EWJ)
    strategy_name: str = 'MOMENTUM'

    # ── Filtro de régimen ─────────────────────────────────────────────────────
    # classify_market_regime() está calibrado para crypto/acciones volátiles.
    # Para ETFs índice (SPY, QQQ, EWJ, EEM...) clasifica RANGE el 90% del tiempo
    # bloqueando todas las señales BUY. Desactivar para activos con baja volatilidad.
    use_regime_filter: bool = True

    notes: str = ''


# ══════════════════════════════════════════════════════════════════════════════
#  Perfiles por acción — portafolio inicial 8 activos
# ══════════════════════════════════════════════════════════════════════════════

STOCKS_PROFILES: dict[str, StocksProfile] = {

    # ── NVDA ──────────────────────────────────────────────────────────────────
    # Mayor momentum 2024-26, ATR alto para stocks (~2-4%), muchas señales X
    # Permite ambas direcciones — tendencia alcista fuerte pero con pullbacks pronunciados
    'NVDA': StocksProfile(
        symbol='NVDA',
        confluence_min=3,
        allowed_directions=frozenset({'BUY', 'SELL'}),
        sl_multiplier=1.2,
        tp_multiplier=2.5,
        trailing_activation_r=0.75,
        trailing_step_r=0.30,
        trailing_offset_r=0.70,
        min_atr_pct=0.008,
        xsignal_profiles=('unusual_whales', 'aguti00'),
        xsignal_boost=15,
        use_macro_filter=True,
        notes='Máximo momentum 2024-26. SL 1.2 para aguantar noise. xsignals de unusual_whales y aguti00.',
    ),

    # ── TSLA ──────────────────────────────────────────────────────────────────
    # Máxima volatilidad en el universo (ATR 3-6%). Muchas señales X de aguti00
    # SL más amplio para evitar stops en el noise de TSLA
    'TSLA': StocksProfile(
        symbol='TSLA',
        confluence_min=3,
        allowed_directions=frozenset({'BUY', 'SELL'}),
        sl_multiplier=1.3,      # más amplio por volatilidad extrema
        tp_multiplier=2.8,      # mayor TP porque se mueve más
        trailing_activation_r=1.0,
        trailing_step_r=0.35,
        trailing_offset_r=0.80,
        min_atr_pct=0.010,
        xsignal_profiles=('aguti00',),
        xsignal_boost=15,
        use_macro_filter=True,
        notes='Altísima volatilidad. SL amplio para evitar stop hunting. aguti00 menciona TSLA 12 veces en 300 tweets.',
    ),

    # ── AAPL ──────────────────────────────────────────────────────────────────
    # Liquidez máxima, ATR estable (~1%), movimientos predecibles
    # Reduce SL porque el ruido es menor que NVDA/TSLA
    'AAPL': StocksProfile(
        symbol='AAPL',
        confluence_min=3,
        allowed_directions=frozenset({'BUY', 'SELL'}),
        sl_multiplier=1.0,
        tp_multiplier=2.0,
        trailing_activation_r=0.75,
        trailing_step_r=0.25,
        trailing_offset_r=0.55,
        min_atr_pct=0.006,  # v3: 0.004→0.006 (filtrar ruido — SL a 1.0×ATR muy ceñido)
        xsignal_profiles=('deitaone',),
        xsignal_boost=10,
        use_macro_filter=True,
        notes='Máxima liquidez, menor volatilidad. SL ajustado 1.0 ATR.',
    ),

    # ── SPY ───────────────────────────────────────────────────────────────────
    # ETF S&P500 — gauge macro + hedge. Muy bajo ATR (~0.5%)
    # Solo BUY en bull market, solo SELL en bear market
    'SPY': StocksProfile(
        symbol='SPY',
        confluence_min=3,
        allowed_directions=frozenset({'BUY', 'SELL'}),
        sl_multiplier=0.9,
        tp_multiplier=1.8,
        min_atr_pct=0.004,  # v3: 0.002→0.004 (SPY con 0.2% ATR es ruido — filtrar)
        strategy_name='TREND_ETF',
        use_regime_filter=False,
        notes='ETF S&P500. Gauge macro. No aplica filtro macro (es el propio macro).',
    ),

    # ── QQQ ───────────────────────────────────────────────────────────────────
    # ETF NASDAQ — tech momentum index. Similar a SPY pero más volátil
    'QQQ': StocksProfile(
        symbol='QQQ',
        confluence_min=3,
        allowed_directions=frozenset({'BUY', 'SELL'}),
        sl_multiplier=1.0,
        tp_multiplier=2.0,
        min_atr_pct=0.005,  # v3: 0.003→0.005 (QQQ con 0.3% ATR es ruido — filtrar)
        strategy_name='TREND_ETF',
        use_regime_filter=False,
        notes='ETF NASDAQ. Tech momentum index. xsignals unusual_whales.',
    ),

    # ── META ──────────────────────────────────────────────────────────────────
    # Fuerte momentum, movimientos bien definidos, aguti00 menciona 13 veces
    'META': StocksProfile(
        symbol='META',
        confluence_min=3,
        allowed_directions=frozenset({'BUY', 'SELL'}),
        sl_multiplier=1.1,
        tp_multiplier=2.3,
        min_atr_pct=0.006,
        xsignal_profiles=('aguti00',),
        xsignal_boost=15,
        use_macro_filter=True,
        notes='Momentum fuerte. aguti00 menciona META 13 veces en el análisis.',
    ),

    # ── AMZN ──────────────────────────────────────────────────────────────────
    # Tendencias claras, bien cubierto por xsignals
    'AMZN': StocksProfile(
        symbol='AMZN',
        confluence_min=3,
        allowed_directions=frozenset({'BUY', 'SELL'}),
        sl_multiplier=1.1,
        tp_multiplier=2.3,
        min_atr_pct=0.005,
        xsignal_profiles=('unusual_whales', 'aguti00'),
        xsignal_boost=12,
        use_macro_filter=True,
        notes='Tendencias claras. Cubierto por unusual_whales y aguti00.',
    ),

    # ── GLD ───────────────────────────────────────────────────────────────────
    # ETF Oro — correlaciona con XAU que ya opera el bot crypto
    # Mayor spread → SL un poco más amplio; horario más amplio (commodities)
    'GLD': StocksProfile(
        symbol='GLD',
        confluence_min=3,
        allowed_directions=frozenset({'BUY', 'SELL'}),
        sl_multiplier=1.0,
        tp_multiplier=2.0,
        min_atr_pct=0.003,
        xsignal_profiles=('fxhedgers',),
        xsignal_boost=10,
        use_macro_filter=False,  # Oro es hedge — se mueve opuesto al macro
        strategy_name='TREND_ETF',
        use_regime_filter=False,
        notes='ETF Oro. Correlación con XAU. fxhedgers cubre commodities/forex.',
    ),

    # ═══════════════════════════════════════════════════════════════════════════
    # ETFs INTERNACIONALES — Exposición a mercados fuera de USA
    # Todos operan en NYSE (misma API Alpaca, mismo horario)
    # ═══════════════════════════════════════════════════════════════════════════

    # ── EWZ ───────────────────────────────────────────────────────────────────
    # iShares Brasil — alta volatilidad commodity-driven
    # Correlado con petróleo (Petrobras ~20% del ETF) y riesgo político
    # SL amplio igual que TSLA: gaps frecuentes en apertura
    # blocked_hours primeros 30min: el gap de apertura es ruido puro
    'EWZ': StocksProfile(
        symbol='EWZ',
        confluence_min=3,
        allowed_directions=frozenset({'BUY', 'SELL'}),
        sl_multiplier=1.3,
        tp_multiplier=2.6,
        min_atr_pct=0.006,
        blocked_hours_utc=frozenset({14}),   # 14:30-14:59 UTC = primeros 30min NYSE
        xsignal_profiles=(),
        xsignal_boost=0,
        use_macro_filter=True,   # Muy correlado con risk-on/off global
        strategy_name='TREND_ETF',
        use_regime_filter=False,
        notes='Brasil. Alta vol commodity/político. SL=1.3 para gaps. Bloqueado primera media hora.',
    ),

    # ── EEM ───────────────────────────────────────────────────────────────────
    # iShares Emergentes — basket diversificado (China 28%, India 18%, Korea 12%)
    # Volatilidad media, muy sensible al USD y tasas de la Fed
    # En BEAR macro cae más que SPY → macro filter estricto
    'EEM': StocksProfile(
        symbol='EEM',
        confluence_min=3,
        allowed_directions=frozenset({'BUY', 'SELL'}),
        sl_multiplier=1.1,
        tp_multiplier=2.2,
        min_atr_pct=0.004,
        xsignal_profiles=(),
        xsignal_boost=0,
        use_macro_filter=True,
        strategy_name='TREND_ETF',
        use_regime_filter=False,
        notes='Emergentes. USD-sensible. Cae más que SPY en BEAR. Confluence estricta.',
    ),

    # ── FXI ───────────────────────────────────────────────────────────────────
    # iShares China Large Cap — máxima volatilidad geopolítica
    # Gaps fuertes por noticias PBOC / regulación tech China overnight
    # SL más amplio (1.5) y ATR mínimo alto para filtrar noise
    # Solo operar si hay momentum claro: confluence_min=4
    'FXI': StocksProfile(
        symbol='FXI',
        confluence_min=4,            # más estricto por ruido geopolítico
        allowed_directions=frozenset({'BUY', 'SELL'}),
        sl_multiplier=1.5,
        tp_multiplier=2.8,
        min_atr_pct=0.007,           # solo operar si hay movimiento real
        blocked_hours_utc=frozenset({14}),   # evitar gap de apertura
        xsignal_profiles=(),
        xsignal_boost=0,
        use_macro_filter=True,
        strategy_name='TREND_ETF',
        use_regime_filter=False,
        notes='China. Máxima vol geopolítica. SL=1.5, confluence=4, ATR_min alto.',
    ),

    # ── EWJ ───────────────────────────────────────────────────────────────────
    # iShares Japón — baja volatilidad, correlado con Yen (JPY/USD)
    # Movimientos lentos y predecibles → SL ajustado, TP conservador
    # Riesgo: noticias BOJ overnight pueden crear gaps pequeños
    'EWJ': StocksProfile(
        symbol='EWJ',
        confluence_min=3,
        allowed_directions=frozenset({'BUY', 'SELL'}),
        sl_multiplier=0.9,
        tp_multiplier=1.8,
        min_atr_pct=0.003,
        xsignal_profiles=(),
        xsignal_boost=0,
        use_macro_filter=True,
        strategy_name='TREND_ETF',
        use_regime_filter=False,
        notes='Japón. Baja vol, JPY-correlado. SL=0.9 ajustado. Movimientos lentos y limpios.',
    ),

    # ── SLV ───────────────────────────────────────────────────────────────────
    # iShares Silver Trust — ETF de plata física
    # Backtest 24m: WR=37.2%, PF=1.31 ✓, PnL=+$140 (+63.7%), MaxDD=14.3%
    # Mayor volatilidad que GLD (~1.5x): SL/TP ligeramente más anchos
    # Correlado con oro y DXY; reacciona también a demanda industrial
    # use_macro_filter=False: plata es hedge, se mueve opuesto al ciclo macro
    'SLV': StocksProfile(
        symbol='SLV',
        confluence_min=3,
        allowed_directions=frozenset({'BUY', 'SELL'}),
        sl_multiplier=1.1,
        tp_multiplier=2.2,
        min_atr_pct=0.004,
        xsignal_profiles=('fxhedgers',),
        xsignal_boost=10,
        use_macro_filter=False,  # Plata es hedge como GLD — se mueve opuesto al macro
        strategy_name='TREND_ETF',
        use_regime_filter=False,
        notes='ETF Plata. Backtest 24m: PF=1.31, WR=37.2%, MaxDD=14.3%. Mayor vol que GLD, SL=1.1.',
    ),
}


def get_stocks_profile(symbol: str) -> StocksProfile:
    """Devuelve el perfil del símbolo. Fallback a perfil genérico si no existe."""
    sym = symbol.upper()
    if sym in STOCKS_PROFILES:
        return STOCKS_PROFILES[sym]
    return StocksProfile(
        symbol=sym,
        notes=f'Perfil genérico para {sym} — añadir a STOCKS_PROFILES para calibración fina',
    )


def stocks_direction_allowed(symbol: str, direction: str) -> bool:
    profile = get_stocks_profile(symbol)
    return direction in profile.allowed_directions


# Lista canónica de activos del portafolio de acciones
STOCKS_ASSETS = list(STOCKS_PROFILES.keys())

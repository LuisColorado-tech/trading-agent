"""
IndicatorEngine — Motor de indicadores técnicos.
Calcula EMA, RSI, MACD, Bollinger Bands, ATR, VWAP y volume
de forma determinística sobre DataFrames de OHLCV.
"""
import pandas as pd
import numpy as np
import ta
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class IndicatorSet:
    """Snapshot inmutable de todos los indicadores para un activo/timeframe."""
    asset: str
    timeframe: str
    close: float
    volume: float
    # Trend
    ema20: float
    ema50: float
    ema200: float
    # Momentum
    rsi: float
    macd: float
    macd_signal: float
    macd_hist: float
    # Volatility
    bb_upper: float
    bb_middle: float
    bb_lower: float
    bb_pct: float       # Posición del precio dentro de las bandas (0-1)
    bb_width: float     # Ancho relativo de las bandas
    atr: float
    atr_pct: float      # ATR como % del precio
    # Volume
    vwap: float
    vol_sma20: float
    vol_ratio: float    # Volumen actual / SMA20 (>1.5 = spike)
    # ADX (Average Directional Index)
    adx: float       # Fuerza de tendencia 0-100 (>25 = tendencia, <20 = rango)
    adx_pos: float   # DI+ (fuerza alcista)
    adx_neg: float   # DI- (fuerza bajista)
    # Derived
    trend_direction: str   # 'UP' | 'DOWN' | 'SIDEWAYS'
    trend_strength: float  # 0-1
    # Minervini daily indicators (defaults for non-daily timeframes)
    ema150: float = 0.0
    high_52w: float = 0.0
    # EMA Ribbon (defaults for non-ribbon timeframes)
    ema8: float = 0.0
    ema13: float = 0.0
    ema21: float = 0.0
    ema34: float = 0.0
    ema55: float = 0.0
    stoch_k: float = 0.0


class IndicatorEngine:
    """Calcula todos los indicadores técnicos de un DataFrame OHLCV."""

    @staticmethod
    def calculate(df: pd.DataFrame, asset: str, timeframe: str) -> Optional[IndicatorSet]:
        """
        Calcula indicadores sobre un DataFrame con columnas:
        open, high, low, close, volume.
        Requiere al menos 50 filas.
        """
        if len(df) < 50:
            return None

        c = df['close']
        v = df['volume']
        h = df['high']
        lo = df['low']

        # EMAs
        ema20 = ta.trend.ema_indicator(c, window=20).iloc[-1]
        ema50 = ta.trend.ema_indicator(c, window=50).iloc[-1]
        ema200 = (
            ta.trend.ema_indicator(c, window=200).iloc[-1]
            if len(df) >= 200
            else ema50
        )
        ema150 = (
            ta.trend.ema_indicator(c, window=150).iloc[-1]
            if len(df) >= 150
            else ema50
        )
        high_52w = float(h.max()) if len(df) > 0 else 0.0

        # EMA Ribbon (8, 13, 21, 34, 55)
        ema8 = ta.trend.ema_indicator(c, window=8).iloc[-1] if len(df) >= 8 else ema20
        ema13 = ta.trend.ema_indicator(c, window=13).iloc[-1] if len(df) >= 13 else ema20
        ema21 = ta.trend.ema_indicator(c, window=21).iloc[-1] if len(df) >= 21 else ema20
        ema34 = ta.trend.ema_indicator(c, window=34).iloc[-1] if len(df) >= 34 else ema20
        ema55 = ta.trend.ema_indicator(c, window=55).iloc[-1] if len(df) >= 55 else ema20

        # Stochastic
        stoch_k = ta.momentum.StochasticOscillator(high=h, low=lo, close=c, window=14, smooth_window=3).stoch().iloc[-1]
        stoch_k = float(stoch_k) if not np.isnan(stoch_k) else 50.0

        # RSI
        rsi = ta.momentum.rsi(c, window=14).iloc[-1]

        # MACD
        macd_obj = ta.trend.MACD(c)
        macd_val = macd_obj.macd().iloc[-1]
        macd_signal = macd_obj.macd_signal().iloc[-1]
        macd_hist = macd_obj.macd_diff().iloc[-1]

        # Bollinger Bands
        bb = ta.volatility.BollingerBands(c, window=20, window_dev=2)
        bb_upper = bb.bollinger_hband().iloc[-1]
        bb_lower = bb.bollinger_lband().iloc[-1]
        bb_middle = bb.bollinger_mavg().iloc[-1]
        bb_range = bb_upper - bb_lower
        bb_width = bb_range / bb_middle if bb_middle > 0 else 0.0
        bb_pct = (c.iloc[-1] - bb_lower) / bb_range if bb_range > 0 else 0.5

        # ATR
        atr = ta.volatility.average_true_range(h, lo, c, window=14).iloc[-1]
        atr_pct = atr / c.iloc[-1] if c.iloc[-1] > 0 else 0.0

        # VWAP (proxy intraday: rolling 20 velas)
        typical = (h + lo + c) / 3
        vol_sum = v.rolling(20).sum().iloc[-1]
        vwap = (
            (typical * v).rolling(20).sum().iloc[-1] / vol_sum
            if vol_sum > 0
            else c.iloc[-1]
        )

        # Volume
        vol_sma20 = v.rolling(20).mean().iloc[-1]
        vol_ratio = v.iloc[-1] / vol_sma20 if vol_sma20 > 0 else 1.0

        # Trend direction — v1.1: MACD confirmation for ambiguous EMA alignment.
        # When EMAs disagree with price or gap is tiny, MACD breaks the tie.
        macd_line_val = float(macd_obj.macd().iloc[-1])
        macd_signal_val = float(macd_obj.macd_signal().iloc[-1])
        macd_bullish = macd_line_val > macd_signal_val
        macd_bearish = macd_line_val < macd_signal_val
        
        if ema20 > ema50 and c.iloc[-1] > ema20:
            trend_direction = 'UP'
        elif ema20 < ema50 and c.iloc[-1] < ema20:
            trend_direction = 'DOWN'
        elif ema20 > ema50 and macd_bullish:
            # EMA bullish pero precio entre EMAs → MACD confirma UP
            trend_direction = 'UP'
        elif ema20 < ema50 and macd_bearish:
            # EMA bearish pero precio entre EMAs → MACD confirma DOWN
            trend_direction = 'DOWN'
        elif c.iloc[-1] < ema20 and c.iloc[-1] < ema50 and macd_bearish:
            # Precio bajo ambas EMAs + MACD bearish → DOWN débil
            trend_direction = 'DOWN'
        elif c.iloc[-1] > ema20 and c.iloc[-1] > ema50 and macd_bullish:
            # Precio sobre ambas EMAs + MACD bullish → UP débil
            trend_direction = 'UP'
        else:
            trend_direction = 'SIDEWAYS'

        # ADX — fuerza de tendencia (independiente de dirección)
        adx_obj = ta.trend.ADXIndicator(high=h, low=lo, close=c, window=14)
        adx_val = float(adx_obj.adx().iloc[-1])
        adx_pos = float(adx_obj.adx_pos().iloc[-1])
        adx_neg = float(adx_obj.adx_neg().iloc[-1])
        # ADX necesita ~28 barras para converger; si es NaN usar 0
        if not np.isfinite(adx_val):
            adx_val, adx_pos, adx_neg = 0.0, 0.0, 0.0

        # Trend strength: distancia EMA20/EMA50 normalizada por ATR
        trend_strength = min(abs(ema20 - ema50) / (atr * 5), 1.0) if atr > 0 else 0.0

        return IndicatorSet(
            asset=asset,
            timeframe=timeframe,
            close=float(c.iloc[-1]),
            volume=float(v.iloc[-1]),
            ema20=float(ema20),
            ema50=float(ema50),
            ema200=float(ema200),
            rsi=float(rsi),
            macd=float(macd_val),
            macd_signal=float(macd_signal),
            macd_hist=float(macd_hist),
            bb_upper=float(bb_upper),
            bb_middle=float(bb_middle),
            bb_lower=float(bb_lower),
            bb_pct=float(bb_pct),
            bb_width=float(bb_width),
            atr=float(atr),
            atr_pct=float(atr_pct),
            vwap=float(vwap),
            vol_sma20=float(vol_sma20),
            vol_ratio=float(vol_ratio),
            adx=adx_val,
            adx_pos=adx_pos,
            adx_neg=adx_neg,
            trend_direction=trend_direction,
            trend_strength=float(trend_strength),
            ema150=float(ema150),
            high_52w=float(high_52w),
            ema8=float(ema8),
            ema13=float(ema13),
            ema21=float(ema21),
            ema34=float(ema34),
            ema55=float(ema55),
            stoch_k=float(stoch_k),
        )

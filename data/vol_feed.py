"""
Volatility Feed — Datos de VIX y productos de volatilidad.

Fuentes:
  - yfinance: ^VIX (VIX spot), VXX, UVXY, SVXY
  - Yahoo Finance: VIX futures (^VX=F, ^VX1=F, etc.)
  - Cálculos: contango, percentiles, term structure

Uso:
  feed = VolFeed()
  vix = feed.get_vix_spot()
  percentile = feed.get_vix_percentile(window_days=252)
  contango = feed.get_contango_pct()
"""
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf


class VolFeed:
    """Feed de datos de volatilidad para estrategia VIX Mean Reversion."""

    VIX_TICKER = '^VIX'
    VIX_FUTURES_TICKER = '^VX=F'  # VIX futures 30-day
    PRODUCTS = {
        'SVXY': 'SVXY',   # ProShares Short VIX (inverso, -0.5×)
        'VXX': 'VXX',     # iPath Series B S&P 500 VIX (long vol, decay)
        'UVXY': 'UVXY',   # ProShares Ultra VIX (1.5× long vol)
        'VIXY': 'VIXY',   # ProShares VIX Mid-Term (long vol)
    }

    def __init__(self):
        self._vix_cache: Optional[pd.DataFrame] = None
        self._vix_last_fetch: float = 0
        self._cache_ttl = 300  # 5 minutos

    def _fetch_vix_data(self, period: str = '2y') -> pd.DataFrame:
        """Descarga datos históricos de VIX desde yfinance."""
        now = time.time()
        if self._vix_cache is not None and (now - self._vix_last_fetch) < self._cache_ttl:
            return self._vix_cache

        try:
            ticker = yf.Ticker(self.VIX_TICKER)
            df = ticker.history(period=period)
            if not df.empty:
                self._vix_cache = df
                self._vix_last_fetch = now
                return df
        except Exception:
            pass

        # Fallback: datos pre-descargados o generados
        if self._vix_cache is not None:
            return self._vix_cache
        return pd.DataFrame()

    def get_vix_spot(self) -> Optional[float]:
        """VIX spot actual (último close)."""
        df = self._fetch_vix_data(period='5d')
        if df.empty:
            return None
        return float(df['Close'].iloc[-1])

    def get_vix_history(self, days: int = 252) -> pd.Series:
        """Historial de VIX de los últimos N días."""
        df = self._fetch_vix_data(period=f'{max(days, 300)}d')
        if df.empty or len(df) < 2:
            return pd.Series(dtype=float)
        return df['Close'].iloc[-days:]

    def get_vix_percentile(self, window_days: int = 252) -> Optional[float]:
        """Percentil actual del VIX en los últimos N días.

        Returns:
            Percentil (0-100). >80 = VIX alto (pánico).
        """
        vix_now = self.get_vix_spot()
        history = self.get_vix_history(days=window_days)
        if vix_now is None or history.empty:
            return None
        percentile = (history < vix_now).sum() / len(history) * 100
        return round(percentile, 1)

    def get_vix_futures_term_structure(self) -> dict:
        """Term structure de futuros de VIX (spot vs front month).

        Returns:
            Dict con precios de VIX spot, M1, M2, M3 futures.
        """
        result = {'spot': self.get_vix_spot()}

        try:
            for i in range(1, 4):
                ticker_str = f'^VX{i}=F' if i > 1 else '^VX=F'
                t = yf.Ticker(ticker_str)
                df = t.history(period='5d')
                if not df.empty:
                    result[f'M{i}'] = float(df['Close'].iloc[-1])
        except Exception:
            pass

        return result

    def get_contango_pct(self) -> Optional[float]:
        """Calcula contango entre VIX spot y el futuro del mes front.

        Contango = (M1 - Spot) / Spot × 100%.
        Contango positivo: futuros más caros que spot → decay favorable.
        """
        ts = self.get_vix_futures_term_structure()
        spot = ts.get('spot')
        m1 = ts.get('M1')
        if spot and m1 and spot > 0:
            return (m1 - spot) / spot * 100
        return None

    def get_contango_annual_pct(self) -> Optional[float]:
        """Contango anualizado aproximado.

        El contango de 1 mes se anualiza ×12 para comparar con
        el decay de productos como SVXY (~20-40%/año en contango normal).
        """
        monthly = self.get_contango_pct()
        if monthly is None:
            return None
        return round(monthly * 12, 2)

    def get_product_price(self, ticker: str) -> Optional[float]:
        """Precio actual de un producto de volatilidad (SVXY, VXX, etc.)."""
        try:
            t = yf.Ticker(ticker)
            df = t.history(period='5d')
            if not df.empty:
                return float(df['Close'].iloc[-1])
        except Exception:
            pass
        return None

    def get_product_history(self, ticker: str, days: int = 252) -> pd.DataFrame:
        """Historial de precios de un producto de volatilidad."""
        try:
            t = yf.Ticker(ticker)
            df = t.history(period=f'{max(days, 300)}d')
            return df.iloc[-days:]
        except Exception:
            return pd.DataFrame()

    def get_vix_signal(self, entry_percentile: float = 80,
                       exit_percentile: float = 50) -> dict:
        """Genera señal de entrada/salida basada en percentil de VIX.

        Returns:
            Dict con señal, percentil actual, contango, y recomendación.
        """
        pct = self.get_vix_percentile()
        vix = self.get_vix_spot()
        contango = self.get_contango_annual_pct()

        signal = 'HOLD'
        reason = ''

        if pct is not None:
            if pct >= entry_percentile:
                signal = 'ENTRY'
                reason = f'VIX en percentil {pct} (>{entry_percentile}) — pánico'
            elif pct <= exit_percentile:
                signal = 'EXIT'
                reason = f'VIX en percentil {pct} (<{exit_percentile}) — complacencia'

        return {
            'signal': signal,
            'vix_spot': vix,
            'vix_percentile': pct,
            'contango_annual_pct': contango,
            'reason': reason,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }

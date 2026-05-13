"""
Pairs Feed — Datos de pares cointegrados.

Descarga OHLCV para ambas piernas del par, calcula:
  - Beta (hedge ratio) via regresión OLS rolling
  - Half-life del spread (mean reversion speed)
  - Z-score del spread actual
  - Señales de entrada/salida basadas en z-score
"""
import time as _time
from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf
from loguru import logger
from statsmodels.tsa.stattools import adfuller


class PairsFeed:
    """Feed de datos para estrategia Pairs Trading."""

    def __init__(self):
        self._cache: dict = {}
        self._cache_ttl = 300

    def _cached(self, key: str):
        """Retorna cached value si no expiró."""
        entry = self._cache.get(key)
        if entry and (_time.time() - entry['ts']) < self._cache_ttl:
            return entry['data']
        return None

    def _set_cache(self, key: str, data):
        self._cache[key] = {'ts': _time.time(), 'data': data}

    def get_pair_ohlcv(self, ticker_a: str, ticker_b: str,
                       source: str = 'alpaca', days: int = 400) -> pd.DataFrame:
        """Descarga OHLCV para ambas piernas del par y alinea índices.

        Returns:
            DataFrame con columnas close_a y close_b, index fecha.
        """
        cache_key = f'{ticker_a}_{ticker_b}_{source}_{days}'
        cached = self._cached(cache_key)
        if cached is not None:
            return cached

        try:
            period = f'{days}d'
            try:
                ta = yf.Ticker(ticker_a)
                tb = yf.Ticker(ticker_b)
                df_a = ta.history(period=period)
                df_b = tb.history(period=period)
            except Exception:
                return pd.DataFrame()

            if df_a.empty or df_b.empty:
                return pd.DataFrame()

            df_a.index = pd.to_datetime(df_a.index).tz_localize(None).normalize()
            df_b.index = pd.to_datetime(df_b.index).tz_localize(None).normalize()

            merged = pd.DataFrame({
                'close_a': df_a['Close'],
                'close_b': df_b['Close'],
            }).dropna()

            self._set_cache(cache_key, merged)
            return merged
        except Exception as e:
            logger.warning(f'PairsFeed.get_pair_ohlcv error: {e}')
            return pd.DataFrame()

    def calc_hedge_ratio(self, df: pd.DataFrame, window: int = 252) -> pd.Series:
        """Calcula beta (hedge ratio) rolling window via OLS.

        log(A) = alpha + beta * log(B) + epsilon
        Returns:
            Series con beta para cada día (NaN en warmup).
        """
        if len(df) < window or df.empty:
            return pd.Series(dtype=float)

        log_a = np.log(df['close_a'])
        log_b = np.log(df['close_b'])

        betas = pd.Series(np.nan, index=df.index, dtype=float)
        for i in range(window, len(df)):
            x = log_b.iloc[i - window:i].values
            y = log_a.iloc[i - window:i].values
            x_mean = x.mean()
            y_mean = y.mean()
            num = ((x - x_mean) * (y - y_mean)).sum()
            den = ((x - x_mean) ** 2).sum()
            if den != 0:
                betas.iloc[i] = num / den

        return betas

    def calc_spread(self, df: pd.DataFrame, beta: pd.Series) -> pd.Series:
        """Calcula el spread: log(A) - beta * log(B)."""
        log_a = np.log(df['close_a'])
        log_b = np.log(df['close_b'])
        return log_a - beta * log_b

    def calc_zscore(self, spread: pd.Series, window: int = 252) -> pd.Series:
        """Z-score rodante del spread. Usa min_periods para trabajar con datos parciales."""
        mean = spread.rolling(window=window, min_periods=max(60, window//4)).mean()
        std = spread.rolling(window=window, min_periods=max(60, window//4)).std()
        std = std.replace(0, np.nan)
        return (spread - mean) / std

    def calc_half_life(self, spread: pd.Series) -> Optional[float]:
        """Estima half-life del spread (días hasta revertir 50%).

        Usa regresión AR(1): spread_t = alpha + rho * spread_{t-1} + e
        Half-life = -ln(2) / ln(rho)
        """
        s = spread.dropna()
        if len(s) < 30:
            return None
        s_lag = s.shift(1).dropna()
        s_cur = s.iloc[1:]
        if len(s_cur) < 20:
            return None
        x = s_lag.values[-len(s_cur):]
        y = s_cur.values
        x_mean = x.mean()
        y_mean = y.mean()
        num = ((x - x_mean) * (y - y_mean)).sum()
        den = ((x - x_mean) ** 2).sum()
        if den == 0:
            return None
        rho = num / den
        if rho <= 0 or rho >= 1:
            return None
        return -np.log(2) / np.log(rho)

    def test_cointegration(self, df: pd.DataFrame, window: int = 252) -> Optional[float]:
        """Test de cointegración ADF sobre el spread.

        Returns:
            p-valor del test ADF. <0.05 sugiere cointegración.
        """
        if len(df) < window:
            return None
        beta = self.calc_hedge_ratio(df, window)
        spread = self.calc_spread(df, beta).dropna()
        if len(spread) < 30:
            return None
        try:
            result = adfuller(spread.values, maxlag=int(len(spread) ** 0.25))
            return result[1]  # p-value
        except Exception:
            return None

    def evaluate_pair(self, pair_name: str, profile,
                      days: int = 400) -> Optional[dict]:
        """Evalúa señal para un par completo.

        Returns:
            Dict con z-score actual, beta, half-life, señal y estadísticas.
        """
        cache_key = f'eval_{pair_name}_{days}'
        cached = self._cached(cache_key)
        if cached is not None:
            return cached

        df = self.get_pair_ohlcv(
            profile.asset_a, profile.asset_b,
            source=profile.source, days=days,
        )
        if df.empty or len(df) < profile.hedge_ratio_window:
            return None

        window = profile.hedge_ratio_window
        beta = self.calc_hedge_ratio(df, window)
        spread = self.calc_spread(df, beta)
        zscore = self.calc_zscore(spread, window)
        hl = self.calc_half_life(spread)

        z_now = float(zscore.iloc[-1]) if not zscore.empty and not pd.isna(zscore.iloc[-1]) else None
        beta_now = float(beta.iloc[-1]) if not beta.empty and not pd.isna(beta.iloc[-1]) else None

        # Señal
        signal = 'HOLD'
        reason = ''
        if z_now is not None:
            if z_now >= profile.z_entry:
                signal = 'ENTRY_LONG_SPREAD'  # A under, B over → long A, short B
                reason = f'z={z_now:.1f} > entry={profile.z_entry}'
            elif z_now <= -profile.z_entry:
                signal = 'ENTRY_SHORT_SPREAD'  # A over, B under → short A, long B
                reason = f'z={z_now:.1f} < -{profile.z_entry}'
            elif profile.z_exit >= 0 and abs(z_now) <= profile.z_exit:
                if z_now > 0:
                    signal = 'EXIT'
                    reason = f'z={z_now:.1f} revertido a {profile.z_exit}'

        result = {
            'pair': pair_name,
            'signal': signal,
            'z_score': round(z_now, 2) if z_now is not None else None,
            'beta': round(beta_now, 4) if beta_now is not None else None,
            'half_life_days': round(hl, 1) if hl is not None else None,
            'reason': reason,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'spread_mean': float(spread.mean()) if not spread.empty else None,
            'spread_std': float(spread.std()) if not spread.empty else None,
        }

        self._set_cache(cache_key, result)
        return result

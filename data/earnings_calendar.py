"""
earnings_calendar.py — Calendario de earnings para mega-cap stocks via yfinance.

Filtra por market cap > $100B y retorna próximas fechas de earnings.
Usa yfinance .calendar y .earnings_dates para obtener fechas históricas y futuras.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, Union
from dataclasses import dataclass, field

import pandas as pd

from loguru import logger


@dataclass
class EarningsEvent:
    ticker: str
    earnings_date: datetime
    fiscal_period: str = ''
    estimated_eps: Optional[float] = None
    reported_eps: Optional[float] = None
    surprise_pct: Optional[float] = None
    market_cap: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def is_upcoming(self) -> bool:
        return self.earnings_date > datetime.now(timezone.utc)

    @property
    def is_historical(self) -> bool:
        return self.earnings_date <= datetime.now(timezone.utc)


class EarningsCalendar:
    """Calendario de earnings usando yfinance."""

    MIN_MARKET_CAP = 100e9

    def __init__(self, min_market_cap: float = None):
        self.min_market_cap = min_market_cap or self.MIN_MARKET_CAP

    def _get_info(self, ticker: str) -> Optional[dict]:
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            info = t.info or {}
            return info
        except Exception as e:
            logger.warning(f"yfinance info error {ticker}: {e}")
            return None

    def get_market_cap(self, ticker: str) -> float:
        info = self._get_info(ticker)
        if not info:
            return 0.0
        return float(info.get('marketCap', 0) or 0)

    def get_next_earnings_date(self, ticker: str) -> Optional[datetime]:
        info = self._get_info(ticker)
        if not info:
            return None

        raw = info.get('earningsDate')
        if raw:
            try:
                return datetime.fromtimestamp(raw[0], tz=timezone.utc) if isinstance(raw, list) else datetime.fromtimestamp(raw, tz=timezone.utc)
            except (TypeError, OSError):
                return None

        raw_str = info.get('nextEarningsDate') or info.get('mostRecentQuarter')
        if raw_str:
            try:
                return datetime.fromisoformat(raw_str.replace('Z', '+00:00'))
            except (ValueError, TypeError):
                pass

        return None

    def get_calendar(self, ticker: str) -> Optional[dict]:
        info = self._get_info(ticker)
        if not info:
            return None

        return {
            'ticker': ticker,
            'market_cap': float(info.get('marketCap', 0) or 0),
            'next_earnings_date': info.get('earningsDate'),
            'earnings_quarterly_growth': info.get('earningsQuarterlyGrowth'),
            'revenue_growth': info.get('revenueGrowth'),
            'sector': info.get('sector', ''),
            'industry': info.get('industry', ''),
            'beta': info.get('beta'),
        }

    def get_upcoming_earnings(self, tickers: list[str]) -> list[EarningsEvent]:
        events = []
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(days=60)

        for ticker in tickers:
            info = self._get_info(ticker)
            if not info:
                continue

            mcap = float(info.get('marketCap', 0) or 0)
            if mcap < self.min_market_cap:
                logger.debug(f"{ticker}: market cap ${mcap:,.0f} < ${self.min_market_cap:,.0f} min, skip")
                continue

            date = self.get_next_earnings_date(ticker)
            if not date or date < now or date > cutoff:
                continue

            events.append(EarningsEvent(
                ticker=ticker,
                earnings_date=date,
                market_cap=mcap,
            ))

        events.sort(key=lambda e: e.earnings_date)
        return events

    def get_historical_earnings(self, ticker: str, years: int = 3) -> list[EarningsEvent]:
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            info = t.info or {}
            mcap = float(info.get('marketCap', 0) or 0) if info else 0.0

            df = t.earnings_dates
            if df is None or df.empty:
                logger.warning(f"{ticker}: sin datos de earnings_dates")
                return []

            start = datetime.now(timezone.utc) - timedelta(days=years * 365)
            if hasattr(df.index, 'tz') and df.index.tz is None:
                df.index = df.index.tz_localize(timezone.utc)
            df = df[df.index >= start]
            df = df.sort_index()

            events = []
            for idx, row in df.iterrows():
                if isinstance(row, pd.DataFrame):
                    row = row.iloc[0]
                events.append(EarningsEvent(
                    ticker=ticker,
                    earnings_date=idx.to_pydatetime() if hasattr(idx, 'to_pydatetime') else idx,
                    reported_eps=float(row.get('Reported EPS', 0) or 0) if hasattr(row, 'get') else 0,
                    surprise_pct=float(row.get('Surprise(%)', 0) or 0) if hasattr(row, 'get') else 0,
                    market_cap=mcap,
                ))

            return events
        except Exception as e:
            logger.warning(f"get_historical_earnings {ticker}: {e}")
            return []

    def filter_qualifying(self, tickers: list[str]) -> list[str]:
        qualifying = []
        for ticker in tickers:
            mcap = self.get_market_cap(ticker)
            if mcap >= self.min_market_cap:
                qualifying.append(ticker)
            else:
                logger.debug(f"{ticker}: market cap ${mcap:,.0f} < min, excluded")
        return qualifying

    def get_earnings_schedule(self, tickers: list[str], days_ahead: int = 30) -> list[dict]:
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(days=days_ahead)
        schedule = []

        for ticker in tickers:
            date = self.get_next_earnings_date(ticker)
            if not date or date < now or date > cutoff:
                continue

            mcap = self.get_market_cap(ticker)
            if mcap < self.min_market_cap:
                continue

            schedule.append({
                'ticker': ticker,
                'earnings_date': date.isoformat(),
                'days_away': (date - now).days,
                'market_cap': mcap,
            })

        schedule.sort(key=lambda x: x['days_away'])
        return schedule


def get_earnings_calendar() -> EarningsCalendar:
    return EarningsCalendar()

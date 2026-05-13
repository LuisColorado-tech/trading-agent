"""
options_chain_feed.py — Feed de cadena de opciones via Alpaca/yfinance.

Proporciona precios de opciones (calls/puts), implied volatility, Greeks
y strikes OTM para la estrategia Earnings Strangle.

Paper trading en Alpaca Options. Soporta formato OCC symbol y queries directas.
"""
import sys
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, Union
from dataclasses import dataclass, field

import numpy as np
from loguru import logger

sys.path.insert(0, '/opt/trading')


@dataclass
class OptionContract:
    symbol: str
    ticker: str
    strike: float
    option_type: str                     # 'call' or 'put'
    expiration: str                      # '2026-05-22'
    bid: float = 0.0
    ask: float = 0.0
    last: float = 0.0
    volume: int = 0
    open_interest: int = 0
    implied_volatility: float = 0.0
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    rho: float = 0.0
    stock_price: float = 0.0
    days_to_expiry: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def mid_price(self) -> float:
        return (self.bid + self.ask) / 2 if (self.bid + self.ask) > 0 else self.last

    @property
    def is_otm(self) -> bool:
        if self.option_type == 'call':
            return self.strike > self.stock_price
        return self.strike < self.stock_price

    @property
    def otm_pct(self) -> float:
        return abs(self.strike - self.stock_price) / self.stock_price if self.stock_price else 0


@dataclass
class StrangleQuote:
    ticker: str
    stock_price: float
    call: OptionContract
    put: OptionContract
    call_otm_pct: float = 0.0
    put_otm_pct: float = 0.0
    total_cost: float = 0.0
    total_iv: float = 0.0
    days_to_expiry: int = 0

    @property
    def breakeven_up(self) -> float:
        return self.call.strike + self.total_cost

    @property
    def breakeven_down(self) -> float:
        return self.put.strike - self.total_cost

    @property
    def breakeven_move_pct_up(self) -> float:
        return (self.breakeven_up - self.stock_price) / self.stock_price * 100 if self.stock_price else 0

    @property
    def breakeven_move_pct_down(self) -> float:
        return (self.stock_price - self.breakeven_down) / self.stock_price * 100 if self.stock_price else 0

    @property
    def cost_as_pct(self) -> float:
        return self.total_cost / self.stock_price * 100 if self.stock_price else 0


class OptionsChainFeed:
    """Feed de opciones usando Alpaca API + yfinance fallback."""

    ALPACA_OPTIONS_URL = 'https://paper-api.alpaca.markets'

    def __init__(self, paper: bool = True):
        self.paper = paper
        self.alpaca = None
        self._init_alpaca()

    def _init_alpaca(self):
        try:
            from core.alpaca_session_manager import get_alpaca_client
            self.alpaca = get_alpaca_client(is_paper=self.paper)
        except Exception as e:
            logger.warning(f"Alpaca client init fail (will use yfinance): {e}")

    def _get_stock_price(self, ticker: str) -> float:
        if self.alpaca:
            try:
                trade = self.alpaca.get_latest_trade(ticker)
                if trade and trade.get('p'):
                    return float(trade['p'])
            except Exception:
                pass

        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            df = t.history(period='5d')
            if not df.empty:
                return float(df['Close'].iloc[-1])
        except Exception:
            pass

        return 0.0

    def _calc_greeks_estimation(self, S: float, K: float, T: float, r: float,
                                sigma: float, option_type: str) -> dict:
        """Estima Greeks usando Black-Scholes (para paper/backtest)."""
        from math import exp, log, sqrt
        from scipy.stats import norm

        if T <= 0 or sigma <= 0 or S <= 0:
            return {'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0, 'rho': 0, 'iv': sigma}

        d1 = (log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt(T))
        d2 = d1 - sigma * sqrt(T)

        is_call = option_type.lower() == 'call'
        nd1 = norm.cdf(d1)
        nd2 = norm.cdf(d2)
        npd1 = norm.pdf(d1)

        if is_call:
            delta = nd1
            theta = (-S * npd1 * sigma / (2 * sqrt(T)) - r * K * exp(-r * T) * nd2) / 365
            rho_val = K * T * exp(-r * T) * nd2 / 100
        else:
            delta = nd1 - 1
            theta = (-S * npd1 * sigma / (2 * sqrt(T)) + r * K * exp(-r * T) * (1 - nd2)) / 365
            rho_val = -K * T * exp(-r * T) * (1 - nd2) / 100

        gamma = npd1 / (S * sigma * sqrt(T))
        vega = S * npd1 * sqrt(T) / 100

        return {
            'delta': round(delta, 4),
            'gamma': round(gamma, 4),
            'theta': round(theta, 4),
            'vega': round(vega, 4),
            'rho': round(rho_val, 4),
            'iv': sigma,
        }

    def get_option_chain(self, ticker: str, expiration: str = None,
                         strike_min: float = None, strike_max: float = None) -> list[OptionContract]:
        stock_price = self._get_stock_price(ticker)
        if not stock_price:
            return []

        contracts = self._fetch_alpaca_options(ticker, expiration)
        if not contracts:
            contracts = self._fetch_yfinance_options(ticker, expiration)

        result = []
        for c in contracts:
            strike = float(c.get('strike_price', 0) or c.get('strike', 0))
            if strike_min and strike < strike_min:
                continue
            if strike_max and strike > strike_max:
                continue

            exp = c.get('expiration_date', '') or c.get('expiration', '')
            days = (datetime.strptime(exp, '%Y-%m-%d').date() - datetime.now(timezone.utc).date()).days if exp else 0

            opt_type = c.get('type', '').lower() or c.get('option_type', '').lower()
            iv = float(c.get('implied_volatility', 0) or 0)
            if not iv:
                iv = self._estimate_iv_from_price(ticker, stock_price, strike, days, opt_type,
                                                  float(c.get('last', c.get('mid', 0)) or 0))

            result.append(OptionContract(
                symbol=c.get('symbol', ''),
                ticker=ticker,
                strike=strike,
                option_type=opt_type,
                expiration=exp,
                bid=float(c.get('bid', 0) or 0),
                ask=float(c.get('ask', 0) or 0),
                last=float(c.get('last', 0) or c.get('mid', 0) or 0),
                volume=int(c.get('volume', 0) or 0),
                open_interest=int(c.get('open_interest', 0) or 0),
                implied_volatility=iv,
                delta=float(c.get('delta', 0) or 0),
                gamma=float(c.get('gamma', 0) or 0),
                theta=float(c.get('theta', 0) or 0),
                vega=float(c.get('vega', 0) or 0),
                rho=float(c.get('rho', 0) or 0),
                stock_price=stock_price,
                days_to_expiry=days,
            ))

        return result

    def _fetch_alpaca_options(self, ticker: str, expiration: str = None) -> list:
        if not self.alpaca:
            return []

        try:
            params = {'underlying_symbols': ticker, 'status': 'active'}
            if expiration:
                params['expiration_date'] = expiration
            data = self.alpaca._get('/v2/options/contracts', base=self.ALPACA_OPTIONS_URL, params=params)
            contracts = data.get('option_contracts', []) if isinstance(data, dict) else []
            return [{**c, 'bid': 0, 'ask': 0} for c in contracts]
        except Exception as e:
            logger.debug(f"Alpaca options {ticker}: {e}")
            return []

    def _fetch_yfinance_options(self, ticker: str, expiration: str = None) -> list:
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)

            expirations = t.options
            if not expirations:
                return []

            if expiration:
                if expiration not in expirations:
                    return []
                exp_list = [expiration]
            else:
                exp_list = [e for e in expirations[:4]]

            contracts = []
            stock_price = self._get_stock_price(ticker)

            for exp in exp_list:
                chain = t.option_chain(exp)
                for side, df in [('call', chain.calls), ('put', chain.puts)]:
                    for _, row in df.iterrows():
                        contracts.append({
                            'symbol': f"{ticker}{exp.replace('-','')}{side[0].upper()}{int(row['strike'] * 1000):08d}",
                            'ticker': ticker,
                            'strike': float(row['strike']),
                            'option_type': side,
                            'expiration_date': exp,
                            'bid': float(row.get('bid', 0) or 0),
                            'ask': float(row.get('ask', 0) or 0),
                            'last': float(row.get('lastPrice', 0) or 0),
                            'volume': int(row.get('volume', 0) or 0),
                            'open_interest': int(row.get('openInterest', 0) or 0),
                            'implied_volatility': float(row.get('impliedVolatility', 0) or 0),
                            'delta': 0,
                            'gamma': 0,
                            'theta': 0,
                            'vega': 0,
                            'rho': 0,
                            'stock_price': stock_price,
                        })

            return contracts
        except Exception as e:
            logger.warning(f"yfinance options {ticker}: {e}")
            return []

    def _estimate_iv_from_price(self, ticker: str, S: float, K: float, days: int,
                                option_type: str, market_price: float) -> float:
        if not market_price or days <= 0 or S <= 0 or K <= 0:
            return 0.0

        from math import exp, log, sqrt
        from scipy.stats import norm

        T = days / 365
        r = 0.05
        sigma_guess = 0.50
        is_call = option_type.lower() == 'call'

        for _ in range(50):
            try:
                d1 = (log(S / K) + (r + 0.5 * sigma_guess ** 2) * T) / (sigma_guess * sqrt(T))
                d2 = d1 - sigma_guess * sqrt(T)
                nd1 = norm.cdf(d1)
                nd2 = norm.cdf(d2)

                if is_call:
                    price = S * nd1 - K * exp(-r * T) * nd2
                    vega = S * norm.pdf(d1) * sqrt(T)
                else:
                    price = K * exp(-r * T) * (1 - nd2) - S * (1 - nd1)
                    vega = S * norm.pdf(d1) * sqrt(T)

                diff = price - market_price
                if abs(diff) < 0.01:
                    return sigma_guess
                if vega < 1e-6:
                    break
                sigma_guess = sigma_guess - diff / vega
                sigma_guess = max(0.01, min(3.0, sigma_guess))
            except (ZeroDivisionError, ValueError):
                break

        return sigma_guess

    def find_otm_strangle(self, ticker: str, target_otm_pct: float = 0.05,
                          max_dte: int = 21) -> Optional[StrangleQuote]:
        stock_price = self._get_stock_price(ticker)
        if not stock_price:
            return None

        otm_strike_call = stock_price * (1 + target_otm_pct)
        otm_strike_put = stock_price * (1 - target_otm_pct)

        contracts = self.get_option_chain(ticker)
        if not contracts:
            return None

        calls = [c for c in contracts if c.option_type == 'call' and c.strike > stock_price
                 and 1 <= c.days_to_expiry <= max_dte]
        puts = [c for c in contracts if c.option_type == 'put' and c.strike < stock_price
                and 1 <= c.days_to_expiry <= max_dte]

        if not calls or not puts:
            return None

        best_call = min(calls, key=lambda c: abs(c.strike - otm_strike_call) + abs(c.days_to_expiry - 7))
        best_put = min(puts, key=lambda p: abs(p.strike - otm_strike_put) + abs(p.days_to_expiry - 7))

        total_cost = best_call.mid_price + best_put.mid_price
        total_iv = (best_call.implied_volatility + best_put.implied_volatility) / 2

        return StrangleQuote(
            ticker=ticker,
            stock_price=stock_price,
            call=best_call,
            put=best_put,
            call_otm_pct=(best_call.strike - stock_price) / stock_price,
            put_otm_pct=(stock_price - best_put.strike) / stock_price,
            total_cost=total_cost,
            total_iv=total_iv,
            days_to_expiry=best_call.days_to_expiry,
        )

    def get_iv_rank(self, ticker: str, days: int = 252) -> float:
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            df = t.history(period='1y')

            if df.empty or len(df) < 20:
                return 50.0

            df['returns'] = df['Close'].pct_change()
            rolling_std = df['returns'].rolling(20).std()
            annualized_vol = rolling_std * np.sqrt(252)

            if len(annualized_vol.dropna()) < 20:
                return 50.0

            current_vol = float(annualized_vol.iloc[-1])
            vol_min = float(annualized_vol.min())
            vol_max = float(annualized_vol.max())

            if vol_max - vol_min <= 0:
                return 50.0

            iv_rank = (current_vol - vol_min) / (vol_max - vol_min) * 100
            return round(max(0, min(100, iv_rank)), 1)
        except Exception as e:
            logger.warning(f"get_iv_rank {ticker}: {e}")
            return 50.0

    def estimate_strangle_cost(self, ticker: str, otm_pct: float = 0.05,
                                dte: int = 7) -> float:
        stock_price = self._get_stock_price(ticker)
        if not stock_price:
            return 0.0

        iv = self.get_iv_rank(ticker) / 100
        if iv <= 0:
            iv = 0.50

        from math import exp, log, sqrt
        from scipy.stats import norm

        r = 0.05
        T = dte / 365
        sigma = iv
        K_call = stock_price * (1 + otm_pct)
        K_put = stock_price * (1 - otm_pct)

        try:
            d1c = (log(stock_price / K_call) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt(T))
            call_price = stock_price * norm.cdf(d1c) - K_call * exp(-r * T) * norm.cdf(d1c - sigma * sqrt(T))

            d1p = (log(stock_price / K_put) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt(T))
            put_price = K_put * exp(-r * T) * norm.cdf(-d1p + sigma * sqrt(T)) - stock_price * norm.cdf(-d1p)

            return max(0, call_price + put_price)
        except (ZeroDivisionError, ValueError):
            return 0.0


def get_options_feed(paper: bool = True) -> OptionsChainFeed:
    return OptionsChainFeed(paper=paper)

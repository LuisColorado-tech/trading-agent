"""
EarningsStrangleStrategy — Estrategia de Strangle pre-earnings.

Flujo:
  1. Identificar próximos earnings de mega-cap tech (NVDA, TSLA, AAPL, META, AMZN)
  2. 1 día antes del earnings: comprar strangle (call OTM + put OTM)
  3. Las opciones tienen IV alto pre-earnings pero el movimiento suele superar la prima
  4. Cerrar 1 día después del earnings (ya pasó el evento)

Paper trading en Alpaca Options.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional
from enum import Enum


class StrangleState(Enum):
    PENDING = 'PENDING'
    ACTIVE = 'ACTIVE'
    CLOSED = 'CLOSED'
    CANCELLED = 'CANCELLED'


@dataclass
class EarningsStrangleSignal:
    ticker: str
    earnings_date: datetime
    strike_call: float
    strike_put: float
    stock_price: float
    call_price: float
    put_price: float
    total_cost: float
    cost_as_pct: float
    call_otm_pct: float
    put_otm_pct: float
    iv_rank: float
    days_before_earnings: int = 1
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def is_valid(self) -> bool:
        return (self.stock_price > 0 and self.total_cost > 0
                and self.call_price > 0 and self.put_price > 0)

    @property
    def breakeven_up(self) -> float:
        return self.strike_call + self.total_cost

    @property
    def breakeven_down(self) -> float:
        return self.strike_put - self.total_cost


@dataclass
class StranglePosition:
    ticker: str
    entry_time: str
    stock_price_entry: float
    strike_call: float
    strike_put: float
    call_cost: float
    put_cost: float
    total_cost: float
    capital_used: float
    call_otm_pct: float
    put_otm_pct: float
    iv_rank_at_entry: float
    earnings_date: str
    state: StrangleState = StrangleState.ACTIVE
    close_time: Optional[str] = None
    close_price: Optional[float] = None
    call_exit: float = 0.0
    put_exit: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    close_reason: str = ''


class EarningsStrangleStrategy:
    NAME = 'EARNINGS_STRANGLE'

    def __init__(self, config: dict):
        self.cfg = config
        self.assets = config.get('assets', ['NVDA', 'TSLA', 'AAPL', 'META', 'AMZN'])
        self.otm_pct = config.get('otm_pct', 0.05)
        self.days_before = config.get('days_before', 1)
        self.days_after = config.get('days_after', 1)
        self.max_position_pct = config.get('max_position_pct', 0.05)
        self.stop_loss_pct = config.get('stop_loss_pct', 0.50)
        self.take_profit_pct = config.get('take_profit_pct', 0.80)
        self.min_market_cap = config.get('min_market_cap', 100e9)
        self.max_iv_rank = config.get('max_iv_rank', 90)
        self.min_iv_rank = config.get('min_iv_rank', 40)

    def evaluate(self, ticker: str, stock_price: float,
                 earnings_date: datetime, iv_rank: float,
                 call_strike: float, call_price: float,
                 put_strike: float, put_price: float,
                 profile_cost_as_pct: float = None) -> Optional[EarningsStrangleSignal]:
        now = datetime.now(timezone.utc)
        days_to_earnings = (earnings_date - now).days if earnings_date.tzinfo else (earnings_date.replace(tzinfo=timezone.utc) - now).days

        if days_to_earnings > self.days_before or days_to_earnings < 0:
            return None
        if stock_price <= 0:
            return None

        total_cost = call_price + put_price
        if total_cost <= 0:
            return None

        cost_pct = total_cost / stock_price

        if iv_rank < self.min_iv_rank:
            return None
        if iv_rank > self.max_iv_rank:
            return None

        call_otm = (call_strike - stock_price) / stock_price
        put_otm = (stock_price - put_strike) / stock_price

        if call_otm < 0.01 or put_otm < 0.01:
            return None
        if call_otm > 0.20 or put_otm > 0.20:
            return None

        return EarningsStrangleSignal(
            ticker=ticker,
            earnings_date=earnings_date,
            strike_call=call_strike,
            strike_put=put_strike,
            stock_price=stock_price,
            call_price=call_price,
            put_price=put_price,
            total_cost=total_cost,
            cost_as_pct=cost_pct,
            call_otm_pct=call_otm,
            put_otm_pct=put_otm,
            iv_rank=iv_rank,
            days_before_earnings=days_to_earnings,
        )

    def calculate_position_size(self, capital: float, stock_price: float,
                                 total_cost: float) -> int:
        max_capital = capital * self.max_position_pct
        max_contracts = int(max_capital / (total_cost * 100))
        return max(1, min(max_contracts, 5))

    def calculate_pnl(self, position: StranglePosition, current_price: float,
                      call_mid: float = 0, put_mid: float = 0) -> float:
        if call_mid > 0 and put_mid > 0:
            return (call_mid + put_mid - position.total_cost) * 100
        return 0.0

    def should_close(self, position: StranglePosition, current_price: float,
                     earnings_passed: bool = False, call_mid: float = 0,
                     put_mid: float = 0) -> tuple[bool, str]:
        current_value = call_mid + put_mid if (call_mid + put_mid) > 0 else position.total_cost
        pnl_pct = (current_value - position.total_cost) / position.total_cost if position.total_cost else 0

        if pnl_pct <= -self.stop_loss_pct:
            return True, 'STOP_LOSS'
        if pnl_pct >= self.take_profit_pct:
            return True, 'TAKE_PROFIT'

        if earnings_passed:
            if pnl_pct > 0:
                return True, 'EARNINGS_PASSED_PROFIT'
            return True, 'EARNINGS_PASSED_LOSS'

        return False, ''

    def estimate_pnl_post_earnings(self, stock_price_before: float,
                                    stock_price_after: float,
                                    strike_call: float, strike_put: float,
                                    total_cost: float) -> float:
        call_value = max(0, stock_price_after - strike_call)
        put_value = max(0, strike_put - stock_price_after)
        strangle_value = (call_value + put_value) * 100
        cost_total = total_cost * 100
        return strangle_value - cost_total

    def expected_return(self, avg_move_pct: float, otm_pct: float,
                        cost_pct: float) -> float:
        excess_move = avg_move_pct - otm_pct
        if excess_move <= 0:
            return -cost_pct
        return (excess_move / 100) - cost_pct

    def should_enter(self, ticker: str, earnings_date: datetime,
                     avg_historical_move: float) -> tuple[bool, str]:
        now = datetime.now(timezone.utc)
        if earnings_date.tzinfo is None:
            earnings_date = earnings_date.replace(tzinfo=timezone.utc)
        days_to_earnings = (earnings_date - now).days

        if days_to_earnings != self.days_before:
            return False, f'days_to_earnings={days_to_earnings}'

        from core.earnings_profiles import get_earnings_profile
        profile = get_earnings_profile(ticker)
        if avg_historical_move < profile.min_avg_move_pct:
            return False, f'avg_move={avg_historical_move:.1f}% < min={profile.min_avg_move_pct:.1f}%'

        return True, ''

    def get_earnings_move_stats(self, earnings_dates: list, price_history: list) -> dict:
        moves = []
        for ed in earnings_dates:
            if ed.get('price_before') and ed.get('price_after'):
                move = abs(ed['price_after'] - ed['price_before']) / ed['price_before']
                moves.append(move)

        if not moves:
            return {'avg_move_pct': 5.0, 'max_move_pct': 10.0, 'min_move_pct': 2.0,
                    'above_5pct_ratio': 0.5, 'n_events': 0}

        return {
            'avg_move_pct': round(sum(moves) / len(moves) * 100, 1),
            'max_move_pct': round(max(moves) * 100, 1),
            'min_move_pct': round(min(moves) * 100, 1),
            'above_5pct_ratio': round(sum(1 for m in moves if m > 0.05) / len(moves), 2),
            'n_events': len(moves),
        }

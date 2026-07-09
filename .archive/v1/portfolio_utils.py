"""
Helpers puros para mantener coherencia en el estado del portfolio.
"""
from typing import Iterable, Mapping, Optional


def calculate_risk_exposure(open_trades: Iterable[Mapping]) -> float:
    return sum(
        abs(float(trade['entry_price']) - float(trade['stop_loss'])) * float(trade['position_size'])
        for trade in open_trades
    )


def calculate_total_notional(open_trades: Iterable[Mapping]) -> float:
    return sum(
        float(trade['entry_price']) * float(trade['position_size'])
        for trade in open_trades
    )


def calculate_peak_balance(balance: float, *candidate_peaks: Optional[float], floor: float = 0.0) -> float:
    peak_candidates = [balance, floor]
    peak_candidates.extend(float(peak) for peak in candidate_peaks if peak is not None)
    return max(peak_candidates) if peak_candidates else balance


def calculate_drawdown(balance: float, peak_balance: float) -> float:
    if peak_balance <= 0:
        return 0.0
    return max(0.0, (peak_balance - balance) / peak_balance)


def build_portfolio_state(
    balance: float,
    open_trades: Iterable[Mapping],
    latest_peak_balance: Optional[float] = None,
    historical_peak_balance: Optional[float] = None,
    historical_max_drawdown: float = 0.0,
    halt_triggered: bool = False,
    initial_capital: float = 0.0,
) -> dict:
    peak_balance = calculate_peak_balance(
        balance,
        latest_peak_balance,
        historical_peak_balance,
        floor=initial_capital,
    )
    exposure_value = calculate_risk_exposure(open_trades)
    total_notional = calculate_total_notional(open_trades)
    drawdown_pct = calculate_drawdown(balance, peak_balance)

    return {
        'total_balance': balance,
        'available_cash': balance - exposure_value,   # Fase 5: usar exposicion de RIESGO, no notional
        'exposure_pct': exposure_value / balance if balance > 0 else 0.0,
        'drawdown_pct': drawdown_pct,
        'peak_balance': peak_balance,
        'historical_max_drawdown': max(float(historical_max_drawdown or 0.0), drawdown_pct),
        'halt_triggered': bool(halt_triggered),
        'recommended_action': 'MAINTAIN_HALT' if halt_triggered else 'NORMAL',
    }
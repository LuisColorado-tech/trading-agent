"""
EarningsProfile — Perfiles de acciones para Earnings Strangle.

Define parámetros OTM%, DTE, SL%, TP% y capital allocation
para cada acción mega-cap del universo de earnings.
"""
from dataclasses import dataclass
from typing import Optional, FrozenSet


@dataclass(frozen=True)
class EarningsProfile:
    ticker: str
    description: str
    sector: str = 'Technology'

    otm_pct_call: float = 0.06
    otm_pct_put: float = 0.06
    target_dte: int = 7

    max_position_pct: float = 0.05
    stop_loss_pct: float = 0.50
    take_profit_pct: float = 0.80

    min_iv_rank: int = 40
    max_iv_rank: int = 90
    min_market_cap: float = 100e9

    min_avg_move_pct: float = 5.0

    notes: str = ''


EARNINGS_PROFILES: dict[str, EarningsProfile] = {

    'NVDA': EarningsProfile(
        ticker='NVDA',
        description='NVIDIA — AI/datacenter líder. Alta volatilidad post-earnings.',
        sector='Technology',
        otm_pct_call=0.06,
        otm_pct_put=0.06,
        target_dte=7,
        max_position_pct=0.05,
        stop_loss_pct=0.50,
        take_profit_pct=0.80,
        min_iv_rank=40,
        max_iv_rank=90,
        min_avg_move_pct=5.0,
        notes='NVDA promedia 8-10% de movimiento post-earnings. '
              'OTM 6% captura la mayoría de los movimientos. '
              'La prima suele ser alta pero el movimiento la supera.',
    ),

    'TSLA': EarningsProfile(
        ticker='TSLA',
        description='Tesla — Alta volatilidad, movimientos extremos en earnings.',
        sector='Consumer Cyclical',
        otm_pct_call=0.08,
        otm_pct_put=0.08,
        target_dte=7,
        max_position_pct=0.05,
        stop_loss_pct=0.50,
        take_profit_pct=0.80,
        min_iv_rank=40,
        max_iv_rank=90,
        min_avg_move_pct=6.0,
        notes='TSLA tiene movimientos más extremos (±10-15%). '
              'OTM 8% para filtrar ruido y capturar los grandes swings. '
              'Es el activo más volátil del universo.',
    ),

    'AAPL': EarningsProfile(
        ticker='AAPL',
        description='Apple — Movimientos moderados. Empresa madura.',
        sector='Technology',
        otm_pct_call=0.04,
        otm_pct_put=0.04,
        target_dte=7,
        max_position_pct=0.05,
        stop_loss_pct=0.50,
        take_profit_pct=0.80,
        min_iv_rank=40,
        max_iv_rank=90,
        min_avg_move_pct=3.5,
        notes='AAPL es la acción más estable del grupo. '
              'Movimientos post-earnings ~4-6%. OTM 4% más ajustado. '
              'Menor retorno esperado pero mayor consistencia.',
    ),

    'META': EarningsProfile(
        ticker='META',
        description='Meta — Alta volatilidad tech. Earnings impactantes.',
        sector='Communication Services',
        otm_pct_call=0.06,
        otm_pct_put=0.06,
        target_dte=7,
        max_position_pct=0.05,
        stop_loss_pct=0.50,
        take_profit_pct=0.80,
        min_iv_rank=40,
        max_iv_rank=90,
        min_avg_move_pct=5.0,
        notes='META históricamente mueve 7-10% post-earnings. '
              'OTM 6% balance entre costo y probabilidad de ITM.',
    ),

    'AMZN': EarningsProfile(
        ticker='AMZN',
        description='Amazon — Moderate volatility, AWS growth focus.',
        sector='Consumer Cyclical',
        otm_pct_call=0.05,
        otm_pct_put=0.05,
        target_dte=7,
        max_position_pct=0.05,
        stop_loss_pct=0.50,
        take_profit_pct=0.80,
        min_iv_rank=40,
        max_iv_rank=90,
        min_avg_move_pct=4.5,
        notes='AMZN mueve 5-8% post-earnings. '
              'OTM 5% estándar para capturar movimiento sin pagar demasiada prima.',
    ),

}


def get_earnings_profile(ticker: str) -> EarningsProfile:
    if ticker in EARNINGS_PROFILES:
        return EARNINGS_PROFILES[ticker]
    return EarningsProfile(
        ticker=ticker,
        description=f'Perfil genérico para {ticker}',
        otm_pct_call=0.06,
        otm_pct_put=0.06,
        target_dte=7,
        max_position_pct=0.05,
        stop_loss_pct=0.50,
        take_profit_pct=0.80,
        min_iv_rank=40,
        max_iv_rank=90,
        min_avg_move_pct=5.0,
        notes=f'Perfil no calibrado para {ticker}. Ajustar con backtest.',
    )

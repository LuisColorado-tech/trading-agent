"""
VolProfile — Perfiles de productos de volatilidad.

Define parámetros de trading para SVXY, VXX, UVXY, VIXY:
  - SL/TP
  - Tamaño máximo de posición
  - Filtros de entrada/salida
  - Decay esperado (contango beneficia a SVXY)
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class VolProfile:
    ticker: str                      # SVXY, VXX, UVXY, VIXY
    description: str

    # Dirección de la operación
    direction: str = 'LONG'          # LONG para SVXY (short vol), SHORT para VXX/UVXY

    # Tamaño y riesgo
    max_position_pct: float = 0.10   # % del capital
    stop_loss_pct: float = 0.15      # -15% en el activo
    take_profit_pct: float = 0.25    # +25% en el activo

    # Filtros de entrada
    min_vix_percentile: int = 80     # VIX > percentil 80 para entrar
    exit_vix_percentile: int = 50    # VIX < percentil 50 para salir
    min_contango_annual_pct: float = 20.0  # Contango mínimo para SVXY

    # Time management
    max_hold_days: int = 60          # Días máximo en posición

    notes: str = ''


VOL_PROFILES: dict[str, VolProfile] = {

    'SVXY': VolProfile(
        ticker='SVXY',
        description='ProShares Short VIX Short-Term Futures ETF (-0.5x inverso)',
        direction='LONG',
        max_position_pct=0.10,
        stop_loss_pct=0.15,
        take_profit_pct=0.25,
        min_vix_percentile=80,
        exit_vix_percentile=50,
        min_contango_annual_pct=20.0,
        max_hold_days=60,
        notes='Estrategia principal. Long SVXY cuando VIX alto. '
              'Se beneficia del contango (decay de futuros VIX). '
              'El decay normal es ~20-40%/año favorable para SVXY.',
    ),

    'VXX': VolProfile(
        ticker='VXX',
        description='iPath Series B S&P 500 VIX Short-Term Futures ETN',
        direction='SHORT',
        max_position_pct=0.05,
        stop_loss_pct=0.15,
        take_profit_pct=0.20,
        min_vix_percentile=80,
        exit_vix_percentile=50,
        min_contango_annual_pct=20.0,
        max_hold_days=30,
        notes='Short VXX = same direction as long SVXY. Decay natural '
              'de VXX (~30-60%/año) da edge adicional. Pero más volátil.',
    ),

    'UVXY': VolProfile(
        ticker='UVXY',
        description='ProShares Ultra VIX Short-Term Futures ETF (1.5x long vol)',
        direction='SHORT',
        max_position_pct=0.03,
        stop_loss_pct=0.12,
        take_profit_pct=0.15,
        min_vix_percentile=85,
        exit_vix_percentile=55,
        min_contango_annual_pct=25.0,
        max_hold_days=21,
        notes='SHORT UVXY = high decay. 1.5× leverage acelera decay (~50-80%/año). '
              'Requiere VIX muy alto (percentil 85+) y SL más ceñido. '
              'Solo paper — tamaño pequeño por alta volatilidad.',
    ),
}


def get_vol_profile(ticker: str) -> VolProfile:
    """Retorna perfil del producto o un perfil conservador por defecto."""
    if ticker in VOL_PROFILES:
        return VOL_PROFILES[ticker]
    return VolProfile(
        ticker=ticker,
        description=f'Perfil genérico conservador para {ticker}',
        notes=f'Perfil no calibrado. Usar con precaución.',
    )

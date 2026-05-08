#!/usr/bin/env python3
"""
Backtest VIX Mean Reversion — Simula estrategia de volatilidad.

Evalúa la estrategia de long SVXY (short vol) cuando VIX > percentil 80.
Usa datos históricos de yfinance (5 años).

Calcula:
  - Número de trades y WR
  - PnL acumulado
  - Sharpe, Profit Factor, Max Drawdown
  - Comparación con buy & hold SVXY
"""
import os
import sys
import argparse
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')

import yaml
import pandas as pd
import numpy as np
from loguru import logger

from data.vol_feed import VolFeed
from strategies.vol_mean_reversion import VolMeanReversionStrategy, VolPosition


def load_config():
    with open('/opt/trading/config/exchange_config.yaml') as f:
        return yaml.safe_load(f).get('vol_mean_reversion', {})


def run_backtest(config: dict, years: float = 5.0):
    """Ejecuta backtest completo de la estrategia."""
    feed = VolFeed()
    strategy = VolMeanReversionStrategy(config)
    capital = config.get('initial_balance', 1000.0)
    assets = strategy.assets

    print(f"\n{'='*60}")
    print(f"  BACKTEST VIX MEAN REVERSION ({years} años)")
    print(f"  Activos: {', '.join(assets)}")
    print(f"  Capital: ${capital:,.0f}")
    print(f"  Entry: VIX > p{strategy.entry_percentile}")
    print(f"  Exit: VIX < p{strategy.exit_percentile} | SL={strategy.stop_loss_pct*100:.0f}%")
    print(f"{'='*60}")

    for ticker in assets:
        trades = []
        print(f"\n  ── {ticker} ──")

        # Obtener datos históricos
        df = feed.get_product_history(ticker, days=int(years * 365))
        if df.empty:
            print(f"  Sin datos históricos para {ticker}")
            continue

        vix_history = feed.get_vix_history(days=int(years * 365))
        if vix_history.empty:
            print(f"  Sin datos de VIX históricos")
            continue

        # Alinear índices (normalizar timezone)
        vix_history.index = vix_history.index.tz_localize(None)
        df.index = df.index.tz_localize(None)
        common_idx = df.index.intersection(vix_history.index)
        if len(common_idx) < 30:
            print(f"  Datos insuficientes: {len(common_idx)} días")
            continue

        product_prices = df['Close'].reindex(common_idx)
        vix_prices = vix_history.reindex(common_idx)

        # Rolling percentile (252 días lookback)
        vix_percentile = vix_prices.rolling(252).apply(
            lambda x: (x.iloc[-1] > x.iloc[:-1]).sum() / (len(x) - 1) * 100
            if len(x) > 1 else 50
        ).fillna(50)

        # Simulación
        position: VolPosition = None
        trades = []
        balance = capital
        equity_curve = [capital]
        dates = [common_idx[0]]

        for i, ts in enumerate(common_idx):
            if i < 252:  # Necesitamos 252 días para el percentil
                continue

            price = product_prices.iloc[i]
            vix_pct = vix_percentile.iloc[i]
            prev_price = product_prices.iloc[i - 1]

            # Check SL/TP en posición abierta
            if position is not None:
                pnl_pct = (price - position.entry_price) / position.entry_price

                if pnl_pct <= -strategy.stop_loss_pct:
                    pnl = position.size * (price - position.entry_price)
                    trades.append({
                        'entry': position.entry_time,
                        'exit': str(ts),
                        'pnl': pnl,
                        'reason': 'STOP_LOSS',
                        'hold_days': (ts - pd.Timestamp(position.entry_time)).days,
                    })
                    balance += pnl
                    position = None
                elif pnl_pct >= 0.25:  # TP 25%
                    pnl = position.size * (price - position.entry_price)
                    trades.append({
                        'entry': position.entry_time,
                        'exit': str(ts),
                        'pnl': pnl,
                        'reason': 'TAKE_PROFIT',
                        'hold_days': (ts - pd.Timestamp(position.entry_time)).days,
                    })
                    balance += pnl
                    position = None
                elif vix_pct <= strategy.exit_percentile:
                    pnl = position.size * (price - position.entry_price)
                    trades.append({
                        'entry': position.entry_time,
                        'exit': str(ts),
                        'pnl': pnl,
                        'reason': 'VIX_NORMALIZED',
                        'hold_days': (ts - pd.Timestamp(position.entry_time)).days,
                    })
                    balance += pnl
                    position = None
                else:
                    hold_days = (ts - pd.Timestamp(position.entry_time)).days
                    if hold_days >= strategy.max_hold_days:
                        pnl = position.size * (price - position.entry_price)
                        trades.append({
                            'entry': position.entry_time,
                            'exit': str(ts),
                            'pnl': pnl,
                            'reason': 'MAX_HOLD',
                            'hold_days': hold_days,
                        })
                        balance += pnl
                        position = None

            # Señal de entrada
            if position is None and vix_pct >= strategy.entry_percentile:
                if np.isnan(price) or price <= 0:
                    continue
                size = strategy.calculate_position_size(balance, price)
                if size > 0:
                    position = VolPosition(
                        ticker=ticker,
                        entry_price=price,
                        size=size,
                        entry_time=str(ts),
                        vix_at_entry=float(vix_prices.iloc[i]),
                    )

            equity_curve.append(balance)
            dates.append(ts)

        # Cerrar posición final
        if position is not None:
            price = product_prices.iloc[-1]
            pnl = position.size * (price - position.entry_price)
            trades.append({
                'entry': position.entry_time,
                'exit': str(common_idx[-1]),
                'pnl': pnl,
                'reason': 'END_OF_BACKTEST',
                'hold_days': (common_idx[-1] - pd.Timestamp(position.entry_time)).days,
            })
            balance += pnl

        # Métricas
        n_trades = len(trades)
        n_wins = sum(1 for t in trades if t['pnl'] > 0)
        wr = (n_wins / n_trades * 100) if n_trades > 0 else 0
        total_pnl = sum(t['pnl'] for t in trades)
        avg_pnl = total_pnl / n_trades if n_trades > 0 else 0
        avg_hold = np.mean([t['hold_days'] for t in trades]) if n_trades else 0

        # Profit Factor
        gross_profit = sum(t['pnl'] for t in trades if t['pnl'] > 0)
        gross_loss = abs(sum(t['pnl'] for t in trades if t['pnl'] < 0))
        pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        # Max DD
        eq = np.array(equity_curve)
        peak = np.maximum.accumulate(eq)
        dd = (peak - eq) / peak * 100
        max_dd = float(np.max(dd))

        # Sharpe
        daily_returns = np.diff(eq) / eq[:-1]
        sharpe = (np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(252)) if len(daily_returns) > 1 and np.std(daily_returns) > 0 else 0

        # Buy & hold comparación
        buyhold_return = (product_prices.iloc[-1] / product_prices.iloc[252] - 1) * 100

        print(f"  Trades: {n_trades}")
        print(f"  Wins: {n_wins} | WR: {wr:.1f}%")
        print(f"  PnL Total: ${total_pnl:,.2f} ({total_pnl / capital * 100:.1f}%)")
        print(f"  Avg PnL/Trade: ${avg_pnl:,.2f}")
        print(f"  Avg Hold: {avg_hold:.0f} días")
        print(f"  Max DD: {max_dd:.1f}%")
        print(f"  Sharpe: {sharpe:.2f}")
        print(f"  Profit Factor: {pf:.2f}")
        print(f"  Buy & Hold SVXY: {buyhold_return:.1f}%")

        # Por año
        if n_trades > 0:
            trades_per_year = n_trades / years
            pnl_per_year = total_pnl / years
            annual_return = pnl_per_year / capital * 100
            print(f"  Trades/año: {trades_per_year:.0f}")
            print(f"  PnL/año: ${pnl_per_year:,.2f}")
            print(f"  Return anual: {annual_return:.1f}%")

    print(f"\n{'='*60}")
    print(f"  FIN BACKTEST VIX MEAN REVERSION")
    print(f"{'='*60}")

    return trades


def main():
    parser = argparse.ArgumentParser(description='Backtest VIX Mean Reversion Strategy')
    parser.add_argument('--years', type=float, default=5.0, help='Años de backtest')
    parser.add_argument('--capital', type=float, default=1000.0, help='Capital inicial')
    args = parser.parse_args()

    config = load_config()
    if not config:
        config = {
            'enabled': True,
            'paper_trading': True,
            'assets': ['SVXY'],
            'vix_entry_percentile': 80,
            'vix_exit_percentile': 50,
            'max_position_pct': 0.10,
            'stop_loss_pct': 0.15,
            'min_contango_annual_pct': 20.0,
            'max_hold_days': 60,
            'initial_balance': args.capital,
        }
    else:
        config['initial_balance'] = args.capital

    print(f"╔══════════════════════════════════════════╗")
    print(f"║  BACKTEST — VIX MEAN REVERSION          ║")
    print(f"║  {args.years} años | ${args.capital:,.0f} capital      ║")
    print(f"╚══════════════════════════════════════════╝")

    run_backtest(config, years=args.years)


if __name__ == '__main__':
    main()

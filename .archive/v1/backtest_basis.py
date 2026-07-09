#!/usr/bin/env python3
"""
Backtest Basis Trade — Simula estrategia de captura de funding rate.

Usa datos históricos de funding rate de Kraken Futures (vía API o
simulación con tasas promedio del mercado). Calcula:
  - Funding rate promedio histórico
  - Retorno anual estimado
  - Drawdown
  - Comparación con buy & hold

Paper trading — sin impacto en cuenta real.
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

from data.kraken_futures_feed import KrakenFuturesFeed
from strategies.basis_trade import BasisTradeStrategy


def load_config():
    with open('/opt/trading/config/exchange_config.yaml') as f:
        return yaml.safe_load(f).get('basis_trade', {})


def fetch_historical_funding(feed: KrakenFuturesFeed, asset: str) -> pd.DataFrame:
    """Intenta obtener funding histórico desde Kraken Futures API."""
    history = feed.get_funding_history(asset, limit=365 * 3)
    if history:
        df = pd.DataFrame(history)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.set_index('timestamp').sort_index()
        return df[['funding_rate']]

    print(f"[WARN] No historical funding data for {asset} from API. Generating synthetic data.")
    return generate_synthetic_funding(asset, days=365 * 2)


def generate_synthetic_funding(asset: str, days: int = 730) -> pd.DataFrame:
    """Genera funding rates sintéticos basados en promedios de mercado.

    BTC funding típico: 0.01% por intervalo (10.95% anual), con volatilidad.
    ETH funding: ligeramente menor, ~8% anual.
    """
    intervals_per_day = 3  # Cada 8 horas
    n = days * intervals_per_day
    dates = pd.date_range(end=datetime.now(timezone.utc), periods=n, freq='8h')

    if asset == 'BTC':
        base_rate = 0.0001  # 0.01% por intervalo
        std = 0.000025
    else:
        base_rate = 0.000073  # ~8% anual
        std = 0.000020

    np.random.seed(42)
    rates = np.random.normal(base_rate, std, n)
    rates = np.clip(rates, -0.0001, 0.0005)  # Floor -0.01%, Cap 0.05%

    return pd.DataFrame({'funding_rate': rates}, index=dates)


def run_backtest(config: dict, years: float = 2.0):
    """Ejecuta backtest de la estrategia de Basis Trade."""
    feed = KrakenFuturesFeed(paper=True)
    strategy = BasisTradeStrategy(config)
    days = int(years * 365)
    capital = config.get('initial_balance', 1000.0)

    results = {}
    total_pnl = 0.0
    total_trades = 0
    winning_trades = 0

    for asset in strategy.contracts:
        print(f"\n{'='*50}")
        print(f"  BACKTEST BASIS TRADE: {asset} ({years} años)")
        print(f"{'='*50}")

        df = fetch_historical_funding(feed, asset)
        if df.empty:
            print(f"  Sin datos para {asset}")
            continue

        annual_rates = []
        monthly_pnl = []
        position_open = False
        entry_time = None
        entry_rate = None
        funding_collected = 0.0
        trade_pnls = []

        for i, (ts, row) in enumerate(df.iterrows()):
            rate = row['funding_rate']
            funding_annual = rate * 3 * 365 * 100  # Anualizado

            if not position_open:
                if funding_annual >= strategy.min_funding:
                    position_open = True
                    entry_time = ts
                    entry_rate = funding_annual
                    total_trades += 1
            else:
                # Colección de funding
                funding_collected += rate * capital

                # Cerrar si funding cae debajo del umbral
                if funding_annual < strategy.min_funding * 0.5:
                    position_open = False
                    hold_days = (ts - entry_time).days
                    pnl = funding_collected
                    trade_pnls.append(pnl)
                    if pnl > 0:
                        winning_trades += 1
                    total_pnl += pnl
                    monthly_pnl.append({'date': ts, 'pnl': pnl})
                    funding_collected = 0.0

        # Cerrar posición final si quedó abierta
        if position_open:
            pnl = funding_collected
            trade_pnls.append(pnl)
            if pnl > 0:
                winning_trades += 1
            total_pnl += pnl

        avg_rate = df['funding_rate'].mean()
        avg_annual = avg_rate * 3 * 365 * 100
        annual_returns = [pnl / capital * 100 for pnl in trade_pnls] if trade_pnls else [0]
        wr = (winning_trades / total_trades * 100) if total_trades > 0 else 0

        # Calcular drawdown
        cumulative = np.cumsum(trade_pnls) if trade_pnls else [0]
        peak = np.maximum.accumulate(cumulative)
        dd = -(cumulative - peak)
        max_dd = float(np.max(dd)) if len(dd) > 0 else 0
        max_dd_pct = max_dd / capital * 100

        # Sharpe ratio
        returns_arr = np.array(annual_returns) / 100
        sharpe = (np.mean(returns_arr) / np.std(returns_arr) * np.sqrt(total_trades)) if total_trades > 1 and np.std(returns_arr) > 0 else 0

        # Profit factor
        gross_profit = sum(p for p in trade_pnls if p > 0)
        gross_loss = abs(sum(p for p in trade_pnls if p < 0))
        pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        asset_pnl = sum(trade_pnls)
        results[asset] = {
            'trades': total_trades,
            'wins': winning_trades,
            'wr_pct': round(wr, 1),
            'pnl': round(asset_pnl, 4),
            'return_pct': round(asset_pnl / capital * 100, 2),
            'max_dd_pct': round(max_dd_pct, 2),
            'sharpe': round(sharpe, 2),
            'pf': round(pf, 2) if pf != float('inf') else 99.99,
            'avg_funding_annual_pct': round(avg_annual, 2),
        }

        print(f"  Trades: {total_trades}")
        print(f"  WR: {wr:.1f}%")
        print(f"  PnL: ${asset_pnl:.4f}")
        print(f"  Return: {asset_pnl / capital * 100:.2f}%")
        print(f"  Max DD: {max_dd_pct:.2f}%")
        print(f"  Sharpe: {sharpe:.2f}")
        print(f"  Profit Factor: {pf:.2f}")
        print(f"  Avg Funding Rate (anual): {avg_annual:.2f}%")

    print(f"\n{'='*50}")
    print(f"  CONSOLIDADO BASIS TRADE ({years} años)")
    print(f"{'='*50}")
    total_return = sum(r['pnl'] for r in results.values())
    print(f"  PnL Total: ${total_return:.4f}")
    print(f"  Return Total: {total_return / capital * 100:.2f}%")
    if results:
        avg_wr = np.mean([r['wr_pct'] for r in results.values()])
        print(f"  WR Promedio: {avg_wr:.1f}%")

    return results


def main():
    parser = argparse.ArgumentParser(description='Backtest Basis Trade Strategy')
    parser.add_argument('--years', type=float, default=2.0, help='Años de backtest')
    parser.add_argument('--capital', type=float, default=1000.0, help='Capital inicial')
    args = parser.parse_args()

    config = load_config()
    config['initial_balance'] = args.capital

    print(f"╔══════════════════════════════════════╗")
    print(f"║  BACKTEST — BASIS TRADE STRATEGY    ║")
    print(f"║  {args.years} años | ${args.capital:,.0f} capital  ║")
    print(f"╚══════════════════════════════════════╝")

    run_backtest(config, years=args.years)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
backtest_pairs.py — Backtester de Pairs Trading con cointegración rolling.

Descarga datos de ambas piernas via yfinance, calcula beta rodante,
spread, z-score, y simula entradas/salidas según umbrales.

Uso:
  python3 scripts/backtest_pairs.py
  python3 scripts/backtest_pairs.py --pair GLD-SLV --years 5
  python3 scripts/backtest_pairs.py --all-pairs
"""
import argparse
import sys
import os
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')

import yaml
from data.pairs_feed import PairsFeed
from core.pairs_profiles import PAIRS_PROFILES, get_pairs_profile
from strategies.pairs_trading import PairsTradingStrategy, PairsPosition

INITIAL_BALANCE = 500.0


def parse_args():
    p = argparse.ArgumentParser(description='Backtest Pairs Trading')
    p.add_argument('--pair', type=str, default='GLD-SLV', help='Par a backtestear')
    p.add_argument('--years', type=int, default=5, help='Años de datos')
    p.add_argument('--all-pairs', action='store_true', help='Todos los pares configurados')
    return p.parse_args()


def run_backtest(pair_name: str, years: int, profile) -> dict:
    """Ejecuta backtest walk-forward para un par."""
    feed = PairsFeed()
    df = feed.get_pair_ohlcv(profile.asset_a, profile.asset_b,
                             source=profile.source, days=years * 365)

    if df.empty or len(df) < profile.hedge_ratio_window + 50:
        print(f'  ⚠ {pair_name}: datos insuficientes ({len(df)} días)')
        return {'trades': 0, 'return_pct': 0, 'wr': 0, 'total_pnl': 0}

    window = profile.hedge_ratio_window
    refit = profile.refit_interval
    balance = INITIAL_BALANCE
    peak = INITIAL_BALANCE
    max_dd = 0
    position: PairsPosition | None = None
    trades = []

    for i in range(window, len(df)):
        # Recalcular beta cada refit_interval días
        if i % refit == 0 or i == window:
            subset = df.iloc[:i + 1]
            beta_series = feed.calc_hedge_ratio(subset, window)
            spread = feed.calc_spread(subset, beta_series)
            zscore = feed.calc_zscore(spread, window)
            beta_now = float(beta_series.iloc[-1]) if not pd.isna(beta_series.iloc[-1]) else 1.0
        else:
            if 'beta_now' not in dir():
                continue
            beta_now_val = float(beta_now) if isinstance(beta_now, (int, float)) else 1.0
            log_a = np.log(df['close_a'].iloc[i])
            log_b = np.log(df['close_b'].iloc[i])
            spread_now = log_a - beta_now_val * log_b
            spread_mean = spread.iloc[max(0, i - window):i].mean()
            spread_std = spread.iloc[max(0, i - window):i].std()
            if spread_std and spread_std > 0:
                z_now = (spread_now - spread_mean) / spread_std
            else:
                continue

        # Saltar si z-score no es válido
        try:
            z_now = float(zscore.iloc[i]) if i < len(zscore) and not pd.isna(zscore.iloc[i]) else None
        except Exception:
            continue
        if z_now is None:
            continue

        price_a = df['close_a'].iloc[i]
        price_b = df['close_b'].iloc[i]
        dt = df.index[i]

        # Gestión de posición abierta
        if position is not None:
            hold_days = (dt - pd.to_datetime(position.entry_time)).days
            close_it = False
            reason = ''

            if abs(z_now) <= profile.z_exit:
                close_it, reason = True, 'Z_REVERTED'
            elif position.side_a == 'LONG' and z_now <= -profile.stop_loss_z:
                close_it, reason = True, 'STOP_LOSS_Z'
            elif position.side_a == 'SHORT' and z_now >= profile.stop_loss_z:
                close_it, reason = True, 'STOP_LOSS_Z'
            elif hold_days >= profile.max_hold_days:
                close_it, reason = True, 'MAX_HOLD_TIME'

            if close_it:
                pnl_a = (price_a - position.entry_price_a) * position.size_a
                pnl_a = pnl_a if position.side_a == 'LONG' else -pnl_a
                total_pnl = pnl_a
                balance += total_pnl

                trades.append({
                    'pair': pair_name,
                    'entry_date': pd.to_datetime(position.entry_time),
                    'exit_date': dt,
                    'z_entry': position.z_at_entry,
                    'z_exit': z_now,
                    'side': position.side_a,
                    'pnl': round(total_pnl, 2),
                    'reason': reason,
                    'hold_days': hold_days,
                })
                position = None
                peak = max(peak, balance)

        # Entrada si no hay posición
        if position is None:
            capital = INITIAL_BALANCE * profile.max_capital_pct

            if z_now >= profile.z_entry:
                size = capital / price_a
                position = PairsPosition(
                    pair=pair_name,
                    side_a='LONG',
                    entry_price_a=price_a,
                    entry_price_b=price_b,
                    size_a=size,
                    size_b=size,
                    beta_at_entry=beta_now_val,
                    z_at_entry=z_now,
                    entry_time=str(dt),
                )
            elif z_now <= -profile.z_entry:
                size = capital / price_a
                position = PairsPosition(
                    pair=pair_name,
                    side_a='SHORT',
                    entry_price_a=price_a,
                    entry_price_b=price_b,
                    size_a=size,
                    size_b=size,
                    beta_at_entry=beta_now_val,
                    z_at_entry=z_now,
                    entry_time=str(dt),
                )

        # Drawdown
        equity_now = balance
        peak = max(peak, equity_now)
        dd = (peak - equity_now) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)

    # Reporte
    n_trades = len(trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    wr = len(wins) / n_trades * 100 if n_trades > 0 else 0
    total_pnl = sum(t['pnl'] for t in trades)
    return_pct = (balance - INITIAL_BALANCE) / INITIAL_BALANCE * 100
    avg_win = np.mean([t['pnl'] for t in wins]) if wins else 0
    avg_loss = np.mean([abs(t['pnl']) for t in losses]) if losses else 0
    pf = avg_win / avg_loss if avg_loss > 0 else 0

    return {
        'pair': pair_name,
        'trades': n_trades,
        'wins': len(wins),
        'losses': len(losses),
        'wr': round(wr, 1),
        'total_pnl': round(total_pnl, 2),
        'return_pct': round(return_pct, 1),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'profit_factor': round(pf, 2),
        'max_dd': round(max_dd, 1),
        'trades_list': trades,
    }


def main():
    args = parse_args()
    pairs = list(PAIRS_PROFILES.keys()) if args.all_pairs else [args.pair]

    print('═' * 60)
    print(f'Pairs Trading — Backtest {args.years}Y')
    print(f'Capital inicial: ${INITIAL_BALANCE:,.0f}')
    print(f'Pares: {", ".join(pairs)}')
    print('═' * 60)

    with open('/opt/trading/config/exchange_config.yaml') as f:
        cfg = yaml.safe_load(f)

    results = []
    for pair_name in pairs:
        profile = get_pairs_profile(pair_name)
        print(f'\n{pair_name} ({profile.asset_a}/{profile.asset_b})...')
        r = run_backtest(pair_name, args.years, profile)
        results.append(r)

        print(f'  Trades: {r["trades"]}')
        print(f'  Win Rate: {r["wr"]}%')
        print(f'  PnL: ${r["total_pnl"]:+,.2f}')
        print(f'  Return: {r["return_pct"]:+.1f}%')
        print(f'  Avg Win/Loss: ${r["avg_win"]:+.2f} / ${r["avg_loss"]:+.2f}')
        print(f'  PF: {r["profit_factor"]:.2f}')
        print(f'  Max DD: {r["max_dd"]}%')

        if r['trades_list']:
            print(f'\n  ── Trades ──')
            for t in r['trades_list'][-10:]:
                emoji = '✅' if t['pnl'] > 0 else '❌'
                print(f'  {emoji} {t["entry_date"].date()} → {t["exit_date"].date()} '
                      f'| z:{t["z_entry"]:+.1f}→{t["z_exit"]:+.1f} '
                      f'| ${t["pnl"]:+,.2f} | {t["reason"]}')

    if results:
        total_trades = sum(r['trades'] for r in results)
        total_pnl = sum(r['total_pnl'] for r in results)
        print(f'\n═══ CONSOLIDADO ═══')
        print(f'  Total trades: {total_trades}')
        print(f'  Total PnL: ${total_pnl:+,.2f}')
        print(f'  Return: {(total_pnl / INITIAL_BALANCE * 100):+.1f}%')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
backtest_vol.py — Backtester de VIX Mean Reversion con datos históricos.

Descarga VIX + productos de volatilidad (SVXY, VXX, UVXY) via yfinance,
aplica la estrategia VolMeanReversionStrategy y genera reporte.

Uso:
  python3 scripts/backtest_vol.py
  python3 scripts/backtest_vol.py --years 5 --asset SVXY
  python3 scripts/backtest_vol.py --years 3 --all-assets
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
from strategies.vol_mean_reversion import VolMeanReversionStrategy, VolPosition, VolSignal
from core.vol_profiles import VOL_PROFILES, get_vol_profile
from data.vol_feed import VolFeed

INITIAL_BALANCE = 500.0
PAPER_TRADING = True

# ── CLI ───────────────────────────────────────────────────────────────────────


def parse_args():
    p = argparse.ArgumentParser(description='Backtest VIX Mean Reversion')
    p.add_argument('--years', type=int, default=5, help='Años de backtest (default: 5)')
    p.add_argument('--asset', type=str, default='SVXY', help='Ticker del producto de vol (default: SVXY)')
    p.add_argument('--all-assets', action='store_true', help='Backtest todos los assets configurados')
    return p.parse_args()


# ── Data fetching ─────────────────────────────────────────────────────────────


def fetch_vix_history(years: int) -> pd.DataFrame:
    """Descarga historial de VIX."""
    import yfinance as yf
    period = f'{years}y'
    t = yf.Ticker('^VIX')
    df = t.history(period=period)
    if df.empty:
        print('ERROR: No se pudo descargar VIX')
        sys.exit(1)
    print(f'  VIX: {len(df):,} velas  ({df.index[0].date()} → {df.index[-1].date()})')
    return df


def fetch_product_history(ticker: str, years: int) -> pd.DataFrame:
    """Descarga historial de un producto de vol."""
    import yfinance as yf
    period = f'{years}y'
    t = yf.Ticker(ticker)
    df = t.history(period=period)
    if df.empty:
        print(f'  ⚠ {ticker}: sin datos para {years}y')
    else:
        print(f'  {ticker}: {len(df):,} velas  ({df.index[0].date()} → {df.index[-1].date()})')
    return df


# ── Backtest engine ───────────────────────────────────────────────────────────


def run_backtest(ticker: str, vix_df: pd.DataFrame, product_df: pd.DataFrame,
                 strategy: VolMeanReversionStrategy, initial_balance: float = INITIAL_BALANCE) -> dict:
    """Ejecuta backtest de VIX Mean Reversion para un ticker.

    Simula:
      1. Cada día hábil, evaluar señal VIX
      2. ENTRY: abrir posición long (SVXY) si no hay posición abierta
      3. EXIT: cerrar cuando VIX normaliza o se alcanza SL/TP
      4. Trackear trades, equity curve, drawdown, WR
    """
    if product_df.empty or vix_df.empty:
        return {'trades': 0, 'return_pct': 0, 'wr': 0}

    balance = initial_balance
    peak = initial_balance
    position: VolPosition | None = None
    trades = []
    equity_curve = []
    max_dd = 0.0

    # Alinear índices (normalizar a date, ignorar timezones)
    vix_aligned = vix_df.copy()
    product_aligned = product_df.copy()
    vix_aligned.index = pd.to_datetime(vix_aligned.index).tz_localize(None).normalize()
    product_aligned.index = pd.to_datetime(product_aligned.index).tz_localize(None).normalize()
    common_idx = product_aligned.index.intersection(vix_aligned.index)
    if len(common_idx) < 252:
        print(f'  ⚠ Datos insuficientes: {len(common_idx)} días (<252)')
        return {'ticker': ticker, 'trades': 0, 'return_pct': 0, 'wr': 0, 'total_pnl': 0,
                'avg_win': 0, 'avg_loss': 0, 'profit_factor': 0, 'max_dd': 0,
                'equity': [], 'trades_list': []}

    vix_window = min(252, max(40, len(common_idx) // 5))  # Lookback adaptativo

    for i, dt in enumerate(common_idx):
        if i < vix_window:
            equity_curve.append(balance)
            continue

        vix_now = float(vix_aligned.loc[dt, 'Close'])
        price_now = float(product_aligned.loc[dt, 'Close'])
        vix_history = vix_aligned['Close'].iloc[max(0, i - vix_window):i]

        # Percentil de VIX en ventana rodante
        vix_pct = (vix_history < vix_now).sum() / len(vix_history) * 100

        # Si hay posición abierta, verificar SL/TP/exit
        if position is not None:
            hold_days = (dt - pd.to_datetime(position.entry_time)).days

            close_it, reason = strategy.should_close(
                position, price_now, current_vix_percentile=vix_pct, hold_days=hold_days,
            )

            if close_it:
                pnl = (price_now - position.entry_price) * position.size
                pnl_pct = (price_now - position.entry_price) / position.entry_price * 100
                position.close_time = dt.isoformat()
                position.close_reason = reason
                position.pnl = pnl
                position.closed = True

                balance += pnl
                trades.append({
                    'entry_date': pd.to_datetime(position.entry_time),
                    'exit_date': dt,
                    'entry_price': position.entry_price,
                    'exit_price': price_now,
                    'size': position.size,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'reason': reason,
                    'vix_at_entry': position.vix_at_entry,
                    'vix_at_exit': vix_now,
                    'hold_days': hold_days,
                })
                position = None
                peak = max(peak, balance)

        # Si no hay posición, evaluar entrada
        if position is None:
            contango = None  # Simplificado: no usamos contango en backtest base
            can_enter = vix_pct >= strategy.entry_percentile

            if can_enter and price_now > 0:
                profile = get_vol_profile(ticker)
                max_cap = balance * profile.max_position_pct
                size = max_cap / price_now

                position = VolPosition(
                    ticker=ticker,
                    entry_price=price_now,
                    size=size,
                    entry_time=dt.isoformat(),
                    vix_at_entry=vix_now,
                )

        # Equity
        equity_now = balance
        if position is not None:
            equity_now += (price_now - position.entry_price) * position.size
        equity_curve.append(equity_now)
        peak = max(peak, equity_now)
        dd = (peak - equity_now) / peak * 100
        max_dd = max(max_dd, dd)

    # Reporte
    n_trades = len(trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    wr = len(wins) / n_trades * 100 if n_trades > 0 else 0
    total_pnl = sum(t['pnl'] for t in trades)
    return_pct = (balance - initial_balance) / initial_balance * 100
    avg_win = np.mean([t['pnl'] for t in wins]) if wins else 0
    avg_loss = np.mean([t['pnl'] for t in losses]) if losses else 0
    pf = abs(avg_win / avg_loss) if avg_loss != 0 and wins else float('inf') if wins and not losses else 0

    return {
        'ticker': ticker,
        'balance': round(balance, 2),
        'initial_balance': initial_balance,
        'trades': n_trades,
        'wins': len(wins),
        'losses': len(losses),
        'wr': round(wr, 1),
        'return_pct': round(return_pct, 1),
        'total_pnl': round(total_pnl, 2),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'profit_factor': round(pf, 2),
        'max_dd': round(max_dd, 1),
        'equity': equity_curve,
        'trades_list': trades,
    }


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    args = parse_args()
    assets = list(VOL_PROFILES.keys()) if args.all_assets else [args.asset]

    print(f'═' * 60)
    print(f'VIX Mean Reversion — Backtest {args.years}Y')
    print(f'Capital inicial: ${INITIAL_BALANCE:,.0f}')
    print(f'Assets: {", ".join(assets)}')
    print(f'═' * 60)

    # Cargar config
    with open('/opt/trading/config/exchange_config.yaml') as f:
        cfg = yaml.safe_load(f)
    vol_cfg = cfg.get('vol_mean_reversion', {})
    strategy = VolMeanReversionStrategy(vol_cfg)

    # Datos
    print(f'\nDescargando datos ({args.years} años)...')
    vix_df = fetch_vix_history(args.years)

    results = []
    for ticker in assets:
        product_df = fetch_product_history(ticker, args.years)
        if product_df.empty:
            continue

        print(f'\nEjecutando backtest {ticker}...')
        r = run_backtest(ticker, vix_df, product_df, strategy)
        results.append(r)

        # Print result
        print(f'  Trades: {r["trades"]}')
        print(f'  Win Rate: {r["wr"]}%')
        print(f'  PnL Total: ${r["total_pnl"]:+,.2f}')
        print(f'  Return: {r["return_pct"]:+.1f}%')
        print(f'  Avg Win/Loss: ${r["avg_win"]:+.2f} / ${r["avg_loss"]:+.2f}')
        print(f'  Profit Factor: {r["profit_factor"]}')
        print(f'  Max DD: {r["max_dd"]}%')

        # Trade log
        if r['trades_list']:
            print(f'\n  ── Trade log ──')
            for t in r['trades_list']:
                emoji = '✅' if t['pnl'] > 0 else '❌'
                print(f'  {emoji} {t["entry_date"].date()} → {t["exit_date"].date()} '
                      f'| ${t["pnl"]:+,.2f} ({t["pnl_pct"]:+.1f}%) '
                      f'| {t["reason"]}')

    # Consolidated
    if results:
        total_trades = sum(r['trades'] for r in results)
        total_pnl = sum(r['total_pnl'] for r in results)
        avg_wr = np.mean([r['wr'] for r in results])
        print(f'\n═══ CONSOLIDADO ═══')
        print(f'  Total trades: {total_trades}')
        print(f'  Total PnL: ${total_pnl:+,.2f}')
        print(f'  Avg WR: {avg_wr:.1f}%')
        print(f'  Return combinado: {(total_pnl / INITIAL_BALANCE * 100):+.1f}%')


if __name__ == '__main__':
    main()

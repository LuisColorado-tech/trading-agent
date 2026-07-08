#!/usr/bin/env python3
"""
backtest_minervini.py — Backtest de la estrategia Minervini SEPA momentum.

Usa velas diarias (1d) de yfinance. Evalúa el Trend Template:
  - Precio > EMA150 y EMA200
  - EMA150 > EMA200 (tendencia alcista)
  - Precio cerca de máximo 52 semanas (<25%)
  - RSI 48-68 (momentum, no sobrecomprado)
  - Volumen > 1.5× media

SL: -7%. TP: +20%. Solo BUY. Máximo 3 posiciones simultáneas.
Evalúa 1 vez al día (al cierre).

Uso:
  python3 scripts/backtest_minervini.py
  python3 scripts/backtest_minervini.py --years 3 --symbols NVDA,META,TSLA
  python3 scripts/backtest_minervini.py --years 5 --all
"""
import argparse
import sys
import os
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')

from agents.indicators import IndicatorEngine
from strategies.stocks_minervini import StocksMinerviniStrategy

INITIAL_BALANCE = 500.0
MAX_POSITIONS = 2
RISK_PER_TRADE = 0.01  # 1% risk per trade
SL_PCT = 0.07
TP_PCT = 0.20
MINERVINI_SYMBOLS = ['NVDA', 'META', 'TSLA', 'AMZN', 'AAPL']

# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description='Backtest Minervini SEPA Strategy')
    p.add_argument('--years', type=int, default=3, help='Años de backtest')
    p.add_argument('--symbols', type=str, default='NVDA,META,TSLA,AMZN,AAPL',
                   help='Símbolos separados por coma')
    p.add_argument('--all', action='store_true', help='Todos los símbolos Minervini')
    return p.parse_args()

# ── Data ──────────────────────────────────────────────────────────────────────

def fetch_daily(symbol: str, years: int) -> pd.DataFrame:
    period = f'{years}y'
    t = yf.Ticker(symbol)
    df = t.history(period=period)
    if df.empty:
        print(f'  ⚠ {symbol}: sin datos')
        return df
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    print(f'  {symbol}: {len(df):,} velas ({df.index[0].date()} → {df.index[-1].date()})')
    return df[['Open', 'High', 'Low', 'Close', 'Volume']].rename(
        columns={'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'}
    )

# ── Backtest Engine ───────────────────────────────────────────────────────────

def run_backtest(symbol: str, df: pd.DataFrame, years: int) -> dict:
    if df.empty or len(df) < 250:
        return None

    strategy = StocksMinerviniStrategy()
    balance = INITIAL_BALANCE
    peak = INITIAL_BALANCE
    positions: list = []
    trades: list = []
    max_dd = 0

    for i in range(250, len(df)):
        # Use data up to this point for indicator calculation
        window = df.iloc[max(0, i-250):i+1].copy()
        window = window.rename(columns={
            'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'
        })

        # Calculate indicators
        # Need at least 200 for EMA200
        if len(window) < 200:
            continue

        ind = IndicatorEngine.calculate(window, symbol, '1d')
        if ind is None:
            continue

        current_price = float(window['close'].iloc[-1])
        dt = window.index[-1]

        # ── Monitor open positions ──
        for pos in list(positions):
            pnl_pct = (current_price - pos['entry_price']) / pos['entry_price']
            close_reason = None

            if pnl_pct <= -SL_PCT:
                close_reason = 'STOP_LOSS'
            elif pnl_pct >= TP_PCT:
                close_reason = 'TAKE_PROFIT'
            elif pos['hold_days'] > 90:
                close_reason = 'MAX_HOLD'

            if close_reason:
                pnl = (current_price - pos['entry_price']) * pos['shares']
                balance += pnl
                trades.append({
                    'symbol': symbol,
                    'entry_date': pos['entry_date'],
                    'exit_date': dt,
                    'entry_price': pos['entry_price'],
                    'exit_price': current_price,
                    'pnl': round(pnl, 2),
                    'pnl_pct': round(pnl_pct * 100, 2),
                    'reason': close_reason,
                    'hold_days': pos['hold_days'],
                })
                positions.remove(pos)
                peak = max(peak, balance)
                continue

            pos['hold_days'] += 1

        # ── Evaluate entry ──
        if len(positions) >= MAX_POSITIONS:
            continue

        # Simulate daily evaluation (once per day)
        result = strategy.score(ind)
        if result['direction'] != 'BUY':
            continue

        # Position sizing
        risk_usd = balance * RISK_PER_TRADE
        sl_dist = current_price * SL_PCT
        if sl_dist <= 0:
            continue
        shares = risk_usd / sl_dist
        notional = shares * current_price

        positions.append({
            'symbol': symbol,
            'entry_date': dt,
            'entry_price': current_price,
            'shares': shares,
            'notional': notional,
            'hold_days': 0,
            'score': result['score'],
        })

        # Drawdown tracking
        equity = balance + sum((current_price - p['entry_price']) * p['shares'] for p in positions)
        peak = max(peak, equity)
        dd = (peak - equity) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)

    # Close remaining positions at last price
    for pos in positions:
        last_price = float(df['close'].iloc[-1])
        pnl = (last_price - pos['entry_price']) * pos['shares']
        balance += pnl
        pnl_pct = (last_price - pos['entry_price']) / pos['entry_price'] * 100
        trades.append({
            'symbol': symbol,
            'entry_date': pos['entry_date'],
            'exit_date': df.index[-1],
            'entry_price': pos['entry_price'],
            'exit_price': last_price,
            'pnl': round(pnl, 2),
            'pnl_pct': round(pnl_pct, 2),
            'reason': 'EOT',
            'hold_days': pos['hold_days'],
        })

    n = len(trades)
    if n == 0:
        return {'symbol': symbol, 'trades': 0, 'total_pnl': 0, 'wr': 0, 'pf': 0, 'return_pct': 0, 'max_dd': 0, 'trades_list': []}

    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    wr = len(wins) / n * 100
    total_pnl = sum(t['pnl'] for t in trades)
    return_pct = (balance - INITIAL_BALANCE) / INITIAL_BALANCE * 100
    avg_win = np.mean([t['pnl'] for t in wins]) if wins else 0
    avg_loss = abs(np.mean([t['pnl'] for t in losses])) if losses else 0
    pf = round(avg_win / avg_loss, 2) if avg_loss > 0 else 0

    return {
        'symbol': symbol,
        'trades': n,
        'wins': len(wins),
        'losses': len(losses),
        'wr': round(wr, 1),
        'total_pnl': round(total_pnl, 2),
        'return_pct': round(return_pct, 1),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'profit_factor': pf,
        'max_dd': round(max_dd, 1),
        'balance': round(balance, 2),
        'trades_list': trades,
    }

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()
    symbols = MINERVINI_SYMBOLS if args.all else args.symbols.upper().split(',')

    print('═' * 60)
    print(f'Minervini SEPA — Backtest {args.years}Y')
    print(f'Capital: ${INITIAL_BALANCE:,.0f} | SL: {SL_PCT*100:.0f}% | TP: {TP_PCT*100:.0f}%')
    print(f'Activos: {", ".join(symbols)}')
    print('═' * 60)

    all_results = []
    for symbol in symbols:
        df = fetch_daily(symbol, args.years)
        if df.empty:
            continue

        result = run_backtest(symbol, df, args.years)
        if result is None:
            print(f'  ⚠ {symbol}: datos insuficientes')
            continue

        all_results.append(result)

        print(f'\n{symbol}:')
        print(f'  Trades: {result["trades"]} | WR: {result["wr"]}%')
        print(f'  PnL: ${result["total_pnl"]:+,.2f} ({result["return_pct"]:+.1f}%)')
        print(f'  PF: {result["profit_factor"]:.2f} | MaxDD: {result["max_dd"]}%')
        print(f'  Avg Win: ${result["avg_win"]:+,.2f} | Avg Loss: -${result["avg_loss"]:+.2f}')

        if result['trades_list']:
            print('  ── Last 10 trades ──')
            for t in result['trades_list'][-10:]:
                e = '✅' if t['pnl'] > 0 else '❌'
                print(f'    {e} {t["entry_date"].date()} → {t["exit_date"].date()} '
                      f'| ${t["pnl"]:+,.2f} ({t["pnl_pct"]:+.1f}%) '
                      f'| {t["reason"]} | {t["hold_days"]}d')

    if all_results:
        total_trades = sum(r['trades'] for r in all_results)
        total_pnl = sum(r['total_pnl'] for r in all_results)
        avg_wr = np.mean([r['wr'] for r in all_results if r['trades'] > 0])
        print(f'\n═══ CONSOLIDADO ═══')
        print(f'  Total trades: {total_trades}')
        print(f'  Total PnL: ${total_pnl:+,.2f}')
        print(f'  Avg WR: {avg_wr:.1f}%')
        print(f'  Return combinado: {(total_pnl / INITIAL_BALANCE / len(all_results) * 100):+.1f}%')


if __name__ == '__main__':
    main()

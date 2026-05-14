#!/usr/bin/env python3
"""
backtest_earnings.py — Backtest simple de Earnings Strangle.

Simula comprar un strangle (call + put OTM) 1 día antes de cada earnings
reportado en los últimos N años y cerrar 1 día después.

Uso:
  python3 scripts/backtest_earnings.py
  python3 scripts/backtest_earnings.py --years 3
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

SYMBOLS = ['NVDA', 'TSLA', 'AAPL', 'META', 'AMZN']
INITIAL_BALANCE = 1000.0
POSITION_PCT = 0.05          # 5% per trade
OTM_PCT = 0.06               # 6% OTM
STOP_LOSS_PCT = 0.50         # 50% of premium lost = stop

def parse_args():
    p = argparse.ArgumentParser(description='Backtest Earnings Strangle')
    p.add_argument('--years', type=int, default=3, help='Years of data')
    p.add_argument('--symbols', type=str, default='NVDA,TSLA,AAPL,META,AMZN')
    return p.parse_args()

def get_earnings_dates(symbol: str, years: int) -> list:
    """Get earnings dates from yfinance."""
    t = yf.Ticker(symbol)
    try:
        ed = t.earnings_dates
        if ed is not None and len(ed) > 0:
            import pandas as pd
            cutoff = pd.Timestamp.now(tz='UTC') - pd.DateOffset(months=years*12)
            dates = []
            for d in ed.index:
                # Normalize timezone
                dt = d.tz_convert('UTC') if d.tzinfo else d.tz_localize('UTC')
                if dt >= cutoff:
                    dates.append(dt.date())
            if dates:
                return sorted(dates)
    except Exception:
        pass
    # Fallback: historical quarterly estimates
    start = datetime.now() - timedelta(days=years*365)
    dates = []
    d = start
    months_per_q = 3
    while d < datetime.now():
        d += timedelta(days=90)
        if d > start:
            dates.append(d.date())
    return dates

def run_backtest(symbol: str, years: int):
    df = yf.Ticker(symbol).history(period=f'{years}y')
    if df.empty:
        return None
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()

    earnings = get_earnings_dates(symbol, years)
    if not earnings:
        return None

    balance = INITIAL_BALANCE
    trades = []
    peak = INITIAL_BALANCE
    max_dd = 0

    for ed in earnings:
        # Find trading day before and after earnings
        before = None
        after = None
        for dt in sorted(df.index):
            if dt.date() < ed:
                before = dt
            elif dt.date() > ed and after is None:
                after = dt
                break
        if before is None or after is None:
            continue

        entry_price = float(df.loc[before, 'Close'])
        exit_price = float(df.loc[after, 'Close'])

        # OTM strangle: call at +6%, put at -6%
        call_strike = entry_price * (1 + OTM_PCT)
        put_strike = entry_price * (1 - OTM_PCT)

        # Simplified premium estimate using ATR
        atr = float(df['High'].iloc[-20:].max() - df['Low'].iloc[-20:].min()) * 0.3
        # Simplified premium: ~3-5% of stock price for OTM options near earnings
        call_premium = entry_price * 0.03
        put_premium = entry_price * 0.03
        total_cost = call_premium + put_premium

        # Position sizing: 5% of balance per trade
        capital = balance * POSITION_PCT
        contracts = int(capital / (total_cost * 100))  # 100 shares per contract
        if contracts < 1:
            continue

        # P&L calculation
        move_pct = abs(exit_price - entry_price) / entry_price
        call_value = max(0, exit_price - call_strike)
        put_value = max(0, put_strike - exit_price)
        total_value = (call_value + put_value) * 100 * contracts
        total_cost_actual = total_cost * 100 * contracts
        pnl = total_value - total_cost_actual

        balance += pnl
        trades.append({
            'symbol': symbol,
            'earnings_date': ed,
            'entry_price': round(entry_price, 2),
            'exit_price': round(exit_price, 2),
            'move_pct': round(move_pct * 100, 1),
            'call_strike': round(call_strike, 2),
            'put_strike': round(put_strike, 2),
            'pnl': round(pnl, 2),
            'pnl_pct': round(pnl / total_cost_actual * 100, 1) if total_cost_actual > 0 else 0,
            'win': pnl > 0,
        })

        peak = max(peak, balance)
        dd = (peak - balance) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)

    n = len(trades)
    if n == 0:
        return None
    wins = [t for t in trades if t['win']]
    wr = len(wins) / n * 100
    total_pnl = sum(t['pnl'] for t in trades)
    avg_win = np.mean([t['pnl'] for t in wins]) if wins else 0
    avg_loss = abs(np.mean([t['pnl'] for t in trades if not t['win']])) if n > len(wins) else 0

    return {
        'symbol': symbol,
        'trades': n,
        'wins': len(wins),
        'wr': round(wr, 1),
        'total_pnl': round(total_pnl, 2),
        'return_pct': round((balance - INITIAL_BALANCE) / INITIAL_BALANCE * 100, 1),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'pf': round(avg_win / avg_loss, 2) if avg_loss > 0 else 0,
        'max_dd': round(max_dd, 1),
        'avg_move_pct': round(np.mean([t['move_pct'] for t in trades]), 1),
        'trades_list': trades,
    }

def main():
    args = parse_args()
    symbols = args.symbols.upper().split(',')

    print('═' * 60)
    print(f'Earnings Strangle — Backtest {args.years}Y')
    print(f'Capital: ${INITIAL_BALANCE:,.0f} | OTM: {OTM_PCT*100:.0f}% | SL: {STOP_LOSS_PCT*100:.0f}%')
    print(f'Symbols: {", ".join(symbols)}')
    print('═' * 60)

    results = []
    for sym in symbols:
        r = run_backtest(sym, args.years)
        if r is None:
            continue
        results.append(r)
        print(f'\n{sym}:')
        print(f'  Earnings trades: {r["trades"]} | WR: {r["wr"]}%')
        print(f'  PnL: ${r["total_pnl"]:+,.2f} ({r["return_pct"]:+.1f}%)')
        print(f'  PF: {r["pf"]:.2f} | MaxDD: {r["max_dd"]}%')
        print(f'  Avg Move: ±{r["avg_move_pct"]:.1f}%')

    if results:
        total_trades = sum(r['trades'] for r in results)
        total_pnl = sum(r['total_pnl'] for r in results)
        print(f'\n═══ CONSOLIDADO ═══')
        print(f'  Total trades: {total_trades}')
        print(f'  Total PnL: ${total_pnl:+,.2f}')

if __name__ == '__main__':
    main()

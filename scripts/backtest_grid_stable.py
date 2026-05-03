#!/usr/bin/env python3
"""
backtest_grid_stable.py — Backtester del Grid Stable Bot para pares estables.

Descarga velas de KuCoin (sin API key), aplica la estrategia GridStableStrategy
con perfiles calibrados para ETH/BTC y LINK/BTC.

Uso:
  python3 scripts/backtest_grid_stable.py
  python3 scripts/backtest_grid_stable.py --pair ETH/BTC --months 12
  python3 scripts/backtest_grid_stable.py --csv results.csv
"""
import argparse
import sys
import os
from datetime import datetime, timezone, timedelta

import pandas as pd
import numpy as np

sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')

from agents.indicators import IndicatorEngine
from core.grid_stable_profiles import get_grid_stable_profile, GridStableProfile
from strategies.grid_stable import GridStableStrategy, GridStableConfig

INITIAL_BALANCE = 500.0        # capital pequeño para grid estable
RISK_PER_TRADE_PCT = 0.005     # 0.5% riesgo por trade
MAX_CONCURRENT = 5
SL_COOLDOWN_BARS = 4

STABLE_PAIRS = ['ETH/BTC', 'LINK/BTC']


def download_ohlcv(symbol: str, timeframe: str, months: int) -> pd.DataFrame:
    """Descarga velas históricas de KuCoin."""
    import ccxt, time as _t
    exchange = ccxt.kucoin({'enableRateLimit': True})
    since_dt = datetime.now(timezone.utc) - timedelta(days=months * 30)
    since_ms = int(since_dt.timestamp() * 1000)
    all_ohlcv = []
    limit = 1000
    print(f"  Descargando {symbol} {timeframe} desde {since_dt.date()} ({months} meses)...")
    while True:
        try:
            batch = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=limit)
        except Exception as e:
            print(f"  ⚠ Error: {e}")
            break
        if not batch:
            break
        all_ohlcv.extend(batch)
        since_ms = batch[-1][0] + 1
        if len(all_ohlcv) % 10000 == 0:
            print(f"    ... {len(all_ohlcv):,} velas")
        _t.sleep(0.3)
    if not all_ohlcv:
        return pd.DataFrame()
    df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    df = df.set_index('timestamp').sort_index()
    df = df[~df.index.duplicated(keep='last')]
    print(f"  ✓ {len(df):,} velas  ({df.index[0].date()} → {df.index[-1].date()})")
    return df


def run_backtest(df: pd.DataFrame, pair: str, profile: GridStableProfile) -> dict:
    """Ejecuta backtest de grid estable para un par."""
    strategy = GridStableStrategy(profile)
    balance = INITIAL_BALANCE
    peak = INITIAL_BALANCE
    trades = []
    open_positions = []
    cooldown = 0
    warmup = 200

    for i in range(warmup, len(df)):
        if cooldown > 0:
            cooldown -= 1

        window = df.iloc[max(0, i - profile.grid_range_candles):i + 1]
        ind = IndicatorEngine.calculate(window, pair, '15m')
        if ind is None:
            continue

        config = strategy.build_grid(window, ind)
        if config is None:
            continue

        current_price = float(df.iloc[i]['close'])
        bar_ts = df.index[i]

        # Verificar cierres (SL/TP)
        still_open = []
        for pos in open_positions:
            if pos['direction'] == 'SELL':
                if current_price <= pos['tp']:
                    pnl = (pos['entry'] - pos['tp']) * pos['size']
                    balance += pnl
                    trades.append({**pos, 'exit': pos['tp'], 'pnl': pnl, 'reason': 'TP', 'exit_ts': bar_ts})
                    continue
                elif current_price >= pos['sl']:
                    pnl = (pos['entry'] - pos['sl']) * pos['size']
                    balance += pnl
                    trades.append({**pos, 'exit': pos['sl'], 'pnl': pnl, 'reason': 'SL', 'exit_ts': bar_ts})
                    cooldown = SL_COOLDOWN_BARS
                    continue
            elif pos['direction'] == 'BUY':
                if current_price >= pos['tp']:
                    pnl = (pos['tp'] - pos['entry']) * pos['size']
                    balance += pnl
                    trades.append({**pos, 'exit': pos['tp'], 'pnl': pnl, 'reason': 'TP', 'exit_ts': bar_ts})
                    continue
                elif current_price <= pos['sl']:
                    pnl = (pos['sl'] - pos['entry']) * pos['size']
                    balance += pnl
                    trades.append({**pos, 'exit': pos['sl'], 'pnl': pnl, 'reason': 'SL', 'exit_ts': bar_ts})
                    cooldown = SL_COOLDOWN_BARS
                    continue
            still_open.append(pos)
        open_positions = still_open

        if balance > peak:
            peak = balance

        # No abrir si cooldown o max concurrent
        if cooldown > 0 or len(open_positions) >= MAX_CONCURRENT:
            continue

        # Buscar nivel cercano
        level = strategy.find_nearest_level(current_price, config)
        if level is None:
            continue

        # Ya hay posición en este nivel?
        if any(p['level_idx'] == level.level_idx for p in open_positions):
            continue

        # Tamaño
        risk_usd = balance * RISK_PER_TRADE_PCT * profile.risk_fraction
        sl_dist = abs(level.sl - level.price)
        if sl_dist <= 0:
            continue
        size = risk_usd / sl_dist

        open_positions.append({
            'pair': pair,
            'entry': level.price,
            'tp': level.tp,
            'sl': level.sl,
            'size': size,
            'level_idx': level.level_idx,
            'direction': level.direction,
            'entry_ts': bar_ts,
        })

    # Cerrar posiciones abiertas al final
    for pos in open_positions:
        last_price = float(df.iloc[-1]['close'])
        if pos['direction'] == 'SELL':
            pnl = (pos['entry'] - last_price) * pos['size']
        else:
            pnl = (last_price - pos['entry']) * pos['size']
        trades.append({**pos, 'exit': last_price, 'pnl': pnl, 'reason': 'EOD', 'exit_ts': df.index[-1]})
        balance += pnl

    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()
    if trades_df.empty:
        return {'total_trades': 0, 'error': 'no trades', 'final_balance': balance}

    n = len(trades_df)
    wins = int((trades_df['pnl'] > 0).sum())
    losses = n - wins
    total_pnl = float(trades_df['pnl'].sum())
    gp = float(trades_df[trades_df['pnl'] > 0]['pnl'].sum())
    gl = abs(float(trades_df[trades_df['pnl'] <= 0]['pnl'].sum()))
    pf = gp / gl if gl > 0 else float('inf')
    dd = (peak - balance) / peak * 100 if peak > 0 else 0
    ret = (balance / INITIAL_BALANCE - 1) * 100

    # Sharpe mensual
    if n > 1:
        trades_df['exit_ts'] = pd.to_datetime(trades_df['exit_ts'], utc=True)
        trades_df['month'] = trades_df['exit_ts'].dt.to_period('M')
        monthly = trades_df.groupby('month')['pnl'].sum()
        monthly_ret = monthly / INITIAL_BALANCE
        sharpe = float(monthly_ret.mean() / monthly_ret.std() * np.sqrt(12)) if monthly_ret.std() > 0 else 0
    else:
        sharpe = 0

    return {
        'pair': pair,
        'total_trades': n,
        'win_rate_pct': round(wins / n * 100, 1),
        'profit_factor': round(pf, 2),
        'total_pnl': round(total_pnl, 2),
        'final_balance': round(balance, 2),
        'return_pct': round(ret, 2),
        'max_drawdown_pct': round(dd, 1),
        'sharpe_ratio': round(sharpe, 2),
        'avg_win': round(gp / wins, 2) if wins > 0 else 0,
        'avg_loss': round(gl / losses, 2) if losses > 0 else 0,
        'trades_list': trades_df,
    }


def print_report(metrics: dict):
    print(f"\n{'='*60}")
    print(f"  GRID STABLE: {metrics.get('pair', '?')} — {metrics['total_trades']} trades")
    print(f"{'='*60}")
    if 'error' in metrics:
        print(f"  ⚠ {metrics['error']}")
        return
    verdict = '✅ RENTABLE' if metrics['profit_factor'] >= 1.0 else '❌ PIERDE DINERO'
    print(f"  {verdict}")
    print(f"  Trades:          {metrics['total_trades']}")
    print(f"  Win rate:        {metrics['win_rate_pct']:.1f}%")
    print(f"  Profit factor:   {metrics['profit_factor']:.2f}")
    print(f"  Retorno total:   {metrics['return_pct']:+.2f}%  (${metrics['total_pnl']:+,.2f})")
    print(f"  Balance final:   ${metrics['final_balance']:,.2f}")
    print(f"  Max drawdown:    {metrics['max_drawdown_pct']:.1f}%")
    print(f"  Sharpe ratio:    {metrics['sharpe_ratio']:.2f}")
    print(f"  Avg ganancia:    ${metrics['avg_win']:+,.2f}")
    print(f"  Avg pérdida:     ${metrics['avg_loss']:+,.2f}")


def main():
    parser = argparse.ArgumentParser(description='Backtest Grid Stable Bot')
    parser.add_argument('--pair', default=None, help='Par específico (default: todos)')
    parser.add_argument('--months', type=int, default=12, help='Meses de historia')
    parser.add_argument('--csv', default='', help='Exportar trades a CSV')
    args = parser.parse_args()

    pairs = [args.pair] if args.pair else STABLE_PAIRS
    all_metrics = []

    for pair in pairs:
        profile = get_grid_stable_profile(pair)
        df = download_ohlcv(pair, '15m', args.months)
        if df.empty:
            print(f"  ⚠ {pair}: sin datos")
            continue
        metrics = run_backtest(df, pair, profile)
        all_metrics.append(metrics)
        print_report(metrics)

    # Reporte global
    if len(all_metrics) > 1:
        total_trades = sum(m.get('total_trades', 0) for m in all_metrics)
        total_pnl = sum(m.get('total_pnl', 0) for m in all_metrics)
        # PF combinado
        total_gp = sum(
            m['trades_list'][m['trades_list']['pnl'] > 0]['pnl'].sum()
            for m in all_metrics if 'trades_list' in m and not m['trades_list'].empty
        )
        total_gl = sum(
            abs(m['trades_list'][m['trades_list']['pnl'] <= 0]['pnl'].sum())
            for m in all_metrics if 'trades_list' in m and not m['trades_list'].empty
        )
        combined_pf = total_gp / total_gl if total_gl > 0 else 0
        ret = (INITIAL_BALANCE + total_pnl) / INITIAL_BALANCE - 1

        print(f"\n{'='*60}")
        print(f"  RESUMEN GLOBAL — {total_trades} trades totales")
        print(f"{'='*60}")
        print(f"  Trades: {total_trades} | PF: {combined_pf:.2f} | PnL: ${total_pnl:+,.2f} | Ret: {ret*100:+.1f}%")

    # Exportar
    if args.csv and all_metrics:
        all_trades = pd.concat(
            [m['trades_list'] for m in all_metrics if 'trades_list' in m and not m['trades_list'].empty],
            ignore_index=True,
        )
        if not all_trades.empty:
            all_trades.to_csv(args.csv, index=False)
            print(f"\n  📄 Trades exportados a: {args.csv}")


if __name__ == '__main__':
    main()

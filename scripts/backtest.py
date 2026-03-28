#!/usr/bin/env python3
"""
backtest.py — Backtester del trading agent sobre datos históricos reales.

Descarga 1 año de velas de Binance (gratis, sin API key) y aplica
exactamente la misma lógica de indicadores, régimen, estrategia y
gestión de riesgo que usa el agente en producción.

Uso:
  python3 scripts/backtest.py                          # BTC/ETH/SOL, 15m, 1 año
  python3 scripts/backtest.py --assets BTC --tf 1h     # solo BTC en 1h
  python3 scripts/backtest.py --months 6               # últimos 6 meses
  python3 scripts/backtest.py --csv results.csv        # exportar trades
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
from core.market_regime import classify_market_regime
from agents.strategy_engine import count_confluence, MIN_CONFLUENCE_INDICATORS
from strategies.trend_momentum import TrendMomentumStrategy
from strategies.breakout import BreakoutStrategy

# ── Parámetros de riesgo (mismos que producción) ─────────────────────
INITIAL_BALANCE    = 10_000.0
RISK_PER_TRADE_PCT = 0.01       # 1% del balance por trade
MAX_CONCURRENT     = 3
SL_COOLDOWN_BARS   = 4          # velas de cooldown tras SL (≈ 1h en 15m)
MIN_RR             = 1.8        # R:R mínimo para tomar el trade

STRATEGIES = [TrendMomentumStrategy(), BreakoutStrategy()]


# ── Descarga de datos ─────────────────────────────────────────────────

def download_ohlcv(symbol: str, timeframe: str, months: int) -> pd.DataFrame:
    """Descarga velas históricas de KuCoin sin API key."""
    import ccxt, time as _t
    exchange = ccxt.kucoin({'enableRateLimit': True})
    
    since_dt = datetime.now(timezone.utc) - timedelta(days=months * 30)
    since_ms  = int(since_dt.timestamp() * 1000)
    
    all_ohlcv = []
    limit = 1500
    print(f"  Descargando {symbol} {timeframe} desde {since_dt.date()}...")
    
    while True:
        try:
            batch = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=limit)
        except Exception as e:
            print(f"  ⚠ Error descargando {symbol}: {e}")
            break
        if not batch:
            break
        all_ohlcv.extend(batch)
        since_ms = batch[-1][0] + 1
        if len(batch) < limit:
            break
        _t.sleep(0.3)
    
    if not all_ohlcv:
        return pd.DataFrame()
    
    df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    df = df.set_index('timestamp').sort_index()
    # Eliminar duplicados que puede traer KuCoin en los bordes
    df = df[~df.index.duplicated(keep='last')]
    print(f"  ✓ {len(df)} velas  ({df.index[0].date()} → {df.index[-1].date()})")
    return df


# ── Backtester ────────────────────────────────────────────────────────

class Backtest:
    def __init__(self, df: pd.DataFrame, asset: str, timeframe: str):
        self.df = df.copy()
        self.asset = asset
        self.timeframe = timeframe
        self.balance = INITIAL_BALANCE
        self.peak = INITIAL_BALANCE
        self.trades: list[dict] = []
        self.open_trade: dict | None = None
        self.cooldown_remaining = 0

    def run(self) -> list[dict]:
        warmup = 250  # velas de calentamiento para indicadores
        for i in range(warmup, len(self.df)):
            window = self.df.iloc[i - warmup:i + 1]
            bar    = self.df.iloc[i]

            # 1. Gestionar trade abierto
            if self.open_trade:
                self._check_exit(bar)

            # 2. Cooldown
            if self.cooldown_remaining > 0:
                self.cooldown_remaining -= 1
                continue

            # 3. Ya tenemos trade abierto → no abrir otro (1 a la vez por activo)
            if self.open_trade:
                continue

            # 4. Calcular indicadores y buscar señal
            ind = IndicatorEngine.calculate(window, self.asset, self.timeframe)
            if ind is None:
                continue

            regime = classify_market_regime(ind)
            signal = self._best_signal(ind, regime, window)
            if signal is None:
                continue

            # 5. Verificar R:R mínimo
            sl   = signal['stop_loss']
            tp   = signal['take_profit']
            risk = abs(bar['close'] - sl)
            rwd  = abs(tp - bar['close'])
            if risk <= 0 or (rwd / risk) < MIN_RR:
                continue

            # 6. Calcular tamaño de posición
            risk_amount = self.balance * RISK_PER_TRADE_PCT
            size = risk_amount / risk

            self.open_trade = {
                'asset':      self.asset,
                'timeframe':  self.timeframe,
                'strategy':   signal['strategy'],
                'direction':  signal['direction'],
                'entry':      bar['close'],
                'sl':         sl,
                'tp':         tp,
                'size':       size,
                'risk':       risk_amount,
                'rr':         rwd / risk,
                'entry_bar':  i,
                'entry_time': bar.name,
                'regime':     regime.name,
            }

        # Cerrar trade pendiente al final del período
        if self.open_trade:
            last = self.df.iloc[-1]
            self._force_close(last, 'END_OF_DATA')

        return self.trades

    def _check_exit(self, bar: pd.Series):
        t = self.open_trade
        hit_sl = hit_tp = False

        if t['direction'] == 'BUY':
            hit_sl = bar['low']  <= t['sl']
            hit_tp = bar['high'] >= t['tp']
        else:
            hit_sl = bar['high'] >= t['sl']
            hit_tp = bar['low']  <= t['tp']

        if hit_tp:
            self._close_trade(bar, 'TP', t['tp'])
        elif hit_sl:
            self._close_trade(bar, 'SL', t['sl'])

    def _close_trade(self, bar: pd.Series, reason: str, exit_price: float):
        t = self.open_trade
        if t['direction'] == 'BUY':
            pnl = (exit_price - t['entry']) * t['size']
        else:
            pnl = (t['entry'] - exit_price) * t['size']

        self.balance += pnl
        self.peak = max(self.peak, self.balance)

        record = {**t, 'exit': exit_price, 'exit_time': bar.name,
                  'close_reason': reason, 'pnl': pnl,
                  'pnl_pct': pnl / (t['entry'] * t['size']) * 100,
                  'balance_after': self.balance,
                  'drawdown_pct': (self.peak - self.balance) / self.peak * 100,
                  'bars_open': bar.name}
        self.trades.append(record)
        self.open_trade = None
        if reason == 'SL':
            self.cooldown_remaining = SL_COOLDOWN_BARS

    def _force_close(self, bar: pd.Series, reason: str):
        self._close_trade(bar, reason, bar['close'])

    def _best_signal(self, ind, regime, df_window) -> dict | None:
        from core.market_regime import strategy_allowed_in_regime
        results = []
        for strat in STRATEGIES:
            if not strategy_allowed_in_regime(strat.NAME, regime):
                continue
            try:
                res = strat.score(ind, df_window) if strat.NAME == 'BREAKOUT' else strat.score(ind)
            except Exception:
                continue
            if res['direction'] == 'NEUTRAL':
                continue
            min_conf = MIN_CONFLUENCE_INDICATORS + (1 if regime.name == 'RANGE' else 0)
            n_conf, _ = count_confluence(ind, res['direction'])
            if n_conf < min_conf:
                continue
            res['strategy'] = strat.NAME
            results.append(res)

        if not results:
            return None
        return max(results, key=lambda r: r['score'])


# ── Métricas ──────────────────────────────────────────────────────────

def compute_metrics(trades: list[dict], initial: float) -> dict:
    if not trades:
        return {'error': 'sin trades'}

    df = pd.DataFrame(trades)
    closed = df[df['close_reason'] != 'END_OF_DATA'].copy()

    wins   = closed[closed['pnl'] > 0]
    losses = closed[closed['pnl'] <= 0]
    total  = len(closed)

    win_rate   = len(wins) / total * 100 if total else 0
    avg_win    = wins['pnl'].mean()   if len(wins)   else 0
    avg_loss   = losses['pnl'].mean() if len(losses) else 0
    profit_factor = (wins['pnl'].sum() / abs(losses['pnl'].sum())
                     if len(losses) and losses['pnl'].sum() != 0 else float('inf'))
    total_pnl  = closed['pnl'].sum()
    final_bal  = initial + total_pnl
    max_dd     = closed['drawdown_pct'].max() if len(closed) else 0

    # Sharpe aproximado (diario)
    daily_pnl = closed.set_index('exit_time')['pnl'].resample('1D').sum()
    sharpe = (daily_pnl.mean() / daily_pnl.std() * np.sqrt(252)
              if daily_pnl.std() > 0 else 0)

    # Racha máxima de pérdidas consecutivas
    streak = max_loss_streak = cur = 0
    for p in closed['pnl']:
        if p <= 0:
            cur += 1
            max_loss_streak = max(max_loss_streak, cur)
        else:
            cur = 0

    by_strat = closed.groupby('strategy')['pnl'].agg(['sum', 'count', lambda x: (x > 0).mean() * 100])
    by_strat.columns = ['pnl_total', 'trades', 'win_rate_pct']

    by_regime = closed.groupby('regime')['pnl'].agg(['sum', 'count', lambda x: (x > 0).mean() * 100])
    by_regime.columns = ['pnl_total', 'trades', 'win_rate_pct']

    return {
        'total_trades':    total,
        'win_rate_pct':    win_rate,
        'profit_factor':   profit_factor,
        'total_pnl':       total_pnl,
        'return_pct':      (final_bal - initial) / initial * 100,
        'final_balance':   final_bal,
        'max_drawdown_pct': max_dd,
        'sharpe_ratio':    sharpe,
        'avg_win':         avg_win,
        'avg_loss':        avg_loss,
        'avg_rr_actual':   abs(avg_win / avg_loss) if avg_loss != 0 else 0,
        'max_loss_streak': max_loss_streak,
        'by_strategy':     by_strat.to_dict('index'),
        'by_regime':       by_regime.to_dict('index'),
    }


def print_report(metrics: dict, asset: str, tf: str, months: int):
    print(f"\n{'='*60}")
    print(f"  BACKTEST: {asset}/{tf} — últimos {months} meses")
    print(f"{'='*60}")
    if 'error' in metrics:
        print(f"  ⚠ {metrics['error']}")
        return

    verdict = "✅ RENTABLE" if metrics['return_pct'] > 0 else "❌ PIERDE DINERO"
    print(f"  {verdict}")
    print(f"  Trades:          {metrics['total_trades']}")
    print(f"  Win rate:        {metrics['win_rate_pct']:.1f}%")
    print(f"  Profit factor:   {metrics['profit_factor']:.2f}  (>1.5 = bueno)")
    print(f"  Retorno total:   {metrics['return_pct']:+.2f}%  (${metrics['total_pnl']:+,.2f})")
    print(f"  Balance final:   ${metrics['final_balance']:,.2f}")
    print(f"  Max drawdown:    {metrics['max_drawdown_pct']:.1f}%")
    print(f"  Sharpe ratio:    {metrics['sharpe_ratio']:.2f}  (>1.0 = bueno)")
    print(f"  Avg ganancia:    ${metrics['avg_win']:+.2f}")
    print(f"  Avg pérdida:     ${metrics['avg_loss']:+.2f}")
    print(f"  R:R real:        {metrics['avg_rr_actual']:.2f}x")
    print(f"  Racha pérdidas:  {metrics['max_loss_streak']} seguidas")

    print(f"\n  Por estrategia:")
    for strat, row in metrics['by_strategy'].items():
        print(f"    {strat}: {int(row['trades'])} trades | win={row['win_rate_pct']:.0f}% | pnl=${row['pnl_total']:+,.2f}")

    print(f"\n  Por régimen:")
    for regime, row in metrics['by_regime'].items():
        print(f"    {regime}: {int(row['trades'])} trades | win={row['win_rate_pct']:.0f}% | pnl=${row['pnl_total']:+,.2f}")


# ── Main ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Backtest del trading agent')
    parser.add_argument('--assets',  default='BTC,ETH,SOL', help='Activos separados por coma')
    parser.add_argument('--tf',      default='15m',         help='Timeframe: 1m 5m 15m 1h')
    parser.add_argument('--months',  type=int, default=12,  help='Meses de historia a descargar')
    parser.add_argument('--csv',     default='',            help='Exportar trades a CSV')
    args = parser.parse_args()

    assets = [a.strip().upper() for a in args.assets.split(',')]
    symbol_map = {'BTC': 'BTC/USDT', 'ETH': 'ETH/USDT', 'SOL': 'SOL/USDT',
                  'XAU': 'XAU/USDT', 'XAG': 'XAG/USDT'}

    all_trades = []
    all_metrics = []

    for asset in assets:
        symbol = symbol_map.get(asset)
        if not symbol:
            print(f"⚠ {asset} sin symbol map, omitiendo")
            continue

        print(f"\n▶ {asset}/{args.tf}")
        df = download_ohlcv(symbol, args.tf, args.months)
        if df.empty or len(df) < 300:
            print(f"  ⚠ Datos insuficientes ({len(df)} velas)")
            continue

        bt = Backtest(df, asset, args.tf)
        trades = bt.run()
        metrics = compute_metrics(trades, INITIAL_BALANCE)
        all_trades.extend(trades)

        print_report(metrics, asset, args.tf, args.months)
        all_metrics.append({'asset': asset, **metrics})

    # Resumen global si hay múltiples activos
    if len(assets) > 1 and all_trades:
        print(f"\n{'='*60}")
        print(f"  RESUMEN GLOBAL — {len(all_trades)} trades totales")
        global_m = compute_metrics(all_trades, INITIAL_BALANCE)
        print_report(global_m, 'TODOS', args.tf, args.months)

    if args.csv and all_trades:
        pd.DataFrame(all_trades).to_csv(args.csv, index=False)
        print(f"\n  📄 Trades exportados a: {args.csv}")

    # Consejo final
    print(f"\n{'='*60}")
    print("  INTERPRETACIÓN DE RESULTADOS:")
    print("  • Profit factor > 1.5 → estrategia robusta")
    print("  • Win rate > 45% con R:R > 1.8 → rentable a largo plazo")
    print("  • Sharpe > 1.0 → buen ajuste riesgo/retorno")
    print("  • Max drawdown < 15% → riesgo controlado")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()

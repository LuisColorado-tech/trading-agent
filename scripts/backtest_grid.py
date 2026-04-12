#!/usr/bin/env python3
"""
backtest_grid.py — Backtester específico para GridBotStrategy.

Descarga datos históricos de KuCoin (igual que backtest.py) y simula
el Grid Bot en régimen RANGE/CHOPPY con múltiples niveles simultáneos.

Diferencias clave vs backtest.py:
  - Múltiples posiciones abiertas simultáneamente por asset (hasta GRID_MAX_PER_ASSET)
  - Solo actúa cuando regime.allow_grid == True (RANGE o CHOPPY)
  - No hay trailing stop
  - Comparación de rendimiento vs "no operar en RANGE" (benchmark)

Uso:
  python3 scripts/backtest_grid.py
  python3 scripts/backtest_grid.py --assets ETH,SOL,AVAX --months 12
  python3 scripts/backtest_grid.py --assets BTC --tf 15m --months 6 --csv grid_bt.csv
  python3 scripts/backtest_grid.py --months 24 --csv reports/backtest_grid_24m.csv
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
from core.asset_profiles import get_profile
from strategies.grid_bot import (
    GridBotStrategy, GridConfig, GridLevel,
    GRID_DEFAULT_LEVELS, LEVEL_TOLERANCE_PCT, GRID_BUFFER_PCT,
)

# ── Parámetros de riesgo ─────────────────────────────────────────────
INITIAL_BALANCE     = 10_000.0
RISK_PER_TRADE_PCT  = 0.005 * 0.40  # 0.5% normal × 40% fracción grid = 0.2% por orden
MAX_CONCURRENT      = 4             # trades grid totales simultáneos
GRID_MAX_PER_ASSET  = 2             # máx por asset
SL_COOLDOWN_BARS    = 4             # velas de cooldown tras SL
WARMUP_BARS         = 100           # mínimo de velas para calcular indicadores
# ─────────────────────────────────────────────────────────────────────


# ── Descarga de datos (reutiliza lógica de backtest.py) ──────────────

def download_ohlcv(symbol: str, timeframe: str, months: int) -> pd.DataFrame:
    """Descarga velas históricas de KuCoin sin API key."""
    import ccxt, time as _t
    exchange = ccxt.kucoin({'enableRateLimit': True})

    since_dt = datetime.now(timezone.utc) - timedelta(days=months * 30)
    end_dt   = datetime.now(timezone.utc) - timedelta(minutes=30)
    since_ms = int(since_dt.timestamp() * 1000)
    end_ms   = int(end_dt.timestamp() * 1000)

    all_ohlcv = []
    limit = 1500
    print(f"  Descargando {symbol} {timeframe} desde {since_dt.date()} ({months} meses)...")

    while since_ms < end_ms:
        try:
            batch = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=limit)
        except Exception as e:
            print(f"  ⚠ Error descargando {symbol}: {e}")
            break
        if not batch:
            break

        all_ohlcv.extend(batch)
        last_ts = batch[-1][0]
        since_ms = last_ts + 1

        if len(all_ohlcv) % 15000 == 0:
            from_dt = datetime.fromtimestamp(batch[0][0] / 1000, tz=timezone.utc)
            print(f"    ... {len(all_ohlcv):,} velas | hasta {from_dt.date()}")

        if last_ts >= end_ms:
            break
        _t.sleep(0.4)

    if not all_ohlcv:
        return pd.DataFrame()

    df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    df = df.set_index('timestamp').sort_index()
    df = df[~df.index.duplicated(keep='last')]
    print(f"  ✓ {len(df):,} velas  ({df.index[0].date()} → {df.index[-1].date()})")
    return df


# ── Backtester Grid ───────────────────────────────────────────────────

class GridBacktest:
    """
    Simula el GridAgent sobre datos históricos.

    Diferencias con el backtester de tendencia:
    - Mantiene lista de trades abiertos (no solo 1)
    - Verifica que no hay nivel duplicado antes de abrir
    - No aplica trailing; cierra en TP o SL fijos
    - Registra las barras en régimen RANGE/CHOPPY para calcular "cobertura"

    Parámetros v5 (MTF):
    - df_1h: datos 1h para filtro multi-timeframe (si se pasa + use_mtf=True)
    - use_mtf: activa filtro MTF (classifica regime con ind_htf) y thresholds per-asset
    """

    def __init__(self, df: pd.DataFrame, asset: str, timeframe: str,
                 risk_pct: float = RISK_PER_TRADE_PCT,
                 df_1h: pd.DataFrame = None, use_mtf: bool = False):
        self.df        = df.copy()
        self.asset     = asset
        self.timeframe = timeframe
        self.risk_pct  = risk_pct
        self.df_1h     = df_1h
        self.use_mtf   = use_mtf
        self.strategy  = GridBotStrategy()

        self.balance   = INITIAL_BALANCE
        self.peak      = INITIAL_BALANCE
        self.trades: list[dict]    = []
        self.open_trades: list[dict] = []   # puede haber varios simultáneos
        self.cooldown_remaining    = 0

        # Estadísticas de régimen
        self.bars_total    = 0
        self.bars_range    = 0   # RANGE
        self.bars_choppy   = 0   # CHOPPY
        self.bars_trend    = 0   # TREND_UP / TREND_DOWN

    def run(self) -> list[dict]:
        for i in range(WARMUP_BARS, len(self.df)):
            window = self.df.iloc[i - WARMUP_BARS:i + 1]
            bar    = self.df.iloc[i]
            self.bars_total += 1

            # 1. Evaluar salida de trades abiertos (SL / TP)
            self._check_exits(bar)

            # 2. Cooldown tras SL
            if self.cooldown_remaining > 0:
                self.cooldown_remaining -= 1
                continue

            # 3. Calcular indicadores + régimen
            ind = IndicatorEngine.calculate(window, self.asset, self.timeframe)
            if ind is None:
                continue

            # v5: thresholds per-asset (si MTF activado)
            if self.use_mtf:
                profile_v5 = get_profile(self.asset)
                if (ind.bb_width > profile_v5.grid_bb_width_max
                        or ind.atr_pct > profile_v5.grid_atr_pct_max):
                    continue

            # v5: filtro MTF — ind_1h cacheado por hora (solo recalcula al cambiar la hora)
            ind_htf = None
            if self.use_mtf and self.df_1h is not None:
                ts_cutoff = bar.name.floor('h')  # inicio de la hora actual
                cached_ts, cached_ind = getattr(self, '_mtf_cache', (None, None))
                if ts_cutoff != cached_ts:
                    window_1h = self.df_1h[self.df_1h.index < ts_cutoff].tail(250)
                    cached_ind = (IndicatorEngine.calculate(window_1h, self.asset, '1h')
                                  if len(window_1h) >= 50 else None)
                    self._mtf_cache = (ts_cutoff, cached_ind)
                ind_htf = cached_ind

            regime = classify_market_regime(ind, ind_htf=ind_htf)

            # Contabilizar barras por régimen
            if regime.name in ('RANGE', 'CHOPPY'):
                if regime.name == 'RANGE':
                    self.bars_range += 1
                else:
                    self.bars_choppy += 1
            else:
                self.bars_trend += 1

            # 4. Solo operar si el régimen lo permite
            if not regime.allow_grid:
                continue

            # 5. Verificar límites de posiciones abiertas
            if len(self.open_trades) >= GRID_MAX_PER_ASSET:
                continue

            # 6. Calcular grid con parámetros del perfil del asset
            profile = get_profile(self.asset)
            grid = self.strategy.calculate_grid(
                ind, window,
                n_levels=profile.grid_levels,
                tp_ratio=profile.grid_tp_ratio,
                sl_ratio=profile.grid_sl_ratio,
                min_rr=profile.grid_min_rr,
                range_candles=profile.grid_range_candles,
            )
            if grid is None:
                continue

            # 7. ¿Hay un nivel cercano al precio actual?
            level = self.strategy.nearest_level(grid, ind.close)
            if level is None:
                continue

            # 8. ¿Ese nivel ya está ocupado por un trade abierto?
            if self._level_occupied(level.price):
                continue

            # 9. Abrir trade
            risk_per_unit = abs(ind.close - level.sl)
            if risk_per_unit < 1e-10:
                continue

            risk_amount = self.balance * self.risk_pct
            size = risk_amount / risk_per_unit

            self.open_trades.append({
                'asset':       self.asset,
                'timeframe':   self.timeframe,
                'strategy':    'GRID_BOT',
                'direction':   level.direction,
                'entry':       ind.close,
                'sl':          level.sl,
                'tp':          level.tp,
                'grid_level':  level.price,
                'level_idx':   level.level_idx,
                'size':        size,
                'risk':        risk_amount,
                'rr':          level.rr,
                'entry_bar':   i,
                'entry_time':  bar.name,
                'regime':      regime.name,
                'range_pct':   grid.range_pct,
            })

        # Cerrar lo que quede abierto al final del período
        if self.open_trades:
            last = self.df.iloc[-1]
            for t in list(self.open_trades):
                self._force_close(t, last, 'END_OF_DATA')

        return self.trades

    def _check_exits(self, bar: pd.Series):
        """Evalúa SL/TP para todos los trades abiertos en la barra actual."""
        for t in list(self.open_trades):
            hit_sl = hit_tp = False

            if t['direction'] == 'SELL':
                hit_sl = bar['high'] >= t['sl']
                hit_tp = bar['low']  <= t['tp']
            else:  # BUY (por si se añade en el futuro)
                hit_sl = bar['low']  <= t['sl']
                hit_tp = bar['high'] >= t['tp']

            if hit_tp:
                self._close_trade(t, bar, 'TP', t['tp'])
            elif hit_sl:
                self._close_trade(t, bar, 'SL', t['sl'])

    def _close_trade(self, trade: dict, bar: pd.Series,
                     reason: str, exit_price: float):
        t = trade
        if t['direction'] == 'SELL':
            pnl = (t['entry'] - exit_price) * t['size']
        else:
            pnl = (exit_price - t['entry']) * t['size']

        self.balance += pnl
        self.peak = max(self.peak, self.balance)

        record = {
            **t,
            'exit':          exit_price,
            'exit_time':     bar.name,
            'close_reason':  reason,
            'pnl':           pnl,
            'pnl_pct':       pnl / (t['entry'] * t['size']) * 100 if t['entry'] else 0,
            'balance_after': self.balance,
            'drawdown_pct':  (self.peak - self.balance) / self.peak * 100,
        }
        self.trades.append(record)
        self.open_trades.remove(t)

        if reason == 'SL':
            self.cooldown_remaining = SL_COOLDOWN_BARS

    def _force_close(self, trade: dict, bar: pd.Series, reason: str):
        self._close_trade(trade, bar, reason, bar['close'])

    def _level_occupied(self, level_price: float,
                        tolerance: float = LEVEL_TOLERANCE_PCT) -> bool:
        """True si ya hay un trade abierto a ±tolerance% de ese nivel."""
        for t in self.open_trades:
            if abs(t['entry'] - level_price) / level_price < tolerance:
                return True
        return False


# ── Métricas ──────────────────────────────────────────────────────────

def compute_metrics(trades: list[dict], initial: float,
                    bars_total: int = 0, bars_range: int = 0, bars_choppy: int = 0) -> dict:
    if not trades:
        return {'error': 'sin trades'}

    df = pd.DataFrame(trades)
    closed = df[df['close_reason'] != 'END_OF_DATA'].copy()

    if len(closed) == 0:
        return {'error': 'todos los trades quedaron abiertos'}

    wins   = closed[closed['pnl'] > 0]
    losses = closed[closed['pnl'] <= 0]
    total  = len(closed)

    win_rate      = len(wins) / total * 100 if total else 0
    avg_win       = float(wins['pnl'].mean())   if len(wins)   else 0.0
    avg_loss      = float(losses['pnl'].mean()) if len(losses) else 0.0
    profit_factor = (wins['pnl'].sum() / abs(losses['pnl'].sum())
                     if len(losses) and losses['pnl'].sum() != 0 else float('inf'))
    total_pnl  = float(closed['pnl'].sum())
    final_bal  = initial + total_pnl
    max_dd     = float(closed['drawdown_pct'].max()) if len(closed) else 0.0

    # Sharpe (diario)
    daily_pnl = closed.set_index('exit_time')['pnl'].resample('1D').sum()
    sharpe = (float(daily_pnl.mean() / daily_pnl.std() * np.sqrt(252))
              if daily_pnl.std() > 0 else 0.0)

    # Duración media del trade (en barras)
    closed_dur = closed.copy()
    avg_bars = float((closed_dur['exit_time'] - closed_dur['entry_time'])
                     .dt.total_seconds().mean() / 900) if len(closed_dur) > 0 else 0.0

    # Racha pérdidas consecutivas
    max_loss_streak = cur = 0
    for p in closed['pnl']:
        if p <= 0:
            cur += 1
            max_loss_streak = max(max_loss_streak, cur)
        else:
            cur = 0

    # Desglose por régimen
    by_regime = (closed.groupby('regime')['pnl']
                 .agg(['sum', 'count', lambda x: (x > 0).mean() * 100])
                 .rename(columns={'sum': 'pnl_total', 'count': 'trades', '<lambda_0>': 'win_rate_pct'}))

    # Cobertura de régimen
    range_bars_pct = (bars_range + bars_choppy) / bars_total * 100 if bars_total else 0

    return {
        'total_trades':       total,
        'win_rate_pct':       win_rate,
        'profit_factor':      profit_factor,
        'total_pnl':          total_pnl,
        'return_pct':         (final_bal - initial) / initial * 100,
        'final_balance':      final_bal,
        'max_drawdown_pct':   max_dd,
        'sharpe_ratio':       sharpe,
        'avg_win':            avg_win,
        'avg_loss':           avg_loss,
        'avg_rr_actual':      abs(avg_win / avg_loss) if avg_loss != 0 else 0,
        'avg_bars_open':      avg_bars,
        'max_loss_streak':    max_loss_streak,
        'by_regime':          by_regime.to_dict('index'),
        'bars_total':         bars_total,
        'bars_range_pct':     range_bars_pct,
    }


def print_report(metrics: dict, asset: str, tf: str, months: int):
    print(f"\n{'='*62}")
    print(f"  BACKTEST GRID: {asset}/{tf} — últimos {months} meses")
    print(f"{'='*62}")
    if 'error' in metrics:
        print(f"  ⚠ {metrics['error']}")
        return

    verdict = '✅ RENTABLE' if metrics['return_pct'] > 0 else '❌ PIERDE DINERO'
    print(f"  {verdict}")
    print(f"  Trades cerrados:    {metrics['total_trades']}")
    print(f"  Win rate:           {metrics['win_rate_pct']:.1f}%")
    print(f"  Profit factor:      {metrics['profit_factor']:.2f}  (>1.2 = aceptable para grid)")
    print(f"  Retorno total:      {metrics['return_pct']:+.2f}%  (${metrics['total_pnl']:+,.2f})")
    print(f"  Balance final:      ${metrics['final_balance']:,.2f}")
    print(f"  Max drawdown:       {metrics['max_drawdown_pct']:.1f}%")
    print(f"  Sharpe ratio:       {metrics['sharpe_ratio']:.2f}")
    print(f"  Avg ganancia:       ${metrics['avg_win']:+.2f}")
    print(f"  Avg pérdida:        ${metrics['avg_loss']:+.2f}")
    print(f"  R:R real:           {metrics['avg_rr_actual']:.2f}x")
    print(f"  Duración media:     {metrics['avg_bars_open']:.1f} barras ({metrics['avg_bars_open']*15/60:.1f}h en 15m)")
    print(f"  Racha pérdidas:     {metrics['max_loss_streak']} seguidas")
    print(f"  Barras RANGE/CHOP:  {metrics['bars_range_pct']:.1f}% del tiempo")

    print(f"\n  Por régimen:")
    for regime, row in metrics['by_regime'].items():
        print(f"    {regime:<12}: {int(row['trades'])} trades | "
              f"win={row['win_rate_pct']:.0f}% | pnl=${row['pnl_total']:+,.2f}")


# ── Main ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Backtest del Grid Bot')
    parser.add_argument('--assets', default='BTC,ETH,SOL,AVAX,INJ',
                        help='Activos separados por coma (default: BTC,ETH,SOL,AVAX,INJ)')
    parser.add_argument('--tf',     default='15m',
                        help='Timeframe (default: 15m)')
    parser.add_argument('--months', type=int, default=12,
                        help='Meses de historia (default: 12)')
    parser.add_argument('--csv',    default='',
                        help='Exportar trades a CSV')
    parser.add_argument('--mtf', action='store_true', default=False,
                        help='Activar filtro MTF 1h + thresholds per-asset (v5)')
    args = parser.parse_args()

    symbol_map = {
        'BTC':  'BTC/USDT', 'ETH':  'ETH/USDT', 'SOL':  'SOL/USDT',
        'AVAX': 'AVAX/USDT', 'INJ':  'INJ/USDT',
        'XAU':  'XAU/USDT', 'XAG':  'XAG/USDT',
    }

    assets = [a.strip().upper() for a in args.assets.split(',')]
    all_trades: list[dict] = []
    all_metrics: list[dict] = []

    for asset in assets:
        symbol = symbol_map.get(asset)
        if not symbol:
            print(f"⚠ {asset} sin symbol map, omitiendo")
            continue

        print(f"\n▶ {asset}/{args.tf}" + (" [MTF v5]" if args.mtf else " [sin MTF v4]"))
        df = download_ohlcv(symbol, args.tf, args.months)
        if df.empty or len(df) < WARMUP_BARS + 50:
            print(f"  ⚠ Datos insuficientes ({len(df)} velas)")
            continue

        df_1h = None
        if args.mtf:
            df_1h = download_ohlcv(symbol, '1h', args.months)
            if df_1h.empty:
                print(f"  ⚠ No se pudo descargar 1h para {asset}; MTF desactivado")
                df_1h = None

        bt = GridBacktest(df, asset, args.tf, df_1h=df_1h, use_mtf=args.mtf)
        trades = bt.run()
        metrics = compute_metrics(
            trades, INITIAL_BALANCE,
            bars_total=bt.bars_total,
            bars_range=bt.bars_range,
            bars_choppy=bt.bars_choppy,
        )
        all_trades.extend(trades)
        print_report(metrics, asset, args.tf, args.months)
        all_metrics.append({'asset': asset, **{k: v for k, v in metrics.items()
                                                if not isinstance(v, dict)}})

    # Resumen global si hay múltiples activos
    if len(assets) > 1 and all_trades:
        bars_total  = sum(m.get('bars_total', 0) for m in all_metrics)
        bars_rangep = sum(m.get('bars_range_pct', 0) * m.get('bars_total', 0)
                          for m in all_metrics) / bars_total if bars_total else 0

        print(f"\n{'='*62}")
        print(f"  RESUMEN GLOBAL — {len(all_trades)} trades totales en {len(assets)} assets")
        global_m = compute_metrics(all_trades, INITIAL_BALANCE, bars_total=bars_total)
        global_m['bars_range_pct'] = bars_rangep
        print_report(global_m, 'TODOS', args.tf, args.months)

    if args.csv and all_trades:
        out_path = args.csv or f'reports/backtest_grid_{args.tf}_{args.months}m.csv'
        pd.DataFrame(all_trades).to_csv(out_path, index=False)
        print(f"\n  📄 Trades exportados a: {out_path}")

    # Comparativa vs benchmark
    print(f"\n{'='*62}")
    print("  INTERPRETACIÓN (Grid Bot):")
    print("  • Profit factor > 1.2 → válido (frecuencia alta, RR < 2)")
    print("  • Win rate > 55%      → grid saludable")
    print("  • Barras RANGE < 30%  → mercado mayormente en tendencia (grid poco activo)")
    print("  • Max drawdown < 10%  → riesgo controlado")
    print("  • Si RANGE/CHOP > 40% del tiempo → Grid Bot muy relevante para el sistema")
    print(f"{'='*62}\n")


if __name__ == '__main__':
    main()

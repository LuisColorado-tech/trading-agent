#!/usr/bin/env python3
"""
backtest_stocks.py — Backtester del stocks agent sobre datos históricos reales.

Descarga hasta 2 años de velas de yfinance (gratis) y aplica exactamente
la misma lógica de indicadores, régimen, estrategia y perfiles que usa
el agente en producción.

Uso:
  python3 scripts/backtest_stocks.py                           # 12 activos, 1h, 2 años
  python3 scripts/backtest_stocks.py --tf 15m                  # 15m (últimos 60 días, límite yfinance)
  python3 scripts/backtest_stocks.py --assets NVDA TSLA        # solo esos activos
  python3 scripts/backtest_stocks.py --tf 1h --months 12       # 1h, 1 año
  python3 scripts/backtest_stocks.py --no-macro                # sin macro filter
  python3 scripts/backtest_stocks.py --csv resultados.csv      # exportar trades
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
from core.stocks_profiles import get_stocks_profile
from strategies.stocks_momentum import StocksMomentumStrategy
from strategies.stocks_trend_etf import StocksTrendEtfStrategy

_STRATEGIES = {
    'MOMENTUM':  StocksMomentumStrategy(),
    'TREND_ETF': StocksTrendEtfStrategy(),
}

# ── Universo completo ─────────────────────────────────────────────────
ALL_ASSETS = ['NVDA', 'TSLA', 'AAPL', 'META', 'AMZN', 'QQQ', 'GLD', 'SLV',
              'EEM', 'FXI', 'EWJ']
# Eliminados del default por PF < 1.0 en backtest 24m: SPY (PF=0.94), EWZ (PF=0.89)
# Añadido SLV: PF=1.31 ✓, WR=37.2%, MaxDD=14.3%

# ── Parámetros de simulación ──────────────────────────────────────────
INITIAL_BALANCE    = 220.0      # capital real del usuario
RISK_PER_TRADE_PCT = 0.01       # 1% por trade = $2.20 con $220
MAX_CONCURRENT     = 3
WARMUP_BARS        = 100        # barras mínimas para indicadores

# Horario NYSE: 9:30-16:00 ET = 13:30-20:00 UTC (EDT), 14:30-21:00 UTC (EST)
NYSE_OPEN_UTC  = 13   # hora mínima UTC (EDT, verano)
NYSE_CLOSE_UTC = 21   # hora máxima UTC (EST, invierno) — usamos 20 para ser conservadores


# ── Descarga de datos ─────────────────────────────────────────────────

def download_yfinance(symbol: str, timeframe: str, months: int) -> pd.DataFrame:
    """Descarga histórico de yfinance para el símbolo.

    Límites reales de yfinance:
      15m / 5m  → máximo 60 días (period='60d')
      1h        → máximo ~730 días (start explícito)
      1d        → sin límite práctico (start explícito)
    """
    import yfinance as yf

    _TF_MAP = {'15m': '15m', '1h': '1h', '1d': '1d', '5m': '5m'}
    interval = _TF_MAP.get(timeframe, '15m')

    if interval in ('15m', '5m'):
        # Máximo 60 días reales para intraday corto — period fijo
        try:
            df = yf.download(
                symbol,
                period='60d',
                interval=interval,
                auto_adjust=True,
                progress=False,
            )
        except Exception:
            return pd.DataFrame()
    else:
        start_date = datetime.now() - timedelta(days=months * 30)
        try:
            df = yf.download(
                symbol,
                start=start_date.strftime('%Y-%m-%d'),
                interval=interval,
                auto_adjust=True,
                progress=False,
            )
        except Exception:
            return pd.DataFrame()

    if df.empty:
        return pd.DataFrame()

    # Normalizar columnas (yfinance puede retornar MultiIndex)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.rename(columns={
        'Open': 'open', 'High': 'high', 'Low': 'low',
        'Close': 'close', 'Volume': 'volume',
    })
    df = df[['open', 'high', 'low', 'close', 'volume']].copy()
    df.index = pd.to_datetime(df.index, utc=True)
    df = df[~df.index.duplicated(keep='last')].sort_index()
    df = df.dropna()
    return df


def download_macro(months: int) -> dict:
    """Descarga SPY y QQQ diario para calcular macro bias histórico."""
    spy = download_yfinance('SPY', '1d', months + 1)
    qqq = download_yfinance('QQQ', '1d', months + 1)
    return {'SPY': spy, 'QQQ': qqq}


def get_macro_bias_at(dt: pd.Timestamp, macro_data: dict) -> str:
    """Calcula el macro bias en un momento dado usando rolling 10d."""
    try:
        spy = macro_data['SPY']
        qqq = macro_data['QQQ']
        # Filtrar hasta el momento dado
        dt_date = dt.date()
        spy_h = spy[spy.index.date <= dt_date]
        qqq_h = qqq[qqq.index.date <= dt_date]
        if len(spy_h) < 10 or len(qqq_h) < 10:
            return 'NEUTRAL'
        spy_trend = spy_h.iloc[-1]['close'] > spy_h['close'].rolling(10).mean().iloc[-1]
        qqq_trend = qqq_h.iloc[-1]['close'] > qqq_h['close'].rolling(10).mean().iloc[-1]
        if spy_trend and qqq_trend:
            return 'BULL'
        elif not spy_trend and not qqq_trend:
            return 'BEAR'
        return 'NEUTRAL'
    except Exception:
        return 'NEUTRAL'


def is_nyse_open(dt: pd.Timestamp) -> bool:
    """Comprueba si el timestamp cae dentro del horario NYSE."""
    if dt.weekday() >= 5:
        return False
    hour_utc = dt.hour
    return NYSE_OPEN_UTC <= hour_utc < NYSE_CLOSE_UTC


# ── Motor de backtest ─────────────────────────────────────────────────

class StocksBacktest:
    def __init__(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
        macro_data: dict,
        use_macro_filter: bool = True,
        risk_pct: float = RISK_PER_TRADE_PCT,
    ):
        self.df = df.copy()
        self.symbol = symbol
        self.timeframe = timeframe
        self.macro_data = macro_data
        self.profile = get_stocks_profile(symbol)
        self.strategy = _STRATEGIES.get(self.profile.strategy_name, _STRATEGIES['MOMENTUM'])
        self.use_macro_filter = use_macro_filter
        self.risk_pct = risk_pct

        self.balance = INITIAL_BALANCE
        self.peak = INITIAL_BALANCE
        self.max_dd = 0.0
        self.trades: list[dict] = []
        self.open_trade: dict | None = None

    def run(self) -> list[dict]:
        for i in range(WARMUP_BARS, len(self.df)):
            bar = self.df.iloc[i]
            ts  = self.df.index[i]

            # Filtro horario NYSE
            if not is_nyse_open(ts):
                continue

            # Filtro horas bloqueadas por perfil
            if self.profile.blocked_hours_utc and ts.hour in self.profile.blocked_hours_utc:
                if self.open_trade:
                    self._check_exit(bar)
                continue

            window = self.df.iloc[i - WARMUP_BARS:i + 1]

            # Gestionar trade abierto primero
            if self.open_trade:
                self._check_exit(bar)

            if self.open_trade:
                continue  # ya hay trade abierto en este símbolo

            # Calcular indicadores
            ind = IndicatorEngine.calculate(window, self.symbol, self.timeframe)
            if ind is None:
                continue

            # Régimen — solo para activos con use_regime_filter=True
            if self.profile.use_regime_filter:
                # Override ADX: tendencia confirmada por ADX > 20 siempre pasa
                adx_confirms = ind.adx > 20
                if not adx_confirms:
                    regime = classify_market_regime(ind)
                    if not (regime.allow_trend or regime.allow_breakout):
                        continue

            # Score
            result = self.strategy.score(ind, xsignal_boost=0)
            if result['direction'] == 'NEUTRAL':
                continue

            direction = result['direction']

            # Macro filter
            if self.use_macro_filter and self.profile.use_macro_filter:
                macro = get_macro_bias_at(ts, self.macro_data)
                if macro == 'BEAR' and direction == 'BUY':
                    continue
                if macro == 'BULL' and direction == 'SELL':
                    continue

            # ATR filter
            atr = ind.atr if hasattr(ind, 'atr') and ind.atr else 0
            price = float(bar['close'])
            if atr and (atr / price) < self.profile.min_atr_pct:
                continue

            # Dirección permitida por perfil
            if direction not in self.profile.allowed_directions:
                continue

            # Tamaño de posición
            risk_amount = self.balance * self.risk_pct
            sl_distance = price * (atr / price if atr else 0.01) * self.profile.sl_multiplier
            if sl_distance <= 0:
                sl_distance = price * 0.01
            qty = risk_amount / sl_distance
            notional = qty * price

            # Calcular SL y TP
            if direction == 'BUY':
                sl_price = price - sl_distance
                tp_price = price + sl_distance * self.profile.tp_multiplier
            else:
                sl_price = price + sl_distance
                tp_price = price - sl_distance * self.profile.tp_multiplier

            self.open_trade = {
                'symbol': self.symbol,
                'direction': direction,
                'entry_price': price,
                'entry_ts': ts,
                'sl': sl_price,
                'tp': tp_price,
                'qty': qty,
                'notional': notional,
                'score': result['score'],
            }

        # Cerrar trade abierto al final (como si fuera al precio de cierre)
        if self.open_trade:
            last_bar = self.df.iloc[-1]
            self._force_close(last_bar, 'end_of_data')

        return self.trades

    def _check_exit(self, bar) -> None:
        t = self.open_trade
        high = float(bar['high'])
        low  = float(bar['low'])
        close = float(bar['close'])

        hit_sl = hit_tp = False
        if t['direction'] == 'BUY':
            hit_sl = low  <= t['sl']
            hit_tp = high >= t['tp']
        else:
            hit_sl = high >= t['sl']
            hit_tp = low  <= t['tp']

        if hit_tp:
            self._close_trade(t['tp'], 'TP')
        elif hit_sl:
            self._close_trade(t['sl'], 'SL')

    def _force_close(self, bar, reason: str) -> None:
        self._close_trade(float(bar['close']), reason)

    def _close_trade(self, exit_price: float, reason: str) -> None:
        t = self.open_trade
        if t['direction'] == 'BUY':
            pnl = (exit_price - t['entry_price']) * t['qty']
        else:
            pnl = (t['entry_price'] - exit_price) * t['qty']

        self.balance += pnl
        if self.balance > self.peak:
            self.peak = self.balance
        dd = (self.peak - self.balance) / self.peak
        if dd > self.max_dd:
            self.max_dd = dd

        self.trades.append({
            'symbol':      t['symbol'],
            'direction':   t['direction'],
            'entry_price': t['entry_price'],
            'exit_price':  exit_price,
            'entry_ts':    t['entry_ts'],
            'qty':         t['qty'],
            'notional':    t['notional'],
            'pnl':         pnl,
            'reason':      reason,
            'score':       t['score'],
        })
        self.open_trade = None


# ── Análisis de resultados ────────────────────────────────────────────

def analyze(trades: list[dict], symbol: str, initial_balance: float) -> dict:
    if not trades:
        return {'symbol': symbol, 'trades': 0}

    df = pd.DataFrame(trades)
    wins = df[df['pnl'] > 0]
    losses = df[df['pnl'] <= 0]

    gross_profit = wins['pnl'].sum() if len(wins) else 0
    gross_loss   = abs(losses['pnl'].sum()) if len(losses) else 0.001
    pf = gross_profit / gross_loss

    total_pnl = df['pnl'].sum()
    wr = len(wins) / len(df) * 100

    # Drawdown máximo
    cumulative = df['pnl'].cumsum() + initial_balance
    rolling_max = cumulative.cummax()
    dd_series = (rolling_max - cumulative) / rolling_max
    max_dd = dd_series.max() * 100

    # Avg trade
    avg_win  = wins['pnl'].mean() if len(wins) else 0
    avg_loss = losses['pnl'].mean() if len(losses) else 0

    return {
        'symbol':       symbol,
        'trades':       len(df),
        'win_rate':     round(wr, 1),
        'profit_factor': round(pf, 2),
        'total_pnl':    round(total_pnl, 2),
        'pct_return':   round(total_pnl / initial_balance * 100, 1),
        'max_dd_pct':   round(max_dd, 1),
        'avg_win':      round(avg_win, 2),
        'avg_loss':     round(avg_loss, 2),
        'buys':         len(df[df['direction'] == 'BUY']),
        'sells':        len(df[df['direction'] == 'SELL']),
        'tp_hits':      len(df[df['reason'] == 'TP']),
        'sl_hits':      len(df[df['reason'] == 'SL']),
    }


def print_summary(results: list[dict], timeframe: str, months: int, use_macro: bool) -> None:
    print(f"\n{'='*80}")
    print(f"  STOCKS BACKTEST — {timeframe.upper()} | {months} meses | macro_filter={'ON' if use_macro else 'OFF'}")
    print(f"  Capital inicial: ${INITIAL_BALANCE} | Riesgo/trade: {RISK_PER_TRADE_PCT*100:.1f}%")
    print(f"{'='*80}")
    print(f"{'Ticker':<6} {'Trades':>6} {'WR%':>6} {'PF':>5} {'PnL$':>8} {'Ret%':>6} {'MaxDD%':>7} {'BUY/SELL':>9} {'TP/SL':>7}")
    print('-'*80)

    total_trades = total_pnl = 0
    edge_assets = []

    for r in sorted(results, key=lambda x: x.get('profit_factor', 0), reverse=True):
        if r['trades'] == 0:
            print(f"{r['symbol']:<6} {'sin datos':>50}")
            continue

        pf_str = f"{r['profit_factor']:.2f}"
        wr_str = f"{r['win_rate']:.1f}%"
        pnl_str = f"${r['total_pnl']:+.2f}"
        ret_str = f"{r['pct_return']:+.1f}%"
        dd_str  = f"{r['max_dd_pct']:.1f}%"
        bs_str  = f"{r['buys']}/{r['sells']}"
        ts_str  = f"{r['tp_hits']}/{r['sl_hits']}"

        # Colorear si tiene edge (PF >= 1.3, trades >= 15)
        has_edge = r['profit_factor'] >= 1.3 and r['trades'] >= 15
        marker = ' ✓' if has_edge else '  '
        if has_edge:
            edge_assets.append(r['symbol'])

        print(f"{r['symbol']:<6} {r['trades']:>6} {wr_str:>6} {pf_str:>5} {pnl_str:>8} {ret_str:>6} {dd_str:>7} {bs_str:>9} {ts_str:>7}{marker}")

        total_trades += r['trades']
        total_pnl += r.get('total_pnl', 0)

    print('-'*80)
    print(f"{'TOTAL':<6} {total_trades:>6} {'':>6} {'':>5} ${total_pnl:+.2f}")
    print(f"\n✓ = PF ≥ 1.3 y ≥ 15 trades (edge real)")
    if edge_assets:
        print(f"Activos con edge: {', '.join(edge_assets)}")
    else:
        print("Sin activos con edge suficiente — revisar parámetros")
    print('='*80)


# ── Entry point ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Backtest del stocks agent')
    parser.add_argument('--assets', nargs='+', default=ALL_ASSETS, metavar='SYM',
                        help='Activos a testear (default: todos)')
    parser.add_argument('--tf', default='1h', choices=['5m', '15m', '1h', '1d'],
                        # 1h default: 2 años disponibles en yfinance. 15m = solo 60 días.
                        help='Timeframe (default: 15m)')
    parser.add_argument('--months', type=int, default=24,
                        help='Meses de historia (default: 24)')
    parser.add_argument('--no-macro', action='store_true',
                        help='Desactivar macro filter para comparación')
    parser.add_argument('--csv', metavar='FILE',
                        help='Exportar todos los trades a CSV')
    parser.add_argument('--compare-macro', action='store_true',
                        help='Correr con y sin macro filter y comparar')
    args = parser.parse_args()

    assets   = [a.upper() for a in args.assets]
    tf       = args.tf
    months   = args.months
    use_macro = not args.no_macro

    print(f"\nDescargando macro data (SPY/QQQ) para {months} meses...")
    macro_data = download_macro(months)
    print(f"  SPY: {len(macro_data['SPY'])} barras diarias")
    print(f"  QQQ: {len(macro_data['QQQ'])} barras diarias")

    all_trades = []
    results = []

    for symbol in assets:
        print(f"\n[{symbol}] Descargando {tf} × {months} meses...", end=' ', flush=True)
        df = download_yfinance(symbol, tf, months)

        if df.empty or len(df) < WARMUP_BARS + 10:
            print(f"sin datos suficientes ({len(df)} barras)")
            results.append({'symbol': symbol, 'trades': 0})
            continue

        print(f"{len(df):,} barras ({df.index[0].date()} → {df.index[-1].date()})")

        bt = StocksBacktest(df, symbol, tf, macro_data, use_macro_filter=use_macro)
        trades = bt.run()
        r = analyze(trades, symbol, INITIAL_BALANCE)
        results.append(r)
        all_trades.extend(trades)

        if trades:
            print(f"  → {r['trades']} trades | WR={r['win_rate']}% | PF={r['profit_factor']} | "
                  f"PnL=${r['total_pnl']:+.2f} ({r['pct_return']:+.1f}%) | MaxDD={r['max_dd_pct']}%")
        else:
            print(f"  → 0 trades (sin señales)")

    print_summary(results, tf, months, use_macro)

    # Comparación con/sin macro filter
    if args.compare_macro and use_macro:
        print("\n\n--- COMPARACIÓN: SIN macro filter ---")
        results_nomacro = []
        for symbol in assets:
            df = download_yfinance(symbol, tf, months)
            if df.empty or len(df) < WARMUP_BARS + 10:
                results_nomacro.append({'symbol': symbol, 'trades': 0})
                continue
            macro_data2 = download_macro(months)
            bt2 = StocksBacktest(df, symbol, tf, macro_data2, use_macro_filter=False)
            trades2 = bt2.run()
            results_nomacro.append(analyze(trades2, symbol, INITIAL_BALANCE))
        print_summary(results_nomacro, tf, months, use_macro=False)

    # Exportar CSV
    if args.csv and all_trades:
        csv_df = pd.DataFrame(all_trades)
        csv_df.to_csv(args.csv, index=False)
        print(f"\nTrades exportados a: {args.csv}")

    # Resumen ejecutivo
    valid = [r for r in results if r['trades'] >= 10]
    if valid:
        avg_pf = np.mean([r['profit_factor'] for r in valid])
        avg_wr = np.mean([r['win_rate'] for r in valid])
        print(f"\nResumen ejecutivo (activos con ≥10 trades):")
        print(f"  PF promedio:  {avg_pf:.2f}")
        print(f"  WR promedio:  {avg_wr:.1f}%")
        print(f"  Criterio live (PF ≥ 1.3): {'✓ CUMPLE' if avg_pf >= 1.3 else '✗ NO CUMPLE'}")


if __name__ == '__main__':
    main()

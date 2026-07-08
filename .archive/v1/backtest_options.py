"""
backtest_options.py — Backtest histórico de la estrategia Theta Farming (venta de PUTs OTM).

Metodología:
  - Datos: precios diarios de cierre via KuCoin (CCXT) — 24 meses
  - IV proxy: volatilidad histórica rolling 30 días (HV30)
  - IV Rank: percentil de HV30 actual vs últimos 90 días
  - Entrada: cuando IV Rank ≥ MIN_IV_RANK%, vender PUT OTM_PCT OTM con DTE=7
  - Prima estimada: Black-Scholes con HV30 como IV implícita
  - Tamaño: BTC=0.1 contratos, ETH=1.0 contratos
  - Margen: max(0.10, 0.15 - OTM_PCT) × contracts × price
  - Salida: expiración worthless (PnL = +prima), asignación (PnL = -intrínseco),
            stop STOP_MULT× prima, profit lock 80%

Uso (single run):
  /opt/trading/venv/bin/python3 scripts/backtest_options.py
  /opt/trading/venv/bin/python3 scripts/backtest_options.py --asset ETH
  /opt/trading/venv/bin/python3 scripts/backtest_options.py --asset BTC,ETH

Uso (sweep de parámetros):
  /opt/trading/venv/bin/python3 scripts/backtest_options.py --sweep
"""
import argparse
import math
import sys
from datetime import date, timedelta

import ccxt
import numpy as np
import pandas as pd
from loguru import logger

sys.path.insert(0, '/opt/trading')

# ── Parámetros por defecto (configuración baseline) ───────────────────────────
DEFAULT_OTM_PCT          = 0.07      # strike 7% por debajo del precio spot
DEFAULT_DTE              = 7         # días hasta expiración de cada contrato simulado
DEFAULT_HV_WINDOW        = 30        # días para volatilidad histórica
DEFAULT_IV_RANK_LOOKBACK = 90        # días para calcular IV Rank
DEFAULT_MIN_IV_RANK      = 15.0      # umbral mínimo para vender (%)
DEFAULT_MAX_OPEN         = 3         # máximo de posiciones simultáneas
DEFAULT_STOP_MULT        = 2.0       # stop si prima sube N×
DEFAULT_PROFIT_LOCK_PCT  = 0.80      # cerrar si prima cae 80%
INITIAL_BALANCE          = 2000.0    # capital inicial USD

CONTRACT_SIZE = {'BTC': 0.1, 'ETH': 1.0}
SYMBOL_MAP    = {'BTC': 'BTC/USDT', 'ETH': 'ETH/USDT'}

# ── Variantes para sweep paramétrico ─────────────────────────────────────────
# Objetivo: PF ≥ 1.10 AND MaxDD ≤ 40%
SWEEP_VARIANTS = [
    {
        'name':        'Baseline',
        'otm_pct':     0.07,
        'min_iv_rank': 15.0,
        'stop_mult':   2.0,
        'max_open':    3,
    },
    {
        'name':        'A-Conservadora',   # todas las mejoras juntas
        'otm_pct':     0.10,
        'min_iv_rank': 25.0,
        'stop_mult':   3.0,
        'max_open':    2,
    },
    {
        'name':        'B-SoloStrike',     # solo OTM más lejano
        'otm_pct':     0.10,
        'min_iv_rank': 15.0,
        'stop_mult':   2.0,
        'max_open':    3,
    },
    {
        'name':        'C-SoloFiltroIV',   # solo ser más selectivo
        'otm_pct':     0.07,
        'min_iv_rank': 30.0,
        'stop_mult':   2.0,
        'max_open':    2,
    },
    {
        'name':        'D-Equilibrada',    # balance entre frecuencia y riesgo
        'otm_pct':     0.09,
        'min_iv_rank': 25.0,
        'stop_mult':   2.5,
        'max_open':    2,
    },
]


# ── Black-Scholes — precio de PUT europeo ────────────────────────────────────

def _norm_cdf(x: float) -> float:
    return (1 + math.erf(x / math.sqrt(2))) / 2

def bs_put_price(S: float, K: float, T: float, iv: float, r: float = 0.0) -> float:
    """
    Black-Scholes PUT price.
    S = precio spot, K = strike, T = años hasta expiración,
    iv = volatilidad implícita (fracción), r = tasa libre de riesgo.
    """
    if T <= 0 or iv <= 0 or S <= 0:
        return 0.0
    d1 = (math.log(S / K) + (r + 0.5 * iv ** 2) * T) / (iv * math.sqrt(T))
    d2 = d1 - iv * math.sqrt(T)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


# ── Cache de OHLCV (evitar re-descarga en sweep) ──────────────────────────────
_OHLCV_CACHE: dict = {}  # cache_key -> raw df (sin HV calculado)


# ── Descarga de datos ─────────────────────────────────────────────────────────

def fetch_ohlcv(asset: str, months: int = 24) -> pd.DataFrame:
    """Descarga datos diarios. Primera llamada va a la red, siguientes usan caché."""
    cache_key = f'{asset}_{months}'
    if cache_key in _OHLCV_CACHE:
        return _OHLCV_CACHE[cache_key].copy()

    exchange = ccxt.kucoin({'enableRateLimit': True})
    symbol = SYMBOL_MAP[asset]
    since_ms = exchange.parse8601(
        (date.today() - timedelta(days=months * 31)).strftime('%Y-%m-%dT00:00:00Z')
    )
    ohlcv = []
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe='1d', since=since_ms, limit=500)
        if not batch:
            break
        ohlcv.extend(batch)
        since_ms = batch[-1][0] + 86_400_000
        if len(batch) < 500:
            break

    df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
    df['date'] = pd.to_datetime(df['ts'], unit='ms').dt.date
    df = df.drop_duplicates('date').sort_values('date').reset_index(drop=True)
    logger.info(f'[{asset}] {len(df)} días descargados ({df["date"].iloc[0]} → {df["date"].iloc[-1]})')
    _OHLCV_CACHE[cache_key] = df
    return df.copy()


# ── Cálculo de HV e IV Rank ───────────────────────────────────────────────────

def add_hv_and_iv_rank(
    df: pd.DataFrame,
    hv_window: int = DEFAULT_HV_WINDOW,
    iv_rank_lookback: int = DEFAULT_IV_RANK_LOOKBACK,
) -> pd.DataFrame:
    df = df.copy()
    df['log_ret'] = np.log(df['close'] / df['close'].shift(1))
    df['hv30'] = df['log_ret'].rolling(hv_window).std() * math.sqrt(252) * 100  # % anual
    def iv_rank_at(idx: int) -> float:
        start = max(0, idx - iv_rank_lookback + 1)
        window = df['hv30'].iloc[start:idx + 1].dropna()
        if len(window) < 5:
            return float('nan')
        cur = window.iloc[-1]
        lo, hi = window.min(), window.max()
        return (cur - lo) / (hi - lo) * 100 if hi > lo else 50.0

    df['iv_rank'] = [iv_rank_at(i) for i in range(len(df))]
    return df


# ── Backtest principal ────────────────────────────────────────────────────────

def run_backtest(asset: str, config: dict | None = None, months: int = 24) -> dict:
    """
    Corre el backtest para un activo con una configuración de parámetros.

    config: dict con claves opcionales:
        otm_pct, min_iv_rank, stop_mult, max_open,
        dte, hv_window, iv_rank_lookback, profit_lock_pct
    """
    cfg = config or {}
    otm_pct          = cfg.get('otm_pct',          DEFAULT_OTM_PCT)
    min_iv_rank      = cfg.get('min_iv_rank',       DEFAULT_MIN_IV_RANK)
    stop_mult        = cfg.get('stop_mult',         DEFAULT_STOP_MULT)
    max_open         = cfg.get('max_open',          DEFAULT_MAX_OPEN)
    dte              = cfg.get('dte',               DEFAULT_DTE)
    hv_window        = cfg.get('hv_window',         DEFAULT_HV_WINDOW)
    iv_rank_lookback = cfg.get('iv_rank_lookback',  DEFAULT_IV_RANK_LOOKBACK)
    profit_lock_pct  = cfg.get('profit_lock_pct',   DEFAULT_PROFIT_LOCK_PCT)

    df = fetch_ohlcv(asset, months)
    df = add_hv_and_iv_rank(df, hv_window=hv_window, iv_rank_lookback=iv_rank_lookback)

    cs = CONTRACT_SIZE[asset]
    balance = INITIAL_BALANCE
    peak_balance = INITIAL_BALANCE

    open_positions: list[dict] = []
    monthly_results: dict[str, dict] = {}
    all_trades: list[dict] = []

    def ym(d: date) -> str:
        return d.strftime('%Y-%m')

    for _, row in df.iterrows():
        today: date = row['date']
        price: float = row['close']
        hv: float    = row['hv30']
        iv_rank: float = row['iv_rank']

        if pd.isna(hv) or pd.isna(iv_rank):
            continue

        # ── 1. Cerrar posiciones expiradas o tocando stop / lock ──────────────
        still_open = []
        for pos in open_positions:
            T_rem = max(0, (pos['expiry_date'] - today).days) / 365
            current_put_usd = bs_put_price(price, pos['strike'], T_rem, hv / 100) * cs

            expired   = today >= pos['expiry_date']
            stop_hit  = current_put_usd >= pos['stop_usd']
            lock_hit  = current_put_usd <= pos['lock_usd'] and T_rem > 0

            if expired:
                if price < pos['strike']:
                    intrinsic = (pos['strike'] - price) * cs
                    pnl = pos['premium_usd'] - intrinsic
                    reason = 'ASSIGNED'
                else:
                    pnl = pos['premium_usd']
                    reason = 'EXPIRED'
            elif stop_hit:
                pnl = pos['premium_usd'] - current_put_usd
                reason = 'STOP_2X'
            elif lock_hit:
                pnl = pos['premium_usd'] - current_put_usd
                reason = 'PROFIT_LOCK'
            else:
                still_open.append(pos)
                continue

            balance += pnl
            peak_balance = max(peak_balance, balance)
            all_trades.append({
                'asset':       asset,
                'entry_date':  pos['entry_date'],
                'exit_date':   today,
                'strike':      pos['strike'],
                'entry_price': pos['entry_price'],
                'premium_usd': pos['premium_usd'],
                'margin_usd':  pos['margin_usd'],
                'pnl':         pnl,
                'reason':      reason,
                'iv_rank':     pos['iv_rank_entry'],
                'hv30':        hv,
            })
            month_key = ym(pos['entry_date'])
            if month_key not in monthly_results:
                monthly_results[month_key] = {'wins': 0, 'losses': 0, 'pnl': 0.0}
            if pnl > 0:
                monthly_results[month_key]['wins'] += 1
            else:
                monthly_results[month_key]['losses'] += 1
            monthly_results[month_key]['pnl'] += pnl

        open_positions = still_open

        # ── 2. Entrar nueva posición si IV Rank ≥ umbral y hay cupo ──────────
        margin_in_use = sum(p['margin_usd'] for p in open_positions)
        margin_avail  = balance - margin_in_use

        if (
            iv_rank >= min_iv_rank
            and len(open_positions) < max_open
            and margin_avail > balance * 0.05
        ):
            strike = price * (1 - otm_pct)
            T = dte / 365
            premium_usd = bs_put_price(price, strike, T, hv / 100) * cs
            if premium_usd < 2.0:
                continue
            margin_usd = max(0.10, 0.15 - otm_pct) * cs * price
            if margin_usd > margin_avail:
                continue

            expiry   = today + timedelta(days=dte)
            stop_usd = premium_usd * stop_mult
            lock_usd = premium_usd * (1 - profit_lock_pct)

            open_positions.append({
                'entry_date':    today,
                'expiry_date':   expiry,
                'strike':        strike,
                'entry_price':   price,
                'premium_usd':   premium_usd,
                'margin_usd':    margin_usd,
                'stop_usd':      stop_usd,
                'lock_usd':      lock_usd,
                'iv_rank_entry': iv_rank,
            })

    # ── 3. Cerrar todo al final ────────────────────────────────────────────────
    last_price = df['close'].iloc[-1]
    for pos in open_positions:
        if last_price < pos['strike']:
            intrinsic = (pos['strike'] - last_price) * cs
            pnl = pos['premium_usd'] - intrinsic
            reason = 'ASSIGNED'
        else:
            pnl = pos['premium_usd']
            reason = 'EXPIRED'
        balance += pnl
        all_trades.append({
            'asset':       asset,
            'entry_date':  pos['entry_date'],
            'exit_date':   df['date'].iloc[-1],
            'strike':      pos['strike'],
            'entry_price': pos['entry_price'],
            'premium_usd': pos['premium_usd'],
            'margin_usd':  pos['margin_usd'],
            'pnl':         pnl,
            'reason':      reason,
            'iv_rank':     pos['iv_rank_entry'],
            'hv30':        df['hv30'].iloc[-1],
        })
        month_key = ym(pos['entry_date'])
        if month_key not in monthly_results:
            monthly_results[month_key] = {'wins': 0, 'losses': 0, 'pnl': 0.0}
        if pnl > 0:
            monthly_results[month_key]['wins'] += 1
        else:
            monthly_results[month_key]['losses'] += 1
        monthly_results[month_key]['pnl'] += pnl

    # ── 4. Métricas ───────────────────────────────────────────────────────────
    trades_df = pd.DataFrame(all_trades)
    total_trades = len(trades_df)
    if total_trades == 0:
        return {
            'asset': asset, 'total_trades': 0, 'config': cfg,
            'win_rate': 0, 'profit_factor': 0,
            'total_pnl': 0, 'final_balance': balance,
            'max_dd_pct': 0, 'avg_pnl': 0,
            'monthly': monthly_results, 'trades': trades_df,
        }

    wins    = trades_df[trades_df['pnl'] > 0]
    losses  = trades_df[trades_df['pnl'] <= 0]
    gross_p = wins['pnl'].sum()
    gross_l = abs(losses['pnl'].sum())
    win_rate = len(wins) / total_trades * 100
    pf       = gross_p / gross_l if gross_l > 0 else float('inf')
    total_pnl = balance - INITIAL_BALANCE

    running_bal = INITIAL_BALANCE
    peak = INITIAL_BALANCE
    max_dd = 0.0
    for t in all_trades:
        running_bal += t['pnl']
        peak = max(peak, running_bal)
        dd = (peak - running_bal) / peak * 100
        max_dd = max(max_dd, dd)

    return {
        'asset':         asset,
        'config':        cfg,
        'total_trades':  total_trades,
        'win_rate':      win_rate,
        'profit_factor': pf,
        'total_pnl':     total_pnl,
        'final_balance': balance,
        'max_dd_pct':    max_dd,
        'avg_pnl':       trades_df['pnl'].mean(),
        'monthly':       monthly_results,
        'trades':        trades_df,
    }


# ── Sweep paramétrico ─────────────────────────────────────────────────────────

def run_sweep(assets: list[str], months: int = 24) -> list[dict]:
    """
    Corre todas las variantes de SWEEP_VARIANTS sobre cada activo.
    OHLCV se descarga una sola vez por activo gracias a la caché.
    Retorna lista de resultados ordenados por PF descendente.
    """
    # Pre-calentar caché
    for asset in assets:
        logger.info(f'Precargando datos {asset}...')
        fetch_ohlcv(asset, months)

    rows = []
    for variant in SWEEP_VARIANTS:
        name = variant['name']
        cfg  = {k: v for k, v in variant.items() if k != 'name'}
        for asset in assets:
            r = run_backtest(asset, config=cfg, months=months)
            rows.append({
                'variante':   name,
                'activo':     asset,
                'otm_pct':    variant['otm_pct'],
                'min_iv_rank': variant['min_iv_rank'],
                'stop_mult':  variant['stop_mult'],
                'max_open':   variant['max_open'],
                'trades':     r['total_trades'],
                'win_rate':   r['win_rate'],
                'pf':         r['profit_factor'],
                'pnl':        r['total_pnl'],
                'max_dd':     r['max_dd_pct'],
                '_result':    r,
            })
        logger.info(f'[{name}] completado')

    return rows


def print_sweep_report(rows: list[dict], assets: list[str]):
    """Imprime tabla comparativa del sweep."""
    # Por activo: ordenar por PF desc
    for asset in assets:
        asset_rows = [r for r in rows if r['activo'] == asset]
        asset_rows.sort(key=lambda x: x['pf'], reverse=True)
        print(f'\n{"="*78}')
        print(f'SWEEP — {asset}   (objetivo: PF≥1.10 AND MaxDD≤40%)')
        print(f'{"="*78}')
        print(f'  {"Variante":<20} {"OTM%":>5} {"IVmin":>6} {"Stop":>5} {"MaxP":>5} '
              f'{"Trades":>7} {"WR%":>6} {"PF":>6} {"PnL":>9} {"MaxDD%":>8}  {"OK?":>4}')
        print(f'  {"-"*76}')
        for r in asset_rows:
            ok = '✅' if r['pf'] >= 1.10 and r['max_dd'] <= 40.0 else '❌'
            pf_str = f'{r["pf"]:.2f}' if r["pf"] != float("inf") else ' inf'
            print(
                f'  {r["variante"]:<20} {r["otm_pct"]*100:>4.0f}% {r["min_iv_rank"]:>6.0f} '
                f'{r["stop_mult"]:>5.1f} {r["max_open"]:>5} '
                f'{r["trades"]:>7} {r["win_rate"]:>5.1f}% {pf_str:>6} '
                f'${r["pnl"]:>8.2f} {r["max_dd"]:>7.1f}%  {ok:>4}'
            )

    # Ganador combinado: mejor PF promedio BTC+ETH con PF≥1.10 y MaxDD≤40% en ambos
    print(f'\n{"="*78}')
    print('SELECCIÓN DE GANADOR (PF≥1.10 y MaxDD≤40% en todos los activos)')
    print(f'{"="*78}')

    variant_scores: dict[str, dict] = {}
    for r in rows:
        vname = r['variante']
        if vname not in variant_scores:
            variant_scores[vname] = {'pf_sum': 0.0, 'count': 0, 'all_ok': True, 'max_dd_max': 0.0}
        vs = variant_scores[vname]
        vs['pf_sum']    += r['pf'] if r['pf'] != float('inf') else 5.0
        vs['count']     += 1
        vs['max_dd_max'] = max(vs['max_dd_max'], r['max_dd'])
        if not (r['pf'] >= 1.10 and r['max_dd'] <= 40.0):
            vs['all_ok'] = False

    winners = [(v, s) for v, s in variant_scores.items() if s['all_ok']]
    if winners:
        best = max(winners, key=lambda x: x[1]['pf_sum'] / x[1]['count'])
        best_name, best_score = best
        best_variant = next(v for v in SWEEP_VARIANTS if v['name'] == best_name)
        avg_pf = best_score['pf_sum'] / best_score['count']
        print(f'\n  🏆 GANADOR: {best_name}')
        print(f'     PF promedio: {avg_pf:.2f}  |  MaxDD máx: {best_score["max_dd_max"]:.1f}%')
        print(f'     Parámetros:')
        print(f'       OTM_PCT          = {best_variant["otm_pct"]}')
        print(f'       MIN_IV_RANK      = {best_variant["min_iv_rank"]}')
        print(f'       STOP_LOSS_MULT   = {best_variant["stop_mult"]}')
        print(f'       MAX_OPEN_POSITIONS = {best_variant["max_open"]}')
        return best_variant
    else:
        print('\n  ⚠️  Ninguna variante cumple PF≥1.10 y MaxDD≤40% en todos los activos.')
        # Mostrar la mejor de todas de todas formas
        all_sorted = sorted(
            [(v, s) for v, s in variant_scores.items()],
            key=lambda x: x[1]['pf_sum'] / x[1]['count'],
            reverse=True,
        )
        best_name, best_score = all_sorted[0]
        best_variant = next(v for v in SWEEP_VARIANTS if v['name'] == best_name)
        avg_pf = best_score['pf_sum'] / best_score['count']
        print(f'  Mejor disponible: {best_name}  (PF promedio={avg_pf:.2f}, MaxDD={best_score["max_dd_max"]:.1f}%)')
        return best_variant


# ── Impresión de reporte (single run) ────────────────────────────────────────

def print_report(results: list[dict]):
    cfg = results[0]['config'] if results else {}
    otm  = cfg.get('otm_pct', DEFAULT_OTM_PCT)
    dte  = cfg.get('dte', DEFAULT_DTE)
    ivmin = cfg.get('min_iv_rank', DEFAULT_MIN_IV_RANK)
    print('\n' + '=' * 70)
    print('BACKTEST OPTIONS THETA FARMING — 24 MESES')
    print(f'Estrategia: vender PUTs {otm*100:.0f}% OTM, DTE={dte}, min IV Rank={ivmin}%')
    print('=' * 70)

    for r in results:
        asset = r['asset']
        print(f'\n── {asset} ──────────────────────────────────────────────────────')
        print(f'  Trades totales : {r["total_trades"]}')
        print(f'  Win Rate       : {r["win_rate"]:.1f}%')
        print(f'  Profit Factor  : {r["profit_factor"]:.2f}')
        print(f'  PnL total      : ${r["total_pnl"]:+.2f}')
        print(f'  Balance final  : ${r["final_balance"]:.2f}')
        print(f'  Max Drawdown   : {r["max_dd_pct"]:.1f}%')
        print(f'  PnL promedio/t : ${r["avg_pnl"]:.2f}')

        if len(r['trades']) > 0:
            rc = r['trades']['reason'].value_counts()
            print('  Cierres:')
            for reason, cnt in rc.items():
                print(f'    {reason:15s}: {cnt}')

        print(f'\n  {"Mes":<10} {"Trades":>7} {"WR%":>7} {"PnL USD":>10}')
        print(f'  {"-"*38}')
        for month in sorted(r['monthly'].keys()):
            m = r['monthly'][month]
            total_m = m['wins'] + m['losses']
            wr_m    = m['wins'] / total_m * 100 if total_m else 0
            print(f'  {month:<10} {total_m:>7} {wr_m:>6.1f}% {m["pnl"]:>10.2f}')

    if len(results) > 1:
        print('\n' + '=' * 70)
        print('COMPARATIVA')
        print(f'  {"Activo":<6} {"Trades":>7} {"WR%":>7} {"PF":>7} {"PnL":>10} {"MaxDD%":>8}')
        print(f'  {"-"*45}')
        for r in results:
            print(
                f'  {r["asset"]:<6} {r["total_trades"]:>7} '
                f'{r["win_rate"]:>6.1f}% {r["profit_factor"]:>7.2f} '
                f'${r["total_pnl"]:>9.2f} {r["max_dd_pct"]:>7.1f}%'
            )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Backtest Options Theta Farming')
    parser.add_argument(
        '--asset', default='BTC,ETH',
        help='Activo(s) separados por coma: BTC, ETH, BTC,ETH (default: BTC,ETH)',
    )
    parser.add_argument('--months', type=int, default=24, help='Meses de historia (default: 24)')
    parser.add_argument(
        '--sweep', action='store_true',
        help='Correr sweep de 5 variantes de parámetros y mostrar tabla comparativa',
    )
    args = parser.parse_args()

    assets = [a.strip().upper() for a in args.asset.split(',')]
    for a in assets:
        if a not in SYMBOL_MAP:
            print(f'Activo no soportado: {a}. Usa: {list(SYMBOL_MAP.keys())}')
            sys.exit(1)

    if args.sweep:
        logger.info(f'SWEEP PARAMÉTRICO — {len(SWEEP_VARIANTS)} variantes × {len(assets)} activos')
        rows = run_sweep(assets, months=args.months)
        winner = print_sweep_report(rows, assets)

        # Guardar CSV del sweep
        sweep_df = pd.DataFrame([
            {k: v for k, v in r.items() if k != '_result'} for r in rows
        ])
        out_path = '/opt/trading/reports/bt_options_sweep.csv'
        sweep_df.to_csv(out_path, index=False)
        print(f'\nCSV guardado: {out_path}')
        return winner
    else:
        results = []
        for asset in assets:
            logger.info(f'Backtesting {asset} ({args.months} meses)...')
            r = run_backtest(asset, months=args.months)
            results.append(r)

        print_report(results)

        all_trades_df = pd.concat([r['trades'] for r in results if len(r['trades']) > 0], ignore_index=True)
        if len(all_trades_df) > 0:
            out_path = '/opt/trading/reports/bt_options_24m.csv'
            all_trades_df.to_csv(out_path, index=False)
            print(f'\nCSV guardado: {out_path}')


if __name__ == '__main__':
    main()

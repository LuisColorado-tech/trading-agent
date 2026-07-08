#!/usr/bin/env python3
"""
backtest_polymarket.py — Análisis histórico del Polymarket Agent.

Lee el historial real de poly_positions (CLOSED) desde PostgreSQL y calcula
métricas por estrategia, por close_reason, por precio de entrada, y la
distribución de R:R para diagnosticar el problema de PnL negativo.

Uso:
  python3 scripts/backtest_polymarket.py
  python3 scripts/backtest_polymarket.py --session POLY_SESSION_003
  python3 scripts/backtest_polymarket.py --all-sessions
  python3 scripts/backtest_polymarket.py --csv reports/bt_poly.csv
  python3 scripts/backtest_polymarket.py --simulate-sl 0.30 --simulate-tp 0.80

Modo simulación (--simulate-sl / --simulate-tp):
  Re-aplica SL/TP distintos a los trades históricos para evaluar qué
  combinación habría dado mejor resultado. No cambia la DB.
"""
import argparse
import os
import sys
from datetime import datetime, timezone

import pandas as pd
import numpy as np

sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')

from sqlalchemy import create_engine, text


# ── Conexión DB ───────────────────────────────────────────────────────────────

def _db_url() -> str:
    return (
        f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
        f"@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}"
        f"/{os.getenv('POSTGRES_DB')}"
    )


def load_trades(session_name: str | None = None, all_sessions: bool = False) -> pd.DataFrame:
    """Carga poly_positions CLOSED desde DB."""
    engine = create_engine(_db_url())
    with engine.connect() as conn:
        # Sesiones disponibles
        sessions_q = conn.execute(text(
            "SELECT session_name, status, initial_balance, current_balance, total_pnl, started_at "
            "FROM poly_sessions ORDER BY started_at DESC LIMIT 20"
        )).fetchall()

        if sessions_q:
            print("\n=== SESIONES POLYMARKET ===")
            for s in sessions_q:
                pnl = s.total_pnl or 0
                print(f"  {s.session_name} | {s.status} | inicial=${s.initial_balance:.0f} "
                      f"| pnl=${pnl:+.2f} | desde {str(s.started_at)[:10]}")

        # Filtro de sesión
        if session_name:
            where = "WHERE p.status = 'CLOSED' AND p.session_name = :sess"
            params = {'sess': session_name}
        elif all_sessions:
            where = "WHERE p.status = 'CLOSED'"
            params = {}
        else:
            # Por defecto: sesión más reciente
            last = conn.execute(text(
                "SELECT session_name FROM poly_sessions ORDER BY started_at DESC LIMIT 1"
            )).fetchone()
            if not last:
                print("⚠ No hay sesiones poly en DB.")
                return pd.DataFrame()
            where = "WHERE p.status = 'CLOSED' AND p.session_name = :sess"
            params = {'sess': last.session_name}
            print(f"\nUsando sesión más reciente: {last.session_name}")

        rows = conn.execute(text(f"""
            SELECT
                p.id,
                p.condition_id,
                p.question,
                p.side,
                p.strategy,
                p.strategy_tag,
                p.entry_price,
                p.exit_price,
                p.shares,
                p.cost_basis,
                p.pnl,
                p.pnl_pct,
                p.close_reason,
                p.session_name,
                p.paper_trade,
                p.timestamp_open,
                p.timestamp_close,
                p.metadata
            FROM poly_positions p
            {where}
            ORDER BY p.timestamp_close ASC
        """), params).fetchall()

    if not rows:
        print("⚠ Sin trades cerrados en DB.")
        return pd.DataFrame()

    df = pd.DataFrame([dict(r._mapping) for r in rows])
    df['entry_price'] = pd.to_numeric(df['entry_price'], errors='coerce')
    df['exit_price']  = pd.to_numeric(df['exit_price'],  errors='coerce')
    df['pnl']         = pd.to_numeric(df['pnl'],         errors='coerce').fillna(0)
    df['pnl_pct']     = pd.to_numeric(df['pnl_pct'],     errors='coerce').fillna(0)
    df['cost_basis']  = pd.to_numeric(df['cost_basis'],  errors='coerce').fillna(0)
    df['shares']      = pd.to_numeric(df['shares'],      errors='coerce').fillna(0)
    df['timestamp_close'] = pd.to_datetime(df['timestamp_close'], utc=True, errors='coerce')
    df['timestamp_open']  = pd.to_datetime(df['timestamp_open'],  utc=True, errors='coerce')
    df['duration_hours'] = (
        (df['timestamp_close'] - df['timestamp_open']).dt.total_seconds() / 3600
    ).round(1)

    print(f"\n→ {len(df)} trades cerrados cargados.")
    return df


# ── Métricas ──────────────────────────────────────────────────────────────────

def compute_metrics(df: pd.DataFrame, initial_balance: float = 1000.0) -> dict:
    """Calcula métricas globales sobre un DataFrame de trades."""
    if df.empty:
        return {'error': 'sin trades'}

    wins   = df[df['pnl'] > 0]
    losses = df[df['pnl'] <= 0]
    total  = len(df)

    win_rate   = len(wins) / total * 100 if total else 0
    avg_win    = wins['pnl'].mean()   if len(wins)   else 0.0
    avg_loss   = losses['pnl'].mean() if len(losses) else 0.0
    ev_trade   = df['pnl'].mean()

    gross_wins  = wins['pnl'].sum()
    gross_loss  = abs(losses['pnl'].sum())
    pf = gross_wins / gross_loss if gross_loss > 0 else float('inf')

    total_pnl = df['pnl'].sum()
    rr_actual = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    # Sharpe mensual aproximado
    if 'timestamp_close' in df.columns and not df['timestamp_close'].isna().all():
        monthly = df.set_index('timestamp_close')['pnl'].resample('1ME').sum()
        sharpe = (monthly.mean() / monthly.std()) if monthly.std() > 0 else 0
    else:
        sharpe = 0.0

    # Racha pérdidas consecutivas
    max_streak = cur = 0
    pnl_series = df['pnl'] if 'timestamp_close' not in df.columns else df.sort_values('timestamp_close')['pnl']
    for p in pnl_series:
        cur = cur + 1 if p <= 0 else 0
        max_streak = max(max_streak, cur)

    return {
        'total_trades':    total,
        'win_rate_pct':    win_rate,
        'avg_win':         avg_win,
        'avg_loss':        avg_loss,
        'ev_trade':        ev_trade,
        'profit_factor':   pf,
        'total_pnl':       total_pnl,
        'return_pct':      total_pnl / initial_balance * 100,
        'rr_actual':       rr_actual,
        'sharpe_monthly':  sharpe,
        'max_loss_streak': max_streak,
    }


# ── Reporte por sección ───────────────────────────────────────────────────────

def report_global(df: pd.DataFrame, initial: float = 1000.0):
    m = compute_metrics(df, initial)
    if 'error' in m:
        print(f"  ⚠ {m['error']}")
        return

    verdict = "✅ EV POSITIVO" if m['ev_trade'] > 0 else "❌ EV NEGATIVO"
    print(f"\n{'='*60}")
    print(f"  RESUMEN GLOBAL — {m['total_trades']} trades")
    print(f"{'='*60}")
    print(f"  {verdict}")
    print(f"  Win rate:         {m['win_rate_pct']:.1f}%")
    print(f"  EV por trade:     ${m['ev_trade']:+.3f}")
    print(f"  Avg ganancia:     ${m['avg_win']:+.3f}")
    print(f"  Avg pérdida:      ${m['avg_loss']:+.3f}")
    print(f"  R:R real:         {m['rr_actual']:.2f}x")
    print(f"  Profit factor:    {m['profit_factor']:.2f}")
    print(f"  PnL total:        ${m['total_pnl']:+.2f}  ({m['return_pct']:+.1f}%)")
    print(f"  Sharpe mensual:   {m['sharpe_monthly']:.2f}")
    print(f"  Racha pérdidas:   {m['max_loss_streak']} seguidas")


def report_by_strategy(df: pd.DataFrame):
    print(f"\n{'='*60}")
    print(f"  POR ESTRATEGIA")
    print(f"{'='*60}")
    tag_col = 'strategy_tag' if 'strategy_tag' in df.columns else 'strategy'
    grouped = df.groupby(tag_col)

    rows = []
    for tag, g in grouped:
        wins = (g['pnl'] > 0).sum()
        wr   = wins / len(g) * 100
        ev   = g['pnl'].mean()
        pnl  = g['pnl'].sum()
        gross_w = g[g['pnl'] > 0]['pnl'].sum()
        gross_l = abs(g[g['pnl'] <= 0]['pnl'].sum())
        pf = gross_w / gross_l if gross_l > 0 else float('inf')
        rows.append((tag, len(g), wins, wr, ev, pnl, pf))

    rows.sort(key=lambda x: x[5], reverse=True)
    for tag, n, wins, wr, ev, pnl, pf in rows:
        verdict = "✅" if ev > 0 else "❌"
        print(f"  {verdict} {tag:<30} | {n:>4} trades | WR={wr:.0f}% | "
              f"EV=${ev:+.3f} | PnL=${pnl:+.2f} | PF={pf:.2f}")


def report_by_close_reason(df: pd.DataFrame):
    print(f"\n{'='*60}")
    print(f"  POR CLOSE REASON")
    print(f"{'='*60}")
    for reason, g in df.groupby('close_reason'):
        pnl = g['pnl'].sum()
        avg = g['pnl'].mean()
        n   = len(g)
        print(f"  {reason:<25} | {n:>4} trades | avg=${avg:+.3f} | total=${pnl:+.2f}")


def report_by_entry_price_bucket(df: pd.DataFrame):
    """Distribución de resultados por rango de precio de entrada."""
    print(f"\n{'='*60}")
    print(f"  POR PRECIO DE ENTRADA (BUCKETS)")
    print(f"{'='*60}")
    df = df.copy()
    bins   = [0, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 1.01]
    labels = ['<0.20','0.20-0.29','0.30-0.39','0.40-0.49',
              '0.50-0.59','0.60-0.69','0.70-0.79','≥0.80']
    df['price_bucket'] = pd.cut(df['entry_price'], bins=bins, labels=labels, right=False)
    for bucket, g in df.groupby('price_bucket', observed=True):
        if len(g) == 0:
            continue
        wr  = (g['pnl'] > 0).mean() * 100
        ev  = g['pnl'].mean()
        pnl = g['pnl'].sum()
        n   = len(g)
        verdict = "✅" if ev > 0 else "❌"
        print(f"  {verdict} entry={bucket:<12} | {n:>3} trades | WR={wr:.0f}% | EV=${ev:+.3f} | total=${pnl:+.2f}")


def report_rratio_distribution(df: pd.DataFrame):
    """Muestra el R:R real implícito por cuantiles."""
    print(f"\n{'='*60}")
    print(f"  DISTRIBUCIÓN PnL POR TRADE")
    print(f"{'='*60}")
    pnl = df['pnl'].sort_values()
    quantiles = [0.10, 0.25, 0.50, 0.75, 0.90]
    for q in quantiles:
        print(f"  P{int(q*100):>3}: ${pnl.quantile(q):+.3f}")
    print(f"  Min: ${pnl.min():+.3f}  Max: ${pnl.max():+.3f}")
    print(f"\n  Trades con PnL > +$1.00: {(pnl > 1.0).sum()}")
    print(f"  Trades con PnL < -$1.00: {(pnl < -1.0).sum()}")
    print(f"  Trades con PnL en [-$0.50, +$0.50]: {((pnl >= -0.5) & (pnl <= 0.5)).sum()} (ruidosos)")


def report_monthly_pnl(df: pd.DataFrame):
    """PnL mensual acumulado."""
    if 'timestamp_close' not in df.columns or df['timestamp_close'].isna().all():
        return
    print(f"\n{'='*60}")
    print(f"  PnL MENSUAL")
    print(f"{'='*60}")
    monthly = df.set_index('timestamp_close')['pnl'].resample('1ME').agg(['sum', 'count'])
    for dt, row in monthly.iterrows():
        verdict = "✅" if row['sum'] > 0 else "❌"
        print(f"  {verdict} {str(dt)[:7]} | {int(row['count']):>3} trades | ${row['sum']:+.2f}")


# ── Simulación de SL/TP alternativos ─────────────────────────────────────────

def simulate_sl_tp(df: pd.DataFrame, sl_factor: float, tp_price: float,
                   initial: float = 1000.0) -> dict:
    """
    Re-simula el resultado de los trades históricos con SL/TP distintos.

    Lógica:
      - SL dinámico: si el precio de salida real fue < entry_price * sl_factor,
        asumimos que el nuevo SL lo habría cortado antes → pnl_sim = -cost * (1 - sl_factor)
      - TP dinámico: si el precio de salida real fue ≥ tp_price y el close reason
        fue RESOLVED_WIN, dejamos pnl sin cambio (capturado igual).
        Si TAKE_PROFIT (salida anticipada), el pnl es el mismo o mejor con trailing.
      - RESOLVED_WIN / RESOLVED_LOSS no cambian — son resoluciones binarias.

    Limitación: es una aproximación conservadora. En realidad el nuevo SL
    habría cortado pérdidas en posiciones que se resolvieron a 0 (RESOLVED_LOSS).
    """
    sim_records = []
    for _, row in df.iterrows():
        entry  = float(row['entry_price'])
        cost   = float(row['cost_basis'])
        shares = float(row['shares'])
        reason = str(row.get('close_reason', ''))

        # Resoluciones binarias (YES/NO) — el SL/TP no aplica
        if reason in ('RESOLVED_WIN', 'RESOLVED_LOSS'):
            sim_records.append({'pnl': float(row['pnl']), 'close_reason': reason + '_SIM'})
            continue

        exit_price = float(row.get('exit_price') or 0.0)

        # Nuevo SL: cortar si el precio cae por debajo de entry * (1 - loss_frac)
        # sl_factor=0.40 → SL cuando precio = entry * (1 - 0.40) = entry * 0.60
        # es decir, se pierde el 40% del capital invertido
        sl_price = entry * (1.0 - sl_factor)

        # Si el exit real fue peor que el nuevo SL → aplicar el nuevo SL
        if exit_price < sl_price and reason in ('STOP_LOSS', 'EXPIRED_UNKNOWN'):
            pnl_sim = -cost * sl_factor  # pérdida controlada
            sim_records.append({'pnl': pnl_sim, 'close_reason': 'STOP_LOSS_SIM'})
            continue

        # Nuevo TP: salir anticipado si llegamos a tp_price
        if exit_price >= tp_price or reason == 'TAKE_PROFIT':
            pnl_sim = shares * tp_price - cost
            sim_records.append({'pnl': pnl_sim, 'close_reason': 'TAKE_PROFIT_SIM'})
            continue

        # Resto: mantener pnl original
        sim_records.append({'pnl': float(row['pnl']), 'close_reason': reason + '_SIM'})

    sim_df = pd.DataFrame(sim_records)
    return compute_metrics(sim_df, initial)


def print_simulation(m: dict, sl_factor: float, tp_price: float):
    if 'error' in m:
        print(f"  ⚠ {m['error']}")
        return
    verdict = "✅ MEJOR" if m['ev_trade'] > 0 else "❌ PEOR"
    print(f"\n  SL={sl_factor*100:.0f}% loss / TP={tp_price:.2f} → {verdict}")
    print(f"  EV/trade: ${m['ev_trade']:+.3f}  |  WR: {m['win_rate_pct']:.1f}%  |  "
          f"R:R: {m['rr_actual']:.2f}x  |  PnL: ${m['total_pnl']:+.2f}")


# ── Escáner de combinaciones SL/TP ───────────────────────────────────────────

def scan_sl_tp_combinations(df: pd.DataFrame, initial: float = 1000.0):
    """Prueba grillas de SL y TP para encontrar la combinación óptima."""
    print(f"\n{'='*60}")
    print(f"  SCAN SL/TP — buscando combinación óptima")
    print(f"{'='*60}")
    sl_factors = [0.20, 0.30, 0.40, 0.50, 0.60]   # pérdida máx % del capital
    tp_prices  = [0.70, 0.75, 0.80, 0.85, 0.90]   # precio YES target

    best_ev    = -999
    best_combo = (0, 0)
    results    = []

    for sl in sl_factors:
        for tp in tp_prices:
            m = simulate_sl_tp(df, sl, tp, initial)
            ev = m.get('ev_trade', -999)
            pnl = m.get('total_pnl', 0)
            wr  = m.get('win_rate_pct', 0)
            rr  = m.get('rr_actual', 0)
            results.append((sl, tp, ev, pnl, wr, rr))
            if ev > best_ev:
                best_ev    = ev
                best_combo = (sl, tp)

    # Imprimir tabla
    header = f"  {'SL%':<6} {'TP':<6} {'EV/trade':>10} {'PnL':>8} {'WR%':>6} {'R:R':>5}"
    print(header)
    print(f"  {'-'*45}")
    results.sort(key=lambda x: x[2], reverse=True)
    for sl, tp, ev, pnl, wr, rr in results:
        flag = " ◄ MEJOR" if (sl, tp) == best_combo else ""
        print(f"  SL={sl*100:.0f}%  TP={tp:.2f}  {ev:>+10.3f}  {pnl:>+8.2f}  {wr:>5.1f}%  {rr:>4.2f}x{flag}")

    print(f"\n  → Mejor combinación: SL={best_combo[0]*100:.0f}% pérdida / TP={best_combo[1]:.2f}")
    print(f"    EV/trade: ${best_ev:+.3f}")
    return best_combo


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Backtest histórico del Polymarket Agent desde DB'
    )
    parser.add_argument('--session',         default='',    help='Nombre de sesión específica')
    parser.add_argument('--all-sessions',    action='store_true', help='Todas las sesiones')
    parser.add_argument('--csv',             default='',    help='Exportar trades a CSV')
    parser.add_argument('--simulate-sl',     type=float, default=0.0,
                        help='Factor de pérdida máx para SL dinámico (ej: 0.40 = 40%%)')
    parser.add_argument('--simulate-tp',     type=float, default=0.0,
                        help='Precio YES para TP dinámico (ej: 0.80)')
    parser.add_argument('--scan-combos',     action='store_true',
                        help='Escanea grilla de SL/TP para encontrar combinación óptima')
    args = parser.parse_args()

    # 1. Cargar datos
    df = load_trades(
        session_name=args.session or None,
        all_sessions=args.all_sessions,
    )
    if df.empty:
        print("Sin datos para analizar.")
        return

    initial_balance = 1000.0

    # 2. Reporte global
    report_global(df, initial_balance)

    # 3. Por estrategia
    report_by_strategy(df)

    # 4. Por close reason
    report_by_close_reason(df)

    # 5. Por precio de entrada
    report_by_entry_price_bucket(df)

    # 6. Distribución PnL
    report_rratio_distribution(df)

    # 7. PnL mensual
    report_monthly_pnl(df)

    # 8. Scan de combinaciones SL/TP
    if args.scan_combos:
        best_combo = scan_sl_tp_combinations(df, initial_balance)
    elif args.simulate_sl > 0 and args.simulate_tp > 0:
        print(f"\n{'='*60}")
        print(f"  SIMULACIÓN SL/TP ALTERNATIVO")
        print(f"{'='*60}")
        print(f"  Original (baseline):")
        m_orig = compute_metrics(df, initial_balance)
        print(f"  EV/trade: ${m_orig['ev_trade']:+.3f}  WR: {m_orig['win_rate_pct']:.1f}%  "
              f"R:R: {m_orig['rr_actual']:.2f}x  PnL: ${m_orig['total_pnl']:+.2f}")
        print(f"\n  Simulado:")
        m_sim = simulate_sl_tp(df, args.simulate_sl, args.simulate_tp, initial_balance)
        print_simulation(m_sim, args.simulate_sl, args.simulate_tp)

    # 9. Exportar CSV
    if args.csv:
        df.to_csv(args.csv, index=False)
        print(f"\n  📄 Trades exportados a: {args.csv}")

    # 10. Recomendaciones automáticas
    print(f"\n{'='*60}")
    print(f"  DIAGNÓSTICO AUTOMÁTICO")
    print(f"{'='*60}")
    m = compute_metrics(df, initial_balance)
    if 'error' in m:
        return

    wr   = m['win_rate_pct']
    rr   = m['rr_actual']
    ev   = m['ev_trade']
    pf   = m['profit_factor']

    # Diagnóstico R:R
    if wr >= 50 and rr < 1.0:
        print(f"  ⚠ WIN RATE OK ({wr:.0f}%) pero R:R bajo ({rr:.2f}x) — SL demasiado amplio o TP demasiado conservador")
        print(f"    → Ajustar SL dinámico y subir TP trail. Ejecutar --scan-combos para calibrar.")
    elif wr < 45 and rr >= 1.5:
        print(f"  ⚠ R:R bueno ({rr:.2f}x) pero WR bajo ({wr:.0f}%) — señales de baja calidad")
        print(f"    → Subir min_edge_pct o añadir filtros de calidad de mercado.")
    elif ev > 0:
        print(f"  ✅ EV positivo (${ev:+.3f}/trade) — sistema profitable. Escalar kelly_fraction.")
    else:
        print(f"  ❌ EV negativo (${ev:+.3f}/trade) — sistema pierde dinero.")

    # Diagnóstico por estrategia
    tag_col = 'strategy_tag' if 'strategy_tag' in df.columns else 'strategy'
    for tag, g in df.groupby(tag_col):
        ev_tag = g['pnl'].mean()
        n = len(g)
        if ev_tag < -0.50 and n >= 5:
            print(f"  ❌ Estrategia '{tag}' destruye valor (EV=${ev_tag:+.3f}, {n} trades) → considerar desactivar")
        elif ev_tag > 0.50 and n >= 5:
            print(f"  ✅ Estrategia '{tag}' genera valor (EV=${ev_tag:+.3f}, {n} trades) → aumentar kelly_fraction")

    # Diagnóstico por close reason
    for reason, g in df.groupby('close_reason'):
        avg = g['pnl'].mean()
        n   = len(g)
        if reason == 'STOP_LOSS' and avg < -1.0:
            print(f"  ⚠ STOP_LOSS promedio muy negativo (${avg:+.2f}) con {n} trades → SL demasiado amplio")
        if reason == 'EXPIRED_UNKNOWN' and n > 3:
            print(f"  ⚠ {n} cierres EXPIRED_UNKNOWN → mejorar manejo de expiración o reducir max_end_days")

    print(f"{'='*60}")


if __name__ == '__main__':
    main()

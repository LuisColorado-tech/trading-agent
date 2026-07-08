#!/usr/bin/env python3
"""
backtest_value_zone.py — Valida la estrategia Value Zone contra datos históricos.

Simula la lógica de poly_value_zone.py sobre trades cerrados de Polymarket:
  - Filtra mercados direccionales en zona $0.42-$0.58
  - Simula TP a $0.85 y SL a -25% del capital
  - Calcula métricas: WR, EV, PnL, Sharpe

Uso:
  python3 scripts/backtest_value_zone.py
  python3 scripts/backtest_value_zone.py --session POLY_SESSION_005
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


def _db_url() -> str:
    return (
        f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
        f"@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}"
        f"/{os.getenv('POSTGRES_DB')}"
    )


# ── Filtros Value Zone ─────────────────────────────────────────────────────────

TP_PRICE   = 0.85
SL_FRACTION = 0.25
MIN_PRICE  = 0.42
MAX_PRICE  = 0.58
MIN_VOLUME = 30000
MIN_LIQUIDITY = 5000
MIN_DAYS   = 1
MAX_DAYS   = 7

import re

_DIRECTIONAL_PATTERNS = [
    r'\b(above|over|reach|hit|break|cross|exceed|surpass|top)\b',
    r'\b(below|under|dip|drop|fall|crash)\b',
]
_EXCLUDE_PATTERNS = [
    r'\bbetween\b',
    r'\bin\s+the\s+range\b',
]


def is_directional(question: str) -> bool:
    q = question.lower()
    for pat in _EXCLUDE_PATTERNS:
        if re.search(pat, q):
            return False
    if q.count(' and ') >= 1:
        return False
    return any(re.search(p, q) for p in _DIRECTIONAL_PATTERNS)


def load_trades(session_name: str | None = None) -> pd.DataFrame:
    """Carga todos los trades cerrados con datos de mercado."""
    engine = create_engine(_db_url())
    with engine.connect() as conn:
        if session_name:
            where = "WHERE p.status = 'CLOSED' AND p.session_name = :sess"
            params = {'sess': session_name}
        else:
            where = "WHERE p.status = 'CLOSED'"
            params = {}

        rows = conn.execute(text(f"""
            SELECT
                p.id,
                p.question,
                p.side,
                p.entry_price,
                p.exit_price,
                p.pnl,
                p.pnl_pct,
                p.cost_basis,
                p.shares,
                p.close_reason,
                p.strategy,
                p.timestamp_close
            FROM poly_positions p
            {where}
            ORDER BY p.timestamp_close DESC
        """), params).fetchall()

    df = pd.DataFrame([dict(r._mapping) for r in rows])
    for col in ['entry_price', 'exit_price', 'pnl', 'cost_basis', 'shares']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    df['pnl'] = df['pnl'].fillna(0)
    df['cost_basis'] = df['cost_basis'].fillna(0)
    df['shares'] = df['shares'].fillna(0)

    return df


def filter_value_zone(df: pd.DataFrame) -> pd.DataFrame:
    """Aplica los filtros de Value Zone al dataset histórico."""
    mask = (
        (df['entry_price'] >= MIN_PRICE) &
        (df['entry_price'] <= MAX_PRICE) &
        (df['side'] == 'YES')
    )
    df_vz = df[mask].copy()

    # Filtro direccional
    df_vz['directional'] = df_vz['question'].apply(is_directional)
    df_vz = df_vz[df_vz['directional']]

    return df_vz


def simulate_value_zone(df: pd.DataFrame) -> pd.DataFrame:
    """Simula qué habría pasado con TP=0.85 y SL=-25%."""
    results = []

    for _, row in df.iterrows():
        entry  = float(row['entry_price'])
        cost   = float(row['cost_basis'])
        shares = float(row['shares'])

        # SL dinámico: vender si precio cae a entry * (1 - SL_FRACTION)
        sl_price = entry * (1.0 - SL_FRACTION)

        # ¿Llegó al TP?
        # En backtest no tenemos el path de precios, solo entry y exit.
        # Usamos close_reason como proxy:
        #   TAKE_PROFIT → asumimos que llegó a TP
        #   STOP_LOSS   → asumimos que llegó a SL
        #   RESOLVED_*  → mantiene pnl real (resolución binaria)
        reason = str(row.get('close_reason', ''))

        if reason == 'TAKE_PROFIT':
            # Llegó a TP → profit = shares * TP - cost
            sim_pnl = shares * TP_PRICE - cost
            sim_close = 'TP_SIM'
        elif reason == 'STOP_LOSS':
            # Llegó a SL → pérdida = cost * SL_FRACTION
            sim_pnl = -cost * SL_FRACTION
            sim_close = 'SL_SIM'
        elif reason in ('RESOLVED_WIN',):
            # Resolución binaria WIN → pnl real (ya es el peor caso)
            sim_pnl = float(row['pnl'])
            sim_close = 'RESOLVED_WIN'
        elif reason in ('RESOLVED_LOSS',):
            # Resolución binaria LOSS → pnl real (catastrófico)
            sim_pnl = float(row['pnl'])
            sim_close = 'RESOLVED_LOSS'
        elif reason == 'SESSION_RESET':
            sim_pnl = 0.0
            sim_close = 'SESSION_RESET'
        else:
            sim_pnl = float(row['pnl'])
            sim_close = reason

        results.append({
            'question':     row['question'],
            'entry_price':  entry,
            'cost_basis':   cost,
            'shares':       shares,
            'real_pnl':     float(row['pnl']),
            'real_reason':  reason,
            'sim_pnl':      sim_pnl,
            'sim_reason':   sim_close,
        })

    return pd.DataFrame(results)


def compute_metrics(sim_df: pd.DataFrame, capital: float = 1000.0) -> dict:
    """Calcula métricas del backtest simulado."""
    if sim_df.empty:
        return {'error': 'sin trades'}

    n    = len(sim_df)
    wins = sim_df[sim_df['sim_pnl'] > 0]
    loss = sim_df[sim_df['sim_pnl'] <= 0]
    wr   = len(wins) / n * 100 if n else 0
    avg_w  = wins['sim_pnl'].mean() if len(wins) else 0
    avg_l  = loss['sim_pnl'].mean() if len(loss) else 0
    ev   = sim_df['sim_pnl'].mean()
    total_pnl = sim_df['sim_pnl'].sum()
    gross_w = wins['sim_pnl'].sum()
    gross_l = abs(loss['sim_pnl'].sum())
    pf = gross_w / gross_l if gross_l > 0 else float('inf')
    rr = abs(avg_w / avg_l) if avg_l != 0 else 0

    return {
        'total_trades': n,
        'win_rate': wr,
        'avg_win': avg_w,
        'avg_loss': avg_l,
        'ev': ev,
        'total_pnl': total_pnl,
        'return_pct': total_pnl / capital * 100,
        'profit_factor': pf,
        'rr': rr,
    }


def report(sim_df: pd.DataFrame, label: str = ''):
    """Imprime reporte formateado."""
    m = compute_metrics(sim_df)
    if 'error' in m:
        print(f'  ⚠ {m["error"]}')
        return

    verdict = '✅ VIABLE' if m['ev'] > 0 else '❌ NO VIABLE'
    print(f"\n{'='*60}")
    print(f"  VALUE ZONE BACKTEST {label}")
    print(f"{'='*60}")
    print(f"  {verdict}")
    print(f"  Trades simulados:  {m['total_trades']}")
    print(f"  Win Rate:          {m['win_rate']:.1f}%")
    print(f"  EV por trade:      ${m['ev']:+.2f}")
    print(f"  Avg win:           ${m['avg_win']:+.2f}")
    print(f"  Avg loss:          ${m['avg_loss']:+.2f}")
    print(f"  R:R real:          {m['rr']:.2f}x")
    print(f"  Profit Factor:     {m['profit_factor']:.2f}")
    print(f"  PnL Total:         ${m['total_pnl']:+.2f}")
    print(f"  Return s/capital:  {m['return_pct']:+.1f}%")

    # Proyección mensual
    if m['ev'] > 0:
        monthly_est = m['ev'] * 15  # ~15 trades/mes en esta zona
        monthly_return = monthly_est / 1000 * 100
        print(f"\n  📊 Proyección mensual (~15 trades):")
        print(f"     PnL estimado:    ${monthly_est:+.2f}")
        print(f"     Retorno mensual:  {monthly_return:+.1f}%")
        if monthly_return >= 0.3:
            print(f"     🎯 OBJETIVO 0.3%:  CUMPLIDO ({monthly_return:.1f}% ≥ 0.3%)")
        else:
            print(f"     ⚠ OBJETIVO 0.3%:  NO CUMPLIDO ({monthly_return:.1f}% < 0.3%)")

    # Breakdown por close reason simulado
    print(f"\n  ── Por close reason simulado ──")
    for reason, g in sim_df.groupby('sim_reason'):
        avg = g['sim_pnl'].mean()
        tot = g['sim_pnl'].sum()
        n   = len(g)
        print(f"  {reason:<20} | {n:>3} trades | avg=${avg:+.2f} | total=${tot:+.2f}")

    # Comparación con realidad
    real_total = sim_df['real_pnl'].sum()
    sim_total  = sim_df['sim_pnl'].sum()
    improvement = sim_total - real_total
    print(f"\n  ── Comparación vs realidad ──")
    print(f"  PnL real (histórico):    ${real_total:+.2f}")
    print(f"  PnL simulado (VZ+TP/SL): ${sim_total:+.2f}")
    print(f"  Mejora:                  ${improvement:+.2f}")

    return m


def main():
    parser = argparse.ArgumentParser(description='Backtest Value Zone strategy')
    parser.add_argument('--session', default='', help='Sesión específica')
    args = parser.parse_args()

    # 1. Cargar trades
    df = load_trades(args.session or None)
    print(f"→ {len(df)} trades totales cargados")

    # 2. Filtrar zona value
    df_vz = filter_value_zone(df)
    print(f"→ {len(df_vz)} trades en zona value (${MIN_PRICE}-${MAX_PRICE}, direccionales)")

    if df_vz.empty:
        print("⚠ Sin trades en la zona value. No se puede validar.")
        return

    # 3. Simular
    sim_df = simulate_value_zone(df_vz)

    # 4. Reporte
    report(sim_df, f"({len(df_vz)} trades)")

    # 5. Reporte por sesión
    print(f"\n{'='*60}")
    print(f"  DETALLE DE TRADES SIMULADOS")
    print(f"{'='*60}")
    for _, row in sim_df.iterrows():
        q = str(row['question'])[:70]
        rpnl = row['real_pnl']
        spnl = row['sim_pnl']
        diff = spnl - rpnl
        arrow = '🔼' if diff > 0 else ('🔽' if diff < 0 else '➡️')
        tag   = '✅' if spnl > 0 else '❌'
        print(f"  {tag} {q:70s}")
        print(f"     Entry=${row['entry_price']:.3f} | Real=${rpnl:+.2f} | Sim=${spnl:+.2f} {arrow} | {row['sim_reason']}")


if __name__ == '__main__':
    main()

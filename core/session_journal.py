"""
Session Journal — Genera un diario completo al cerrar una sesión paper.

Captura TODA la información de una sesión para auditoría retrospectiva:
  - Métricas globales (WR, PF, Sharpe, DD, expectancy)
  - Desglose por estrategia, asset, hora, close_reason
  - Top trades (mejores y peores)
  - Decisiones LLM: cuántos trades bloqueó correcta/incorrectamente
  - Equity curve
  - Contexto: qué mejoras se hicieron antes de esta sesión

Uso:
    python -m core.session_journal                     # sesión activa
    python -m core.session_journal PAPER_SESSION_003   # sesión específica
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

sys.path.insert(0, '/opt/trading')
load_dotenv('/opt/trading/config/.env')

REPORTS_DIR = Path('/opt/trading/reports')
REPORTS_DIR.mkdir(exist_ok=True)


def _db_url() -> str:
    return (
        f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
        f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT', '5432')}"
        f"/{os.getenv('POSTGRES_DB')}"
    )


def _load_session(conn, name_or_id: str = None) -> Optional[dict]:
    """Carga sesión por nombre, ID, o la última activa/cerrada."""
    if name_or_id:
        row = conn.execute(
            text(
                "SELECT * FROM paper_sessions "
                "WHERE session_name = :v OR id::text = :v "
                "ORDER BY started_at DESC LIMIT 1"
            ),
            {'v': name_or_id},
        ).fetchone()
    else:
        row = conn.execute(
            text(
                "SELECT * FROM paper_sessions "
                "ORDER BY started_at DESC LIMIT 1"
            )
        ).fetchone()
    return dict(row._mapping) if row else None


def _load_trades(conn, session: dict) -> pd.DataFrame:
    """Carga todos los trades cerrados de una sesión."""
    return pd.read_sql(
        text(
            "SELECT * FROM trades "
            "WHERE paper_trade = true AND status = 'CLOSED' "
            "AND timestamp_open >= :t0 "
            "AND (:t1 IS NULL OR timestamp_open <= :t1) "
            "ORDER BY timestamp_open"
        ),
        conn,
        params={'t0': session['started_at'], 't1': session.get('ended_at')},
    )


def _load_equity(conn, session: dict) -> pd.DataFrame:
    """Carga snapshots de portfolio para equity curve."""
    return pd.read_sql(
        text(
            "SELECT timestamp, total_balance, available_cash, exposure_pct, "
            "drawdown_pct, peak_balance "
            "FROM portfolio "
            "WHERE timestamp >= :t0 "
            "AND (:t1 IS NULL OR timestamp <= :t1) "
            "ORDER BY timestamp"
        ),
        conn,
        params={'t0': session['started_at'], 't1': session.get('ended_at')},
    )


def _load_signals(conn, session: dict) -> pd.DataFrame:
    """Carga señales generadas durante la sesión."""
    return pd.read_sql(
        text(
            "SELECT * FROM signals "
            "WHERE timestamp >= :t0 "
            "AND (:t1 IS NULL OR timestamp <= :t1) "
            "ORDER BY timestamp"
        ),
        conn,
        params={'t0': session['started_at'], 't1': session.get('ended_at')},
    )


def _load_llm_decisions(conn, session: dict) -> pd.DataFrame:
    """Carga decisiones del LLM (anomaly_check) durante la sesión."""
    return pd.read_sql(
        text(
            "SELECT * FROM claude_explanations "
            "WHERE timestamp >= :t0 "
            "AND (:t1 IS NULL OR timestamp <= :t1) "
            "ORDER BY timestamp"
        ),
        conn,
        params={'t0': session['started_at'], 't1': session.get('ended_at')},
    )


# ── Cálculos de métricas ─────────────────────────────────────────

def _global_metrics(trades: pd.DataFrame, equity: pd.DataFrame, session: dict) -> dict:
    """Métricas globales de la sesión."""
    n = len(trades)
    if n == 0:
        return {'total_trades': 0, 'note': 'No closed trades in session'}

    winners = trades[trades['pnl'] > 0]
    losers = trades[trades['pnl'] < 0]
    breakeven = trades[trades['pnl'] == 0]

    avg_win = float(winners['pnl'].mean()) if len(winners) else 0.0
    avg_loss = float(abs(losers['pnl'].mean())) if len(losers) else 0.0
    gross_profit = float(winners['pnl'].sum()) if len(winners) else 0.0
    gross_loss = float(abs(losers['pnl'].sum())) if len(losers) else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

    total_pnl = float(trades['pnl'].sum())
    initial = float(session['initial_balance'])
    final_balance = initial + total_pnl

    # Sharpe & drawdown from equity curve
    sharpe, max_dd = 0.0, 0.0
    if len(equity) > 1:
        returns = equity['total_balance'].pct_change().dropna()
        if returns.std() > 0:
            sharpe = float((returns.mean() / returns.std()) * np.sqrt(365))
        max_dd = float(
            (equity['total_balance'] / equity['total_balance'].cummax() - 1).min()
        )

    expectancy = (len(winners) / n) * avg_win - (len(losers) / n) * avg_loss

    # Duración promedio
    trades_with_duration = trades.dropna(subset=['timestamp_close'])
    if len(trades_with_duration) > 0:
        durations = (
            trades_with_duration['timestamp_close'] - trades_with_duration['timestamp_open']
        )
        avg_duration_min = float(durations.mean().total_seconds() / 60)
    else:
        avg_duration_min = 0.0

    return {
        'total_trades': int(n),
        'winners': int(len(winners)),
        'losers': int(len(losers)),
        'breakeven': int(len(breakeven)),
        'win_rate': round(len(winners) / n, 4),
        'profit_factor': round(profit_factor, 3),
        'sharpe_ratio': round(sharpe, 3),
        'max_drawdown_pct': round(max_dd * 100, 2),
        'expectancy_per_trade': round(expectancy, 2),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'gross_profit': round(gross_profit, 2),
        'gross_loss': round(gross_loss, 2),
        'total_pnl': round(total_pnl, 2),
        'initial_balance': round(initial, 2),
        'final_balance': round(final_balance, 2),
        'return_pct': round((total_pnl / initial) * 100, 2) if initial > 0 else 0,
        'avg_duration_min': round(avg_duration_min, 1),
    }


def _by_strategy(trades: pd.DataFrame) -> list[dict]:
    """Desglose de rendimiento por estrategia."""
    results = []
    for strat, grp in trades.groupby('strategy'):
        w = grp[grp['pnl'] > 0]
        l = grp[grp['pnl'] < 0]
        n = len(grp)
        avg = float(grp['pnl'].mean())
        results.append({
            'strategy': strat,
            'trades': n,
            'winners': int(len(w)),
            'losers': int(len(l)),
            'win_rate': round(len(w) / n, 3) if n else 0,
            'total_pnl': round(float(grp['pnl'].sum()), 2),
            'avg_pnl': round(avg, 2) if not np.isnan(avg) else 0.0,
            'best_trade': round(float(grp['pnl'].max()), 2),
            'worst_trade': round(float(grp['pnl'].min()), 2),
        })
    return sorted(results, key=lambda x: x['total_pnl'], reverse=True)


def _by_asset(trades: pd.DataFrame) -> list[dict]:
    """Desglose de rendimiento por asset."""
    results = []
    for asset, grp in trades.groupby('asset'):
        w = grp[grp['pnl'] > 0]
        n = len(grp)
        avg = float(grp['pnl'].mean())
        results.append({
            'asset': asset,
            'trades': n,
            'winners': int(len(w)),
            'win_rate': round(len(w) / n, 3) if n else 0,
            'total_pnl': round(float(grp['pnl'].sum()), 2),
            'avg_pnl': round(avg, 2) if not np.isnan(avg) else 0.0,
            'sides': dict(grp['side'].value_counts()),
        })
    return sorted(results, key=lambda x: x['total_pnl'], reverse=True)


def _by_hour(trades: pd.DataFrame) -> list[dict]:
    """Desglose de rendimiento por hora UTC."""
    trades = trades.copy()
    trades['hour'] = trades['timestamp_open'].dt.hour
    results = []
    for hour, grp in trades.groupby('hour'):
        w = grp[grp['pnl'] > 0]
        n = len(grp)
        results.append({
            'hour_utc': int(hour),
            'trades': n,
            'win_rate': round(len(w) / n, 3) if n else 0,
            'total_pnl': round(float(grp['pnl'].sum()), 2),
        })
    return sorted(results, key=lambda x: x['hour_utc'])


def _by_close_reason(trades: pd.DataFrame) -> list[dict]:
    """Desglose por motivo de cierre."""
    results = []
    for reason, grp in trades.groupby('close_reason'):
        w = grp[grp['pnl'] > 0]
        n = len(grp)
        avg = float(grp['pnl'].mean())
        results.append({
            'close_reason': reason,
            'count': n,
            'win_rate': round(len(w) / n, 3) if n else 0,
            'total_pnl': round(float(grp['pnl'].sum()), 2),
            'avg_pnl': round(avg, 2) if not np.isnan(avg) else 0.0,
        })
    return sorted(results, key=lambda x: x['total_pnl'], reverse=True)


def _by_side(trades: pd.DataFrame) -> dict:
    """Desglose BUY vs SELL."""
    results = {}
    for side, grp in trades.groupby('side'):
        w = grp[grp['pnl'] > 0]
        n = len(grp)
        results[side] = {
            'count': n,
            'win_rate': round(len(w) / n, 3) if n else 0,
            'total_pnl': round(float(grp['pnl'].sum()), 2),
        }
    return results


def _top_trades(trades: pd.DataFrame, n: int = 5) -> dict:
    """Top N mejores y peores trades."""
    def _trade_summary(row):
        duration = None
        if pd.notna(row.get('timestamp_close')) and pd.notna(row.get('timestamp_open')):
            duration = round(
                (row['timestamp_close'] - row['timestamp_open']).total_seconds() / 60, 1
            )
        return {
            'asset': row['asset'],
            'side': row['side'],
            'strategy': row['strategy'],
            'entry_price': float(row['entry_price']),
            'exit_price': float(row['exit_price']) if pd.notna(row.get('exit_price')) else None,
            'pnl': round(float(row['pnl']), 2),
            'pnl_pct': round(float(row['pnl_pct']), 4) if pd.notna(row.get('pnl_pct')) else None,
            'close_reason': row['close_reason'],
            'duration_min': duration,
            'timestamp_open': str(row['timestamp_open']),
        }

    best = trades.nlargest(n, 'pnl')
    worst = trades.nsmallest(n, 'pnl')
    return {
        'best': [_trade_summary(row) for _, row in best.iterrows()],
        'worst': [_trade_summary(row) for _, row in worst.iterrows()],
    }


def _llm_analysis(llm_df: pd.DataFrame, trades: pd.DataFrame) -> dict:
    """Analiza la efectividad de las decisiones del LLM."""
    if llm_df.empty:
        return {'total_calls': 0, 'note': 'No LLM decisions recorded'}

    anomaly_checks = llm_df[llm_df['task_type'] == 'anomaly_check']
    total = len(anomaly_checks)
    if total == 0:
        return {
            'total_calls': len(llm_df),
            'anomaly_checks': 0,
            'task_types': dict(llm_df['task_type'].value_counts()),
        }

    flagged = anomaly_checks[anomaly_checks['confidence'] >= 60]

    return {
        'total_calls': len(llm_df),
        'anomaly_checks': total,
        'flagged_as_anomaly': int(len(flagged)),
        'flag_rate': round(len(flagged) / total, 3) if total else 0,
        'task_types': dict(llm_df['task_type'].value_counts()),
        'avg_confidence': round(float(anomaly_checks['confidence'].mean()), 1),
        'avg_latency_ms': round(float(llm_df['latency_ms'].mean()), 0) if 'latency_ms' in llm_df else None,
        'total_tokens': int(llm_df['tokens_used'].sum()) if 'tokens_used' in llm_df else None,
    }


def _equity_curve_summary(equity: pd.DataFrame) -> dict:
    """Resumen de la equity curve para graficar después."""
    if equity.empty:
        return {'points': 0}

    return {
        'points': len(equity),
        'start_balance': round(float(equity['total_balance'].iloc[0]), 2),
        'end_balance': round(float(equity['total_balance'].iloc[-1]), 2),
        'high': round(float(equity['total_balance'].max()), 2),
        'low': round(float(equity['total_balance'].min()), 2),
        'max_exposure_pct': round(float(equity['exposure_pct'].max()), 4),
        'avg_exposure_pct': round(float(equity['exposure_pct'].mean()), 4),
        # Data points (sampled to max 200 for storage efficiency)
        'curve': _sample_curve(equity),
    }


def _sample_curve(equity: pd.DataFrame, max_points: int = 200) -> list[dict]:
    """Muestrea la equity curve para almacenamiento eficiente."""
    if len(equity) <= max_points:
        df = equity
    else:
        step = max(1, len(equity) // max_points)
        df = equity.iloc[::step]

    return [
        {
            'ts': str(row['timestamp']),
            'bal': round(float(row['total_balance']), 2),
            'dd': round(float(row['drawdown_pct']), 4),
        }
        for _, row in df.iterrows()
    ]


def _generate_recommendations(metrics: dict, by_strat: list, by_asset: list,
                              by_hour: list, by_reason: list) -> list[str]:
    """Genera recomendaciones accionables basadas en los datos."""
    recs = []

    # Win rate
    wr = metrics.get('win_rate', 0)
    if wr < 0.50:
        recs.append(f'WIN_RATE BAJA ({wr:.0%}): Revisar criterios de entrada — '
                     f'demasiadas señales falsas están pasando el filtro.')
    elif wr >= 0.65:
        recs.append(f'WIN_RATE ALTA ({wr:.0%}): Considerar aumentar TP target '
                     f'o reducir SL — podrías capturar más profit por trade.')

    # Profit factor
    pf = metrics.get('profit_factor', 0)
    if pf < 1.0:
        recs.append(f'PROFIT_FACTOR < 1 ({pf:.2f}): El sistema pierde dinero neto. '
                     f'Las pérdidas son mayores que las ganancias.')
    elif pf < 1.5:
        recs.append(f'PROFIT_FACTOR BAJO ({pf:.2f}): Edge marginal. Necesita más '
                     f'filtros o mejor timing de salida.')

    # Drawdown
    dd = metrics.get('max_drawdown_pct', 0)
    if dd < -10:
        recs.append(f'DRAWDOWN ALTO ({dd:.1f}%): Reducir position sizing o '
                     f'agregar filtro de régimen de mercado.')

    # Estrategias perdedoras
    for s in by_strat:
        if s['total_pnl'] < -100 and s['trades'] >= 5:
            recs.append(f'ESTRATEGIA {s["strategy"]}: P&L negativo (${s["total_pnl"]:.0f} en '
                         f'{s["trades"]} trades). Considerar desactivar o recalibrar.')

    # Assets perdedores
    for a in by_asset:
        if a['total_pnl'] < -100 and a['trades'] >= 5:
            recs.append(f'ASSET {a["asset"]}: P&L negativo (${a["total_pnl"]:.0f}). '
                         f'Evaluar si este mercado es operable con la estrategia actual.')

    # Horas malas
    bad_hours = [h for h in by_hour if h['total_pnl'] < -50 and h['trades'] >= 3]
    if bad_hours:
        hours_str = ', '.join(f'{h["hour_utc"]}:00' for h in bad_hours)
        recs.append(f'HORAS NEGATIVAS ({hours_str} UTC): Considerar agregar a DEAD_HOURS.')

    # Close reason analysis
    for r in by_reason:
        if r['close_reason'] == 'STOP_LOSS' and r['count'] > metrics.get('total_trades', 1) * 0.5:
            recs.append(f'DEMASIADOS SL ({r["count"]}/{metrics["total_trades"]}): '
                         f'SL puede estar muy ajustado, o las entradas son imprecisas.')

    # Sesgo BUY vs SELL (revisaremos vía metrics si existe)
    if metrics.get('total_trades', 0) >= 10:
        if metrics.get('avg_duration_min', 0) < 5:
            recs.append('DURACIÓN MUY CORTA: Trades promedio < 5 min. '
                        'Posible señal de apertura/cierre rápido o loop.')

    if not recs:
        recs.append('Sin issues críticos detectados. Mantener configuración actual.')

    return recs


# ── Generador principal ──────────────────────────────────────────

def generate_journal(session_name_or_id: str = None, save_to_db: bool = True,
                     notes: str = None) -> dict:
    """
    Genera el diario completo de una sesión paper.

    Args:
        session_name_or_id: Nombre o UUID de la sesión. None = última sesión.
        save_to_db: Guardar en session_reports.
        notes: Notas manuales del operador (qué cambios se hicieron antes de esta sesión).

    Returns:
        Dict con todo el journal.
    """
    engine = create_engine(_db_url())

    with engine.connect() as conn:
        session = _load_session(conn, session_name_or_id)
        if session is None:
            logger.error(f'Session not found: {session_name_or_id}')
            return {'error': 'Session not found'}

        trades = _load_trades(conn, session)
        equity = _load_equity(conn, session)
        signals = _load_signals(conn, session)
        llm = _load_llm_decisions(conn, session)

    logger.info(f'Journal: {session["session_name"]} — {len(trades)} trades, '
                f'{len(equity)} equity points, {len(signals)} signals')

    metrics = _global_metrics(trades, equity, session)
    by_strat = _by_strategy(trades) if len(trades) > 0 else []
    by_asset = _by_asset(trades) if len(trades) > 0 else []
    by_hour = _by_hour(trades) if len(trades) > 0 else []
    by_reason = _by_close_reason(trades) if len(trades) > 0 else []
    by_side = _by_side(trades) if len(trades) > 0 else {}
    top = _top_trades(trades) if len(trades) > 0 else {'best': [], 'worst': []}
    llm_stats = _llm_analysis(llm, trades)
    eq_summary = _equity_curve_summary(equity)
    recommendations = _generate_recommendations(metrics, by_strat, by_asset, by_hour, by_reason)

    journal = {
        'session': {
            'id': str(session['id']),
            'name': session['session_name'],
            'status': session['status'],
            'started_at': str(session['started_at']),
            'ended_at': str(session.get('ended_at')),
            'initial_balance': float(session['initial_balance']),
            'operator_notes': notes,
        },
        'metrics': metrics,
        'by_strategy': by_strat,
        'by_asset': by_asset,
        'by_hour': by_hour,
        'by_close_reason': by_reason,
        'by_side': by_side,
        'top_trades': top,
        'llm_analysis': llm_stats,
        'equity_curve': eq_summary,
        'signals_generated': int(len(signals)),
        'signal_to_trade_ratio': round(len(trades) / len(signals), 3) if len(signals) > 0 else 0,
        'recommendations': recommendations,
        'generated_at': str(datetime.now(timezone.utc)),
    }

    # Guardar JSON en /reports/
    filename = f'{session["session_name"]}_journal.json'
    filepath = REPORTS_DIR / filename
    with open(filepath, 'w') as f:
        json.dump(journal, f, indent=2, default=str)
    logger.info(f'Journal saved: {filepath}')

    # Guardar en DB (sanitize NaN → null for JSON compat)
    if save_to_db:
        def _sanitize(obj):
            """Replace NaN/Inf with None for JSON serialization."""
            s = json.dumps(obj, default=str)
            s = s.replace(': NaN', ': null').replace(':NaN', ':null')
            s = s.replace(': Infinity', ': null').replace(': -Infinity', ': null')
            return s

        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO session_reports "
                    "(id, session_id, report_type, metrics, analysis, recommendations, created_at) "
                    "VALUES (:id, :sid, 'journal', :metrics, :analysis, :recs, NOW())"
                ),
                {
                    'id': str(uuid.uuid4()),
                    'sid': str(session['id']),
                    'metrics': _sanitize(metrics),
                    'analysis': _sanitize({
                        'by_strategy': by_strat,
                        'by_asset': by_asset,
                        'by_hour': by_hour,
                        'by_close_reason': by_reason,
                        'by_side': by_side,
                        'top_trades': top,
                        'llm_analysis': llm_stats,
                        'equity_curve': eq_summary,
                    }),
                    'recs': recommendations,
                },
            )
        logger.info(f'Journal saved to DB: session_reports')

    # Generar Markdown legible
    _save_markdown(journal, REPORTS_DIR / f'{session["session_name"]}_journal.md')

    return journal


def _save_markdown(journal: dict, path: Path):
    """Genera un Markdown legible del journal."""
    s = journal['session']
    m = journal['metrics']

    lines = [
        f'# 📊 Journal: {s["name"]}',
        f'',
        f'**Estado:** {s["status"]}  ',
        f'**Período:** {s["started_at"][:19]} → {str(s["ended_at"])[:19]}  ',
        f'**Balance:** ${m.get("initial_balance", 0):,.0f} → ${m.get("final_balance", 0):,.0f} '
        f'({m.get("return_pct", 0):+.1f}%)  ',
    ]

    if s.get('operator_notes'):
        lines += ['', f'> **Notas del operador:** {s["operator_notes"]}', '']

    # Métricas globales
    lines += [
        '', '## Métricas Globales', '',
        f'| Métrica | Valor | Target |',
        f'|---------|-------|--------|',
        f'| Total trades | {m.get("total_trades", 0)} | ≥30 |',
        f'| Win rate | {m.get("win_rate", 0):.1%} | ≥55% |',
        f'| Profit factor | {m.get("profit_factor", 0):.2f} | ≥1.5 |',
        f'| Sharpe ratio | {m.get("sharpe_ratio", 0):.2f} | ≥1.5 |',
        f'| Max drawdown | {m.get("max_drawdown_pct", 0):.1f}% | ≥-12% |',
        f'| Expectancy | ${m.get("expectancy_per_trade", 0):.2f}/trade | >0 |',
        f'| Avg duration | {m.get("avg_duration_min", 0):.0f} min | — |',
        f'| Total P&L | ${m.get("total_pnl", 0):,.2f} | — |',
    ]

    # Graduación
    ready = all([
        m.get('win_rate', 0) >= 0.55,
        m.get('profit_factor', 0) >= 1.5,
        m.get('max_drawdown_pct', 0) >= -12,
        m.get('total_trades', 0) >= 30,
    ])
    lines += ['', f'**🎓 Ready for live:** {"SÍ ✅" if ready else "NO ❌"}', '']

    # Por estrategia
    if journal.get('by_strategy'):
        lines += ['## Por Estrategia', '',
                   '| Estrategia | Trades | WR | P&L | Avg |',
                   '|------------|--------|-----|------|-----|']
        for s in journal['by_strategy']:
            lines.append(
                f'| {s["strategy"]} | {s["trades"]} | {s["win_rate"]:.0%} '
                f'| ${s["total_pnl"]:,.0f} | ${s["avg_pnl"]:.1f} |'
            )
        lines.append('')

    # Por asset
    if journal.get('by_asset'):
        lines += ['## Por Asset', '',
                   '| Asset | Trades | WR | P&L | Sides |',
                   '|-------|--------|-----|------|-------|']
        for a in journal['by_asset']:
            sides = ', '.join(f'{k}:{v}' for k, v in a.get('sides', {}).items())
            lines.append(
                f'| {a["asset"]} | {a["trades"]} | {a["win_rate"]:.0%} '
                f'| ${a["total_pnl"]:,.0f} | {sides} |'
            )
        lines.append('')

    # Por hora
    if journal.get('by_hour'):
        lines += ['## Por Hora (UTC)', '',
                   '| Hora | Trades | WR | P&L |',
                   '|------|--------|-----|------|']
        for h in journal['by_hour']:
            lines.append(
                f'| {h["hour_utc"]:02d}:00 | {h["trades"]} | {h["win_rate"]:.0%} '
                f'| ${h["total_pnl"]:,.0f} |'
            )
        lines.append('')

    # Por close reason
    if journal.get('by_close_reason'):
        lines += ['## Por Motivo de Cierre', '',
                   '| Motivo | Count | WR | P&L | Avg |',
                   '|--------|-------|-----|------|-----|']
        for r in journal['by_close_reason']:
            lines.append(
                f'| {r["close_reason"]} | {r["count"]} | {r["win_rate"]:.0%} '
                f'| ${r["total_pnl"]:,.0f} | ${r["avg_pnl"]:.1f} |'
            )
        lines.append('')

    # Top trades
    if journal.get('top_trades', {}).get('best'):
        lines += ['## Top 5 Mejores Trades', '']
        for i, t in enumerate(journal['top_trades']['best'], 1):
            lines.append(
                f'{i}. **{t["asset"]} {t["side"]}** — ${t["pnl"]:+,.2f} '
                f'({t["strategy"]}, {t["close_reason"]}, {t.get("duration_min", "?")} min)'
            )
        lines.append('')

    if journal.get('top_trades', {}).get('worst'):
        lines += ['## Top 5 Peores Trades', '']
        for i, t in enumerate(journal['top_trades']['worst'], 1):
            lines.append(
                f'{i}. **{t["asset"]} {t["side"]}** — ${t["pnl"]:+,.2f} '
                f'({t["strategy"]}, {t["close_reason"]}, {t.get("duration_min", "?")} min)'
            )
        lines.append('')

    # Recomendaciones
    if journal.get('recommendations'):
        lines += ['## Recomendaciones', '']
        for r in journal['recommendations']:
            lines.append(f'- {r}')
        lines.append('')

    # LLM
    llm = journal.get('llm_analysis', {})
    if llm.get('total_calls', 0) > 0:
        lines += [
            '## LLM (anomaly_check)', '',
            f'- Total llamadas: {llm["total_calls"]}',
            f'- Anomaly checks: {llm.get("anomaly_checks", 0)}',
            f'- Flagged: {llm.get("flagged_as_anomaly", 0)} ({llm.get("flag_rate", 0):.0%})',
            f'- Avg confidence: {llm.get("avg_confidence", 0):.0f}',
            f'- Tokens usados: {llm.get("total_tokens", "N/A"):,}' if llm.get('total_tokens') else '',
            '',
        ]

    with open(path, 'w') as f:
        f.write('\n'.join(lines))
    logger.info(f'Markdown journal saved: {path}')


# ── CLI ──────────────────────────────────────────────────────────

def _print_journal_summary(journal: dict):
    """Imprime resumen del journal en consola."""
    s = journal['session']
    m = journal.get('metrics', {})

    print(f'\n{"="*60}')
    print(f'  SESSION JOURNAL: {s["name"]}')
    print(f'{"="*60}')

    if m.get('total_trades', 0) == 0:
        print('  No closed trades in this session.')
        return

    print(f'  Período:   {s["started_at"][:19]} → {str(s["ended_at"])[:19]}')
    print(f'  Balance:   ${m["initial_balance"]:,.0f} → ${m["final_balance"]:,.0f} ({m["return_pct"]:+.1f}%)')
    print(f'  Trades:    {m["total_trades"]} ({m["winners"]}W / {m["losers"]}L / {m["breakeven"]}BE)')
    print(f'  Win Rate:  {m["win_rate"]:.1%}')
    print(f'  PF:        {m["profit_factor"]:.2f}')
    print(f'  Sharpe:    {m["sharpe_ratio"]:.2f}')
    print(f'  Max DD:    {m["max_drawdown_pct"]:.1f}%')
    print(f'  Expect:    ${m["expectancy_per_trade"]:.2f}/trade')
    print()

    if journal.get('by_strategy'):
        print('  ESTRATEGIAS:')
        for s in journal['by_strategy']:
            print(f'    {s["strategy"]:25s}  {s["trades"]:3d} trades  '
                  f'WR={s["win_rate"]:.0%}  P&L=${s["total_pnl"]:>8,.0f}')
        print()

    if journal.get('recommendations'):
        print('  RECOMENDACIONES:')
        for r in journal['recommendations']:
            print(f'    → {r}')
        print()

    ready = all([
        m.get('win_rate', 0) >= 0.55,
        m.get('profit_factor', 0) >= 1.5,
        m.get('max_drawdown_pct', 0) >= -12,
        m.get('total_trades', 0) >= 30,
    ])
    print(f'  GRADUATION: {"READY ✅" if ready else "NOT READY ❌"}')
    print(f'{"="*60}\n')


if __name__ == '__main__':
    session_arg = sys.argv[1] if len(sys.argv) > 1 else None
    notes_arg = sys.argv[2] if len(sys.argv) > 2 else None
    journal = generate_journal(session_arg, notes=notes_arg)
    if 'error' not in journal:
        _print_journal_summary(journal)

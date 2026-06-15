"""
agent_health.py — Métricas mínimas de salud por agente.

Define los umbrales que cada agente debe cumplir en una ventana de 7 días.
Si un agente falla 2 semanas consecutivas → se recomienda pausar.

Usado por health_check.py y dashboard para mostrar semáforos.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional


# ── Umbrales por agente ─────────────────────────────────────────────────

AGENT_THRESHOLDS = {
    'TREND_MOMENTUM': {
        'min_pf': 0.90,
        'min_wr': 40.0,
        'min_trades': 15,       # trades/semana
        'max_dd': 10.0,         # % drawdown máximo
        'table': 'trades',
        'strategy_filter': "strategy='TREND_MOMENTUM'",
        'pnl_col': 'pnl',
    },
    'GRID_BOT': {
        'min_pf': 1.00,
        'min_wr': 45.0,
        'min_trades': 30,
        'max_dd': 8.0,
        'table': 'trades',
        'strategy_filter': "strategy='GRID_BOT'",
        'pnl_col': 'pnl',
    },
    'GRID_STABLE': {
        'min_pf': 2.00,
        'min_wr': 45.0,
        'min_trades': 80,
        'max_dd': 5.0,
        'table': 'trades',
        'strategy_filter': "strategy='GRID_STABLE'",
        'pnl_col': 'pnl',
    },
    'STOCKS': {
        'min_pf': 0.90,
        'min_wr': 35.0,
        'min_trades': 5,
        'max_dd': 10.0,
        'table': 'stocks_trades',
        'strategy_filter': "1=1",  # all stocks strategies
        'pnl_col': 'pnl',
    },
    'OPTIONS': {
        'min_pf': 1.00,
        'min_wr': 50.0,
        'min_trades': 1,
        'max_dd': 15.0,
        'table': 'options_positions',
        'strategy_filter': "status='CLOSED'",
        'pnl_col': 'pnl_usd',
    },
}


def get_status_emoji(passing: int, total: int, dd_pct: float, max_dd: float) -> str:
    """Semáforo: 🟢🟡🔴⚫"""
    if dd_pct >= max_dd:
        return '🔴'
    if passing == total:
        return '🟢'
    if passing >= total - 1:
        return '🟡'
    return '🔴'


def check_agent_health(conn, agent_name: str, days: int = 7) -> dict:
    """Evalúa la salud de un agente en la ventana de N días.

    Returns:
        Dict con métricas, passing_count, y semáforo.
    """
    cfg = AGENT_THRESHOLDS.get(agent_name)
    if not cfg:
        return {'error': f'Unknown agent: {agent_name}'}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    pnl_col = cfg['pnl_col']
    tbl = cfg['table']
    where = cfg['strategy_filter']
    ts_col = 'timestamp_close' if tbl == 'trades' else ('closed_at' if tbl in ('stocks_trades', 'options_positions') else 'timestamp_close')

    try:
        cur = conn.cursor()

        # Total trades
        cur.execute(f"SELECT COUNT(*) FROM {tbl} WHERE {where} AND {ts_col} >= %s", (cutoff,))
        n_trades = int((cur.fetchone() or [0])[0])

        # Wins
        cur.execute(f"SELECT COUNT(*) FROM {tbl} WHERE {where} AND {pnl_col} > 0 AND {ts_col} >= %s", (cutoff,))
        n_wins = int((cur.fetchone() or [0])[0])

        # WR
        wr = round(n_wins / n_trades * 100, 1) if n_trades > 0 else 0

        # P&L
        cur.execute(f"SELECT COALESCE(SUM({pnl_col}), 0) FROM {tbl} WHERE {where} AND {ts_col} >= %s", (cutoff,))
        total_pnl = float((cur.fetchone() or [0])[0])

        # Avg win/loss
        cur.execute(f"SELECT COALESCE(AVG({pnl_col}), 0) FROM {tbl} WHERE {where} AND {pnl_col} > 0 AND {ts_col} >= %s", (cutoff,))
        avg_win = float((cur.fetchone() or [0])[0])
        cur.execute(f"SELECT COALESCE(AVG(ABS({pnl_col})), 0) FROM {tbl} WHERE {where} AND {pnl_col} <= 0 AND {ts_col} >= %s", (cutoff,))
        avg_loss = float((cur.fetchone() or [0])[0])

        # PF
        pf = round(avg_win / avg_loss, 2) if avg_loss > 0 else 0

        # DD (approximate from balance tracking or use max_dd from session)
        dd_pct = 0.0
        if agent_name == 'TREND_MOMENTUM':
            cur.execute("SELECT COALESCE(drawdown_pct, 0) FROM portfolio ORDER BY timestamp DESC LIMIT 1")
            dd_pct = float((cur.fetchone() or [0])[0] or 0) * 100
        elif agent_name == 'STOCKS':
            cur.execute("SELECT COALESCE(MAX(max_drawdown), 0) FROM stocks_sessions WHERE status='ACTIVE'")
            dd_pct = float((cur.fetchone() or [0])[0] or 0)
        elif agent_name == 'OPTIONS':
            cur.execute("SELECT COALESCE(MAX(max_drawdown_pct), 0) FROM options_sessions WHERE status='ACTIVE'")
            dd_pct = float((cur.fetchone() or [0])[0] or 0)

    except Exception as e:
        return {'error': str(e)[:100], 'agent': agent_name}

    # Check thresholds
    passing = 0
    checks = {}
    checks['pf'] = {'value': pf, 'min': cfg['min_pf'], 'pass': pf >= cfg['min_pf']}
    checks['wr'] = {'value': wr, 'min': cfg['min_wr'], 'pass': wr >= cfg['min_wr']}
    checks['trades'] = {'value': n_trades, 'min': cfg['min_trades'], 'pass': n_trades >= cfg['min_trades']}
    checks['dd'] = {'value': dd_pct, 'max': cfg['max_dd'], 'pass': dd_pct < cfg['max_dd']}

    for c in checks.values():
        if c['pass']:
            passing += 1

    emoji = get_status_emoji(passing, len(checks), dd_pct, cfg['max_dd'])

    return {
        'agent': agent_name,
        'emoji': emoji,
        'passing': f'{passing}/{len(checks)}',
        'n_trades': n_trades,
        'wr': wr,
        'pf': pf,
        'total_pnl': round(total_pnl, 2),
        'dd_pct': round(dd_pct, 1),
        'checks': checks,
        'window_days': days,
        'action': 'HEALTHY' if emoji == '🟢' else ('WARNING' if emoji == '🟡' else 'CRITICAL'),
    }


def get_all_agents_health(conn, days: int = 7) -> list[dict]:
    """Salud de todos los agentes."""
    results = []
    for name in AGENT_THRESHOLDS:
        r = check_agent_health(conn, name, days)
        if 'error' not in r:
            results.append(r)
    return results

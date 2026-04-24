"""Router: agente de stocks (NYSE/NASDAQ — Alpaca paper)."""
from fastapi import APIRouter
from api.db import q, q_one

router = APIRouter()

UNIVERSE = ['TSLA', 'AAPL', 'AMZN', 'NVDA', 'META', 'QQQ', 'GLD', 'EEM', 'FXI', 'EWJ']


@router.get('/session')
def get_session():
    """Sesión activa + KPIs."""
    session = q_one("SELECT * FROM stocks_sessions ORDER BY started_at DESC LIMIT 1")
    if not session:
        return {}

    sid = session['id']
    stats = q_one("""
        SELECT
            COUNT(*) FILTER (WHERE status = 'CLOSED') AS total_closed,
            COUNT(*) FILTER (WHERE status = 'CLOSED' AND pnl > 0) AS winners,
            COUNT(*) FILTER (WHERE status = 'OPEN') AS open_count,
            COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED'), 0) AS total_pnl,
            COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED' AND pnl > 0), 0) AS gross_profit,
            COALESCE(ABS(SUM(pnl) FILTER (WHERE status = 'CLOSED' AND pnl < 0)), 0) AS gross_loss,
            COALESCE(SUM(notional) FILTER (WHERE status = 'OPEN'), 0) AS exposure
        FROM stocks_trades WHERE session_id = :sid
    """, {'sid': sid})

    closed = stats['total_closed'] or 0
    winners = stats['winners'] or 0
    gp = float(stats['gross_profit'] or 0)
    gl = float(stats['gross_loss'] or 0)

    return {
        **session,
        'total_closed': closed,
        'open_count': stats['open_count'],
        'win_rate': round(winners / closed * 100, 1) if closed > 0 else 0,
        'profit_factor': round(gp / gl, 2) if gl > 0 else (float('inf') if gp > 0 else 0),
        'total_pnl': round(float(stats['total_pnl'] or 0), 2),
        'exposure': round(float(stats['exposure'] or 0), 2),
    }


@router.get('/trades')
def get_trades(limit: int = 200, symbol: str = None, status: str = None, strategy: str = None):
    """Historial de trades con filtros opcionales."""
    filters = ['1=1']
    params = {'limit': limit}
    if symbol:
        filters.append('symbol = :symbol')
        params['symbol'] = symbol.upper()
    if status:
        filters.append('status = :status')
        params['status'] = status.upper()
    if strategy:
        filters.append('strategy = :strategy')
        params['strategy'] = strategy.upper()

    where = ' AND '.join(filters)
    return q(f"""
        SELECT * FROM stocks_trades
        WHERE {where}
        ORDER BY opened_at DESC
        LIMIT :limit
    """, params)


@router.get('/trades/open')
def get_open_trades():
    session = q_one("SELECT id FROM stocks_sessions ORDER BY started_at DESC LIMIT 1")
    if not session:
        return []
    return q("""
        SELECT * FROM stocks_trades
        WHERE session_id = :sid AND status = 'OPEN'
        ORDER BY opened_at DESC
    """, {'sid': session['id']})


@router.get('/trades/equity')
def get_equity_curve():
    """Curva de equity acumulada para el agente de stocks."""
    session = q_one("SELECT id, initial_balance FROM stocks_sessions ORDER BY started_at DESC LIMIT 1")
    if not session:
        return []
    initial = float(session['initial_balance'] or 220)
    trades = q("""
        SELECT closed_at, pnl FROM stocks_trades
        WHERE session_id = :sid AND status = 'CLOSED' AND closed_at IS NOT NULL
        ORDER BY closed_at ASC
    """, {'sid': session['id']})
    balance = initial
    points = [{'ts': None, 'balance': initial}]
    for t in trades:
        balance += float(t['pnl'] or 0)
        points.append({'ts': str(t['closed_at']), 'balance': round(balance, 2)})
    return points


@router.get('/universe')
def get_universe():
    """Stats por símbolo del universo (24h de trades)."""
    rows = q("""
        SELECT
            symbol,
            strategy,
            COUNT(*) FILTER (WHERE status = 'CLOSED') AS total_trades,
            COUNT(*) FILTER (WHERE status = 'CLOSED' AND pnl > 0) AS winners,
            COUNT(*) FILTER (WHERE status = 'OPEN') AS open_positions,
            COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED'), 0) AS total_pnl,
            COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED' AND pnl > 0), 0) AS gross_profit,
            COALESCE(ABS(SUM(pnl) FILTER (WHERE status = 'CLOSED' AND pnl < 0)), 0) AS gross_loss,
            MAX(opened_at) AS last_signal
        FROM stocks_trades
        GROUP BY symbol, strategy
        ORDER BY total_pnl DESC
    """)

    # Completar el universo con assets sin trades aún
    existing = {r['symbol'] for r in rows}
    for sym in UNIVERSE:
        if sym not in existing:
            rows.append({
                'symbol': sym, 'strategy': None,
                'total_trades': 0, 'winners': 0, 'open_positions': 0,
                'total_pnl': 0, 'gross_profit': 0, 'gross_loss': 0,
                'last_signal': None,
            })

    # Calcular PF y WR
    result = []
    for r in rows:
        closed = int(r['total_trades'] or 0)
        winners = int(r['winners'] or 0)
        gp = float(r['gross_profit'] or 0)
        gl = float(r['gross_loss'] or 0)
        result.append({
            **r,
            'win_rate': round(winners / closed * 100, 1) if closed > 0 else None,
            'profit_factor': round(gp / gl, 2) if gl > 0 else None,
            'total_pnl': round(float(r['total_pnl'] or 0), 2),
        })
    return result


@router.get('/stats/by-strategy')
def stats_by_strategy():
    return q("""
        SELECT
            strategy,
            COUNT(*) FILTER (WHERE status = 'CLOSED') AS trades,
            COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED'), 0) AS total_pnl,
            COUNT(*) FILTER (WHERE status = 'CLOSED' AND pnl > 0) AS winners
        FROM stocks_trades
        WHERE status = 'CLOSED'
        GROUP BY strategy
        ORDER BY total_pnl DESC
    """)


@router.get('/stats/daily-pnl')
def daily_pnl():
    """P&L por día de calendario para el heatmap."""
    return q("""
        SELECT
            DATE(closed_at) AS day,
            SUM(pnl) AS pnl,
            COUNT(*) AS trades
        FROM stocks_trades
        WHERE status = 'CLOSED' AND closed_at IS NOT NULL
        GROUP BY DATE(closed_at)
        ORDER BY day ASC
    """)

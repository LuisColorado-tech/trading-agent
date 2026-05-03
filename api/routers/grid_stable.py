"""Router: Grid Stable Bot (ETH/BTC, LINK/BTC) — servicio independiente."""
from fastapi import APIRouter, Query
from api.db import q, q_one

router = APIRouter()


@router.get('/trades')
def get_trades(limit: int = 200, pair: str = None):
    where = "strategy = 'GRID_STABLE'"
    params = {'limit': limit}
    if pair:
        where += " AND asset = :pair"
        params['pair'] = pair
    return q(f"""
        SELECT * FROM trades WHERE {where}
        ORDER BY timestamp_open DESC LIMIT :limit
    """, params)


@router.get('/stats')
def stats():
    """KPIs del Grid Stable Bot por par."""
    row = q_one("""
        SELECT
            COUNT(*) FILTER (WHERE status = 'CLOSED') AS total_closed,
            COUNT(*) FILTER (WHERE status = 'OPEN') AS open_count,
            COUNT(*) FILTER (WHERE status = 'CLOSED' AND pnl > 0) AS winners,
            COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED'), 0) AS total_pnl,
            COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED' AND pnl > 0), 0) AS gross_profit,
            COALESCE(ABS(SUM(pnl) FILTER (WHERE status = 'CLOSED' AND pnl < 0)), 0) AS gross_loss,
            COALESCE(AVG(pnl) FILTER (WHERE status = 'CLOSED' AND pnl > 0), 0) AS avg_win,
            COALESCE(AVG(pnl) FILTER (WHERE status = 'CLOSED' AND pnl < 0), 0) AS avg_loss
        FROM trades WHERE strategy = 'GRID_STABLE'
    """) or {}
    closed = int(row.get('total_closed') or 0)
    winners = int(row.get('winners') or 0)
    gp = float(row.get('gross_profit') or 0)
    gl = float(row.get('gross_loss') or 0)

    # Por par
    by_pair = q("""
        SELECT asset, COUNT(*) as trades,
               COUNT(*) FILTER (WHERE pnl > 0) as wins,
               SUM(pnl) as total_pnl,
               ROUND((COUNT(*) FILTER (WHERE pnl > 0)::numeric / NULLIF(COUNT(*),0))*100, 1) as wr
        FROM trades WHERE strategy = 'GRID_STABLE' AND status = 'CLOSED'
        GROUP BY asset ORDER BY asset
    """)

    # Por close_reason
    by_reason = q("""
        SELECT close_reason, COUNT(*) as count, SUM(pnl) as total_pnl
        FROM trades WHERE strategy = 'GRID_STABLE' AND status = 'CLOSED'
        GROUP BY close_reason ORDER BY close_reason
    """)

    return {
        'total_trades': closed,
        'open_trades': int(row.get('open_count') or 0),
        'winners': winners,
        'win_rate': round(winners / closed * 100, 1) if closed > 0 else 0,
        'profit_factor': round(gp / gl, 2) if gl > 0 else 0,
        'total_pnl': round(float(row.get('total_pnl') or 0), 2),
        'avg_win': round(float(row.get('avg_win') or 0), 2),
        'avg_loss': round(float(row.get('avg_loss') or 0), 2),
        'by_pair': [dict(r) for r in by_pair],
        'by_reason': [dict(r) for r in by_reason],
    }


@router.get('/stats/daily')
def daily_pnl():
    return q("""
        SELECT DATE(timestamp_close) AS day, asset, SUM(pnl) AS pnl, COUNT(*) AS trades
        FROM trades
        WHERE strategy = 'GRID_STABLE' AND status = 'CLOSED' AND timestamp_close IS NOT NULL
        GROUP BY DATE(timestamp_close), asset
        ORDER BY day DESC, asset
    """)

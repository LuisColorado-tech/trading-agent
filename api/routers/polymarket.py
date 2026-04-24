"""Router: Polymarket + BTC Direction."""
from fastapi import APIRouter
from api.db import q, q_one

router = APIRouter()


@router.get('/session')
def get_session():
    return q_one("SELECT * FROM poly_sessions ORDER BY started_at DESC LIMIT 1") or {}


@router.get('/positions')
def get_positions(limit: int = 200, status: str = None):
    params = {'limit': limit}
    where = '1=1'
    if status:
        where = 'status = :status'
        params['status'] = status.upper()
    return q(f"""
        SELECT * FROM poly_positions WHERE {where}
        ORDER BY timestamp_open DESC LIMIT :limit
    """, params)


@router.get('/stats')
def stats():
    row = q_one("""
        SELECT
            COUNT(*) FILTER (WHERE status = 'CLOSED') AS total,
            COUNT(*) FILTER (WHERE status = 'CLOSED' AND pnl > 0) AS winners,
            COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED'), 0) AS total_pnl,
            COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED' AND pnl > 0), 0) AS gross_profit,
            COALESCE(ABS(SUM(pnl) FILTER (WHERE status = 'CLOSED' AND pnl < 0)), 0) AS gross_loss
        FROM poly_positions
    """) or {}
    closed = int(row.get('total') or 0)
    winners = int(row.get('winners') or 0)
    gp = float(row.get('gross_profit') or 0)
    gl = float(row.get('gross_loss') or 0)
    return {
        **row,
        'win_rate': round(winners / closed * 100, 1) if closed > 0 else 0,
        'profit_factor': round(gp / gl, 2) if gl > 0 else 0,
    }


@router.get('/btc-direction')
def btc_direction(limit: int = 100):
    return q("""
        SELECT * FROM btc_direction_trades
        ORDER BY timestamp_open DESC LIMIT :limit
    """, {'limit': limit})

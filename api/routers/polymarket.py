"""Router: Polymarket + BTC Direction + PolySnipe."""
from fastapi import APIRouter, Query
from api.db import q, q_one

router = APIRouter()


def _get_active_poly_session():
    return q_one("SELECT * FROM poly_sessions WHERE status='ACTIVE' ORDER BY started_at DESC LIMIT 1")


def _get_active_snipe_session():
    return q_one("SELECT * FROM snipe_sessions WHERE status='ACTIVE' ORDER BY started_at DESC LIMIT 1")


@router.get('/session')
def get_session():
    return q_one("SELECT * FROM poly_sessions ORDER BY started_at DESC LIMIT 1") or {}


@router.get('/positions')
def get_positions(limit: int = 200, status: str = None, scope: str = Query("all", description="all | session")):
    params = {'limit': limit}
    where = '1=1'
    if scope == "session":
        session = _get_active_poly_session()
        if session:
            where = "session_name = :sn"
            params['sn'] = session['session_name']
    if status:
        where += " AND status = :status"
        params['status'] = status.upper()
    return q(f"""
        SELECT * FROM poly_positions WHERE {where}
        ORDER BY timestamp_open DESC LIMIT :limit
    """, params)


@router.get('/stats')
def stats(scope: str = Query("all", description="all | session")):
    if scope == "session":
        session = _get_active_poly_session()
        if session:
            row = q_one("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'CLOSED') AS total,
                    COUNT(*) FILTER (WHERE status = 'CLOSED' AND pnl > 0) AS winners,
                    COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED'), 0) AS total_pnl,
                    COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED' AND pnl > 0), 0) AS gross_profit,
                    COALESCE(ABS(SUM(pnl) FILTER (WHERE status = 'CLOSED' AND pnl < 0)), 0) AS gross_loss
                FROM poly_positions WHERE session_name = :sn
            """, {'sn': session['session_name']}) or {}
            closed = int(row.get('total') or 0)
            winners = int(row.get('winners') or 0)
            gp = float(row.get('gross_profit') or 0)
            gl = float(row.get('gross_loss') or 0)
            return {
                **row,
                'win_rate': round(winners / closed * 100, 1) if closed > 0 else 0,
                'profit_factor': round(gp / gl, 2) if gl > 0 else 0,
            }
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
def btc_direction(limit: int = 100, scope: str = Query("all", description="all | session")):
    if scope == "session":
        session = _get_active_poly_session()
        if session:
            return q("""
                SELECT * FROM btc_direction_trades
                WHERE session_name = :sn
                ORDER BY timestamp_open DESC LIMIT :limit
            """, {'sn': session['session_name'], 'limit': limit})
    return q("""
        SELECT * FROM btc_direction_trades
        ORDER BY timestamp_open DESC LIMIT :limit
    """, {'limit': limit})


# ── PolySnipe endpoints ──
@router.get('/snipe')
def snipe_trades(limit: int = 200, scope: str = Query("all", description="all | session")):
    if scope == "session":
        session = _get_active_snipe_session()
        if session:
            return q("""
                SELECT * FROM snipe_trades
                WHERE timestamp_open >= :started_at
                ORDER BY timestamp_open DESC LIMIT :limit
            """, {'started_at': session['started_at'], 'limit': limit})
    return q("""
        SELECT * FROM snipe_trades
        ORDER BY timestamp_open DESC LIMIT :limit
    """, {'limit': limit})


@router.get('/snipe/stats')
def snipe_stats(scope: str = Query("all", description="all | session")):
    if scope == "session":
        session = _get_active_snipe_session()
        if session:
            row = q_one("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status = 'OPEN') AS open_cnt,
                    COUNT(*) FILTER (WHERE status = 'CLOSED') AS closed_cnt,
                    COUNT(*) FILTER (WHERE outcome = 'WIN') AS wins,
                    COUNT(*) FILTER (WHERE strategy = 'SNIPE') AS snipe_cnt,
                    COUNT(*) FILTER (WHERE strategy = 'ARB') AS arb_cnt,
                    COALESCE(SUM(pnl_usdc) FILTER (WHERE status = 'CLOSED'), 0) AS total_pnl
                FROM snipe_trades
                WHERE timestamp_open >= :started_at
            """, {'started_at': session['started_at']}) or {}
            closed = int(row.get('closed_cnt') or 0)
            wins = int(row.get('wins') or 0)
            return {
                **row,
                'win_rate': round(wins / closed * 100, 1) if closed > 0 else 0,
                'balance': 500.0 + float(row.get('total_pnl') or 0),
            }
    row = q_one("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = 'OPEN') AS open_cnt,
            COUNT(*) FILTER (WHERE status = 'CLOSED') AS closed_cnt,
            COUNT(*) FILTER (WHERE outcome = 'WIN') AS wins,
            COUNT(*) FILTER (WHERE strategy = 'SNIPE') AS snipe_cnt,
            COUNT(*) FILTER (WHERE strategy = 'ARB') AS arb_cnt,
            COALESCE(SUM(pnl_usdc) FILTER (WHERE status = 'CLOSED'), 0) AS total_pnl
        FROM snipe_trades
    """) or {}
    closed = int(row.get('closed_cnt') or 0)
    wins = int(row.get('wins') or 0)
    return {
        **row,
        'win_rate': round(wins / closed * 100, 1) if closed > 0 else 0,
        'balance': 500.0 + float(row.get('total_pnl') or 0),
    }

"""Router: Deribit Options (Theta Farming)."""
from fastapi import APIRouter, Query
from api.db import q, q_one

router = APIRouter()


def _get_active_options_session():
    return q_one("SELECT * FROM options_sessions WHERE status='ACTIVE' ORDER BY started_at DESC LIMIT 1")


@router.get('/session')
def get_session():
    try:
        return q_one("SELECT * FROM options_sessions ORDER BY started_at DESC LIMIT 1") or {}
    except Exception:
        return {}


@router.get('/positions')
def get_positions(limit: int = 200, scope: str = Query("all", description="all | session")):
    try:
        if scope == "session":
            session = _get_active_options_session()
            if session:
                return q("""
                    SELECT * FROM options_positions
                    WHERE opened_at >= :started_at
                    ORDER BY opened_at DESC LIMIT :limit
                """, {'started_at': session['started_at'], 'limit': limit})
        return q("""
            SELECT * FROM options_positions
            ORDER BY opened_at DESC LIMIT :limit
        """, {'limit': limit})
    except Exception:
        return []


@router.get('/stats')
def stats(scope: str = Query("all", description="all | session")):
    try:
        if scope == "session":
            session = _get_active_options_session()
            if session:
                row = q_one("""
                    SELECT
                        COUNT(*) FILTER (WHERE status != 'OPEN') AS total,
                        COUNT(*) FILTER (WHERE status != 'OPEN' AND pnl_usd > 0) AS winners,
                        COALESCE(SUM(entry_premium_usd) FILTER (WHERE status != 'OPEN'), 0) AS total_premium,
                        COALESCE(SUM(pnl_usd) FILTER (WHERE status != 'OPEN'), 0) AS total_pnl
                    FROM options_positions
                    WHERE opened_at >= :started_at
                """, {'started_at': session['started_at']}) or {}
                closed = int(row.get('total') or 0)
                winners = int(row.get('winners') or 0)
                return {
                    **row,
                    'win_rate': round(winners / closed * 100, 1) if closed > 0 else 0,
                }
        row = q_one("""
            SELECT
                COUNT(*) FILTER (WHERE status != 'OPEN') AS total,
                COUNT(*) FILTER (WHERE status != 'OPEN' AND pnl_usd > 0) AS winners,
                COALESCE(SUM(entry_premium_usd) FILTER (WHERE status != 'OPEN'), 0) AS total_premium,
                COALESCE(SUM(pnl_usd) FILTER (WHERE status != 'OPEN'), 0) AS total_pnl
            FROM options_positions
        """) or {}
        closed = int(row.get('total') or 0)
        winners = int(row.get('winners') or 0)
        return {
            **row,
            'win_rate': round(winners / closed * 100, 1) if closed > 0 else 0,
        }
    except Exception:
        return {}

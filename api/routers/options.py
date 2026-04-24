"""Router: Deribit Options (Theta Farming)."""
from fastapi import APIRouter
from api.db import q, q_one

router = APIRouter()


@router.get('/session')
def get_session():
    try:
        return q_one("SELECT * FROM options_sessions ORDER BY started_at DESC LIMIT 1") or {}
    except Exception:
        return {}


@router.get('/positions')
def get_positions(limit: int = 200):
    try:
        return q("""
            SELECT * FROM options_positions
            ORDER BY opened_at DESC LIMIT :limit
        """, {'limit': limit})
    except Exception:
        return []


@router.get('/stats')
def stats():
    try:
        row = q_one("""
            SELECT
                COUNT(*) FILTER (WHERE status = 'CLOSED') AS total,
                COUNT(*) FILTER (WHERE status = 'CLOSED' AND pnl > 0) AS winners,
                COALESCE(SUM(entry_premium_usd) FILTER (WHERE status = 'CLOSED'), 0) AS total_premium,
                COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED'), 0) AS total_pnl
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

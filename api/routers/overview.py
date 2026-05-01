"""Router: Overview — resumen de todos los agentes (v2 — session-scoped + fixes)."""
from fastapi import APIRouter
from api.db import q, q_one

router = APIRouter()


@router.get('/')
def overview():
    """Un solo endpoint que agrega KPIs de todos los agentes para el Overview page."""
    result = {}

    # ── Stocks agent ──
    try:
        sess = q_one("SELECT * FROM stocks_sessions WHERE status='ACTIVE' ORDER BY started_at DESC LIMIT 1")
        if not sess:
            sess = q_one("SELECT * FROM stocks_sessions ORDER BY started_at DESC LIMIT 1")
        if sess:
            sid = sess['id']
            sname = sess['session_name']
            stats = q_one("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'CLOSED') AS total_closed,
                    COUNT(*) FILTER (WHERE status = 'CLOSED' AND pnl > 0) AS winners,
                    COUNT(*) FILTER (WHERE status = 'OPEN') AS open_count,
                    COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED'), 0) AS total_pnl,
                    COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED' AND pnl > 0), 0) AS gross_profit,
                    COALESCE(ABS(SUM(pnl) FILTER (WHERE status = 'CLOSED' AND pnl < 0)), 0) AS gross_loss
                FROM stocks_trades WHERE session_id = :sid
            """, {'sid': sid})
            closed = int(stats['total_closed'] or 0)
            winners = int(stats['winners'] or 0)
            gp = float(stats['gross_profit'] or 0)
            gl = float(stats['gross_loss'] or 0)
            result['stocks'] = {
                'session_name': sname,
                'balance': float(sess['current_balance'] or sess['initial_balance'] or 220),
                'initial_balance': float(sess['initial_balance'] or 220),
                'total_pnl': round(float(stats['total_pnl'] or 0), 2),
                'win_rate': round(winners / closed * 100, 1) if closed > 0 else 0,
                'profit_factor': round(gp / gl, 2) if gl > 0 else 0,
                'open_trades': int(stats['open_count'] or 0),
                'total_trades': closed,
                'max_drawdown': float(sess.get('max_drawdown') or 0),
                'status': sess['status'],
            }
    except Exception:
        result['stocks'] = {'status': 'error'}

    # ── Crypto agent ──
    try:
        sess = q_one("SELECT * FROM paper_sessions WHERE status='ACTIVE' ORDER BY started_at DESC LIMIT 1")
        if not sess:
            sess = q_one("SELECT * FROM paper_sessions ORDER BY started_at DESC LIMIT 1")
        if sess:
            sname = sess['session_name']
            sstart = sess['started_at']
            pf = q_one("SELECT * FROM portfolio WHERE timestamp >= :ts ORDER BY timestamp DESC LIMIT 1",
                       {'ts': sstart}) or {}
            stats = q_one("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'CLOSED' AND close_reason != 'SESSION_CLOSE') AS total_closed,
                    COUNT(*) FILTER (WHERE status = 'CLOSED' AND pnl > 0) AS winners,
                    COUNT(*) FILTER (WHERE status = 'OPEN') AS open_count,
                    COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED'), 0) AS total_pnl,
                    COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED' AND pnl > 0), 0) AS gross_profit,
                    COALESCE(ABS(SUM(pnl) FILTER (WHERE status = 'CLOSED' AND pnl < 0)), 0) AS gross_loss
                FROM trades WHERE timestamp_open >= :ts
            """, {'ts': sstart}) or {}
            closed = int(stats.get('total_closed') or 0)
            winners = int(stats.get('winners') or 0)
            gp = float(stats.get('gross_profit') or 0)
            gl = float(stats.get('gross_loss') or 0)
            result['crypto'] = {
                'session_name': sname,
                'balance': float(pf.get('total_balance') or sess['initial_balance'] or 10000),
                'initial_balance': float(sess['initial_balance'] or 10000),
                'drawdown_pct': float(pf.get('drawdown_pct') or 0),
                'exposure_pct': float(pf.get('exposure_pct') or 0),
                'total_pnl': round(float(stats.get('total_pnl') or 0), 2),
                'win_rate': round(winners / closed * 100, 1) if closed > 0 else 0,
                'profit_factor': round(gp / gl, 2) if gl > 0 else 0,
                'open_trades': int(stats.get('open_count') or 0),
                'total_trades': closed,
                'max_drawdown': float(sess.get('max_drawdown') or 0),
                'status': sess['status'],
            }
    except Exception:
        result['crypto'] = {'status': 'error'}

    # ── Polymarket ──
    try:
        sess = q_one("SELECT * FROM poly_sessions WHERE status='ACTIVE' ORDER BY started_at DESC LIMIT 1")
        if not sess:
            sess = q_one("SELECT * FROM poly_sessions ORDER BY started_at DESC LIMIT 1")
        if sess:
            sname = sess['session_name']
            stats = q_one("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'CLOSED' AND close_reason != 'SESSION_RESET') AS total,
                    COUNT(*) FILTER (WHERE status = 'CLOSED' AND pnl > 0) AS winners,
                    COUNT(*) FILTER (WHERE status = 'OPEN') AS open_count,
                    COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED'), 0) AS total_pnl,
                    COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED' AND pnl > 0), 0) AS gross_profit,
                    COALESCE(ABS(SUM(pnl) FILTER (WHERE status = 'CLOSED' AND pnl < 0)), 0) AS gross_loss
                FROM poly_positions WHERE session_name = :sn
            """, {'sn': sname}) or {}
            closed = int(stats.get('total') or 0)
            winners = int(stats.get('winners') or 0)
            gp = float(stats.get('gross_profit') or 0)
            gl = float(stats.get('gross_loss') or 0)
            result['polymarket'] = {
                'session_name': sname,
                'balance': float(sess['current_balance'] or sess['initial_balance'] or 1000),
                'initial_balance': float(sess['initial_balance'] or 1000),
                'total_pnl': round(float(stats.get('total_pnl') or 0), 2),
                'win_rate': round(winners / closed * 100, 1) if closed > 0 else 0,
                'profit_factor': round(gp / gl, 2) if gl > 0 else 0,
                'open_trades': int(stats.get('open_count') or 0),
                'total_trades': closed,
                'max_drawdown': float(sess.get('max_drawdown') or 0),
                'status': sess['status'],
            }
    except Exception:
        result['polymarket'] = {'status': 'error'}

    # ── Options ──
    try:
        sess = q_one("SELECT * FROM options_sessions WHERE status='ACTIVE' ORDER BY started_at DESC LIMIT 1")
        if not sess:
            sess = q_one("SELECT * FROM options_sessions ORDER BY started_at DESC LIMIT 1")
        if sess:
            sname = sess['session_name']
            stats = q_one("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'CLOSED') AS total,
                    COUNT(*) FILTER (WHERE status = 'CLOSED' AND pnl_usd > 0) AS winners,
                    COUNT(*) FILTER (WHERE status = 'OPEN') AS open_count,
                    COALESCE(SUM(entry_premium_usd) FILTER (WHERE status = 'CLOSED'), 0) AS total_premium,
                    COALESCE(SUM(pnl_usd) FILTER (WHERE status = 'CLOSED'), 0) AS total_pnl
                FROM options_positions
            """) or {}
            closed = int(stats.get('total') or 0)
            winners = int(stats.get('winners') or 0)
            result['options'] = {
                'session_name': sname,
                'balance': float(sess['current_balance_usd'] or sess['initial_balance_usd'] or 2000),
                'initial_balance': float(sess['initial_balance_usd'] or 2000),
                'total_premium': round(float(stats.get('total_premium') or 0), 2),
                'total_pnl': round(float(stats.get('total_pnl') or 0), 2),
                'win_rate': round(winners / closed * 100, 1) if closed > 0 else 0,
                'open_trades': int(stats.get('open_count') or 0),
                'total_trades': closed,
                'status': sess['status'],
            }
    except Exception:
        result['options'] = {'status': 'error'}

    # ── BTC Direction ──
    try:
        btcd = q_one("""
            SELECT
                COUNT(*) FILTER (WHERE status = 'CLOSED') AS total,
                COUNT(*) FILTER (WHERE status = 'CLOSED' AND pnl_usdc > 0) AS winners,
                COUNT(*) FILTER (WHERE status = 'OPEN') AS open_count,
                COALESCE(SUM(pnl_usdc) FILTER (WHERE status = 'CLOSED'), 0) AS total_pnl,
                COALESCE(SUM(pnl_usdc) FILTER (WHERE status = 'CLOSED' AND pnl_usdc > 0), 0) AS gross_profit,
                COALESCE(ABS(SUM(pnl_usdc) FILTER (WHERE status = 'CLOSED' AND pnl_usdc < 0)), 0) AS gross_loss
            FROM btc_direction_trades
        """) or {}
        closed = int(btcd.get('total') or 0)
        winners = int(btcd.get('winners') or 0)
        gp = float(btcd.get('gross_profit') or 0)
        gl = float(btcd.get('gross_loss') or 0)
        result['btc_direction'] = {
            'total_pnl': round(float(btcd.get('total_pnl') or 0), 2),
            'win_rate': round(winners / closed * 100, 1) if closed > 0 else 0,
            'profit_factor': round(gp / gl, 2) if gl > 0 else 0,
            'open_trades': int(btcd.get('open_count') or 0),
            'total_trades': closed,
            'status': 'active' if closed > 0 else 'no_data',
        }
    except Exception:
        result['btc_direction'] = {'status': 'error'}

    return result

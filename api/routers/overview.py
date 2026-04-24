"""Router: Overview — resumen de todos los agentes."""
from fastapi import APIRouter
from api.db import q, q_one

router = APIRouter()


@router.get('/')
def overview():
    """Un solo endpoint que agrega KPIs de todos los agentes para el Overview page."""
    result = {}

    # ── Stocks agent ──
    try:
        stocks_session = q_one("SELECT * FROM stocks_sessions ORDER BY started_at DESC LIMIT 1")
        if stocks_session:
            sid = stocks_session['id']
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
                'balance': float(stocks_session.get('balance') or stocks_session.get('initial_balance') or 220),
                'total_pnl': round(float(stats['total_pnl'] or 0), 2),
                'win_rate': round(winners / closed * 100, 1) if closed > 0 else 0,
                'profit_factor': round(gp / gl, 2) if gl > 0 else 0,
                'open_trades': int(stats['open_count'] or 0),
                'total_trades': closed,
                'status': 'active',
            }
    except Exception:
        result['stocks'] = {'status': 'no_data'}

    # ── Crypto agent ──
    try:
        pf = q_one("SELECT * FROM portfolio ORDER BY timestamp DESC LIMIT 1") or {}
        stats = q_one("""
            SELECT
                COUNT(*) FILTER (WHERE status = 'CLOSED') AS total_closed,
                COUNT(*) FILTER (WHERE status = 'CLOSED' AND pnl > 0) AS winners,
                COUNT(*) FILTER (WHERE status = 'OPEN') AS open_count,
                COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED'), 0) AS total_pnl,
                COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED' AND pnl > 0), 0) AS gross_profit,
                COALESCE(ABS(SUM(pnl) FILTER (WHERE status = 'CLOSED' AND pnl < 0)), 0) AS gross_loss
            FROM trades
        """) or {}
        closed = int(stats.get('total_closed') or 0)
        winners = int(stats.get('winners') or 0)
        gp = float(stats.get('gross_profit') or 0)
        gl = float(stats.get('gross_loss') or 0)
        result['crypto'] = {
            'balance': float(pf.get('total_balance') or 0),
            'drawdown_pct': float(pf.get('drawdown_pct') or 0),
            'exposure_pct': float(pf.get('exposure_pct') or 0),
            'total_pnl': round(float(stats.get('total_pnl') or 0), 2),
            'win_rate': round(winners / closed * 100, 1) if closed > 0 else 0,
            'profit_factor': round(gp / gl, 2) if gl > 0 else 0,
            'open_trades': int(stats.get('open_count') or 0),
            'total_trades': closed,
            'status': 'active',
        }
    except Exception:
        result['crypto'] = {'status': 'no_data'}

    # ── Polymarket ──
    try:
        poly = q_one("SELECT * FROM poly_sessions ORDER BY started_at DESC LIMIT 1") or {}
        stats = q_one("""
            SELECT
                COUNT(*) FILTER (WHERE status = 'CLOSED') AS total,
                COUNT(*) FILTER (WHERE status = 'CLOSED' AND pnl > 0) AS winners,
                COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED'), 0) AS total_pnl,
                COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED' AND pnl > 0), 0) AS gross_profit,
                COALESCE(ABS(SUM(pnl) FILTER (WHERE status = 'CLOSED' AND pnl < 0)), 0) AS gross_loss
            FROM poly_positions
        """) or {}
        closed = int(stats.get('total') or 0)
        winners = int(stats.get('winners') or 0)
        gp = float(stats.get('gross_profit') or 0)
        gl = float(stats.get('gross_loss') or 0)
        result['polymarket'] = {
            'balance': float(poly.get('balance') or 0),
            'total_pnl': round(float(stats.get('total_pnl') or 0), 2),
            'win_rate': round(winners / closed * 100, 1) if closed > 0 else 0,
            'profit_factor': round(gp / gl, 2) if gl > 0 else 0,
            'total_trades': closed,
            'status': 'active' if poly else 'no_data',
        }
    except Exception:
        result['polymarket'] = {'status': 'no_data'}

    # ── Options ──
    try:
        opts = q_one("SELECT * FROM options_sessions ORDER BY started_at DESC LIMIT 1") or {}
        stats = q_one("""
            SELECT
                COUNT(*) FILTER (WHERE status = 'CLOSED') AS total,
                COUNT(*) FILTER (WHERE status = 'CLOSED' AND pnl > 0) AS winners,
                COALESCE(SUM(entry_premium_usd) FILTER (WHERE status = 'CLOSED'), 0) AS total_premium,
                COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED'), 0) AS total_pnl
            FROM options_positions
        """) or {}
        closed = int(stats.get('total') or 0)
        winners = int(stats.get('winners') or 0)
        result['options'] = {
            'balance': float(opts.get('balance') or 0),
            'total_premium': round(float(stats.get('total_premium') or 0), 2),
            'total_pnl': round(float(stats.get('total_pnl') or 0), 2),
            'win_rate': round(winners / closed * 100, 1) if closed > 0 else 0,
            'total_trades': closed,
            'status': 'active' if opts else 'no_data',
        }
    except Exception:
        result['options'] = {'status': 'no_data'}

    # ── BTC Direction ──
    try:
        btcd = q_one("""
            SELECT
                COUNT(*) FILTER (WHERE status = 'CLOSED') AS total,
                COUNT(*) FILTER (WHERE status = 'CLOSED' AND pnl > 0) AS winners,
                COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED'), 0) AS total_pnl,
                COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED' AND pnl > 0), 0) AS gross_profit,
                COALESCE(ABS(SUM(pnl) FILTER (WHERE status = 'CLOSED' AND pnl < 0)), 0) AS gross_loss
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
            'total_trades': closed,
            'status': 'active' if closed > 0 else 'no_data',
        }
    except Exception:
        result['btc_direction'] = {'status': 'no_data'}

    return result

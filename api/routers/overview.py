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

    # ── PolySnipe ──
    try:
        snipe_s = q_one("SELECT * FROM snipe_sessions WHERE status='ACTIVE' ORDER BY started_at DESC LIMIT 1")
        if not snipe_s:
            snipe_s = q_one("SELECT * FROM snipe_sessions ORDER BY started_at DESC LIMIT 1")
        if snipe_s:
            snipe_st = q_one("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'CLOSED') AS total,
                    COUNT(*) FILTER (WHERE outcome = 'WIN') AS winners,
                    COUNT(*) FILTER (WHERE status = 'OPEN') AS open_count,
                    COALESCE(SUM(pnl_usdc) FILTER (WHERE status = 'CLOSED'), 0) AS total_pnl
                FROM snipe_trades
            """) or {}
            closed = int(snipe_st.get('total') or 0)
            winners = int(snipe_st.get('winners') or 0)
            result['snipe'] = {
                'session_name': snipe_s['session_name'],
                'balance': round(500.0 + float(snipe_st.get('total_pnl') or 0), 2),
                'initial_balance': 500.0,
                'total_pnl': round(float(snipe_st.get('total_pnl') or 0), 2),
                'win_rate': round(winners / closed * 100, 1) if closed > 0 else 0,
                'open_trades': int(snipe_st.get('open_count') or 0),
                'total_trades': closed,
                'status': snipe_s['status'],
            }
    except Exception:
        result['snipe'] = {'status': 'error'}

    # ── BTC Direction (DEPRECATED) ──
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


@router.get('/consortium')
def consortium():
    """Resumen financiero consolidado del consorcio — KPIs globales."""
    try:
        from api.db import q_one, q

        # Capital total = suma de balances de todos los agentes activos
        capital = 0.0
        rows = []

        # Crypto
        cs = q_one("SELECT * FROM paper_sessions WHERE status='ACTIVE' ORDER BY started_at DESC LIMIT 1")
        if not cs:
            cs = q_one("SELECT * FROM paper_sessions ORDER BY started_at DESC LIMIT 1")
        if cs:
            pf = q_one("SELECT total_balance FROM portfolio ORDER BY timestamp DESC LIMIT 1") or {}
            cb = float(pf.get('total_balance') or cs['initial_balance'] or 0)
            capital += cb
            rows.append(('Crypto', cs['session_name'], cb))

        # Stocks
        ss = q_one("SELECT * FROM stocks_sessions WHERE status='ACTIVE' ORDER BY started_at DESC LIMIT 1")
        if not ss:
            ss = q_one("SELECT * FROM stocks_sessions ORDER BY started_at DESC LIMIT 1")
        if ss:
            sb = float(ss['current_balance'] or ss['initial_balance'] or 0)
            capital += sb
            rows.append(('Stocks', ss['session_name'], sb))

        # Polymarket
        ps = q_one("SELECT * FROM poly_sessions WHERE status='ACTIVE' ORDER BY started_at DESC LIMIT 1")
        if not ps:
            ps = q_one("SELECT * FROM poly_sessions ORDER BY started_at DESC LIMIT 1")
        if ps:
            pb = float(ps['current_balance'] or ps['initial_balance'] or 0)
            capital += pb
            rows.append(('Polymarket', ps['session_name'], pb))

        # Options
        os_ = q_one("SELECT * FROM options_sessions WHERE status='ACTIVE' ORDER BY started_at DESC LIMIT 1")
        if not os_:
            os_ = q_one("SELECT * FROM options_sessions ORDER BY started_at DESC LIMIT 1")
        if os_:
            ob = float(os_['current_balance_usd'] or os_['initial_balance_usd'] or 0)
            capital += ob
            rows.append(('Options', os_['session_name'], ob))

        # PolySnipe
        try:
            ss = q_one("SELECT * FROM snipe_sessions WHERE status='ACTIVE' LIMIT 1")
            if ss:
                snp = q_one("SELECT COALESCE(SUM(pnl_usdc), 0) as pnl FROM snipe_trades WHERE status='CLOSED'") or {}
                sb = 500.0 + float(snp.get('pnl') or 0)
                capital += sb
                rows.append(('PolySnipe', ss['session_name'], sb))
        except Exception:
            pass

        # Grid Stable
        gs_pnl = q_one("SELECT COALESCE(SUM(pnl), 0) as pnl FROM trades WHERE strategy='GRID_STABLE' AND status='CLOSED'") or {}
        gs_bal = 500.0 + float(gs_pnl.get('pnl') or 0)
        capital += gs_bal
        rows.append(('Grid Stable', 'GRID_STABLE', gs_bal))

        # P&L diario (últimas 24h)
        daily = q_one("""
            SELECT COALESCE(SUM(pnl), 0) as pnl FROM trades
            WHERE status='CLOSED' AND timestamp_close >= NOW() - INTERVAL '24 hours'
        """) or {}
        daily_poly = q_one("""
            SELECT COALESCE(SUM(pnl), 0) as pnl FROM poly_positions
            WHERE status='CLOSED' AND timestamp_close >= NOW() - INTERVAL '24 hours'
        """) or {}
        daily_pnl = float(daily.get('pnl') or 0) + float(daily_poly.get('pnl') or 0)

        # DD global
        crypto_dd = q_one("SELECT drawdown_pct FROM portfolio ORDER BY timestamp DESC LIMIT 1") or {}
        dd_pct = float(crypto_dd.get('drawdown_pct') or 0) * 100

        # Agentes activos
        services = q_one("SELECT COUNT(*) as c FROM paper_sessions WHERE status='ACTIVE'") or {}
        active = int(services.get('c') or 0)

        return {
            'capital_total': round(capital, 2),
            'daily_pnl': round(daily_pnl, 2),
            'daily_pnl_pct': round(daily_pnl / capital * 100, 2) if capital > 0 else 0,
            'max_drawdown_pct': round(dd_pct, 1),
            'active_agents': active,
            'allocation': [{'agent': name, 'session': sess, 'balance': bal}
                          for name, sess, bal in rows],
        }
    except Exception as e:
        return {'error': str(e), 'capital_total': 0, 'daily_pnl': 0}


@router.get('/daily-pnl')
def daily_pnl(limit: int = 90):
    """P&L diario consolidado de todos los agentes — para heatmap."""
    rows = q(f"""
        SELECT
            series.date,
            COALESCE(t.pnl, 0) + COALESCE(p.pnl, 0) as pnl
        FROM (
            SELECT generate_series(
                CURRENT_DATE - INTERVAL '{limit} days',
                CURRENT_DATE,
                '1 day'::interval
            )::date as date
        ) series
        LEFT JOIN (
            SELECT DATE(timestamp_close) as dt, SUM(pnl) as pnl
            FROM trades WHERE status='CLOSED'
            GROUP BY dt
        ) t ON series.date = t.dt
        LEFT JOIN (
            SELECT DATE(timestamp_close) as dt, SUM(pnl) as pnl
            FROM poly_positions WHERE status='CLOSED'
            GROUP BY dt
        ) p ON series.date = p.dt
        ORDER BY series.date
    """)
    return [{'date': str(r['date']), 'pnl': round(float(r['pnl'] or 0), 2)} for r in rows]

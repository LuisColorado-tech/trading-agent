"""Router: Overview — resumen de todos los agentes (v2 — session-scoped + fixes)."""
from fastapi import APIRouter, Query
from api.db import q, q_one

router = APIRouter()


@router.get('/')
def overview(scope: str = Query("session", description="session | all")):
    """Un solo endpoint que agrega KPIs de todos los agentes para el Overview page."""
    result = {}

    # ── Stocks agent ──
    try:
        if scope == "session":
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
        else:
            sess = q_one("SELECT * FROM stocks_sessions ORDER BY started_at DESC LIMIT 1") or {}
            sname = sess.get('session_name', 'all')
            stats = q_one("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'CLOSED') AS total_closed,
                    COUNT(*) FILTER (WHERE status = 'CLOSED' AND pnl > 0) AS winners,
                    COUNT(*) FILTER (WHERE status = 'OPEN') AS open_count,
                    COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED'), 0) AS total_pnl,
                    COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED' AND pnl > 0), 0) AS gross_profit,
                    COALESCE(ABS(SUM(pnl) FILTER (WHERE status = 'CLOSED' AND pnl < 0)), 0) AS gross_loss
                FROM stocks_trades
            """) or {}
        if sess:
            closed = int(stats.get('total_closed') or 0)
            winners = int(stats.get('winners') or 0)
            gp = float(stats.get('gross_profit') or 0)
            gl = float(stats.get('gross_loss') or 0)
            result['stocks'] = {
                'session_name': sname,
                'balance': float(sess.get('current_balance') or sess.get('initial_balance') or 220),
                'initial_balance': float(sess.get('initial_balance') or 220),
                'total_pnl': round(float(stats.get('total_pnl') or 0), 2),
                'win_rate': round(winners / closed * 100, 1) if closed > 0 else 0,
                'profit_factor': round(gp / gl, 2) if gl > 0 else 0,
                'open_trades': int(stats.get('open_count') or 0),
                'total_trades': closed,
                'max_drawdown': float(sess.get('max_drawdown') or 0),
                'status': sess.get('status', 'no_data'),
            }
    except Exception:
        result['stocks'] = {'status': 'error'}

    # ── Crypto agent ──
    try:
        if scope == "session":
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
        else:
            sess = q_one("SELECT * FROM paper_sessions ORDER BY started_at DESC LIMIT 1") or {}
            sname = sess.get('session_name', 'all')
            pf = q_one("SELECT * FROM portfolio ORDER BY timestamp DESC LIMIT 1") or {}
            stats = q_one("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'CLOSED' AND close_reason != 'SESSION_CLOSE') AS total_closed,
                    COUNT(*) FILTER (WHERE status = 'CLOSED' AND pnl > 0) AS winners,
                    COUNT(*) FILTER (WHERE status = 'OPEN') AS open_count,
                    COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED'), 0) AS total_pnl,
                    COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED' AND pnl > 0), 0) AS gross_profit,
                    COALESCE(ABS(SUM(pnl) FILTER (WHERE status = 'CLOSED' AND pnl < 0)), 0) AS gross_loss
                FROM trades
            """) or {}
        if sess:
            closed = int(stats.get('total_closed') or 0)
            winners = int(stats.get('winners') or 0)
            gp = float(stats.get('gross_profit') or 0)
            gl = float(stats.get('gross_loss') or 0)
            result['crypto'] = {
                'session_name': sname,
                'balance': float(pf.get('total_balance') or sess.get('initial_balance') or 10000),
                'initial_balance': float(sess.get('initial_balance') or 10000),
                'drawdown_pct': float(pf.get('drawdown_pct') or 0),
                'exposure_pct': float(pf.get('exposure_pct') or 0),
                'total_pnl': round(float(stats.get('total_pnl') or 0), 2),
                'win_rate': round(winners / closed * 100, 1) if closed > 0 else 0,
                'profit_factor': round(gp / gl, 2) if gl > 0 else 0,
                'open_trades': int(stats.get('open_count') or 0),
                'total_trades': closed,
                'max_drawdown': float(sess.get('max_drawdown') or 0),
                'status': sess.get('status', 'no_data'),
            }
    except Exception:
        result['crypto'] = {'status': 'error'}

    # ── Options ──
    try:
        if scope == "session":
            sess = q_one("SELECT * FROM options_sessions WHERE status='ACTIVE' ORDER BY started_at DESC LIMIT 1")
            if not sess:
                sess = q_one("SELECT * FROM options_sessions ORDER BY started_at DESC LIMIT 1")
            if sess:
                sname = sess['session_name']
                stats = q_one("""
                    SELECT
                        COUNT(*) FILTER (WHERE status != 'OPEN') AS total,
                        COUNT(*) FILTER (WHERE status != 'OPEN' AND pnl_usd > 0) AS winners,
                        COUNT(*) FILTER (WHERE status = 'OPEN') AS open_count,
                        COALESCE(SUM(entry_premium_usd) FILTER (WHERE status != 'OPEN'), 0) AS total_premium,
                        COALESCE(SUM(pnl_usd) FILTER (WHERE status != 'OPEN'), 0) AS total_pnl
                    FROM options_positions
                    WHERE opened_at >= :started_at
                """, {'started_at': sess['started_at']}) or {}
        else:
            sess = q_one("SELECT * FROM options_sessions ORDER BY started_at DESC LIMIT 1") or {}
            sname = sess.get('session_name', 'all')
            stats = q_one("""
                SELECT
                    COUNT(*) FILTER (WHERE status != 'OPEN') AS total,
                    COUNT(*) FILTER (WHERE status != 'OPEN' AND pnl_usd > 0) AS winners,
                    COUNT(*) FILTER (WHERE status = 'OPEN') AS open_count,
                    COALESCE(SUM(entry_premium_usd) FILTER (WHERE status != 'OPEN'), 0) AS total_premium,
                    COALESCE(SUM(pnl_usd) FILTER (WHERE status != 'OPEN'), 0) AS total_pnl
                FROM options_positions
            """) or {}
        if sess:
            closed = int(stats.get('total') or 0)
            winners = int(stats.get('winners') or 0)
            result['options'] = {
                'session_name': sname,
                'balance': float(sess.get('current_balance_usd') or sess.get('initial_balance_usd') or 2000),
                'initial_balance': float(sess.get('initial_balance_usd') or 2000),
                'total_premium': round(float(stats.get('total_premium') or 0), 2),
                'total_pnl': round(float(stats.get('total_pnl') or 0), 2),
                'win_rate': round(winners / closed * 100, 1) if closed > 0 else 0,
                'open_trades': int(stats.get('open_count') or 0),
                'total_trades': closed,
                'status': sess.get('status', 'no_data'),
            }
    except Exception:
        result['options'] = {'status': 'error'}

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

        # Options
        os_ = q_one("SELECT * FROM options_sessions WHERE status='ACTIVE' ORDER BY started_at DESC LIMIT 1")
        if not os_:
            os_ = q_one("SELECT * FROM options_sessions ORDER BY started_at DESC LIMIT 1")
        if os_:
            ob = float(os_['current_balance_usd'] or os_['initial_balance_usd'] or 0)
            capital += ob
            rows.append(('Options', os_['session_name'], ob))

        # Grid Stable
        gs_pnl = q_one("SELECT COALESCE(SUM(pnl), 0) as pnl FROM trades WHERE strategy='GRID_STABLE' AND status='CLOSED'") or {}
        gs_bal = 500.0 + float(gs_pnl.get('pnl') or 0)
        capital += gs_bal
        rows.append(('Grid Stable', 'GRID_STABLE', gs_bal))

        # Pairs Trading
        pairs_pnl = q_one("SELECT COALESCE(SUM(pnl), 0) as pnl FROM trades WHERE strategy='PAIRS_TRADING' AND status='CLOSED'") or {}
        pairs_bal = 500.0 + float(pairs_pnl.get('pnl') or 0)
        capital += pairs_bal
        rows.append(('Pairs Trading', 'PAIRS_TRADING', pairs_bal))

        # P&L diario (últimas 24h) — todas las fuentes
        daily = q_one("""
            SELECT COALESCE(SUM(pnl), 0) as pnl FROM trades
            WHERE status='CLOSED' AND timestamp_close >= NOW() - INTERVAL '24 hours'
        """) or {}
        daily_options = q_one("""
            SELECT COALESCE(SUM(pnl_usd), 0) as pnl FROM options_positions
            WHERE status = 'CLOSED_MANUAL' AND closed_at >= NOW() - INTERVAL '24 hours'
        """) or {}
        daily_pnl = (
            float(daily.get('pnl') or 0) +
            float(daily_options.get('pnl') or 0)
        )

        # DD global: usar el mayor DD de todas las fuentes
        crypto_dd = q_one("SELECT COALESCE(MAX(COALESCE(drawdown_pct, 0)), 0) as dd FROM portfolio") or {}
        stocks_dd = q_one("SELECT COALESCE(MAX(COALESCE(max_drawdown, 0)), 0) as dd FROM stocks_sessions") or {}
        options_dd = q_one("SELECT COALESCE(MAX(COALESCE(max_drawdown_pct, 0)), 0) as dd FROM options_sessions") or {}
        dd_pct = max(
            float(crypto_dd.get('dd') or 0) * 100,
            float(stocks_dd.get('dd') or 0),
            float(options_dd.get('dd') or 0),
        )

        # Agentes activos: contar TODAS las sesiones activas
        active = 0
        for tbl in ['paper_sessions', 'stocks_sessions', 'options_sessions']:
            try:
                c = q_one(f"SELECT COUNT(*) as c FROM {tbl} WHERE status='ACTIVE'") or {}
                active += int(c.get('c') or 0)
            except Exception:
                pass
        # Grid stable + Pairs siempre activos
        active = max(active, len(rows))

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


@router.get('/risk')
def risk_metrics():
    """Métricas de riesgo: Sharpe, Sortino, VaR, MaxDD, returns mensuales."""
    pnl_rows = q("""
        SELECT DATE(timestamp_close) as dt, SUM(pnl) as pnl
        FROM trades WHERE status='CLOSED'
        GROUP BY dt ORDER BY dt
    """)
    if not pnl_rows:
        return {'error': 'no_data'}

    import numpy as np
    daily_returns = [float(r['pnl']) for r in pnl_rows]
    if len(daily_returns) < 30:
        return {'error': 'insufficient_data', 'days': len(daily_returns)}

    arr = np.array(daily_returns)
    total_return = round(float(arr.sum()), 2)
    mean_daily = float(arr.mean())
    std_daily = float(arr.std())

    # Sharpe ratio (risk-free = 0, annualized 252 days)
    sharpe = round((mean_daily / std_daily * np.sqrt(252)) if std_daily > 0 else 0, 2)

    # Sortino ratio
    neg = arr[arr < 0]
    downside_std = float(neg.std()) if len(neg) > 0 else 0
    sortino = round((mean_daily / downside_std * np.sqrt(252)) if downside_std > 0 else 0, 2)

    # VaR 95% (historical)
    var_95 = round(float(np.percentile(arr, 5)), 2)

    # Max drawdown
    cumulative = np.cumsum(arr)
    peak = np.maximum.accumulate(cumulative)
    dd = cumulative - peak
    max_dd = round(float(dd.min()), 2)
    max_dd_pct = round(float(dd.min() / abs(peak.max())) * 100 if peak.max() > 0 else 0, 2)

    # Daily return stats
    win_days = int((arr > 0).sum())
    loss_days = int((arr < 0).sum())
    wr_daily = round(win_days / len(arr) * 100, 1) if len(arr) > 0 else 0
    avg_win = round(float(arr[arr > 0].mean()), 2) if win_days > 0 else 0
    avg_loss = round(float(arr[arr < 0].mean()), 2) if loss_days > 0 else 0

    # Monthly returns
    monthly = q("""
        SELECT DATE_TRUNC('month', timestamp_close) as month, SUM(pnl) as pnl
        FROM trades WHERE status='CLOSED'
        GROUP BY month ORDER BY month DESC LIMIT 12
    """)
    monthly_returns = [
        {'month': str(r['month'])[:7], 'pnl': round(float(r['pnl'] or 0), 2)}
        for r in monthly
    ]

    return {
        'sharpe': sharpe,
        'sortino': sortino,
        'var_95': var_95,
        'max_drawdown': max_dd,
        'max_drawdown_pct': max_dd_pct,
        'total_return': total_return,
        'mean_daily': round(mean_daily, 2),
        'std_daily': round(std_daily, 2),
        'win_days': win_days,
        'loss_days': loss_days,
        'wr_daily': wr_daily,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'monthly_returns': monthly_returns,
        'days': len(daily_returns),
    }

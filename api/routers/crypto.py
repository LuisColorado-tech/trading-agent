"""Router: agente crypto (Kraken — paper session manager)."""
from fastapi import APIRouter, Query
from api.db import q, q_one

router = APIRouter()


@router.get('/portfolio')
def get_portfolio():
    """Último snapshot de portfolio."""
    return q_one("SELECT * FROM portfolio ORDER BY timestamp DESC LIMIT 1") or {}


@router.get('/portfolio/history')
def get_portfolio_history(limit: int = 500):
    return q("""
        SELECT timestamp, total_balance, peak_balance, drawdown_pct, exposure_pct
        FROM portfolio ORDER BY timestamp ASC LIMIT :limit
    """, {'limit': limit})


@router.get('/trades')
def get_trades(limit: int = 200, asset: str = None, status: str = None):
    filters = ['1=1']
    params = {'limit': limit}
    if asset:
        filters.append('asset = :asset')
        params['asset'] = asset.upper()
    if status:
        filters.append('status = :status')
        params['status'] = status.upper()
    where = ' AND '.join(filters)
    return q(f"""
        SELECT * FROM trades WHERE {where}
        ORDER BY timestamp_open DESC LIMIT :limit
    """, params)


@router.get('/trades/stats')
def trade_stats():
    row = q_one("""
        SELECT
            COUNT(*) FILTER (WHERE status = 'CLOSED') AS total_closed,
            COUNT(*) FILTER (WHERE status = 'OPEN') AS open_count,
            COUNT(*) FILTER (WHERE status = 'CLOSED' AND pnl > 0) AS winners,
            COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED'), 0) AS total_pnl,
            COALESCE(SUM(pnl) FILTER (WHERE status = 'CLOSED' AND pnl > 0), 0) AS gross_profit,
            COALESCE(ABS(SUM(pnl) FILTER (WHERE status = 'CLOSED' AND pnl < 0)), 0) AS gross_loss
        FROM trades
    """)
    closed = int(row['total_closed'] or 0)
    winners = int(row['winners'] or 0)
    gp = float(row['gross_profit'] or 0)
    gl = float(row['gross_loss'] or 0)
    return {
        **row,
        'win_rate': round(winners / closed * 100, 1) if closed > 0 else 0,
        'profit_factor': round(gp / gl, 2) if gl > 0 else 0,
        'total_pnl': round(float(row['total_pnl'] or 0), 2),
    }


@router.get('/signals')
def get_signals(limit: int = 100, asset: str = None):
    params = {'limit': limit}
    where = '1=1'
    if asset:
        where = 'asset = :asset'
        params['asset'] = asset.upper()
    return q(f"""
        SELECT * FROM signals WHERE {where}
        ORDER BY timestamp DESC LIMIT :limit
    """, params)


@router.get('/signals/heatmap')
def signals_heatmap():
    """Conteo de señales por asset × tipo para heatmap."""
    return q("""
        SELECT asset, signal_type, COUNT(*) AS count
        FROM signals
        GROUP BY asset, signal_type
        ORDER BY count DESC
    """)


@router.get('/ai')
def get_ai_explanations(limit: int = 50):
    return q("""
        SELECT * FROM claude_explanations
        ORDER BY timestamp DESC LIMIT :limit
    """, {'limit': limit})


@router.get('/stats/daily-pnl')
def daily_pnl():
    return q("""
        SELECT DATE(timestamp_close) AS day, SUM(pnl) AS pnl, COUNT(*) AS trades
        FROM trades
        WHERE status = 'CLOSED' AND timestamp_close IS NOT NULL
        GROUP BY DATE(timestamp_close)
        ORDER BY day ASC
    """)


# ── Por estrategia ──────────────────────────────────────────────

@router.get('/trades/by-strategy')
def get_trades_by_strategy(strategy: str = Query(None), limit: int = 200):
    """Trades filtrados por estrategia (TREND_MOMENTUM, GRID_BOT, GRID_STABLE)."""
    if strategy:
        return q("""
            SELECT * FROM trades WHERE strategy = :s AND paper_trade = true
            ORDER BY timestamp_open DESC LIMIT :limit
        """, {'s': strategy, 'limit': limit})
    return q("""
        SELECT * FROM trades WHERE paper_trade = true
        ORDER BY timestamp_open DESC LIMIT :limit
    """, {'limit': limit})


@router.get('/stats/by-strategy')
def stats_by_strategy():
    """KPIs por estrategia dentro del agente crypto (excluye GRID_STABLE que es servicio aparte)."""
    strategies = ['TREND_MOMENTUM', 'GRID_BOT']
    result = {}
    for s in strategies:
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
            FROM trades WHERE strategy = :s
        """, {'s': s})
        if row:
            closed = int(row['total_closed'] or 0)
            winners = int(row['winners'] or 0)
            gp = float(row['gross_profit'] or 0)
            gl = float(row['gross_loss'] or 0)
            result[s] = {
                'strategy': s,
                'total_trades': closed,
                'open_trades': int(row['open_count'] or 0),
                'winners': winners,
                'win_rate': round(winners / closed * 100, 1) if closed > 0 else 0,
                'profit_factor': round(gp / gl, 2) if gl > 0 else 0,
                'total_pnl': round(float(row['total_pnl'] or 0), 2),
                'avg_win': round(float(row['avg_win'] or 0), 2),
                'avg_loss': round(float(row['avg_loss'] or 0), 2),
            }
    return result


@router.get('/stats/by-asset')
def stats_by_asset(limit: int = 20):
    """KPIs por asset dentro de todas las estrategias crypto + grid."""
    return q("""
        SELECT asset, strategy, COUNT(*) as trades,
               COUNT(*) FILTER (WHERE pnl > 0) as wins,
               SUM(pnl) as total_pnl,
               ROUND((COUNT(*) FILTER (WHERE pnl > 0)::numeric / NULLIF(COUNT(*),0))*100, 1) as wr
        FROM trades WHERE status = 'CLOSED' AND paper_trade = true
        GROUP BY asset, strategy
        ORDER BY total_pnl DESC LIMIT :limit
    """, {'limit': limit})

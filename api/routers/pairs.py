"""
Router: Pairs Trading — consulta de trades y estado del agente.
"""
from fastapi import APIRouter, Query
from api.db import q, q_one

router = APIRouter()


@router.get('/session')
def pairs_session():
    """Estado actual y stats del Pairs Trading agent."""
    stats = q_one("""
        SELECT
            COUNT(*) as total_trades,
            COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), 0) as winning_trades,
            COALESCE(SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END), 0) as losing_trades,
            ROUND(COALESCE(SUM(pnl), 0), 2) as total_pnl,
            ROUND(COALESCE(AVG(CASE WHEN pnl > 0 THEN pnl END), 0), 2) as avg_win,
            ROUND(COALESCE(AVG(CASE WHEN pnl <= 0 THEN pnl END), 0), 2) as avg_loss
        FROM trades WHERE strategy = 'PAIRS_TRADING' AND status = 'CLOSED'
    """)

    open_trades = q("""
        SELECT asset, side, ROUND(entry_price, 4) as entry_price,
               ROUND(position_size, 4) as size, timestamp_open
        FROM trades WHERE strategy = 'PAIRS_TRADING' AND status = 'OPEN'
        ORDER BY timestamp_open DESC
    """)

    recent = q("""
        SELECT asset, side, ROUND(entry_price, 4) as entry_price,
               ROUND(exit_price, 4) as exit_price,
               ROUND(pnl, 2) as pnl, ROUND(pnl_pct, 2) as pnl_pct,
               close_reason, timestamp_close
        FROM trades WHERE strategy = 'PAIRS_TRADING' AND status = 'CLOSED'
        ORDER BY timestamp_close DESC LIMIT 20
    """)

    if not stats:
        return {'error': 'no_data'}

    total = int(stats['total_trades'] or 0)
    wins = int(stats['winning_trades'] or 0)
    return {
        'strategy': 'PAIRS_TRADING',
        'status': 'ACTIVE',
        'total_trades': total,
        'winning_trades': wins,
        'losing_trades': int(stats['losing_trades'] or 0),
        'win_rate': round(wins / total * 100, 1) if total > 0 else 0,
        'total_pnl': float(stats['total_pnl'] or 0),
        'avg_win': float(stats['avg_win'] or 0),
        'avg_loss': float(stats['avg_loss'] or 0),
        'profit_factor': round(
            float(stats['avg_win'] or 0) / abs(float(stats['avg_loss'] or 1))
            if float(stats['avg_loss'] or 0) != 0 else 0, 2
        ),
        'open_trades': len(open_trades),
        'open_positions': [dict(r) for r in open_trades],
        'recent_trades': [{
            'asset': r['asset'], 'side': r['side'],
            'entry_price': float(r['entry_price']),
            'exit_price': float(r['exit_price']),
            'pnl': float(r['pnl']), 'pnl_pct': float(r['pnl_pct']),
            'close_reason': r['close_reason'],
            'timestamp_close': str(r['timestamp_close']),
        } for r in recent],
    }

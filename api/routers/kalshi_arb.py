"""Router: Kalshi Arbitrage — señales y estadísticas."""
from fastapi import APIRouter, Query
from api.db import q, q_one

router = APIRouter()


@router.get('/signals')
def kalshi_signals(limit: int = Query(20, description='Número de señales')):
    rows = q("""
        SELECT strategy, poly_token, poly_price, kalshi_side, kalshi_price,
               total_cost, profit_per_unit, profit_pct, timestamp
        FROM kalshi_arbitrage ORDER BY timestamp DESC LIMIT :limit
    """, {'limit': limit})
    return [{
        'strategy': r.get('strategy'),
        'poly_token': r.get('poly_token'),
        'poly_price': float(r.get('poly_price', 0) or 0),
        'kalshi_side': r.get('kalshi_side'),
        'kalshi_price': float(r.get('kalshi_price', 0) or 0),
        'total_cost': float(r.get('total_cost', 0) or 0),
        'profit_per_unit': float(r.get('profit_per_unit', 0) or 0),
        'profit_pct': float(r.get('profit_pct', 0) or 0),
        'timestamp': str(r.get('timestamp')),
    } for r in rows]


@router.get('/stats')
def kalshi_stats():
    row = q_one("""
        SELECT COUNT(*) as n, COALESCE(SUM(profit_per_unit), 0) as profit,
               COALESCE(AVG(profit_pct), 0) as avg_pct
        FROM kalshi_arbitrage WHERE timestamp > NOW() - INTERVAL '24 hours'
    """)
    if not row:
        return {'signals_24h': 0, 'profit_24h': 0, 'avg_profit_pct': 0, 'capital': 500}
    n = int(row.get('n', 0) or 0)
    profit = float(row.get('profit', 0) or 0)
    avg = float(row.get('avg_pct', 0) or 0)
    return {
        'signals_24h': n,
        'profit_24h': profit,
        'avg_profit_pct': avg,
        'capital': 500,
    }

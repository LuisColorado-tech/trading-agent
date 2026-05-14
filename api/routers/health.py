"""Router: Agent Health — métricas mínimas y semáforos."""
from fastapi import APIRouter, Query
from api.db import q

router = APIRouter()

@router.get('/health')
def agent_health(days: int = Query(7, description='Ventana en días')):
    """Semáforos de salud por agente (PF, WR, trades, DD)."""
    try:
        import psycopg2
        import os
        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            port=int(os.getenv('POSTGRES_PORT', '5432')),
            dbname=os.getenv('POSTGRES_DB', 'trading_agent'),
            user=os.getenv('POSTGRES_USER', 'trading'),
            password=os.getenv('POSTGRES_PASSWORD', 'Tr4d1ng_Ag3nt_2026!'),
            connect_timeout=5,
        )
        from core.agent_health import get_all_agents_health
        results = get_all_agents_health(conn, days)
        conn.close()
        return {'agents': results, 'window_days': days, 'timestamp': __import__('datetime').datetime.now().isoformat()}
    except Exception as e:
        return {'error': str(e)[:200]}


@router.get('/health-summary')
def health_summary(days: int = Query(7, description='Ventana en días')):
    """Resumen compacto para el dashboard overview."""
    try:
        import psycopg2
        import os
        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            port=int(os.getenv('POSTGRES_PORT', '5432')),
            dbname=os.getenv('POSTGRES_DB', 'trading_agent'),
            user=os.getenv('POSTGRES_USER', 'trading'),
            password=os.getenv('POSTGRES_PASSWORD', 'Tr4d1ng_Ag3nt_2026!'),
            connect_timeout=5,
        )
        from core.agent_health import get_all_agents_health
        results = get_all_agents_health(conn, days)
        conn.close()

        green = sum(1 for r in results if r['emoji'] == '🟢')
        yellow = sum(1 for r in results if r['emoji'] == '🟡')
        red = sum(1 for r in results if r['emoji'] == '🔴')
        critical = [r['agent'] for r in results if r['emoji'] in ('🔴', '🟡')]

        return {
            'total': len(results),
            'green': green,
            'yellow': yellow,
            'red': red,
            'summary': f'{green}🟢 {yellow}🟡 {red}🔴',
            'critical_agents': critical,
            'agents': [{ 'agent': r['agent'], 'emoji': r['emoji'], 'passing': r['passing'],
                        'pf': r['pf'], 'wr': r['wr'], 'trades': r['n_trades'], 'dd': r['dd_pct'] }
                      for r in results],
            'window_days': days,
        }
    except Exception as e:
        return {'error': str(e)[:200]}

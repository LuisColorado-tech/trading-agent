#!/usr/bin/env python3
"""Health check v2 — Funding Rate Arbitrage Agent."""
import os, sys, subprocess
from datetime import datetime, timezone

sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')

import psycopg2

DB_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'port': int(os.getenv('POSTGRES_PORT', '5432')),
    'user': os.getenv('POSTGRES_USER'),
    'password': os.getenv('POSTGRES_PASSWORD'),
    'dbname': os.getenv('POSTGRES_DB', 'trading_agent'),
    'connect_timeout': 5,
}

def _query(conn, sql):
    try:
        cur = conn.cursor()
        cur.execute(sql)
        return cur.fetchone()
    except:
        return None

def check_service():
    r = subprocess.run(['systemctl', 'is-active', 'funding-agent'], capture_output=True, text=True)
    if r.stdout.strip() == 'active':
        return True, 'funding-agent activo'
    return False, 'funding-agent INACTIVO'

def check_db():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        row = _query(conn, "SELECT COUNT(*) FROM funding_sessions WHERE status='ACTIVE'")
        conn.close()
        n = int(row[0]) if row else 0
        return True, f'DB OK | {n} posiciones activas'
    except Exception as e:
        return False, f'DB error: {str(e)[:60]}'

def check_funding():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        row = _query(conn, "SELECT COALESCE(SUM(funding_earned_usd),0) FROM funding_events WHERE timestamp > NOW() - INTERVAL '24 hours'")
        conn.close()
        earned = float(row[0]) if row else 0
        return True, f'Funding 24h: ${earned:.4f}'
    except Exception as e:
        return False, f'Funding error: {str(e)[:60]}'

def check_portfolio():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        row = _query(conn, "SELECT total_balance, available_cash FROM portfolio_v2 ORDER BY timestamp DESC LIMIT 1")
        conn.close()
        if row:
            bal, cash = float(row[0]), float(row[1])
            return True, f'Balance: ${bal:,.2f} | Cash: ${cash:,.2f}'
        return True, 'Portfolio OK'
    except Exception as e:
        return False, f'Portfolio error: {str(e)[:60]}'

def check_logs():
    import datetime as dt_mod
    since = (datetime.now(timezone.utc) - dt_mod.timedelta(minutes=15)).strftime('%H:%M:%S')
    r = subprocess.run(['journalctl', '-u', 'funding-agent', '--since', since,
                        '--no-pager'], capture_output=True, text=True, timeout=10)
    errors = r.stdout.count('ERROR')
    if errors == 0:
        return True, 'Sin errores en logs'
    return False, f'{errors} errores en logs'

checks = [
    ('Servicio', check_service),
    ('DB', check_db),
    ('Funding', check_funding),
    ('Portfolio', check_portfolio),
    ('Logs', check_logs),
]

passed = 0
failed = 0
for name, fn in checks:
    ok, msg = fn()
    tag = '✓' if ok else '✗'
    print(f'  {tag} {name}: {msg}')
    if ok: passed += 1
    else: failed += 1

print(f'\n[{datetime.now().strftime("%H:%M:%S")}] Health check: {"PASS" if failed == 0 else "FAIL"} ({passed}/{len(checks)} passed)')

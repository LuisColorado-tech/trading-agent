#!/usr/bin/env python3
"""Funding report — sends summary to Telegram every 6h."""
import os, sys, json, urllib.request
from datetime import datetime, timezone

sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')

import psycopg2

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

if not TOKEN or not CHAT_ID:
    print('Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID')
    sys.exit(1)

DB_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'port': int(os.getenv('POSTGRES_PORT', '5432')),
    'user': os.getenv('POSTGRES_USER'),
    'password': os.getenv('POSTGRES_PASSWORD'),
    'dbname': os.getenv('POSTGRES_DB', 'trading_agent'),
    'connect_timeout': 5,
}

def send_telegram(text):
    url = f'https://api.telegram.org/bot{TOKEN}/sendMessage'
    data = json.dumps({'chat_id': CHAT_ID, 'text': text, 'parse_mode': 'HTML'}).encode()
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    urllib.request.urlopen(req, timeout=10)

conn = psycopg2.connect(**DB_CONFIG)
cur = conn.cursor()

# Active positions
cur.execute("""
    SELECT pair, capital_usd, ROUND(entry_funding_annual*100,1) as annual,
           ROUND(total_funding_earned::numeric,4) as earned, 
           ROUND(total_fees_paid::numeric,4) as fees
    FROM funding_sessions WHERE status='ACTIVE'
    ORDER BY pair
""")
positions = cur.fetchall()

# 24h funding
cur.execute("""
    SELECT COALESCE(SUM(funding_earned_usd),0) 
    FROM funding_events WHERE timestamp > NOW() - INTERVAL '24 hours'
""")
earned_24h = float(cur.fetchone()[0])

# Portfolio
cur.execute("SELECT total_balance, available_cash FROM portfolio_v2 ORDER BY timestamp DESC LIMIT 1")
row = cur.fetchone()
balance, cash = float(row[0]), float(row[1]) if row else (5500.0, 5500.0)

# Active count
cur.execute("SELECT COUNT(*) FROM funding_sessions WHERE status='ACTIVE'")
n_active = cur.fetchone()[0]

cur.close()
conn.close()

# Agent errors last 6h
import subprocess
r = subprocess.run(['journalctl', '-u', 'funding-agent', '--since', '6 hours ago', '--no-pager'],
                   capture_output=True, text=True, timeout=10)
errors = r.stdout.count('ERROR')

now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

msg = f'<b>🤖 Funding Agent — {now}</b>\n\n'
msg += f'<b>Posiciones activas: {n_active}</b>\n'

for p in positions:
    pair, cap, annual, earned, fees = p[0], float(p[1]), p[2], float(p[3]), float(p[4])
    net = earned - fees
    tag = '🟢' if net >= 0 else '🔴'
    msg += f'{tag} <b>{pair}</b>: ${cap:.0f} | {annual:.1f}%/yr | +${earned:.4f} | net ${net:+.4f}\n'

msg += f'\n<b>24h funding earned:</b> ${earned_24h:.4f}\n'
msg += f'<b>Balance:</b> ${balance:,.2f} | <b>Available:</b> ${cash:,.2f}\n'
msg += f'<b>Errors (6h):</b> {errors}\n'
msg += f'\n<i>Next report in 6h</i>'

send_telegram(msg)
print(f'Report sent: {n_active} positions, ${earned_24h:.4f} earned/24h')

#!/usr/bin/env python3
"""
TM Pulse — Diagnóstico rápido de TrendMomentum.
Ejecutar cuando TM no está operando.

Uso: cd /opt/trading && venv/bin/python3 scripts/tm_pulse.py
"""
import os, sys, subprocess, json
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')
db_url = f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT')}/{os.getenv('POSTGRES_DB')}"
from sqlalchemy import create_engine, text
e = create_engine(db_url)

def pnl(x):
    try: return float(x)
    except: return 0.0

now = datetime.now(timezone.utc)
print(f"🫀 TM PULSE — {now.strftime('%Y-%m-%d %H:%M UTC')}")
print("=" * 60)

# 1. TRADES RECIENTES
s = e.connect().execute(text("SELECT started_at FROM paper_sessions WHERE status='ACTIVE' LIMIT 1")).fetchone()
tm_closed = e.connect().execute(text(
    "SELECT COUNT(*), ROUND(SUM(pnl)::numeric,2) FROM trades "
    "WHERE strategy='TREND_MOMENTUM' AND status='CLOSED' AND timestamp_open >= :s"
), {'s': s[0]}).fetchone()
tm_open = e.connect().execute(text(
    "SELECT COUNT(*) FROM trades WHERE strategy='TREND_MOMENTUM' AND status='OPEN'"
)).fetchone()[0]

print(f"\n1. TRADES SESSION_011")
print(f"   TM cerrados: {tm_closed[0]} | PnL: ${pnl(tm_closed[1]):,.2f}")
print(f"   TM abiertos: {tm_open}")
print(f"   Último cierre: ", end="")
r = e.connect().execute(text(
    "SELECT asset, ROUND(pnl::numeric,2), close_reason, timestamp_close "
    "FROM trades WHERE strategy='TREND_MOMENTUM' AND status='CLOSED' "
    "ORDER BY timestamp_close DESC LIMIT 1"
)).fetchone()
if r:
    print(f"{r[0]} ${pnl(r[1]):,.2f} {r[2]} {str(r[3])[:19]}")
else:
    print("NUNCA")

# 2. SEÑALES (últimos 15 min)
print(f"\n2. SEÑALES (últimos 15 min)")
signals = subprocess.run(
    'journalctl -u trading-agent --since "15 min ago" --no-pager 2>/dev/null | grep "Opportunity:" | sed "s/.*Opportunity: //" | sort | uniq -c | sort -rn | head -5',
    shell=True, capture_output=True, text=True, timeout=10
)
print(f"   {signals.stdout.strip() if signals.stdout else '   NINGUNA — TM no encuentra señales'}")

# 3. BLOQUEOS (últimos 15 min) — THIS IS THE KEY CHECK
print(f"\n3. BLOQUEOS — ¿qué frena las señales?")
blocks = subprocess.run(
    'journalctl -u trading-agent --since "15 min ago" --no-pager 2>/dev/null | grep -E "REJECTED.*TREND_MOMENTUM|low_confluence.*TREND|CHOPPY.*inactivo|INSUFFICIENT_CASH|MAX_CONCURRENT_TREND|cooldown.*TREND" | tail -5',
    shell=True, capture_output=True, text=True, timeout=10
)
if blocks.stdout.strip():
    # Count block reasons
    reasons = {}
    for line in blocks.stdout.strip().split('\n'):
        if 'REJECTED:' in line:
            reason = line.split('REJECTED:')[1].split(':')[0].strip() if ':' in line.split('REJECTED:')[1] else line.split('REJECTED:')[1].strip()
            # Clean up
            reason = reason.split(' ')[0] if ' ' in reason else reason
            reasons[reason] = reasons.get(reason, 0) + 1
        elif 'CHOPPY' in line:
            reasons['CHOPPY'] = reasons.get('CHOPPY', 0) + 1
        elif 'low_confluence' in line:
            reasons['low_confluence'] = reasons.get('low_confluence', 0) + 1
    
    # Mostrar resumen de bloqueos
    shown = set()
    for line in blocks.stdout.strip().split('\n')[-8:]:
        # Extract key info
        if 'REJECTED:' in line:
            parts = line.split('REJECTED:')[1].strip()
            if parts not in shown:
                print(f"   ❌ {parts[:80]}")
                shown.add(parts)
    if not shown:
        for line in blocks.stdout.strip().split('\n')[-3:]:
            print(f"   {line[line.find('No opportunity'):][:100] if 'No opportunity' in line else line[-120:]}")
else:
    print("   ✅ Sin bloqueos visibles — señales deberían ejecutarse")

# 4. PORTFOLIO
r = e.connect().execute(text(
    "SELECT total_balance, available_cash, exposure_pct, drawdown_pct FROM portfolio ORDER BY timestamp DESC LIMIT 1"
)).fetchone()
print(f"\n4. PORTFOLIO")
print(f"   Balance: ${pnl(r[0]):,.2f}")
print(f"   Available cash: ${pnl(r[1]):,.2f}")
print(f"   Exposure: {pnl(r[2])*100:.1f}%")
print(f"   DD: {pnl(r[3])*100:.1f}%")

if pnl(r[1]) < 10:
    print(f"   ⚠️ AVAILABLE CASH MUY BAJO — posible causa de INSUFFICIENT_CASH")

# 5. COOLDOWNS
import redis as redis_lib
rt = redis_lib.Redis(host='localhost', port=6379, decode_responses=True)
cooldowns = list(rt.scan_iter('cooldown:*'))
print(f"\n5. COOLDOWNS")
if cooldowns:
    for k in cooldowns:
        ttl = rt.ttl(k)
        print(f"   {k.decode() if isinstance(k, bytes) else k}: {ttl//60}min restantes")
else:
    print(f"   Ninguno")

# 6. DIRECTION GUARD
blocked_crypto = list(rt.scan_iter('direction_guard_crypto:*'))
print(f"\n6. DIRECTION GUARD (crypto)")
if blocked_crypto:
    for k in blocked_crypto:
        v = rt.get(k)
        print(f"   {k.decode() if isinstance(k, bytes) else k}: {v}")
else:
    print(f"   Sin bloqueos")

# ── VEREDICT ──
print(f"\n{'='*60}")
print(f"DIAGNÓSTICO:")
issues = []
if tm_open == 0 and (signals.stdout.strip() == '' or 'NINGUNA' in signals.stdout):
    issues.append("TM no encuentra señales → posible CHOPPY")
if blocks.stdout.strip():
    if 'INSUFFICIENT_CASH' in blocks.stdout:
        issues.append("INSUFFICIENT_CASH → revisar available_cash")
    if 'CHOPPY' in blocks.stdout:
        issues.append("CHOPPY bloqueando → revisar régimen")
    if 'low_confluence' in blocks.stdout:
        issues.append("Confluencia insuficiente")
    if 'COOLDOWN' in blocks.stdout or 'cooldown' in blocks.stdout:
        issues.append("Cooldown activo → esperar")
if pnl(r[1]) < 10:
    issues.append("Available cash negativo → GRID_BOT consumiendo presupuesto")

if not issues:
    print("✅ TM debería estar operando normalmente")
else:
    for i, issue in enumerate(issues, 1):
        print(f"  {i}. {issue}")

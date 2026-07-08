#!/usr/bin/env python3
"""
Spec Runner — Verifica que el sistema cumple con sus SPECs.

Ejecuta todos los checks definidos en /opt/trading/specs/
Compara realidad vs especificación.
Retorna 0 si todo OK, 1 si hay violaciones.

Uso: venv/bin/python3 scripts/spec_check.py
     venv/bin/python3 scripts/spec_check.py --agent trend_momentum
     venv/bin/python3 scripts/spec_check.py --agent stocks
"""
import os, sys, subprocess, argparse
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')
db_url = f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT')}/{os.getenv('POSTGRES_DB')}"
from sqlalchemy import create_engine, text
e = create_engine(db_url)

now = datetime.now(timezone.utc)

def pnl(x):
    try: return float(x)
    except: return 0.0

def check(name, fn):
    """Ejecuta un check. Retorna (ok, message)."""
    try:
        return fn()
    except Exception as ex:
        return False, f"CRASH: {ex}"

def run_shell(cmd, timeout=10):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return int(r.stdout.strip() or 0)

# ── TM CHECKS ─────────────────────────────────────────────────────────────

def tm_signals_present():
    n = run_shell('journalctl -u trading-agent --since "2 hours ago" --no-pager 2>/dev/null | grep -c "Opportunity:"')
    return n > 0, f"{n} señales en 2h"

def tm_executing():
    n = run_shell('journalctl -u trading-agent --since "2 hours ago" --no-pager 2>/dev/null | grep -c "Executed trade:"')
    return n > 0, f"{n} ejecuciones en 2h"

def tm_not_blocked():
    """Detecta si TM está bloqueado por INSUFFICIENT_CASH u otros."""
    r = subprocess.run(
        'journalctl -u trading-agent --since "30 min ago" --no-pager 2>/dev/null | grep "REJECTED:" | awk -F"REJECTED: " "{print \$2}" | cut -d":" -f1 | sort | uniq -c | sort -rn',
        shell=True, capture_output=True, text=True, timeout=10
    )
    if r.stdout.strip():
        lines = r.stdout.strip().split('\n')[:3]
        return False, f"Rechazos: {' | '.join(l.strip() for l in lines)}"
    return True, "Sin rechazos"

def tm_available_cash():
    r = e.connect().execute(text(
        "SELECT available_cash FROM portfolio ORDER BY timestamp DESC LIMIT 1"
    )).fetchone()
    cash = pnl(r[0])
    return cash >= 10, f"Available cash: ${cash:,.2f}"

def tm_dd_ok():
    r = e.connect().execute(text(
        "SELECT drawdown_pct FROM portfolio ORDER BY timestamp DESC LIMIT 1"
    )).fetchone()
    dd = pnl(r[0]) * 100
    return dd < 10, f"DD: {dd:.1f}%"

def tm_open_trades():
    r = e.connect().execute(text(
        "SELECT COUNT(*) FROM trades WHERE strategy='TREND_MOMENTUM' AND status='OPEN'"
    )).fetchone()
    n = r[0]
    return True, f"{n} trades abiertos"

def tm_trades_today():
    r = e.connect().execute(text(
        "SELECT COUNT(*), ROUND(SUM(pnl)::numeric,2) FROM trades "
        "WHERE strategy='TREND_MOMENTUM' AND status='CLOSED' AND timestamp_close::date = CURRENT_DATE"
    )).fetchone()
    return True, f"{r[0]} trades hoy, PnL=${pnl(r[1]):,.2f}"

# ── STOCKS CHECKS ─────────────────────────────────────────────────────────

def stocks_feed_fresh():
    n = run_shell('journalctl -u stocks-agent --since "30 min ago" --no-pager 2>/dev/null | grep -c "STOCKS FEED: stale"')
    return n < 5, f"{n} warnings de stale en 30 min"

def stocks_no_loops():
    r = e.connect().execute(text(
        "SELECT COUNT(*) FROM (SELECT symbol, entry_price, COUNT(*) as cnt FROM stocks_trades "
        "WHERE status='CLOSED' AND closed_at > NOW() - INTERVAL '4 hours' "
        "GROUP BY symbol, entry_price HAVING COUNT(*) > 5) sub"
    )).fetchone()
    return r[0] == 0, f"{r[0]} loops detectados"

def stocks_trades_today():
    if now.weekday() >= 5:
        return True, "Fin de semana — sin trades esperado"
    r = e.connect().execute(text(
        "SELECT COUNT(*), ROUND(SUM(pnl)::numeric,2) FROM stocks_trades "
        "WHERE status='CLOSED' AND closed_at::date = CURRENT_DATE"
    )).fetchone()
    is_nyse = 14.5 <= now.hour + now.minute/60 < 21
    if is_nyse and r[0] == 0 and now.hour > 16:
        return False, f"NYSE abierto 2h+, 0 trades"
    return True, f"{r[0]} trades hoy, PnL=${pnl(r[1]):,.2f}"

# ── RUNNER ────────────────────────────────────────────────────────────────

AGENTS = {
    'trend_momentum': [
        ('Señales generadas', tm_signals_present),
        ('Ejecuciones', tm_executing),
        ('Sin bloqueos', tm_not_blocked),
        ('Available cash ≥ $10', tm_available_cash),
        ('DD < 10%', tm_dd_ok),
        ('Trades abiertos', tm_open_trades),
        ('Trades hoy', tm_trades_today),
    ],
    'stocks': [
        ('Feed fresco', stocks_feed_fresh),
        ('Sin loops', stocks_no_loops),
        ('Trades hoy', stocks_trades_today),
    ],
}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--agent', choices=list(AGENTS.keys()), help='Agente específico')
    parser.add_argument('--json', action='store_true', help='Salida JSON')
    args = parser.parse_args()

    targets = [args.agent] if args.agent else list(AGENTS.keys())
    
    results = {}
    all_ok = True
    
    for agent in targets:
        agent_results = []
        for name, fn in AGENTS[agent]:
            ok, msg = check(name, fn)
            agent_results.append({'check': name, 'ok': ok, 'message': msg})
            if not ok:
                all_ok = False
        
        if args.json:
            results[agent] = agent_results
        else:
            print(f"\n{'='*60}")
            print(f"📋 SPEC CHECK: {agent}")
            print(f"{'='*60}")
            for r in agent_results:
                icon = '✅' if r['ok'] else '❌'
                print(f"  {icon} {r['check']:<30s} {r['message']}")
    
    if args.json:
        import json
        print(json.dumps(results, indent=2, default=str))
    
    if all_ok:
        print(f"\n✅ Todos los SPECs cumplidos")
    else:
        print(f"\n❌ Hay violaciones de SPEC — revisar arriba")
    
    sys.exit(0 if all_ok else 1)

if __name__ == '__main__':
    main()

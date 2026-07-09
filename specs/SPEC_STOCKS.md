# SPEC: Stocks Agent

> **Versión**: 1.0 | **Última actualización**: Mayo 27, 2026

---

## 1. Comportamiento esperado

### 1.1 Horario

| Condición | Comportamiento |
|-----------|---------------|
| L-V 14:30-21:00 UTC | Operando |
| Fuera de horario | "NYSE cerrado. Ciclo saltado." |
| Fin de semana / festivo | "NYSE cerrado. Ciclo saltado." |

### 1.2 Frecuencia

| Métrica | Mínimo | Esperado |
|---------|--------|----------|
| Trades/día hábil | 3 | 5-15 |
| Señales evaluadas/ciclo | 1 | 3-8 |

**ALERTA**: 0 trades en día hábil con NYSE abierto > 2h → revisar logs de `STOCKS FEED: stale`.

---

## 2. Pipeline de ejecución

```
1. _is_nyse_open()            → ¿Mercado abierto?
2. feed.get_price()           → ¿Precio fresco? (< 5 min, no congelado)
3. get_stocks_profile()       → Perfil del símbolo
4. direction_guard_allowed()  → ¿DirectionGuard permite?
5. Alpaca submit_order()      → Ejecutar en paper/live
6. _monitor_open_trades()     → SL/TP/trailing
```

---

## 3. Parámetros críticos

| Parámetro | Archivo | Valor |
|-----------|---------|-------|
| MAX_CONCURRENT_TRADES | stocks_agent.py | 4 |
| MAX_RISK_PER_TRADE_PCT | stocks_agent.py | 1% |
| confluence_min | stocks_profiles.py | 2-3 por activo |
| STALE_THRESHOLD | stocks_feed.py | 300s (5 min) |
| FROZEN_THRESHOLD | stocks_feed.py | 300s (5 min) |

---

## 4. Checks automáticos

```bash
# Check 1: ¿NYSE abierto?
date -u +"%H:%M UTC — %A"

# Check 2: ¿Datos frescos?
journalctl -u stocks-agent --since "30 min ago" --no-pager | grep -c "STOCKS FEED: stale"

# Check 3: ¿Trades hoy?
venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
e = create_engine(os.environ['DB_URL'])
r = e.execute(text(\"SELECT symbol, COUNT(*), ROUND(SUM(pnl)::numeric,2) FROM stocks_trades WHERE status='CLOSED' AND closed_at::date = CURRENT_DATE GROUP BY symbol\")).fetchall()
for row in r: print(f'{row[0]:<6s} {row[1]} trades, PnL=\${float(row[2]):,.2f}')
print(f'---')
r = e.execute(text(\"SELECT COUNT(*) FROM stocks_trades WHERE status='OPEN'\")).fetchone()
print(f'Abiertos: {r[0]}')
"

# Check 4: ¿Entry prices repetidos? (loop detection)
venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
e = create_engine(os.environ['DB_URL'])
r = e.execute(text(\"SELECT symbol, entry_price, COUNT(*) FROM stocks_trades WHERE status='CLOSED' AND closed_at > NOW() - INTERVAL '4 hours' GROUP BY symbol, entry_price HAVING COUNT(*) > 5\")).fetchall()
if r:
    for row in r: print(f'LOOP: {row[0]} entry=\${float(row[1]):.2f} x{row[2]}')
else:
    print('Sin loops detectados')
"
```

---

## 5. Fallos conocidos y fixes

| Fecha | Problema | Causa | Fix |
|-------|----------|-------|-----|
| May 22 | 75 trades QQQ falsos | Precio Alpaca congelado post-cierre | stocks_feed.py: staleness guard + frozen price detection |
| May 25 | Error monitoreando QQQ | NoneType de get_price() | stocks_agent.py: `if price is None: continue` |

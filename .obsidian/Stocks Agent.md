# Stocks Agent — 🟢

## Servicio
- **systemctl**: `stocks-agent`
- **Entry point**: `scripts/run_stocks.py`
- **Sesión**: `STOCKS_SESSION_011` — $1,000
- **Broker**: Alpaca (paper)
- **Horario**: L-V 14:30-21:00 UTC (NYSE)

## Pipeline de ejecución

```
1. _is_nyse_open()              → ¿Mercado abierto?
2. feed.get_price()             → ¿Precio fresco? (<5 min, no congelado)
3. get_stocks_profile()         → Perfil del símbolo (SL/TP/trailing)
4. direction_guard_allowed()    → ¿DirectionGuard permite?
5. Alpaca submit_order()        → Ejecutar en paper/live
6. _monitor_open_trades()       → SL/TP/trailing stop
```

## Estrategias

| Estrategia | Activos | WR |
|-----------|---------|-----|
| STOCKS_MOMENTUM | NVDA, TSLA, AAPL, META, AMZN | 56% |
| TREND_ETF | SPY, QQQ, GLD, SLV, EEM, FXI, EWJ | 44% |
| MINERVINI | Momentum diario BUY-only | 67% |

## Comandos de diagnóstico

```bash
# ¿NYSE abierto?
date -u +"%H:%M UTC — %A"

# ¿Datos frescos?
journalctl -u stocks-agent --since "30 min ago" --no-pager | grep "STOCKS FEED: stale"

# ¿Trades hoy?
venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
e = create_engine(os.environ['DB_URL'])
r = e.execute(text(\"SELECT symbol, COUNT(*), ROUND(SUM(pnl)::numeric,2) FROM stocks_trades WHERE status='CLOSED' AND closed_at::date = CURRENT_DATE GROUP BY symbol\")).fetchall()
for row in r: print(f'{row[0]:<6s} {row[1]} trades, PnL=\${float(row[2]):,.2f}')
"

# ¿Loops? (entry price repetido > 5 veces en 4h)
venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
e = create_engine(os.environ['DB_URL'])
r = e.execute(text(\"SELECT symbol, entry_price, COUNT(*) FROM stocks_trades WHERE status='CLOSED' AND closed_at > NOW() - INTERVAL '4 hours' GROUP BY symbol, entry_price HAVING COUNT(*) > 5\")).fetchall()
if r: [print(f'LOOP: {row[0]} \${float(row[1]):.2f} x{row[2]}') for row in r]
else: print('Sin loops')
"
```

## Parámetros clave

| Parámetro | Archivo | Valor |
|-----------|---------|-------|
| MAX_CONCURRENT_TRADES | stocks_agent.py | 4 |
| MAX_RISK_PER_TRADE_PCT | stocks_agent.py | 1% |
| STALE_THRESHOLD | stocks_feed.py | 300s (5 min) |
| confluence_min | stocks_profiles.py | 2-3/activo |
| MemoryMax | systemd | 768MB |

## Gotchas

- **NYSE cerrado** fines de semana y festivos (Memorial Day, 4 Julio, etc.)
- **Precio congelado**: si get_price() retorna None → el agente salta el símbolo
- **Loop detection**: mismo entry_price > 5 veces en 4h = feed roto
- **GLD/SLV**: confluence_min y min_atr reducidos (May 19)
- **EEM/BUY**: bloqueado por DirectionGuard (19.7% WR)
- **QQQ fake trades**: 75 trades el 22 de Mayo por precio congelado (ya arreglado)

## Historial de fixes

| Fecha | Problema | Fix |
|-------|----------|-----|
| May 22 | 75 trades QQQ falsos | stocks_feed.py: staleness guard |
| May 25 | Error monitoreando (NoneType) | stocks_agent.py: None guard |
| May 19 | GLD/SLV 0 trades | confluence_min↓, min_atr↓ |
| May 19 | DirectionGuard stocks | EEM/BUY bloqueado |

## SPEC

[[SPEC_STOCKS]]

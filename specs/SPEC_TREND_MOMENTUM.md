# SPEC: TrendMomentum Strategy

> **Versión**: 1.0 | **Última actualización**: Mayo 27, 2026
> **Regla de oro**: Si la realidad no coincide con este SPEC, hay un bug.
> Antes de tocar código, ejecutar `scripts/tm_pulse.py` y comparar con este documento.

---

## 1. Comportamiento esperado (condiciones normales)

### 1.1 Frecuencia de señales

| Métrica | Mínimo | Esperado | Máximo |
|---------|--------|----------|--------|
| Oportunidades/día (L-V) | 10 | 50-200 | 500 |
| Ejecuciones/día (L-V) | 1 | 3-8 | 15 |
| Señales sin ejecutar | 0 | < 20% | 50% (normal en CHOPPY) |

**ALERTA**: Si > 50 señales en 2h con 0 ejecuciones → SPEC VIOLATION. Ejecutar `tm_pulse.py`.

### 1.2 Métricas de rendimiento (ventana 7 días)

| Métrica | Verde 🟢 | Amarillo 🟡 | Rojo 🔴 |
|---------|----------|-------------|---------|
| Win Rate | ≥ 45% | 35-44% | < 35% |
| Profit Factor | ≥ 1.20 | 0.90-1.19 | < 0.90 |
| Trades cerrados | ≥ 15 | 5-14 | < 5 |
| Drawdown | < 5% | 5-10% | > 10% |

**ALERTA**: 🔴 en cualquier métrica → Council session obligatoria.

### 1.3 Estados del agente

| Estado | Síntoma | Causas posibles (en orden) |
|--------|---------|---------------------------|
| OPERANDO | Ejecuciones > 0 en últimas 2h | Normal |
| SEÑALIZANDO | Oportunidades > 0, ejecuciones = 0 | 1) REJECTED en logs 2) CHOPPY 3) INSUFFICIENT_CASH 4) cooldown 5) low_confluence |
| INACTIVO | Oportunidades = 0 | 1) CHOPPY régimen 2) Datos stale 3) Fuera de horario |

---

## 2. Pipeline de ejecución (orden exacto)

Cada señal pasa por estas puertas. Si se bloquea, el log DEBE mostrar el motivo:

```
1. strategy.score(ind)         → ¿Score ≥ MIN_SCORE (65)?
2. classify_market_regime()    → ¿Régimen permite TM? (allow_trend)
3. direction_allowed()         → ¿Dirección permitida por perfil?
4. crypto_is_allowed()         → ¿DirectionGuard permite?
5. count_confluence()          → ¿Confluencia ≥ min del asset?
6. risk_manager.evaluate()     → ¿Hay cash? ¿Slots libres? ¿DD < 10%?
7. execution_agent.execute()   → Ejecutar orden
```

**PROTOCOLO DE DIAGNÓSTICO**: Empezar por el paso 6 (risk_manager). El 90% de los bloqueos silenciosos están ahí. Los logs de `REJECTED:` son la fuente de verdad.

---

## 3. Parámetros críticos (NO modificar sin Council)

| Parámetro | Archivo | Valor | Justificación |
|-----------|---------|-------|---------------|
| MIN_SCORE | trend_momentum.py:12 | 65 | Council #1 implícito. 70-75 eliminaba 90% señales |
| _TREND_STRENGTH_MIN | market_regime.py:19 | 0.08 | Council #2 (3-0-1). 0.12 muy restrictivo |
| confluence_min | asset_profiles.py | 2-3 por activo | Council #5 (4-0) |
| MAX_CONCURRENT | risk_manager.py:37 | 2 | Original |
| SL_COOLDOWN | execution_agent.py | 60 min | Original — protege overtrading |

---

## 4. Checks automáticos (ejecutar antes de tocar código)

```bash
# Check 1: ¿TM está generando señales?
journalctl -u trading-agent --since "30 min ago" --no-pager | grep -c "Opportunity:"

# Check 2: ¿TM está ejecutando?
journalctl -u trading-agent --since "30 min ago" --no-pager | grep -c "Executed trade:"

# Check 3: ¿Por qué se rechazan las señales?
journalctl -u trading-agent --since "30 min ago" --no-pager | grep "REJECTED:" | awk -F'REJECTED: ' '{print $2}' | cut -d':' -f1 | sort | uniq -c | sort -rn

# Check 4: ¿Available cash?
venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
e = create_engine(os.environ['DB_URL'])
r = e.connect().execute(text('SELECT total_balance, available_cash, drawdown_pct FROM portfolio ORDER BY timestamp DESC LIMIT 1')).fetchone()
print(f'Balance: \${float(r[0]):,.2f} | Cash: \${float(r[1]):,.2f} | DD: {float(r[2])*100:.1f}%')
"

# Check 5: ¿Trades abiertos que consumen cash?
venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
e = create_engine(os.environ['DB_URL'])
r = e.execute(text(\"SELECT strategy, COUNT(*), ROUND(SUM(entry_price * position_size)::numeric,2) FROM trades WHERE status='OPEN' AND strategy NOT IN ('GRID_STABLE','BASIS_TRADE','GRID_BOT') GROUP BY strategy\")).fetchall()
for row in r: print(f'{row[0]:<25s} {row[1]} trades, notional=\${float(row[2]):,.2f}')
print(f'---')
r = e.execute(text(\"SELECT COUNT(*) FROM trades WHERE strategy='TREND_MOMENTUM' AND status='OPEN'\")).fetchone()
print(f'TM abiertos: {r[0]}')
"
```

---

## 5. Historial de fixes (para no repetir)

| Fecha | Problema | Causa raíz | Fix |
|-------|----------|------------|-----|
| May 19 | TM parado (CHOPPY) | trend_direction muy estricto | indicators.py: MACD confirmation (#1) |
| May 21 | TM parado (CHOPPY) | _TREND_STRENGTH_MIN = 0.12 | market_regime.py: 0.12→0.08 (#2) |
| May 25 | TM señalizando, no ejecutando | confluence_min muy alto | asset_profiles.py: 3→2, 4→3 (#5) |
| May 27 | **TM señalizando, no ejecutando (REAL)** | **INSUFFICIENT_CASH** | run_trading.py: GRID_BOT excluido de get_open_trades + portfolio query |

**PATRÓN**: 3 fixes equivocados antes del real. Causa: no revisar `REJECTED:` en logs.

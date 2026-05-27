# AGENTS.md — Arthas Trading System v1.2

> Entry point para sesiones de OpenCode. Lee esto primero.
> **Tag**: `v1.2` — Protocolo de diagnóstico obligatorio. Mayo 27, 2026.

---

## ⚠️ REGLA DE ORO — LEER ANTES DE HACER NADA

**Antes de escribir una sola línea de código o proponer un fix, ejecutar:**

```bash
cd /opt/trading && venv/bin/python3 scripts/ai_context.py
```

**Antes de crear un módulo nuevo, verificar si ya existe:**

```bash
ls /opt/trading/core/*guard* /opt/trading/core/*health* /opt/trading/core/*monitor*
ls /opt/trading/scripts/*health* /opt/trading/scripts/*monitor* /opt/trading/scripts/*pulse*
```

---

## Protocolo de diagnóstico MANDATORIO

Cuando el usuario reporta un problema con un agente, seguir este orden **sin saltar pasos**:

### Paso 0 — Contexto
```bash
cd /opt/trading && venv/bin/python3 scripts/ai_context.py
```

### Paso 1 — ¿Está vivo?
```bash
systemctl is-active <servicio>
journalctl -u <servicio> -n 20 --no-pager
```

### Paso 2 — ¿Está operando? (MÉTRICAS, NO OPINIONES)
```bash
# Para crypto:
venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
e = create_engine(os.environ['DB_URL'])
with e.connect() as c:
    r = c.execute(text(\"SELECT strategy, COUNT(*), SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END), ROUND(SUM(pnl)::numeric,2) FROM trades WHERE status='CLOSED' AND timestamp_close > NOW() - INTERVAL '24 hours' GROUP BY strategy\")).fetchall()
    [print(row) for row in r]
    r = c.execute(text(\"SELECT COUNT(*) FROM trades WHERE status='OPEN'\")).fetchone()
    print(f'Abiertos: {r[0]}')
"
```

### Paso 3 — Si no opera, TRAZAR SEÑAL COMPLETA
NO asumir. Seguir la señal desde detección hasta ejecución:

```bash
# 1. ¿Genera señales?
journalctl -u <servicio> --since "30 min ago" --no-pager | grep "Opportunity:"

# 2. ¿Las señales llegan al risk manager?
journalctl -u <servicio> --since "30 min ago" --no-pager | grep "REJECTED"

# 3. ¿Se ejecutan?
journalctl -u <servicio> --since "30 min ago" --no-pager | grep "Executed trade"

# 4. Si se rechazan, ¿POR QUÉ? (ESTE ES EL PASO QUE FALLÉ)
journalctl -u <servicio> --since "30 min ago" --no-pager | grep "REJECTED:" | awk -F'REJECTED: ' '{print $2}' | sort | uniq -c | sort -rn
```

**NUNCA proponer un fix sin haber visto el motivo de rechazo en el paso 3.4.**

### Paso 4 — Si aplica fix, verificar antes/después
```bash
# Antes: guardar métricas
venv/bin/python3 scripts/tm_pulse.py > /tmp/before_fix.txt

# Aplicar fix

# Después: verificar que el problema desapareció
sleep 300  # esperar 1-2 ciclos
venv/bin/python3 scripts/tm_pulse.py > /tmp/after_fix.txt
diff /tmp/before_fix.txt /tmp/after_fix.txt
```

---

## Inventario de módulos EXISTENTES

### Guards y monitores (NO crear nuevos sin revisar estos)

| Módulo | Qué hace | ¿Cableado? |
|--------|----------|------------|
| `core/agent_health.py` | Thresholds por agente, semáforos 🟢🟡🔴, ventana 7 días | ❌ Pendiente integrar en health_check |
| `core/market_guard.py` | Protección de volatilidad, reducción de tamaño | ✅ run_trading.py |
| `core/performance_guard.py` | Circuit breaker por estrategia (bloquea edge insuficiente) | ✅ strategy_engine.py |
| `core/direction_guard.py` | Bloqueo de direcciones con WR < 30% (crypto + stocks) | ✅ strategy_engine + stocks_agent |
| `scripts/health_check.py` | 14 checks, alertas Telegram, noise filter | ✅ systemd timer |
| `scripts/strategy_monitor.py` | Monitoreo de estrategias | ❌ No cableado |
| `scripts/tm_pulse.py` | Diagnóstico rápido manual de TM | ✅ Manual |

### Diagnóstico rápido

```bash
# TM no opera:
venv/bin/python3 scripts/tm_pulse.py

# Agente salud (7 días):
venv/bin/python3 -c "
from core.agent_health import get_all_agents_health
import psycopg2, os
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')
conn = psycopg2.connect(dbname=os.getenv('POSTGRES_DB'), user=os.getenv('POSTGRES_USER'), password=os.getenv('POSTGRES_PASSWORD'), host=os.getenv('POSTGRES_HOST'))
for a in get_all_agents_health(conn, 7):
    print(f'{a[\"emoji\"]} {a[\"agent\"]:<20s} {a[\"passing\"]} PF={a[\"pf\"]} WR={a[\"wr\"]}% T={a[\"n_trades\"]} PnL=\${a[\"total_pnl\"]}')
"
```

---

## Reglas de no-duplicación

1. **Antes de crear un archivo nuevo en `core/` o `scripts/`**, verificar que no exista uno con nombre similar: `ls /opt/trading/core/*guard* /opt/trading/scripts/*health*`
2. **Si existe**, extenderlo. No crear uno nuevo.
3. **Si no existe**, crearlo con nombre descriptivo y documentarlo en AGENTS.md.

---

## Lecciones de Mayo 2026

| Error | Causa | Cómo evitarlo |
|---|---|---|
| 3 fixes equivocados para TM | No revisé REJECTED en logs | Paso 3.4 del protocolo |
| agentguard.py duplicado | No revisé core/agent_health.py | Inventario de módulos |
| TM parado 7 días | available_cash negativo invisible | Paso 2: métricas diarias |
| QQQ fake trades 3 días | No detecté precio repetido | Paso 2 + Paso 3 |
| Basis Agent -$346 | No verifiqué exit_price | Paso 2 |

---

## Setup obligatorio al iniciar sesión

```bash
cd /opt/trading && venv/bin/python3 scripts/ai_context.py  # briefing completo
set -a && source config/.env && set +a                     # cargar env vars
```

**Python**: SIEMPRE `/opt/trading/venv/bin/python3`, NUNCA `python3` del sistema.

## Agentes activos (6 systemd + Homerun externo)

| Agente | Servicio | Entry point | Sesión |
|--------|----------|-------------|--------|
| Trading (Crypto/Metales) | `trading-agent` | `scripts/run_trading.py` | SESSION_011 ($1,000) |
| Stocks (Alpaca) | `stocks-agent` | `scripts/run_stocks.py` | STOCKS_SESSION_011 ($1,000) |
| Options (Theta Farming) | `options-agent` | `scripts/run_options.py` | OPTIONS_SESSION_001 |
| PolySnipe (Up/Down 15m) | `polymarket-snipe` | `scripts/run_polymarket_snipe.py` | SNIPE_SESSION |
| Grid Stable Pairs | `grid-stable` | `agents/grid_stable_agent.py` | Compartida |
| Pairs Trading | `pairs-agent` | `agents/pairs_executor.py` | Compartida |
| VIX Mean Reversion | `vix-agent` | `agents/vol_executor.py` | — |
| Homerun (Prediction Mkts) | PC externa Omarchy | Docker | Shadow mode |

### Desactivados
Polymarket Agent, Basis Trade Agent, Kalshi Arbitrage, BTC Direction.

## Estrategias crypto activas

| Estrategia | Tipo | Slots | Estado |
|-----------|------|-------|--------|
| TREND_MOMENTUM | SELL + BUY condicional | 2 | Operando (fix INSUFFICIENT_CASH Mayo 27) |
| GRID_BOT | Grid en RANGE/CHOPPY | 3 | Operando |
| GRID_STABLE | Grid pares estables | — | Operando |
| SMC_ORDER_BLOCKS | BUY+SELL ICT | 2 | Council #3: slots 1→2 |
| BTC_MICROSTRUCTURE | BUY+SELL multi-indicator | 2 | Council #3: slots 1→2 |
| EMA_RIBBON | BUY trend-following | 1 | Inactivo (incompatible SELL-only) |

### Parámetros post-council (Mayo 2026)

| Fix | Archivo | Cambio | Council |
|-----|---------|--------|---------|
| trend_direction + MACD | `agents/indicators.py` | EMA gap + confirmación MACD | #1 (4-0) |
| _TREND_STRENGTH_MIN | `core/market_regime.py` | 0.12 → 0.08 | #2 (3-0-1) |
| MAX_CONCURRENT SMC/BTC | `risk/risk_manager.py` | 1 → 2 slots | #3 (3-0-1) |
| available_cash fix | `scripts/run_trading.py` | GRID_BOT excluido de get_open_trades | Directo |
| confluence_min | `core/asset_profiles.py` | 3→2, 4→3 por activo | #5 (4-0) |

### Trading Council

```bash
venv/bin/python3 scripts/trading_council.py "tema a debatir"
```

Actas en `/opt/trading/.council/`. Documentación: `docs/TRADING_COUNCIL.md`.

## Servicios systemd

```bash
systemctl status trading-agent options-agent polymarket-snipe stocks-agent dashboard-api dashboard-web grid-stable pairs-agent vix-agent trading-health
```

## Documentación

| Doc | Contenido |
|-----|----------|
| `docs/AI_MASTER.md` | Índice maestro del sistema |
| `docs/AGENTGUARD.md` | Propuesta de watchdog (PENDIENTE integrar agent_health) |
| `docs/STRATEGY_ARCHITECTURE_V2.md` | Plan de migración a BaseStrategy |
| `docs/STOCKS_IMPROVEMENT_PLAN.md` | Análisis forense + plan de mejora stocks |
| `docs/TRADING_COUNCIL.md` | Sistema de consejo multi-agente |
| `docs/OMARCHY_HOMERUN_GUIDE.md` | Guía instalación Homerun en PC externa |

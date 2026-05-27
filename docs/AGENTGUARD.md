# AGENTGUARD — Sistema de Garantía de Funcionamiento

> **Objetivo**: Detectar anomalías en los agentes ANTES de que causen daño,
> basado en el patrón común de los 5 fallos de Mayo 2026.

---

## 1. El patrón de todos los fallos

Cada fallo tuvo una **señal temprana** que fue ignorada:

| Fallo | Señal temprana | Cuándo se pudo detectar |
|---|---|---|
| TM sin operar | available_cash negativo | Minuto 1 |
| QQQ fake trades | entry_price repetido 75× | Minuto 30 |
| Basis drain | exit_price=$0 en trades | Minuto 1 |
| Polymarket | WR < 30% sostenido | Día 30 |
| Health check ciego | Métricas de negocio sin monitoreo | Siempre |

**Solución**: un watchdog de 5 capas que revise estas señales cada 5 minutos.

---

## 2. Arquitectura AgentGuard

```
┌─────────────────────────────────────────────────────────┐
│                    AGENTGUARD                             │
│                   (cada 5 minutos)                        │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  CAPA 1 — Heartbeat    ¿El agente está vivo?             │
│  CAPA 2 — Actividad    ¿Está operando lo esperado?       │
│  CAPA 3 — Anomalías    ¿Hay patrones sospechosos?        │
│  CAPA 4 — Negocio      ¿Las métricas son saludables?     │
│  CAPA 5 — Tendencia    ¿Está empeorando?                │
│                                                          │
├─────────────────────────────────────────────────────────┤
│  ALERTAS → Telegram solo si:                              │
│    - CRÍTICO: acción inmediata requerida                  │
│    - WARNING: tendencia negativa > 2h                     │
│    - INFO: heartbeat cada 6h con resumen                  │
└─────────────────────────────────────────────────────────┘
```

---

## 3. Checks por agente

### 3.1 TRADING AGENT (Crypto)

| Capa | Check | Umbral | Acción |
|---|---|---|---|
| Heartbeat | Ciclos completados | < 3 en 5 min | 🚨 CRÍTICO |
| Actividad | TM trades/día | < 1 en 48h siendo lunes-viernes | ⚠️ WARNING |
| Actividad | TM señales sin ejecutar | > 50 señales, 0 ejecuciones en 2h | 🚨 CRÍTICO |
| Anomalías | entry_price repetido | mismo precio > 10 trades consecutivos | 🚨 CRÍTICO |
| Anomalías | exit_price = $0 | cualquiera | 🚨 CRÍTICO |
| Anomalías | PnL idéntico repetido | mismo PnL > 20 trades | ⚠️ WARNING |
| Negocio | available_cash | < $10 | 🚨 CRÍTICO |
| Negocio | DD | > 10% | 🚨 CRÍTICO |
| Negocio | WR semanal | < 30% con > 15 trades | ⚠️ WARNING |
| Tendencia | PnL diario 3 días | cayendo 3 días seguidos | ⚠️ WARNING |

### 3.2 STOCKS AGENT

| Capa | Check | Umbral | Acción |
|---|---|---|---|
| Heartbeat | Proceso activo | systemctl is-active | 🚨 CRÍTICO |
| Actividad | Trades/día hábil | 0 en día hábil con NYSE abierto > 2h | ⚠️ WARNING |
| Anomalías | Precio stale | get_price() retorna None > 30 min | ⚠️ WARNING |
| Anomalías | entry_price repetido | > 5 trades mismo precio | 🚨 CRÍTICO |
| Negocio | DD | > 10% | 🚨 CRÍTICO |

### 3.3 POLYSNIPE

| Capa | Check | Umbral | Acción |
|---|---|---|---|
| Actividad | Trades/día | 0 en 48h | ⚠️ WARNING |
| Negocio | PnL mensual | < -$50 | ⚠️ WARNING |
| Negocio | Loss > $10 | cualquiera (post-May15 no debería ocurrir) | 🚨 CRÍTICO |

### 3.4 GRID_STABLE / GRID_BOT

| Capa | Check | Umbral | Acción |
|---|---|---|---|
| Anomalías | SL repetidos sin TP | > 20 SL consecutivos, 0 TP | ⚠️ WARNING |
| Negocio | WR semanal | < 35% | ⚠️ WARNING |

---

## 4. Implementación

### Archivo: `scripts/agentguard.py`

- Se ejecuta cada 5 minutos vía systemd timer
- Consulta DB, Redis, y journalctl
- Evalúa los 5 checks por agente
- Envía alertas a Telegram solo si hay anomalías
- Guarda estado en `/opt/trading/.agentguard_state.json` para detectar tendencias

### Timer systemd

```
[Unit]
Description=AgentGuard — Watchdog de agentes

[Timer]
OnCalendar=*:0/5
Persistent=true

[Install]
WantedBy=timers.target
```

---

## 5. TM Pulse (diagnóstico rápido)

### Archivo: `scripts/tm_pulse.py`

- Diagnóstico de 6 capas específico para TM
- Se ejecuta manualmente: `venv/bin/python3 scripts/tm_pulse.py`
- Responde en 10 segundos: ¿por qué TM no opera?
- Ya está creado y funcional

---

## 6. Resultado esperado

| Antes | Después |
|---|---|
| Fallos detectados en días/semanas | Detectados en ≤ 5 minutos |
| "¿Por qué no opera?" → 3 fixes equivocados | TM Pulse responde en 10s |
| Usuario descubre bugs preguntando | AgentGuard alerta proactivamente |
| Health check 14/14 con agents fallando | AgentGuard detecta anomalías de negocio |

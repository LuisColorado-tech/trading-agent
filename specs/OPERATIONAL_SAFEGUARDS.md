# OPERATIONAL_SAFEGUARDS — Especificación Operativa v1.0

> **Versión**: 1.0 | **Ratificado**: Council #10 (2-0-2) | **Junio 15, 2026**
>
> Este documento define cómo debe comportarse el sistema en producción cuando las cosas fallan.
> No es un spec de estrategia — es un spec operativo de supervivencia.

---

## P1 — Drawdown desde capital de sesión, no desde pico

**Problema**: El DD actual se calcula contra el pico histórico absoluto. Si el sistema hace +90% y luego retrocede 8% desde ese pico, se bloquea todo. El capital sigue estando muy por encima del inicial pero el guard no lo sabe.

**Solución**: `calculate_drawdown()` debe usar como referencia `max(capital_inicial_sesion, balance_actual)`, no el pico histórico absoluto.

**Archivos**: `core/portfolio_utils.py`, `scripts/run_trading.py`

**Ejemplo**:
```
Capital inicial: $1,000
Balance actual: $1,928
Pico histórico:  $2,115
DD actual (mal):  (2115 - 1928) / 2115 = 8.8% → EMERGENCY
DD nuevo (bien):  (1928 - 1928) / 1928 = 0.0%  → NORMAL
```

---

## P2 — Circuit breaker de loop

**Problema**: Si el main loop crashea, el agente hace `sleep(10)` y reintenta. Si el error es persistente (zero-size trade, guard unbound), el agente se queda 12h en loop de error sin que nadie se entere hasta que llega la alerta de "sin ciclos completados".

**Solución**: Contador de crashes consecutivos con ventana de 5 minutos. Si 3 crashes en 5 min → HALT total del agente + alerta Telegram crítica. Recuperación solo manual.

**Archivos**: `scripts/run_trading.py`

**Reglas**:
| Crashes consecutivos | Acción |
|---------------------|--------|
| 1-2 | `sleep(10)`, reintentar |
| 3 en ≤5 min | HALT — pausar agente, alerta Telegram |
| Recuperación | Solo manual (`systemctl restart`) |

---

## P3 — Guard de mercado degradado (no binario)

**Problema**: El MarketGuard es binario: NORMAL (1x) → EMERGENCY (0x). No hay punto intermedio. Un DD de 5.1% no debería ser tratado igual que uno de 9.9%.

**Solución**: Añadir modo DEGRADED con multiplier 0.25x para DD entre 5% y 8%.

**Archivos**: `core/market_guard.py`, `core/portfolio_utils.py`

**Niveles**:
| DD | Modo | Multiplier | Efecto |
|----|------|-----------|--------|
| 0-5% | NORMAL | 1.00x | Sin restricción |
| 5-8% | DEGRADED | 0.25x | Tamaños reducidos al 25% |
| 8-10% | EMERGENCY | 0.00x | Sin nuevas posiciones |
| >10% | HALT | — | Sistema detenido |

---

## Procedimientos de recuperación

### Halt por DD > 10%
1. `systemctl stop trading-agent`
2. Verificar causa del drawdown
3. Si es por bugs → fix + restart
4. Si es por mercado → esperar régimen favorable o Council decide

### Halt por circuit breaker (3 crashes)
1. Revisar logs: `journalctl -u trading-agent --since "10 min ago" | grep ERROR`
2. Identificar y fixear la causa raíz
3. `systemctl restart trading-agent`
4. Monitorear 3 ciclos para confirmar estabilidad

---

## Escalado de alertas Telegram

| Evento | Severidad | Acción |
|--------|-----------|--------|
| 1 crash de loop | ⚠️ WARNING | Log silencioso |
| 2 crashes seguidos | 🟡 ALERTA | Notificación Telegram |
| 3 crashes en 5 min | 🔴 CRÍTICA | HALT + Telegram urgente |
| DD > 8% | 🔴 CRÍTICA | EMERGENCY + Telegram |
| Sin ciclos en 15 min | 🔴 CRÍTICA | Telegram urgente |
| Sin ciclos en 30 min | 🔴 CRÍTICA | Escalar a admin |

---

## Changelog

| Fecha | Cambio | Council |
|-------|--------|---------|
| Jun 15, 2026 | v1.0 — P1, P2, P3 definidos | #10 (2-0-2) |

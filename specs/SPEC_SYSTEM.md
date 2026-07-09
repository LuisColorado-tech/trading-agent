# SPEC: Sistema Completo

> **Versión**: 1.0 | **Última actualización**: Mayo 27, 2026
> **Regla de oro**: Antes de cualquier cambio, leer este SPEC + el SPEC del agente afectado.

---

## 1. Arquitectura de agentes

```
┌─────────────┐  ┌─────────────┐  ┌──────────────┐  ┌────────────┐
│ TRADING     │  │ STOCKS      │  │ OPTIONS      │  │ POLYSNIPE  │
│ (crypto)    │  │ (Alpaca)    │  │ (Deribit)    │  │ (Polymkt)  │
│ systemd     │  │ systemd     │  │ systemd      │  │ systemd    │
└──────┬──────┘  └──────┬──────┘  └──────┬───────┘  └─────┬──────┘
       │                │                │                 │
       └────────────────┴────────────────┴─────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │   SHARED LAYER    │
                    │ PostgreSQL :5432  │
                    │ Redis :6379       │
                    └───────────────────┘
```

## 2. Agentes y sus expectativas

| Agente | Estrategias | Trades/día esperado | WR mínimo | PP mínimo |
|--------|------------|---------------------|-----------|-----------|
| **Trading** | TM, GridBot, GridStable, SMC, BTC_Micro | 50-200 total | 45% | 1.2 |
| **Stocks** | MOMENTUM, TREND_ETF, MINERVINI | 3-15 (días hábiles) | 40% | 1.0 |
| **Options** | Theta Farming | 0.1-1 | 50% | 1.0 |
| **PolySnipe** | SNIPE Up 15m | 1-5 | 85% | 1.0 |

## 3. Shared risks (afectan a todos los agentes)

| Riesgo | Detección | Severidad |
|--------|-----------|-----------|
| GRID_BOT nocional consume available_cash | `available_cash < $10` en portfolio | 🚨 CRÍTICO |
| PostgreSQL caído | health_check.py Check 4 | 🚨 CRÍTICO |
| Redis caído | health_check.py (implícito) | 🚨 CRÍTICO |
| DD > 10% | health_check.py Check 7 | 🚨 CRÍTICO |
| Agente inactivo > 48h | health_check.py Check 9 (balance_stuck) | ⚠️ WARNING |

## 4. Protocolo ante fallo

```
1. NO TOCAR CÓDIGO hasta completar diagnóstico
2. Ejecutar: venv/bin/python3 scripts/tm_pulse.py (si es TM)
3. Si no es TM: journalctl -u <servicio> --since "30 min ago" | grep "REJECTED:"
4. Leer el SPEC del agente afectado en /opt/trading/specs/
5. Si es cambio de parámetro → Council
6. Si es bug → Fix directo + actualizar SPEC
7. Verificar con datos (antes/después)
```

## 5. Sistema de alertas

| Canal | Qué | Frecuencia |
|-------|-----|------------|
| **Telegram** | health_check.py: FAIL, HALT, recuperación | Cada 5 min si hay fallo |
| **Telegram** | health_check.py: Heartbeat | Cada 3h |
| **Dashboard** | Agent semáforos 🟢🟡🔴 | Tiempo real |
| **Logs** | journalctl -u <servicio> | Continuo |

## 6. Módulos de protección

| Módulo | Archivo | Activo | Qué protege |
|--------|---------|--------|-------------|
| RiskManager | risk/risk_manager.py | ✅ | DD, concurrentes, cash |
| DirectionGuard | core/direction_guard.py | ✅ | WR < 30% en ≥15 trades |
| PerformanceGuard | core/performance_guard.py | ✅ | Edge insuficiente por estrategia |
| MarketGuard | core/market_guard.py | ✅ | Volatilidad baja → reduce tamaño |
| AgentHealth | core/agent_health.py | ⚠️ | Semáforos (no cableado a alertas) |

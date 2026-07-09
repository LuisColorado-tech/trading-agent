# PLAN DE EXPANSIÓN AUTOMATIZADO — 5 Líneas en 14 Días

> **Orquestador**: OpenCode v1.14.31 con `opencode run`
> **Triggers**: Cron jobs → Telegram aviso → OpenCode ejecuta
> **Meta**: 2% mensual compuesto entre todos los agentes

---

## Infraestructura de automatización

```
cron (horario UTC)
  │
  ├── Día 1, 08:00 → Telegram "🚀 Fase 1: Grid Stable Pairs"
  │                  + opencode run --phase grid_stable
  │
  ├── Día 3, 08:00 → Telegram "🚀 Fase 2: Basis Trade"
  │                  + opencode run --phase basis_trade
  │
  ├── Día 5, 08:00 → Telegram "🚀 Fase 3: VIX Mean Reversion"
  │                  + opencode run --phase vix
  │
  ├── Día 8, 08:00 → Telegram "🚀 Fase 4: Pairs Trading"
  │                  + opencode run --phase pairs
  │
  ├── Día 11, 08:00 → Telegram "🚀 Fase 5: Earnings Strangle"
  │                  + opencode run --phase earnings
  │
  └── Día 14, 08:00 → Telegram "📊 Reporte Final Consolidado"
                     + opencode run --phase final_report
```

## Cronograma comprimido (14 días)

| Día | Fecha | Hora UTC | Fase | Entregables |
|---|---|---|---|---|
| 1 | May 3 | 08:00 | Grid Stable Pairs | 6 archivos + backtest ETH/BTC 2Y + dashboard |
| 3 | May 5 | 08:00 | Basis Trade | 6 archivos + backtest funding rates 2Y + dashboard |
| 5 | May 7 | 08:00 | VIX Mean Reversion | 5 archivos + backtest VIX 5Y + dashboard |
| 8 | May 10 | 08:00 | Pairs Trading | 6 archivos + backtest cointegración 5Y + dashboard |
| 11 | May 13 | 08:00 | Earnings Strangle | 6 archivos + backtest earnings 3Y + dashboard |
| 14 | May 16 | 08:00 | Reporte Final | Dashboard consolidado + Telegram + git push |

---

## Mecanismo de ejecución

Cada trigger de cron ejecuta:

```bash
#!/bin/bash
# 1. Telegram: "🚀 Inicia Fase X"
curl -s -X POST "https://api.telegram.org/bot{TOKEN}/sendMessage" \
  -d "chat_id={CHAT}" \
  -d "text=🚀 <b>FASE X INICIADA</b>%0A%0AImplementando: [nombre]%0AArchivos a crear: [lista]%0ABacktest: [script]%0A%0A⏱️ Tiempo estimado: [X] minutos" \
  -d "parse_mode=HTML"

# 2. Ejecutar OpenCode con el prompt de la fase
cd /opt/trading
opencode run "$(cat /opt/trading/scripts/phases/phase_X_prompt.txt)"

# 3. Telegram: "✅ Fase X completada"  
curl -s -X POST "https://api.telegram.org/bot{TOKEN}/sendMessage" \
  -d "chat_id={CHAT}" \
  -d "text=✅ <b>FASE X COMPLETADA</b>%0A%0AArchivos creados: [count]%0ABacktest: [resultado]%0ADashboard: actualizado%0A%0APróxima fase: [nombre] — [fecha] 08:00 UTC" \
  -d "parse_mode=HTML"
```

---

## Archivos del orquestador

```
scripts/
  orchestrator.sh              ← Script maestro que despacha fases
  phases/
    phase_1_grid_stable.txt    ← Prompt detallado para OpenCode
    phase_2_basis_trade.txt
    phase_3_vix.txt
    phase_4_pairs.txt
    phase_5_earnings.txt
    phase_6_final_report.txt
```

## Cron entries

```cron
0 8 3 5 * /opt/trading/scripts/orchestrator.sh grid_stable
0 8 5 5 * /opt/trading/scripts/orchestrator.sh basis_trade
0 8 7 5 * /opt/trading/scripts/orchestrator.sh vix
0 8 10 5 * /opt/trading/scripts/orchestrator.sh pairs
0 8 13 5 * /opt/trading/scripts/orchestrator.sh earnings
0 8 16 5 * /opt/trading/scripts/orchestrator.sh final_report
```

---

## ESTADO DE EJECUCIÓN — May 13, 2026

> **Última intervención**: Fase 5 (Earnings) ejecutada parcialmente — archivos generados, timeout antes de activar.

### Ejecución de fases

| Fase | Fecha | Mecanismo | Estado | Nota |
|------|-------|-----------|--------|------|
| 1. Grid Stable | May 3 | system crontab | ✅ | Completado |
| 2. Basis Trade | May 5 | system crontab | ✅ | Completado |
| 3. VIX Mean Rev | May 7 | system crontab + manual | ✅ | opencode crasheó; completado manualmente May 9 |
| 4. Pairs Trading | May 10 | Hermes cron + manual | ✅ | opencode falló; completado manualmente May 12-13 |
| 5. Earnings Strangle | May 13 | Hermes cron | ⚠️ Parcial | opencode timeout 120s. Archivos creados pero config no activada |
| 6. Final Report | **May 16** | Hermes cron | ⏳ | Próximo viernes 08:00 UTC |

### Phase 5 — Earnings Strangle (May 13)

Archivos generados automáticamente:
- `agents/earnings_executor.py` ✅
- `core/earnings_profiles.py` ✅
- `data/earnings_calendar.py` ✅
- `strategies/earnings_strangle.py` ✅

Pendiente:
- `scripts/backtest_earnings.py` ❌ (no creado, timeout)
- `config/exchange_config.yaml` earnings_strangle: enabled (sigue false)
- `systemd: earnings-agent.service` ❌ (no creado)
- Dashboard earnings card ❌

### Dashboard Improvement Plan

| Fase | Tarea | Estado |
|------|-------|--------|
| 1.1 | ConsortiumWidget | **HECHO** |
| 1.2 | AllocationChart donut | **HECHO** |
| 1.3 | P&L consolidado heatmap | **HECHO** |
| 2.1-2.4 | Páginas agentes | **HECHO** |
| 3.1 | Risk panel (Sharpe, Sortino, VaR) | **HECHO** |
| 3.2 | Drawdown chart | **HECHO** |
| 3.3 | Monthly returns bars | **HECHO** |
| 4.1 | SSE live ticker | **PENDIENTE** |
| 4.2 | Notificaciones | **PENDIENTE** |
| 4.3 | Sidebar + cards clickeables | **HECHO** |
| R | Dashboard responsive | **HECHO** |
| P | Pairs Trading AgentCard | **HECHO** |
| H | Health check 15/15 agents | **HECHO** May 13 |

### Fixes críticos aplicados

| Fix | Fecha | Descripción |
|-----|-------|-------------|
| `orchestrator.sh` exit 0 bug | May 9 | Dashboard phases eran código muerto |
| VIX backtest | May 9 | `scripts/backtest_vol.py` creado |
| Cron duplicado | May 9 | System crontab phases 4-6 comentados |
| TrendMomentum bloqueado | May 12 | `get_open_trades()` filtra Grid Stable |
| ASSETS expandido | May 12 | 10 activos (era 5) |
| MarketGuard | May 13 | 6 circuit breakers, cero permanentes |
| Minervini SEPA | May 13 | BUY-only daily, 116 trades BT 3Y PF=2.04 |
| PolySnipe recalibrado | May 13 | BTC/ETH only, entry max $0.92 |
| Dashboard API URL | May 13 | api.ts → localhost:8000 + cache no-store |
| Health check 15/15 | May 13 | Options + Pairs + Minervini tracking |
| Duplicate heartbeat | May 13 | Hermes heartbeat disabled, solo systemd |
| Hermes jobs.json | May 13 | Corrupted by edit, restored manually |

### Servicios (9 activos)

```
trading-agent options-agent polymarket-agent polymarket-snipe
stocks-agent grid-stable pairs-agent dashboard-api dashboard-web
```

### Notas para el futuro agente

- **NO volver a crear** páginas que ya existen en `web/app/`.
- **NO tocar** `web/.next/` a menos que haya errores de build.
- Para rebuild: `rm -rf web/.next && cd web && npm run build && systemctl restart dashboard-web`.
- El plan `DASHBOARD_IMPROVEMENT_PLAN.md` sigue vigente como guía de fases.
- TrendMomentum y Grid Stable son independientes en RiskManager — no reinstroducir el bug de conteo unificado de trades abiertos.
- Hermes cron maneja fases 4, 5, 6. System crontab maneja phases 1-3 (ya ejecutadas).

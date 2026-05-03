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

## ESTADO ACTUAL DEL DASHBOARD — May 2, 2026

> **Última intervención**: Fix de crash + Fases 1-2 parciales del `DASHBOARD_IMPROVEMENT_PLAN.md`.

### Fix aplicado
- **Problema**: `Failed to find Server Action "x"` — build de Next.js obsoleto.
- **Solución**: `rm -rf web/.next && npm run build` + `systemctl restart dashboard-web`.

### Páginas existentes (9/9 con detalle)

| Ruta | Archivo | Estado |
|---|---|---|
| `/` (Overview) | `web/app/page.tsx` | **OK** — ConsortiumWidget, AllocationChart, MiniEquity, 6 AgentCards con href |
| `/stocks` | `web/app/stocks/page.tsx` | **OK** — preexistente |
| `/crypto` | `web/app/crypto/page.tsx` | **OK** — preexistente |
| `/polymarket` | `web/app/polymarket/page.tsx` | **NUEVO** — KPIs, posiciones abiertas/cerradas, historial |
| `/options` | `web/app/options/page.tsx` | **NUEVO** — KPIs, primas, posiciones abiertas/cerradas |
| `/btc-direction` | `web/app/btc-direction/page.tsx` | **NUEVO** — KPIs, WR por timeframe, historial trades |
| `/grid-stable` | `web/app/grid-stable/page.tsx` | **NUEVO** — KPIs, estrategia, plan implementación |
| `/trades` | `web/app/trades/page.tsx` | **MEJORADO** — Unifica 4 agentes (era 2: Stocks+Crypto, ahora +Poly+BTC Dir) |
| `/signals` | `web/app/signals/page.tsx` | **OK** — preexistente |
| `/analytics` | `web/app/analytics/page.tsx` | **OK** — preexistente |

### Componentes actualizados

| Componente | Cambio |
|---|---|
| `AgentCard.tsx` | Acepta `href` prop → wrappea en `<Link>` si se provee |
| `Sidebar.tsx` | 9 links (era 6) — agregados Polymarket, Options, BTC Direction |
| `lib/api.ts` | 4 métodos nuevos: `consortium`, `dailyPnl`, `polySession`, `polyPositions`, `optionsSession`, `optionsPositions`, `btcDirection` |

### API endpoints existentes (FastAPI :8000)

| Router | Endpoints | Estado |
|---|---|---|
| `overview.py` | `/` + `/consortium` + `/daily-pnl` | OK |
| `stocks.py` | `/session`, `/trades`, `/trades/open`, `/trades/equity`, `/universe`, `/stats/by-strategy`, `/stats/daily-pnl` | OK |
| `crypto.py` | `/portfolio`, `/portfolio/history`, `/trades`, `/trades/stats`, `/signals`, `/signals/heatmap`, `/ai`, `/stats/daily-pnl` | OK |
| `polymarket.py` | `/session`, `/positions`, `/stats`, `/btc-direction` | OK |
| `options.py` | `/session`, `/positions`, `/stats` | OK |
| `live.py` | `/prices` (REST) + `/stream` (SSE, sin usar en frontend) | OK |

### Grid Stable

- El endpoint `/overview/consortium` ya calcula balance y P&L real desde `trades WHERE strategy='GRID_STABLE'`.
- La página `/grid-stable` consume `consortium` + filtra `cryptoTrades` por `strategy='GRID_STABLE'`.
- **Pendiente**: Un endpoint dedicado `/grid-stable/stats` según Fase 5 del plan.

### Pendientes del DASHBOARD_IMPROVEMENT_PLAN.md

| Fase | Tarea | Estado |
|---|---|---|
| 1.1 | ConsortiumWidget | **HECHO** |
| 1.2 | AllocationChart donut | **HECHO** |
| 1.3 | P&L consolidado heatmap | **HECHO** (endpoint `/overview/daily-pnl`, sin componente en frontend) |
| 2.1 | Polymarket page | **HECHO** |
| 2.2 | Options page | **HECHO** |
| 2.3 | BTC Direction page | **HECHO** |
| 2.4 | Trade journal unificado | **HECHO** (4 agentes, faltan filtros por fecha/asset) |
| 3.1 | Risk panel (Sharpe, Sortino, VaR) | **PENDIENTE** |
| 3.2 | Drawdown chart | **PENDIENTE** |
| 3.3 | Monthly returns bars | **PENDIENTE** |
| 4.1 | SSE live ticker | **PENDIENTE** (SSE endpoint existe en `/live/stream`) |
| 4.2 | Notificaciones | **PENDIENTE** |
| 4.3 | Sidebar + cards clickeables | **HECHO** |
| 5.1 | Grid Stable API dedicada | **PENDIENTE** (datos reales ya usándose vía consortium) |

### Servicios

```
dashboard-api.service  → FastAPI :8000 (uvicorn, 2 workers) — activo
dashboard-web.service  → Next.js :3000 — activo
```

### Notas para el futuro agente

- **NO volver a crear** páginas que ya existen en `web/app/`.
- **NO tocar** `web/.next/` a menos que haya errores de build.
- Para rebuild: `rm -rf web/.next && cd web && npm run build && systemctl restart dashboard-web`.
- El plan `DASHBOARD_IMPROVEMENT_PLAN.md` sigue vigente como guía de fases.
- Los endpoints del backend (`api/routers/`) no se modificaron en esta intervención.

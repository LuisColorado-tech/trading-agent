# PLAN DE MEJORA — Dashboard Profesional para Live Trading

> **Objetivo**: Dashboard unificado para el consorcio, listo para live, con rendimientos consolidados y saldos en tiempo real.
> **Base**: React/Next.js + FastAPI existentes. Puntaje actual: 4/10 → Meta: 8/10.

---

## Auditoría rápida

| Dimensión | Puntaje | Problema principal |
|---|---|---|
| Arquitectura | 7/10 | Sólida pero 8 endpoints del backend sin usar |
| Completitud | 4/10 | Solo 2/5 agentes tienen página de detalle |
| Visualización | 5/10 | Sin drawdown, correlación, distribución, velas |
| Riesgo | 2/10 | Sin Sharpe, Sortino, VaR, expectancy |
| Tiempo real | 4/10 | SSE existe pero frontend no lo usa |
| Profesionalismo | 4/10 | Sin filtros, export, paginación, notificaciones |

---

## FASE 1: Consorcio Live — Overview Ejecutivo (Día 1-2)

### 1.1 Widget de rendimiento consorcio

**Qué**: Un bloque superior en el Overview que muestre el estado financiero total del consorcio.

```
┌─────────────────────────────────────────────────────────────┐
│  🏦 CONSORCIO ARTHAS                                        │
│                                                             │
│  Capital total:    $12,476     P&L hoy:    +$143 (+1.2%)   │
│  P&L mensual:      +$892       P&L anual:  +$2,341 (+18%)  │
│  Agentes activos:  4/5         DD global:  4.7%            │
└─────────────────────────────────────────────────────────────┘
```

**Entregables**:
- Nuevo componente `ConsortiumWidget.tsx`
- Nuevo endpoint `/overview/consortium` (agrega P&L diario/mensual/anual, DD global)
- Cambios en `page.tsx` (Overview) para mostrar arriba de los AgentCards

### 1.2 Portfolio Allocation — Donut chart

**Qué**: Gráfico circular que muestra cómo está distribuido el capital entre agentes.

```
Portfolio Allocation
┌──────────────────────┐
│   🍩 Donut chart     │  Crypto:      $10,000 (80%)
│                      │  Stocks:      $220    (2%)
│   Crypto 80%         │  Polymarket:  $976    (8%)
│   Poly 8%            │  Grid Stable: $500    (4%)
│   Grid 4%            │  Cold Wallet: $0      (0%)
│   Stocks 2%          │
└──────────────────────┘
```

**Entregables**:
- Nuevo componente `AllocationChart.tsx` (Recharts PieChart/Donut)
- Agregar al Overview

### 1.3 P&L diario consolidado — Heatmap

**Qué**: Un solo calendario de calor que combine el PnL diario de TODOS los agentes.

```
P&L Diario Consolidado — Mayo 2026
┌───┬───┬───┬───┬───┬───┬───┐
│ L │ M │ X │ J │ V │ S │ D │
├───┼───┼───┼───┼───┼───┼───┤
│   │   │   │ ■ │ ■ │ ■ │   │  ← verde intenso = +$100+
│   │ ■ │ ■ │ ■ │   │ ■ │   │  ← verde claro = +$10-99
│ ■ │ ■ │   │   │ ■ │   │   │  ← rojo = pérdida
└───┴───┴───┴───┴───┴───┴───┘
```

**Entregables**:
- Nuevo endpoint `/overview/daily-pnl`
- Nuevo componente `ConsolidatedCalendar.tsx`

---

## FASE 2: Páginas faltantes — Polymarket, Options, BTC Dir (Día 3-4)

### 2.1 Polymarket detail page (`/polymarket`)

**Qué**: Lo mismo que tiene Crypto pero para Polymarket. KPIs, posiciones abiertas, entry price buckets, historial.

**Entregables**:
- `web/app/polymarket/page.tsx` con KPIs, tabla posiciones, gráfico P&L
- Wire endpoint `/polymarket/session` y `/polymarket/positions` (ya existen)

### 2.2 Options detail page (`/options`) 

**Qué**: Theta farming stats: primas cobradas, contratos expirados, IV rank, posiciones abiertas.

**Entregables**:
- `web/app/options/page.tsx`
- Wire endpoints existentes

### 2.3 BTC Direction page (`/btc-direction`)

**Qué**: WR por timeframe, P&L, trades recientes, estado de vigilancia.

**Entregables**:
- `web/app/btc-direction/page.tsx`

### 2.4 Trade Journal unificado

**Qué**: Agregar Polymarket + Options + BTC Direction al journal de trades existente. Filtro por agente, fecha, símbolo.

**Entregables**:
- Nuevo endpoint `/trades/all` (unifica 5 tablas)
- `TradesFilter.tsx` (barra de filtros: agente, fecha, asset, P&L range)

---

## FASE 3: Risk & Performance Analytics (Día 5)

### 3.1 Panel de riesgo consolidado

**Qué**: Sharpe, Sortino, Max DD, VaR, expectancy para cada agente y consolidado.

**Entregables**:
- `RiskPanel.tsx` con KPI cards de riesgo
- API: calcular Sharpe/Sortino en `/overview/risk`

### 3.2 Drawdown chart

**Qué**: Gráfico de drawdown acumulado con zona sombreada bajo el agua.

**Entregables**:
- `DrawdownChart.tsx` (área roja bajo línea base)
- Agregar a Analytics

### 3.3 Monthly returns bar chart

**Qué**: Barras de retorno mensual (verde=positivo, rojo=negativo) para cada agente.

**Entregables**:
- `MonthlyReturns.tsx`
- Agregar a Analytics y a cada página de agente

---

## FASE 4: Tiempo Real y UX (Día 6)

### 4.1 Live Ticker con SSE

**Qué**: Cambiar el ticker de polling 30s a SSE (Server-Sent Events). Agregar crypto, flash verde/rojo en cambio de precio.

**Entregables**:
- Modificar `LiveTicker.tsx` para usar SSE (`/live/stream`)
- Agregar `EventSource` client-side

### 4.2 Notificaciones de trading

**Qué**: Toast notifications cuando un agente abre/cierra trade, o cuando el DD supera un umbral.

**Entregables**:
- `NotificationProvider.tsx` (React context)
- Suscribirse a Redis pub/sub via SSE para eventos de trading

### 4.3 Sidebar navegable + Click on cards

**Qué**: Agregar links a las nuevas páginas en Sidebar. Hacer clickeables los AgentCards (navegan a la página del agente).

**Entregables**:
- Modificar `Sidebar.tsx` (agregar Poly, Options, BTC Dir)
- Modificar `AgentCard.tsx` (onClick → navigate)

---

## FASE 5: Grid Stable real data (Día 7)

### 5.1 API para Grid Stable

**Qué**: El AgentCard de Grid Stable está hardcodeado. Necesita datos reales.

**Entregables**:
- Nuevo endpoint `/grid-stable/stats` (trades con strategy='GRID_STABLE')
- Agregar a `/overview/` el agente Grid Stable
- Actualizar AgentCard con datos vivos

---

## CRONOGRAMA

| Día | Fase | Qué se entrega |
|---|---|---|
| **1** | Consorcio | Widget consorcio + Allocation donut + P&L heatmap consolidado |
| **2** | Consorcio | Pulido Overview: mini-sparklines, métricas YTD/MTD, último update |
| **3** | Páginas | Polymarket detail page + Options detail page |
| **4** | Páginas | BTC Direction page + Trade journal unificado con filtros |
| **5** | Risk | Panel de riesgo, drawdown chart, monthly returns |
| **6** | UX | SSE ticker, notificaciones, sidebar navegable, cards clickeables |
| **7** | Grid | API Grid Stable, datos reales en AgentCard |

---

## COMPARATIVA: ANTES vs DESPUÉS

| Métrica | Antes | Después |
|---|---|---|
| Páginas de agente | 2/5 (Crypto, Stocks) | **5/5** (+Poly, Options, BTC Dir) |
| Widget consorcio | P&L consolidado simple | Capital total, P&L diario/mensual/anual, DD |
| Risk metrics | WR + PF básicos | Sharpe, Sortino, Max DD, expectancy, VaR |
| Charts | Equity + heatmap | +Donut allocation, drawdown, monthly bars, correlation |
| Trades journal | Crypto + Stocks | **5 agentes** unificados con filtros |
| Real-time | Polling 30s | **SSE** eventos en vivo + notificaciones |
| Grid Stable | Hardcodeado | **Datos reales** de DB |

---

## PRÓXIMO PASO

¿Arranco con la Fase 1 (Overview Consorcio)?

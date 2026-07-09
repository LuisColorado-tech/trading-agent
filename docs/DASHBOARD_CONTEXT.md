# DASHBOARD — Contexto para IA

> Arquitectura del dashboard del Arthas Trading System.
> Última actualización: Mayo 2026

---

## 1. Stack del dashboard

| Capa | Tecnología | Puerto | Servicio |
|------|-----------|--------|----------|
| **Frontend** | Next.js 14 (React) | `:3000` | `dashboard-web` |
| **API** | FastAPI + uvicorn | `:8000` | `dashboard-api` |
| **Proxy** | Nginx | `:80/443` | `nginx` |
| ~~Streamlit~~ | ~~DESACTIVADO~~ | ~~:8501~~ | ~~`trading-dashboard`~~ |

---

## 2. Archivos clave

```
/opt/trading/web/
├── app/
│   ├── page.tsx              # Overview — tarjetas de agentes + allocation + equity
│   ├── layout.tsx            # Layout global (Sidebar + LiveTicker)
│   ├── crypto/page.tsx       # Crypto agent detail
│   ├── stocks/page.tsx       # Stocks agent detail
│   ├── polymarket/page.tsx   # Polymarket agent detail
│   ├── snipe/page.tsx        # PolySnipe agent detail (NUEVO)
│   ├── btc-direction/page.tsx # BTC Direction legacy
│   ├── options/page.tsx      # Options agent detail
│   ├── grid-stable/page.tsx  # Grid Stable detail
│   ├── trades/page.tsx       # All trades
│   ├── signals/page.tsx      # Signals feed
│   └── analytics/page.tsx    # Analytics
├── components/
│   ├── Sidebar.tsx           # Navegación lateral
│   ├── AgentCard.tsx         # Tarjeta KPI de agente
│   ├── LiveTicker.tsx        # Ticker superior
│   ├── MiniEquity.tsx        # Equity curve widget
│   ├── AllocationChart.tsx   # Pie chart allocation
│   └── ConsortiumWidget.tsx  # Capital consolidado
├── lib/
│   ├── api.ts               # Cliente API (fetch wrapper)
│   └── fmt.ts               # Formateo de números/P&L
├── tailwind.config.ts
├── package.json
└── .next/                   # Build output (generado)
```

```
/opt/trading/api/
├── main.py                  # FastAPI app — incluye routers
├── db.py                    # Helpers: q(), q_one() → PostgreSQL
└── routers/
    ├── overview.py          # /overview/ + /overview/consortium
    ├── crypto.py            # /crypto/*
    ├── stocks.py            # /stocks/*
    ├── polymarket.py        # /polymarket/* + /polymarket/snipe/*
    ├── options.py           # /options/*
    └── live.py              # /live/prices
```

---

## 3. Cómo agregar un nuevo agente al dashboard

### Paso 1: API endpoints (`api/routers/polymarket.py`)
```python
@router.get('/snipe')
def snipe_trades(limit: int = 200):
    return q("SELECT * FROM snipe_trades ORDER BY timestamp_open DESC LIMIT :limit", {'limit': limit})

@router.get('/snipe/stats')
def snipe_stats():
    row = q_one("SELECT COUNT(*) ... FROM snipe_trades") or {}
    return {**row, 'win_rate': ..., 'balance': ...}
```

### Paso 2: Overview endpoint (`api/routers/overview.py`)
Agregar sección en `def overview()` con KPIs del agente y en `def consortium()` con balance.

### Paso 3: Cliente API (`web/lib/api.ts`)
```ts
snipe:       (limit?: number) => get<any[]>(`/polymarket/snipe?limit=${limit ?? 200}`),
snipeStats:  () => get<any>('/polymarket/snipe/stats'),
```

### Paso 4: Página del agente (`web/app/snipe/page.tsx`)
Componente React con KPIs, tabla de trades open/closed.

### Paso 5: Sidebar (`web/components/Sidebar.tsx`)
Agregar entrada en `NAV[]` con href, label, icon.

### Paso 6: Overview page (`web/app/page.tsx`)
Agregar `AgentCard` para el nuevo agente.

### Paso 7: Rebuild
```bash
cd /opt/trading/web && npm run build
systemctl restart dashboard-api dashboard-web
```

---

## 4. Agentes actuales en el dashboard

| Agente | Ruta | Página | Estado |
|--------|------|--------|--------|
| Overview | `/` | `page.tsx` | ✅ |
| Stocks | `/stocks` | `stocks/page.tsx` | ✅ |
| Crypto | `/crypto` | `crypto/page.tsx` | ✅ |
| Polymarket | `/polymarket` | `polymarket/page.tsx` | ✅ |
| **PolySnipe** | `/snipe` | `snipe/page.tsx` | ✅ NUEVO |
| Options | `/options` | `options/page.tsx` | ✅ |
| BTC Direction | `/btc-direction` | `btc-direction/page.tsx` | ⚠️ Legacy |
| Grid Stable | `/grid-stable` | `grid-stable/page.tsx` | ✅ |
| Trades | `/trades` | `trades/page.tsx` | ✅ |
| Señales | `/signals` | `signals/page.tsx` | ✅ |
| Analytics | `/analytics` | `analytics/page.tsx` | ✅ |

---

## 5. Heartbeat + Telegram

El `health_check.py` corre como `trading-health.service` y envía:
- **Heartbeat**: cada ~3h, tabla con estado de TODOS los agentes (incluye PolySnipe)
- **Alertas**: inmediatas si hay fallos en cualquier agente/servicio
- **Checks**: 13 checks (servicio, ciclos, logs, DB, datos, dashboard, DD, trades, balance, GridBot, Polymarket, PolySnipe, Stocks)

---

## 6. URLs

| Servicio | URL |
|----------|-----|
| Dashboard | `http://187.77.5.109:3000` |
| API | `http://187.77.5.109:8000` |
| ~~Streamlit~~ | ~~DESACTIVADO~~ |

---

## 7. Comandos de mantenimiento

```bash
# Ver estado
systemctl status dashboard-api dashboard-web nginx

# Rebuild tras cambios en React
cd /opt/trading/web && npm run build

# Reiniciar todo
systemctl restart dashboard-api && systemctl restart dashboard-web

# Logs
journalctl -u dashboard-api -f
journalctl -u dashboard-web -f
```

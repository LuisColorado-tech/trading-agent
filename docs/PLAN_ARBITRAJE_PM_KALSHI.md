# PLAN DE DESARROLLO — Arbitraje Polymarket ↔ Kalshi
## Estrategia de Arbitraje Cross-Platform BTC 1-Hour

**Creado:** 2026-05-02
**Fuentes:** `CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot` (179⭐) + `Polymarket/agents` (3,363⭐)
**Estado:** PLAN — Pendiente de ejecución

---

## 1. RESUMEN EJECUTIVO

Estrategia de **arbitraje libre de riesgo** entre Polymarket y Kalshi aprovechando
discrepancias de precio en mercados BTC 1-Hour Price. Cuando la suma de comprar
posiciones opuestas en ambas plataformas cuesta **menos de $1.00**, la ganancia
está matemáticamente garantizada sin importar el outcome.

| Métrica | Objetivo |
|---------|----------|
| Retorno mensual | ≥ 0.3% (conservador) |
| Riesgo por operación | **$0 (arbitraje puro)** |
| Frecuencia esperada | 1-5 oportunidades/día |
| Profit por trade | $0.01 - $0.15 por unidad |
| Capital requerido | ~$500-$1,000 entre ambas plataformas |
| Timeframe | Mercados 1h BTC (renuevan cada hora) |

---

## 2. DIAGNÓSTICO DE VIABILIDAD

### 2.1 Lo que YA tenemos (fortalezas)

| Componente | Estado | Archivo |
|-----------|--------|---------|
| Polymarket CLOB API | ✅ Integrado | `data/polymarket_feed.py` (usa `py_clob_client`) |
| Polymarket Gamma API | ✅ Integrado | `data/polymarket_feed.py` |
| Sesión Polymarket activa | ✅ | `poly_sessions` en DB |
| Trade executor PM | ✅ | `agents/poly_executor.py` |
| Strategy hub | ✅ | `core/poly_strategy_hub.py` |
| Risk management | ✅ | `risk/poly_risk.py` |
| Estrategia legged arb (intra-PM) | ✅ | `strategies/poly_legged_arb.py` |
| Dashboard Streamlit | ✅ | Puerto 8501 |
| Backtesting framework PM | ✅ | `scripts/backtest_polymarket.py` |

### 2.2 Lo que FALTA (brechas)

| Componente | Acción requerida |
|-----------|-----------------|
| **Kalshi API** | ❌ No existe integración. Hay que construir `data/kalshi_feed.py` |
| **Kalshi account** | Verificar si ya hay cuenta y fondos |
| **Cross-platform arb scanner** | Construir `strategies/cross_platform_arb.py` |
| **Executor multi-platform** | Modificar o crear executor sincronizado |
| **Dashboard PM+Kalshi** | Agregar panel al dashboard existente |
| **Backtest cross-platform** | Adaptar backtest para 2 plataformas |

### 2.3 ⚠️ DISPONIBILIDAD DE MERCADOS (verificado 2026-05-02)

**Polymarket:** ✅ BTC 15-min y 1-hour markets activos. Ya operando.

**Kalshi:** ❌ **Sin mercados BTC al 2-May-2026.** Kalshi actualmente solo tiene
mercados de deportes, política, entretenimiento y clima. Los mercados crypto/BTC
no están disponibles en este momento.

> **Importante:** El repo `CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot` fue
> creado en Noviembre 2025 y funcionó con mercados BTC en Kalshi que existían
> en ese momento. Kalshi puede volver a listar mercados crypto en el futuro.
> El código del bot es totalmente funcional y reutilizable cuando los mercados
> estén disponibles.

**Estrategia de monitoreo:**
- Agregar un health check que verifique disponibilidad de mercados BTC en Kalshi
- Si Kalshi lista mercados BTC → activar el pipeline de arbitraje

**Alternativa inmediata — Intra-Polymarket Legged Arbitrage:**
Mientras Kalshi no tenga BTC, usar `strategies/poly_legged_arb.py` que YA EXISTE
en la codebase. Esta estrategia hace arbitraje en 2 pasos dentro de Polymarket:
- Fase 1: Comprar YES barato (≤$0.30) en mercado volátil
- Fase 2: Cuando el precio rebota, comprar NO barato
- Si YES_cost + NO_cost < $0.95 → profit garantizado

### 2.4 Montos mínimos y requisitos

**Polymarket (YA operativo):**
- Sesión activa: `POLY_SESSION_005` con balance ~$971
- Comisión: ~0% en Polymarket actualmente
- Mínimo por trade: ~$1 (1 share)
- API key: configurada en `exchange_config.yaml`

**Kalshi (POR CONFIGURAR):**
- Registro en https://kalshi.com
- API key desde https://kalshi.com/account/api
- Fondear cuenta: mínimo ~$100-$200 para empezar
- Comisión: ~$0.07-$0.10 por contrato
- Mínimo por trade: ~$1 (1 contrato)
- Requiere KYC (US person o international con restricciones)

**Capital total recomendado para empezar:**
- Polymarket: ya tenés ~$971
- Kalshi: fondear $200-$500
- **Total: ~$1,200-$1,500 disponible para arbitraje**

---

## 3. MATEMÁTICA DE ARBITRAJE (del thesis.md)

### Escenario A: Poly Strike > Kalshi Strike
```
Poly Strike = $90,000 | Kalshi Strike = $89,000

Estrategia: Comprar Poly DOWN + Kalshi YES

Outcome:
  BTC < $89,000  → Poly DOWN wins ($1), Kalshi YES loses → $1.00
  BTC ≥ $90,000  → Poly DOWN loses, Kalshi YES wins ($1) → $1.00
  BTC entre ambos → Poly DOWN wins ($1), Kalshi YES wins ($1) → $2.00

Profit si Total Cost < $1.00 → arb libre de riesgo
```

### Escenario B: Poly Strike < Kalshi Strike
```
Poly Strike = $89,000 | Kalshi Strike = $90,000

Estrategia: Comprar Poly UP + Kalshi NO

Outcome:
  BTC < $89,000  → Poly UP loses, Kalshi NO wins ($1) → $1.00
  BTC ≥ $90,000  → Poly UP wins ($1), Kalshi NO loses → $1.00
  BTC entre ambos → Poly UP wins ($1), Kalshi NO wins ($1) → $2.00

Profit si Total Cost < $1.00 → arb libre de riesgo
```

### Escenario C: Strikes iguales
```
Poly Strike = Kalshi Strike = $90,000

Estrategia A: Poly DOWN + Kalshi YES
Estrategia B: Poly UP + Kalshi NO

El payout mínimo sigue siendo $1.00 en ambas.
Si cualquiera de Total Cost < $1.00 → arbitraje.
```

### Fórmula de profit
```python
def calculate_arb(poly_up, poly_down, kalshi_yes, kalshi_no, poly_strike, kalshi_strike):
    if poly_strike > kalshi_strike:
        # Comprar Poly DOWN + Kalshi YES
        total_cost = poly_down + kalshi_yes
    elif poly_strike < kalshi_strike:
        # Comprar Poly UP + Kalshi NO
        total_cost = poly_up + kalshi_no
    else:
        # Strikes iguales: probar ambas
        cost_a = poly_down + kalshi_yes
        cost_b = poly_up + kalshi_no
        total_cost = min(cost_a, cost_b)
    
    if total_cost < 1.00:
        profit = 1.00 - total_cost
        return profit  # En dólares por unidad
    return 0  # Sin oportunidad
```

---

## 4. ARQUITECTURA PROPUESTA

```
┌─────────────────────────────────────────────────────────────────┐
│                      CROSS-PLATFORM ARB ENGINE                    │
│                                                                   │
│  ┌──────────────────┐  ┌──────────────────┐                      │
│  │ Polymarket Feed  │  │  Kalshi Feed     │  ← NUEVO            │
│  │ data/polymarket_ │  │  data/kalshi_    │                      │
│  │ feed.py (existe) │  │  feed.py (nuevo) │                      │
│  └────────┬─────────┘  └────────┬─────────┘                      │
│           │                     │                                 │
│           ▼                     ▼                                 │
│  ┌─────────────────────────────────────────┐                     │
│  │       Arb Scanner (cada 1s - 5s)        │  ← NUEVO            │
│  │  strategies/cross_platform_arb.py       │                     │
│  │  - Match de mercados por strike         │                     │
│  │  - Calcula total cost por estrategia    │                     │
│  │  - Detecta oportunidades (TC < $1.00)   │                     │
│  └────────────────┬────────────────────────┘                     │
│                   │                                              │
│                   ▼                                              │
│  ┌─────────────────────────────────────────┐                     │
│  │         Arb Executor                     │  ← MODIFICAR       │
│  │  agents/cross_arb_executor.py            │                     │
│  │  - Ejecuta simultáneamente en ambas      │                     │
│  │  - Confirma fills antes de completar     │                     │
│  │  - Rollback si falla una pata            │                     │
│  └────────────────┬────────────────────────┘                     │
│                   │                                              │
│                   ▼                                              │
│  ┌─────────────────────────────────────────┐                     │
│  │       DB: cross_arb_trades               │  ← NUEVA TABLA     │
│  │  - Registro de trades de arbitraje       │                     │
│  │  - PnL, fees, slippage, timing           │                     │
│  └─────────────────────────────────────────┘                     │
│                                                                   │
│  ┌─────────────────────────────────────────┐                     │
│  │       Dashboard (Streamlit)              │  ← NUEVO PANEL     │
│  │  - Precios live PM + Kalshi              │                     │
│  │  - Oportunidades detectadas              │                     │
│  │  - Histórico de trades de arbitraje      │                     │
│  │  - PnL acumulado                         │                     │
│  └─────────────────────────────────────────┘                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. PLAN DE DESARROLLO — Ruta Dual

Dado que Kalshi no tiene mercados BTC actualmente, el plan sigue 2 rutas paralelas:

### RUTA A — Cross-Platform (Kalshi → futuro)
Cuando Kalshi vuelva a listar mercados BTC, ejecutar:

### RUTA B — Intra-Polymarket (INMEDIATA)
Refinar `strategies/poly_legged_arb.py` existente para ≥0.3% mensual AHORA.

### SEMANA 1-2 — Ruta B: Intra-Polymarket Legged Arb

| Día | Tarea | Entregable |
|-----|-------|-----------|
| 1-2 | Auditar `strategies/poly_legged_arb.py` actual | Código revisado |
| 2-3 | Backtest histórico: 30 días de datos Polymarket | Métricas reales |
| 3-4 | Optimizar parámetros: entry_price, hedge_trigger, profit_target | Config óptima |
| 4-5 | Paper trading 3 días con montos pequeños | Resultados paper |
| 5 | Evaluar si alcanza ≥0.3% mensual | Decisión |

### SEMANA 1-2 — Ruta A: Infraestructura Kalshi (preparación)

| Día | Tarea | Entregable |
|-----|-------|-----------|
| 1 | `data/kalshi_feed.py` — Connector a Kalshi API | Feed funcionando |
| 2 | `kalshi_market_monitor.py` — Health check que alerta cuando BTC está disponible | Monitor |
| 3 | Migración DB: tabla `cross_arb_trades` | Tabla creada |
| 3-4 | `strategies/cross_platform_arb.py` — Scanner (test con datos históricos) | Scanner |
| 4-5 | `agents/cross_arb_executor.py` — Ejecutor (paper mode) | Executor |

### SEMANA 3-4 — Backtesting + Dashboard

| Día | Tarea | Entregable |
|-----|-------|-----------|
| 1-3 | Backtest intra-PM legged arb | Reporte de métricas |
| 3-5 | Panel de arbitraje en dashboard Streamlit | Panel nuevo |

### SEMANA 4+ — Producción

- Si Ruta B confirma ≥0.3% → activar con fondos reales
- Si Kalshi lista BTC → activar Ruta A inmediatamente
- Ambos pueden correr simultáneamente

---

## 6. DETALLE TÉCNICO DE COMPONENTES NUEVOS

### 6.1 `data/kalshi_feed.py`

```python
"""
kalshi_feed.py — Fuente de datos para Kalshi Trade API v2.
"""
import requests
import time
from datetime import datetime, timezone
from loguru import logger

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
REST_URL = "https://trading-api.kalshi.com/trade-api/v2"  # Para órdenes

class KalshiFeed:
    def __init__(self, api_key: str, private_key_path: str):
        self.api_key = api_key
        # Kalshi usa RSA signing para órdenes
        # Solo lectura: GET /markets no requiere auth en v2
    
    def get_btc_markets(self, event_ticker: str = "BTC-") -> list[dict]:
        """Obtiene mercados BTC 1h activos con strikes y precios."""
        params = {"limit": 100, "event_ticker": event_ticker, "status": "open"}
        r = requests.get(f"{KALSHI_BASE}/markets", params=params)
        r.raise_for_status()
        return r.json().get("markets", [])
    
    def get_order_book(self, ticker: str) -> dict:
        """Order book para un mercado específico."""
        r = requests.get(f"{KALSHI_BASE}/markets/{ticker}/orderbook")
        r.raise_for_status()
        return r.json()
    
    def place_order(self, ticker: str, side: str, count: int, price: int) -> dict:
        """Coloca una orden en Kalshi (requiere auth RSA)."""
        # side: 'yes' o 'no', count: contratos, price: centavos (1-99)
        ...
```

### 6.2 `strategies/cross_platform_arb.py`

```python
"""
cross_platform_arb.py — Scanner de arbitraje Polymarket ↔ Kalshi.
"""
from dataclasses import dataclass
from typing import Optional

@dataclass
class ArbOpportunity:
    timestamp: datetime
    poly_strike: float
    kalshi_strike: float
    strategy: str  # "poly_down_kalshi_yes" | "poly_up_kalshi_no"
    poly_leg: str   # "Up" o "Down"
    kalshi_leg: str # "Yes" o "No"
    poly_cost: float
    kalshi_cost: float
    total_cost: float
    profit_per_unit: float
    profit_pct: float

class CrossPlatformArbScanner:
    def __init__(self, poly_feed, kalshi_feed):
        self.poly_feed = poly_feed
        self.kalshi_feed = kalshi_feed
        self.min_profit = 0.005  # Mínimo $0.005 por unidad
        self.max_slippage = 0.02  # 2% slippage asumido
    
    def scan(self) -> Optional[ArbOpportunity]:
        """Escanea una vez y devuelve la mejor oportunidad."""
        poly_data = self.poly_feed.get_current_btc_market()
        kalshi_markets = self.kalshi_feed.get_btc_markets()
        
        poly_strike = poly_data['price_to_beat']
        poly_prices = poly_data['prices']
        
        best_opp = None
        
        for km in kalshi_markets:
            kalshi_strike = km['strike']
            kalshi_yes = km['yes_ask'] / 100.0
            kalshi_no = km['no_ask'] / 100.0
            
            # Solo considerar mercados cercanos al strike de Poly (±$5000)
            if abs(kalshi_strike - poly_strike) > 5000:
                continue
            
            opp = self._check_arb(poly_strike, poly_prices, kalshi_strike, kalshi_yes, kalshi_no)
            if opp and (best_opp is None or opp.profit_per_unit > best_opp.profit_per_unit):
                best_opp = opp
        
        return best_opp
```

### 6.3 Migración DB — `cross_arb_trades`

```sql
CREATE TABLE IF NOT EXISTS cross_arb_trades (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Detección
    poly_strike FLOAT NOT NULL,
    kalshi_strike FLOAT NOT NULL,
    strategy TEXT NOT NULL,  -- 'poly_down_kalshi_yes' | 'poly_up_kalshi_no'
    
    -- Ejecución
    poly_order_id TEXT,
    kalshi_order_id TEXT,
    poly_fill_price FLOAT,
    kalshi_fill_price FLOAT,
    total_cost FLOAT,
    
    -- Resultado
    pnl FLOAT,
    pnl_pct FLOAT,
    fees_total FLOAT,
    slippage_total FLOAT,
    
    -- Meta
    execution_time_ms INTEGER,
    status TEXT DEFAULT 'pending',  -- pending, filled, partial, failed, rolled_back
    error_msg TEXT,
    
    -- Paper/Live
    mode TEXT DEFAULT 'paper'  -- 'paper' | 'live'
);

CREATE INDEX idx_cross_arb_ts ON cross_arb_trades(timestamp);
CREATE INDEX idx_cross_arb_status ON cross_arb_trades(status);
```

---

## 7. INTEGRACIÓN AL DASHBOARD

Agregar una pestaña "Arbitraje PM↔Kalshi" en el dashboard Streamlit existente con:

### Panel 1: Monitor en tiempo real
- Precio actual BTC (Binance)
- Polymarket: strike, Up/Down prices + spread
- Kalshi: strikes cercanos, Yes/No prices
- Heatmap de oportunidades (strike vs strike con color = profit potencial)

### Panel 2: Oportunidades activas
- Tabla con oportunidades detectadas en los últimos 60s
- Columnas: timestamp, strikes, strategy, total cost, profit/unit, profit %

### Panel 3: Histórico de trades
- Tabla de `cross_arb_trades` con filtros por fecha
- Gráfico de PnL acumulado
- Distribución de profits por trade (histograma)
- Métricas: total trades, win rate, PnL total, avg profit/trade

---

## 8. RIESGOS Y MITIGACIONES

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|-------------|---------|-----------|
| **Kalshi no tiene mercados BTC (CONFIRMADO)** | 100% | Alto | Ruta B: intra-PM legged arb como alternativa inmediata |
| Kalshi rechaza non-US residents | Media | Alto | Verificar antes de fondear |
| Slippage entre ejecución de ambas patas | Alta | Medio | Ejecutar en < 1s; rollback si falla |
| Una plataforma cae mid-trade | Baja | Alto | Timeout 5s; cancelar si no se completa |
| Spread desaparece entre detección y ejecución | Alta | Bajo | Re-check precios antes de ejecutar |
| Mercados sin liquidez suficiente | Media | Medio | Verificar order book depth antes de ejecutar |

---

## 9. ÉXITO DEL PROYECTO

### Criterios de aceptación
- [ ] Scanner detecta ≥1 oportunidad por día con profit > 0
- [ ] Backtest confirma ≥0.3% retorno mensual con datos reales
- [ ] Ejecutor sincronizado funciona en paper trading sin errores por 1 semana
- [ ] Dashboard muestra datos en tiempo real de ambas plataformas
- [ ] Si paper trading exitoso → activar con fondos reales progresivamente

### Próximo paso inmediato (Ruta B — HOY)
```bash
# 1. Auditar la estrategia intra-PM existente
cat /opt/trading/strategies/poly_legged_arb.py

# 2. Correr backtest con datos reales
python /opt/trading/scripts/backtest_polymarket.py --strategy legged_arb --days 30

# 3. Si backtest OK → paper trading con $50
python /opt/trading/strategies/poly_legged_arb.py --mode paper --capital 50
```

### Próximo paso (Ruta A — cuando Kalshi liste BTC)
```bash
# El kalshi_feed.py y scanner estarán listos para activar
python /opt/trading/strategies/cross_platform_arb.py --mode paper
```

---

## 10. APÉNDICE: Referencias

- **Repositorio fuente:** https://github.com/CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot
- **Tesis de arbitraje:** thesis.md en el repo (incluida en sección 3)
- **Polymarket AI Agents:** https://github.com/Polymarket/agents
- **Polymarket CLOB API:** https://docs.polymarket.com
- **Kalshi Trade API v2:** https://docs.kalshi.com
- **Código arbitrage_bot.py original:** `backend/arbitrage_bot.py` en el repo fuente

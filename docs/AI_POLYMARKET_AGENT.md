# POLYMARKET AGENT — Mercados de Predicción Crypto

> Estrategia de trading en mercados de predicción (Polymarket) usando señales técnicas.
> Estado: **ACTIVO** — en validación de edge
> Última actualización: Abril 2026

---

## 1. Resumen ejecutivo

El Polymarket Agent apuesta en mercados de predicción tipo "¿Subirá BTC esta semana?" usando señales técnicas del Trading Agent. La idea: si la señal técnica da SELL con alta confluencia y hay un mercado predictivo activo sobre esa dirección, tenemos edge sobre el precio del mercado (que refleja sentimiento general, no señales técnicas).

**Resultados actuales**:
- Win Rate: **~60%** (bueno en teoría)
- PnL: **-$70** (malo en práctica)
- Problema: R:R desequilibrado — las pérdidas son más grandes que las ganancias; se gana en frecuencia pero se pierde en magnitud.
- Estado: bajo vigilancia. El edge de 15% se aplicó para mejorar R:R.

**Balance paper**: $1,000 USDC inicial.

---

## 2. Dos estrategias — solo una activa

| Estrategia | Estado | Descripción |
|---|---|---|
| `SIGNAL_BASED` | ✅ ACTIVA | Usa señales técnicas del Trading Agent para detectar edge en mercados Polymarket |
| `PREDICTION_LLM` | ❌ DESACTIVADA | Usaba Claude/OpenAI para predecir. Sin API key configurada. 43 trades, 0 wins, -$582. `ENABLED=False` en `prediction.py` |

---

## 3. Arquitectura

```
scripts/run_polymarket.py            ← Entry point (systemd: polymarket-agent.service)
    │
    └── agents/market_scanner.py     ← Descubre mercados Polymarket elegibles
            │
            └── strategies/signal_based_poly.py  ← Estrategia SIGNAL_BASED
                    ├── data/polymarket_feed.py   ← API Polymarket (Gamma + CLOB)
                    ├── agents/poly_executor.py   ← Ejecuta apuestas (CLOB)
                    ├── agents/poly_monitor.py    ← Monitorea posiciones abiertas
                    └── risk/poly_risk.py         ← Filtros de riesgo Polymarket

-- SEÑALES compartidas (tabla `signals` en DB):
   Trading Agent → escribe señales técnicas
   Polymarket Agent → lee señales para SIGNAL_BASED
   BTC Direction → lee señales para momentum
```

**Ciclo** (cada `SCAN_INTERVAL=300` segundos = 5 min):
1. `market_scanner` obtiene mercados activos de Gamma API
2. Aplica filtros de mercado (volumen, precio YES, keywords, días)
3. Para cada mercado elegible: calcula edge con señal técnica
4. Si edge ≥ 15%: calcula Kelly sizing → ejecuta en CLOB
5. `poly_monitor` revisa posiciones → cierra por TP/SL/expiración

---

## 4. Flujo de la estrategia SIGNAL_BASED

### Paso 1: Descubrir mercados

Gamma API: `GET https://gamma-api.polymarket.com/markets`

Filtros aplicados:
```python
min_volume   = 20_000   # USD mínimo (filtrar mercados con poca liquidez)
min_liquidity = 5_000   # USD mínimo liquidez
max_end_days  = 30      # No apostar a más de 30 días
min_end_hours = 2       # No apostar si resuelve en <2 horas
min_price_yes = 0.20    # YES debe costar al menos $0.20
max_price_yes = 0.80    # YES no puede costar más de $0.80
categories    = ['crypto']   # SOLO crypto
keywords      = ['BTC', 'Bitcoin', 'ETH', 'Ethereum', 'crypto', 'cryptocurrency']
```

### Paso 2: Detectar edge

Para cada mercado que pasa los filtros:
1. Identificar si la pregunta es alcista o bajista ("sube", "above", "below"...)
2. Buscar señal técnica reciente en DB tabla `signals` para ese asset
3. Calcular divergencia entre precio de mercado y señal:

```python
edge = abs(signal_probability - market_price_yes)
# donde signal_probability es 0.7 si la señal es fuerte, 0.5 si es débil
# y market_price_yes es el precio actual del token YES (ej: 0.45)
# si señal dice 70% SELL y mercado dice 45% de que baje → edge = 25%
```

### Paso 3: Kelly sizing

```python
kelly_fraction = 0.25    # Cuarto Kelly (conservador)
position_size = kelly_fraction × edge × balance
position_size = min(position_size, max_position_pct × balance)
# max_position_pct = 2.5% → máximo $25 por posición con balance $1,000
```

### Paso 4: Ejecutar en CLOB

- API: `https://clob.polymarket.com`
- Autenticación: ECDSA sobre Polygon (chain_id=137)
- Tipo de orden: Market order (entrada y salida inmediatas)

---

## 5. Parámetros de riesgo (actualizados Abr 2026)

```yaml
polymarket:
  risk:
    max_position_pct: 2.5        # ↓ era 4.0% (reducir DD mientras se valida)
    max_total_exposure_pct: 40.0 # Max 40% del balance en posiciones
    max_concurrent_positions: 5  # Max 5 posiciones simultáneas
    min_edge_pct: 15.0           # ↑ era 10.0% (mejorar R:R, filtrar mercados ajustados)
    kelly_fraction: 0.25         # Cuarto Kelly (conservador)
    early_exit_profit: 0.85      # Cerrar si precio YES sube 85% (TP)
    early_exit_loss: 0.10        # Cerrar si precio YES baja 10% (SL)
```

**Razonamiento de los cambios**:
- `min_edge_pct 10%→15%`: Con 10%, muchos mercados "ajustados" entraban con edge casi nulo → pérdidas por spread/slippage
- `max_position_pct 4%→2.5%`: Reducir exposición máxima mientras se valida que el edge es real

---

## 6. Gestión de posiciones abiertas (poly_monitor)

**Archivo**: `agents/poly_monitor.py`

Cada 5 min revisa todas las posiciones abiertas:

1. **TP (early_exit_profit=0.85)**: Si el precio YES llega al 85% del target → cerrar y realizar ganancia
   - Ejemplo: apostaste que BTC sube (YES = $0.45). Si sube a $0.85 → cerrar
2. **SL (early_exit_loss=0.10)**: Si el precio YES baja al 10% → cerrar y limitar pérdida
   - Ejemplo: apostaste YES $0.45. Si baja a $0.10 → cerrar (perdiste $0.35/dólar apostado)
3. **Expiración**: El mercado resuelve → Gamma API confirma resultado → contabilizar PnL

---

## 7. Tabla `signals` — protocolo de comunicación entre agentes

Esta tabla es el **canal compartido** entre el Trading Agent (escritor) y Polymarket + BTC Direction (lectores).

```sql
CREATE TABLE signals (
    id SERIAL PRIMARY KEY,
    asset VARCHAR(10),           -- BTC, ETH, SOL, etc.
    direction VARCHAR(5),        -- BUY / SELL
    timeframe VARCHAR(5),        -- 15m, 1h, etc.
    strategy VARCHAR(50),        -- TREND_MOMENTUM, BREAKOUT, etc.
    score NUMERIC,               -- 0-100 (confluencia de indicadores)
    regime VARCHAR(20),          -- TREND_DOWN, BREAKOUT_DOWN, etc.
    timestamp TIMESTAMPTZ,
    expires_at TIMESTAMPTZ       -- cuándo pierde validez esta señal
);
```

El Polymarket Agent busca señales recientes (< 15 min de antigüedad) antes de evaluar edge.

---

## 8. prediction.py — estrategia DESACTIVADA

**Archivo**: `strategies/prediction.py`

```python
ENABLED = False   # ← Desactivado. Ver razón abajo.
```

**Por qué está desactivada**:
- Requería `OPENAI_API_KEY` (no configurada en `.env` del VPS)
- Paper results antes de deshabilitar: **43 trades, 0 wins, -$582**
- Sin API key, Claude generaba predicciones aleatorias → pérdida constante

**Cómo reactivar** (solo si se configura API key):
```python
# En strategies/prediction.py:
ENABLED = True  # cambiar a True
# Y agregar en config/.env:
OPENAI_API_KEY=sk-...
```

---

## 9. Base de datos — tablas del Polymarket Agent

```sql
-- Sesiones paper
CREATE TABLE poly_sessions (
    id SERIAL PRIMARY KEY,
    session_name VARCHAR(50),
    status VARCHAR(20),
    initial_balance_usd NUMERIC,
    current_balance_usd NUMERIC,
    total_bets INTEGER,
    winning_bets INTEGER,
    started_at TIMESTAMPTZ
);

-- Posiciones
CREATE TABLE poly_positions (
    id SERIAL PRIMARY KEY,
    market_id VARCHAR(100),      -- ID del mercado Polymarket
    question TEXT,               -- La pregunta del mercado
    side VARCHAR(5),             -- YES / NO
    entry_price NUMERIC,         -- Precio de entrada (0-1)
    current_price NUMERIC,
    amount_usdc NUMERIC,         -- USDC apostados
    potential_pnl NUMERIC,
    realized_pnl NUMERIC,
    status VARCHAR(20),          -- OPEN / CLOSED
    exit_reason VARCHAR(30),     -- TP / SL / EXPIRED / RESOLVED
    signal_score NUMERIC,        -- Score de la señal que catalizó
    edge_at_entry NUMERIC,       -- Edge calculado al entrar
    opened_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ
);

-- Mercados indexados (para cache y análisis)
CREATE TABLE poly_markets (
    id SERIAL PRIMARY KEY,
    market_id VARCHAR(100) UNIQUE,
    question TEXT,
    category VARCHAR(50),
    price_yes NUMERIC,
    volume_24h NUMERIC,
    end_date TIMESTAMPTZ,
    last_updated TIMESTAMPTZ
);
```

---

## 10. APIs utilizadas

```
Gamma API (datos públicos):
  Base: https://gamma-api.polymarket.com
  GET /markets              → listar mercados con filtros
  GET /events?slug={slug}   → resolver mercado por slug (CORRECTO para fast markets)
  GET /markets/{id}         → detalle de un mercado

CLOB API (ejecución, requiere auth):
  Base: https://clob.polymarket.com
  POST /order               → crear orden mercado
  DELETE /order/{id}        → cancelar orden
  GET /midpoint             → precio midpoint de un token
  GET /book                 → orderbook completo
  Chain: Polygon (chain_id=137)
  Auth: ECDSA firma de cada request
```

---

## 11. Cómo diagnosticar el Polymarket Agent

```bash
# Logs en tiempo real:
journalctl -u polymarket-agent -f

# Posiciones abiertas:
set -a && source /opt/trading/config/.env && set +a
/opt/trading/venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
e = create_engine(os.environ['DB_URL'])
with e.connect() as c:
    r = c.execute(text('''
        SELECT question, side, entry_price, current_price, amount_usdc, edge_at_entry
        FROM poly_positions WHERE status='OPEN'
        ORDER BY opened_at DESC
    ''')).fetchall()
    print(f'{len(r)} posiciones abiertas')
    [print(' ', row) for row in r]
"

# Win rate y PnL total:
/opt/trading/venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
e = create_engine(os.environ['DB_URL'])
with e.connect() as c:
    r = c.execute(text('''
        SELECT COUNT(*) total,
               SUM(CASE WHEN realized_pnl>0 THEN 1 ELSE 0 END) wins,
               SUM(realized_pnl) pnl
        FROM poly_positions WHERE status='CLOSED'
    ''')).fetchone()
    wr = r[1]/r[0]*100 if r[0] else 0
    print(f'Total: {r[0]} | WR: {wr:.1f}% | PnL: \${r[2]:+.2f}')
"
```

---

## 12. Análisis del problema actual y roadmap

**Problema identificado**: Win Rate = 60% PERO PnL = -$70

Esto indica que el agente **gana en frecuencia, pierde en magnitud**:
- Las apuestas ganadas son pequeñas (entramos cuando el market ya reflejó parte del movimiento)
- Las apuestas perdidas son grandes (SL en $0.10 = -78% de la apuesta)

**Solución en evaluación**:
1. Mejorar el timing de entrada (edge más alto = mejor precio de entrada)
2. El aumento de `min_edge_pct 10%→15%` debería mejorar el R:R
3. Evaluar en próximas 2-3 semanas si el ajuste funciona

**Criterio de decisión**:
- Si PnL ≥ 0 después de 50 trades más → continuar y aumentar size
- Si PnL sigue negativo → desactivar hasta revisar estrategia de sizing

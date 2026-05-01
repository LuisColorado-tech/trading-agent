# POLYMARKET AGENT — Mercados de Predicción Crypto

> Estrategia de trading en mercados de predicción (Polymarket) usando señales técnicas.
> Estado: **ACTIVO v3** — bugs críticos corregidos, en validación post-fix
> Última actualización: 2026-05-01 (v3 — post-auditoría general)

---

## 1. Resumen ejecutivo

El Polymarket Agent apuesta en mercados de predicción tipo "¿Subirá BTC esta semana?" usando señales técnicas del Trading Agent. La tesis: si las señales macro de BTC (1h/4h) muestran dirección clara y hay un mercado predictivo activo sobre esa dirección, existe edge sobre el precio del mercado.

**Resultados reales (DB, 4 sesiones, 137 trades cerrados)**:
- Win Rate global: **29.9%**
- Profit Factor: **0.37**
- PnL total: **-$961.17**
- EV por trade: **-$7.02**

**Diagnóstico v3 (2026-05-01 — auditoría general)**:
- Causa raíz #1: **Edge = abs(0.50 - price)** era una tautología matemática que causaba selección adversa inversa. Entraba sistemáticamente en trades con `price_yes ≤ 0.40` (baja probabilidad real) filtrando fuera los de `0.42-0.58` (WR=50%, EV=+$2.28). → **Edge reemplazado por `tf_conviction * 0.15`.**
- Causa raíz #2: `min_price_yes = 0.35` aún permitía entradas en zona de pérdida. → **Subido a 0.42.**
- Causa raíz #3: `estimated_prob = entry_price + edge` inflaba artificialmente la probabilidad (0.35→0.50), causando Kelly sizing 2-3× mayor al correcto. → **Corregido a `entry_price * (1 + edge * 0.5)`.**
- Causa raíz #4: `max_spread = 1.05` configurado en YAML pero nunca aplicado en código. → **Forzado en `polymarket_feed.py`.**
- Causa raíz #5: Dynamic SL permitía perder hasta 40% del capital por trade. → **Reducido a 25%.**
- Causa raíz #6: `max_concurrent = 5`, `max_position = 2.5%` demasiado altos para fase de validación. → **Reducidos a 3 y 1.5%.**

**Balance paper**: $1,000 USDC inicial → $731.37 actual (-$268.63). POLY_SESSION_004 activa.

**Estado DD HALT**: Drawdown 26.9% supera el circuit breaker de 20%. El agente no abre nuevas posiciones hasta que las abiertas se cierren y el DD baje.

---

## 2. Estrategias activas

| Estrategia | Estado | Descripción |
|---|---|---|
| `SIGNAL_BASED` | ✅ ACTIVA (v3) | Señales macro BTC 1h/4h + market_regime. Solo entra en zona 0.42–0.58 |
| `TAIL_END` | ✅ ACTIVA | Mercados near-resolution (>2h, <24h) con señal confirmada |
| `LATE_ENTRY` | ❌ DESACTIVADA | Datos insuficientes para validar edge |
| `COMBINATORIAL` | ❌ DESACTIVADA | EV=-$3.32/trade en 17 trades; no tiene edge comprobable |
| `LEGGED_ARB` | ❌ DESACTIVADA | WR=0% en 10 trades, -$176.81. Entraba en mercados no-crypto |
| `PREDICTION_LLM` | ❌ DESACTIVADA | 43 trades/0 wins/-$582. Sin API key de OpenAI |

---

## 3. Arquitectura

```
scripts/run_polymarket.py            ← Entry point (systemd: polymarket-agent.service)
    │
    └── agents/market_scanner.py     ← Descubre mercados Polymarket elegibles
            │
            └── strategies/signal_based_poly.py  ← Estrategia SIGNAL_BASED (v3)
                    ├── data/polymarket_feed.py   ← API Polymarket (Gamma + CLOB) + filtro spread
                    ├── agents/poly_executor.py   ← Ejecuta apuestas (CLOB)
                    ├── agents/poly_monitor.py    ← Monitorea posiciones + SL dinámico 25%
                    └── risk/poly_risk.py         ← Filtros de riesgo + Kelly sizing corregido

-- SEÑALES compartidas (tabla `signals` en DB):
   Trading Agent → escribe señales técnicas
   Polymarket Agent → lee señales macro 1h/4h para SIGNAL_BASED
   BTC Direction → lee señales para momentum
```

**Ciclo** (cada `SCAN_INTERVAL=300` segundos = 5 min):
1. `market_scanner` obtiene mercados activos de Gamma API
2. Aplica filtros: volumen, liquidez, precio YES (0.42–0.58), spread (≤1.05), keywords, días
3. Para cada mercado elegible: calcula edge con conteo de timeframes macro
4. Si edge ≥ 10%: calcula Kelly sizing corregido → ejecuta en CLOB
5. `poly_monitor` revisa posiciones → cierra por TP/SL/expiración/trailing

---

## 4. Flujo de la estrategia SIGNAL_BASED (v3)

### Paso 1: Descubrir mercados

Gamma API: `GET https://gamma-api.polymarket.com/markets`

Filtros aplicados (exchange_config.yaml):
```python
min_volume      = 30_000   # USD mínimo
min_liquidity   =  5_000   # USD mínimo liquidez
max_end_days    =     14   # No apostar a más de 14 días
min_end_hours   =      2   # No apostar si resuelve en <2h
min_price_yes   =   0.42   # ★ subido de 0.35 (v3: zona 0.42-0.58 WR=50% EV=+$2.28)
max_price_yes   =   0.58   # bajado de 0.80 (v2)
max_spread      =   1.05   # ★ AHORA SÍ aplicado en código (v3: rake ≤ 5%)
categories      = ['crypto']
keywords        = ['BTC','Bitcoin','ETH','Ethereum','crypto','cryptocurrency']
```

### Paso 2: Detectar edge (CORREGIDO v3)

**Fórmula anterior (v2 — BUG)**: `edge = abs(0.50 - price_yes)` → tautología, selección adversa inversa.

**Fórmula actual (v3)**: 
```python
# Conteo de timeframes macro con dirección clara (consulta DB signals 1h/4h)
buys, sells = contar_señales_macro_1h_4h()

# Convicción: qué tan unánime es la dirección (0.0 = empate, 1.0 = todos igual)
tf_conviction = abs(buys - sells) / (buys + sells)

# Edge = convicción * 0.15 (máximo 15% cuando todos los TF coinciden)
edge = tf_conviction * 0.15
```

Esto significa que el edge refleja la **fuerza real de la señal macro**, no la distancia arbitraria al 50%.

### Paso 3: Kelly sizing (CORREGIDO v3)

**Fórmula anterior (v2 — BUG)**: `estimated_prob = entry_price + edge` → 0.35 + 0.15 = 0.50 (inflado).

**Fórmula actual (v3)**:
```python
estimated_prob = min(0.75, entry_price * (1.0 + edge * 0.5))
# Ej: entry=0.45, edge=0.15 → 0.45 * 1.075 = 0.48 (7.5% uplift máximo)
```

El Kelly criterion en `poly_risk.py` usa `p = entry_price + edge` → recibe `estimated_prob` del paso anterior.

```python
kelly_fraction = 0.25       # Cuarto Kelly base (dinámico según edge)
max_position_pct = 1.5%     # ↓ era 2.5% (v3: reducir exposición)
max_concurrent = 3          # ↓ era 5 (v3: menos trades simultáneos)
```

### Paso 4: Ejecutar en CLOB

- API: `https://clob.polymarket.com`
- Autenticación: ECDSA sobre Polygon (chain_id=137)
- Tipo de orden: Market order

---

## 5. Parámetros de riesgo (actualizados May 2026 — v3)

```yaml
polymarket:
  market_filters:
    min_volume: 30000
    min_liquidity: 5000
    max_end_days: 14
    min_end_hours: 2
    min_price_yes: 0.42            # ★ 0.35→0.42 (v3)
    max_price_yes: 0.58
    max_spread: 1.05               # ★ AHORA aplicado en polymarket_feed.py (v3)

  risk:
    max_position_pct: 1.5          # ★ 2.5→1.5 (v3: protección en validación)
    max_total_exposure_pct: 30.0   # ★ 40→30 (v3)
    max_concurrent_positions: 3    # ★ 5→3 (v3)
    min_edge_pct: 10.0             # Edge mínimo 10% (v2)
    kelly_fraction: 0.25           # Cuarto Kelly (dinámico según edge)
    early_exit_profit: 0.85        # TP fijo
    early_exit_loss: 0.10          # SL fijo (fallback)
    sl_loss_fraction: 0.25         # ★ 0.40→0.25 (v3: max pérdida 40%→25%)
    sl_trailing_activate: 0.72     # Activar trailing TP
    sl_trailing_step: 0.04         # Avance trailing
    max_session_drawdown_pct: 20.0 # Circuit breaker
    consecutive_losses_halt: 5     # Halt si 5 pérdidas seguidas
```

---

## 6. Gestión de posiciones abiertas (poly_monitor)

**Archivo**: `agents/poly_monitor.py`

Cada 5 min revisa todas las posiciones abiertas. Prioridad de cierre:

1. **Resolución detectada**: Si `price_yes ≥ 0.95` o `≤ 0.05` → RESOLVED_WIN / RESOLVED_LOSS
2. **Trailing TP**: Si precio ≥ 0.72, activa trailing con step=0.04 → TAKE_PROFIT
3. **TP fijo**: Si precio ≥ 0.85 → TAKE_PROFIT (fallback)
4. **SL dinámico (v3)**: Si precio ≤ `entry * (1 - 0.25)` → STOP_LOSS (max -25% capital)
5. **SL fijo**: Si precio ≤ 0.10 → STOP_LOSS (fallback)
6. **Expiración**: Token sin precio + fecha pasada → EXPIRED_UNKNOWN

**Cambio clave v3**: SL dinámico pasó de `entry * 0.60` (max -40%) a `entry * 0.75` (max -25%).

---

## 7. Tabla `signals` — protocolo de comunicación entre agentes

Tabla compartida entre Trading Agent (escritor) y Polymarket + BTC Direction (lectores).

```sql
CREATE TABLE signals (
    id SERIAL PRIMARY KEY,
    asset VARCHAR(10),
    direction VARCHAR(5),        -- BUY / SELL
    timeframe VARCHAR(5),        -- 15m, 1h, 4h, etc.
    strategy VARCHAR(50),
    score NUMERIC,
    regime VARCHAR(20),
    timestamp TIMESTAMPTZ,
    expires_at TIMESTAMPTZ
);
```

Polymarket Agent usa **DISTINCT ON (timeframe)** para obtener UNA señal por timeframe (1h, 4h). Solo señales de las últimas 4 horas. El conteo de BUY vs SELL en esos timeframes determina la dirección macro y el edge.

---

## 8. Base de datos — tablas del Polymarket Agent

```sql
poly_sessions          -- sesiones paper (balance, PnL, trades, drawdown)
poly_positions         -- posiciones individuales (entry/exit, PnL, edge, close_reason)
poly_markets           -- mercados indexados (cache de Gamma API)
```

Ver `docs/AI_MASTER.md` sección 7 para queries de diagnóstico.

---

## 9. APIs utilizadas

```
Gamma API (datos públicos):
  GET /markets              → listar mercados con filtros
  GET /events?slug={slug}   → resolver mercado por slug
  GET /markets/{id}         → detalle de un mercado

CLOB API (ejecución, requiere auth ECDSA):
  POST /order               → crear orden
  GET /midpoint             → precio midpoint de un token
  GET /book                 → orderbook completo
  Chain: Polygon (chain_id=137)
```

---

## 10. Diagnóstico y comandos

```bash
# Logs en tiempo real:
journalctl -u polymarket-agent -f

# Estado del agente:
systemctl status polymarket-agent

# Backtest de trades históricos (análisis DB):
cd /opt/trading && venv/bin/python3 scripts/backtest_polymarket.py --all-sessions
cd /opt/trading && venv/bin/python3 scripts/backtest_polymarket.py --scan-combos  # SL/TP óptimo

# Posiciones abiertas:
venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
from dotenv import load_dotenv; load_dotenv('config/.env')
e = create_engine(os.environ['DB_URL'])
with e.connect() as c:
    r = c.execute(text(\"SELECT question, side, entry_price, cost_basis, pnl FROM poly_positions WHERE status='OPEN'\")).fetchall()
    print(f'{len(r)} posiciones abiertas')
    [print(dict(row._mapping)) for row in r]
"

# Resumen global:
venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
from dotenv import load_dotenv; load_dotenv('config/.env')
e = create_engine(os.environ['DB_URL'])
with e.connect() as c:
    r = c.execute(text(\"SELECT COUNT(*) t, SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) w, SUM(pnl) p FROM poly_positions WHERE status='CLOSED' AND close_reason!='SESSION_RESET'\")).fetchone()
    print(f'Trades={r[0]} | WR={r[1]/r[0]*100:.1f}% | PnL=\${r[2]:+.2f}')
"
```

---

## 11. Historial de bugs y fixes

| Fecha | Bug | Severidad | Fix | Archivo |
|---|---|---|---|---|
| 2026-04-28 | `min_price_yes = 0.20` permitía entradas en zona WR=0-5% | CRÍTICA | Subido a 0.35 | exchange_config.yaml |
| 2026-04-28 | COMBINATORIAL EV=-$3.32, LEGGED_ARB WR=0% | ALTA | Estrategias desactivadas | exchange_config.yaml |
| 2026-04-28 | `estimated_prob = 1.0` (YES) o `0.0` (NO) rompía Kelly | ALTA | Corregido a `entry_price + edge` | signal_based_poly.py |
| 2026-05-01 | **Edge = abs(0.50 - price)** — tautología, selección adversa inversa | **CRÍTICA** | **`tf_conviction * 0.15`** | signal_based_poly.py:383 |
| 2026-05-01 | `min_price_yes = 0.35` aún muy bajo (WR<30% en 0.35-0.41) | ALTA | Subido a 0.42 | config + 2 .py |
| 2026-05-01 | `max_spread` configurado pero nunca leído en código | ALTA | `price_yes+price_no > 1.05 → None` | polymarket_feed.py:165 |
| 2026-05-01 | `estimated_prob = entry_price + edge` inflaba Kelly 2-3× | ALTA | `entry_price * (1 + edge * 0.5)` | signal_based_poly.py:412 |
| 2026-05-01 | SL dinámico permitía -40% del capital | MEDIA | `SL_LOSS_FRACTION 0.40→0.25` | poly_monitor.py + config |
| 2026-05-01 | Risk sizing muy alto para fase de validación | MEDIA | `max_position 2.5%→1.5%`, `max_concurrent 5→3` | config |

---

## 12. Roadmap y criterios de decisión

**Estado actual**: DD HALT — drawdown 26.9% supera circuit breaker 20%. 1 posición abierta.

**Plan de validación v3**:
- Esperar a que la posición abierta cierre y el DD baje de 20%
- Observar 50 trades con la nueva lógica (edge corregido, filtro 0.42, Kelly realista, SL 25%)
- Criterio de éxito: PnL ≥ $0 y WR ≥ 45% en esos 50 trades

**Criterio de continuación**:
- Si PnL ≥ 0 después de 50 trades → continuar paper y aumentar gradualmente `max_position_pct`
- Si PnL sigue negativo → **pausar el agente** y reconsiderar si las señales técnicas de crypto tienen poder predictivo real sobre mercados de Polymarket

**Plan de mejora completo**: Ver `docs/IMPROVEMENT_PLAN.md`.

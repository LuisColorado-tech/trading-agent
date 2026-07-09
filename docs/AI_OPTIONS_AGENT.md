# OPTIONS AGENT — Theta Farming en Deribit

> Estrategia de venta de PUTs OTM en BTC para cobrar prima de tiempo (theta).
> Estado: **ACTIVO en paper_mode** — sin resultados históricos aún (lanzado Abr 2026)
> Última actualización: Abril 2026

---

## 1. Resumen ejecutivo

El Options Agent vende PUTs OTM semanales en BTC a través de Deribit. La filosofía es simple: el 80% de las opciones OTM expiran sin valor. El vendedor cobra la prima y, si BTC no cae hasta el strike, se queda con todo.

**Estado actual**: `paper_mode=True`. Usa precios `mark` (no bid) para simular de forma realista. Todavía no hay suficientes trades para evaluar edge.

**Balance paper**: $2,000 USD inicial.

---

## 2. Arquitectura

```
scripts/run_options.py               ← Entry point (systemd: options-agent.service)
    │
    └── agents/options_agent.py      ← Orquestador
            ├── strategies/theta_farming.py   ← Lógica completa
            └── core/deribit_session_manager.py  ← Auth + API calls (con mutex)
```

**Ciclos**:
- **Scan de nuevas entradas**: cada `SCAN_INTERVAL=3600` segundos (1 hora)
- **Monitor de posiciones abiertas**: cada `MONITOR_INTERVAL=300` segundos (5 min)

---

## 3. Lógica de entrada — 7 filtros en orden

Todos los filtros deben cumplirse para abrir una posición.

### Filtro 1: IV Rank ≥ 20% (lookback 252 días)
```
IV Rank = (IV_actual - IV_min_252d) / (IV_max_252d - IV_min_252d)
```
- Lookback: **252 días** (estándar del sector = 1 año de trading)
- Antes era 30 días → demasiado corto, distorsionaba el rank
- Si IV Rank < 20%: la prima no compensa el riesgo, no entrar

### Filtro 2: DTE entre 3 y 21 días (óptimo: 5-10)
- `min_dte = 3` — menos de 3 días: poco theta que decaiga
- `max_dte = 21` — más de 21 días: exposición a eventos macro
- Rango óptimo `target_dte_min=5`, `target_dte_max=10` → mejor theta/gamma ratio
- Múltiples expiraciones disponibles: candidatos se filtran por DTE óptimo primero

### Filtro 3: Delta del PUT ≤ 0.20 (probabilidad ITM ≤ 20%)
- `max_delta_abs = 0.20`
- Preferencia: delta entre -0.05 y -0.15 (5–8% OTM)
- Delta = probabilidad aproximada de que la opción expire in-the-money

### Filtro 4: Strike 4–12% OTM del precio BTC actual
- `min_otm_pct = 0.04` (4% mínimo fuera del dinero)
- `max_otm_pct = 0.12` (12% máximo — si está muy OTM, la prima es insignificante)

### Filtro 5: Spread bid/ask ≤ 25% del mark price
- `max_spread_pct = 0.25`
- Spread mayor = poca liquidez, slippage alto → no entrar

### Filtro 6: Sin posición en el mismo instrumento
- Un PUT por instrumento (strike+expiración) como máximo

### Filtro 7: MAX_OPEN_POSITIONS = 3
- Máximo 3 contratos abiertos simultáneamente
- Diversifica strikes y expiraciones

---

## 4. Priorización de candidatos

Antes de hacer llamadas API costosas, los candidatos se pre-ordenan por rentabilidad estimada:

```python
yield_score = est_premium / est_margin
```

Se evalúan primero los del rango DTE óptimo (5-10 días), ordenados por `yield_score` descendente. Esto reduce llamadas API y mejora la calidad de los candidatos analizados.

---

## 5. Lógica de salida — 4 escenarios

### A. Expiración natural (EXPIRED) — resultado ideal
- La opción llega al vencimiento sin ser ejercida
- PnL = +100% de la prima cobrada
- Sin costo de cierre

### B. Stop Loss 2× prima (STOP_LOSS_2X)
```
stop_price = entry_premium × STOP_LOSS_MULTIPLIER (= 2.0)
```
- Si el mark price del PUT sube al doble de la prima cobrada → recomprar
- Pérdida máxima = ~100% de la prima (pierdes lo que cobraste)
- Protege contra movimientos bruscos bajistas en BTC

### C. Profit Lock 80% (PROFIT_LOCK)
```
lock_price = entry_premium × (1 - PROFIT_LOCK_PCT) = entry × 0.20
```
- Si la prima cae al 20% del valor de entrada → cerrar antes de vencimiento
- Asegura el 80% de la ganancia máxima teórica
- Elimina gamma risk del último periodo

### D. Asignación (ASSIGNED)
- Solo en live: BTC cierra bajo el strike → obligación de comprar BTC a ese precio
- En paper: se trata como pérdida máxima (2× prima)

---

## 6. Cálculo de margen (Deribit portfolio margin)

```
initial_margin = max(0.10, 0.15 - OTM_pct) × contracts × btc_price
```

**Ejemplo** con BTC = $74,085, strike = $69,000, contracts = 0.1 BTC:
```
OTM_pct = (74,085 - 69,000) / 74,085 = 0.0686 (6.86%)
margin   = max(0.10, 0.15 - 0.0686) × 0.1 × 74,085
         = max(0.10, 0.0814) × 7,408.5
         = 0.10 × 7,408.5
         = $740.85 de margen requerido
```

**Nota**: el margen mínimo siempre es 10% del valor nocional del contrato.

**Límite total**: `MAX_MARGIN_USAGE = 70%` del balance → con $2,000 no se puede superar $1,400 en margen.

---

## 7. Parámetros completos (exchange_config.yaml)

```yaml
options:
  enabled: true
  paper_trading: true
  exchange: deribit
  initial_paper_balance_usd: 2000.0

  strategy:
    underlying: BTC
    option_type: PUT
    contract_size: 0.1            # BTC por contrato (mínimo Deribit)
    min_dte: 3
    max_dte: 21
    target_dte_min: 5             # DTE óptimo
    target_dte_max: 10
    min_otm_pct: 0.04
    max_otm_pct: 0.12
    min_iv_rank: 20               # % mínimo IV Rank (lookback 252d)
    max_delta_abs: 0.20
    max_spread_pct: 0.25
    max_open_positions: 3

  risk:
    max_drawdown_pct: 30.0        # Halt si DD > 30%
    stop_loss_multiplier: 2.0     # Stop si prima sube 2× la cobrada
    profit_lock_pct: 0.80         # Cerrar cuando ganamos 80% de la prima
    max_margin_usage_pct: 70.0    # Max 70% del balance en margen
```

**Constantes en theta_farming.py**:
```python
SCAN_INTERVAL   = 3600   # segundos entre scans de nuevas entradas
MONITOR_INTERVAL = 300   # segundos entre monitoreos de posiciones
INITIAL_BALANCE = 2000.0 # USD paper
MAX_DD          = 0.30   # 30% drawdown → halt
```

---

## 8. Entry premium: paper vs live

```python
# En theta_farming.py (línea ~200):
entry_premium_btc = mark_btc if self.paper_mode else bid_btc
```

- **paper_mode=True**: usa precio `mark` (mid entre bid y ask) → simulación realista
- **paper_mode=False**: usa precio `bid` → precio real al que se vende la prima en live
- El flag se propaga desde `agents/options_agent.py`:
  ```python
  PAPER_MODE = os.getenv('PAPER_TRADING','true').lower() == 'true'
  self.strategy = ThetaFarmingStrategy(paper_mode=PAPER_MODE)
  ```

---

## 9. Deribit Session Manager — gestión de autenticación

**Archivo**: `core/deribit_session_manager.py`

- Maneja OAuth2 con `DERIBIT_CLIENT_ID` y `DERIBIT_CLIENT_SECRET`
- Refresca el token automáticamente antes de expirar
- **Mutex**: todas las llamadas usan un lock para evitar condiciones de carrera
- **Deadlock fix** (Abr 2026): `_update_peak_and_drawdown` acepta `conn=None` para reutilizar la transacción activa en lugar de abrir una nueva (causaba deadlock en PostgreSQL)

**Endpoints Deribit usados**:
```
GET  /api/v2/public/get_instruments          → listar opciones disponibles
GET  /api/v2/public/get_order_book           → precios bid/ask/mark, Greeks
GET  /api/v2/public/get_index_price          → precio BTC actual
GET  /api/v2/public/get_volatility_index_data → IV histórico (252d)
POST /api/v2/private/sell                    → vender opción (cobrar prima)
POST /api/v2/private/buy                     → recomprar para cerrar posición
GET  /api/v2/private/get_open_orders_by_currency → órdenes abiertas
```

---

## 10. Base de datos — tablas del Options Agent

```sql
-- Sesiones paper
CREATE TABLE options_sessions (
    id SERIAL PRIMARY KEY,
    session_name VARCHAR(50),
    status VARCHAR(20),          -- ACTIVE / CLOSED
    initial_balance_usd NUMERIC,
    current_balance_usd NUMERIC,
    peak_balance_usd NUMERIC,
    max_drawdown_pct NUMERIC,
    total_premium_collected NUMERIC,
    started_at TIMESTAMPTZ
);

-- Posiciones (31 columnas relevantes)
CREATE TABLE options_positions (
    id SERIAL PRIMARY KEY,
    instrument_name VARCHAR(50),  -- ej: BTC-25APR26-69000-P
    strike NUMERIC,
    expiration_date DATE,
    dte_at_entry INTEGER,
    entry_premium_usd NUMERIC,
    entry_premium_btc NUMERIC,
    current_premium_usd NUMERIC,
    delta_at_entry NUMERIC,
    iv_rank_at_entry NUMERIC,
    otm_pct NUMERIC,
    contracts NUMERIC,            -- 0.1 BTC por contrato
    margin_required_usd NUMERIC,
    unrealized_pnl NUMERIC,
    realized_pnl NUMERIC,
    status VARCHAR(20),           -- OPEN / CLOSED
    exit_reason VARCHAR(30),      -- EXPIRED / STOP_LOSS_2X / PROFIT_LOCK / ASSIGNED
    opened_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ
);

-- Snapshots de mercado (para análisis histórico de IV)
CREATE TABLE options_market_data (
    id SERIAL PRIMARY KEY,
    instrument_name VARCHAR(50),
    mark_price NUMERIC,
    bid NUMERIC,
    ask NUMERIC,
    delta NUMERIC,
    gamma NUMERIC,
    theta NUMERIC,
    vega NUMERIC,
    iv NUMERIC,
    iv_rank NUMERIC,
    btc_price NUMERIC,
    timestamp TIMESTAMPTZ
);
```

---

## 11. Cómo diagnosticar el Options Agent

```bash
# Ver logs en tiempo real:
journalctl -u options-agent -f

# Ver posiciones abiertas:
set -a && source /opt/trading/config/.env && set +a
/opt/trading/venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
e = create_engine(os.environ['DB_URL'])
with e.connect() as c:
    r = c.execute(text('''
        SELECT instrument_name, strike, entry_premium_usd, delta_at_entry,
               expiration_date, status
        FROM options_positions WHERE status='OPEN'
        ORDER BY opened_at DESC
    ''')).fetchall()
    print(f'{len(r)} posiciones abiertas')
    [print(' ', row) for row in r]
"

# Ver PnL de la sesión activa:
/opt/trading/venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
e = create_engine(os.environ['DB_URL'])
with e.connect() as c:
    r = c.execute(text('''
        SELECT COUNT(*) total, SUM(realized_pnl) pnl,
               SUM(CASE WHEN exit_reason='EXPIRED' THEN 1 ELSE 0 END) expired,
               SUM(CASE WHEN exit_reason='STOP_LOSS_2X' THEN 1 ELSE 0 END) stopped
        FROM options_positions WHERE status='CLOSED'
    ''')).scalar()
    print(r)
"
```

---

## 12. Cambios recientes (Abril 2026)

| Archivo | Cambio | Razón |
|---|---|---|
| `strategies/theta_farming.py` | IV Rank lookback: 30d → **252d** | 30d = rank distorsionado en periodos cortos; 252d = estándar del sector |
| `strategies/theta_farming.py` | Pre-ordenar candidatos por `prima/margen` antes de API calls | Reduce llamadas API; evalúa primero los más rentables |
| `strategies/theta_farming.py` | `entry_premium = mark if paper_mode else bid` | Paper usaba bid (imposible de ejecutar); mark es más realista |
| `strategies/theta_farming.py` | `__init__(self, paper_mode: bool = True)` | Permite propagar el flag desde options_agent |
| `agents/options_agent.py` | `ThetaFarmingStrategy(paper_mode=PAPER_MODE)` | Propaga `PAPER_TRADING` env var automáticamente |
| `core/deribit_session_manager.py` | `_update_peak_and_drawdown(conn=None)` | Deadlock fix: reutiliza tx existente en lugar de abrir nueva |

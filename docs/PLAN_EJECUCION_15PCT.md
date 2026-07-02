# PLAN DE EJECUCIÓN — Rentabilidad 15% anual (neta de costos)

> **Para quien ejecuta este plan (humano o IA)**: este documento es autocontenido.
> Contiene contexto, decisiones ya tomadas con datos, cambios exactos por archivo,
> comandos, SQL y criterios de aceptación por fase. Ejecutar las fases EN ORDEN.
> No saltar fases. No re-litigar decisiones marcadas como CERRADAS sin datos nuevos.
>
> Creado: Jul 2, 2026. Base: `docs/FEASIBILITY_STUDY.md` (leerlo primero — contiene
> toda la evidencia). Protocolo operativo: `AGENTS.md` (leer antes de tocar la VPS).

---

## 0. Contexto y estado actual (Jul 2, 2026)

### Infraestructura
- **VPS**: `187.77.5.109` (srv1347416), Ubuntu, repo en `/opt/trading`, venv en
  `/opt/trading/venv`. Acceso: ssh root + password (**pedir credencial al usuario,
  NO está en este repo**). DB: PostgreSQL local, base `trading_agent`
  (`sudo -u postgres psql -d trading_agent`). Redis local.
- **Clon local** (WSL del usuario): `~/personal/trading-agent` — clonado de
  `github.com/LuisColorado-tech/trading-agent` (público).

### Estado de los repos — ⚠️ TRES versiones distintas
1. **GitHub**: desactualizado, HEAD = `83afed8` (v1.2).
2. **VPS `/opt/trading`**: 8 commits adelante de GitHub, HEAD = `52d350e` (v1.4).
   Nunca se pusheó. Es la versión que CORRE.
3. **Clon local**: base v1.2 + **retrofit de costos SIN COMMITEAR** (ver §0.3).

### Cambios locales sin commitear (el "retrofit de costos")
Archivos nuevos:
- `core/cost_model.py` — fees/slippage por exchange, `net_pnl()`, `round_trip_cost_pct()`, `MIN_NET_RR_RATIO=1.0`
- `db/migrations/007_trade_costs.sql` — columnas `pnl_gross`, `fee_paid` en `trades`
- `scripts/preflight_live.py` — verificación pre-arranque (fees reales vía ccxt, DB, viabilidad)
- `tests/unit/test_cost_model.py`, `test_net_rr_gate.py`, `test_grid_costs.py`, `test_trade_monitor_costs.py`
- `docs/FEASIBILITY_STUDY.md`

Archivos modificados (vs base v1.2):
- `agents/trade_monitor.py` — `_close_trade()` calcula PnL NETO, persiste `pnl_gross`/`fee_paid`, devuelve dict
- `agents/grid_stable_agent.py` — `close_trade()` neto; constante `GRID_STABLE_EXCHANGE='kraken'`
- `risk/risk_manager.py` — gate 5b: rechaza `INSUFFICIENT_NET_RR` si RR neto de costos < 1.0
- `strategies/grid_bot.py` — gate de RR neto en `calculate_grid()` (param `exchange`)
- `strategies/grid_stable.py` — gate de RR neto en `build_grid()` + `_net_rr()` estático
- `agents/grid_agent.py` — pasa `exchange` desde `ASSET_MAP` a `calculate_grid()`
- `core/grid_stable_profiles.py` — LINK/BTC retuneado (levels 8→4, min_range 0.8%→3.0%)

### Acciones ya ejecutadas en la VPS
- `systemctl stop grid-stable && systemctl disable grid-stable` (Jul 2) — quedan
  **2 trades GRID_STABLE con status='OPEN' huérfanos** en DB (cerrarlos en Fase 2.5).

### Hallazgos cerrados (evidencia en FEASIBILITY_STUDY.md — NO re-litigar)
1. **Ninguna estrategia cubre fees taker de Kraken (0.68% round-trip)** con su
   comportamiento realizado. Mejor edge: SMC +0.237%/trade, TREND +0.189%.
2. **Edge por activo** (TREND, 3.5 meses): XAG +0.668%, LINK +0.484%, AAVE +0.383%,
   AVAX +0.353% (juntos: 261 trades, +0.44% ponderado). INJ −0.08%, SOL 0.00%.
3. **Stocks** (Alpaca, sin comisión): FXI +1.708% (67 trades), GLD +0.371% (70).
   QQQ −0.276% (132), EEM −1.856% (79), NVDA/META/SVXY negativos. Agregado: −$501.
4. **Polymarket: 0 de 5 sesiones ganadoras** (~−$985). Matar, no retunear.
5. **Grids stablecoin (DAI/USDT, USDC/USDT)**: WR 99%+ pero neto real −$70 a −$104
   por trade con fees. El WR alto es la firma de estrategia fee-blind.
6. **Bug de unidades en sizing**: pares BTC-quoted calculan `size = riesgo_USD /
   distancia_en_BTC` sin conversión → posiciones de millones de tokens (visto en
   vivo: SELL 7,812,500 LINK en agente de $500). También produce `available_cash`
   negativo (visto Jul 2: −$6,744).
7. `grid_stable_agent` y `grid_agent` NO pasan por RiskManager → sin cap de notional.

### Meta
**≥15% anual compuesto (~1.17%/mes) neto de costos, sobre el capital total.**
Cartera objetivo (§6): TREND podado 45%, Stocks podado 30%, Grid experimental 10%,
reserva 15%.

---

## FASE 1 — Reconciliación de repos (½ día)

**Objetivo**: una sola línea de código. Todo trabajo posterior se hace sobre v1.4.

1. En la VPS, subir v1.4 a GitHub:
   ```bash
   cd /opt/trading && git remote -v   # verificar origin
   git push origin master             # requiere credenciales GitHub del usuario
   ```
   Si la VPS no tiene credenciales de push: pedir al usuario un PAT con permiso
   `contents:write` sobre `LuisColorado-tech/trading-agent` y usar
   `git push https://<PAT>@github.com/LuisColorado-tech/trading-agent.git master`.
   NO guardar el PAT en disco.
2. En el clon local, el retrofit YA está commiteado en la rama **`cost-retrofit`**
   (commit `4ec7283`, base v1.2). Rebasearlo sobre v1.4:
   ```bash
   cd ~/personal/trading-agent
   git fetch origin
   git checkout cost-retrofit
   git rebase origin/master   # v1.4 tras el push del paso 1
   ```
   **Conflictos esperados (solo 2 archivos, +42 líneas del lado VPS):**
   - `core/grid_stable_profiles.py`: la VPS agregó perfiles `DAI/USDT` y `USDC/USDT`.
     Resolución: conservar los perfiles de stables PERO el retrofit los silenciará
     por el gate (su spacing nunca cubre fees). Mantener el retune de LINK/BTC
     (levels=4, min_range=0.030) del lado del retrofit.
   - `risk/risk_manager.py`: +6 líneas de la VPS (fix menor). Conservar ambos cambios.

**Aceptación**: `git log --oneline -3` muestra el commit del retrofit encima de
`52d350e` (v1.4). `python3 -m py_compile` pasa en todos los archivos del retrofit.

---

## FASE 2 — Fix de unidades del sizing + caps de notional (1-2 días)

**Objetivo**: que ningún agente pueda abrir una posición imposible. Es EL
prerequisito — sin esto los datos de paper siguen contaminados.

### 2.1 Helper de conversión (nuevo, en `core/cost_model.py` o módulo aparte)
```python
def quote_to_usd_rate(pair: str, feed) -> float:
    """Tasa quote→USD para un par. 'ETH/BTC' → precio BTC/USDT actual.
    'DAI/USDT' → 1.0. 'AAPL' → 1.0. Usa MarketFeed/ccxt para el precio BTC."""
```
- Para pares `*/BTC`: obtener precio BTC/USDT del feed (cachear 60s).
- Para `*/USDT`, `*/USD`, stocks: retornar 1.0.

### 2.2 `agents/grid_stable_agent.py` — sizing correcto + cap
Localizar el cálculo de `size` (buscar `grep -n "size" agents/grid_stable_agent.py`,
está en el flujo de `open_trade`/`run_cycle`). Cambiar a:
```python
quote_rate = quote_to_usd_rate(pair, feed)          # USD por 1 unidad de quote
risk_usd   = balance * MAX_RISK_PER_TRADE_PCT * profile.risk_fraction
risk_quote = risk_usd / quote_rate                   # riesgo en moneda de cotización
size       = risk_quote / abs(level.price - level.sl)
# CAP de notional: nunca más del 50% del balance del agente, en USD
notional_usd = size * level.price * quote_rate
max_notional = balance * 0.50
if notional_usd > max_notional:
    size = max_notional / (level.price * quote_rate)
```
Además: **guard de distancia mínima de SL** — si
`abs(level.price - level.sl)/level.price < round_trip_cost_pct(exchange)`,
rechazar el nivel (una distancia de SL menor que el costo es ruido, no señal).

### 2.3 `agents/grid_agent.py` — mismo cap de notional
GRID_BOT opera pares USD-quoted (unidades OK) pero no tiene cap. Añadir el mismo
bloque de cap tras `position_size = risk_amount / risk_per_unit` (paso 9 de
`_evaluate_asset`).

### 2.4 El PnL también debe convertirse
En `agents/grid_stable_agent.py::close_trade` y `monitor_trades`: el PnL de pares
BTC-quoted está en BTC. Convertir a USD con `quote_rate` ANTES de guardarlo en la
columna `pnl` (que el resto del sistema trata como USD).

### 2.5 Tests de aceptación (nuevos, `tests/unit/test_sizing_units.py`)
- Par ETH/BTC, balance $500, riesgo 0.1%: `notional_usd ≤ $250` SIEMPRE.
- Par con SL a 0.002% del precio: nivel rechazado (guard de distancia mínima).
- PnL de un trade ETH/BTC ganador queda en USD (magnitud ~riesgo, no ~riesgo×100k).

**Aceptación**: tests pasan en la VPS (`venv/bin/python3 -m pytest
tests/unit/test_sizing_units.py -v`). En 24h de paper tras el deploy, CERO
snapshots de portfolio con `available_cash < 0`:
```sql
SELECT COUNT(*) FROM portfolio WHERE available_cash < 0
  AND timestamp > NOW() - INTERVAL '24 hours';  -- debe dar 0
```

---

## FASE 3 — Deploy del retrofit + poda de universos (1 día)

### 3.1 Migración de DB (en la VPS)
```bash
sudo -u postgres psql -d trading_agent -f /opt/trading/db/migrations/007_trade_costs.sql
```

### 3.2 Cerrar los 2 trades GRID_STABLE huérfanos
```sql
UPDATE trades SET status='CLOSED', close_reason='ADMIN_CLOSE_SIZING_BUG',
       exit_price=entry_price, pnl=0, pnl_pct=0, timestamp_close=NOW()
WHERE strategy='GRID_STABLE' AND status='OPEN';
```

### 3.3 Poda de universos (decisiones CERRADAS, con evidencia)
- **`config/exchange_config.yaml`**:
  - `grid_stable.pairs`: `DAI/USDT.enabled: false`, `USDC/USDT.enabled: false`,
    `ETH/BTC.enabled: false`. Solo `LINK/BTC: true` (con perfil retuneado).
  - Quitar `INJ` y `SOL` de los activos de TREND (o marcar `enabled: false` si el
    formato lo permite; si no, quitarlos del mapa de assets).
- **Stocks** (`core/stocks_profiles.py`): dejar activos solo FXI y GLD. Desactivar
  QQQ, EEM, NVDA, META, SVXY, EWJ, SLV (poner su flag/profile en inactivo según el
  patrón existente del archivo).
- **Polymarket**: `systemctl stop polymarket-snipe && systemctl disable polymarket-snipe`
  (y cualquier otro servicio poly activo). NO borrar código ni datos.
- Servicios que siguen: `trading-agent`, `stocks-agent`, `dashboard-*`. `grid-stable`
  se re-habilita SOLO al terminar Fase 2+3 (con LINK/BTC únicamente).

### 3.4 Deploy código a la VPS
```bash
# desde el clon local reconciliado:
git push origin master
# en la VPS:
cd /opt/trading && git pull origin master
venv/bin/python3 -m pytest tests/unit/test_cost_model.py tests/unit/test_net_rr_gate.py \
  tests/unit/test_grid_costs.py tests/unit/test_trade_monitor_costs.py tests/unit/test_sizing_units.py -v
venv/bin/python3 scripts/preflight_live.py   # exit 0 requerido (warnings OK, failures NO)
systemctl restart trading-agent stocks-agent
systemctl start grid-stable && systemctl enable grid-stable   # solo LINK/BTC activo
```

**Aceptación**: preflight exit 0; tests verdes; en logs aparecen cierres con
`PnL neto=... (bruto=... fee=...)`; señales rechazadas con `INSUFFICIENT_NET_RR`
visibles en `journalctl -u trading-agent | grep REJECTED`.

---

## FASE 4 — Ejecución maker (limit orders) (~1 semana)

**Objetivo**: bajar el costo round-trip de 0.68% (taker) a 0.16–0.32% (maker).
Es la palanca que convierte los sleeves podados en rentables.

### Diseño (paper primero — simular fills maker de forma honesta)
1. Nuevo modo en `agents/execution_agent.py`: `ORDER_TYPE=limit_maker`.
   - Entrada: colocar límite AL precio del nivel/señal. En paper: el fill se simula
     SOLO si una vela posterior TOCA el precio límite (high/low lo cruza) — no fill
     instantáneo. Registrar `entry_order_type='maker'` en metadata.
   - Timeout: si no llena en N velas (config, default 3), cancelar señal.
2. Salidas TP: límite (maker). Salidas SL: siguen siendo market/taker (un SL límite
   puede no llenar en un crash — no negociable).
   - En `core/cost_model.py` ya existe soporte: `net_pnl(..., entry_order_type='maker',
     exit_order_type='taker')`. Usar el tipo real de cada pata al calcular fee.
3. `trade_monitor` lee el tipo de orden de metadata del trade y pasa los parámetros
   correctos a `calc_net_pnl`.
4. Routing por costo: donde el activo exista en ambos exchanges, preferir OKX
   (maker 0.08%) sobre Kraken (0.16%). Mapa en `exchange_config.yaml` — cambiar
   `role: primary` por activo donde aplique (AVAX, LINK existen en ambos).

**Aceptación**: en paper, ≥70% de las entradas llenan como maker (medir con
`SELECT COUNT(*) FROM trades WHERE metadata->>'entry_order_type'='maker'`);
el `fee_paid` promedio por trade baja ≥40% vs la semana previa.

---

## FASE 5 — Validación paper 4-6 semanas + graduación

**La métrica de graduación es UNA: expectancy neta por trade.** No usar win rate
(demostrado engañoso), no usar PnL bruto.

Query semanal por estrategia (correr cada lunes, guardar en `session_reports`):
```sql
SELECT strategy,
       COUNT(*) AS n,
       ROUND((AVG(pnl / NULLIF(entry_price*position_size,0)) * 100)::numeric, 4) AS edge_neto_pct,
       ROUND(SUM(pnl)::numeric, 2) AS pnl_neto,
       ROUND(SUM(fee_paid)::numeric, 2) AS fees
FROM trades
WHERE status='CLOSED' AND timestamp_close > NOW() - INTERVAL '7 days'
GROUP BY strategy;
```

**Criterios de graduación a live (por estrategia, TODOS deben cumplirse):**
| Criterio | Umbral |
|---|---|
| Edge neto promedio/trade | > 0 sostenido 4 semanas consecutivas |
| Trades en el periodo | ≥ 30 |
| Max drawdown del sleeve | < 8% |
| Snapshots con cash negativo | 0 |
| Fills maker (si Fase 4 activa) | ≥ 70% de entradas |

**Si TREND podado no gradúa**: revisar el trailing (activación 0.75R corta ganadores
a +0.387% cuando los TP completos pagan +1.233% — ver FEASIBILITY_STUDY §6b).
Experimento A/B permitido: `TRAILING_ACTIVATION_R` 0.75 → 1.25 en la mitad de los
activos, comparar expectancy neta a 3 semanas.

---

## FASE 6 — Live gradual (semana 9+)

Solo con estrategias graduadas. Checklist de seguridad de `CAPITAL_FLOW.md` §7
COMPLETO antes de fondear (API keys sin permiso withdraw, 2FA, whitelist, etc.).

| Semana | Sizing | Condición para avanzar |
|---|---|---|
| 1-2 | 0.25× con $300-500 | expectancy neta live > 0 |
| 3-4 | 0.5× | 2 semanas positivas |
| 5+ | 1.0× | 4 semanas positivas y DD < 8% |

Cartera al escalar: TREND podado 45%, Stocks podado 30% (FXI/GLD), grid LINK/BTC
10% (solo si graduó), reserva 15%.

**Matemática de la meta**: escenario pesimista (edge out-of-sample = mitad del
medido) → ~0.7-1.5%/mes ≈ 9-20% anual. La meta de 15% está dentro del rango.
Si tras 8 semanas de paper el edge medido cae por debajo de la mitad, PARAR y
re-evaluar — no forzar el go-live para cumplir el calendario.

---

## Reglas duras para quien ejecute esto

1. **NUNCA** re-habilitar DAI/USDT, USDC/USDT, ETH/BTC en grid_stable ni Polymarket
   sin un cambio estructural documentado (p.ej. ejecución maker + fees verificados
   que cambien la matemática de FEASIBILITY_STUDY §3b/6c).
2. **NUNCA** evaluar una estrategia por win rate o PnL bruto.
3. Todo fix en la VPS sigue el protocolo de diagnóstico de `AGENTS.md` (paso 3.4:
   ver el motivo de rechazo en logs ANTES de proponer cambios).
4. Los fees asumidos en `core/cost_model.py` deben verificarse con
   `scripts/preflight_live.py` después de cualquier cambio de exchange/tier.
5. No guardar credenciales (SSH, PATs, API keys) en el repo ni en docs.
6. Python en la VPS: SIEMPRE `/opt/trading/venv/bin/python3`.
7. Ante cualquier número "demasiado bueno" (WR>90%, edge>2%/trade, balance que
   se duplica en semanas): sospechar bug de unidades/fees ANTES de celebrar.
   Verificar con la query de expectancy neta y con notionals
   (`SELECT MAX(entry_price*position_size) ...`).

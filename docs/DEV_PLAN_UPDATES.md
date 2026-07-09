# Actualizaciones al Plan de Desarrollo — Post Fase 6

> Este documento complementa `dev_plan_trading_agent.docx` con los cambios
> realizados después de completar la Fase 6 original.
> Fecha: 2026-03-16

---

## Resumen de Gaps Detectados y Corregidos

### GAP CRÍTICO: Sin lógica de cierre de trades

**Problema**: El plan original (Fase 4 + Fase 6) definía las condiciones de salida
(SL 1.5×ATR, TP 2.5×ATR, trailing stop) y el schema de DB tenía columnas
`exit_price`, `close_reason`, `pnl`, `timestamp_close`. Sin embargo, **no se
especificó ni implementó un módulo para monitorear trades abiertos y cerrarlos**.

El `run_trading.py` de Fase 6.2 tenía `# TODO: query DB` para trades abiertos
y solo ejecutaba nuevos trades sin verificar los existentes.

**Consecuencia**: Tras 9 horas de operación, los 3 trades iniciales (BTC, ETH, SOL)
permanecían OPEN indefinidamente. ETH había superado su TP (+$317, +1.52%) pero
seguía abierto. Los 1,448 nuevos oportunidades fueron TODAS rechazadas por
MAX_CONCURRENT_TRADES (3/3 slots ocupados permanentemente).

**Solución implementada**: Nuevo módulo `agents/trade_monitor.py` — ver sección abajo.

### GAP: Portfolio sin actualización periódica

**Problema**: Solo se guardaba 1 snapshot de portfolio al iniciar `run_trading.py`.
Sin snapshots periódicos, imposible calcular equity curve, Sharpe ratio, o drawdown real.

**Solución**: Snapshot cada 5 ciclos (~5 min) + snapshot al cerrar cada trade.

### GAP: Costo excesivo del LLM

**Problema**: Claude Opus 4.5 ($15/$75 por 1M tokens) ejecutándose en 3 puntos por
cada evaluación de estrategia. Con 5 assets × 2 TF × 1/min = ~600 llamadas/hora.
Costo real: **$5.36 en 9 horas**.

**Solución**: Migración a GPT-4o-mini ($0.15/$0.60 por 1M tokens) usando la misma
API key de OpenAI que ya usa OpenClaw. Costo estimado: ~$0.03-0.05/día.

---

## Módulo Nuevo: TradeMonitor

**Archivo**: `agents/trade_monitor.py`
**Commit**: `79e35ac`
**Clase**: `TradeMonitor`

### Responsabilidad

Monitorear todos los trades con status='OPEN' en cada ciclo del loop principal.
Evaluar si el precio actual ha alcanzado Stop Loss, Take Profit, o el umbral de
trailing stop. Si sí, cerrar el trade con cálculo de PnL y actualización de portfolio.

### Flujo de evaluación

```
Por cada trade OPEN:
  1. Obtener precio actual de market_data (último close)
  2. Calcular trailing threshold = entry ± 1.5 × |entry - SL|
  3. Si precio alcanzó trailing → mover SL a break-even
  4. Si precio alcanzó SL → cerrar STOP_LOSS
  5. Si precio alcanzó TP → cerrar TAKE_PROFIT
```

### Lógica BUY vs SELL

| Condición | BUY | SELL |
|-----------|-----|------|
| SL hit | precio ≤ stop_loss | precio ≥ stop_loss |
| TP hit | precio ≥ take_profit | precio ≤ take_profit |
| Trailing | precio ≥ entry + 1.5×risk → SL=entry | precio ≤ entry - 1.5×risk → SL=entry |

### Al cerrar un trade

1. `UPDATE trades SET status='CLOSED', exit_price, pnl, pnl_pct, close_reason, timestamp_close`
2. Recalcular portfolio: `new_balance = old_balance + pnl`
3. Recalcular exposición real desde trades abiertos restantes
4. `INSERT INTO portfolio` nuevo snapshot
5. `PUBLISH trades:closed` en Redis

### PnL: fórmulas

```
BUY:  pnl = (exit_price - entry_price) × position_size
SELL: pnl = (entry_price - exit_price) × position_size
pnl_pct = pnl / (entry_price × position_size) × 100
```

### Integración en loop principal

```python
# run_trading.py — Step 0 (antes del scan)
closed_trades = monitor.check_open_trades(portfolio)
if closed_trades:
    portfolio = get_portfolio()  # Refresh
```

---

## Módulo Actualizado: LLMBridge (ex-ClaudeBridge)

**Archivo**: `core/claude_bridge.py`
**Commit**: `c5b7f25`
**Clase**: `ClaudeBridge` (nombre mantenido por compatibilidad de imports)

### Cambios

- Multi-provider: detecta `OPENAI_API_KEY` primero, luego `ANTHROPIC_API_KEY`
- Provider por defecto: OpenAI GPT-4o-mini
- Variable `LLM_MODEL` en `.env` controla el modelo sin tocar código
- Imports lazy: solo carga el SDK del provider activo
- Logging actualizado: `LLM [openai/gpt-4o-mini] task for ASSET`

### Configuración (.env)

```env
# Opción 1: OpenAI (recomendado — barato)
OPENAI_API_KEY=sk-proj-...
LLM_MODEL=gpt-4o-mini

# Opción 2: Anthropic (caro — solo si se necesita Opus)
#ANTHROPIC_API_KEY=sk-ant-...
#LLM_MODEL=claude-opus-4-5
```

---

## Módulo Actualizado: run_trading.py

**Commit**: `79e35ac`

### Cambios

1. **Paso 0 del loop**: `monitor.check_open_trades(portfolio)` antes del scan
2. **Portfolio snapshot periódico**: cada `PORTFOLIO_SNAPSHOT_INTERVAL=5` ciclos
3. **Cycle counter**: `cycle_count` para tracking y operaciones periódicas
4. **get_portfolio() mejorado**: calcula exposición real consultando trades OPEN
5. **Import TradeMonitor**: `from agents.trade_monitor import TradeMonitor`

### Loop actualizado

```
while True:
    cycle_count += 1
    0. monitor.check_open_trades(portfolio)    ← NUEVO
    1. scanner.scan()
    2. strategy.evaluate() por asset/TF
    3. executor.execute() si hay oportunidad
    4. portfolio = get_portfolio()
    5. if cycle_count % 5 == 0: save_snapshot() ← NUEVO
    sleep(60)
```

---

## Estado de Fases Actualizado

| Fase | Estado | Fecha | Commit |
|------|--------|-------|--------|
| 0 - Preflight | ✅ COMPLETADA | 2026-03-16 | `7225bcf` |
| 1 - Infraestructura | ✅ COMPLETADA | 2026-03-16 | `ec8bc1d` |
| 2 - Market Scanner | ✅ COMPLETADA | 2026-03-16 | `efd7437` |
| 3 - Strategy Engine | ✅ COMPLETADA | 2026-03-16 | `1b8c9ed` |
| 4 - Risk + Execution | ✅ COMPLETADA | 2026-03-16 | `4f6e1a2` |
| 5 - Dashboard + Briefing | ✅ COMPLETADA | 2026-03-16 | `76a8228` |
| 6 - Paper Trading | ✅ COMPLETADA | 2026-03-16 | `1b61032` |
| 6+ - Trade Monitor | ✅ COMPLETADA | 2026-03-16 | `79e35ac` |
| 6+ - LLM Migration | ✅ COMPLETADA | 2026-03-16 | `c5b7f25` |
| 6+ - Arthas CLI | ✅ COMPLETADA | 2026-03-16 | `cafc25a` |
| 6+ - Systemd 24/7 | ✅ COMPLETADA | 2026-03-16 | `ab07e48` |
| 7 - Producción | ⬜ PENDIENTE | — | — |

### Criterios de graduación a producción (sin cambios)

| Métrica | Target mínimo | Target óptimo | Estado actual |
|---------|--------------|---------------|---------------|
| Win Rate | ≥ 55% | ≥ 62% | ⬜ En acumulación |
| Profit Factor | ≥ 1.5 | ≥ 2.0 | ⬜ En acumulación |
| Max Drawdown | < 12% | < 8% | ⬜ En acumulación |
| Sharpe Ratio | ≥ 1.2 | ≥ 1.8 | ⬜ En acumulación |
| Total trades cerrados | ≥ 30 | ≥ 60 | 1 (ETH +$166.67) |
| Semanas estables | ≥ 4 | ≥ 6 | 0 |

---

## ROADMAP DE PROYECTOS FUTUROS (Actualizado 2026-04-14)

> **Objetivo**: $500/mes sumando MÚLTIPLES agentes, cada uno aportando 3–5% mensual
> sobre su capital asignado. Ningún agente tiene que ser perfecto — la suma es lo que importa.
> Capital inicial pequeño, compounding del 100% de ganancias los primeros 18–24 meses.
>
> Arbitraje cross-exchange spot descartado: spreads BTC/ETH entre exchanges grandes son
> 0.02-0.08%, eliminados por HFTs institucionales en <100ms. No viable para capital retail.

---

### PROYECTO 1: Polymarket — Signal-Based Strategy [DESPLEGADO ✓]

**Estado actual (2026-04-14)**: POLY_SESSION_003 activa | 7 posiciones abiertas

**5 bugs críticos corregidos** en `strategies/signal_based_poly.py` (ver módulo para CHANGELOG completo):
1. Señales duplicadas (74×/hora del mismo `price_at_signal`) → `DISTINCT ON(timeframe)`, solo 1h/4h, ventana 4h
2. Dead code: doble bloque `regime_confirms = False` → una sola verificación limpia
3. Sin validación de precio → filtro de viabilidad: `gap% > días_restantes × 2%` → SKIP
4. `estimated_prob` era 1.0/0.0 (Kelly inválido) → ahora `round(min(0.90, entry + edge), 4)`
5. Reasoning opaco → `BTC[DB:macro BUY=1 SELL=0] → UP | ...`

**Ejemplo validado**: `BTC above $76k on April 15` con BTC@$74,246 y 1 día restante
→ BLOQUEADO: `PRICE_TOO_FAR:BTC@74246 target=76000 gap=2.4% max=2.0% (1d)`

**Criterios para capital real** (actualmente validando en paper):
- ≥ 30 trades con `strategy = SIGNAL_BASED`
- Win Rate ≥ 55% en ese subset
- Profit Factor ≥ 1.3

**Capital objetivo**: $200 real. Retorno esperado: **5–15%/mes** (~$10–30/mes).

---

### PROYECTO 2: Trading Bot Trend Momentum

**Estado**: SESSION_008 activa | 57 trades | WR 56.1% | PnL paper +$325.90

Agente original del sistema. Opera BTC/ETH/SOL en Kraken con señales EMA cross (1h/4h),
Market Regime (TRENDING_UP/DOWN vs RANGE/CHOPPY), y trailing stop dinámico.

**Criterios para capital real**:
- WR ≥ 55% sostenido en ≥ 50 trades paper
- Profit Factor ≥ 1.4
- Max Drawdown < 8%
- ≥ 5 trades/semana (señales suficientes)

**Capital objetivo**: $500 real. Retorno esperado: **3–5%/mes** (~$15–25/mes).

**Archivos core**: `agents/execution_agent.py`, `core/market_regime.py`, `agents/indicators.py`

---

### PROYECTO 5: Funding Rate OKX (neutro al mercado, largo plazo)

**Exchange: OKX** (Binance y Bybit bloqueados desde el VPS — HTTP 451 y 403 respectivamente)

> **Diagnóstico de exchanges (verificado 2026-04-14 desde srv1347416)**:
> - Binance: HTTP 451 "Service unavailable from a restricted country" → DESCARTADO
> - Bybit: HTTP 403 "CloudFront configured to block access from your country" → DESCARTADO
> - **OKX: ACCESIBLE** — ya configurado en el sistema con API keys activas (lo usamos para XAG)

**Concepto**: BTC perp SHORT en OKX + BTC spot LONG en OKX = posición delta neutral.
Solo cobras el funding rate cuando es positivo (longs pagan a shorts).
El precio del BTC no te afecta porque una pierna cancela a la otra.

**Funding rates OKX — datos reales (2026-04-14)**:

| Asset | Rate actual (8h) | APY actual | Historial (20p) |
|-------|-----------------|------------|-----------------|
| BTC | -0.0158% | -17.3% | **+4.48% APY promedio** |
| ETH | +0.0008% | +0.88% | pendiente medir |
| SOL | -0.0003% | -0.30% | pendiente medir |

> **Nota importante**: El rate actual de BTC es **negativo** (-0.0158%) — mercado bajista.
> Pero el **promedio histórico de 20 periodos (≈7 días) es +4.48% APY**.
> Un rate negativo significa que los SHORTS pagan a los LONGS: hay que esperar
> o adaptar la posición (ver estrategia adaptativa abajo).
> La cifra de 11% APY era para Binance que históricamente tiene rates más altos.
> En OKX el rendimiento realista es **3–6% APY** en períodos normales.

**Estrategia adaptativa (solo OKX)**:

```
Cada 8h — antes del pago de funding:
  SI rate > umbral_mínimo (0.005% = +5.48% APY):
    → ABRIR: spot BTC LONG + perp BTC SHORT (delta neutral)
    → COBRAR funding cada 8h
  SI rate < 0 (shorts pagan longs):
    → CERRAR hedge o INVERTIR si rate < -0.005%
    → Esperar o mantenerse neutro
  Cuando cerrar:
    → Spread spot-perp vuelve a equilibrio
    → Abre nueva posición si rate vuelve al umbral
```

**Ventajas vs Binance**:
- OKX **ya está en el sistema** — API keys configuradas, ccxt mapeado, sin onboarding
- Un solo exchange = sin riesgo de ejecución cross-exchange (slippage, latencia)
- Fees OKX maker: 0.02% spot + 0.02% perp = 0.04% round-trip (vs 0.10% Binance)
- Sin gestión de transferencias entre wallets

**Capital mínimo**: $300 — distribuido 50% spot / 50% margen perpetuo.

**Lo que falta construir**:
- `agents/funding_agent.py` — monitorear funding rate OKX cada 8h, abrir/cerrar hedge
- `strategies/funding_arb.py` — lógica de entrada/salida por umbral de rate
- `scripts/run_funding.py` — loop independiente systemd
- NO requiere nuevo exchange — solo activar los perpetuos OKX en el config

**ROI realista OKX** (conservador):

| Escenario | APY funding | APY neto (fees) | $300 capital | $1k capital |
|-----------|------------|-----------------|-------------|-------------|
| Pesimista | +2% | +1.5% | +$4.50/año | +$15/año |
| Base | +4.5% | +4.0% | +$12/año | +$40/año |
| Optimista | +8% | +7.4% | +$22/año | +$74/año |



---

### PROYECTO 3 (NUEVO): Opciones Crypto — Theta Farming en Deribit

**Estado**: En diseño | Verificación de accesibilidad pendiente

**Concepto**: Vender opciones PUT de BTC semanales fuera-del-dinero en Deribit.
El comprador paga una prima por "seguro" contra caídas. Si BTC no cae drásticamente,
la prima expira y el vendedor se la queda. Es el negocio de las aseguradoras:
cobrar prima por riesgo que raramente se materializa al nivel temido.

**Por qué Deribit**:
- Mayor exchange de opciones crypto (~90% del open interest global)
- Accesible globalmente sin restricciones de país (a diferencia de Binance/Bybit)
- API completa soportada por `ccxt` (ya instalado en el sistema)
- Liquidación en BTC para opciones BTC; en USDC para opciones en USDC-settled

**Mecánica básica**:
```
Cada lunes — selección del strike:
  BTC precio actual: $74,000
  Vender 1x PUT semanal strike $70,000 (5.4% OTM, delta ~0.15)
  Prima recibida: ~$200–400 (0.003–0.005 BTC)
  Expiración: viernes siguiente

  Resultado posible:
  → BTC ≥ $70,000 el viernes: prima cobrada completa (+$200–400)  ✓
  → BTC < $70,000: asignado — compras BTC a $70,000 (pérdida parcial)
  Stop: comprar de vuelta si pérdida > 2× la prima recibida
```

**Plan de construcción**:
1. `scripts/test_deribit_access.py` — verificar conectividad desde el VPS (PRIMER PASO)
2. `agents/options_agent.py` — selección de strike, gestión de posición
3. `strategies/theta_farming.py` — lógica: delta PUT < 0.15, IV rank > 30, DTE 5–7 días
4. `scripts/run_options.py` — loop semanal (cron es suficiente, no necesita systemd continuo)

**Gestión de riesgo**:
- Solo PUTs cash-secured (tienes el colateral en BTC o USDC)
- Máximo 2 contratos/semana hasta validar la estrategia (0.01 BTC/contrato en Deribit)
- No operar si IV rank < 20 (prima demasiado baja para el riesgo)

**Capital necesario**: 0.01 BTC (~$740 al precio actual) como colateral mínimo.
**Retorno esperado**: 1–2% semanal sobre colateral = **4–8%/mes** en condiciones normales.

---

### PROYECTO 4: Aave USDC Lending (yield pasivo)

**Estado**: Diseñado, pendiente de capital PnL

**Protocolo**: Aave v3 en Polygon o Arbitrum (fees de gas mínimas).
Depositar USDC en el pool de lending. Prestatarios pagan interés automáticamente.
Sin custodia centralizada: los fondos son tuyos vía smart contract auditado.

**Retorno histórico Aave v3 USDC**:
- Polygon: 4–6% APY base + rewards ocasionales
- Arbitrum: 5–8% APY base

**Solo usar PnL acumulado, nunca capital principal.**
- $500 USDC → ~$25–40/año (~$2–3/mes) — complemento pasivo
- $2,000 USDC → ~$100–160/año (~$8–13/mes) — base interesante

**Automatización**: `agents/yield_agent.py` — monitorear APY cross-pool, mover si delta > 2%.

---

### DESCARTADOS

- ~~**Arbitraje Cross-Exchange spot**~~: spreads BTC/ETH <0.08%, eliminados por HFTs en <100ms.
- ~~**Copy Trading automático**~~: lag de 1–5s destruye el edge del líder copiado.
- ~~**MEV / Sandwich attacks**~~: requiere co-location en nodos ETH + capital >$50k. No viable.
- ~~**Binance**~~: HTTP 451 «Service unavailable from a restricted country» — definitivamente fuera.
- ~~**Bybit**~~: HTTP 403 CloudFront access block — definitivamente fuera.

---

### Tabla resumen: Todos los agentes

| Agente | Capital | Retorno/mes | Ingreso/mes | Estado |
|--------|---------|-------------|-------------|--------|
| Trading Bot (Kraken) | $500 | 3–5% | $15–25 | Paper SESSION_008 ✓ |
| Polymarket Signal | $200 | 5–15% | $10–30 | Desplegado, validando |
| Opciones Deribit | $750 BTC | 4–8% | $30–60 | En diseño |
| Aave USDC | $500–2k | 0.5%/mes | $2–13 | Pendiente capital PnL |
| Funding OKX | $1,000+ | 0.3%/mes | $3–6 | Bajo retorno, esperar |
| **TOTAL ~$3,450** | | | **$60–134/mes** | Con todo activo |

> Para llegar a **$500/mes** necesitamos ~$8,000–10,000 desplegados con esos retornos,
> o escalar las Opciones Deribit (múltiples contratos = el mayor multiplicador del portfolio).

---

### Hoja de ruta para llegar a $500/mes (con compounding)

| Mes | Hito | Capital activo | Ingreso estimado/mes |
|-----|------|---------------|----------------------|
| 4 | Trading bot → $500 real (WR≥55%, 50 trades) | $500 | ~$20 |
| 5 | Polymarket real $200 (WR≥55%, 30 SIGNAL trades) | $700 | ~$45 |
| 6 | Deribit test: 1 contrato semanal (0.01 BTC) | $1,450 | ~$90 |
| 7 | Aave: $500 PnL → USDC lending | $1,950 | ~$100 |
| 9 | Escalar Deribit (2–3 contratos) + compounding | $2,500 | ~$150 |
| 12 | Todos activos, ganancias reinvertidas | ~$3,000 | ~$180 |
| 18 | Opciones escaladas (5–8 contratos/semana) | ~$5,000 | ~$310 |
| 24 | Meta: Deribit 10+ contratos + bots escalados | ~$10,000 | **~$500/mes** |

> La clave: **reinvertir el 100% de ganancias** los primeros 18–24 meses.
> El mayor multiplicador es Deribit options: vender puts semanales escala linealmente
> con el colateral. Una gestora profesional hace 3–5% semanal. Nuestro target es
> conservador: 1–2% semanal con puts 5–8% OTM y stops definidos.

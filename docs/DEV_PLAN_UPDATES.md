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

# Auditoría Técnica del Pipeline de Trading

> Fecha: 2026-03-17  
> Versión: Post-Fase 6, Pipeline Audit  
> Autor: AI Trading Agent Team

---

## 1. Resumen Ejecutivo

Se realizó una auditoría completa del pipeline de trading para verificar que no existan brechas lógicas entre la teoría de gestión de riesgo y la implementación en código. Se analizaron los 11 trades ejecutados, el código de los 8 componentes del pipeline, y la coherencia matemática de cada fórmula.

### Resultados

| Categoría | Total | Crítico | Alto | Medio |
|-----------|-------|---------|------|-------|
| Bugs encontrados | 8 | 3 | 3 | 2 |
| Bugs corregidos | 8 | 3 | 3 | 2 |
| Mejoras recomendadas | 1 | 0 | 0 | 1 |

### Historial completo de bugs (incluye sesiones anteriores)

| # | Bug | Severidad | Impacto | Estado | Fecha |
|---|-----|-----------|---------|--------|-------|
| 1 | Sin TradeMonitor | CRÍTICO | Trades nunca cerraban | ✅ Corregido | 2026-03-16 |
| 2 | Exposición nocional bloqueante | CRÍTICO | 1 trade bloqueaba todo | ✅ Corregido | 2026-03-17 |
| 3 | Trades duplicados por activo | CRÍTICO | 2 BTC idénticos, riesgo 2× | ✅ Corregido | 2026-03-17 |
| 4 | `available_cash` incoherente | ALTO | Cash = $42K con balance $11K | ✅ Corregido | 2026-03-17 |
| 5 | Sin detección datos obsoletos | ALTO | Señales sobre datos viejos | ✅ Corregido | 2026-03-17 |
| 6 | Trailing solo a break-even | MEDIO | No captura ganancia parcial | ✅ Corregido | 2026-03-17 |
| 7 | Loop re-entrada post SL | CRÍTICO | Re-entry en 20s tras SL = loop destructivo ~$750 | ✅ Corregido | 2026-03-17 |
| 8 | Drawdown halt no persistente | ALTO | Restart del servicio borra halt 10% | ✅ Corregido | 2026-03-17 |

---

## 2. Arquitectura del Pipeline

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐     ┌──────────────┐
│ MarketFeed  │────▶│ MarketScanner│────▶│ StrategyEngine  │────▶│ RiskManager  │
│ (Kraken/OKX)│     │ (Indicadores)│     │ (3 estrategias) │     │ (8 reglas)   │
└─────────────┘     └──────────────┘     └─────────────────┘     └──────┬───────┘
                                                                        │
                    ┌──────────────┐     ┌─────────────────┐           │
                    │ TradeMonitor │◀────│ ExecutionAgent  │◀──────────┘
                    │ (SL/TP/Trail)│     │ (Paper/Live)    │
                    └──────────────┘     └─────────────────┘
```

### Flujo de datos por ciclo (~60s):

1. **MarketFeed** → descarga OHLCV de exchanges, persiste en PostgreSQL
2. **MarketScanner** → calcula indicadores (EMA, RSI, BB, ATR, MACD, VWAP), detecta señales
3. **StrategyEngine** → evalúa 3 estrategias, selecciona la mejor, pide verificación a GPT-4o-mini
4. **RiskManager** → aplica 8 reglas inmutables, calcula position sizing
5. **ExecutionAgent** → simula/ejecuta orden, persiste trade en DB
6. **TradeMonitor** → evalúa trades abiertos contra SL/TP/trailing, cierra y actualiza portfolio

---

## 3. Reglas de Riesgo (Teoría → Código)

### 3.1 Parámetros inmutables

| Parámetro | Valor | Constante | Archivo |
|-----------|-------|-----------|---------|
| Riesgo máximo por trade | 1% | `MAX_RISK_PER_TRADE_PCT = 0.01` | `risk/risk_manager.py` |
| Exposición máxima portfolio | 5% | `MAX_PORTFOLIO_EXPOSURE = 0.05` | `risk/risk_manager.py` |
| Stop Loss | 1.5 × ATR | `STOP_LOSS_ATR_MULTIPLIER = 1.5` | `risk/risk_manager.py` |
| Take Profit | 2.5 × ATR | `TAKE_PROFIT_ATR_MULT = 2.5` | `risk/risk_manager.py` |
| Drawdown máximo | 10% | `MAX_DRAWDOWN_STOP = 0.10` | `risk/risk_manager.py` |
| Trades concurrentes | 3 | `MAX_CONCURRENT_TRADES = 3` | `risk/risk_manager.py` |
| Ratio R:R mínimo | 1.5 | `MIN_RR_RATIO = 1.5` | `risk/risk_manager.py` |
| Cooldown post SL | 30 min | `SL_COOLDOWN_MINUTES = 30` | `risk/risk_manager.py` |

### 3.2 Secuencia de validación del RiskManager

```
evaluate(signal, portfolio, open_trades) → RiskDecision
│
├─ Regla 0: ¿Trading halted por drawdown previo?     → TRADING_HALTED
├─ Regla 1: drawdown_pct ≥ 10%?                      → DRAWDOWN_LIMIT_REACHED (halt permanente)
├─ Regla 2: exposure_pct ≥ 5%?                        → MAX_EXPOSURE_REACHED
├─ Regla 3: n_open ≥ 3?                               → MAX_CONCURRENT_TRADES
├─ Regla 3b: ¿Ya hay trade abierto del mismo asset?   → DUPLICATE_ASSET:{asset}
├─ Regla 3c: ¿Asset en cooldown post SL? (30 min)     → SL_COOLDOWN:{asset}
├─ Regla 4: Calcular position_size = (1% × balance) / |entry - SL|
│   └─ 4b: exposure_actual + risk_pct > 5%?           → MAX_EXPOSURE_WITH_NEW_TRADE
├─ Regla 5: R:R < 1.5?                                → INSUFFICIENT_RR
├─ Regla 6: GPT anomaly_check → severity=CRITICAL + conf≥85% → CLAUDE_CRITICAL_ANOMALY
│
└─ ✅ APPROVED (position_size, SL, TP, risk_amount)
```

### 3.3 Fórmulas matemáticas

**Position Sizing (Regla 4):**
$$\text{risk\_amount} = \text{balance} \times 0.01$$
$$\text{position\_size} = \frac{\text{risk\_amount}}{|p_{\text{entry}} - p_{\text{SL}}|}$$

**Exposición (risk-based):**
$$\text{exposure} = \frac{\sum_{i \in \text{open}} |p_{\text{entry},i} - p_{\text{SL},i}| \times q_i}{\text{balance}}$$

**Cash disponible (notional-based):**
$$\text{available\_cash} = \text{balance} - \sum_{i \in \text{open}} p_{\text{entry},i} \times q_i$$

**R:R Ratio:**
$$\text{RR} = \frac{|p_{\text{TP}} - p_{\text{entry}}|}{|p_{\text{entry}} - p_{\text{SL}}|}$$

---

## 4. Detalle de Bugs Encontrados y Corregidos

### Bug #3: Trades duplicados por activo (CRÍTICO)

**Síntoma**: 2 trades BTC abiertos simultáneamente con entry/SL/TP idénticos.

**Causa raíz**: El main loop evalúa cada asset en 2 timeframes (`15m`, `1h`). Ambos podían generar señal BUY al mismo ciclo. El RiskManager no tenía regla de unicidad por activo.

**Evidencia**:
```
OPEN | BTC BUY entry=75398.90 SL=75024.29 TP=76023.25
OPEN | BTC BUY entry=75398.90 SL=75024.29 TP=76023.25  ← DUPLICADO
```
Total trades: 7/11 eran BTC. Cero diversificación.

**Corrección**: Nueva regla 3b en `risk_manager.py`:
```python
asset_open_count = sum(1 for t in open_trades if t.get('asset') == asset_name)
if asset_open_count >= 1:
    return RiskDecision(approved=False, reason=f'DUPLICATE_ASSET:{asset_name}')
```

**Verificación**: Test `test_duplicate_asset_rejected()`.

---

### Bug #4: available_cash incoherente (ALTO)

**Síntoma**: Portfolio mostraba cash=$42,570 con balance=$11,202 (cash > balance).

**Causa raíz**: Dos fórmulas incompatibles:
- `get_portfolio()`: `cash = balance - Σ(|entry-SL| × size)` → cifra grande (balance - ~$337)
- `_close_trade()`: `cash += entry × size + pnl` → sumaba nocional (~$22K)

Acumulación: tras varios cierres, cash divergía absurdamente.

**Corrección**: Ambos puntos ahora recalculan:
```python
total_notional = sum(entry × size for each open trade)
available_cash = balance - total_notional
```

**Verificación**: Test `test_portfolio_cash_consistency()`.

---

### Bug #5: Sin detección de datos obsoletos (ALTO)

**Síntoma**: Si un exchange fallaba, `get_latest()` devolvía datos de horas previas sin aviso.

**Corrección**: Validación de frescura en `market_feed.py`:
```python
max_age = tf_minutes[timeframe] * 3
if age > max_age:
    logger.warning(f'STALE DATA: {asset}/{timeframe}')
```

**Verificación**: Test `test_stale_data_detection()`.

---

## 5. Métricas de Rendimiento Actuales

| Métrica | Valor |
|---------|-------|
| Balance inicial | $10,000.00 |
| Balance actual | $11,383.70 |
| Retorno | +13.84% |
| Trades totales | 11 (8 cerrados, 3 abiertos) |
| Win rate | 87.5% (7 TP / 8 cerrados) |
| PnL realizado | +$1,217.98 |
| Pérdida máxima | $0.00 (SL en break-even) |
| Ratio promedio R:R | 1.67:1 (diseño) |
| Drawdown máximo | 0.00% |

---

## 6. Suite de Tests Técnicos

Ver `/opt/trading/tests/` para la suite completa:

| Archivo | Cobertura | Tests |
|---------|-----------|-------|
| `tests/unit/test_risk_manager.py` | 10 reglas de riesgo, position sizing, cooldown, halt persistente | 23 |
| `tests/unit/test_trade_monitor.py` | SL/TP/Trailing dinámico BUY+SELL, PnL, close reasons | 24 |
| `tests/unit/test_portfolio.py` | Exposure, cash, balance, coherencia entre módulos | 10 |
| `tests/unit/test_strategies.py` | Señales, SL/TP ATR, scoring, directionality | 10 |
| `tests/integration/test_pipeline.py` | Flujo completo: signal → risk → execute → close | 8 |

Ejecutar: `cd /opt/trading && pytest tests/ -v`

---

## 7. Mejoras Pendientes (Diseño)

### 7.1 Estrategias SELL
**Estado actual**: Solo `TrendMomentumStrategy` genera SELL (condición muy estricta).

**Mejora propuesta**: Añadir SELL a MeanReversion (BB upper extreme) y Breakout (breakdown).

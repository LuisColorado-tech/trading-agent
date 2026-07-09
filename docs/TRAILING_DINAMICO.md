# Trailing Dinámico — Flujo Técnico (Fase A)

> Fecha: 2026-03-17  
> Versión: Fase A — Trailing stop progresivo  
> Módulo: `agents/trade_monitor.py`

---

## 1. Problema Actual

El trailing stop actual ejecuta **un solo movimiento**: cuando el profit alcanza 1.5×R,
mueve el SL a break-even (entry). Después de ese movimiento, el SL queda fijo.

### Consecuencias

1. **No captura ganancias parciales**: Si el precio sube 3R y luego revierte a entry, el trade
   cierra en $0 (break-even). Se pierde todo el recorrido favorable.
2. **Efecto casi nulo en trend\_momentum**: TP está a 1.667R y trailing activa a 1.5R →
   solo 0.167R de ventana protegida antes de que TP cierre.
3. **Breakout desaprovechado**: Con TP a 3.0R, la ventana es mayor (0.75R),
   pero igualmente no escala la protección.

### Código actual (líneas 120-129 de `trade_monitor.py`)

```python
# Trailing: mover SL a break-even cuando ganancia > 1.5 × riesgo
risk_distance = abs(entry_price - stop_loss)
trailing_threshold = entry_price + (1.5 * risk_distance)  # BUY

if current_price >= trailing_threshold and stop_loss < entry_price:
    self._update_stop_loss(trade['id'], entry_price)  # Único movimiento: → entry
    stop_loss = entry_price
```

---

## 2. Solución: Trailing Progresivo por Escalones de R

Reemplazar el movimiento único por **escalones incrementales** que avanzan el SL
conforme el precio se mueve a favor, bloqueando fracciones crecientes de ganancia.

### Principios de diseño

| Principio | Implementación |
|-----------|----------------|
| **El SL solo avanza, nunca retrocede** | Guard: `new_sl > current_sl` (BUY) o `new_sl < current_sl` (SELL) |
| **R es inmutable por trade** | Se calcula una sola vez del SL original y se persiste en metadata |
| **TP se mantiene intacto** | Trailing protege; TP cierra si se alcanza |
| **Compatibilidad con trades existentes** | Trades legacy (sin `initial_risk`) no se rompen |
| **Sin acoplamiento nuevo** | Parámetros como constantes locales, sin dependencias |

---

## 3. Modelo Matemático

### 3.1 Variables

| Símbolo | Definición | Valor default |
|---------|-----------|---------------|
| $R$ | Riesgo Inicial = $\|p_{entry} - p_{SL_{original}}\|$ | Calculado por trade |
| $P$ | Profit actual en múltiplos de R | Variable |
| $T_{act}$ | Umbral de activación | $1.0R$ |
| $S$ | Tamaño de paso entre escalones | $0.5R$ |
| $O$ | Offset: cuánto rezaga el SL respecto al trigger | $1.0R$ |

### 3.2 Fórmula General

**Cálculo del profit en R:**

$$P_{BUY} = \frac{p_{current} - p_{entry}}{R}$$

$$P_{SELL} = \frac{p_{entry} - p_{current}}{R}$$

**Número de pasos completados:**

$$n = \left\lfloor \frac{P - T_{act}}{S} \right\rfloor \quad \text{(solo si } P \geq T_{act}\text{)}$$

**Profit bloqueado:**

$$L = n \times S$$

**Nuevo SL:**

$$SL_{BUY} = p_{entry} + L \times R$$

$$SL_{SELL} = p_{entry} - L \times R$$

**Condición de actualización:**

$$SL_{new} > SL_{actual} \text{ (BUY)} \quad \lor \quad SL_{new} < SL_{actual} \text{ (SELL)}$$

### 3.3 Tabla de Escalones

| Paso $n$ | Trigger $P \geq$ | $L$ (locked) | SL BUY | SL SELL | Ejemplo BTC (entry=75000, R=1000) |
|----------|------------------|------|---------|---------|-----------------------------------|
| 0 | 1.0R | 0R | entry | entry | SL → 75,000 (BE) |
| 1 | 1.5R | 0.5R | entry + 0.5R | entry − 0.5R | SL → 75,500 |
| 2 | 2.0R | 1.0R | entry + 1.0R | entry − 1.0R | SL → 76,000 |
| 3 | 2.5R | 1.5R | entry + 1.5R | entry − 1.5R | SL → 76,500 |
| 4 | 3.0R | 2.0R | entry + 2.0R | entry − 2.0R | SL → 77,000 |
| $n$ | $1.0 + 0.5n$ | $0.5n$ | $entry + 0.5nR$ | $entry - 0.5nR$ | continúa... |

### 3.4 Interacción con TP

El TP existente se mantiene sin cambios. Se evalúa **después** del trailing:

| Estrategia | R (ATR×) | TP (ATR×) | TP en R | Pasos trailing antes de TP |
|------------|----------|-----------|---------|---------------------------|
| trend\_momentum | 1.5 | 2.5 | 1.667R | 2 (paso 0: BE, paso 1: +0.5R) |
| mean\_reversion | 1.5 | BB\_mid | variable | depende de BB |
| breakout | 1.0 | 3.0 | 3.0R | 5 (paso 0→4: BE hasta +2.0R) |

**Escenario clave — trend\_momentum**:
- Precio sube a 1.5R → trailing avanza SL a entry+0.5R
- Precio sube a TP (1.667R) → cierra por TAKE\_PROFIT
- Si revierte desde 1.5R → cierra en entry+0.5R con 0.5R de ganancia capturada (antes: $0)

**Escenario clave — breakout**:
- Precio sube a 3.0R → SL ya está en entry+2.0R
- Si revierte → cierra con 2.0R de ganancia (antes: $0 en break-even)

---

## 4. Flujo de Evaluación (`_evaluate_trade`)

```
_evaluate_trade(trade)
│
├── 1. OBTENER PRECIO ACTUAL
│   ├── _get_current_price(asset) → float
│   └── Si None → return None (skip)
│
├── 2. EXTRAER PARÁMETROS
│   ├── entry_price, stop_loss, take_profit, position_size, side
│   └── metadata = trade['metadata'] or {}
│
├── 3. CALCULAR R (initial_risk)
│   │
│   ├── ¿metadata tiene 'initial_risk'?
│   │   └── SÍ → initial_risk = metadata['initial_risk']  (preservado de evaluciones previas)
│   │
│   ├── ¿metadata tiene 'trailing_activated' pero NO 'initial_risk'?
│   │   └── SÍ → Trade LEGACY (viejo trailing, ya en break-even)
│   │       └── initial_risk = 0 → Skip trailing, mantener SL actual
│   │
│   └── Else → Trade FRESCO
│       └── initial_risk = |entry_price - stop_loss|
│
├── 4. TRAILING DINÁMICO (solo si initial_risk > 0)
│   │
│   ├── 4a. Calcular Profit en R
│   │   ├── BUY:  P = (current_price - entry_price) / initial_risk
│   │   └── SELL: P = (entry_price - current_price) / initial_risk
│   │
│   ├── 4b. ¿P ≥ 1.0R? (activation_threshold)
│   │   │
│   │   ├── NO → Sin trailing, continuar a paso 5
│   │   │
│   │   └── SÍ → Calcular nuevo nivel
│   │       ├── n = floor((P - 1.0) / 0.5)
│   │       ├── locked_r = n × 0.5
│   │       ├── BUY:  new_sl = entry + locked_r × R
│   │       └── SELL: new_sl = entry - locked_r × R
│   │
│   └── 4c. ¿new_sl más protector que stop_loss actual?
│       ├── BUY:  new_sl > stop_loss? → Actualizar
│       └── SELL: new_sl < stop_loss? → Actualizar
│           │
│           ├── _update_trailing(trade_id, new_sl, R, level, locked_r, metadata)
│           │   ├── UPDATE trades SET stop_loss, metadata
│           │   ├── metadata += {initial_risk, trailing_activated, trailing_level, trailing_history}
│           │   └── PUBLISH Redis 'trades:trailing'
│           │
│           ├── stop_loss = new_sl  (variable local actualizada)
│           └── LOG: "TRAILING {asset} Level {n}: SL→{new_sl} (locked {locked_r}R)"
│
├── 5. CHECK STOP LOSS
│   ├── BUY:  current_price ≤ stop_loss?
│   ├── SELL: current_price ≥ stop_loss?
│   │
│   └── SÍ → Cerrar trade
│       ├── close_reason = 'TRAILING_STOP' si trailing fue activado
│       ├── close_reason = 'STOP_LOSS' si trailing nunca activó
│       ├── PnL = (SL - entry) × size  [BUY]
│       └── return {exit_price: SL, close_reason, pnl, pnl_pct}
│
├── 6. CHECK TAKE PROFIT
│   ├── BUY:  current_price ≥ take_profit?
│   ├── SELL: current_price ≤ take_profit?
│   │
│   └── SÍ → Cerrar trade
│       ├── close_reason = 'TAKE_PROFIT'
│       └── return {exit_price: TP, close_reason, pnl, pnl_pct}
│
└── 7. TRADE SIGUE ABIERTO → return None
```

---

## 5. Almacenamiento (metadata JSONB)

### 5.1 Estructura de metadata tras trailing

```json
{
  "initial_risk": 1000.0,
  "trailing_activated": true,
  "trailing_level": 2,
  "trailing_history": [
    {"level": 0, "sl": 75000.0, "locked_r": 0.0, "ts": "2026-03-17T10:00:00Z"},
    {"level": 1, "sl": 75500.0, "locked_r": 0.5, "ts": "2026-03-17T12:00:00Z"},
    {"level": 2, "sl": 76000.0, "locked_r": 1.0, "ts": "2026-03-17T14:00:00Z"}
  ]
}
```

### 5.2 Campos

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `initial_risk` | float | $\|entry - SL_{original}\|$, inmutable por trade |
| `trailing_activated` | bool | `true` cuando cualquier paso se activa |
| `trailing_level` | int | Último paso alcanzado ($n$) |
| `trailing_history` | array | Historial de todos los movimientos de SL |

### 5.3 Razones de cierre

| `close_reason` | Cuándo |
|----------------|--------|
| `STOP_LOSS` | Precio alcanza SL original (sin trailing activado) |
| `TRAILING_STOP` | Precio alcanza SL que fue avanzado por trailing |
| `TAKE_PROFIT` | Precio alcanza TP (independiente del trailing) |

---

## 6. Compatibilidad con Trades Existentes

| Tipo de trade | Detección | Comportamiento |
|---------------|-----------|----------------|
| **Nuevo** (post-implementación) | `metadata` vacía o sin `initial_risk` | Calcula R del SL original, persiste, trailing prograsivo completo |
| **Legacy con trailing** (pre-implementación) | `trailing_activated=true` pero sin `initial_risk` | R irrecuperable (SL ya es entry). `initial_risk=0`. Skip trailing. Cierra por TP o SL actual |
| **Legacy sin trailing** | `metadata` vacía, SL ≠ entry | Comportamiento idéntico a trade nuevo |

---

## 7. Parámetros Configurables

Definidos como constantes en `agents/trade_monitor.py`:

```python
TRAILING_ACTIVATION_R = 1.0   # Profit mínimo en R para activar trailing
TRAILING_STEP_R = 0.5         # Incremento entre escalones (en R)
TRAILING_OFFSET_R = 1.0       # SL se coloca a (trigger - offset)×R del entry
```

Y referenciados en `config/exchange_config.yaml`:

```yaml
trailing:
  activation_threshold_r: 1.0
  step_size_r: 0.5
  lock_offset_r: 1.0
```

### Justificación de valores

| Parámetro | Valor | Razón |
|-----------|-------|-------|
| Activación 1.0R | Antes era 1.5R | 1.0R da protección más temprana. El trade ya recorrió 1× su riesgo a favor — momentum confirmado |
| Paso 0.5R | — | Balance entre granularidad y ruido. Pasos más pequeños (0.25R) causarían actualizaciones excesivas |
| Offset 1.0R | — | SL siempre 1.0R detrás del trigger. Evita que el trailing se active y cierre en el mismo tick |

---

## 8. Eventos Redis

Nuevo canal `trades:trailing` para notificar avances de trailing al dashboard:

```json
{
  "trade_id": "uuid",
  "asset": "BTC",
  "side": "BUY",
  "level": 2,
  "new_sl": 76000.0,
  "locked_r": 1.0,
  "initial_risk": 1000.0
}
```

---

## 9. Tests Requeridos

| # | Test | Descripción | Tipo |
|---|------|-------------|------|
| T1 | `test_buy_trailing_step_0_breakeven` | P=1.0R → SL=entry | Unit |
| T2 | `test_buy_trailing_step_1_lock_half_r` | P=1.5R → SL=entry+0.5R | Unit |
| T3 | `test_buy_trailing_step_2_lock_full_r` | P=2.0R → SL=entry+1.0R | Unit |
| T4 | `test_buy_trailing_gap_multiple_levels` | P=2.3R → SL=entry+1.0R (paso 2, no 3) | Unit |
| T5 | `test_sell_trailing_step_0` | SELL P=1.0R → SL=entry | Unit |
| T6 | `test_sell_trailing_step_1` | SELL P=1.5R → SL=entry-0.5R | Unit |
| T7 | `test_trailing_sl_never_retreats` | Precio baja → SL no retrocede | Unit |
| T8 | `test_initial_risk_persisted` | metadata contiene initial\_risk tras trailing | Unit |
| T9 | `test_legacy_trade_no_crash` | Trade con trailing\_activated sin initial\_risk | Unit |
| T10 | `test_tp_still_closes_with_trailing_active` | TP cierra independiente del trailing | Unit |
| T11 | `test_close_reason_trailing_stop` | Cierre en SL avanzado → TRAILING\_STOP | Unit |
| T12 | `test_close_reason_original_sl` | Cierre en SL original → STOP\_LOSS | Unit |
| T13 | `test_no_trailing_below_activation` | P < 1.0R → sin movimiento de SL | Unit |

---

## 10. Archivos Modificados

| Archivo | Cambio |
|---------|--------|
| `agents/trade_monitor.py` | Reescritura de `_evaluate_trade()`, nuevo `_update_trailing()`, constantes trailing |
| `config/exchange_config.yaml` | Sección `trailing:` con parámetros |
| `tests/unit/test_trade_monitor.py` | 5 tests actualizados, 13 tests nuevos |
| `docs/AUDIT_PIPELINE.md` | Bug #6 marcado como ✅ Corregido |
| `docs/CHANGELOG.md` | Entrada trailing dinámico |
| `docs/ARCHITECTURE.md` | Sección TradeMonitor actualizada |

---

## 11. Diagrama de Secuencia — Trade con Trailing

```
Precio
  ▲
  │                                              ┌── TP (2.5 ATR)
  │                                         ●────┘  close: TAKE_PROFIT
  │                                    ●
  │                               ●
  │          ╔═══ Paso 3 ═══╗●
  │          ║ SL = entry   ║
  │          ║ + 1.5R       ║
  │     ╔═══ Paso 2 ════════╝
  │     ║ SL = entry
  │     ║ + 1.0R
  │╔═══ Paso 1 ═════════════╝
  │║ SL = entry
  │║ + 0.5R
  │╔══ Paso 0 (BE) ═════════╝
  │║ SL = entry
  │║
  │──── Entry ───────────────────────────────────
  │
  │ SL original ────────────────────────────────
  │
  └──────────────────────────────────────────── Tiempo
```

Cada `═══` representa un escalón donde el SL sube irreversiblemente.
Si el precio revierte en cualquier punto, el SL captura la ganancia bloqueada.

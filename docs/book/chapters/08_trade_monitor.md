# Capítulo 8: El Trade Monitor — Anatomía de un Bug Crítico

## 8.1 El Bug: Trades que Nunca Cerraban

Durante las primeras semanas de paper trading, el agente se comportaba de forma aparentemente correcta: analizaba el mercado, detectaba señales técnicas, consultaba a Claude para validar la lógica, y abría trades con sus respectivos stop-loss y take-profit. Todo parecía funcionar. Excepto por un detalle devastador: **ningún trade se cerraba jamás**.

El portfolio mostraba una lista creciente de posiciones abiertas. Algunas en profit, otras en pérdida catastrófica, pero todas con status `OPEN`. El balance disponible se reducía con cada nueva operación porque el capital quedaba comprometido en posiciones que nunca liberaban fondos.

### El diagnóstico

Una consulta rápida a PostgreSQL reveló la magnitud del problema:

```sql
SELECT status, COUNT(*) FROM trades GROUP BY status;
--  status  | count
-- ---------+-------
--  OPEN    |    47
--  CLOSED  |     0
```

Cero trades cerrados. Cuarenta y siete posiciones abiertas acumuladas durante días de ejecución continua.

### La causa raíz

Al revisar el código del agente, la causa era evidente una vez que sabías dónde mirar: **no existía ningún componente TradeMonitor**. El flujo del agente era:

1. Obtener datos de mercado → ✅
2. Calcular indicadores técnicos → ✅
3. Detectar señales → ✅
4. Consultar a Claude → ✅
5. Abrir trade con SL/TP → ✅
6. **Monitorear precios contra SL/TP** → ❌ **No existía**
7. Cerrar trade cuando se alcance SL/TP → ❌ **Imposible sin el paso 6**

Los campos `stop_loss` y `take_profit` se guardaban correctamente en la base de datos. Pero eran datos decorativos — nadie los consultaba después. Es como instalar una alarma contra incendios pero nunca conectarla a la corriente.

### Por qué no se detectó antes

Este tipo de bug es particularmente insidioso porque el sistema no lanza errores. No hay excepciones, no hay logs de error, no hay crashes. El agente funciona "perfectamente" — simplemente omite una funcionalidad completa. En un sistema con muchos componentes, la ausencia de uno puede pasar desapercibida si no tienes métricas que validen el flujo completo.

---

## 8.2 Diseño de la Solución

El TradeMonitor se diseñó como un componente independiente con una responsabilidad clara y bien delimitada: **evaluar si algún trade abierto debe cerrarse**. Su ciclo de vida se ejecuta en cada iteración del loop principal, *antes* de buscar nuevas oportunidades.

### Responsabilidades del TradeMonitor

1. **Consultar trades abiertos** — `SELECT * FROM trades WHERE status = 'OPEN'`
2. **Obtener precio actual** — para cada activo, buscar el último precio en `market_data`
3. **Evaluar SL/TP** — comparar precio actual contra los niveles de cada trade
4. **Cerrar trade** — si se alcanza un nivel, ejecutar el proceso de cierre completo

### La función central: `_evaluate_trade()`

El corazón del TradeMonitor es una función que toma un trade y decide si debe cerrarse:

```python
def _evaluate_trade(self, trade):
    """Evalúa si un trade abierto debe cerrarse por SL o TP."""
    asset = trade['asset']
    side = trade['side']
    current_price = self._get_current_price(asset)
    
    if current_price is None:
        logger.warning(f"Sin precio actual para {asset}, skip evaluación")
        return
    
    entry_price = float(trade['entry_price'])
    stop_loss = float(trade['stop_loss'])
    take_profit = float(trade['take_profit'])
    
    close_reason = None
    
    if side == 'BUY':
        if current_price <= stop_loss:
            close_reason = 'STOP_LOSS'
        elif current_price >= take_profit:
            close_reason = 'TAKE_PROFIT'
    elif side == 'SELL':
        if current_price >= stop_loss:
            close_reason = 'STOP_LOSS'
        elif current_price <= take_profit:
            close_reason = 'TAKE_PROFIT'
    
    if close_reason:
        self._close_trade(trade, current_price, close_reason)
```

### La inversión lógica BUY/SELL — el detalle que mata

Este fragmento de código parece simple, pero contiene una de las fuentes de bugs más comunes en sistemas de trading: **la lógica invertida entre BUY y SELL**.

Para un trade **BUY** (compramos esperando que suba):
- **Stop Loss**: el precio CAE por debajo de nuestro límite → `current_price <= stop_loss`
- **Take Profit**: el precio SUBE por encima de nuestro objetivo → `current_price >= take_profit`

Para un trade **SELL** (vendemos esperando que baje):
- **Stop Loss**: el precio SUBE por encima de nuestro límite → `current_price >= stop_loss` *(invertido)*
- **Take Profit**: el precio BAJA por debajo de nuestro objetivo → `current_price <= take_profit` *(invertido)*

La confusión surge porque intuitivamente asociamos "stop loss" con "precio baja", pero en un SELL es exactamente lo contrario. Si vendiste esperando que baje y el precio sube, *eso* es tu pérdida.

```
BUY:  SL está DEBAJO del entry_price    |  TP está ENCIMA del entry_price
SELL: SL está ENCIMA del entry_price     |  TP está DEBAJO del entry_price

         SELL TP          BUY SL
            ↓                ↓
    --------+---[ENTRY]------+--------→ precio
                    ↑                ↑
                 SELL SL          BUY TP
```

> **Lección**: si estás implementando un sistema de trading y solo testeas trades BUY, tu lógica SELL probablemente esté rota. Testea ambos lados explícitamente.

---

## 8.3 Trailing Stop

### Concepto académico

Un trailing stop es un stop-loss que se mueve en la dirección del profit. La idea es simple pero poderosa: si el trade va a tu favor, mueves el SL para proteger las ganancias acumuladas. Si el precio se revierte, sales con profit (o al menos sin pérdida) en lugar de devolver todo lo ganado.

En la práctica, existen muchas variantes: trailing por porcentaje, por ATR, por niveles de soporte/resistencia. Nuestra implementación usa un enfoque conservador: **mover el SL a break-even cuando el profit supera 1.5× la distancia de riesgo original**.

### Implementación

```python
def _check_trailing_stop(self, trade, current_price):
    """Activa trailing stop moviendo SL a break-even."""
    side = trade['side']
    entry_price = float(trade['entry_price'])
    stop_loss = float(trade['stop_loss'])
    
    risk_distance = abs(entry_price - stop_loss)
    
    if side == 'BUY':
        trailing_threshold = entry_price + (1.5 * risk_distance)
        if current_price >= trailing_threshold and stop_loss < entry_price:
            self._update_stop_loss(trade['id'], entry_price)
            logger.info(
                f"Trailing activado trade {trade['id']}: "
                f"SL movido de {stop_loss:.2f} a {entry_price:.2f} (break-even)"
            )
    elif side == 'SELL':
        trailing_threshold = entry_price - (1.5 * risk_distance)
        if current_price <= trailing_threshold and stop_loss > entry_price:
            self._update_stop_loss(trade['id'], entry_price)
            logger.info(
                f"Trailing activado trade {trade['id']}: "
                f"SL movido de {stop_loss:.2f} a {entry_price:.2f} (break-even)"
            )
```

### ¿Por qué 1.5×?

El factor 1.5 no es arbitrario. Es un balance pragmático:

- **1.0×**: demasiado agresivo — moverías el SL a break-even apenas el trade tiene un profit igual al riesgo. En mercados volátiles, el ruido normal del precio puede sacarte de un trade bueno.
- **2.0×**: demasiado conservador — necesitas un movimiento muy grande antes de proteger ganancias. Muchos trades podrían revertirse antes de llegar.
- **1.5×**: el trade ha demostrado momentum suficiente como para justificar protección, pero sin exigir un movimiento extremo.

### Ejemplo numérico

```
Trade BUY ETH:
  Entry:     $3,000
  Stop Loss: $2,900  (riesgo: $100)
  Take Profit: $3,300

  risk_distance = |3000 - 2900| = $100
  trailing_threshold = 3000 + (1.5 × 100) = $3,150

  Escenario: ETH sube a $3,160
  → $3,160 >= $3,150 ✅  y  $2,900 < $3,000 ✅
  → SL se mueve de $2,900 a $3,000 (break-even)
  
  Ahora el peor caso es salir en $3,000 → PnL = $0
  Antes el peor caso era salir en $2,900 → PnL = -$100
```

### Auditoría con metadata JSONB

Cada activación de trailing se registra en el campo `metadata` del trade usando `jsonb_set`:

```sql
UPDATE trades 
SET stop_loss = $1,
    metadata = jsonb_set(
        COALESCE(metadata, '{}'::jsonb),
        '{trailing_activated}',
        'true'
    )
WHERE id = $2;
```

Esto permite reconstruir la historia de cada trade: no solo si cerró en SL o TP, sino si el trailing se activó antes. Es información crítica para optimizar el factor de trailing en el futuro.

---

## 8.4 El Proceso de Cierre

Cuando el TradeMonitor decide que un trade debe cerrarse, se ejecuta un proceso que actualiza múltiples tablas de forma coherente. Si algún paso falla, toda la transacción se revierte.

### Los 4 pasos del cierre

**Paso 1: Actualizar el trade**

```sql
UPDATE trades SET
    status = 'CLOSED',
    exit_price = $1,
    close_reason = $2,       -- 'STOP_LOSS' | 'TAKE_PROFIT'
    pnl = $3,
    pnl_pct = $4,
    timestamp_close = NOW()
WHERE id = $5;
```

**Paso 2: Actualizar el portfolio**

El portfolio debe reflejar el resultado del trade:

```python
new_balance = current_balance + pnl
new_available = current_available + (entry_price * position_size) + pnl
new_peak = max(current_peak, new_balance)
new_drawdown = ((new_peak - new_balance) / new_peak) * 100
new_exposure = self._calculate_total_exposure()  # recalcular
```

Cada campo tiene su razón de ser:
- `balance`: valor total del portfolio
- `available_cash`: capital libre para nuevos trades (se libera lo invertido ± PnL)
- `peak_balance`: máximo histórico (para calcular drawdown)
- `current_drawdown`: distancia desde el pico — si supera el límite, el sistema se detiene
- `exposure`: porcentaje del capital **en riesgo** en trades abiertos, calculado como $\sum |entry - SL| \times size / balance$ (risk-based, no nocional)

**Paso 3: Guardar snapshot del portfolio**

```sql
INSERT INTO portfolio_snapshots (balance, available_cash, exposure, drawdown, timestamp)
VALUES ($1, $2, $3, $4, NOW());
```

Estos snapshots forman la **curva de equity** — la serie temporal del valor del portfolio. Es la métrica más importante para evaluar el rendimiento del sistema.

**Paso 4: Publicar evento en Redis**

```python
redis_client.publish('trades:closed', json.dumps({
    'trade_id': trade['id'],
    'asset': trade['asset'],
    'side': trade['side'],
    'pnl': pnl,
    'close_reason': close_reason
}))
```

El evento `trades:closed` permite que otros componentes reaccionen al cierre: el dashboard puede actualizar en tiempo real, un futuro sistema de alertas puede notificar por Telegram, etc. Redis pub/sub desacopla al TradeMonitor de los consumidores.

---

## 8.5 Cálculo de PnL

El PnL (Profit and Loss) es la métrica más básica de un trade: ¿cuánto ganaste o perdiste?

### Fórmula

```python
if side == 'BUY':
    pnl = (exit_price - entry_price) * position_size
else:  # SELL
    pnl = (entry_price - exit_price) * position_size

pnl_pct = (pnl / (entry_price * position_size)) * 100
```

### Desglose para BUY

Compraste a `entry_price`, vendiste a `exit_price`. Si subió, ganaste:

```
Entry: $100, Exit: $110, Size: 2 unidades
PnL = (110 - 100) × 2 = +$20  (ganancia)

Entry: $100, Exit: $90, Size: 2 unidades
PnL = (90 - 100) × 2 = -$20  (pérdida)
```

### Desglose para SELL

Vendiste a `entry_price`, recompraste a `exit_price`. Si bajó, ganaste:

```
Entry: $100, Exit: $90, Size: 2 unidades
PnL = (100 - 90) × 2 = +$20  (ganancia — el precio bajó como esperabas)

Entry: $100, Exit: $110, Size: 2 unidades
PnL = (100 - 110) × 2 = -$20  (pérdida — el precio subió en tu contra)
```

### PnL porcentual

El porcentaje se calcula sobre el capital invertido:

```
Capital invertido = entry_price × position_size = 100 × 2 = $200
PnL% = (20 / 200) × 100 = 10%
```

Esto normaliza el rendimiento: un PnL de +$20 en un trade de $200 es 10%, pero en un trade de $2,000 es solo 1%. El porcentaje te dice la eficiencia del capital.

---

## 8.6 Lecciones Aprendidas

### La brecha entre especificación y código

Este bug es un ejemplo clásico de lo que podríamos llamar "la brecha de implementación". La especificación del sistema decía claramente: *"Cada trade tendrá stop-loss y take-profit"*. Y era cierto — se almacenaban en la base de datos. Pero la especificación *asumía* que alguien implementaría la verificación. Nadie lo hizo.

En sistemas complejos, es fácil que un componente crítico caiga en la grieta entre dos responsabilidades. El módulo de apertura de trades dice "yo pongo el SL/TP". El loop principal dice "yo ejecuto componentes". Pero nadie escribió el componente intermedio que realmente usa esos valores.

**Contramedida**: Para cada dato que se escribe en la base de datos, debe existir un consumidor explícito. Si guardas un `stop_loss`, alguien tiene que leerlo y actuar. Si no puedes identificar quién, hay un bug latente.

### El paper trading salvó dinero real

Este es exactamente el escenario para el cual existe el paper trading. Con dinero simulado, descubrir que los trades nunca cierran es una anécdota. Con dinero real, sería una catástrofe: posiciones acumulándose, capital inmovilizado, pérdidas no realizadas creciendo sin límite.

El paper trading no es "una fase previa al trading real". Es una herramienta de verificación de software. Es tu test de integración con datos reales de mercado.

### Monitor-first design

Después de corregir este bug, se reestructuró el loop principal para que el TradeMonitor se ejecute **antes** de buscar nuevas oportunidades:

```python
while True:
    # PRIMERO: ¿hay trades que cerrar?
    trade_monitor.evaluate_open_trades()
    
    # SEGUNDO: ¿hay nuevas oportunidades?
    signals = signal_detector.scan()
    # ...
```

La lógica es simple: antes de abrir trades nuevos, asegúrate de gestionar los que ya tienes. Esto también actualiza el `available_cash` antes de calcular el sizing de nuevas posiciones.

### La inversión lógica BUY/SELL como fuente recurrente de bugs

La lógica invertida entre BUY y SELL no es un error de novato — es una fuente constante de bugs incluso en sistemas institucionales. Cada vez que escribes una comparación de precios en un sistema de trading, tienes que preguntarte: *"¿esto funciona para ambos lados?"*

La recomendación práctica: escribe tests unitarios explícitos para ambos lados, con casos límite:

```python
def test_buy_stop_loss_triggered():
    trade = make_trade(side='BUY', entry=100, sl=95, tp=110)
    assert evaluate(trade, current_price=94) == 'STOP_LOSS'

def test_sell_stop_loss_triggered():
    trade = make_trade(side='SELL', entry=100, sl=105, tp=90)
    assert evaluate(trade, current_price=106) == 'STOP_LOSS'

def test_buy_take_profit_triggered():
    trade = make_trade(side='BUY', entry=100, sl=95, tp=110)
    assert evaluate(trade, current_price=111) == 'TAKE_PROFIT'

def test_sell_take_profit_triggered():
    trade = make_trade(side='SELL', entry=100, sl=105, tp=90)
    assert evaluate(trade, current_price=89) == 'TAKE_PROFIT'
```

Los cuatro tests. Siempre. No asumas que "si BUY funciona, SELL también". No es así.

---

## Resumen del Capítulo

| Concepto | Detalle |
|---|---|
| **Bug** | Trades se abrían pero nunca se cerraban (no existía TradeMonitor) |
| **Causa** | Brecha entre especificación ("SL/TP") e implementación (nadie los verificaba) |
| **Solución** | TradeMonitor que evalúa trades abiertos cada ciclo |
| **Trailing Stop** | Mueve SL a break-even cuando profit > 1.5× riesgo |
| **Cierre** | 4 pasos atómicos: trade, portfolio, snapshot, evento Redis |
| **PnL** | BUY: (exit - entry) × size / SELL: (entry - exit) × size |
| **Lección clave** | Paper trading es verificación de software, no simulación de mercado |

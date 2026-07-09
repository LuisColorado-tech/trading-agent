# Capítulo 6: Arquitectura de Agentes

> *"La inteligencia no reside en un agente individual, sino en la interacción emergente entre agentes especializados."*
> — Gerhard Weiss, *Multiagent Systems* (2013)

Un sistema de trading algorítmico puede diseñarse como un monolito: una única función `main()` que lee datos, calcula indicadores, decide cuándo operar y ejecuta órdenes. Este enfoque funciona para prototipos, pero colapsa ante la realidad operativa — los exchanges fallan, los datos llegan incompletos, las estrategias deben evolucionar sin detener el sistema. Este capítulo presenta la arquitectura multi-agente que sustenta nuestro Trading Agent, donde cada responsabilidad está encapsulada en una unidad autónoma que se comunica con las demás mediante eventos asíncronos.

---

## 6.1 El Patrón Agent

### Definición Formal

En la literatura de inteligencia artificial distribuida, un **agente** es una entidad computacional que satisface tres propiedades (Wooldridge & Jennings, 1995):

1. **Autonomía**: opera sin intervención directa de humanos u otros agentes, manteniendo control interno sobre su estado y acciones.
2. **Reactividad**: percibe su entorno (datos de mercado, señales, eventos) y responde oportunamente a cambios.
3. **Proactividad**: no solo reacciona — genera comportamiento dirigido a objetivos (detectar señales, minimizar riesgo).

En el contexto de ingeniería de software, un agente es un **módulo con estado propio, interfaz pública definida y responsabilidad única**, que se comunica con otros agentes exclusivamente mediante mensajes (no llamadas directas). Esto lo diferencia de un simple servicio o clase: el agente *decide* cuándo actuar y *controla* su propio ciclo de vida.

### Multi-Agent Systems (MAS)

Los **Sistemas Multi-Agente** (Ferber, 1999) formalizan cómo múltiples agentes interactúan para resolver problemas que exceden la capacidad individual. Los principios fundamentales son:

- **Descentralización**: no existe un controlador omnisciente. Cada agente toma decisiones locales con información parcial.
- **Comunicación**: los agentes intercambian mensajes siguiendo protocolos definidos (en nuestro caso, Redis Pub/Sub con formato JSON).
- **Coordinación**: las acciones individuales se articulan mediante mecanismos de consenso o jerarquía (en nuestro caso, una jerarquía estricta de autoridad).
- **Emergencia**: el comportamiento global del sistema — detectar oportunidad, evaluar riesgo, ejecutar, monitorear — emerge de la interacción de agentes simples.

### ¿Por Qué Agentes en Vez de un Monolito?

La decisión arquitectónica responde a tres exigencias operativas concretas:

| Criterio | Monolito | Multi-Agente |
|---|---|---|
| **Separación de concerns** | Una función con 1000+ líneas; cambiar SL afecta escaneo | Cada agente es un archivo independiente; `RiskManager` no importa `MarketScanner` |
| **Testabilidad** | Requiere mock del exchange, DB, Redis, LLM para cualquier test | Cada agente se testea en aislamiento con fixtures específicos |
| **Resiliencia** | Error en cálculo de indicador → crash completo | Error en `MarketScanner` → log + continúa; los demás agentes siguen operando |
| **Evolución** | Agregar estrategia requiere refactorizar el loop principal | Nueva estrategia = nueva clase; `StrategyEngine` la descubre automáticamente |
| **Observabilidad** | Un log monolítico difícil de filtrar | Cada agente emite eventos Redis; el dashboard puede suscribirse selectivamente |

Formalmente, si modelamos el sistema como un grafo dirigido $G = (V, E)$ donde cada agente es un vértice $v \in V$ y cada canal de comunicación un arco $e \in E$, el **acoplamiento** del sistema se mide por la densidad del grafo:

$$\rho = \frac{|E|}{|V|(|V|-1)}$$

En un monolito, $\rho \to 1$ (todo depende de todo). En nuestra arquitectura, $\rho \approx 0.3$ — cada agente se comunica solo con sus vecinos inmediatos en el pipeline.

---

## 6.2 Pipeline de Ejecución

El sistema sigue un **pipeline lineal estricto** donde cada etapa transforma datos y los pasa a la siguiente. Esta topología es deliberada: minimiza los ciclos en el grafo de dependencias y garantiza que la información fluya en una sola dirección.

```
MarketFeed → MarketScanner → StrategyEngine → RiskManager → ExecutionAgent → TradeMonitor
    ↓              ↓               ↓               ↓              ↓              ↓
  OHLCV        Signals      Opportunities     Risk Check       Execute        Monitor
  (DB)       (DB+Redis)     (Redis pub)      (approve/reject)  (DB+Redis)    (SL/TP/Trail)
```

### Descripción de Cada Etapa

**1. MarketFeed** — *Ingestión de datos crudos*. Conecta con exchanges vía API REST (CCXT), descarga velas OHLCV para cada combinación activo/timeframe, y las persiste en PostgreSQL (`market_data`). Es un componente *pasivo*: no genera señales ni toma decisiones. Su responsabilidad es garantizar que la tabla `market_data` contenga datos frescos antes de que el scanner los consuma.

**2. MarketScanner** — *Detección de señales*. Itera sobre todos los activos definidos en `ASSET_MAP` y sus timeframes configurados. Para cada combinación, calcula indicadores técnicos mediante `IndicatorEngine.calculate()` y ejecuta reglas de detección (EMA cross, RSI extremo, Bollinger touch, volume spike). Las señales resultantes se persisten en PostgreSQL (`signals`) y se publican al canal Redis `signals:new`.

**3. StrategyEngine** — *Evaluación estratégica*. Recibe indicadores calculados y evalúa tres estrategias simultáneamente (TrendMomentum, MeanReversion, Breakout). Selecciona la de mayor score y solicita validación al LLM. Publica oportunidades aprobadas al canal Redis `strategies:opportunity`.

**4. RiskManager** — *Autoridad final de riesgo*. Examina la oportunidad contra seis reglas inmutables (drawdown, exposición, trades concurrentes, tamaño de posición, ratio R:R, anomalías). Solo si todas las reglas pasan, aprueba la ejecución. Este agente tiene **veto absoluto** — ni el LLM ni el StrategyEngine pueden invalidar su decisión.

**5. ExecutionAgent** — *Ejecución de órdenes*. Recibe señales aprobadas por el RiskManager. En modo paper, simula la orden; en modo live, ejecuta vía CCXT contra Kraken (market order + stop_market + limit). Persiste el trade en PostgreSQL y publica al canal `trades:executed`.

**6. TradeMonitor** — *Monitoreo post-ejecución*. Revisa continuamente los trades abiertos contra precios actuales. Evalúa condiciones de cierre (stop loss, take profit, trailing stop). Al cerrar un trade, actualiza la base de datos, recalcula el portfolio y publica al canal `trades:closed`.

### La Propiedad del Pipeline

Un aspecto fundamental: el pipeline es **idempotente por ciclo**. Si el scanner no detecta señales en un ciclo, las etapas posteriores simplemente no se ejecutan. El TradeMonitor, sin embargo, siempre se ejecuta primero — debe cerrar posiciones existentes antes de que se abran nuevas. Esta prioridad evita una condición peligrosa: abrir un trade cuando ya se debería haber cerrado otro por stop loss.

---

## 6.3 Event-Driven Architecture (Redis Pub/Sub)

### El Problema del Acoplamiento Directo

Si el `MarketScanner` llamara directamente a `StrategyEngine.evaluate()`, crearíamos un **acoplamiento temporal y espacial**: el scanner debe esperar a que la evaluación termine, y ambos deben estar en el mismo proceso. Esto elimina la posibilidad de escalar horizontalmente, dificulta el testing y hace imposible agregar observadores (dashboard, alertas, logs) sin modificar el código del scanner.

### Redis Pub/Sub como Backbone de Eventos

La arquitectura utiliza **Redis Pub/Sub** como bus de eventos, con cuatro canales definidos:

| Canal | Productor | Consumidores | Payload |
|---|---|---|---|
| `signals:new` | MarketScanner | Dashboard, Logs | Signal JSON (asset, type, direction, strength) |
| `strategies:opportunity` | StrategyEngine | Dashboard, Logs | Opportunity JSON (strategy, score, claude_analysis) |
| `trades:executed` | ExecutionAgent | Dashboard, TradeMonitor, Logs | Trade JSON (id, asset, side, price) |
| `trades:closed` | TradeMonitor | Dashboard, Portfolio, Logs | Close JSON (trade_id, pnl, reason) |

### Publicación en el Código Real

En `MarketScanner._publish_signals()`, cada señal detectada se serializa y publica:

```python
def _publish_signals(self, signals: list):
    """Publica señales en Redis pub/sub."""
    for sig in signals:
        self.redis.publish('signals:new', json.dumps(sig, default=str))
        logger.info(
            f'Signal: {sig["asset"]} {sig["signal_type"]} '
            f'dir={sig["direction"]} str={sig["strength"]:.2f}'
        )
```

El `StrategyEngine`, tras encontrar la mejor oportunidad y validarla con Claude, publica al canal de oportunidades. Y el `ExecutionAgent`, tras ejecutar un trade, notifica al ecosistema:

```python
self.redis.publish('trades:executed', json.dumps({
    'trade_id': trade_id,
    'asset': asset,
    'side': signal['direction'],
    'price': signal['indicators']['price'],
}))
```

### Más Allá de Pub/Sub: Redis como State Store

Redis no solo actúa como bus de eventos. El `MarketScanner` almacena snapshots de indicadores en un hash Redis para consulta rápida:

```python
self.redis.hset(
    'indicators:latest',
    f'{asset}:{tf}',
    json.dumps(asdict(ind), default=str),
)
```

La clave `indicators:latest` es un hash donde cada campo es `{asset}:{timeframe}` y el valor es el JSON completo del `IndicatorSet`. Esto permite que el dashboard (u otros consumidores) obtengan el estado más reciente de indicadores sin consultar PostgreSQL — una optimización crucial cuando múltiples clientes necesitan datos en tiempo real.

### Ventajas del Patrón Event-Driven

1. **Loose coupling**: el scanner no sabe quién consume sus señales. Podemos agregar un módulo de alertas Telegram sin tocar una línea del scanner.
2. **Asincronía natural**: los consumidores procesan eventos a su propio ritmo. Un consumidor lento no bloquea al productor.
3. **Observabilidad**: cualquier servicio puede suscribirse a cualquier canal y registrar eventos — la base del dashboard en tiempo real.
4. **Replay y auditoría**: aunque Redis Pub/Sub no persiste mensajes (a diferencia de Redis Streams), cada evento también se guarda en PostgreSQL, lo que permite replay post-mortem completo.

---

## 6.4 Jerarquía de Autoridad

La jerarquía de autoridad es el concepto más **crítico** de toda la arquitectura. En un sistema donde un LLM puede "opinar" sobre trades, la pregunta central es: *¿quién tiene la última palabra?*

### Los Cuatro Niveles

La jerarquía, de mayor a menor autoridad, es:

```
┌─────────────────────────────────────────────────┐
│  Nivel 1: RiskManager  — AUTORIDAD ABSOLUTA     │
│  Parámetros inmutables. No puede ser overridden  │
│  por Claude ni por ningún agente.                │
├─────────────────────────────────────────────────┤
│  Nivel 2: StrategyEngine — Selección Táctica     │
│  Elige la mejor oportunidad por score.           │
│  Claude puede vetar con ≥80% confianza (ABORT).  │
├─────────────────────────────────────────────────┤
│  Nivel 3: Claude/LLM — Rol Consultivo           │
│  Valida consistencia, detecta anomalías.         │
│  ABORT en StrategyEngine: conf ≥80%.             │
│  Block en RiskManager: conf ≥85% + CRITICAL.     │
├─────────────────────────────────────────────────┤
│  Nivel 4: MarketScanner — Datos Puros            │
│  Sin capacidad de decisión. Solo genera señales.  │
└─────────────────────────────────────────────────┘
```

### Por Qué el RiskManager es Inviolable

Los parámetros del `RiskManager` están definidos como **constantes de módulo**, no como configuración editable:

```python
# ─── PARÁMETROS INMUTABLES ─────────────────────────────────────────
MAX_RISK_PER_TRADE_PCT   = 0.01   # 1% del portafolio por trade
MAX_PORTFOLIO_EXPOSURE   = 0.05   # 5% máximo total en posiciones abiertas
STOP_LOSS_ATR_MULTIPLIER = 1.5    # Stop = Entry - (1.5 × ATR)
TAKE_PROFIT_ATR_MULT     = 2.5    # TP = Entry + (2.5 × ATR)
MAX_DRAWDOWN_STOP        = 0.10   # 10% drawdown → parar TODO
MAX_CONCURRENT_TRADES    = 3      # Máximo trades abiertos simultáneamente
MIN_RR_RATIO             = 1.5    # Ratio riesgo:recompensa mínimo
```

Estos valores no se leen de `.env` ni de una base de datos. Son literales en el código fuente. Para cambiarlos, hay que modificar el código, hacer commit, hacer deploy. **Es una decisión de diseño intencional**: en un momento de euforia de mercado, ni un desarrollador ni un LLM pueden "relajar" los límites sin pasar por el proceso completo de revisión de código.

### El Rol Acotado de Claude

El LLM interviene en dos puntos del pipeline, siempre con umbrales estrictos:

1. **En StrategyEngine** (signal_interpretation): Claude evalúa si los indicadores son consistentes con la señal propuesta. Solo puede emitir un `ABORT` si su confidence es $\geq 80\%$:

```python
if (claude_check.get('recommendation') == 'ABORT'
        and claude_check.get('confidence', 0) >= 80):
    logger.warning(f'Claude ABORT for {asset}: {claude_check.get("reasoning")}')
    return {'opportunity': False, 'reason': 'claude_abort', ...}
```

2. **En RiskManager** (anomaly_check): Claude busca anomalías en el trade propuesto. Solo puede bloquear si la severidad es `CRITICAL` **y** la confianza es $\geq 85\%$:

```python
if (claude_anomaly.get('severity') == 'CRITICAL'
        and claude_anomaly.get('confidence', 0) >= 85):
    return RiskDecision(approved=False, ..., reason='CLAUDE_CRITICAL_ANOMALY')
```

Observa la **asimetría deliberada**: Claude necesita mayor confianza ($85\%$ vs $80\%$) para bloquear en el RiskManager que para abortar en el StrategyEngine. Esto refleja que bloquear una operación que el RiskManager ya aprobó es una decisión más grave que descartar una oportunidad temprana.

### Principio Formal

Si denotamos la función de decisión de cada agente como $D_i$, la decisión final $D_{final}$ sigue la regla:

$$D_{final} = D_{Risk} \circ D_{Strategy} \circ D_{Claude}$$

donde $\circ$ denota composición con precedencia de izquierda a derecha. Si $D_{Risk}$ rechaza, $D_{final}$ es rechazo independientemente de las demás. Si $D_{Risk}$ aprueba pero $D_{Strategy}$ no encontró oportunidad, $D_{final}$ es no-operación. Claude solo puede *invertir* decisiones dentro de los umbrales definidos.

---

## 6.5 Cada Agente Analizado

### MarketScanner (`agents/market_scanner.py`)

El scanner es el **sensor** del sistema. Su método principal `scan()` itera sobre todos los activos definidos en `ASSET_MAP` y sus timeframes asociados:

```python
def scan(self) -> list:
    all_signals = []
    for asset in SCAN_ASSETS:
        asset_info = ASSET_MAP[asset]
        timeframes = asset_info['timeframes']
        for tf in timeframes:
            df = self.feed.refresh(asset, tf, limit=250)
            ind = IndicatorEngine.calculate(df, asset, tf)
            signals = self._detect_signals(ind)
            if signals:
                self._save_signals(signals)
                self._publish_signals(signals)
                all_signals.extend(signals)
            # Snapshot en Redis para consulta rápida
            self.redis.hset('indicators:latest', f'{asset}:{tf}',
                            json.dumps(asdict(ind), default=str))
    return all_signals
```

El scanner detecta **cinco tipos de señal**:

| Tipo | Indicador | Condición | Dirección |
|---|---|---|---|
| `EMA_CROSS_BULL` | EMA(20)/EMA(50) | EMA20 > EMA50 × 1.001 | BUY |
| `EMA_CROSS_BEAR` | EMA(20)/EMA(50) | EMA20 < EMA50 × 0.999 | SELL |
| `RSI_OVERSOLD` | RSI(14) | RSI < 30 | BUY |
| `RSI_OVERBOUGHT` | RSI(14) | RSI > 70 | SELL |
| `BB_LOWER_TOUCH` | BB(20,2) | %B < 0.05 | BUY |
| `BB_UPPER_TOUCH` | BB(20,2) | %B > 0.95 | SELL |
| `VOLUME_SPIKE` | Vol/SMA(20) | Ratio > 2.0 | NEUTRAL |

La **fuerza** de cada señal se normaliza al rango $[0, 1]$. Por ejemplo, para RSI oversold:

$$\text{strength} = \frac{30 - \text{RSI}}{30}$$

Un RSI de 15 produce strength $= 0.5$, mientras que un RSI de 5 produce strength $= 0.83$. El volume spike es siempre `NEUTRAL` en dirección — es una señal *confirmatoria*, no *direccional*.

### StrategyEngine (`agents/strategy_engine.py`)

El motor de estrategias es el **cerebro táctico**. Evalúa tres estrategias para cada combinación activo/timeframe y selecciona la de mayor score:

```python
results = []
for strategy in self.strategies:
    res = strategy.score(ind)  # o strategy.score(ind, df) para Breakout
    if res['direction'] != 'NEUTRAL':
        results.append(res)

best = max(results, key=lambda r: r['score'])
```

Tras seleccionar la mejor estrategia, consulta a Claude para verificación de consistencia. El resultado de Claude se adjunta al objeto de oportunidad como metadato (`claude_analysis`), pero solo puede vetar si cumple el umbral de confianza ≥80%.

El diseño clave aquí es que las tres estrategias se evalúan **en paralelo conceptual** (secuencial en código, pero independientes entre sí). Cada estrategia devuelve un score normalizado, lo que permite comparación directa. Si ninguna estrategia produce una señal no-neutral, el motor retorna `{'opportunity': False, 'reason': 'no_signal'}`.

### ExecutionAgent (`agents/execution_agent.py`)

El agente de ejecución sigue un flujo estrictamente secuencial:

```
Risk Check → Place Order → Save Trade → Claude Explanation → Redis Publish
```

1. **Risk Check**: invoca `RiskManager.evaluate()`. Si rechaza, retorna inmediatamente.
2. **Place Order**: en paper mode, `_simulate_order()` genera un fill ficticio. En live mode, ejecuta tres órdenes vía CCXT contra Kraken: (a) market order de entrada, (b) stop_market para SL, (c) limit para TP.
3. **Save Trade**: persiste todos los datos del trade en PostgreSQL (`trades`).
4. **Claude Explanation**: pide al LLM una explicación del trade (task_type `explain_trade`). Nota: está envuelto en `try/except` — si Claude falla, el trade ya está ejecutado.
5. **Redis Publish**: notifica a `trades:executed` para que el dashboard y otros consumidores actualicen su estado.

La simulación en paper mode es reveladoramente simple:

```python
def _simulate_order(self, signal, decision):
    return {
        'id': f'PAPER_{uuid.uuid4().hex[:8]}',
        'symbol': f'{signal["asset"]}/USDT',
        'side': signal['direction'],
        'amount': decision.position_size,
        'price': signal['indicators']['price'],
        'type': 'market',
        'status': 'closed',
    }
```

El fill price es exactamente el precio actual — sin slippage, sin spreads. Esta es una simplificación deliberada para paper trading: cuando el sistema migre a live, el exchange reportará el precio real del fill.

### TradeMonitor (`agents/trade_monitor.py`)

El monitor es el **guardián** de las posiciones abiertas. En cada ciclo, obtiene todos los trades con status `OPEN` y evalúa cada uno contra el precio actual:

```python
def check_open_trades(self, portfolio):
    open_trades = self._get_open_trades()
    closed = []
    for trade in open_trades:
        result = self._evaluate_trade(trade)
        if result:
            self._close_trade(trade, result['exit_price'],
                              result['close_reason'], portfolio)
            closed.append({...})
    return closed
```

La lógica de evaluación maneja cuatro escenarios para cada trade:

**Para BUY (posición larga)**:
- SL: si $P_{actual} \leq P_{SL}$ → cierre con pérdida
- TP: si $P_{actual} \geq P_{TP}$ → cierre con ganancia
- Trailing: si $P_{actual} \geq P_{entry} + 1.5 \times |P_{entry} - P_{SL}|$ → mover SL a break-even

**Para SELL (posición corta)**:
- SL: si $P_{actual} \geq P_{SL}$ → cierre con pérdida
- TP: si $P_{actual} \leq P_{TP}$ → cierre con ganancia
- Trailing: si $P_{actual} \leq P_{entry} - 1.5 \times |P_{entry} - P_{SL}|$ → mover SL a break-even

El **trailing stop** merece atención especial. El umbral de activación es $1.5\times$ la distancia de riesgo:

$$\text{trailing\_threshold}_{BUY} = P_{entry} + 1.5 \times |P_{entry} - P_{SL}|$$

Cuando el precio supera este umbral, el stop loss se mueve a break-even ($P_{SL} \leftarrow P_{entry}$). Esto transforma un trade con riesgo en un trade **sin riesgo de pérdida** — el peor escenario es salir en cero. Es una técnica clásica de gestión de posiciones que permite "dejar correr" las ganancias sin arriesgar el capital inicial.

---

## 6.6 El Main Loop

El corazón operativo del sistema reside en `scripts/run_trading.py`. Es un bucle infinito que orquesta los agentes en secuencia:

```python
SCAN_INTERVAL = 60                  # segundos entre ciclos
PORTFOLIO_SNAPSHOT_INTERVAL = 5     # snapshot cada N ciclos (~5 min)

def main():
    scanner   = MarketScanner()
    strategy  = StrategyEngine()
    executor  = ExecutionAgent()
    monitor   = TradeMonitor()
    portfolio = get_portfolio()
    cycle_count = 0

    while True:
        cycle_count += 1

        # 0. MONITOREAR TRADES ABIERTOS — cerrar SL/TP
        closed_trades = monitor.check_open_trades(portfolio)
        if closed_trades:
            for ct in closed_trades:
                logger.info(
                    f'Trade closed: {ct["asset"]} {ct["close_reason"]} '
                    f'PnL=${ct["pnl"]:+.2f} ({ct["pnl_pct"]:+.2f}%)'
                )
            portfolio = get_portfolio()  # Refresh tras cierres

        # 1. Scan mercados
        signals = scanner.scan()

        # 2-3-4. Evaluar estrategias → Ejecutar si aprobado
        for asset in ASSETS:
            for tf in TIMEFRAMES:
                result = strategy.evaluate(asset, tf, portfolio)
                if result.get('opportunity'):
                    signal = result['signal']
                    open_trades = get_open_trades()
                    exec_result = executor.execute(signal, portfolio, open_trades)
                    if exec_result.get('executed'):
                        logger.info(f'Executed trade: {exec_result["trade_id"]}')

        # Refresh portfolio
        portfolio = get_portfolio()

        # Snapshot periódico
        if cycle_count % PORTFOLIO_SNAPSHOT_INTERVAL == 0:
            save_portfolio_snapshot(portfolio)

        time.sleep(SCAN_INTERVAL)
```

### Decisiones de Diseño del Loop

**1. TradeMonitor se ejecuta PRIMERO.** Esta es la decisión más importante del loop. Si invertimos el orden (primero escanear y operar, luego monitorear), podemos abrir un nuevo trade en un activo que debería haberse cerrado por stop loss en este mismo ciclo. Ejecutar el monitor primero garantiza que el portfolio refleja la realidad *antes* de tomar nuevas decisiones.

**2. Ciclo de 60 segundos.** La constante `SCAN_INTERVAL = 60` define la resolución temporal mínima del sistema. Esto implica que la granularidad de las decisiones es de 1 minuto — suficiente para timeframes de 5m, 15m, 1h y 4h, pero no para scalping sub-minuto (que no es el objetivo de este sistema).

**3. Portfolio snapshot cada 5 ciclos.** Cada $5 \times 60 = 300$ segundos (5 minutos), se persiste una foto del portfolio en PostgreSQL. Esto alimenta las métricas históricas sin sobrecargar la base de datos con escrituras por segundo.

**4. Tolerancia a errores.** El `try/except` en el loop externo captura cualquier excepción no manejada y espera 10 segundos antes de reintentar. El sistema **nunca muere** por un error transitorio — un timeout de exchange, un dato corrupto, o un fallo de Redis se absorben silenciosamente con un log de error.

### Ciclo de Vida de un Trade Completo

Para consolidar, sigamos el ciclo de vida de un trade desde el dato crudo hasta el cierre:

```
Ciclo N:
  MarketFeed.refresh("BTC", "1h")     → 250 velas OHLCV en DB
  IndicatorEngine.calculate(df)        → IndicatorSet (EMA, RSI, BB, ATR, etc.)
  MarketScanner._detect_signals(ind)   → Signal: EMA_CROSS_BULL, strength=0.72
  redis.publish("signals:new", sig)    → Dashboard actualiza en tiempo real
  StrategyEngine.evaluate("BTC","1h")  → TrendMomentum score=0.85 (mejor de 3)
  ClaudeBridge.call("signal_interpretation") → PROCEED, confidence=62%
  redis.publish("strategies:opportunity")    → Dashboard muestra oportunidad
  RiskManager.evaluate(signal, portfolio)    → APPROVED (RR=1.67, risk_exposure=1.0%)
  ClaudeBridge.call("anomaly_check")         → No anomaly, confidence=45%
  ExecutionAgent._simulate_order()           → PAPER_a3f8c1e2
  DB: INSERT INTO trades (...)               → Trade persistido
  redis.publish("trades:executed")           → Dashboard actualiza posiciones

Ciclo N+47 (47 minutos después):
  TradeMonitor._evaluate_trade(trade)        → precio superó trailing threshold
  TradeMonitor._update_stop_loss(break_even) → SL movido a entry price

Ciclo N+128 (128 minutos después):
  TradeMonitor._evaluate_trade(trade)        → precio alcanzó take_profit
  TradeMonitor._close_trade(...)             → PnL calculado, status=CLOSED
  redis.publish("trades:closed")             → Dashboard cierra posición
  Portfolio recalculado con nueva balance
```

---

## 6.7 Resiliencia y Modos de Fallo

Cada agente está diseñado para **degradar elegantemente**, no para propagar failures:

| Componente que falla | Impacto | Mitigación |
|---|---|---|
| Exchange API (CCXT) | No se pueden obtener datos frescos | `MarketFeed` usa datos de DB como fallback; warning en log |
| Redis | No hay pub/sub ni cache de indicadores | Los agentes continúan usando DB directamente; dashboard sin real-time |
| PostgreSQL | No se pueden persistir trades ni señales | Error crítico → loop espera 10s y reintenta |
| LLM (OpenAI/Anthropic) | No hay validación de Claude | `_neutral_result()` → sistema opera sin IA (capítulo 7) |
| Un agente individual | El trade no se ejecuta en este ciclo | `try/except` per-asset → siguiente activo se procesa normalmente |

La única falla que **detiene** el trading es el halt del RiskManager por drawdown máximo (10%). Esto es intencional: es un circuit breaker que protege el capital cuando algo sistémico está mal.

---

## 6.8 Reflexiones Arquitectónicas

La arquitectura multi-agente con pipeline lineal y eventos Redis ofrece un balance pragmático entre la elegancia académica de los MAS puros y las restricciones de un sistema real que debe operar 24/7. No es un sistema distribuido (todos los agentes corren en el mismo proceso), pero está diseñado para serlo si fuera necesario — los canales Redis y la base de datos compartida permiten separar agentes en procesos o máquinas distintas sin cambiar la lógica de negocio.

La lección fundamental es que la **jerarquía de autoridad** no es un accidente: es el resultado de comprender que en trading, la gestión de riesgo es más importante que la identificación de oportunidades. Un sistema que encuentra todas las oportunidades pero gestiona mal el riesgo quiebra. Un sistema que gestiona el riesgo perfectamente pero encuentra pocas oportunidades sobrevive. El `RiskManager` con parámetros inmutables en código fuente es la expresión más pura de esta filosofía.

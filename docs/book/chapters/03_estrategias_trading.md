# Capítulo 3: Estrategias de Trading — Teoría y Modelado

> *"Una estrategia no es un indicador. Es un sistema de reglas que traduce indicadores en decisiones — con riesgo cuantificado."*

---

## 3.1 Introducción: Del Indicador a la Decisión

El capítulo anterior cubrió el **qué** — los indicadores que cuantifican el estado del mercado. Este capítulo cubre el **cómo** — las estrategias que interpretan esos indicadores para generar señales de trading accionables.

Nuestro agente implementa tres estrategias fundamentalmente diferentes, cada una basada en una teoría financiera distinta:

| Estrategia | Base Teórica | Pregunta que responde |
|---|---|---|
| Trend Momentum | Tendencia + momentum factor | "¿El mercado se está moviendo y va a seguir?" |
| Mean Reversion | Proceso Ornstein-Uhlenbeck | "¿El mercado se desvió demasiado y va a regresar?" |
| Breakout | Ruptura de resistencia/soporte | "¿El mercado está rompiendo un nivel clave con convicción?" |

Las tres estrategias son **complementarias, no competitivas**: en un mercado trending, la estrategia Trend Momentum produce scores altos; en un mercado lateral, Mean Reversion toma la delantera; en consolidaciones que estallan con volumen, Breakout captura la oportunidad. El `StrategyEngine` las evalúa simultáneamente y selecciona la de mayor score.

---

## 3.2 Sistema de Scoring: Diseño y Justificación

Antes de analizar cada estrategia, es fundamental entender el **sistema de scoring** que todas comparten.

### 3.2.1 Puntuación Aditiva

Cada estrategia asigna puntos por condiciones cumplidas:

$$Score_{total} = \sum_{i=1}^{n} w_i \cdot \mathbb{1}_{condition_i}$$

Donde $w_i$ es el peso (puntos) de la condición $i$ y $\mathbb{1}_{condition_i}$ es la función indicadora (1 si la condición se cumple, 0 si no).

Los pesos **no** son iguales: cada condición tiene un peso que refleja su importancia relativa. Por ejemplo, en Trend Momentum:
- EMA bull cross: +30 (condición estructural, peso alto)
- Precio sobre EMA20: +15 (confirmación, peso medio)
- RSI en zona de momentum: +25 (convicción, peso alto)
- Volumen confirmatorio: +15 (confirmación, peso medio)

### 3.2.2 Umbral Mínimo (MIN_SCORE)

Cada estrategia tiene un umbral mínimo que debe alcanzarse para generar una señal:

| Estrategia | MIN_SCORE | Justificación |
|---|---|---|
| Trend Momentum | 65 | Balance entre sensibilidad y precision |
| Mean Reversion | 70 | Más estricto: operar contra la tendencia requiere mayor convicción |
| Breakout | 75 | El más estricto: false breakouts son costosos |

Un score por debajo del umbral produce `direction: NEUTRAL` — el agente no opera.

### 3.2.3 ¿Por qué scoring y no reglas binarias?

Un sistema de reglas binarias ("si RSI < 30 Y precio < BB_lower → COMPRAR") tiene un problema fundamental: es **todo o nada**. No hay gradación entre "señal marginal" y "señal excepcional".

El scoring permite:
1. **Gradación**: una señal con score 90 es materialmente mejor que una con score 65.
2. **Comparación entre estrategias**: si Trend Momentum produce score 70 y Mean Reversion produce score 85, el sistema puede elegir la mejor.
3. **Calibración**: ajustar el `MIN_SCORE` permite controlar la agresividad del sistema sin rediseñar las reglas.
4. **Trazabilidad**: las `reasons` acompañan cada score, permitiendo entender exactamente por qué se generó (o no) una señal.

---

## 3.3 Estrategia 1: Trend Momentum

### 3.3.1 Base Académica: Trend Following y el Exponente de Hurst

La estrategia Trend Momentum se fundamenta en la observación empírica de que los precios financieros exhiben **persistencia**: una serie temporal que ha subido tiene mayor probabilidad de seguir subiendo (y viceversa) durante períodos significativos.

Esta propiedad se formaliza mediante el **exponente de Hurst** ($H$), introducido por Harold Edwin Hurst en 1951 para estudiar las crecidas del río Nilo y posteriormente aplicado a series financieras por Benoit Mandelbrot.

Para una serie temporal $X(t)$, el exponente de Hurst se obtiene del **rango reescalado** (R/S analysis):

$$E\left[\frac{R(n)}{S(n)}\right] = C \cdot n^H$$

Donde:
- $R(n)$ = rango del proceso acumulado sobre ventana de tamaño $n$
- $S(n)$ = desviación estándar de la serie sobre la misma ventana
- $C$ = constante

La interpretación:
- $H = 0.5$: camino aleatorio (random walk). Sin memoria. Ni trend following ni mean reversion funcionan.
- $H > 0.5$: **persistencia**. Las tendencias tienden a continuar. Trend following tiene ventaja estadística.
- $H < 0.5$: **anti-persistencia**. El proceso tiende a revertir. Mean reversion tiene ventaja.

Los estudios empíricos muestran que muchos activos crypto exhiben $H > 0.5$ en timeframes intermedios (horas a días), lo que justifica teóricamente la estrategia de trend momentum. BTC, en particular, ha mostrado $H$ entre 0.55-0.65 en análisis de largo plazo.

### 3.3.2 El Factor Momentum

Complementariamente, la investigación en finanzas cuantitativas ha documentado extensivamente el **momentum factor**: los activos que han tenido buen rendimiento en los últimos 3-12 meses tienden a seguir con buen rendimiento, y viceversa (Jegadeesh & Titman, 1993).

Nuestra estrategia captura momentum a escala intradía/swing, usando EMAs y RSI como proxies cuantitativos.

### 3.3.3 Análisis del Código

```python
class TrendMomentumStrategy:
    NAME = 'TREND_MOMENTUM'
    MIN_SCORE = 65

    def score(self, ind: IndicatorSet, df=None) -> dict:
        score = 0
        reasons = []
        direction = None
```

La firma es limpia: recibe un `IndicatorSet` inmutable y devuelve un diccionario con dirección, score, razones y niveles de SL/TP. El parámetro `df` es opcional y no se usa en esta estrategia (a diferencia de Breakout, que necesita el histórico para detectar resistencias).

**Condiciones SELL (evaluadas primero):**

```python
        if ind.ema20 < ind.ema50 * 0.995 and ind.rsi < 45:
            return {
                'direction': 'SELL',
                'score': 85,
                'reasons': ['EMA_BEAR_CROSS', f'RSI_WEAK:{ind.rsi:.1f}'],
                'stop_loss': ind.close + (1.5 * ind.atr),
                'take_profit': ind.close - (2.5 * ind.atr),
            }
```

La condición de venta requiere **doble confirmación**:
1. EMA(20) está más de 0.5% por debajo de EMA(50): la tendencia de corto plazo es claramente bajista respecto a la de mediano plazo.
2. RSI < 45: el momentum es débil, confirmando la presión vendedora.

Nótese que el score es fijo (85), no aditivo. La razón: las condiciones de SELL son estructurales — si se cumplen, el mercado está en tendencia bajista confirmada y la señal es consistentemente fuerte.

**Condiciones BUY (acumulativas):**

| Condición | Puntos | Razón | Fundamento |
|---|---|---|---|
| EMA20 > EMA50 × 1.005 | +30 | EMA_BULL_CROSS | Estructura alcista con buffer anti-ruido |
| Close > EMA20 | +15 | PRICE_ABOVE_EMA20 | Momentum activo (precio "empujando") |
| RSI ∈ [50, 68] | +25 | RSI_MOMENTUM_ZONE | Momentum confirmado sin sobreextensión |
| RSI > 68 | -20 | RSI_EXTENDED | Penalización por riesgo de pullback |
| Vol ratio > 1.2 | +15 | VOL_CONFIRM | Volumen confirma la convicción |
| Close < BB_upper × 0.98 | +15 | ROOM_TO_BB_UPPER | Hay espacio para subir antes de resistencia |

**Score máximo de BUY: 30 + 15 + 25 + 15 + 15 = 100.**

### 3.3.4 El Umbral del 0.5% en EMA Cross

```python
if ind.ema20 > ind.ema50 * 1.005:
```

¿Por qué no simplemente `ema20 > ema50`? Porque en mercados laterales, las EMAs se cruzan constantemente. El buffer de 0.5% actúa como **filtro de ruido** (noise filter): solo considera el cruce como significativo cuando la EMA corta está al menos 0.5% por encima de la larga.

Matemáticamente, esto equivale a exigir:

$$\frac{EMA_{20} - EMA_{50}}{EMA_{50}} > 0.005$$

Es un umbral empírico calibrado para evitar cruces falsos sin perder cruces genuinos. En crypto, con volatilidades diarias de 2-5%, un 0.5% es lo suficientemente pequeño como para no filtrar tendencias reales.

### 3.3.5 La Zona RSI 50-68: Momentum sin Sobreextensión

La zona RSI [50, 68] es deliberadamente asimétrica respecto al punto medio (50) y al umbral clásico de sobrecompra (70):

- **RSI < 50**: el momentum es bajista o neutral — no queremos comprar en contra del momentum.
- **RSI ∈ [50, 68]**: el momentum es alcista y tiene recorrido. El activo está "empujando" pero no está agotado.
- **RSI > 68**: penalización. El momentum existe pero está sobreextendido. Comprar aquí aumenta la probabilidad de un pullback inmediato que active el stop loss.

El corte en 68 (no en 70) es conservador: preferimos perder una oportunidad marginal que entrar en un pullback probable.

### 3.3.6 Risk:Reward = 1.67

```python
'stop_loss': ind.close - (1.5 * ind.atr),
'take_profit': ind.close + (2.5 * ind.atr),
```

$$R:R = \frac{TP - Entry}{Entry - SL} = \frac{2.5 \times ATR}{1.5 \times ATR} = \frac{2.5}{1.5} \approx 1.67$$

La expectancia matemática de este trade, asumiendo un win rate $p$:

$$E[trade] = p \times 2.5 \cdot ATR - (1-p) \times 1.5 \cdot ATR$$

Para que el trade sea rentable en expectativa:

$$E > 0 \Rightarrow p > \frac{1.5}{1.5 + 2.5} = 0.375$$

Solo necesitamos un win rate superior al **37.5%** para ser rentables. Esto es un margen de seguridad generoso, dado que la combinación de EMA + RSI + volumen históricamente produce win rates de 45-60%.

---

## 3.4 Estrategia 2: Mean Reversion

### 3.4.1 Base Académica: El Proceso Ornstein-Uhlenbeck

La mean reversion (reversión a la media) se fundamenta en procesos estocásticos que exhiben **estacionariedad**: fluctúan alrededor de un nivel de equilibrio $\mu$ al que tienden a regresar después de desviaciones.

El modelo canónico es el **proceso Ornstein-Uhlenbeck** (O-U), descrito por la ecuación diferencial estocástica:

$$dX_t = \theta(\mu - X_t) \, dt + \sigma \, dW_t$$

Donde:
- $X_t$ = precio (o log-precio) en el tiempo $t$
- $\mu$ = nivel de equilibrio al que tiende el proceso (la "media")
- $\theta > 0$ = velocidad de reversión. Mayor $\theta$ = reversión más rápida
- $\sigma$ = volatilidad del proceso
- $dW_t$ = incremento de un proceso de Wiener (ruido browniano)

**Interpretación**: cuando $X_t > \mu$, el término $\theta(\mu - X_t)$ es negativo, "empujando" el precio hacia abajo, de vuelta a $\mu$. Viceversa cuando $X_t < \mu$. El proceso oscila alrededor de $\mu$ con amplitud proporcional a $\sigma/\sqrt{2\theta}$.

La **vida media** (half-life) de la reversión es:

$$t_{1/2} = \frac{\ln 2}{\theta}$$

Esto indica cuánto tiempo tarda, en promedio, una desviación en reducirse a la mitad. Para activos con una vida media corta, la estrategia de mean reversion es más atractiva.

### 3.4.2 ¿Cuándo esperar Mean Reversion?

No todos los activos ni todos los timeframes exhiben mean reversion. Las condiciones favorables son:

1. **Mercado lateral (ranging)**: las EMAs están relativamente planas y cercanas entre sí.
2. **Volatilidad controlada (bb_width bajo)**: las desviaciones son contenidas — no es un crash.
3. **Extremo estadístico**: el precio está en un percentil bajo de su distribución reciente (bb_pct < 0.05).
4. **Ausencia de tendencia bajista estructural**: una corrección en un bull market revierte; un crash no.

### 3.4.3 Activos Preferidos

```python
PREFERRED_ASSETS = ['XAU', 'XAG', 'ETH']
```

¿Por qué estos tres? Porque empíricamente exhiben **mayor tendencia a la reversión**:

**Oro (XAU)**: los metales preciosos son clásicos mean-reverters. El oro tiene un valor "fundamental" anclado a su rol como reserva de valor, inflación esperada y tasas de interés reales. Las desviaciones del fair value tienden a corregirse en escalas de semanas. Su exponente de Hurst históricamente oscila entre 0.42-0.50.

**Plata (XAG)**: aún más volátil que el oro, pero con una fuerte tendencia a revertir al ratio histórico XAU/XAG. La plata tiene un componente industrial (a diferencia del oro, que es casi puramente monetario) que genera ciclos predecibles.

**Ethereum (ETH)**: aunque es crypto, ETH muestra una dualidad interesante. En timeframes largos sigue la tendencia general del mercado crypto (trending), pero en timeframes cortos muestra reversión, especialmente cuando diverge de BTC temporalmente. Su correlación con BTC ($\rho \approx 0.85$) genera oportunidades cuando la relación se estira.

### 3.4.4 Análisis del Código

```python
class MeanReversionStrategy:
    NAME = 'MEAN_REVERSION'
    MIN_SCORE = 70
    PREFERRED_ASSETS = ['XAU', 'XAG', 'ETH']
```

El `MIN_SCORE` de 70 (superior al 65 de Trend Momentum) refleja que operar contra la tendencia requiere **mayor convicción**. Comprar un activo que cae es inherentemente más riesgoso que comprar uno que sube.

**Sistema de scoring:**

| Condición | Puntos | Razón | Fundamento |
|---|---|---|---|
| bb_pct < 0.05 | +35 | BB_LOWER_EXTREME | Precio en el extremo inferior de la distribución |
| bb_pct < 0.10 | +20 | BB_LOWER_ZONE | Precio bajo pero no extremo |
| RSI < 25 | +30 | RSI_EXTREME_OVERSOLD | Momentum bajista agotado |
| RSI < 32 | +20 | RSI_OVERSOLD | Sobreventa moderada |
| EMA drop > 5% | -40 | STRONG_DOWNTREND_ABORT | **Protección anti-cuchillo cayente** |
| bb_width < 0.10 | +15 | LOW_VOLATILITY_FAVORABLE | Entorno contenido para reversión |
| bb_width > 0.20 | -15 | HIGH_VOLATILITY_RISK | Demasiada dispersión |
| Asset preferido | +10 | PREFERRED_ASSET | Bonus por tendencia histórica a revertir |
| R:R < 1.5 | -20 | LOW_RR | Insuficiente reward para el riesgo |

**Score máximo: 35 + 30 + 15 + 10 = 90** (con asset preferido y volatilidad baja, sin penalizaciones).

### 3.4.5 El Mecanismo STRONG_DOWNTREND_ABORT

```python
ema_drop_pct = (ind.ema50 - ind.ema20) / ind.ema50 if ind.ema50 > 0 else 0
if ema_drop_pct > 0.05:
    score -= 40
    reasons.append('STRONG_DOWNTREND_ABORT')
```

Esta es quizás la regla más importante de toda la estrategia. Calcula cuánto ha caído EMA(20) respecto a EMA(50) en términos porcentuales. Si la caída supera el 5%, aplica una penalización de -40 puntos que efectivamente **aborta** la señal.

**¿Por qué?** Porque la diferencia entre "sobreventa que revierte" y "cuchillo cayente" (falling knife) es precisamente la estructura de la tendencia. En una corrección saludable dentro de una tendencia alcista, las EMAs estarán relativamente juntas. En un crash, EMA(20) colapsa muy por debajo de EMA(50), creando una divergencia > 5%.

La metáfora del cuchillo cayente es apta: intentar atrapar un activo en caída libre es extremadamente peligroso. Esta regla existe para proteger al sistema de la tentación de "comprar barato" cuando el mercado está en modo de pánico.

### 3.4.6 Target: Reversión a la Media (BB Middle)

```python
target = ind.bb_middle
reward = target - ind.close
risk = 1.5 * ind.atr
rr_ratio = reward / risk if risk > 0 else 0
```

A diferencia de Trend Momentum (que espera que la tendencia continúe indefinidamente), Mean Reversion tiene un **target definido**: la banda media de Bollinger ($SMA(20)$), que representa la media estadística del precio reciente.

El Risk:Reward se calcula dinámicamente:

$$R:R = \frac{BB_{middle} - P_{close}}{1.5 \times ATR}$$

Si el precio está lejos de la media pero la volatilidad es baja (ATR pequeño), el R:R es alto — exactamente el escenario óptimo para mean reversion. Si el R:R es menor a 1.5, se aplica una penalización de -20 puntos. La lógica: no vale la pena arriesgar 1.5 ATR para ganar menos de 2.25 ATR.

---

## 3.5 Estrategia 3: Breakout

### 3.5.1 Base Académica: Resistencias, Soportes y Zonas de Oferta-Demanda

La estrategia de breakout se basa en la observación de que los precios tienden a moverse en **rangos** definidos por niveles de soporte (pisos) y resistencia (techos), hasta que una fuerza suficiente rompe uno de esos niveles.

**Soporte**: un nivel de precio donde la demanda ha sido históricamente suficiente para detener caídas. Matemáticamente, es un mínimo local recurrente en la serie de precios.

**Resistencia**: un nivel donde la oferta ha detenido alzas. Un máximo local recurrente.

Desde la perspectiva de microestructura, los niveles de soporte/resistencia se forman porque:
1. **Órdenes límite acumuladas**: los traders colocan órdenes de compra en soportes y de venta en resistencias.
2. **Memoria del mercado**: los participantes recuerdan niveles donde compraron (soporte psicológico) o donde perdieron (resistencia como "punto de dolor").
3. **Números redondos**: $60,000, $50,000 actúan como imanes de liquidez.

Un **breakout** ocurre cuando el precio penetra un nivel de resistencia con suficiente fuerza (volumen) como para que las órdenes acumuladas en ese nivel sean absorbidas. Una vez rota la resistencia, esta se convierte en nuevo soporte (principio de polaridad).

### 3.5.2 Volumen: La Condición No Negociable

```python
if ind.vol_ratio < 2.0:
    return {
        'direction': 'NEUTRAL',
        'score': 0,
        'reasons': ['INSUFFICIENT_VOLUME'],
    }
```

Esta es la línea de código más importante de toda la estrategia Breakout. Es un **hard gate**: si el volumen no es al menos 2× su promedio de 20 velas, la estrategia retorna inmediatamente con score 0, sin importar nada más.

**¿Por qué?** Porque un breakout sin volumen es, estadísticamente, un **false breakout** (fakeout). Los false breakouts son trampas donde el precio penetra brevemente un nivel, activa stops de los vendedores, y luego revierte violentamente. Operarlos consistentemente destruye capital.

La evidencia empírica es contundente:
- Breakouts con volumen < 1.5× promedio tienen una tasa de éxito de ~30%.
- Breakouts con volumen ≥ 2× promedio tienen una tasa de éxito de ~55-65%.

El umbral de 2.0× es conservador pero seguro. Filtra la mayoría de los fakeouts a costa de perder algunos breakouts legítimos de bajo volumen.

### 3.5.3 Activos Preferidos

```python
PREFERRED_ASSETS = ['BTC', 'ETH']
```

BTC y ETH son los activos preferidos para breakout porque:
1. **Liquidez**: su profundidad de mercado es la mayor en crypto, lo que significa que los breakouts con alta liquidez tienden a ser más significativos.
2. **Momentum post-breakout**: históricamente, BTC y ETH generan movimientos sostenidos después de romper resistencias (atribuible a $H > 0.5$).
3. **Atención del mercado**: las rupturas en BTC y ETH atraen atención mediática y flujos de capital adicionales, creando un loop de feedback positivo.

### 3.5.4 Análisis del Código

```python
class BreakoutStrategy:
    NAME = 'BREAKOUT'
    MIN_SCORE = 75
    PREFERRED_ASSETS = ['BTC', 'ETH']
    LOOKBACK_CANDLES = 20
```

`MIN_SCORE = 75` es el más alto de las tres estrategias. Esto refleja la naturaleza de alto riesgo de los breakouts: los false breakouts son frecuentes y costosos, así que la barra de evidencia requerida es máxima.

`LOOKBACK_CANDLES = 20` define la ventana para detectar el máximo reciente que actúa como resistencia.

**Sistema de scoring (post-filtro de volumen):**

| Condición | Puntos | Razón | Fundamento |
|---|---|---|---|
| Vol ratio ≥ 2.0 | +30 | STRONG_VOLUME | Pre-filtrado + puntuación base |
| Close > high(20) × 1.005 | +40 | RESISTANCE_BREAK | Ruptura confirmada con buffer 0.5% |
| Sin ruptura de resistencia | -10 | NO_RESISTANCE_BREAK | Volumen alto sin breakout real |
| ATR% > 1.5% | +15 | SUFFICIENT_ATR | Movimiento significativo |
| Trend_direction == UP | +15 | TREND_ALIGNED | Breakout en dirección de la tendencia |
| Asset preferido | +10 | — | Bonus intrínseco |

**Score máximo: 30 + 40 + 15 + 15 + 10 = 110.**

### 3.5.5 Detección de Resistencia con Lookback

```python
if df is not None and len(df) >= self.LOOKBACK_CANDLES:
    recent_high = df['high'].rolling(self.LOOKBACK_CANDLES).max().iloc[-2]
    if ind.close > recent_high * 1.005:
        score += 40
        reasons.append(f'RESISTANCE_BREAK:{recent_high:.2f}')
```

Puntos clave:
- **`rolling(20).max().iloc[-2]`**: el máximo de las últimas 21 velas, excluyendo la vela actual (`iloc[-2]` obtiene el penúltimo valor). Esto evita que la vela actual, que es la candidata a breakout, se incluya en el cálculo de la resistencia.
- **Buffer de 0.5%** (`* 1.005`): el precio debe superar el máximo previo en al menos 0.5%. Esto filtra penetraciones marginales que podrían ser ruido.

### 3.5.6 SL y TP: Stop Ajustado, Target Ambicioso

```python
stop = ind.close - (1.0 * ind.atr)  # SL: 1.0 ATR
target = ind.close + (3.0 * ind.atr)  # TP: 3.0 ATR
```

$$R:R = \frac{3.0 \times ATR}{1.0 \times ATR} = 3.0$$

El Risk:Reward de 3:1 es el más alto de las tres estrategias. La justificación dual:

**Stop Loss ajustado (1.0 ATR)**: en breakouts, la hipótesis es binaria — o el breakout es real y el precio continúa, o es falso y revierte rápidamente. No hay punto intermedio. Un SL amplio solo agrandaría la pérdida en un false breakout sin agregar valor. Cortamos rápido.

**Take Profit ambicioso (3.0 ATR)**: los breakouts genuinos tienden a generar movimientos extendidos porque:
1. Los stops de posiciones contrarias se activan en cascada, alimentando el movimiento.
2. Los traders que esperaban el breakout entran, agregando presión.
3. La atención mediática atrae capital fresco.

La expectancia con win rate $p$:

$$E = p \times 3.0 \cdot ATR - (1-p) \times 1.0 \cdot ATR$$

Rentable cuando:

$$p > \frac{1.0}{1.0 + 3.0} = 0.25$$

Solo se necesita un **25% de win rate** para ser rentable. Este es el poder del R:R asimétrico: podés equivocarte 3 de cada 4 veces y aún ganar dinero.

---

## 3.6 Comparativa de las Tres Estrategias

| Dimensión | Trend Momentum | Mean Reversion | Breakout |
|---|---|---|---|
| Tipo de mercado ideal | Trending | Lateral/ranging | Consolidación → explosión |
| MIN_SCORE | 65 | 70 | 75 |
| Condición primaria | EMA alignment | bb_pct extremo + RSI | Volumen ≥ 2× (hard gate) |
| Stop Loss | 1.5 ATR | 1.5 ATR | 1.0 ATR |
| Take Profit | 2.5 ATR | bb_middle (dinámico) | 3.0 ATR |
| Risk:Reward | 1.67 | Variable (≥ 1.5) | 3.0 |
| Win rate mínimo rentable | 37.5% | 40% | 25% |
| Activos preferidos | Todos | XAU, XAG, ETH | BTC, ETH |
| Protección especial | RSI overextension penalty | STRONG_DOWNTREND_ABORT | Volume hard gate |
| Exponente de Hurst favorable | $H > 0.5$ | $H < 0.5$ | $H > 0.5$ (post-break) |
| Direcciones | BUY + SELL | Solo BUY | Solo BUY |

---

## 3.7 La Orquesta de Estrategias: `StrategyEngine`

### 3.7.1 Arquitectura

El `StrategyEngine` es el director de orquesta que coordina las tres estrategias. Su flujo es:

```
get_latest(asset, timeframe) → DataFrame
    │
    ▼
IndicatorEngine.calculate(df) → IndicatorSet
    │
    ▼
┌─── TrendMomentumStrategy.score(ind) ──► {direction, score, reasons, SL, TP}
│
├─── MeanReversionStrategy.score(ind) ──► {direction, score, reasons, SL, TP}
│
└─── BreakoutStrategy.score(ind, df) ───► {direction, score, reasons, SL, TP}
    │
    ▼ Filtrar: solo results con direction ≠ NEUTRAL
    │
    ▼ Seleccionar: max(score)
    │
    ▼
Claude.call(task_type='signal_interpretation')
    │
    ▼
¿Claude ABORT con confianza ≥ 80%?
    │
    ├─ SÍ → return {opportunity: False, reason: 'claude_abort'}
    │
    └─ NO → return {opportunity: True, signal: best}
```

### 3.7.2 Evaluación Simultánea

```python
results = []
for strategy in self.strategies:
    try:
        if strategy.NAME == 'BREAKOUT':
            res = strategy.score(ind, df)
        else:
            res = strategy.score(ind)
        if res['direction'] != 'NEUTRAL':
            res['strategy'] = strategy.NAME
            results.append(res)
    except Exception as e:
        logger.error(f'Strategy {strategy.NAME} error: {e}')
```

Nótese:
- **`BREAKOUT` recibe `df` extra**: necesita el DataFrame histórico para detectar resistencias (las otras estrategias solo usan `IndicatorSet`).
- **Solo señales no-NEUTRAL**: las estrategias que no encuentran oportunidad devuelven `NEUTRAL` y son filtradas.
- **Manejo de errores por estrategia**: si una estrategia falla, las demás continúan. El sistema es resiliente a errores parciales.

### 3.7.3 Selección del Mejor Score

```python
best = max(results, key=lambda r: r['score'])
```

El criterio de selección es simple y transparente: **gana la estrategia con mayor score**. Esto permite que el mercado "elija" la estrategia: en un mercado trending con volumen moderado, Trend Momentum tendrá el mejor score; si hay un breakout con volumen 3×, BreakoutStrategy ganará con score potencialmente > 100.

### 3.7.4 Claude como Verificador de Consistencia

El rol de Claude (o el LLM configurado) no es **tomar** la decisión de trading — es **verificar** que la decisión algorítmica sea consistente. La llamada:

```python
claude_check = self.claude.call(
    task_type='signal_interpretation',
    asset=asset,
    data={
        'signals': results,         # Todas las señales evaluadas
        'best_signal': best,        # La señal seleccionada
        'indicators': {...},        # Valores de indicadores clave
        'timeframe': timeframe,
    },
    portfolio_context=portfolio_context or {},
)
```

Claude recibe:
1. **Todas** las señales (no solo la mejor): puede verificar si hay conflicto entre estrategias.
2. **Indicadores clave**: puede verificar coherencia (e.g., "¿un BUY con RSI 72 tiene sentido?").
3. **Contexto de portafolio**: puede considerar exposición actual, correlación, etc.

### 3.7.5 El Mecanismo ABORT

```python
if (claude_check.get('recommendation') == 'ABORT'
        and claude_check.get('confidence', 0) >= 80):
    return {
        'opportunity': False,
        'reason': 'claude_abort',
        'claude_analysis': claude_check,
    }
```

Claude puede recomendar abortar un trade, pero solo si su confianza es ≥ 80%. Esto establece una **jerarquía de autoridad**:

1. **Las estrategias algorítmicas** generan la señal.
2. **Claude** puede vetarla, pero solo con alto nivel de confianza.
3. **El RiskManager** (no cubierto en este capítulo) tiene el veto final absoluto.

**¿Por qué el umbral de 80%?**

- Con 50%, Claude abortaría aproximadamente la mitad de las señales, esencialmente anulando el sistema algorítmico.
- Con 95%, Claude casi nunca abortaría, haciendo la verificación inútil.
- 80% es un punto de equilibrio donde Claude solo interviene cuando detecta inconsistencias claras: una señal de compra en un activo que acaba de sufrir un evento fundamental negativo, una incoherencia entre múltiples timeframes, o un conflicto directo entre indicadores que el scoring no captura.

### 3.7.6 Filosofía: IA Asistida, No Dominante

Un principio de diseño fundamental del sistema es que la IA (Claude) es **asistente, no líder**. Las razones:

1. **Determinismo**: los algoritmos son determinísticos. Dado el mismo `IndicatorSet`, siempre producen el mismo score. Los LLMs son estocásticos por naturaleza (temperature > 0), y su output puede variar entre invocaciones idénticas.

2. **Auditabilidad**: un score algorítmico de 75 con razones `[EMA_BULL_CROSS, RSI_MOMENTUM_ZONE, VOL_CONFIRM]` es completamente trazable. Una decisión de Claude es una caja negra.

3. **Costo**: la evaluación algorítmica es gratuita y toma milisegundos. Cada call a Claude tiene un costo monetario y una latencia de 1-3 segundos.

4. **Fiabilidad**: los LLMs pueden alucinar, malinterpretar datos numéricos, o generar razonamiento circular. Usarlos para **verificar** es seguro; usarlos para **decidir** es arriesgado en un contexto financiero.

---

## 3.8 Caso Integrador: BTC con Señal de Trend Momentum

Para concretizar el flujo completo, simulemos un escenario:

**Estado del mercado (BTC, 15m):**
- Close: $62,350
- EMA(20): $62,100 | EMA(50): $61,500 | EMA(200): $58,900
- RSI: 58.3
- BB: upper $63,200, middle $61,800, lower $60,400
- ATR: $450 (atr_pct: 0.72%)
- Vol ratio: 1.35
- Trend: UP, strength: 0.27

**Evaluación TrendMomentumStrategy:**
1. ✅ EMA20 ($62,100) > EMA50 × 1.005 ($61,807): **+30** (EMA_BULL_CROSS)
2. ✅ Close ($62,350) > EMA20 ($62,100): **+15** (PRICE_ABOVE_EMA20)
3. ✅ RSI (58.3) ∈ [50, 68]: **+25** (RSI_MOMENTUM_ZONE)
4. ✅ Vol ratio (1.35) > 1.2: **+15** (VOL_CONFIRM)
5. ✅ Close ($62,350) < BB_upper × 0.98 ($61,936)... $62,350 > $61,936 → ❌
   
Score: 30 + 15 + 25 + 15 = **85** → ≥ MIN_SCORE (65) ✅

**Signal generada:**
```python
{
    'direction': 'BUY',
    'score': 85,
    'strategy': 'TREND_MOMENTUM',
    'reasons': ['EMA_BULL_CROSS', 'PRICE_ABOVE_EMA20', 
                'RSI_MOMENTUM_ZONE:58.3', 'VOL_CONFIRM:1.35x'],
    'stop_loss': 62350 - (1.5 × 450) = $61,675,
    'take_profit': 62350 + (2.5 × 450) = $63,475,
}
```

**MeanReversion:** bb_pct ≈ 0.70 (no está en extremo) → score bajo → NEUTRAL.
**Breakout:** vol_ratio 1.35 < 2.0 → INSUFFICIENT_VOLUME → NEUTRAL inmediato.

**Resultado:** solo TrendMomentum genera señal. Claude la verifica. Si no aborta → se envía como oportunidad.

---

## 3.9 Extensibilidad: Añadiendo Nuevas Estrategias

El diseño modular del sistema permite agregar nuevas estrategias sin modificar las existentes. Una nueva estrategia solo necesita:

1. Implementar un método `score(self, ind: IndicatorSet, df=None) -> dict`.
2. Definir `NAME` y `MIN_SCORE`.
3. Retornar un dict con `direction`, `score`, `reasons`, `stop_loss`, `take_profit`.
4. Ser registrada en la lista `self.strategies` del `StrategyEngine`.

Potenciales estrategias futuras:
- **Statistical Arbitrage**: operar la correlación BTC/ETH cuando diverge (pairs trading).
- **Volatility Expansion**: comprar opciones implícitas cuando bb_width está en mínimos históricos.
- **Intermarket**: operar la correlación inversa entre BTC y DXY (índice del dólar).

Cada una de estas encajaría naturalmente en la arquitectura existente, evaluándose en paralelo con las tres estrategias actuales y compitiendo por el mayor score.

---

## 3.10 Resumen del Capítulo

Las tres estrategias del sistema cubren los tres regímenes fundamentales de mercado:

- **Trend Momentum** captura movimientos persistentes ($H > 0.5$) verificando alineación de EMAs, momentum en zona óptima (RSI 50-68) y confirmación de volumen. R:R de 1.67.

- **Mean Reversion** explota excursiones extremas al nivel Ornstein-Uhlenbeck, comprando en la banda inferior de Bollinger con RSI en sobreventa, protegida por el mecanismo STRONG_DOWNTREND_ABORT contra cuchillos cayentes. Target: banda media.

- **Breakout** requiere volumen ≥ 2× como condición no negociable, buscando rupturas de resistencia de 20 velas con R:R de 3:1. El stop ajustado (1.0 ATR) refleja la naturaleza binaria del breakout.

El **StrategyEngine** orquesta las tres, selecciona la de mayor score, y somete la decisión a verificación por Claude — que puede abortar con ≥ 80% de confianza, pero nunca originar una señal por sí mismo. El resultado es un sistema donde cada capa (indicadores → estrategias → IA → risk management) agrega valor sin dominar la decisión.

# Capítulo 2: Análisis Técnico — Fundamento Matemático

> *"Los indicadores no predicen el futuro; cuantifican el presente."*

---

## 2.1 Introducción: ¿Qué es el Análisis Técnico?

El análisis técnico es el estudio de la acción del precio y el volumen para identificar patrones estadísticos que sugieren la dirección futura del mercado. A diferencia del análisis fundamental (que valora un activo por sus flujos de caja, utilidad o escasez), el análisis técnico opera bajo tres axiomas:

1. **El precio lo descuenta todo**: toda información pública y privada está reflejada en el precio.
2. **Los precios se mueven en tendencias**: una vez establecida, una tendencia tiene mayor probabilidad de continuar que de revertirse.
3. **La historia se repite**: los patrones de comportamiento humano (miedo, codicia, euforia) generan patrones de precio recurrentes.

Nuestro agente no utiliza patrones visuales (hombro-cabeza-hombro, triángulos) porque son subjetivos y difíciles de codificar con precisión. En cambio, usa **indicadores cuantitativos**: transformaciones matemáticas de la serie de precios que producen valores numéricos interpretables programáticamente.

El módulo `indicators.py` calcula **23 métricas** encapsuladas en un dataclass inmutable (`IndicatorSet`). En este capítulo derivaremos matemáticamente cada indicador, analizaremos su implementación y discutiremos sus fortalezas y debilidades.

---

## 2.2 EMA — Media Móvil Exponencial

### 2.2.1 Derivación Matemática

La **Media Móvil Simple** (SMA) de periodo $N$ es el promedio aritmético de los últimos $N$ precios:

$$SMA_t = \frac{1}{N} \sum_{i=0}^{N-1} P_{t-i}$$

El problema de la SMA es que asigna **peso igual** a todas las observaciones. El precio de hace 200 períodos contribuye tanto como el precio actual — una propiedad indeseable cuando queremos capturar tendencias recientes.

La **Media Móvil Exponencial** (EMA) resuelve esto con un **decay exponencial**:

$$EMA_t = \alpha \cdot P_t + (1 - \alpha) \cdot EMA_{t-1}$$

Donde el factor de suavizado $\alpha$ se define como:

$$\alpha = \frac{2}{N + 1}$$

Expandiendo recursivamente:

$$EMA_t = \alpha \sum_{k=0}^{\infty} (1-\alpha)^k \cdot P_{t-k}$$

Cada precio pasado se multiplica por $(1-\alpha)^k$, un peso que decae exponencialmente con la antigüedad $k$. Para una EMA(20), $\alpha = 2/21 \approx 0.095$, lo que significa que el precio actual recibe ~9.5% del peso, y los precios más antiguos contribuyen cada vez menos.

### 2.2.2 Las Tres EMAs del Sistema

El agente calcula tres EMAs con horizontes distintos:

| EMA    | Periodo | $\alpha$  | Interpretación                          |
|--------|---------|-----------|------------------------------------------|
| EMA(20)  | 20    | 0.0952    | Tendencia de corto plazo (~1 semana)    |
| EMA(50)  | 50    | 0.0392    | Tendencia de mediano plazo (~2.5 semanas) |
| EMA(200) | 200   | 0.00995   | Tendencia de largo plazo (~10 semanas)  |

La **relación entre EMAs** es más informativa que cada EMA individual:
- **EMA(20) > EMA(50)**: momentum alcista de corto plazo.
- **EMA(50) > EMA(200)**: tendencia alcista estructural ("golden cross" si cruza ascendentemente).
- **EMA(20) < EMA(50)**: momentum bajista.

### 2.2.3 Implementación

```python
# En indicators.py
ema20 = ta.trend.ema_indicator(c, window=20).iloc[-1]
ema50 = ta.trend.ema_indicator(c, window=50).iloc[-1]
ema200 = (
    ta.trend.ema_indicator(c, window=200).iloc[-1]
    if len(df) >= 200
    else ema50  # fallback si no hay datos suficientes
)
```

Nota el manejo del caso donde no hay 200 velas disponibles: se usa EMA(50) como proxy. Esto es pragmático — un activo recién añadido al sistema puede no tener suficiente historia, pero no debe bloquear el cálculo de los demás indicadores.

### 2.2.4 Fortalezas y Debilidades

**Fortalezas:**
- Reacciona más rápido que la SMA a cambios de precio.
- El parámetro $N$ es intuitivo: mayor $N$ = mayor suavizado.
- Eficiente computacionalmente: $O(1)$ por actualización (solo requiere el EMA anterior).

**Debilidades:**
- **Lag inherente**: toda media móvil es un indicador *retrasado* (lagging). Confirma tendencias, no las predice.
- **Falsos cruces**: en mercados laterales (sideways), las EMAs se cruzan frecuentemente generando señales falsas. El agente mitiga esto con un umbral del 0.5% en el cruce (`ema20 > ema50 * 1.005`).

---

## 2.3 RSI — Índice de Fuerza Relativa (Método de Wilder)

### 2.3.1 Derivación Matemática

El RSI fue desarrollado por J. Welles Wilder Jr. y publicado en 1978 en *"New Concepts in Technical Trading Systems"*. Es un oscilador acotado en $[0, 100]$ que mide la velocidad y magnitud de los cambios de precio.

**Paso 1: Calcular cambios de precio**

$$\Delta P_t = P_t - P_{t-1}$$

**Paso 2: Separar ganancias y pérdidas**

$$Gain_t = \max(\Delta P_t, 0), \quad Loss_t = \max(-\Delta P_t, 0)$$

**Paso 3: Promedios suavizados (método de Wilder)**

La ganancia y pérdida promedio se calculan con el **suavizado de Wilder**, que es una EMA con $\alpha = 1/N$:

$$\overline{Gain}_t = \frac{(N-1) \cdot \overline{Gain}_{t-1} + Gain_t}{N}$$

$$\overline{Loss}_t = \frac{(N-1) \cdot \overline{Loss}_{t-1} + Loss_t}{N}$$

Para la primera observación, se usa el promedio simple de los primeros $N$ períodos.

**Paso 4: Fuerza Relativa**

$$RS = \frac{\overline{Gain}}{\overline{Loss}}$$

**Paso 5: RSI**

$$RSI = 100 - \frac{100}{1 + RS}$$

### 2.3.2 Interpretación Profunda

El RSI no mide si un activo está "caro" o "barato" — mide la **proporción de movimientos alcistas vs bajistas** en los últimos $N$ períodos. Un RSI de 70 significa que, ponderando por magnitud, el 70% de la acción de precio reciente fue alcista.

**Zonas del sistema:**

| RSI        | Zona                | Interpretación del agente                    |
|------------|---------------------|----------------------------------------------|
| < 25       | Sobreventa extrema  | Señal fuerte para Mean Reversion (compra)    |
| 25 - 30    | Sobreventa          | Señal moderada para Mean Reversion           |
| 30 - 50    | Zona neutra baja    | Sin señal clara                              |
| 50 - 68    | Zona de momentum    | Ideal para Trend Momentum (compra)           |
| > 68       | Sobrecompra         | Penalización en Trend Momentum (overextended)|
| > 70       | Sobrecompra clásica | Potencial reversión bajista                  |

**¿Por qué periodo 14?** Wilder eligió 14 porque representaba aproximadamente la mitad de un ciclo lunar (28 días), que él asociaba con ciclos de mercado. Más pragmáticamente, 14 períodos cubren ~3 semanas de trading en mercados tradicionales (5 días/semana), ofreciendo un balance entre sensibilidad y estabilidad.

### 2.3.3 Wilder vs Promedio Simple

Muchas implementaciones de RSI usan un promedio simple en lugar del suavizado de Wilder. La diferencia es sutil pero matemáticamente relevante:

- **Promedio simple**: $\overline{Gain}_t = \frac{1}{N}\sum_{i=1}^{N} Gain_{t-i}$
- **Wilder**: aplica decay exponencial con $\alpha = 1/N$

El suavizado de Wilder produce un RSI más estable que reacciona menos violentamente a outliers individuales. La librería `ta` implementa ambos; nuestro código usa el default que corresponde al método de Wilder.

### 2.3.4 Implementación

```python
rsi = ta.momentum.rsi(c, window=14).iloc[-1]
```

Una línea de código que encapsula una cantidad considerable de matemática. La brevedad es intencional: la librería `ta` está validada contra implementaciones de referencia.

### 2.3.5 Fortalezas y Debilidades

**Fortalezas:**
- Acotado $[0, 100]$: permite comparaciones directas entre activos.
- Identifica eficientemente condiciones extremas (oversold/overbought).
- El suavizado de Wilder reduce señales falsas.

**Debilidades:**
- **Falsos positivos en tendencias fuertes**: en un bull market sostenido, el RSI puede permanecer >70 durante semanas sin que haya reversión. El agente mitiga esto verificando tendencia (EMA alignment) además del RSI.
- **Divergencias**: un RSI descendente con precio ascendente indica debilitamiento del momentum. El sistema actual no implementa detección de divergencias (es un área de mejora futura).

---

## 2.4 MACD — Convergencia/Divergencia de Medias Móviles

### 2.4.1 Derivación Matemática

Gerald Appel desarrolló el MACD en los años 1970. Es un indicador de momentum basado en la diferencia entre dos EMAs:

**Línea MACD:**

$$MACD_t = EMA(12)_t - EMA(26)_t$$

**Línea de Señal:**

$$Signal_t = EMA(9, MACD)_t$$

Es decir, una EMA de 9 períodos aplicada sobre la serie MACD.

**Histograma:**

$$Histogram_t = MACD_t - Signal_t$$

### 2.4.2 Interpretación como Derivadas

La interpretación más elegante del MACD es en términos de cálculo diferencial:

- **MACD** ≈ primera derivada suavizada del precio. Mide la **velocidad** del cambio de precio. MACD > 0 indica que el precio sube (la EMA corta está por encima de la larga); MACD < 0 indica que baja.

- **Histograma** ≈ segunda derivada suavizada del precio. Mide la **aceleración** del momentum. Un histograma creciente indica que el momentum se acelera; uno decreciente indica desaceleración.

Matemáticamente, si $P(t)$ es el precio como función continua:
- $MACD \sim \frac{dP}{dt}$ (velocidad)
- $Histogram \sim \frac{d^2P}{dt^2}$ (aceleración)

### 2.4.3 Parámetros (12, 26, 9)

Los parámetros clásicos (12, 26, 9) fueron elegidos por Appel para mercados bursátiles con 5 días de trading por semana:
- **12 períodos**: ~2.5 semanas (ciclo corto).
- **26 períodos**: ~5 semanas (~1 mes calendario).
- **9 períodos** de la señal: ~2 semanas.

Estos valores funcionan razonablemente bien en crypto (que opera 24/7), aunque los ciclos temporales reales son diferentes. La comunidad crypto ha explorado parámetros alternativos, pero los clásicos siguen siendo los más usados y los que mejor interpretan los modelos de IA entrenados con datos históricos.

### 2.4.4 Implementación

```python
macd_obj = ta.trend.MACD(c)
macd_val = macd_obj.macd().iloc[-1]
macd_signal = macd_obj.macd_signal().iloc[-1]
macd_hist = macd_obj.macd_diff().iloc[-1]
```

Se extraen tres valores del último período: la línea MACD, la señal y el histograma. Los tres son almacenados en `IndicatorSet` como campos separados para ser consumidos por las estrategias.

### 2.4.5 Fortalezas y Debilidades

**Fortalezas:**
- Combina tendencia y momentum en un solo indicador.
- El histograma proporciona señales tempranas de cambio de momentum.
- Ampliamente conocido: los LLMs que verifican las señales (Claude) tienen abundante conocimiento contextual sobre MACD.

**Debilidades:**
- **Doble lag**: al basarse en EMAs (que ya son lagging), el MACD hereda y amplifica el retraso.
- **No acotado**: a diferencia del RSI, el MACD no tiene valores absolutos de referencia. Un MACD de 500 en BTC no es comparable con un MACD de 0.5 en SOL. Por esto, el agente usa MACD principalmente para dirección (positivo/negativo) y tendencia del histograma, no para valores absolutos.

---

## 2.5 Bandas de Bollinger

### 2.5.1 Derivación Matemática

Las Bandas de Bollinger, desarrolladas por John Bollinger en los años 1980, envuelven el precio con un canal dinámico basado en la desviación estándar:

**Banda media (SMA):**

$$BB_{middle} = SMA(20) = \frac{1}{20} \sum_{i=0}^{19} P_{t-i}$$

**Bandas superior e inferior:**

$$BB_{upper} = BB_{middle} + k \cdot \sigma$$
$$BB_{lower} = BB_{middle} - k \cdot \sigma$$

Donde $\sigma$ es la desviación estándar de los últimos 20 precios de cierre y $k = 2$ es el multiplicador estándar.

**Fundamento estadístico:**

Si los retornos fueran normalmente distribuidos (que no lo son exactamente, pero la aproximación es útil), el intervalo $[\mu - 2\sigma, \mu + 2\sigma]$ contendría el **95.44%** de las observaciones. Esto significa que un precio fuera de las bandas es un evento con probabilidad < 5% — estadísticamente inusual.

En realidad, los retornos financieros exhiben **colas pesadas** (fat tails / leptokurtosis), lo que significa que los eventos extremos ocurren con mayor frecuencia de lo que predice la distribución normal. Las bandas de Bollinger subestiman sistemáticamente la probabilidad de excursiones extremas. Esto es importante: un precio tocando la banda inferior no garantiza reversión; en mercados con distribución de cola pesada, puede seguir cayendo.

### 2.5.2 Métricas Derivadas

El agente calcula dos métricas derivadas de las bandas:

**BB Percent (bb_pct):**

$$bb\_pct = \frac{P_{close} - BB_{lower}}{BB_{upper} - BB_{lower}}$$

Normaliza la posición del precio dentro de las bandas en el rango $[0, 1]$:
- $bb\_pct \approx 0$: precio en la banda inferior (potencial sobreventa).
- $bb\_pct \approx 0.5$: precio en la media.
- $bb\_pct \approx 1$: precio en la banda superior (potencial sobrecompra).
- $bb\_pct < 0$ o $bb\_pct > 1$: precio **fuera** de las bandas (evento extremo).

**BB Width (bb_width):**

$$bb\_width = \frac{BB_{upper} - BB_{lower}}{BB_{middle}}$$

Mide la **volatilidad relativa**. Un bb_width pequeño indica que las bandas se han contraído (**squeeze**), lo que históricamente precede a movimientos explosivos. Un bb_width grande indica volatilidad elevada.

### 2.5.3 Implementación

```python
bb = ta.volatility.BollingerBands(c, window=20, window_dev=2)
bb_upper = bb.bollinger_hband().iloc[-1]
bb_lower = bb.bollinger_lband().iloc[-1]
bb_middle = bb.bollinger_mavg().iloc[-1]
bb_range = bb_upper - bb_lower
bb_width = bb_range / bb_middle if bb_middle > 0 else 0.0
bb_pct = (c.iloc[-1] - bb_lower) / bb_range if bb_range > 0 else 0.5
```

Nótese la protección contra división por cero en `bb_width` (si `bb_middle` = 0, que solo ocurriría con un activo de precio cero) y `bb_pct` (si `bb_range` = 0, que indica volatilidad nula — el precio no se movió en 20 períodos).

### 2.5.4 Fortalezas y Debilidades

**Fortalezas:**
- Se adaptan dinámicamente a la volatilidad (a diferencia de canales fijos).
- `bb_pct` normaliza la posición del precio para comparación entre activos.
- El squeeze (bb_width bajo) es un predictor útil de movimientos futuros.

**Debilidades:**
- Asumen distribución normal, que no aplica rigurosamente en mercados financieros.
- La banda media es una SMA(20), que tiene más lag que una EMA.
- En tendencias fuertes, el precio puede "surfear" la banda superior durante semanas sin revertir.

---

## 2.6 ATR — Average True Range

### 2.6.1 Derivación Matemática

El ATR, también creado por Wilder (1978), mide la **volatilidad** del precio en términos absolutos.

**Paso 1: True Range**

$$TR_t = \max(H_t - L_t, \; |H_t - C_{t-1}|, \; |L_t - C_{t-1}|)$$

Donde $H$ = High, $L$ = Low, $C$ = Close. El True Range considera tres escenarios:
- **$H_t - L_t$**: rango intradía (caso normal).
- **$|H_t - C_{t-1}|$**: gap alcista desde el cierre anterior.
- **$|L_t - C_{t-1}|$**: gap bajista desde el cierre anterior.

El uso de $\max$ de los tres asegura que los **gaps** (saltos de precio entre períodos) se capturen en la medida de volatilidad. En crypto, donde el mercado opera 24/7, los gaps son menos frecuentes que en acciones, pero sí ocurren en momentos de alta volatilidad.

**Paso 2: Average True Range**

$$ATR_t = EMA(TR, 14)_t$$

La implementación en `ta` aplica una EMA de 14 períodos al True Range, produciendo una medida suavizada de volatilidad.

### 2.6.2 ATR Normalizado (atr_pct)

El ATR absoluto (en USD) no es comparable entre activos. Un ATR de $500 para BTC ($60,000) indica baja volatilidad (0.83%), mientras que un ATR de $500 para ETH ($3,000) indica altísima volatilidad (16.7%).

La normalización resuelve esto:

$$atr\_pct = \frac{ATR}{P_{close}}$$

Este ratio es adimensional y comparable. Valores típicos:
- BTC: 1-3% (volatilidad moderada)
- SOL: 3-6% (alta volatilidad)
- XAU: 0.5-1.5% (baja volatilidad)

### 2.6.3 Usos del ATR en el Sistema

El ATR es posiblemente el indicador más versátil del sistema. Se usa para:

1. **Stop Loss dinámico**: `SL = precio - ATR × multiplicador`. Un SL basado en ATR se adapta automáticamente a la volatilidad actual del activo.

2. **Take Profit dinámico**: `TP = precio + ATR × multiplicador`. Mismo principio.

3. **Position sizing**: el `RiskManager` usa ATR para calcular el tamaño de posición que limita la pérdida potencial a un porcentaje fijo del portafolio.

4. **Trend strength**: la fuerza de la tendencia se normaliza dividiendo la separación de EMAs por ATR (ver sección 2.9).

5. **Filtro de breakout**: la estrategia Breakout requiere `atr_pct > 1.5%` para confirmar que el movimiento es significativo.

### 2.6.4 Implementación

```python
atr = ta.volatility.average_true_range(h, lo, c, window=14).iloc[-1]
atr_pct = atr / c.iloc[-1] if c.iloc[-1] > 0 else 0.0
```

### 2.6.5 Fortalezas y Debilidades

**Fortalezas:**
- Captura gaps (a diferencia de un simple High-Low range).
- La normalización (`atr_pct`) permite comparación cross-asset.
- Base sólida para position sizing dinámico.

**Debilidades:**
- Es puramente retrospectivo: mide la volatilidad pasada, no la futura.
- En transiciones de régimen (de baja a alta volatilidad), el ATR reacciona con delay.

---

## 2.7 VWAP — Precio Promedio Ponderado por Volumen

### 2.7.1 Derivación Matemática

El VWAP es el **precio promedio ponderado por volumen** del período:

$$VWAP = \frac{\sum_{i=1}^{n} P_{typical,i} \times V_i}{\sum_{i=1}^{n} V_i}$$

Donde el precio típico es:

$$P_{typical} = \frac{H + L + C}{3}$$

El VWAP representa el precio "justo" al que se transaccionó el activo, ponderando cada precio por su volumen asociado. Intuitivamente, si la mayoría del volumen ocurrió a $60,000, el VWAP estará cerca de $60,000 aunque el precio haya fluctuado entre $58,000 y $62,000.

### 2.7.2 Proxy Intraday con Ventana Rolling

El VWAP clásico se reinicia cada día de trading. En crypto (mercado 24/7), no hay un "inicio de día" natural. La implementación usa una **ventana rolling de 20 velas** como proxy:

```python
typical = (h + lo + c) / 3
vol_sum = v.rolling(20).sum().iloc[-1]
vwap = (
    (typical * v).rolling(20).sum().iloc[-1] / vol_sum
    if vol_sum > 0
    else c.iloc[-1]
)
```

Esta aproximación captura el "precio justo reciente" sin depender de una sesión de trading definida. Para timeframe 1h, cubre las últimas 20 horas; para 15m, las últimas 5 horas.

### 2.7.3 Interpretación

- **Precio > VWAP**: los compradores están pagando más que el promedio ponderado por volumen — sesgo alcista.
- **Precio < VWAP**: los vendedores están ejecutando por debajo del promedio — sesgo bajista.
- **Precio ≈ VWAP**: equilibrio entre compradores y vendedores.

El VWAP también actúa como **nivel de soporte/resistencia dinámico**: los traders institucionales suelen usar VWAP como benchmark de ejecución, lo que genera concentraciones de órdenes alrededor del VWAP.

### 2.7.4 Fortalezas y Debilidades

**Fortalezas:**
- Incorpora volumen, una dimensión que la mayoría de indicadores ignoran.
- Ampliamente usado por institucionales como benchmark.

**Debilidades:**
- Pierde significado con ventanas largas (se vuelve insensible a cambios recientes).
- No es un predictor; es un descriptor del estado actual del mercado.

---

## 2.8 Volumen: SMA y Ratio

### 2.8.1 Volumen SMA(20)

$$vol\_sma20 = \frac{1}{20} \sum_{i=0}^{19} V_{t-i}$$

El promedio simple de las últimas 20 velas de volumen establece un **baseline** de actividad normal.

### 2.8.2 Volume Ratio

$$vol\_ratio = \frac{V_t}{vol\_sma20}$$

Este ratio normaliza el volumen actual contra su media:
- $vol\_ratio \approx 1.0$: volumen normal.
- $vol\_ratio > 1.5$: spike de volumen (interés inusual).
- $vol\_ratio \geq 2.0$: requerimiento mínimo para la estrategia Breakout.

El volumen es el **indicador de confirmación** por excelencia. Un movimiento de precio con alto volumen tiene mayor probabilidad de ser genuino que uno con bajo volumen. En la jerga de microestructura, el volumen mide la **convicción** detrás de un movimiento.

### 2.8.3 Implementación

```python
vol_sma20 = v.rolling(20).mean().iloc[-1]
vol_ratio = v.iloc[-1] / vol_sma20 if vol_sma20 > 0 else 1.0
```

---

## 2.9 Indicadores Derivados: Dirección y Fuerza de Tendencia

### 2.9.1 Dirección de Tendencia

La dirección se determina mediante la relación entre precio, EMA(20) y EMA(50):

```python
if ema20 > ema50 and close > ema20:
    trend_direction = 'UP'
elif ema20 < ema50 and close < ema20:
    trend_direction = 'DOWN'
else:
    trend_direction = 'SIDEWAYS'
```

La lógica requiere **doble confirmación**:
- **UP**: la EMA corta está por encima de la larga (estructura alcista) **Y** el precio está por encima de la EMA corta (momentum activo).
- **DOWN**: inversamente.
- **SIDEWAYS**: cualquier combinación que no sea claramente alcista o bajista. Esto incluye escenarios como EMA20 > EMA50 pero precio < EMA20 (estructura alcista con corrección temporal).

### 2.9.2 Fuerza de Tendencia

$$trend\_strength = \min\left(\frac{|EMA_{20} - EMA_{50}|}{ATR \times 5}, \; 1.0\right)$$

Esta fórmula normaliza la separación de las EMAs por la volatilidad (ATR):
- **Numerador**: distancia absoluta entre EMA(20) y EMA(50). Mayor separación = tendencia más definida.
- **Denominador**: $ATR \times 5$ actúa como escala. Se multiplica por 5 para que el ratio se mantenga en un rango útil.
- **$\min(\cdot, 1.0)$**: acota el resultado a $[0, 1]$.

Una `trend_strength` de 0.8 indica una tendencia fuerte; 0.1 indica un mercado sin dirección clara. El factor 5 es empírico: calibrado para que una tendencia de "intensidad media" produzca valores alrededor de 0.5.

---

## 2.10 El Dataclass `IndicatorSet`: Inmutabilidad en Datos Financieros

### 2.10.1 Diseño

```python
@dataclass(frozen=True)
class IndicatorSet:
    """Snapshot inmutable de todos los indicadores para un activo/timeframe."""
    asset: str
    timeframe: str
    close: float
    volume: float
    ema20: float
    ema50: float
    ema200: float
    rsi: float
    macd: float
    macd_signal: float
    macd_hist: float
    bb_upper: float
    bb_middle: float
    bb_lower: float
    bb_pct: float
    bb_width: float
    atr: float
    atr_pct: float
    vwap: float
    vol_sma20: float
    vol_ratio: float
    trend_direction: str
    trend_strength: float
```

### 2.10.2 ¿Por qué `frozen=True`?

El atributo `frozen=True` hace que el dataclass sea **inmutable**: una vez creada una instancia, ningún campo puede ser modificado. Cualquier intento de asignación (`ind.rsi = 50`) lanza un `FrozenInstanceError`.

En el contexto de un sistema de trading, la inmutabilidad no es una mera preferencia estilística — es una **garantía de seguridad**:

1. **Consistencia temporal**: un `IndicatorSet` representa un **snapshot** del mercado en un instante preciso. Todos los indicadores son coherentes entre sí (calculados sobre los mismos datos OHLCV). Si fuera mutable, un módulo podría accidentalmente modificar un campo, generando un estado inconsistente donde el RSI corresponde a un momento y las EMAs a otro.

2. **Thread safety**: si el sistema evoluciona hacia procesamiento concurrente (múltiples assets en paralelo), los objetos inmutables son inherentemente thread-safe — no requieren locks.

3. **Auditabilidad**: cada señal de trading puede trazarse hasta un `IndicatorSet` específico que nunca cambió. Esto es crucial para debugging post-mortem: "¿por qué el agente compró BTC a las 14:30?" — podés inspeccionar el `IndicatorSet` exacto que produjo esa decisión.

4. **Hashabilidad**: los objetos frozen son hashables, lo que permite usarlos como claves de diccionario o elementos de conjuntos — útil para caching y deduplicación.

### 2.10.3 Los 23 Campos

El `IndicatorSet` encapsula **23 métricas** organizadas en cinco categorías:

| Categoría    | Campos                                                             | Propósito                        |
|--------------|--------------------------------------------------------------------|----------------------------------|
| Identificación | `asset`, `timeframe`                                             | Contexto                         |
| Precio/Volumen | `close`, `volume`                                                | Datos crudos                     |
| Tendencia    | `ema20`, `ema50`, `ema200`                                         | Dirección del mercado            |
| Momentum     | `rsi`, `macd`, `macd_signal`, `macd_hist`                          | Velocidad del cambio             |
| Volatilidad  | `bb_upper/middle/lower`, `bb_pct`, `bb_width`, `atr`, `atr_pct`   | Dispersión y riesgo              |
| Volumen      | `vwap`, `vol_sma20`, `vol_ratio`                                   | Convicción del mercado           |
| Derivados    | `trend_direction`, `trend_strength`                                | Resumen interpretativo           |

Este conjunto fue diseñado para proporcionar a las estrategias **toda la información necesaria** para tomar decisiones sin acceder al DataFrame crudo de OHLCV. Es una **interfaz limpia** entre el módulo de cálculo y el módulo de decisión.

---

## 2.11 El Pipeline Completo de `IndicatorEngine.calculate()`

Repasemos el flujo completo del método `calculate()`:

```python
@staticmethod
def calculate(df: pd.DataFrame, asset: str, timeframe: str) -> Optional[IndicatorSet]:
    if len(df) < 50:
        return None  # Insuficientes datos

    c = df['close']
    v = df['volume']
    h = df['high']
    lo = df['low']

    # 1. EMAs (tendencia)
    ema20 = ta.trend.ema_indicator(c, window=20).iloc[-1]
    ema50 = ta.trend.ema_indicator(c, window=50).iloc[-1]
    ema200 = ta.trend.ema_indicator(c, window=200).iloc[-1] if len(df) >= 200 else ema50

    # 2. RSI (momentum)
    rsi = ta.momentum.rsi(c, window=14).iloc[-1]

    # 3. MACD (momentum + tendencia)
    macd_obj = ta.trend.MACD(c)
    macd_val, macd_signal, macd_hist = (
        macd_obj.macd().iloc[-1],
        macd_obj.macd_signal().iloc[-1],
        macd_obj.macd_diff().iloc[-1]
    )

    # 4. Bollinger Bands (volatilidad)
    bb = ta.volatility.BollingerBands(c, window=20, window_dev=2)
    # ... cálculos de bb_upper, bb_lower, bb_middle, bb_width, bb_pct

    # 5. ATR (volatilidad)
    atr = ta.volatility.average_true_range(h, lo, c, window=14).iloc[-1]
    atr_pct = atr / c.iloc[-1]

    # 6. VWAP (volumen)
    # ... cálculo rolling 20

    # 7. Volume ratio
    vol_sma20 = v.rolling(20).mean().iloc[-1]
    vol_ratio = v.iloc[-1] / vol_sma20

    # 8. Trend direction y strength (derivados)
    # ... lógica de clasificación

    return IndicatorSet(...)  # Objeto frozen inmutable
```

**Observaciones de diseño:**

1. **Método estático**: no requiere estado de instancia. Dado un DataFrame, produce un resultado determinístico. Esto facilita el testing.

2. **Guard clause**: `if len(df) < 50: return None`. Se requieren al menos 50 velas para que los indicadores sean estadísticamente significativos (EMA(50) necesita 50 puntos para ser calculada).

3. **Fallback para EMA(200)**: si no hay 200 puntos, usa EMA(50) como proxy. Pragmatismo sobre purismo.

4. **Todas las divisiones protegidas**: cada división verifica que el denominador > 0. En datos financieros, un volumen de 0 o un precio de 0 son posibles (activos delisted, errores de datos), y una división por cero colapsaría todo el pipeline.

---

## 2.12 Limitaciones del Análisis Técnico

Ningún capítulo académico sobre análisis técnico estaría completo sin discutir sus limitaciones fundamentales:

### 2.12.1 La Hipótesis del Mercado Eficiente (EMH)

Eugene Fama (1970) propuso que los mercados son eficientes en tres formas:
- **Débil**: los precios pasados no predicen precios futuros. Si esto es cierto, todo análisis técnico es inútil.
- **Semifuerte**: toda información pública está reflejada en el precio.
- **Fuerte**: toda información (incluso privada) está reflejada.

La evidencia empírica sugiere que los mercados están en algún punto entre débil y semifuerte. Los mercados crypto, siendo más jóvenes y menos regulados, exhiben mayores ineficiencias que los mercados tradicionales, lo que crea oportunidades para sistemas cuantitativos.

### 2.12.2 Overfitting y Data Mining Bias

Con suficientes indicadores y parámetros, cualquier estrategia puede "funcionar" en datos históricos. El peligro del **overfitting** es real: un sistema que obtiene 95% de win rate en backtesting pero falla en live porque memorizó ruido en lugar de capturar patrones genuinos.

Nuestro agente mitiga esto con:
- **Indicadores clásicos**: EMA, RSI, Bollinger, ATR son indicadores con décadas de uso y literatura académica que sustenta su utilidad.
- **Pocos parámetros**: los parámetros estándar (14 para RSI, 20 para BB, etc.) son los más estudiados y menos susceptibles a overfitting.
- **Paper trading extensivo**: antes de operar con capital real, el sistema debe demostrar consistencia en condiciones de mercado diversas.

### 2.12.3 Regímenes de Mercado

Los indicadores técnicos funcionan mejor en ciertos regímenes:
- **Trending**: EMAs y MACD brillan.
- **Mean-reverting**: Bollinger y RSI brillan.
- **Regime changes**: todos los indicadores fallan temporalmente.

El agente aborda esto usando **múltiples estrategias** evaluadas en paralelo. Si el mercado está trending, la TrendMomentumStrategy generará scores altos; si está en rango, la MeanReversionStrategy tomará la delantera. Esta orquestación es el tema del próximo capítulo.

---

## 2.13 Resumen del Capítulo

| Indicador | Fórmula clave | Tipo | Uso principal |
|-----------|---------------|------|---------------|
| EMA | $\alpha P_t + (1-\alpha) EMA_{t-1}$ | Tendencia | Dirección del mercado |
| RSI | $100 - \frac{100}{1+RS}$ | Momentum | Zonas de sobreventa/sobrecompra |
| MACD | $EMA(12) - EMA(26)$ | Momentum/Tendencia | Velocidad y aceleración |
| Bollinger | $SMA(20) \pm 2\sigma$ | Volatilidad | Extremos estadísticos |
| ATR | $EMA(\max(H{-}L, |H{-}C'|, |L{-}C'|), 14)$ | Volatilidad | Position sizing, SL/TP |
| VWAP | $\frac{\sum P_{typ} V}{\sum V}$ | Volumen | Precio justo, soporte/resistencia |
| Vol Ratio | $V_t / SMA(V, 20)$ | Volumen | Confirmación de señales |

Todos estos indicadores, calculados determinísticamente por `IndicatorEngine.calculate()`, producen un `IndicatorSet` inmutable que las tres estrategias del sistema consumen para generar señales de trading. En el próximo capítulo, veremos cómo estas señales se traducen en decisiones concretas de compra o venta.

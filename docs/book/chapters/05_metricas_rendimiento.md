# Capítulo 5: Métricas de Rendimiento y Criterios de Graduación

> *"Sin medición no hay mejora, y sin significancia estadística no hay medición."*

Un sistema de trading sin métricas rigurosas es un acto de fe. Las métricas de rendimiento cumplen tres funciones esenciales: **diagnosticar** el comportamiento del sistema (¿está funcionando como se diseñó?), **comparar** contra benchmarks de la industria (¿es competitivo?), y **decidir** cuándo el sistema está listo para operar con capital real. Este capítulo formaliza cada métrica utilizada por el agente, deriva sus fundamentos matemáticos y establece los criterios cuantitativos para la transición de paper trading a trading en vivo.

---

## 5.1 Sharpe Ratio — El Estándar de la Industria

### Definición y Derivación

El **Sharpe Ratio**, propuesto por William F. Sharpe en 1966 (y revisado en 1994), mide el exceso de retorno por unidad de riesgo total:

$$S = \frac{E[R_p - R_f]}{\sigma_p}$$

Donde:
- $R_p$ = retorno del portafolio
- $R_f$ = tasa libre de riesgo (risk-free rate)
- $\sigma_p$ = desviación estándar de los retornos del portafolio

En la práctica, con datos de retornos diarios $r_1, r_2, \ldots, r_n$, el estimador muestral es:

$$\hat{S}_{daily} = \frac{\bar{r} - r_f}{\hat{\sigma}_r}$$

Donde $\bar{r} = \frac{1}{n}\sum_{i=1}^{n} r_i$ y $\hat{\sigma}_r = \sqrt{\frac{1}{n-1}\sum_{i=1}^{n}(r_i - \bar{r})^2}$.

### Anualización

Para convertir un Sharpe diario a anual, se aplica la **regla de la raíz cuadrada del tiempo**, que asume retornos independientes e idénticamente distribuidos (i.i.d.):

$$S_{annual} = S_{daily} \times \sqrt{T}$$

Donde $T$ es el número de periodos por año. Para mercados cripto que operan 365 días:

$$S_{annual} = S_{daily} \times \sqrt{365}$$

La implementación en el agente:

```python
sharpe = (returns.mean() / returns.std()) * np.sqrt(365)
```

Nota: aquí asumimos $R_f \approx 0$ para simplificar, dado que las tasas libres de riesgo son despreciables comparadas con la volatilidad cripto (la tasa de T-Bills a 3 meses ≈ 4% anual, mientras que la volatilidad anualizada de BTC ≈ 60-80%).

### Interpretación

| Sharpe Ratio | Calificación |
|:---:|:---|
| $< 0$ | El sistema pierde dinero ajustado por riesgo |
| $0 - 0.5$ | Subóptimo — un ETF de S&P500 históricamente da ~0.4 |
| $0.5 - 1.0$ | Aceptable |
| $1.0 - 1.5$ | Bueno — la mayoría de hedge funds se ubican aquí |
| $1.5 - 2.0$ | Excelente — top decil de la industria |
| $> 2.0$ | Excepcional — sostenible solo en nichos o periodos cortos |

**Target del sistema: $S > 1.5$** — excelente por estándares de la industria.

### Limitaciones Fundamentales

El Sharpe Ratio asume que los retornos siguen una **distribución normal** (gaussiana). Los mercados cripto violan esta suposición de maneras críticas:

1. **Asimetría (skewness)**: La distribución de retornos cripto tiene colas asimétricas. Las caídas tienden a ser más abruptas que las subidas.

2. **Curtosis excesiva**: Los retornos cripto exhiben $\kappa \gg 3$ (distribución normal tiene $\kappa = 3$). Esto significa eventos extremos ("cisnes negros") con frecuencia mucho mayor que la predicha por una gaussiana.

3. **Autocorrelación**: Los retornos cripto muestran autocorrelación significativa en periodos cortos (momentum), violando el supuesto i.i.d. necesario para la anualización por $\sqrt{T}$.

4. **Penalización simétrica**: El Sharpe penaliza igualmente la volatilidad al alza y a la baja. Un trade que gana 20% y otro que pierde 20% contribuyen **idénticamente** a $\sigma_p$. Para un trader, claramente no son equivalentes.

Estas limitaciones motivan métricas complementarias, particularmente el Sortino Ratio.

---

## 5.2 Sortino Ratio — Solo el Dolor Cuenta

### Motivación

El Sortino Ratio, propuesto por Frank Sortino, corrige la principal deficiencia conceptual del Sharpe: **la volatilidad al alza no es riesgo, es ganancia**.

Un sistema que frecuentemente produce retornos muy superiores al promedio tiene alta $\sigma_p$ — y por tanto un Sharpe deprimido — a pesar de que ese comportamiento es exactamente lo deseable.

### Definición Formal

$$Sortino = \frac{R_p - R_f}{\sigma_{downside}}$$

Donde la **desviación estándar downside** se calcula considerando solo los retornos negativos:

$$\sigma_{downside} = \sqrt{\frac{1}{n}\sum_{i=1}^{n} \min(r_i - R_f, 0)^2}$$

Observa la sutileza: no se excluyen los periodos con retornos positivos del denominador — se contabilizan como cero. Esto preserva el tamaño muestral y no sobreestima el riesgo downside.

### Relevancia para Sistemas de Trading

Los sistemas de trading bien diseñados exhiben **retornos asimétricos por construcción**: el R:R mínimo de 1.5 implica que las ganancias individuales son mayores que las pérdidas individuales. Esto produce una distribución con **asimetría positiva** (positive skew).

El Sharpe Ratio penaliza esta asimetría positiva. El Sortino no. Por tanto, para un sistema como el nuestro:

$$Sortino > Sharpe \quad \text{(esperado)}$$

Si observamos $Sortino < Sharpe$, es una señal de alarma: indicaría que la volatilidad downside supera la upside, sugiriendo que los stops se activan con más frecuencia (y magnitud) que los take profits.

---

## 5.3 Profit Factor — La Métrica de Eficiencia Bruta

### Definición

$$PF = \frac{\sum \text{Ganancias brutas}}{\sum |\text{Pérdidas brutas}|}$$

Equivalentemente, si descomponemos en trades individuales:

$$PF = \frac{\bar{W} \times n_W}{\bar{L} \times n_L}$$

Donde $\bar{W}$ es la ganancia promedio de trades ganadores, $n_W$ el número de ganadores, $\bar{L}$ la pérdida promedio (en valor absoluto) de trades perdedores, y $n_L$ el número de perdedores.

La implementación en el agente:

```python
profit_factor = (avg_win * n_winners) / (avg_loss * n_losers)
```

### Interpretación

| Profit Factor | Significado |
|:---:|:---|
| $< 1.0$ | El sistema pierde dinero — las pérdidas superan las ganancias |
| $1.0$ | Breakeven (sin comisiones) |
| $1.0 - 1.5$ | Marginalmente rentable — vulnerable a costos de transacción |
| $1.5 - 2.0$ | Bueno — \$1.50 ganados por cada \$1.00 perdido |
| $2.0 - 3.0$ | Excelente — sistema robusto |
| $> 3.0$ | Sospechoso en producción sostenida — posible sobreajuste |

**Target del sistema: $PF > 1.5$**.

### Relación con Win Rate y R:R

El Profit Factor puede expresarse como función del Win Rate ($WR$) y el ratio Ganancia/Pérdida promedio ($R = \bar{W}/\bar{L}$):

$$PF = \frac{WR \times R}{1 - WR}$$

Con $WR = 0.55$ y $R = 1.5$ (consistente con nuestro R:R mínimo):

$$PF = \frac{0.55 \times 1.5}{0.45} = \frac{0.825}{0.45} = 1.833$$

Esto confirma que los parámetros del sistema producen un Profit Factor teórico de ~1.83, cómodamente por encima del target de 1.5.

---

## 5.4 Win Rate vs. Expectativa: La Trampa del Principiante

### El Error Más Común

La mayoría de traders novatos optimizan para **win rate** — el porcentaje de trades ganadores. Esto es un error fundamental.

Considérese dos sistemas:

**Sistema A** — Win Rate 70%:
- $WR = 0.70$, $\bar{W} = \$50$, $\bar{L} = \$150$
- $E_A = 0.70 \times 50 - 0.30 \times 150 = 35 - 45 = -\$10$ por trade

**Sistema B** — Win Rate 40%:
- $WR = 0.40$, $\bar{W} = \$300$, $\bar{L} = \$80$
- $E_B = 0.40 \times 300 - 0.60 \times 80 = 120 - 48 = +\$72$ por trade

El sistema con **menor** win rate es **enormemente más rentable**. La victoria frecuente del Sistema A es una ilusión: gana muchas batallas pequeñas pero pierde guerras costosas.

### Expectativa Formal

La **expectativa** ($E$) por trade se define como:

$$E = WR \times \bar{W} - (1 - WR) \times \bar{L}$$

Para el sistema del agente, con targets de $WR = 0.55$, $\bar{W} = \$200$ (trade ganador promedio), $\bar{L} = \$100$ (trade perdedor promedio = risk amount):

$$E = 0.55 \times 200 - 0.45 \times 100 = 110 - 45 = +\$65 \text{ por trade}$$

Después de 100 trades, la ganancia esperada es $100 \times 65 = \$6{,}500$.

### La Fórmula Unificada

Podemos reescribir la expectativa normalizándola por la pérdida promedio:

$$E_{normalizada} = WR \times RR - (1 - WR)$$

Esta forma revela que la expectativa depende de **dos** variables: win rate y R:R. La isocurva $E = 0$ (breakeven) satisface:

$$WR_{breakeven} = \frac{1}{1 + RR}$$

Esto genera una frontera: toda combinación $(WR, RR)$ por encima de esta curva es rentable. Nuestro sistema opera en el punto $(0.55, 1.5)$, con margen significativo sobre la frontera.

---

## 5.5 Maximum Drawdown — Cuánto Puedes Perder

### Definición Computacional

El maximum drawdown se calcula sobre la serie temporal del equity $E_t$:

$$MDD = \min_{t} \left( \frac{E_t}{\max_{\tau \leq t} E_\tau} - 1 \right)$$

En código vectorizado:

```python
max_dd = (equity / equity.cummax() - 1).min()
```

Este cálculo produce un **número negativo** (o cero): $-0.12$ significa un drawdown del 12%.

### El "Pain Metric"

El maximum drawdown es la métrica que más impacta **psicológicamente** al operador. Un Sharpe Ratio de 2.0 es intelectualmente satisfactorio, pero un drawdown del 30% produce ansiedad visceral. La literatura de behavioral finance documenta que el dolor de perder \$1 es aproximadamente **2.5 veces más intenso** que el placer de ganar \$1 (Kahneman & Tversky, Prospect Theory, 1979).

### Límite del Sistema

El sistema establece:
- **Halt automático**: $MDD \geq 10\%$ (activación del `MAX_DRAWDOWN_STOP`).
- **Criterio de graduación**: $MDD \geq -12\%$ (el drawdown histórico total durante paper trading no debe exceder 12%).

La diferencia entre 10% y 12% es deliberada: el halt protege el capital en tiempo real, mientras que el criterio de graduación evalúa el peor escenario observado en todo el periodo de prueba — que puede incluir recuperaciones.

---

## 5.6 Criterios de Graduación: De Paper Trading a Capital Real

### Los Cuatro Pilares

La transición de paper trading a trading con capital real requiere satisfacer **simultáneamente** cuatro condiciones:

```python
passed = all([
    win_rate >= 0.55,        # >55% win rate
    profit_factor >= 1.5,    # >$1.50 por cada $1.00 perdido
    max_dd >= -0.12,         # <12% drawdown máximo
    n >= 30,                 # mínimo 30 trades para significancia estadística
])
```

Cada condición actúa como un **veto independiente**: basta que una falle para bloquear la graduación.

### ¿Por Qué 55% Win Rate?

Con $RR = 1.5$, el breakeven es $WR_{BE} = \frac{1}{2.5} = 40\%$. Exigir 55% proporciona un **margen de seguridad de 15 puntos porcentuales**. Este colchón absorbe:
- Degradación del modelo en condiciones de mercado diferentes.
- Costos de transacción (slippage, comisiones) no modelados en paper trading.
- La inevitable divergencia entre paper y real (paper fills son instantáneos; real fills pueden deslizarse).

### ¿Por Qué Profit Factor ≥ 1.5?

Un PF de 1.5 significa que por cada \$1.00 que el sistema pierde, genera \$1.50. Después de descontar costos operativos (comisiones típicas de ~0.1% por trade, más slippage de ~0.05%), el PF real será menor. Un PF de 1.5 en paper deja margen para mantener rentabilidad neta en producción.

### ¿Por Qué Max Drawdown ≤ 12%?

Un drawdown del 12% requiere una ganancia del ~13.6% para recuperarse:

$$\text{Recovery} = \frac{1}{1 - 0.12} - 1 \approx 0.136$$

Esto es alcanzable en semanas o pocos meses. Un drawdown del 25%, en cambio, requiere una ganancia del 33% para recuperarse — meses de operación perfecta. Y un drawdown del 50% requiere **duplicar** el capital. La relación es no lineal y se agrava rápidamente:

| Drawdown | Recuperación necesaria |
|:---:|:---:|
| 5% | 5.3% |
| 10% | 11.1% |
| 12% | 13.6% |
| 20% | 25.0% |
| 30% | 42.9% |
| 50% | 100.0% |

### ¿Por Qué n ≥ 30 Trades?

Esta condición es la más fundamental desde el punto de vista estadístico.

El **Teorema del Límite Central** (TLC) establece que, dada una muestra de $n$ observaciones i.i.d. con media $\mu$ y varianza $\sigma^2$ finitas, la distribución de la media muestral $\bar{X}_n$ converge a una distribución normal conforme $n \to \infty$:

$$\frac{\bar{X}_n - \mu}{\sigma / \sqrt{n}} \xrightarrow{d} \mathcal{N}(0, 1)$$

La convención en estadística aplicada establece $n \geq 30$ como el umbral práctico donde la aproximación normal es razonable, independientemente de la distribución subyacente. Con menos de 30 observaciones:

- Los **intervalos de confianza** para el win rate son extremadamente amplios. Con $n = 3$ y $\hat{WR} = 1.00$, el intervalo de confianza del 95% por el método de Wilson es $[0.44, 1.00]$. ¡El verdadero win rate podría ser tan bajo como 44%!
- El **Profit Factor** es hipersensible a outliers. Un trade con ganancia inusualmente grande puede inflar el PF de manera irrecuperable cuando $n$ es pequeño.
- El **Sharpe Ratio** tiene un error estándar de $\approx \sqrt{(1 + 0.5 \times S^2) / n}$, que para $n = 3$ y $S = 1.5$ es $\approx 0.78$ — un intervalo tan amplio que el Sharpe verdadero podría ser negativo.

30 trades es el **mínimo tolerable**. Idealmente, se buscarían 100+ para estimaciones robustas, pero 30 es el compromiso entre rigor estadístico y velocidad de iteración.

---

## 5.7 Estado Actual del Sistema

### Los Números

Al momento de redactar este capítulo, el sistema ha ejecutado **3 trades cerrados**, todos ganadores:

| Métrica | Valor observado | Target | Estado |
|:---|:---:|:---:|:---:|
| Win Rate | 100% (3/3) | ≥ 55% | ⚠️ n insuficiente |
| Profit Factor | $\infty$ (0 pérdidas) | ≥ 1.5 | ⚠️ n insuficiente |
| Max Drawdown | ~0% | ≤ 12% | ⚠️ n insuficiente |
| Trades cerrados | 3 | ≥ 30 | ❌ Faltan 27 |

### Interpretación Honesta

Un win rate del 100% con 3 trades es **estadísticamente indistinguible de un mono lanzando dardos**. Utilizando una prueba binomial:

- $H_0$: El win rate verdadero es 50% (aleatorio).
- $H_1$: El win rate verdadero es > 50%.
- $P(X \geq 3 | n=3, p=0.5) = 0.125$

Con $p\text{-value} = 0.125$, **no podemos rechazar** la hipótesis nula al nivel de significancia estándar ($\alpha = 0.05$). En lenguaje llano: no hay evidencia suficiente para afirmar que el sistema es mejor que el azar.

Esto no es pesimismo — es rigor científico. El sistema puede ser genuinamente excelente, pero 3 observaciones no permiten demostrarlo. El camino es claro: ejecutar 27 trades más y re-evaluar.

### Proyección con Parámetros de Diseño

Si el sistema mantiene los parámetros de diseño ($WR = 55\%$, $RR = 1.5$) a través de 30 trades:

- **Trades ganadores esperados**: $30 \times 0.55 = 16.5 \approx 17$
- **Trades perdedores esperados**: $30 \times 0.45 = 13.5 \approx 13$
- **Ganancia bruta esperada**: $17 \times \$200 = \$3{,}400$
- **Pérdida bruta esperada**: $13 \times \$100 = \$1{,}300$
- **PnL neto esperado**: $\$3{,}400 - \$1{,}300 = +\$2{,}100$
- **Profit Factor esperado**: $3{,}400 / 1{,}300 \approx 2.62$
- **Expectativa por trade**: $\$70$

Estas proyecciones asumen independencia entre trades y estacionariedad de los parámetros — supuestos que se verificarán conforme se acumulen datos.

---

## 5.8 Resumen del Capítulo

Las métricas de rendimiento del agente forman un **sistema de evaluación multidimensional**:

- **Sharpe Ratio** ($> 1.5$): Retorno ajustado por riesgo total. Estándar de la industria, pero asume normalidad.
- **Sortino Ratio**: Versión mejorada que solo penaliza la volatilidad negativa. Superior para sistemas con asimetría positiva.
- **Profit Factor** ($> 1.5$): Eficiencia bruta en dólares ganados vs. perdidos.
- **Expectativa**: Ganancia promedio por trade — la métrica más directamente accionable.
- **Maximum Drawdown** ($< 12\%$): El peor escenario observado. Límite psicológico y operativo.

Los **criterios de graduación** forman una barrera rigurosa pero justa: 55% win rate, PF > 1.5, drawdown < 12%, y un mínimo de 30 trades para significancia estadística. Solo cuando se satisfacen las cuatro condiciones simultáneamente el sistema está autorizado para operar con capital real.

El estado actual — 3 ganadores de 3 — es prometedor pero insuficiente. La estadística no se negocia. Faltan 27 trades cerrados para poder emitir un juicio informado sobre la viabilidad del sistema en producción.

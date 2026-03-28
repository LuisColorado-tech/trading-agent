# Capítulo 4: Gestión de Riesgo — El Pilar del Trading

> *"El trading no se trata de cuánto ganas, sino de cuánto conservas."*

La gestión de riesgo es, sin exageración, **el único componente que separa al trader rentable del jugador compulsivo**. Un sistema con señales mediocres pero gestión de riesgo excelente sobrevivirá y eventualmente generará retornos. Un sistema con señales perfectas pero sin gestión de riesgo terminará en bancarrota — es cuestión de tiempo, no de probabilidad.

En este capítulo derivaremos formalmente cada uno de los fundamentos matemáticos que sustentan las decisiones de riesgo del agente, analizaremos las siete reglas inmutables codificadas en `risk_manager.py`, y recorreremos paso a paso el pipeline completo de evaluación de riesgo.

---

## 4.1 El Criterio de Kelly

### Derivación Formal

El **Criterio de Kelly** (1956) responde a la pregunta fundamental: *¿qué fracción de mi capital debo apostar en cada operación para maximizar el crecimiento logarítmico a largo plazo?*

Consideremos un escenario donde:
- $b$ = razón de pago (odds). Si arriesgas \$1 y ganas, recibes \$b.
- $p$ = probabilidad de ganar.
- $q = 1 - p$ = probabilidad de perder.

Queremos maximizar el valor esperado del logaritmo del capital después de $n$ apuestas. Si apostamos una fracción $f$ de nuestro capital en cada operación, después de una apuesta ganadora nuestro capital se multiplica por $(1 + bf)$ y después de una perdedora por $(1 - f)$.

El **crecimiento logarítmico esperado** por apuesta es:

$$G(f) = p \ln(1 + bf) + q \ln(1 - f)$$

Para encontrar el máximo, derivamos respecto a $f$ e igualamos a cero:

$$\frac{dG}{df} = \frac{pb}{1 + bf} - \frac{q}{1 - f} = 0$$

Resolviendo:

$$\frac{pb}{1 + bf^*} = \frac{q}{1 - f^*}$$

$$pb(1 - f^*) = q(1 + bf^*)$$

$$pb - pbf^* = q + qbf^*$$

$$pb - q = pbf^* + qbf^*$$

$$pb - q = bf^*(p + q)$$

Como $p + q = 1$:

$$pb - q = bf^*$$

$$\boxed{f^* = \frac{bp - q}{b}}$$

### Interpretación Geométrica

El criterio de Kelly maximiza la **tasa de crecimiento geométrico** del capital. Esto es fundamentalmente diferente a maximizar el valor esperado aritmético. Un apostador que maximiza el valor esperado aritmético arriesgaría todo su capital cuando la esperanza es positiva — y eventualmente lo perdería todo por la ruina del jugador.

Kelly, en cambio, **nunca arriesga todo** porque $\ln(0) = -\infty$, lo que penaliza infinitamente la bancarrota.

### Kelly Fraccional: Por Qué Usamos 1%

En la práctica, el Kelly completo presenta problemas serios:

1. **Sobreestimación de $p$ y $b$**: Las estimaciones de win rate y ratio de ganancia son muestras ruidosas. Un error de ±5% en $p$ puede duplicar la fracción óptima.
2. **Volatilidad extrema**: Kelly completo produce drawdowns del 50-70% antes de recuperarse. Psicológica y operativamente, esto es insostenible.
3. **Colas gruesas**: Los mercados cripto exhiben distribuciones leptocúrticas (excess kurtosis), donde eventos extremos ocurren con mayor frecuencia que bajo distribución normal.

La solución estándar en la industria es usar **Kelly fraccional**: apostar una fracción $\alpha$ del Kelly óptimo, típicamente $\alpha \in [0.1, 0.5]$.

Nuestro sistema usa un enfoque aún más conservador:

```python
MAX_RISK_PER_TRADE_PCT = 0.01  # 1% del portafolio por trade
```

Supongamos un Kelly óptimo del 10% (que requeriría $p = 0.6$, $b = 1.5$). Nuestro 1% representa un **Kelly fraccional de $\alpha = 0.1$** — la décima parte del óptimo teórico. Esto sacrifica velocidad de crecimiento a cambio de:

- Drawdowns máximos significativamente menores.
- Robustez ante errores de estimación.
- Supervivencia garantizada durante rachas perdedoras prolongadas.

Con un riesgo del 1% por trade, se necesitan **más de 200 trades perdedores consecutivos** para perder el 87% del capital ($(0.99)^{200} \approx 0.13$). En un sistema con 55% de win rate, la probabilidad de 200 pérdidas consecutivas es $(0.45)^{200} \approx 10^{-70}$ — un evento que no ocurrirá antes de la muerte térmica del universo.

---

## 4.2 Dimensionamiento de Posición (Position Sizing)

### Fórmula de Sizing Basado en Riesgo

El dimensionamiento de posición responde: *dado que acepto perder X dólares si el trade falla, ¿cuántas unidades puedo comprar?*

$$PositionSize = \frac{RiskAmount}{RiskPerUnit}$$

Donde:

$$RiskAmount = Balance \times MaxRiskPct$$

$$RiskPerUnit = |EntryPrice - StopLoss|$$

La implementación en el agente:

```python
risk_amount = total_balance * MAX_RISK_PER_TRADE_PCT  # 1% del balance total
position_size = risk_amount / risk_per_unit             # risk_per_unit = |entry - SL|
```

### Ejemplo Numérico

Supongamos:
- Balance: \$10,000
- Entry BTC: \$60,000
- Stop Loss: \$59,100 (basado en 1.5 × ATR, con ATR = \$600)

Entonces:
- $RiskAmount = 10{,}000 \times 0.01 = \$100$
- $RiskPerUnit = |60{,}000 - 59{,}100| = \$900$
- $PositionSize = \frac{100}{900} = 0.1111$ BTC

El agente compraría 0.1111 BTC (\$6,666.67 de exposición). Si el stop loss se activa, la pérdida es exactamente \$100 — el 1% predeterminado.

### Implicación Crucial

Observa que el **tamaño de la posición es inversamente proporcional a la distancia del stop loss**. Activos más volátiles (ATR mayor) producen stops más lejanos y, por tanto, posiciones más pequeñas. Esto es un **regulador automático de riesgo**: a mayor volatilidad, menor exposición.

---

## 4.3 Ratio Riesgo:Recompensa (R:R)

### Definición Formal

$$RR = \frac{|TP - Entry|}{|Entry - SL|}$$

Donde:
- $TP$ = Take Profit (precio objetivo de ganancia)
- $Entry$ = precio de entrada
- $SL$ = Stop Loss (precio de salida por pérdida)

### Configuración del Sistema

```python
STOP_LOSS_ATR_MULTIPLIER = 1.5    # Stop = Entry ∓ (1.5 × ATR)
TAKE_PROFIT_ATR_MULT     = 2.5    # TP = Entry ± (2.5 × ATR)
MIN_RR_RATIO             = 1.5    # R:R mínimo aceptable
```

Con estos multiplicadores ATR, el ratio R:R implícito es:

$$RR_{implícito} = \frac{2.5 \times ATR}{1.5 \times ATR} = \frac{2.5}{1.5} \approx 1.667$$

Este ratio supera el mínimo de 1.5, pero la validación explícita existe porque el pipeline permite ajustes dinámicos a los niveles de SL/TP basados en niveles de soporte/resistencia identificados por Claude.

### Relación con Win Rate y Expectativa

La **expectativa** ($E$) de un sistema se define como:

$$E = WR \times AvgWin - (1 - WR) \times AvgLoss$$

Si normalizamos con $AvgLoss = 1$ y $AvgWin = RR$:

$$E = WR \times RR - (1 - WR)$$

Para que el sistema sea rentable, necesitamos $E > 0$:

$$WR \times RR > 1 - WR$$

$$WR > \frac{1}{1 + RR}$$

Con $RR = 1.5$: $WR > \frac{1}{2.5} = 0.40$. Es decir, solo necesitamos ganar el **40%** de los trades para ser rentables con R:R de 1.5.

Con nuestro target de $WR = 0.55$:

$$E = 0.55 \times 1.5 - 0.45 \times 1.0 = 0.825 - 0.45 = +0.375$$

Cada trade tiene una expectativa de **+\$0.375 por cada dólar arriesgado**. Con riesgo de \$100 por trade, la ganancia esperada es \$37.50 por operación.

---

## 4.4 Drawdown: La Métrica del Dolor

### Definición

El **Maximum Drawdown** (MDD) mide la mayor caída desde un máximo histórico del equity:

$$DD = \frac{Peak - Trough}{Peak}$$

Donde $Peak$ es el valor máximo del portafolio hasta ese momento y $Trough$ es el mínimo posterior antes de un nuevo máximo.

### Implementación del Halt de Emergencia

```python
MAX_DRAWDOWN_STOP = 0.10  # 10% drawdown → halt
```

Cuando el drawdown alcanza el 10%, el sistema ejecuta:

```python
self._trading_halted = True
```

Este flag **requiere intervención manual** para desactivarse. No existe un mecanismo automático de reactivación.

### ¿Por Qué Manual?

La razón es profundamente deliberada: **prevenir la espiral de muerte algorítmica**.

Cuando un sistema automatizado sufre un drawdown significativo, las condiciones que causaron las pérdidas probablemente persisten (cambio de régimen de mercado, correlaciones rotas, liquidez anormal). Un reinicio automático — basado en tiempo o recuperación parcial — arriesga:

1. **Revenge trading algorítmico**: El sistema entra en trades agresivos intentando "recuperarse", amplificando pérdidas.
2. **Régimen no reconocido**: Si las pérdidas se deben a un cambio estructural del mercado, el modelo que generó las señales ya no es válido.
3. **Cascada de pérdidas**: En mercados cripto, los crash se componen en cascada (liquidaciones forzadas → más ventas → más liquidaciones).

La pausa manual fuerza al operador humano a:
- Diagnosticar la causa del drawdown.
- Evaluar si las condiciones de mercado han cambiado.
- Decidir conscientemente si reasumir riesgo.

Esto encarna el principio rector del sistema: **AI asistida, no autónoma**.

---

## 4.5 Correlación Entre Activos y Límites de Exposición

### Trades Concurrentes

```python
MAX_CONCURRENT_TRADES = 3       # Máximo trades simultáneos
MAX_PORTFOLIO_EXPOSURE = 0.05   # 5% máximo total en posiciones
```

### El Problema de la Correlación

La diversificación funciona cuando los activos tienen correlación baja. En criptomonedas, esta premisa es **frecuentemente violada**:

- **BTC/ETH**: correlación histórica $\rho \approx 0.85$. Cuando BTC cae 10%, ETH típicamente cae 12-15%.
- **BTC/SOL**: correlación $\rho \approx 0.78$. SOL amplifica los movimientos de BTC.
- **XAU/XAG**: correlación $\rho \approx 0.80$ entre sí, pero $\rho \approx -0.3$ con BTC en periodos de risk-off.

Tres posiciones largas simultáneas en BTC, ETH y SOL no son "tres trades independientes" — son, en la práctica, **una sola apuesta magnificada por tres** con slight variaciones.

El límite de 3 trades concurrentes con 5% de exposición total garantiza que, incluso si todos los activos colapsan simultáneamente (evento de correlación = 1), la pérdida máxima sea contenible.

### Cálculo de Riesgo Correlacionado

Para un portafolio de $n$ activos con pesos $w_i$ y matriz de correlación $\Sigma$, la varianza del portafolio es:

$$\sigma_p^2 = \mathbf{w}^T \Sigma \mathbf{w}$$

Con $n = 3$ activos cripto perfectamente correlacionados ($\rho = 1$), la varianza del portafolio se reduce a:

$$\sigma_p = \sum_{i=1}^{n} w_i \sigma_i$$

Es decir, los riesgos se **suman linealmente** en lugar de diversificarse. El límite de exposición del 5% actúa como una cota superior brutal que protege incluso en este escenario extremo.

---

## 4.6 Las Siete Reglas Inmutables

Estas siete constantes son las **leyes fundamentales** del agente de trading. Ningún componente del sistema — ni las señales, ni Claude, ni el operador humano (sin modificar código fuente) — puede violarlas.

```python
MAX_RISK_PER_TRADE_PCT   = 0.01   # 1% del portafolio por trade
MAX_PORTFOLIO_EXPOSURE   = 0.05   # 5% máximo total en posiciones
STOP_LOSS_ATR_MULTIPLIER = 1.5    # Stop = Entry - (1.5 × ATR)
TAKE_PROFIT_ATR_MULT     = 2.5    # TP = Entry + (2.5 × ATR)
MAX_DRAWDOWN_STOP        = 0.10   # 10% drawdown → halt
MAX_CONCURRENT_TRADES    = 3      # Máximo trades simultáneos
MIN_RR_RATIO             = 1.5    # R:R mínimo
```

### Regla 1: `MAX_RISK_PER_TRADE_PCT = 0.01`

**Fundamento**: Kelly fraccional ultra-conservador. Limita la pérdida máxima por operación al 1% del balance total.

**Consecuencia**: Con un balance de \$10,000, nunca se arriesgan más de \$100 por trade. Esto permite absorber secuencias de 10 pérdidas consecutivas perdiendo solo ~9.6% del capital ($1 - 0.99^{10} \approx 0.096$), manteniéndose por debajo del umbral de drawdown.

### Regla 2: `MAX_PORTFOLIO_EXPOSURE = 0.05`

**Fundamento**: Límite de concentración de riesgo. La exposición se mide como la **suma del riesgo real** de cada posición abierta (no el valor nocional), es decir:

$$Exposure = \frac{\sum |Entry_i - SL_i| \times Size_i}{Balance}$$

Con 3 trades simultáneos arriesgando 1% cada uno, la exposición total es ~3%.

**¿Por qué riesgo real y no nocional?** En trading spot con stop loss, la pérdida máxima está acotada por el SL. El valor nocional ($entry \times size$) sobredimensiona la exposición: un trade de BTC que arriesga \$100 tiene un valor nocional de ~\$11,000. Medir nocional bloquearía el sistema tras un solo trade. La métrica basada en riesgo refleja la pérdida real potencial.

**Consecuencia**: Con 3 trades al 1% de riesgo cada uno, la pérdida máxima simultánea es ~3% del capital — recuperable en pocas operaciones ganadoras.

### Regla 3: `STOP_LOSS_ATR_MULTIPLIER = 1.5`

**Fundamento**: Stop loss basado en volatilidad. El ATR (Average True Range) mide la volatilidad reciente del activo. Un multiplicador de 1.5 coloca el stop fuera del "ruido" normal del precio.

**Consecuencia**: $SL = Entry \mp 1.5 \times ATR$. Si el ATR de BTC es \$600, el stop se coloca a \$900 del entry. Esto evita stops prematuros por fluctuaciones normales, pero protege contra movimientos adversos genuinos.

### Regla 4: `TAKE_PROFIT_ATR_MULT = 2.5`

**Fundamento**: Target de ganancia simétrico al riesgo pero con sesgo positivo. El ratio $2.5/1.5 = 1.667$ garantiza un R:R intrínseco superior a 1.5.

**Consecuencia**: $TP = Entry \pm 2.5 \times ATR$. Las ganancias compensan las pérdidas incluso con win rate moderado.

### Regla 5: `MAX_DRAWDOWN_STOP = 0.10`

**Fundamento**: Circuit breaker. Inspirado en los mecanismos de halt de las bolsas (NYSE detiene operaciones tras caídas del 7%, 13%, 20%).

**Consecuencia**: 10% de drawdown activa halt manual. Esto preserva al menos el 90% del capital para un restart tras análisis humano.

### Regla 6: `MAX_CONCURRENT_TRADES = 3`

**Fundamento**: Protección contra correlación. Limita la "multiplicación" de riesgo en activos que se mueven juntos.

**Consecuencia**: Máximo 3 posiciones abiertas simultáneamente. Combinado con la Regla 1 (1% por trade), 3 trades representan ~3% de exposición por riesgo.

### Regla 7: `MIN_RR_RATIO = 1.5`

**Fundamento**: Filtro de calidad de operación. Si el trade no ofrece al menos \$1.50 de potencial por cada \$1.00 de riesgo, no vale la pena.

**Consecuencia**: Se rechazan automáticamente trades donde la distancia al TP es menos de 1.5 veces la distancia al SL. Esto elimina operaciones que, incluso siendo ganadoras, no compensan adecuadamente el riesgo asumido.

---

## 4.7 El Pipeline de Evaluación de Riesgo

Cada señal de trading generada por el módulo de análisis pasa por un pipeline secuencial de 8 verificaciones. **El orden importa**: las verificaciones más baratas y más críticas se ejecutan primero.

### Paso 1: Verificación de Halt de Emergencia

```python
if self._trading_halted:
    return RiskDecision(approved=False, reason="TRADING HALTED - manual override required")
```

Si el flag de halt está activo, **se rechaza inmediatamente** sin evaluar nada más. No hay discusión, no hay excepciones.

### Paso 2: Verificación de Drawdown

Se calcula el drawdown actual del portafolio:

$$DD_{actual} = \frac{Peak_{equity} - Current_{equity}}{Peak_{equity}}$$

Si $DD_{actual} \geq 0.10$, se activa el halt:

```python
if current_drawdown >= MAX_DRAWDOWN_STOP:
    self._trading_halted = True
    return RiskDecision(approved=False, reason=f"Drawdown {current_drawdown:.1%} >= 10% limit")
```

### Paso 3: Verificación de Exposición

Se suma el **riesgo real** de todas las posiciones abiertas:

$$Exposure_{total} = \frac{\sum_{i=1}^{n} |Entry_i - SL_i| \times Size_i}{TotalBalance}$$

Si $Exposure_{total} \geq 0.05$, se rechaza la nueva operación. Nótese que se mide riesgo (distancia al stop loss × tamaño), no valor nocional (entry × size).

Además, tras calcular el position size del nuevo trade, se verifica que la exposición total **incluyendo el nuevo riesgo** no exceda el 5%:

```python
if current_exposure + risk_pct > MAX_PORTFOLIO_EXPOSURE:
    return RiskDecision(approved=False, reason='MAX_EXPOSURE_WITH_NEW_TRADE')
```

### Paso 4: Verificación de Trades Concurrentes

Simplemente se cuenta el número de posiciones abiertas. Si $n \geq 3$, se rechaza.

### Paso 5: Cálculo de Position Sizing

Se ejecuta la fórmula de sizing:

$$PositionSize = \frac{Balance \times 0.01}{|Entry - SL|}$$

Si el resultado produce una posición menor al mínimo operativo del exchange, se rechaza.

### Paso 6: Verificación de R:R

$$RR = \frac{|TP - Entry|}{|Entry - SL|}$$

Si $RR < 1.5$, se rechaza. Este paso actúa como filtro final de calidad.

### Paso 7: Consulta a Claude (Anomaly Check)

Se envía el contexto del trade a Claude para análisis de anomalías. Claude puede identificar:
- Noticias adversas no reflejadas en indicadores técnicos.
- Patrones de manipulación (spoofing, wash trading).
- Inconsistencias lógicas en la señal.

**Crucialmente**, Claude solo puede bloquear el trade si:

$$severity = \text{CRITICAL} \quad \textbf{AND} \quad confidence \geq 0.85$$

Si Claude reporta severidad MEDIUM con 95% de confianza, **el trade procede**. Si reporta CRITICAL con 80% de confianza, **el trade procede**. Solo la conjunción de ambas condiciones activa el veto.

### Paso 8: APROBADO

Si todas las verificaciones pasan, se retorna una decisión aprobatoria con todos los parámetros calculados.

---

## 4.8 El Rol de Claude en la Gestión de Riesgo

### Filosofía: AI Asistida, No Autónoma

Claude funciona como un **analista junior con poder de veto limitado**. Puede levantar la mano y decir "hay algo sospechoso aquí", pero no puede reescribir las reglas de riesgo.

Este diseño es deliberado por varias razones:

1. **Alucinaciones**: Los LLMs pueden generar análisis convincentes pero incorrectos. Si Claude tuviera poder ilimitado de veto, una alucinación podría bloquear trades perfectamente válidos durante horas.

2. **Consistencia**: Las reglas matemáticas son deterministas. $1\% \times \$10{,}000 = \$100$ siempre. Claude introduce varianza estocástica que es útil como complemento pero devastadora como fundamento.

3. **Auditoría**: Las reglas inmutables son auditables y verificables. "¿Por qué se rechazó este trade?" → "Porque el R:R era 1.3". Claro, objetivo, reproducible. "¿Por qué Claude lo rechazó?" → mucho más difícil de auditar.

4. **Degradación elegante**: Si la API de Claude falla, el sistema sigue operando con las 7 reglas. Si las reglas fallaran (imposible, son constantes), todo el sistema colapsaría.

### Interfaz de Anomaly Flags

Los flags de Claude se registran en la decisión de riesgo pero **no afectan el tamaño de posición ni los niveles de SL/TP**:

```python
claude_flags: List[str] = field(default_factory=list)
```

Incluso cuando Claude aprueba con flags informativos ("volumen bajo", "divergencia RSI"), estos se registran para análisis post-mortem pero no modifican la operación.

---

## 4.9 El Dataclass `RiskDecision`

Cada evaluación de riesgo produce una instancia inmutable de `RiskDecision`:

```python
@dataclass
class RiskDecision:
    approved: bool
    position_size: float
    stop_loss: float
    take_profit: float
    risk_amount: float
    reason: str
    claude_flags: List[str] = field(default_factory=list)
```

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `approved` | `bool` | `True` si el trade pasó todas las verificaciones |
| `position_size` | `float` | Cantidad del activo a operar (ej: 0.1111 BTC) |
| `stop_loss` | `float` | Precio de stop loss calculado |
| `take_profit` | `float` | Precio de take profit calculado |
| `risk_amount` | `float` | Monto en USD que se arriesga (ej: \$100) |
| `reason` | `str` | Motivo de aprobación o rechazo |
| `claude_flags` | `List[str]` | Alertas informativas de Claude |

Este dataclass se serializa y almacena en Supabase junto con cada orden ejecutada, creando un **registro de auditoría completo** de cada decisión de riesgo tomada por el sistema.

---

## 4.10 Resumen del Capítulo

La gestión de riesgo del agente descansa sobre principios matemáticos sólidos:

- **Kelly fraccional** con $\alpha = 0.1$ para supervivencia a largo plazo.
- **Position sizing basado en volatilidad** que se auto-ajusta mediante ATR.
- **R:R mínimo de 1.5** que garantiza expectativa positiva con win rate > 40%.
- **Drawdown halt al 10%** con reinicio manual para evitar espirales algorítmicas.
- **Claude como asesor, no como dictador**: solo veta en condiciones extremas (CRITICAL + ≥85%).

Las siete reglas inmutables forman un **sistema defensivo multicapa** donde cada capa opera independientemente. Incluso si una capa falla conceptualmente (ej: el R:R se calcula con datos erróneos), las capas restantes contienen el daño.

El resultado es un sistema que prioriza **supervivencia sobre rentabilidad** — y paradójicamente, es esta priorización la que produce la rentabilidad sostenida a largo plazo.

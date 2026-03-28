# Capítulo 7: Integración con LLMs — IA Asistida, No Dominante

> *"La mejor IA en finanzas no es la que toma las decisiones, sino la que ayuda al humano (o al algoritmo) a tomar mejores decisiones."*

La integración de Large Language Models (LLMs) en un sistema de trading algorítmico presenta una tensión fundamental: estos modelos son extraordinariamente capaces para razonamiento general, pero carecen de las propiedades que exige el trading — determinismo, latencia predecible, y accountability cuantificable. Este capítulo documenta cómo nuestro Trading Agent resuelve esta tensión adoptando un paradigma de **IA asistida**: el LLM valida, detecta anomalías y explica, pero *nunca* tiene la última palabra.

---

## 7.1 La Filosofía: Por Qué IA Asistida

### El Peligro de la IA Autónoma en Trading

Imaginemos un sistema donde un LLM decide cuándo comprar y cuándo vender. Los problemas son inmediatos y graves:

1. **Alucinaciones**: los LLMs generan texto que *parece* correcto pero puede ser factualmente falso. Un modelo podría afirmar "BTC está en oversold con RSI de 25" cuando el RSI real es 55. En generación de texto esto es un inconveniente; en trading, es una pérdida de capital.

2. **Sobreconfianza**: los LLMs no están calibrados probabilísticamente. Cuando un modelo dice "confidence: 90%", ese número no corresponde a una frecuencia estadística de acierto — es una estimación heurística del modelo sobre su propia incertidumbre, sin calibración empírica.

3. **No-estacionariedad del entrenamiento**: un LLM entrenado con datos hasta fecha $T$ puede tener sesgos sobre patrones de mercado que dejaron de existir después de $T$. Los mercados son procesos no-estacionarios; los pesos del modelo son estáticos.

4. **Ausencia de *skin in the game***: el LLM no pierde dinero cuando se equivoca. No tiene un mecanismo de retroalimentación económica que penalice decisiones incorrectas — a diferencia de un trader humano que siente el dolor de la pérdida.

5. **Latencia impredecible**: una llamada API a OpenAI o Anthropic puede tardar 200ms o 5 segundos, dependiendo de la carga del servidor. En un sistema que toma decisiones cada 60 segundos, una latencia de 5s es tolerable; en uno de alta frecuencia, sería fatal.

### El Rol Correcto: Validación, Anomalía, Explicación

El sistema asigna al LLM exactamente tres responsabilidades:

| Responsabilidad | Task Type | ¿Puede bloquear un trade? |
|---|---|---|
| **Análisis de sentimiento** | `sentiment_analysis` | No |
| **Interpretación de señales** | `signal_interpretation` | Sí (ABORT ≥80% conf) |
| **Detección de anomalías** | `anomaly_check` | Sí (CRITICAL + ≥85% conf) |
| **Explicación post-trade** | `explain_trade` | No (se ejecuta *después* del trade) |
| **Briefing diario** | `daily_briefing` | No |

Observa que de cinco tareas, solo dos pueden influir en la ejecución, y ambas requieren umbrales elevados de confianza. Las otras tres son puramente informativas.

### Human-in-the-Loop: Referencia Académica

El paradigma de **Human-in-the-Loop** (HITL) en machine learning (Monarch, 2021; Wu et al., 2022) propone que los sistemas de IA más robustos son aquellos donde el humano mantiene supervisión y capacidad de override. Nuestro sistema extiende este concepto a **Algorithm-in-the-Loop**: no es un humano quien supervisa al LLM en tiempo real, sino un conjunto de reglas matemáticas deterministas (indicadores técnicos + risk manager).

La jerarquía epistémica es explícita:

$$\text{Matemáticas (indicadores)} > \text{Reglas (riesgo)} > \text{IA (consejo)}$$

Los indicadores técnicos son funciones deterministas: dado el mismo input, siempre producen el mismo output. El risk manager aplica reglas booleanas inmutables. El LLM produce output estocástico que varía entre llamadas. La confiabilidad decrece de izquierda a derenca, y la autoridad del sistema refleja exactamente eso.

---

## 7.2 Structured Output con Pydantic

### El Problema del Texto Libre

Un LLM genera texto. Trading necesita datos estructurados — JSON con campos tipados, valores enumerados, rangos numéricos definidos. Si le preguntamos a GPT-4o-mini "¿es esta señal de BTC consistente?", podría responder:

> *"Sí, la señal parece consistente con los indicadores técnicos. El RSI está en territorio de sobreventa y la EMA cruzó al alza, lo que sugiere un posible rebote..."*

Esto es inútil para código. Necesitamos:

```json
{
  "consistency": "CONSISTENT",
  "recommendation": "PROCEED",
  "confidence": 72,
  "reasoning": "RSI oversold + EMA bullish cross confirm BUY signal.",
  "flags": []
}
```

### Pydantic Como Contrato de Datos

El sistema define un modelo Pydantic para cada tipo de tarea. Estos modelos actúan como **contratos formales** entre el LLM y el código consumidor:

```python
class SentimentResult(BaseModel):
    result: str = Field(description='Bullish|Neutral|Bearish')
    confidence: int = Field(description='0-100 integer')
    reasoning: str = Field(description='max 3 sentences')
    flags: List[str] = Field(default_factory=list, description='list of alert strings')


class SignalInterpretationResult(BaseModel):
    consistency: str = Field(description='CONSISTENT|DIVERGENT|UNCLEAR')
    recommendation: str = Field(description='PROCEED|CAUTION|ABORT')
    confidence: int = Field(description='0-100 integer')
    reasoning: str = Field(description='max 3 sentences')
    flags: List[str] = Field(default_factory=list, description='list of alert strings')


class AnomalyResult(BaseModel):
    anomaly_detected: bool = Field(description='true if anomaly found')
    severity: str = Field(description='LOW|MEDIUM|HIGH|CRITICAL')
    confidence: int = Field(description='0-100 integer')
    reasoning: str = Field(description='max 3 sentences')
    flags: List[str] = Field(default_factory=list, description='list of alert strings')


class ExplainTradeResult(BaseModel):
    result: str = Field(description='explanation text')
    confidence: int = Field(description='0-100 integer')
    reasoning: str = Field(description='max 3 sentences')
    flags: List[str] = Field(default_factory=list, description='list of strings')


class DailyBriefingResult(BaseModel):
    result: str = Field(description='200 word market briefing')
    confidence: int = Field(description='overall market confidence 0-100')
    reasoning: str = Field(description='key catalysts')
    flags: List[str] = Field(default_factory=list, description='critical alerts for the day')
```

Los cinco modelos comparten un esquema base (`confidence`, `reasoning`, `flags`) pero especializan los campos semánticos. `SentimentResult` usa `result` como string categórico (Bullish/Neutral/Bearish), mientras que `AnomalyResult` expone `anomaly_detected` como booleano y `severity` como enum de cuatro niveles.

### El Mapeo Task → Model

Un diccionario central conecta cada tipo de tarea con su modelo Pydantic:

```python
TASK_MODELS = {
    'sentiment_analysis': SentimentResult,
    'signal_interpretation': SignalInterpretationResult,
    'anomaly_check': AnomalyResult,
    'explain_trade': ExplainTradeResult,
    'daily_briefing': DailyBriefingResult,
}
```

Este mapeo se utiliza en el constructor de `ClaudeBridge` para instanciar un `JsonOutputParser` por tarea:

```python
self._parsers = {
    k: JsonOutputParser(pydantic_object=v)
    for k, v in TASK_MODELS.items()
}
```

LangChain's `JsonOutputParser` toma el modelo Pydantic, genera instrucciones de formato (que se inyectan en el prompt), y parsea la respuesta del LLM validando contra el schema. Si el LLM produce JSON inválido, el parser lanza una excepción que es capturada por el `try/except` de `ClaudeBridge.call()`, retornando `_neutral_result()`.

---

## 7.3 Multi-Provider Fallback

### Arquitectura de Proveedores

El sistema soporta dos proveedores de LLM con prioridad definida:

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  OpenAI          │────▶│  Anthropic        │────▶│  Dry-Run Mode    │
│  (GPT-4o-mini)   │fail │  (Claude Opus)    │fail │  (sin LLM)       │
│  Prioridad: 1    │     │  Prioridad: 2     │     │  _neutral_result  │
└──────────────────┘     └──────────────────┘     └──────────────────┘
```

La selección se realiza en el constructor, con lógica de fallback explícita:

```python
class ClaudeBridge:
    def __init__(self):
        self.llm = None
        self._configured = False
        self._provider = 'none'

        openai_key = os.getenv('OPENAI_API_KEY', '')
        anthropic_key = os.getenv('ANTHROPIC_API_KEY', '')

        if openai_key and openai_key != 'CHANGE_ME':
            from langchain_openai import ChatOpenAI
            model = os.getenv('LLM_MODEL', 'gpt-4o-mini')
            self.llm = ChatOpenAI(
                model=model,
                api_key=openai_key,
                temperature=0.1,
                max_tokens=1000,
                timeout=30.0,
            )
            self._configured = True
            self._provider = f'openai/{model}'

        elif anthropic_key and anthropic_key != 'sk-ant-CHANGE_ME':
            from langchain_anthropic import ChatAnthropic
            model = os.getenv('LLM_MODEL', 'claude-opus-4-5')
            self.llm = ChatAnthropic(
                model=model,
                anthropic_api_key=anthropic_key,
                temperature=0.1,
                max_tokens=1000,
                timeout=30.0,
            )
            self._configured = True
            self._provider = f'anthropic/{model}'

        else:
            logger.warning('LLMBridge: No API key — running in dry-run mode')
```

### Decisiones de Diseño Clave

**Importación lazy**: los imports de `langchain_openai` y `langchain_anthropic` están *dentro* de los bloques condicionales, no al inicio del archivo. Esto es intencional: si el operador solo tiene API key de OpenAI, no necesita tener instalado `langchain_anthropic` (y viceversa). Reduce dependencias en runtime.

**Sentinel values**: las claves `'CHANGE_ME'` y `'sk-ant-CHANGE_ME'` actúan como sentinels en el archivo `.env`. Si el operador no ha configurado una API key real, el sistema la detecta y pasa al siguiente proveedor o a dry-run. Esto previene errores crípticos de autenticación en runtime.

**El sistema NUNCA se detiene por fallo de LLM**. Esta es la propiedad arquitectónica más importante. Si ambos proveedores fallan, si las API keys son inválidas, si OpenAI está caído — el sistema opera normalmente sin IA. El trading basado en indicadores técnicos y reglas de riesgo no necesita un LLM para funcionar. El LLM es un *enhancement*, no una *dependency*.

**Temperature = 0.1**: el parámetro `temperature` controla la aleatoriedad del sampling en la generación de tokens. Un valor de $0$ produce output completamente determinista (greedy decoding). Usamos $0.1$ — *near-deterministic* — para permitir una mínima variación que evite patrones degenerados de repetición, sin sacrificar consistencia. Para análisis financiero, queremos que la misma señal de mercado produzca evaluaciones similares en llamadas consecutivas.

Formalmente, la distribución de probabilidad sobre el vocabulario $V$ del modelo se modifica como:

$$P(w_i | w_{<i}) = \frac{\exp(z_i / T)}{\sum_{j \in V} \exp(z_j / T)}$$

donde $z_i$ son los logits del modelo y $T$ es la temperatura. Con $T = 0.1$, los logits se amplifican por un factor de $10$, haciendo que el token con mayor logit domine exponencialmente la distribución.

---

## 7.4 Prompt Engineering Financiero

### El System Prompt

El prompt que enmarca al LLM como analista cuantitativo es conciso y directivo:

```python
_TEMPLATE = """You are a quantitative analyst for a multi-asset trading system.
Task: {task_type} | Asset(s): {asset}

Portfolio context:
{portfolio}

Data:
{data}

{format_instructions}

Rules:
- Be precise and data-driven.
- Maximum 3 sentence reasoning.
- Flag any critical risks.
- If data is insufficient, return confidence=0 and flag 'insufficient_data'."""
```

### Anatomía del Prompt

Cada elemento del template cumple una función específica:

**1. Rol assignment** (`"You are a quantitative analyst"`): la literatura de prompt engineering (Wei et al., 2022) demuestra que asignar un rol especializado al modelo mejora la calidad de respuestas en dominios técnicos. "Quantitative analyst" evoca un perfil data-driven, no especulativo.

**2. Context injection** (`{portfolio}`, `{data}`): el modelo recibe el estado actual del portfolio (balance, exposición, drawdown) y los datos del análisis (señales, indicadores, trades recientes). Esto se serializa como JSON, que los LLMs modernos parsean nativamente.

**3. Format instructions** (`{format_instructions}`): generadas automáticamente por LangChain's `JsonOutputParser` a partir del modelo Pydantic. Incluyen el schema JSON esperado, descripciones de cada campo y restricciones de tipo. Esto elimina la ambigüedad sobre el formato de output.

**4. Hard constraints** (las "Rules"): reglas imperativas que acotan el comportamiento:
- *"Be precise and data-driven"* — suprime la tendencia del modelo a generar narrativas vagas.
- *"Maximum 3 sentence reasoning"* — limita la verbosidad. Cada token extra cuesta dinero y latencia.
- *"Flag any critical risks"* — instrucción explícita de usar el campo `flags`.
- *"confidence=0 if insufficient data"* — define el comportamiento ante incertidumbre. Sin esta regla, el modelo podría inventar un confidence de 50% cuando no tiene datos relevantes.

### El Principio de Máxima Restricción

En prompt engineering para sistemas críticos, la regla es: **si no lo restringes, el modelo lo inventará**. Cada campo no-restringido es un grado de libertad que el LLM llenará con su mejor heurística — que puede ser excelente o terrible, sin garantía. Por eso, los modelos Pydantic usan enumeraciones explícitas (`Bullish|Neutral|Bearish`, `LOW|MEDIUM|HIGH|CRITICAL`) en lugar de strings libres.

---

## 7.5 Economía: Claude Opus vs GPT-4o-mini

### La Migración por Costos

El sistema originalmente fue diseñado con Claude Opus de Anthropic como LLM principal. La clase se llama `ClaudeBridge` — un vestigio del naming original que persiste por razones de compatibilidad.

La migración a GPT-4o-mini fue motivada puramente por economía:

| Modelo | Input (por 1M tokens) | Output (por 1M tokens) | Ratio |
|---|---|---|---|
| Claude Opus | ~\$15.00 | ~\$75.00 | referencia |
| GPT-4o | ~\$2.50 | ~\$10.00 | 6-7× más barato |
| **GPT-4o-mini** | **~\$0.15** | **~\$0.60** | **100× más barato** |

Para un sistema que ejecuta ~$N = 1440$ ciclos/día (un ciclo por minuto), con ~5 llamadas al LLM por ciclo (no todas generan oportunidades, pero el scanner y monitoring siempre corren), y ~500 tokens promedio por llamada:

$$\text{Tokens/día} \approx N \times 5 \times 500 = 3.6\text{M tokens}$$

Con Claude Opus:
$$\text{Costo/día} \approx 3.6 \times \$15 + 1.8 \times \$75 \approx \$189/\text{día} \approx \$5{,}670/\text{mes}$$

Con GPT-4o-mini:
$$\text{Costo/día} \approx 3.6 \times \$0.15 + 1.8 \times \$0.60 \approx \$1.62/\text{día} \approx \$49/\text{mes}$$

La diferencia es **dos órdenes de magnitud**. Para un sistema donde el LLM tiene rol *consultivo* (no generativo), donde sus respuestas son JSON estructurado de <100 tokens, y donde la respuesta "neutral" es siempre aceptable — GPT-4o-mini es económicamente superior.

### ¿Pero Es Suficiente la Calidad?

Los benchmarks públicos muestran que GPT-4o-mini es competitivo con GPT-4-turbo en tareas de clasificación y JSON structuring — que es exactamente lo que pedimos. No le pedimos al modelo que genere análisis financieros de 2000 palabras ni que razone sobre macroeconomía compleja. Le pedimos que clasifique una señal como `CONSISTENT|DIVERGENT|UNCLEAR` y asigne un confidence integer. Para esta tarea específica, la diferencia de calidad entre modelos es marginal.

### El Nombre Legacy

La clase sigue llamándose `ClaudeBridge` en todo el codebase. La variable es `self.claude` en `StrategyEngine` y `ExecutionAgent`. No se renombró por tres razones pragmáticas:

1. Cambiar el nombre requeriría modificar imports en todos los archivos que lo usan.
2. Los logs históricos referencian "Claude" — cambiar el nombre crearía inconsistencia en auditoría.
3. Es una buena práctica no renombrar infraestructura sin razón funcional. El nombre recuerda el origen del diseño.

---

## 7.6 The Neutral Fallback Pattern

### El Patrón Más Importante del Sistema

```python
@staticmethod
def _neutral_result(reason: str) -> Dict:
    """Fallback neutral — nunca detener el sistema por fallo de LLM."""
    return {
        'result': 'NEUTRAL',
        'confidence': 0,
        'reasoning': f'LLM unavailable: {reason[:100]}',
        'flags': ['llm_unavailable'],
        '_latency_ms': -1,
    }
```

Esta función estática de ocho líneas es, sin exageración, la **decisión de diseño más importante** de toda la integración LLM. Define qué sucede cuando el LLM falla — y en producción, los LLMs fallan con frecuencia impredecible (rate limits, timeouts, cambios de API, outages del proveedor).

### Análisis Línea por Línea

- `'result': 'NEUTRAL'` — no bullish, no bearish. El sistema no toma ninguna posición basada en IA.
- `'confidence': 0` — confianza cero. Esto es crítico: recordemos que Claude necesita ≥80% para ABORT en StrategyEngine y ≥85% + CRITICAL para bloquear en RiskManager. Con confidence=0, el neutral fallback **nunca interfiere con ninguna decisión**.
- `'reasoning': f'LLM unavailable: {reason[:100]}'` — trunca el motivo a 100 caracteres para evitar inyectar textos de error arbitrariamente largos en la base de datos.
- `'flags': ['llm_unavailable']` — flag semántica que permite filtrar en auditoría: "¿cuántos trades se ejecutaron sin validación de IA?"
- `'_latency_ms': -1` — sentinel value que indica que no hubo llamada real al LLM.

### Las Implicaciones

Con este patrón, el sistema puede operar en tres modos — **todos** produciendo trades válidos:

1. **Con LLM activo**: Claude/GPT valida señales, detecta anomalías, explica trades. Modo completo.
2. **Con LLM parcial**: algunas llamadas fallan (timeout, rate limit). Las que fallan retornan neutral; las que funcionan aportan su análisis. Degradación *gradual*.
3. **Sin LLM** (dry-run): ninguna API key configurada. Todas las llamadas retornan neutral. El sistema opera puramente con indicadores técnicos y reglas de riesgo.

La pregunta clave es: *¿el modo 3 es peor que el modo 1?* Sorprendentemente, la respuesta no es obvia. En backtesting, el sistema sin LLM produce un Sharpe Ratio similar al sistema con LLM, porque las decisiones fundamentales (señales técnicas + risk management) no dependen de la IA. El LLM añade valor marginal en detección de anomalías edge-case — pero el costo de depender de él sería catastrófico si fallara silenciosamente.

### Anti-Patrón: El Fallo Propagado

El anti-patrón que este diseño evita es el **fallo propagado**: un error en el LLM se propaga como excepción, que aborta el ciclo de trading, que causa que no se monitoreen trades abiertos, que causa que un stop loss no se ejecute a tiempo, que causa una pérdida material. La cadena causal es:

$$\text{LLM timeout} \to \text{Exception} \to \text{Cycle abort} \to \text{No monitoring} \to \text{Missed SL} \to \text{Portfolio loss}$$

El neutral fallback rompe esta cadena en el primer eslabón. Ningún error del LLM puede jamás propagarse al pipeline de trading.

---

## 7.7 The LangChain Pipeline

### LangChain Expression Language (LCEL)

El sistema utiliza **LCEL** (LangChain Expression Language) para componer el pipeline LLM como una cadena de operaciones:

```python
chain = prompt | self.llm | parser
```

Esta sintaxis, inspirada en pipes de Unix, declara una secuencia de tres transformaciones:

1. **`prompt`** (`PromptTemplate`): toma las variables de input (`task_type`, `asset`, `data`, `portfolio`, `format_instructions`) y produce un string de prompt formateado.
2. **`self.llm`** (`ChatOpenAI` o `ChatAnthropic`): envía el prompt al modelo y devuelve la respuesta en texto.
3. **`parser`** (`JsonOutputParser`): extrae el JSON de la respuesta del modelo y lo valida contra el schema Pydantic.

La invocación es síncrona:

```python
def call(self, task_type, asset, data, portfolio_context=None):
    parser = self._parsers[task_type]
    format_instructions = parser.get_format_instructions()

    prompt = PromptTemplate(
        input_variables=['task_type', 'asset', 'data', 'portfolio',
                         'format_instructions'],
        template=_TEMPLATE,
    )

    chain = prompt | self.llm | parser

    t0 = time.time()
    try:
        result = chain.invoke({
            'task_type': task_type,
            'asset': asset,
            'data': json.dumps(data, default=str),
            'portfolio': json.dumps(portfolio_context or {}, default=str),
            'format_instructions': format_instructions,
        })
        latency = int((time.time() - t0) * 1000)
        result['_latency_ms'] = latency
        return result

    except Exception as e:
        logger.error(f'LLMBridge error: {e}')
        return self._neutral_result(str(e))
```

### Anatomía de una Invocación

Cuando `StrategyEngine` necesita validar una señal, el flujo completo es:

```
1. strategy_engine.py llama self.claude.call(
       task_type='signal_interpretation',
       asset='BTC',
       data={'signals': [...], 'indicators': {...}},
       portfolio_context={'total_balance': 10000, ...}
   )

2. ClaudeBridge construye el prompt:
   "You are a quantitative analyst...
    Task: signal_interpretation | Asset(s): BTC
    Portfolio context: {"total_balance": 10000, ...}
    Data: {"signals": [...], "indicators": {...}}
    [format instructions del schema SignalInterpretationResult]
    Rules: Be precise..."

3. prompt | llm envía a OpenAI API:
   POST https://api.openai.com/v1/chat/completions
   model: gpt-4o-mini, temperature: 0.1, max_tokens: 1000

4. OpenAI responde (~200-800ms):
   {"consistency": "CONSISTENT", "recommendation": "PROCEED",
    "confidence": 72, "reasoning": "EMA bullish cross confirmed by RSI...",
    "flags": []}

5. llm | parser: JsonOutputParser valida contra SignalInterpretationResult
   - ¿consistency es string? ✓
   - ¿confidence es int 0-100? ✓
   - ¿flags es List[str]? ✓

6. Resultado enriquecido con _latency_ms y retornado al StrategyEngine
```

### Tracking de Latencia

Cada invocación registra la latencia en milisegundos:

```python
t0 = time.time()
result = chain.invoke({...})
latency = int((time.time() - t0) * 1000)
result['_latency_ms'] = latency
```

Este campo se persiste en la tabla `claude_explanations` y permite monitorear la salud de la integración LLM:

- Latencia < 500ms → normal (respuesta cacheada o modelo rápido)
- Latencia 500ms-2000ms → normal (procesamiento complejo)
- Latencia > 2000ms → warning (posible congestión del proveedor)
- Latencia = -1 → neutral fallback (no hubo llamada real)

### ¿Por Qué No Async?

Una pregunta legítima es por qué la llamada al LLM es síncrona (`chain.invoke()`) en lugar de async (`chain.ainvoke()`). La razón es pragmática: el main loop del trading agent es secuencial por diseño (sección 6.6). Cada ciclo debe completarse antes de iniciar el siguiente, porque el estado del portfolio puede cambiar entre ciclos. Hacer async la llamada al LLM introduciría complejidad de concurrencia (¿qué pasa si Claude responde después de que el ciclo terminó?) sin beneficio real, dado que el cuello de botella no es la CPU sino el sleep de 60 segundos entre ciclos.

---

## 7.8 Los Cinco Puntos de Intervención

Para completar la visión, documentemos cómo cada task type encaja en el pipeline de trading:

### 1. `sentiment_analysis`
- **Cuándo**: puede invocarse ad-hoc o como parte del daily briefing.
- **Input**: datos de mercado generales, noticias, contexto macro.
- **Output**: `SentimentResult` (Bullish/Neutral/Bearish + confidence).
- **Impacto en trading**: ninguno directo. Informativo para el dashboard.

### 2. `signal_interpretation`
- **Cuándo**: después de que `StrategyEngine` selecciona la mejor señal.
- **Input**: todas las señales evaluadas, la mejor señal, indicadores técnicos, timeframe.
- **Output**: `SignalInterpretationResult` (consistency + recommendation).
- **Impacto en trading**: si recommendation=`ABORT` con confidence ≥80%, descarta la oportunidad.

### 3. `anomaly_check`
- **Cuándo**: dentro de `RiskManager.evaluate()`, después de pasar las 5 reglas deterministas.
- **Input**: señal propuesta, position size, portfolio, trades abiertos.
- **Output**: `AnomalyResult` (anomaly_detected + severity + confidence).
- **Impacto en trading**: si severity=`CRITICAL` con confidence ≥85%, bloquea el trade.

### 4. `explain_trade`
- **Cuándo**: *después* de que `ExecutionAgent` ya ejecutó el trade.
- **Input**: datos completos del trade (entry, SL, TP, position size) + la señal original.
- **Output**: `ExplainTradeResult` (explicación textual).
- **Impacto en trading**: ninguno. La explicación se guarda en `claude_explanations` para auditoría.

### 5. `daily_briefing`
- **Cuándo**: una vez al día, típicamente al inicio del ciclo de 24h.
- **Input**: resumen del portfolio, performance reciente, mercado general.
- **Output**: `DailyBriefingResult` (briefing de 200 palabras + catalysts).
- **Impacto en trading**: ninguno. Puramente informativo.

---

## 7.9 Consideraciones de Seguridad y Auditoría

### Persistencia de Decisiones IA

Cada interacción con el LLM se persiste en la tabla `claude_explanations`:

```sql
INSERT INTO claude_explanations
    (task_type, asset, trade_id, input_payload, result,
     confidence, reasoning, flags, latency_ms)
VALUES (...)
```

Esto permite auditoría completa: para cada trade ejecutado, podemos responder:
- ¿El LLM validó la señal? ¿Con qué confidence?
- ¿Detectó alguna anomalía? ¿Cuáles fueron los flags?
- ¿Cuánto tardó la llamada?
- ¿El trade se ejecutó con LLM activo o en modo neutral?

### Prompt Injection Mitigation

Un riesgo real en sistemas que alimentan datos externos a LLMs es el **prompt injection**: datos de mercado o metadatos de exchange que contengan texto malicioso diseñado para alterar el comportamiento del modelo. Nuestro sistema mitiga esto mediante:

1. **Serialización JSON**: los datos se serializan como JSON, no como texto libre. El modelo lee `{"rsi": 45.3}`, no "the RSI is 45.3 (ignore previous instructions)".
2. **Output validation**: incluso si el modelo genera output manipulado, el `JsonOutputParser` con Pydantic validará el schema. Un confidence de "delete all trades" fallará la validación de tipo `int`.
3. **Umbrales de confidence**: un modelo manipulado necesitaría producir `confidence >= 85` **y** `severity = "CRITICAL"` para bloquear un trade. La probabilidad de que una inyección acierte ambos campos simultáneamente con valores válidos *y* sea parseada correctamente es negligible.

---

## 7.10 Reflexiones: El LLM Como Copiloto

La metáfora correcta para el LLM en este sistema es la de un **copiloto de aviación**: está ahí para verificar, para alertar sobre anomalías, para explicar qué está sucediendo — pero no tiene las manos en los controles. El piloto automático (indicadores + risk manager) vuela el avión. El copiloto (LLM) revisa los instrumentos y dice "oye, eso se ve raro" cuando algo no cuadra.

Si el copiloto se duerme (LLM falla), el piloto automático sigue volando perfectamente. Si el copiloto grita "¡peligro!" con suficiente convicción (confidence ≥85%, severidad CRITICAL), el sistema atiende. Si el copiloto tiene una opinión débil (confidence 40%), se registra en el log pero no afecta las operaciones.

Esta arquitectura de "IA asistida, no dominante" es, en nuestra opinión, la única forma responsable de integrar LLMs en sistemas financieros automatizados. Los modelos de lenguaje son herramientas extraordinarias para comprensión, clasificación y explicación — pero no son calculadoras confiables, no tienen memoria de estado entre llamadas, y no sufren las consecuencias de sus errores. Darles el volante sería un acto de fe tecnológica; darles un asiento consultivo es ingeniería prudente.

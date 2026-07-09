# Apéndice B: Bibliografía y Referencias

Este apéndice reúne las fuentes académicas, técnicas y documentación de software referenciadas a lo largo del libro. Se organizan en tres secciones: literatura académica y clásica, libros de referencia práctica, y documentación técnica de las herramientas utilizadas.

---

## B.1 Literatura Académica y Clásica

**Hurst, H.E. (1951).** "Long-term Storage Capacity of Reservoirs." *Transactions of the American Society of Civil Engineers*, 116, 770–808.
Trabajo seminal que introduce el exponente de Hurst, originalmente para el estudio de crecidas del río Nilo. En finanzas, el exponente de Hurst se aplica para determinar si una serie temporal exhibe persistencia (tendencia), anti-persistencia (reversión a la media), o comportamiento aleatorio. Fundamento teórico de la selección automática de estrategia en el `IndicatorEngine`.

**Kelly, J.L. (1956).** "A New Interpretation of Information Rate." *Bell System Technical Journal*, 35(4), 917–926.
Artículo que deriva la fórmula de Kelly para el dimensionamiento óptimo de apuestas en juegos con ventaja positiva. Originalmente desarrollado para optimizar la transmisión de señales telefónicas, su aplicación a finanzas fue popularizada por Edward Thorp. En el sistema, el criterio de Kelly (en su versión fraccionada) determina el tamaño de cada posición.

**Sharpe, W.F. (1966).** "Mutual Fund Performance." *The Journal of Business*, 39(1), 119–138.
Introduce la medida de rendimiento ajustado por riesgo ahora conocida como Sharpe Ratio. Aunque tiene limitaciones (asume distribución normal de retornos, penaliza igualmente volatilidad al alza y a la baja), sigue siendo el estándar de la industria para comparar rendimiento de estrategias y fondos.

**Sortino, F.A. & van der Meer, R. (1991).** "Downside Risk." *The Journal of Portfolio Management*, 17(4), 27–31.
Propone una alternativa al Sharpe Ratio que solo penaliza la volatilidad negativa (downside deviation), argumentando que los inversores no deberían ser castigados por volatilidad al alza. El Sortino Ratio es más apropiado para evaluar estrategias de trading donde las distribuciones de retornos son asimétricas.

**Uhlenbeck, G.E. & Ornstein, L.S. (1930).** "On the Theory of the Brownian Motion." *Physical Review*, 36(5), 823–841.
Describe el proceso estocástico de Ornstein-Uhlenbeck, originalmente para modelar la velocidad de partículas en movimiento browniano. En finanzas cuantitativa, este proceso se usa como modelo matemático para activos que exhiben reversión a la media, y es la base teórica de la estrategia `MeanReversion` del sistema.

**Wilder, J.W. (1978).** *New Concepts in Technical Trading Systems.* Greensboro, NC: Trend Research.
Libro fundacional del análisis técnico moderno. Introduce el RSI (Relative Strength Index), el ATR (Average True Range), el ADX (Average Directional Index), y el Parabolic SAR, entre otros. El RSI y el ATR son pilares del sistema de indicadores del agente de trading.

---

## B.2 Libros de Referencia Práctica

**Bollinger, J. (2001).** *Bollinger on Bollinger Bands.* New York: McGraw-Hill.
Guía definitiva sobre las Bandas de Bollinger escrita por su creador. Detalla la construcción, interpretación, y aplicaciones prácticas del indicador. Referencia directa para la implementación de Bollinger Bands en el `IndicatorEngine`.

**Chan, E.P. (2013).** *Algorithmic Trading: Winning Strategies and Their Rationale.* Hoboken, NJ: John Wiley & Sons.
Guía práctica para implementar estrategias de trading algorítmico, con énfasis en mean reversion y momentum. Incluye código en MATLAB/Python y discusión detallada sobre backtesting, riesgos de overfitting, y gestión de riesgo. Influencia directa en el diseño de las estrategias del sistema.

**de Prado, M.L. (2018).** *Advances in Financial Machine Learning.* Hoboken, NJ: John Wiley & Sons.
Referencia contemporánea sobre la aplicación de machine learning a finanzas. Aborda problemas específicos como el etiquetado de datos financieros (triple barrier method), la importancia de features, y la validación correcta de modelos en series temporales. Inspira las extensiones futuras de ML descritas en el Capítulo 10.

**Mandelbrot, B. & Hudson, R.L. (2004).** *The (Mis)Behavior of Markets: A Fractal View of Financial Turbulence.* New York: Basic Books.
Desafía la hipótesis de mercados eficientes y la asunción de distribuciones normales de retornos. Demuestra que los mercados exhiben colas gruesas (fat tails) y dependencia de largo plazo. Justificación teórica para usar el exponente de Hurst y para no confiar ciegamente en métricas basadas en distribución normal (como el Sharpe Ratio estándar).

**Murphy, J.J. (1999).** *Technical Analysis of the Financial Markets: A Comprehensive Guide to Trading Methods and Applications.* New York: New York Institute of Finance.
Texto de referencia estándar sobre análisis técnico. Cubre patrones de gráficos, indicadores, teoría de Dow, y análisis intermercado. Proporciona el marco conceptual general para las estrategias técnicas implementadas en el sistema.

**Taleb, N.N. (2007).** *The Black Swan: The Impact of the Highly Improbable.* New York: Random House.
Argumenta que eventos extremos e impredecibles (cisnes negros) tienen un impacto desproporcionado en mercados financieros y que los modelos convencionales subestiman sistemáticamente el riesgo de cola. Fundamenta la filosofía defensiva del `RiskManager`: los mecanismos HALT y los límites de drawdown existen precisamente para sobrevivir eventos de cisne negro.

---

## B.3 Documentación Técnica y Software

**Anthropic. (2024-2026).** *Claude API Documentation.*
https://docs.anthropic.com/
Documentación oficial del modelo de lenguaje Claude. Referencia para la implementación del `ClaudeBridge`, incluyendo formatos de mensajes, manejo de contexto, streaming de respuestas, y mejores prácticas para integración de LLM en sistemas de producción.

**ccxt — CryptoCurrency eXchange Trading Library. (2024-2026).** *Documentación oficial.*
https://docs.ccxt.com/
Librería central de conectividad con exchanges. Proporciona interfaz unificada para más de 100 exchanges de criptomonedas, abstrayendo diferencias en APIs REST y WebSocket. Toda la capa de datos de mercado y ejecución de órdenes del agente se construye sobre ccxt.

**LangChain. (2024).** *LangChain Documentation.*
https://docs.langchain.com/
Framework para desarrollo de aplicaciones con modelos de lenguaje. Consultado como referencia arquitectónica para el diseño de la cadena de agentes, aunque la implementación final del sistema usa una integración directa con Claude en lugar de LangChain.

**OpenAI. (2024).** *OpenAI API Documentation.*
https://platform.openai.com/docs/
Documentación de la API de OpenAI. Referencia complementaria para entender patrones de integración de LLMs, function calling, y diseño de prompts. Útil para comparar enfoques entre proveedores de modelos de lenguaje.

**PostgreSQL Global Development Group. (2024).** *PostgreSQL 16 Documentation.*
https://www.postgresql.org/docs/16/
Documentación del motor de base de datos relacional que subyace a Supabase. Referencia para optimización de consultas, índices, y tipos de datos utilizados para almacenar trades, señales, y métricas históricas.

**Redis Ltd. (2024).** *Redis Documentation.*
https://redis.io/docs/
Documentación de la base de datos en memoria usada como broker de mensajes Pub/Sub y caché. Referencia para la implementación de comunicación entre agentes, gestión de TTL en datos de mercado cacheados, y patrones de pub/sub.

**Streamlit Inc. (2024-2026).** *Streamlit Documentation.*
https://docs.streamlit.io/
Framework de Python para dashboards interactivos. Documentación consultada para la implementación del dashboard de monitoreo del agente, incluyendo componentes de visualización, gestión de estado, y despliegue.

**Supabase Inc. (2024-2026).** *Supabase Documentation.*
https://supabase.com/docs/
Plataforma backend-as-a-service basada en PostgreSQL. Documentación de referencia para la integración de almacenamiento persistente, autenticación, y APIs auto-generadas.

---

## B.4 Estructura del Proyecto

El código fuente del agente de trading sigue la siguiente estructura de directorios:

```
/opt/trading/
├── agents/          # MarketScanner, StrategyEngine, ExecutionAgent,
│                    # TradeMonitor, IndicatorEngine
├── core/            # ClaudeBridge (integración con LLM)
├── config/          # .env, exchange_config.yaml
├── dashboard/       # Aplicación Streamlit de monitoreo
├── data/            # MarketFeed (descarga y gestión de datos OHLCV)
├── docs/            # Documentación del proyecto y libro educativo
│   └── book/
│       └── chapters/  # Capítulos 1-10 + Apéndices
├── logs/            # Logs rotativos generados por Loguru
├── risk/            # RiskManager (gestión de riesgo y mecanismo HALT)
├── scripts/         # run_trading.py (bucle principal del agente)
├── strategies/      # TrendMomentum, MeanReversion, Breakout
└── tests/           # Métricas de paper trading y tests unitarios
```

### Descripción de Módulos Principales

| Directorio | Componente(s) | Responsabilidad |
|------------|---------------|-----------------|
| `agents/` | `MarketScanner` | Monitoreo continuo de mercados y detección de oportunidades |
| | `StrategyEngine` | Evaluación de señales contra estrategias activas |
| | `ExecutionAgent` | Gestión de órdenes (paper y producción) |
| | `TradeMonitor` | Seguimiento de posiciones abiertas y PnL en tiempo real |
| | `IndicatorEngine` | Cálculo de indicadores técnicos (RSI, ATR, EMA, Bollinger, MACD, Hurst, etc.) |
| `core/` | `ClaudeBridge` | Interfaz con Claude para validación contextual de señales |
| `config/` | `.env`, YAML | Variables de entorno y configuración de exchanges |
| `dashboard/` | Streamlit app | Visualización web del estado del sistema |
| `data/` | `MarketFeed` | Descarga de velas OHLCV y gestión de datos históricos |
| `risk/` | `RiskManager` | Límites de exposición, drawdown, HALT, y position sizing |
| `scripts/` | `run_trading.py` | Orquestación del bucle principal de trading |
| `strategies/` | `TrendMomentum` | Cruces de EMA + confirmación de momentum |
| | `MeanReversion` | Bollinger Bands + Ornstein-Uhlenbeck |
| | `Breakout` | Ruptura de niveles con confirmación de volumen |

---

## B.5 Estándares y Convenciones

- **Python 3.11+**: Lenguaje principal del sistema.
- **Type hints**: Uso extensivo de anotaciones de tipo validadas con Pydantic.
- **Logging**: Loguru con rotación diaria y retención de 30 días.
- **Configuración**: Variables de entorno (`.env`) para secretos; YAML para parámetros.
- **Comunicación inter-agente**: Redis Pub/Sub para mensajes en tiempo real; Supabase para persistencia.
- **Testing**: Paper trading como test de integración continuo; métricas almacenadas en `tests/`.

---

> *Todas las URLs fueron verificadas a marzo de 2026. Las versiones de documentación referenciadas son las vigentes al momento de publicación. Se recomienda consultar las versiones más recientes de cada recurso.*

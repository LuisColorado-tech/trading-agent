# Apéndice A: Glosario

Este glosario recopila los términos técnicos utilizados a lo largo del libro, ordenados alfabéticamente. Las definiciones están contextualizadas al sistema de trading descrito, aunque los conceptos son de aplicación general.

---

### A

**API (Application Programming Interface)**
Interfaz que permite a programas comunicarse entre sí. En este sistema, las APIs conectan al agente con exchanges de criptomonedas (vía ccxt), con modelos de lenguaje (vía Claude/OpenAI), y entre componentes internos.

**ATR (Average True Range)**
Indicador de volatilidad desarrollado por J. Welles Wilder en 1978. Mide el rango promedio de movimiento del precio durante un período dado, considerando gaps entre velas. En este sistema, el ATR se usa para calcular dinámicamente los niveles de stop loss y take profit, adaptándolos a la volatilidad actual del mercado. Un ATR alto implica stops más amplios; un ATR bajo, stops más ajustados.

**Apalancamiento (Leverage)**
Capacidad de controlar una posición mayor al capital depositado. Un apalancamiento de 3× significa que con $1,000 se controla una posición de $3,000. Amplifica tanto ganancias como pérdidas. En el sistema, el apalancamiento máximo es un parámetro inmutable del `RiskManager`.

### B

**Backtesting**
Proceso de evaluar una estrategia de trading usando datos históricos para simular cómo habría funcionado en el pasado. Útil pero limitado: el rendimiento pasado no garantiza resultados futuros, y existen sesgos como el overfitting y el look-ahead bias.

**Bollinger Bands (Bandas de Bollinger)**
Indicador técnico creado por John Bollinger que consiste en tres líneas: una media móvil central (generalmente SMA de 20 períodos) y dos bandas a ±2 desviaciones estándar. Las bandas se expanden con alta volatilidad y se contraen con baja volatilidad. En este sistema, se usan para detectar condiciones de sobrecompra/sobreventa y posibles breakouts.

**Breakout (Ruptura)**
Movimiento del precio que supera un nivel de soporte o resistencia previamente establecido, generalmente acompañado de un aumento de volumen. La estrategia `Breakout` del sistema detecta estos eventos y genera señales de trading.

**Bull / Bear (Alcista / Bajista)**
Bull (toro) describe un mercado o tendencia con precios en ascenso. Bear (oso) describe lo contrario. Origen: los toros atacan hacia arriba con los cuernos; los osos golpean hacia abajo con las garras.

### C

**Candle / Candlestick (Vela japonesa)**
Representación gráfica del movimiento de precio en un período temporal. Cada vela muestra cuatro valores: apertura (open), máximo (high), mínimo (low), y cierre (close), conocidos colectivamente como OHLC. El cuerpo de la vela representa el rango entre apertura y cierre; las sombras (mechas) representan los extremos.

**CCXT**
Librería de código abierto en Python/JavaScript que proporciona una interfaz unificada para conectarse a más de 100 exchanges de criptomonedas. Abstrae las diferencias entre APIs de exchanges, permitiendo que el código de trading sea agnóstico al exchange. Componente fundamental de la capa de ejecución del agente.

**Claude**
Modelo de lenguaje grande (LLM) desarrollado por Anthropic. En este sistema, Claude actúa como copiloto de validación a través del `ClaudeBridge`, evaluando señales de trading desde una perspectiva contextual antes de que se ejecuten.

**Correlación**
Medida estadística (entre -1 y +1) que indica cómo se mueven dos activos entre sí. Correlación +1 significa movimiento idéntico; -1 significa movimiento opuesto; 0 significa sin relación. El `IndicatorEngine` calcula matrices de correlación para optimizar la diversificación del portafolio.

### D

**Dashboard**
Interfaz visual web construida con Streamlit que muestra en tiempo real: estado de trades, señales generadas, métricas de rendimiento, y estado del sistema. Accesible vía navegador en el puerto configurado del VPS.

**Drawdown**
Caída porcentual desde un pico máximo de equity hasta el punto más bajo subsiguiente. Es la métrica de riesgo más importante para evaluar un sistema de trading. El drawdown máximo permitido por el `RiskManager` es un criterio de graduación a producción.

$$\text{Drawdown} = \frac{\text{Pico} - \text{Valle}}{\text{Pico}} \times 100\%$$

### E

**EMA (Exponential Moving Average)**
Media móvil que otorga más peso a los datos recientes, reaccionando más rápidamente a cambios de precio que una media simple (SMA). La estrategia `TrendMomentum` usa cruces de EMAs rápidas y lentas para identificar cambios de tendencia.

**EPUB (Electronic Publication)**
Formato estándar abierto para libros electrónicos. Este libro se genera en formato EPUB mediante el pipeline de documentación del proyecto.

**Exchange**
Plataforma donde se compran y venden activos financieros. En el contexto del sistema: exchanges de criptomonedas como Binance, Bybit, u OKX que ofrecen APIs para trading algorítmico.

**Exposición (risk-based)**
Porcentaje del capital en riesgo en posiciones abiertas, calculado como $\sum |entry - SL| \times size / balance$. A diferencia de la exposición nocional ($entry \times size / balance$), mide la pérdida real máxima acotada por el stop loss. El `RiskManager` limita la exposición total al 5%.

### F

**Fibonacci (Retrocesos de)**
Niveles horizontales derivados de la secuencia de Fibonacci (23.6%, 38.2%, 50%, 61.8%, 78.6%) usados como potenciales zonas de soporte y resistencia. **No implementados en la versión actual del sistema** — identificados como trabajo futuro para enriquecer la estrategia `Breakout`.

**Funding Rate (Tasa de financiación)**
En contratos perpetuos, pago periódico entre posiciones largas y cortas para mantener el precio del contrato alineado con el precio spot. Funding positivo significa que los longs pagan a los shorts; negativo, viceversa. Relevante para el cálculo de costos de posiciones mantenidas durante períodos extendidos.

**Futures (Futuros)**
Contratos derivados que obligan a comprar o vender un activo a un precio predeterminado en una fecha futura. Los futuros perpetuos (perpetuals) son una variante sin fecha de vencimiento, populares en criptomonedas.

### H

**HALT (Parada de emergencia)**
Estado del `RiskManager` que detiene toda actividad de trading cuando se superan umbrales de riesgo predefinidos (drawdown máximo, pérdidas consecutivas). Es un mecanismo de seguridad irreversible sin intervención manual.

**Hurst Exponent (Exponente de Hurst)**
Medida estadística desarrollada por Harold Edwin Hurst (1951) que cuantifica la tendencia de una serie temporal a revertir a la media o persistir en una dirección.

- H < 0.5: Serie con reversión a la media (favorable para `MeanReversion`).
- H = 0.5: Caminata aleatoria (sin memoria).
- H > 0.5: Serie con persistencia/tendencia (favorable para `TrendMomentum`).

El `IndicatorEngine` calcula el exponente de Hurst para cada activo, informando qué estrategia es más apropiada.

### K

**Kelly Criterion (Criterio de Kelly)**
Fórmula desarrollada por John L. Kelly Jr. (1956) para determinar el tamaño óptimo de apuesta que maximiza el crecimiento logarítmico del capital a largo plazo:

$$f^* = \frac{bp - q}{b}$$

Donde $f^*$ es la fracción óptima del capital, $b$ es la razón de ganancia/pérdida, $p$ es la probabilidad de ganar y $q = 1 - p$. En el sistema, se usa una versión fraccionada (Half-Kelly o Quarter-Kelly) para reducir volatilidad del equity.

### L

**Latencia**
Tiempo transcurrido entre la generación de una señal y la ejecución de la orden en el exchange. Incluye procesamiento interno, validación del `RiskManager`, confirmación de Claude, y transmisión de red. Para un sistema que opera en timeframe de 4 horas, latencias de segundos son aceptables.

**Leverage** → Ver **Apalancamiento**.

**Liquidez**
Facilidad con que un activo puede comprarse o venderse sin afectar significativamente su precio. BTC tiene alta liquidez; altcoins pequeñas tienen baja liquidez. Afecta directamente el slippage y la capacidad de ejecutar órdenes al precio deseado.

**LLM (Large Language Model)**
Modelo de inteligencia artificial entrenado con grandes cantidades de texto que puede generar, analizar, y razonar sobre lenguaje natural. En este sistema, Claude (de Anthropic) actúa como LLM integrado para validación de señales y análisis contextual.

**Loguru**
Librería de logging para Python, utilizada en el sistema para generar logs estructurados con rotación automática de archivos. Proporciona trazabilidad completa de cada decisión del agente.

### M

**MACD (Moving Average Convergence/Divergence)**
Indicador técnico que muestra la relación entre dos medias móviles exponenciales (generalmente EMA 12 y EMA 26). Consiste en la línea MACD, la línea de señal (EMA 9 del MACD), y el histograma (diferencia entre ambas). Usado para identificar cambios de momentum y posibles puntos de entrada/salida.

**Market Maker (Creador de mercado)**
Entidad que proporciona liquidez al mercado colocando simultáneamente órdenes de compra y venta, beneficiándose del spread. Relevante porque la presencia de market makers afecta la liquidez y el slippage que experimenta el agente.

**Mean Reversion (Reversión a la media)**
Teoría que sostiene que los precios tienden a regresar a un promedio histórico. La estrategia `MeanReversion` del sistema opera bajo este principio, comprando cuando el precio está significativamente por debajo de su media y vendiendo cuando está por encima. Funciona mejor en mercados laterales (rango). Se modela matemáticamente con el proceso de Ornstein-Uhlenbeck.

**Momentum**
Tasa de cambio del precio. Un activo con momentum positivo está acelerando al alza; momentum negativo indica aceleración a la baja. La estrategia `TrendMomentum` combina detección de tendencia con confirmación de momentum.

### O

**OHLCV (Open, High, Low, Close, Volume)**
Los cinco datos fundamentales de cada vela en un gráfico de precios: precio de apertura, máximo, mínimo, cierre, y volumen negociado. Son la materia prima de todos los indicadores técnicos. El `MarketFeed` descarga datos OHLCV vía ccxt.

**Ornstein-Uhlenbeck (Proceso de)**
Proceso estocástico con reversión a la media, descrito originalmente por Uhlenbeck y Ornstein (1930) para modelar la velocidad de partículas en movimiento browniano. En finanzas, se usa para modelar activos que exhiben reversión a la media. Es la base teórica de la estrategia `MeanReversion`.

### P

**Paper Trading (Trading simulado)**
Modo de operación donde las órdenes se simulan sin ejecutarse en el mercado real. Permite probar estrategias sin arriesgar capital. El sistema opera en modo paper durante toda su fase de validación.

**Perpetual (Contrato perpetuo)**
Tipo de contrato de futuros sin fecha de vencimiento, mantenido indefinidamente sujeto a pagos periódicos de funding rate. Dominante en el mercado de criptomonedas.

**PnL (Profit and Loss)**
Ganancia o pérdida de una posición o del portafolio total. Se expresa en términos absolutos ($) o porcentuales (%). PnL no realizado: posiciones abiertas. PnL realizado: posiciones cerradas.

**Position Sizing (Dimensionamiento de posición)**
Proceso de determinar cuánto capital asignar a cada trade. En el sistema, combina el Criterio de Kelly con límites del `RiskManager` para calcular tamaños de posición que optimizan crecimiento sin exceder el riesgo máximo permitido.

**Profit Factor (Factor de beneficio)**
Ratio entre ganancias brutas y pérdidas brutas. Un PF > 1 indica sistema rentable; PF = 1 indica break-even; PF < 1 indica sistema perdedor. Uno de los cuatro criterios de graduación a producción.

**Pub/Sub (Publish/Subscribe)**
Patrón de comunicación donde los emisores (publishers) envían mensajes a canales sin conocer a los receptores (subscribers), y viceversa. En el sistema, Redis implementa Pub/Sub para comunicación entre agentes.

**Pydantic**
Librería de Python para validación de datos mediante anotaciones de tipo. Usada extensamente en el sistema para definir modelos de datos de señales, trades, y configuración, garantizando integridad de datos en toda la pipeline.

### R

**R:R Ratio (Risk:Reward Ratio)**
Relación entre el riesgo asumido (distancia al stop loss) y la recompensa potencial (distancia al take profit). Un R:R de 1:2 significa arriesgar $1 para potencialmente ganar $2. El sistema configura R:R mínimos por estrategia.

**Redis**
Base de datos en memoria de alto rendimiento, usada como broker de mensajes (Pub/Sub) para comunicación entre agentes y como caché para datos de mercado que se consultan frecuentemente. Su baja latencia es crítica para la coordinación en tiempo real.

**Resistencia**
Nivel de precio donde históricamente se concentra presión vendedora, dificultando que el precio suba más allá. Complemento de soporte. Las rupturas de resistencia generan señales de breakout.

**RSI (Relative Strength Index)**
Oscilador de momentum desarrollado por Wilder (1978) que mide la velocidad y magnitud de cambios de precio en una escala de 0 a 100. RSI > 70 indica sobrecompra; RSI < 30 indica sobreventa. Usado como filtro de confirmación en las tres estrategias del sistema.

### S

**Sharpe Ratio (Ratio de Sharpe)**
Medida de rendimiento ajustado por riesgo, desarrollada por William Sharpe (1966):

$$S = \frac{R_p - R_f}{\sigma_p}$$

Donde $R_p$ es el retorno del portafolio, $R_f$ es la tasa libre de riesgo, y $\sigma_p$ es la desviación estándar de los retornos. Un Sharpe > 1 es bueno; > 2 es excelente. Limitación: penaliza igualmente la volatilidad al alza y a la baja.

**Slippage (Deslizamiento)**
Diferencia entre el precio esperado de ejecución y el precio real obtenido. Ocurre por latencia, baja liquidez, o alta volatilidad. El paper trading no simula slippage, lo que produce resultados artificialmente optimistas.

**Sortino Ratio (Ratio de Sortino)**
Variante del Sharpe ratio propuesta por Sortino y van der Meer (1991) que solo penaliza la volatilidad a la baja (downside deviation), no la volatilidad total:

$$\text{Sortino} = \frac{R_p - R_f}{\sigma_d}$$

Donde $\sigma_d$ es la desviación estándar de los retornos negativos. Más apropiado para evaluar estrategias de trading porque no castiga ganancias volátiles.

**Soporte**
Nivel de precio donde históricamente se concentra presión compradora, impidiendo que el precio baje más. Complemento de resistencia.

**Spot (Mercado al contado)**
Mercado donde los activos se compran y venden para entrega inmediata, al contrario de futuros donde la entrega es diferida. Precios spot son la referencia base para derivados.

**Stop Loss**
Orden que cierra automáticamente una posición cuando el precio alcanza un nivel de pérdida predefinido. Mecanismo fundamental de gestión de riesgo. En el sistema, los niveles de stop loss se calculan dinámicamente usando múltiplos de ATR.

**Streamlit**
Framework de Python para crear aplicaciones web interactivas con código mínimo. Usado para construir el dashboard de monitoreo del agente de trading.

**Supabase**
Plataforma backend-as-a-service basada en PostgreSQL. Usada en el sistema para almacenamiento persistente de trades, señales, y métricas de rendimiento.

**Systemd**
Sistema de init y gestor de servicios de Linux. El agente de trading se ejecuta como servicio systemd, lo que garantiza arranque automático, reinicio ante fallos, y gestión de logs via journalctl.

### T

**Take Profit (Toma de ganancias)**
Orden que cierra automáticamente una posición cuando el precio alcanza un nivel de ganancia predefinido. Complemento del stop loss. En el sistema, se calcula como múltiplo del riesgo (distancia al stop loss × ratio R:R).

**Trailing Stop (Stop dinámico)**
Stop loss que se ajusta automáticamente a medida que el precio se mueve a favor de la posición, "siguiendo" al precio a una distancia fija o basada en ATR. Permite capturar ganancias mayores en tendencias fuertes sin arriesgar toda la ganancia acumulada.

**Trend Following (Seguimiento de tendencia)**
Filosofía de trading que busca identificar y seguir tendencias establecidas, operando en la dirección del movimiento predominante. Base de la estrategia `TrendMomentum`. Funciona mejor en mercados con tendencia definida; peor en mercados laterales.

### V

**Volume (Volumen)**
Cantidad de activo negociado en un período. El volumen confirma movimientos de precio: breakouts con alto volumen son más confiables que breakouts con bajo volumen. Dato incluido en cada vela OHLCV.

**VWAP (Volume Weighted Average Price)**
Precio promedio ponderado por volumen durante un período. Indica el precio "justo" del mercado considerando dónde se concentró la mayor actividad. Instituciones lo usan como benchmark para evaluar calidad de ejecución de órdenes.

### W

**Win Rate (Tasa de acierto)**
Porcentaje de trades cerrados con ganancia sobre el total de trades cerrados. Un win rate del 55% significa que 55 de cada 100 trades son ganadores. Es uno de los cuatro criterios de graduación a producción del sistema. Importante: un win rate alto no garantiza rentabilidad si las pérdidas promedio son mayores que las ganancias promedio.

---

> **Nota**: Los términos en inglés se mantienen cuando son de uso estándar en la industria del trading (stop loss, take profit, drawdown, etc.), ya que su traducción al español no es de uso común entre traders hispanohablantes.
